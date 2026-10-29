"""#148 end to end in CI: the real ``SdkModelClient`` on the fake Claude Code CLI, the real
orchestrator loop and guard, the three kick tools, the fake AbletonOSC server.

Request 1 "drei trockene, dunkle Kicks für 136 BPM" -> generate_kick (3) -> answer.
Request 2 -> list_tracks -> import_sample (confirm) -> answer.

Neither fake is evidence for Claude or Live behaviour (fake_cli.py, fake_abletonosc.py).
"""

from __future__ import annotations

import asyncio
import io
import time

import pytest
from fake_cli import PREFIX, FakeCLI, FakeCLIFactory
from kick_helpers import (  # noqa: F401 - fake_fixture is a pytest fixture
    FAST_KICK,
    ProjectCheckDouble,
    fake_fixture,
    make_session,
    toolbox,
    writes_sent,
)
from kick_helpers import RecordingApprover as Approver
from orch_helpers import (  # noqa: F401 - *_fixture are pytest fixtures (see orch_helpers)
    clock_fixture,
    events_fixture,
    make_guard_fixture,
)
from test_sdk_client import make_client, model_permits, no_real_cli  # noqa: F401

from guard import Limit
from orchestrator.chat import TerminalApprover, main
from orchestrator.kick_tools import KickSession
from orchestrator.loop import Orchestrator, tools_sentence
from orchestrator.tools import Plan, Toolbox

REQUEST_1 = "drei trockene, dunkle Kicks für 136 BPM"
DRY_DARK = {**FAST_KICK, "variants": 3, "pitch_end_hz": 42.0, "tone": -0.6,
            "click_level": 0.1}


def use(tid, name, args):
    return {"id": tid, "name": PREFIX + name, "input": args}


@pytest.fixture(name="clients")
def clients_fixture():
    made = []
    yield made
    for c in made:
        c.close()


def scripts():
    return (
        {"total_cost_usd": 0.05, "turns": [
            {"text": "Ich rendere drei Kicks. ", "tool_uses": [use("t1", "generate_kick",
                                                                  DRY_DARK)]},
            {"text": "Fertig: kick-1, kick-2, kick-3."}]},
        {"total_cost_usd": 0.05, "turns": [
            {"tool_uses": [use("t2", "list_tracks", {})]},
            {"tool_uses": [use("t3", "import_sample", {"sample_id": "kick-2",
                                                        "track_index": 0})]},
            {"text": "kick-2 liegt jetzt in Spur 1-Kick."}]},
    )


def test_request_three_kicks_then_one_import(tmp_path, make_guard, events, clients, fake):
    session = make_session(tmp_path, fake)
    factory = FakeCLIFactory(*scripts())
    client = make_client(clients, factory)
    approver = Approver(True)
    orch = Orchestrator(make_guard(), client, toolbox(session), profile="p",
                        approver=approver, context=session.context)

    first = orch.handle(REQUEST_1)
    assert first.success, first.message_de
    assert session.sample_ids() == ("kick-1", "kick-2", "kick-3")
    assert len(list(session.kick_folder.iterdir())) == 6
    assert writes_sent(fake) == []
    assert factory.made[0].prompts == [REQUEST_1]

    second = orch.handle("Importiere kick-2 auf Spur 1")
    assert second.success, second.message_de
    path = session.entry("kick-2").path
    assert writes_sent(fake) == [("/live/clip_slot/create_audio_clip", (0, 0, path))]
    assert [a[0] for a in approver.asked] == ["import_sample"]
    assert approver.asked[0][2]["track_name"] == "1-Kick"
    # the session's kicks and the tool list reach the model in request 2's system prompt
    system = factory.options[1].system_prompt
    assert "kick-2" in system and tools_sentence(
        ("generate_kick", "list_tracks", "import_sample")) in system
    assert "kick-1" not in factory.options[0].system_prompt
    # every CLI model call had a guard permit; nothing ran past the guard
    assert sum(c.model_calls for c in factory.made) == model_permits(events) == 5
    hooks = [h for c in factory.made for h in c.events("hook")]
    assert [h[2] for h in hooks] == ["allow"] * 3
    assert [c.events("builtin_executed") for c in factory.made] == [[], []]


def test_declined_import_is_not_a_success(tmp_path, make_guard, events, clients, fake):
    session = make_session(tmp_path, fake)
    factory = FakeCLIFactory(*scripts())
    orch = Orchestrator(make_guard(), make_client(clients, factory), toolbox(session),
                        profile="p", approver=Approver(False), context=session.context)
    assert orch.handle(REQUEST_1).success
    out = orch.handle("Importiere kick-2")
    assert out.success is False and "Werkzeug import_sample" in out.open
    assert writes_sent(fake) == []
    [deny] = [h for h in factory.made[1].events("hook") if h[3] == "t3"]
    assert deny[2] == "deny"


def test_live_write_budget_stops_the_third_import(tmp_path, make_guard, events, clients, fake):
    session = make_session(tmp_path, fake)
    fake.num_scenes = 8
    for t in fake.tracks:
        t["slots"] = [None] * 8 if t.get("audio") else t.get("slots")
    turns = [{"tool_uses": [use(f"t{i}", "import_sample",
                                {"sample_id": "kick-1", "track_index": 0, "slot_index": i})]}
             for i in range(3)] + [{"text": "never"}]
    factory = FakeCLIFactory(scripts()[0], {"turns": turns})
    orch = Orchestrator(make_guard(), make_client(clients, factory), toolbox(session),
                        profile="p", approver=Approver(True), context=session.context)
    assert orch.handle(REQUEST_1).success
    out = orch.handle("drei Importe")
    assert out.success is False and out.stop_reason is Limit.LIVE_WRITES
    assert len(writes_sent(fake)) == 2  # TEST_POLICY max_live_writes = 2
    cli = factory.made[1]
    assert cli.model_calls == 3 and cli.events("mcp_call") == [
        e for e in cli.events("mcp_call") if e[2]["slot_index"] in (0, 1)]


class CappedHookCLI(FakeCLI):
    """A CLI that ignores the client's 7-day hook timeout and uses CAP_S instead: what #83 V10
    checks for (not verified). On expiry it blocks the call and makes the next model call."""

    CAP_S = 0.3

    async def _run_tool(self, use):
        self.hook_matchers = [(m, ids, self.CAP_S) for m, ids, _ in self.hook_matchers]
        return await super()._run_tool(use)


class CappedFactory(FakeCLIFactory):
    def __call__(self, options):
        cli = CappedHookCLI(self.scripts[min(len(self.made), len(self.scripts) - 1)], options)
        self.made.append(cli)
        self.options.append(options)
        return cli


@pytest.mark.parametrize("decide_s", [0.0, 0.8])
def test_cli_hook_timeout_never_leads_to_a_live_write(tmp_path, make_guard, events, clients,
                                                      fake, decide_s):
    """#83 V10 handled without the experiment: if the CLI's hook timeout fired while the user
    decides, the CLI goes on without the guard; then the import must not run."""
    session = make_session(tmp_path, fake)
    factory = CappedFactory(*scripts())
    approver = Approver(True, during=lambda: time.sleep(decide_s))
    orch = Orchestrator(make_guard(), make_client(clients, factory), toolbox(session),
                        profile="p", approver=approver, context=session.context)
    assert orch.handle(REQUEST_1).success
    out = orch.handle("Importiere kick-2")
    cli = factory.made[1]
    if decide_s == 0.0:
        assert out.success, out.message_de
        assert len(writes_sent(fake)) == 1 and cli.events("hook_timeout") == []
    else:
        assert cli.events("hook_timeout") != []  # the CLI really gave up and went on
        assert out.success is False
        assert writes_sent(fake) == []  # no Live write after the CLI moved on


def test_cancelled_hook_alone_fails_the_request(tmp_path, make_guard, events, clients, fake):
    """The CLI gives up on the hook but makes no further model call (it hangs): the cancel
    itself must mark the session (mutant S3), so the request ends as a protocol error at
    once, not as a timeout, and nothing is written."""
    session = make_session(tmp_path, fake)
    script = {"turns": [{"tool_uses": [use("t3", "import_sample", {"sample_id": "kick-1",
                                                                   "track_index": 0})]},
                        {"hang": True}]}
    factory = CappedFactory(scripts()[0], script)
    approver = Approver(True, during=lambda: time.sleep(0.8))
    orch = Orchestrator(make_guard(), make_client(clients, factory), toolbox(session),
                        profile="p", approver=approver, context=session.context)
    assert orch.handle(REQUEST_1).success
    started = time.monotonic()
    out = orch.handle("Importiere kick-1")
    assert factory.made[1].events("hook_timeout") != []
    assert out.success is False and out.error == "model_protocol", out.message_de
    assert time.monotonic() - started < 10
    assert writes_sent(fake) == []


class ExtraCallCLI(FakeCLI):
    """While its hook waits, this CLI makes a model call on its own (a new message id) without
    cancelling the hook: the client must notice it from the stream (mutant S4)."""

    async def _run_tool(self, use):
        if use["name"].endswith("import_sample"):
            loop = asyncio.get_running_loop()
            loop.call_later(0.1, self.out.put_nowait,
                            self._assistant("msg_unpermitted", [{"type": "text", "text": "!"}]))
        return await super()._run_tool(use)


def test_model_call_while_the_hook_waits_blocks_the_write(tmp_path, make_guard, events, clients,
                                                          fake):
    session = make_session(tmp_path, fake)

    class Factory(FakeCLIFactory):
        def __call__(self, options):
            cli = ExtraCallCLI(self.scripts[min(len(self.made), len(self.scripts) - 1)], options)
            self.made.append(cli)
            self.options.append(options)
            return cli

    factory = Factory(*scripts())
    approver = Approver(True, during=lambda: time.sleep(0.4))
    orch = Orchestrator(make_guard(), make_client(clients, factory), toolbox(session),
                        profile="p", approver=approver, context=session.context)
    assert orch.handle(REQUEST_1).success
    out = orch.handle("Importiere kick-2")
    assert factory.made[1].events("hook_timeout") == []  # the hook was never given up
    assert out.success is False
    assert writes_sent(fake) == []


def test_system_prompt_names_exactly_the_registered_tools(tmp_path, make_guard, clients, fake):
    """#163: the model must not offer what does not exist."""
    session = make_session(tmp_path, fake)
    for tools, names in (([], ()), (session.tools(), ("generate_kick", "list_tracks",
                                                      "import_sample"))):
        factory = FakeCLIFactory({"turns": [{"text": "x"}]})
        box = Toolbox(tools, capability_gate=session.gate())
        Orchestrator(make_guard(), make_client(clients, factory), box, profile="p").handle("x")
        system = factory.options[0].system_prompt
        assert tools_sentence(names) in system
        mentioned = {n for n in ("generate_kick", "list_tracks", "import_sample", "echo")
                     if n in system}
        assert mentioned == set(names)
    assert "Nothing else is available" in tools_sentence(("a",))
    assert "no tools" in tools_sentence(())


# --- terminal chat --------------------------------------------------------------------------


def test_terminal_approver_shows_track_and_slot(tmp_path):
    out = io.StringIO()
    answers = iter(["j"])
    approver = TerminalApprover(lambda _p: next(answers), out)
    tool = {t.name: t for t in make_session(tmp_path).tools()}["import_sample"]
    plan = Plan({"sample_id": "kick-2", "file": "kick_s1_v1.wav", "track_index": 0,
                 "track_name": "1-Kick", "slot_index": 3, "scene_count": 8})
    assert approver.confirm(tool, {"sample_id": "kick-2", "track_index": 0}, plan) is True
    text = out.getvalue()
    assert "kick_s1_v1.wav" in text and '"1-Kick"' in text and "Zelle (Szene) 3" in text
    assert "40 s" in text


def test_chat_without_project_has_no_tools(make_guard):
    out = io.StringIO()
    from orchestrator.fake_model import FakeModel

    model = FakeModel([{"text": "Hallo"}])
    lines = iter(["hi", ""])
    assert main(["--profile", "p"], read=lambda _p: next(lines), out=out, guard=make_guard(),
                model=model) == 0
    assert "keine Kick-Werkzeuge" in out.getvalue()
    assert model.requests[0].tools == ()


def test_chat_with_project_registers_the_three_tools(tmp_path, make_guard):
    from orchestrator.fake_model import FakeModel

    out = io.StringIO()
    model = FakeModel([{"text": "ok"}])
    lines = iter(["hi", ""])

    def factory(project):
        return make_session(tmp_path, project=None)

    code = main(["--profile", "p", "--project", str(tmp_path)], read=lambda _p: next(lines),
                out=out, guard=make_guard(), model=model, session_factory=factory)
    assert code == 0, out.getvalue()
    assert [t.name for t in model.requests[0].tools] == ["generate_kick", "list_tracks",
                                                         "import_sample"]
    assert "Kicks gehen nach" in out.getvalue()


def test_chat_refuses_a_bad_project(tmp_path, make_guard):
    from orchestrator.fake_model import FakeModel

    out = io.StringIO()

    def refusing(project):
        return KickSession(project, project_check=ProjectCheckDouble())

    code = main(["--profile", "p", "--project", str(tmp_path / "missing")],
                read=lambda _p: "", out=out, guard=make_guard(), model=FakeModel([{"text": "x"}]),
                session_factory=refusing)
    assert code == 2 and "project folder refused" in out.getvalue()


def test_chat_without_the_shared_check_runs_without_tools(tmp_path, make_guard, monkeypatch):
    """Until #149 is merged: --project gives a clear note, the chat still works (D-002)."""
    import orchestrator.kick_tools as mod
    from orchestrator.fake_model import FakeModel

    monkeypatch.setattr(mod, "load_project_check", lambda: None)
    out = io.StringIO()
    model = FakeModel([{"text": "Hallo"}])
    lines = iter(["hi", ""])
    code = main(["--profile", "p", "--project", str(tmp_path)], read=lambda _p: next(lines),
                out=out, guard=make_guard(), model=model)
    assert code == 0
    assert "noch nicht verfügbar" in out.getvalue() and "#149" in out.getvalue()
    assert model.requests[0].tools == ()
