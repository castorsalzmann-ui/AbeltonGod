"""Agent SDK client (#106): the real SDK (``ClaudeSDKClient``, ``Query``, hook dispatch, the
in-process MCP server and its schema check) runs on top of ``FakeCLI`` - a scripted CLI and
model. No process is started and no network is used: ``SubprocessCLITransport.connect`` is
replaced by a failure for every test in this module.

Guard-wiring invariants checked end to end with the real orchestrator loop and a real guard:

- every tool the fake CLI ran through MCP with success is exactly one ``Toolbox`` handler run
  with the same arguments, after ``before_tool``;
- the fake CLI never runs a built-in and never makes more model calls than the guard permitted;
- a stopped or failed request is never a success.

Expected numbers (limits, costs) are written here, not taken from the code under test.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import random

import pytest
from claude_agent_sdk import CLINotFoundError, ResultError
from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport
from fake_cli import PREFIX, FakeCLIFactory
from orch_helpers import (  # noqa: F401 - *_fixture are pytest fixtures (see orch_helpers)
    Events,
    clock_fixture,
    echo_tool,
    events_fixture,
    make_guard_fixture,
)

from guard import Limit
from orchestrator.auth import AuthMode, AuthSettings
from orchestrator.loop import DEFAULT_SYSTEM_PROMPT, Orchestrator
from orchestrator.model_client import (
    ModelLimitReached,
    ModelProtocolError,
    ModelUnavailable,
)
from orchestrator.sdk_client import (
    BUILTIN_PREFIX,
    SUBAGENT_PREFIX,
    TOOL_PREFIX,
    SdkModelClient,
    per_call_estimate,
)
from orchestrator.tools import Tool, Toolbox, ToolOutput

ECHO = PREFIX + "echo"
EST = 0.1  # per-call reservation used in these tests


@pytest.fixture(autouse=True)
def no_real_cli(monkeypatch):
    async def refuse(self):
        raise AssertionError("a test tried to start the real Claude Code CLI")

    monkeypatch.setattr(SubprocessCLITransport, "connect", refuse)


@pytest.fixture(name="clients")
def clients_fixture():
    made: list[SdkModelClient] = []
    yield made
    for client in made:
        client.close()


def settings(mode: AuthMode = AuthMode.SUBSCRIPTION) -> AuthSettings:
    return AuthSettings(mode, "claude-opus-5-5", api_key_present=mode is AuthMode.API_KEY)


def make_client(clients, factory, mode=AuthMode.SUBSCRIPTION, **kwargs) -> SdkModelClient:
    client = SdkModelClient(settings(mode), per_call_estimate_usd=EST,
                            transport_factory=factory, **kwargs)
    clients.append(client)
    return client


def run(guard, client, tools, text="drei Kicks"):
    return Orchestrator(guard, client, Toolbox(tools), profile="p").handle(text)


def use(tid, args, name=ECHO, **extra):
    return {"id": tid, "name": name, "input": args, **extra}


def model_permits(events: Events) -> int:
    return events.kinds().count("before_model")


# --- closed tool surface and limits handed to the SDK -------------------------------------


def test_session_options_close_the_tool_surface(make_guard, events, clients):
    factory = FakeCLIFactory({"turns": [{"text": "Hallo"}], "total_cost_usd": 0.01})
    out = run(make_guard(), make_client(clients, factory), [echo_tool(events)])
    assert out.success, out.message_de
    opts = factory.options[0]
    assert opts.tools == []
    assert opts.strict_mcp_config is True and opts.setting_sources == []
    assert opts.permission_mode == "dontAsk"
    assert opts.allowed_tools == [ECHO]
    assert {"Agent", "Task", "Bash", "ToolSearch", "WebFetch"} <= set(opts.disallowed_tools)
    assert not any(t.startswith("mcp__") for t in opts.disallowed_tools)
    assert opts.env["ENABLE_TOOL_SEARCH"] == "false"
    assert opts.env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "1000"  # TEST_POLICY max_output_tokens
    assert "ANTHROPIC_API_KEY" not in opts.env
    assert opts.agents is None and opts.plugins == []
    assert opts.model == "claude-opus-5-5"
    assert opts.system_prompt == DEFAULT_SYSTEM_PROMPT
    assert opts.max_turns == 5  # TEST_POLICY max_model_calls, nothing used yet
    assert 0 < opts.max_budget_usd <= 1.0
    [matcher] = opts.hooks["PreToolUse"]
    assert matcher.matcher is None and len(matcher.hooks) == 1  # catch-all
    assert set(opts.hooks) == {"PreToolUse"}
    assert list(opts.mcp_servers) == ["abeltongod"]


def test_cli_command_gets_the_closed_surface_and_real_limits(make_guard, events, clients):
    factory = FakeCLIFactory({"turns": [{"text": "x"}]})
    run(make_guard(), make_client(clients, factory), [echo_tool(events)])
    opts = dataclasses.replace(factory.options[0], cli_path="fake-claude")
    cmd = SubprocessCLITransport(prompt="", options=opts)._build_command()
    assert cmd[cmd.index("--max-turns") + 1] == "5"
    assert float(cmd[cmd.index("--max-budget-usd") + 1]) > 0
    assert cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert "--strict-mcp-config" in cmd and "--setting-sources=" in cmd
    assert cmd[cmd.index("--allowedTools") + 1] == ECHO


@pytest.mark.parametrize(
    "limits",
    [{"max_turns": 0, "max_budget_usd": 1.0}, {"max_turns": -1, "max_budget_usd": 1.0},
     {"max_turns": True, "max_budget_usd": 1.0}, {"max_turns": 2.0, "max_budget_usd": 1.0},
     {"max_turns": None, "max_budget_usd": 1.0}, {"max_turns": 3, "max_budget_usd": 0.0},
     {"max_turns": 3, "max_budget_usd": -0.1}, {"max_turns": 3, "max_budget_usd": float("nan")},
     {"max_turns": 3}, {}],
)
def test_sdk_never_starts_with_a_disabling_limit(limits, clients):
    from orchestrator.model_client import ModelRequest, UserMessage

    factory = FakeCLIFactory({"turns": [{"text": "x"}]})
    client = make_client(clients, factory)
    request = ModelRequest("s", (UserMessage("x"),), (), 100, 10.0, limits)
    with pytest.raises(ModelUnavailable) as err:
        client.complete(request)
    assert err.value.request_sent is False
    assert factory.made == []  # no transport, no CLI


def test_max_turns_follows_the_guards_headroom(make_guard, events, clients):
    rng = random.Random(106)
    for _ in range(12):
        limit = rng.randint(1, 9)
        factory = FakeCLIFactory({"turns": [{"text": "x"}]})
        run(make_guard(max_model_calls=limit), make_client(clients, factory), [])
        assert factory.options[0].max_turns == limit


# --- end-to-end guard wiring ---------------------------------------------------------------


def test_tool_call_runs_once_through_the_guard(make_guard, events, clients):
    calls: list = []
    factory = FakeCLIFactory({"total_cost_usd": 0.15, "turns": [
        {"text": "Ich rendere. ", "tool_uses": [use("t1", {"n": 3})]},
        {"text": "Fertig."}]})
    guard = make_guard()
    out = run(guard, make_client(clients, factory), [echo_tool(events, calls)])
    assert out.success and out.reply == "Fertig."
    cli = factory.cli
    assert calls == [{"n": 3}]
    [mcp] = cli.events("mcp_call")
    assert mcp[2] == {"n": 3} and mcp[3] is False
    assert json.loads(mcp[4].split("\n")[0]) == {"echo": {"n": 3}}  # + guard note (warn)
    assert cli.events("hook") == [("hook", ECHO, "allow", "t1")]
    assert cli.model_calls == 2 == model_permits(events)
    k = events.kinds()
    assert k.index("before_tool") < k.index("handler") < k.index("after_tool")
    # the CLI's second model call comes only after the guard's second permit
    assert k.count("before_model") == 2
    assert guard.session_spent_usd == pytest.approx(0.15)  # 0.1 reserved + 0.05 rest


def test_invalid_arguments_are_denied_and_never_reach_a_handler(make_guard, events, clients):
    calls: list = []
    factory = FakeCLIFactory({"turns": [
        {"tool_uses": [use("t1", {"n": 101})]},
        {"text": "Ging nicht."}]})
    out = run(make_guard(), make_client(clients, factory), [echo_tool(events, calls)])
    assert out.success is False  # the failed tool stays open
    assert calls == [] and factory.cli.events("mcp_call") == []
    [hook] = factory.cli.events("hook")
    assert hook[2] == "deny"
    assert events.kinds().count("before_tool") == 1


@pytest.mark.parametrize("name", ["Bash", "Write", "WebFetch", "mcp__other__echo", ""])
def test_builtin_or_foreign_tool_is_counted_and_denied(name, make_guard, events, clients):
    factory = FakeCLIFactory({"turns": [{"tool_uses": [use("t1", {"n": 1}, name=name)]},
                                        {"text": "ok"}]})
    out = run(make_guard(), make_client(clients, factory), [echo_tool(events)])
    assert out.success is False
    assert factory.cli.events("builtin_executed") == [] and factory.cli.events("mcp_call") == []
    assert [d for _, _, d, _ in factory.cli.events("hook")] == ["deny"]
    assert ("before_tool", BUILTIN_PREFIX + (name or "<unnamed>")) in events.items


def test_builtin_is_denied_even_when_a_local_tool_has_its_name(make_guard, events, clients):
    ran: list = []

    def handler(args):
        ran.append(args)
        return ToolOutput({"ok": True}, files_written=0, live_writes=0)

    bash = Tool("Bash", "local tool that happens to be called Bash",
                {"type": "object", "properties": {}}, handler)
    factory = FakeCLIFactory({"turns": [{"tool_uses": [use("t1", {}, name="Bash")]},
                                        {"text": "ok"}]})
    run(make_guard(), make_client(clients, factory), [bash])
    assert ran == [] and factory.cli.events("builtin_executed") == []


def test_subagent_tool_call_is_denied(make_guard, events, clients):
    calls: list = []
    factory = FakeCLIFactory({"turns": [
        {"tool_uses": [use("t1", {"n": 1}, agent_id="agent-7")]}, {"text": "ok"}]})
    out = run(make_guard(), make_client(clients, factory), [echo_tool(events, calls)])
    assert out.success is False and calls == []
    assert factory.cli.events("mcp_call") == []
    assert ("before_tool", SUBAGENT_PREFIX + ECHO) in events.items


def test_subagent_model_call_is_refused(make_guard, events, clients):
    factory = FakeCLIFactory({"turns": [{"raw": {
        "type": "assistant", "session_id": "s1", "parent_tool_use_id": "toolu_agent",
        "message": {"id": "sub1", "model": "x", "content": [{"type": "text", "text": "hi"}]}}},
        {"result": {"subtype": "success", "is_error": False, "result": "fertig"}}]})
    out = run(make_guard(), make_client(clients, factory), [])
    assert out.success is False and out.error == "model_protocol"


@pytest.mark.parametrize("split", [False, True])
def test_parallel_calls_of_one_answer_cost_one_model_call(split, make_guard, events, clients):
    calls: list = []
    factory = FakeCLIFactory({"turns": [
        {"text": "zwei", "split": split,
         "tool_uses": [use("t1", {"n": 1}), use("t2", {"n": 2})]},
        {"text": "fertig"}]})
    out = run(make_guard(), make_client(clients, factory), [echo_tool(events, calls)])
    assert out.success, out.message_de
    assert calls == [{"n": 1}, {"n": 2}]
    assert factory.cli.model_calls == 2 == model_permits(events)


def test_guard_stop_on_tool_calls_ends_the_session_before_the_next_model_call(
    make_guard, events, clients
):
    calls: list = []
    factory = FakeCLIFactory({"turns": [
        {"tool_uses": [use("t1", {"n": 1}), use("t2", {"n": 2})]}, {"text": "never"}]})
    out = run(make_guard(max_tool_calls=1), make_client(clients, factory),
              [echo_tool(events, calls)])
    assert out.success is False and out.stop_reason is Limit.TOOL_CALLS
    cli = factory.cli
    assert calls == [{"n": 1}]
    assert cli.model_calls == 1 and cli.events("mcp_call") == []
    assert cli.closed


def test_tool_loop_is_stopped_and_the_cli_makes_no_unpermitted_call(make_guard, events, clients):
    turns = [{"id": f"m{i}", "tool_uses": [use(f"t{i}", {"n": i})]} for i in range(20)]
    factory = FakeCLIFactory({"turns": turns})
    out = run(make_guard(), make_client(clients, factory), [echo_tool(events)])
    assert out.success is False and out.stop_reason is Limit.MODEL_CALLS
    assert factory.cli.model_calls == model_permits(events) == 5
    assert "Offen" in out.message_de and out.open  # what is still open is reported


def test_identical_tool_loop_is_stopped(make_guard, events, clients):
    turns = [{"id": f"m{i}", "tool_uses": [use(f"t{i}", {"n": 7})]} for i in range(20)]
    factory = FakeCLIFactory({"turns": turns})
    out = run(make_guard(max_model_calls=10, max_tool_calls=10), make_client(clients, factory),
              [echo_tool(events)])
    assert out.success is False and out.stop_reason is Limit.LOOP
    assert factory.cli.model_calls <= model_permits(events)


def test_relay_without_hook_approval_fails_closed(make_guard, events, clients):
    """A CLI that skipped the hook: the relay has no guard-approved result."""
    calls: list = []
    factory = FakeCLIFactory({"turns": [
        {"tool_uses": [use("t1", {"n": 1}, skip_hooks=True)]}, {"text": "ok"}]})
    out = run(make_guard(), make_client(clients, factory), [echo_tool(events, calls)])
    assert out.success is False and out.error == "model_protocol"
    assert calls == []
    [mcp] = factory.cli.events("mcp_call")
    assert mcp[3] is True and "not_permitted" in mcp[4]


def test_relay_violation_blocks_a_success_result(make_guard, events, clients):
    """No second model call to give it away: the result frame follows at once."""
    factory = FakeCLIFactory({"turns": [
        {"tool_uses": [use("t1", {"n": 1}, skip_hooks=True)]},
        {"result": {"subtype": "success", "is_error": False, "result": "fertig"}}]})
    out = run(make_guard(), make_client(clients, factory), [echo_tool(events)])
    assert out.success is False and out.error == "model_protocol"


def test_second_model_call_inside_one_permit_is_a_protocol_error(make_guard, events, clients):
    """A built-in the hook never saw: the CLI goes on to the next model call by itself."""
    factory = FakeCLIFactory({"turns": [
        {"id": "m1", "tool_uses": [use("t1", {}, name="Bash", skip_hooks=True)]},
        {"id": "m2", "text": "unpermitted"}]})
    out = run(make_guard(), make_client(clients, factory), [echo_tool(events)])
    assert out.success is False and out.error == "model_protocol"
    assert "did not permit" in out.message_de


def test_same_message_id_twice_is_one_model_call(make_guard, events, clients):
    factory = FakeCLIFactory({"turns": [
        {"id": "m1", "split": True, "text": "a", "tool_uses": [use("t1", {"n": 1})]},
        {"id": "m2", "text": "b"}]})
    out = run(make_guard(), make_client(clients, factory), [echo_tool(events)])
    assert out.success, out.message_de


# --- auth and session checks ---------------------------------------------------------------


@pytest.mark.parametrize("source", ["ANTHROPIC_API_KEY", "apiKeyHelper", "/login managed key",
                                    None])
def test_subscription_mode_refuses_another_credential_source(source, make_guard, events,
                                                             clients):
    calls: list = []
    factory = FakeCLIFactory({"api_key_source": source,
                              "turns": [{"tool_uses": [use("t1", {"n": 1})]}]})
    out = run(make_guard(), make_client(clients, factory), [echo_tool(events, calls)])
    assert out.success is False and out.error == "model_unavailable"
    assert "auth" in out.message_de and calls == []
    assert factory.cli.closed and factory.cli.events("mcp_call") == []


def test_api_key_mode_passes_the_key_and_expects_its_source(make_guard, events, clients):
    factory = FakeCLIFactory({"api_key_source": "ANTHROPIC_API_KEY", "turns": [{"text": "hi"}]})
    client = make_client(clients, factory, mode=AuthMode.API_KEY,
                         environ={"ANTHROPIC_API_KEY": " sk-test "}, env_file=None)
    assert run(make_guard(), client, []).success
    assert factory.options[0].env["ANTHROPIC_API_KEY"] == "sk-test"
    assert "sk-test" not in repr(client.settings)

    factory = FakeCLIFactory({"api_key_source": "none", "turns": [{"text": "hi"}]})
    client = make_client(clients, factory, mode=AuthMode.API_KEY,
                         environ={"ANTHROPIC_API_KEY": "sk-test"}, env_file=None)
    assert run(make_guard(), client, []).error == "model_unavailable"


@pytest.mark.parametrize("account", [{"apiKeySource": "ANTHROPIC_API_KEY"},
                                     {"apiProvider": "bedrock"}])
def test_account_mismatch_is_refused_before_the_prompt(account, make_guard, events, clients):
    factory = FakeCLIFactory({"account": account, "turns": [{"text": "hi"}]})
    guard = make_guard()
    out = run(guard, make_client(clients, factory), [])
    assert out.error == "model_unavailable" and "subscription" in out.message_de
    assert factory.cli.prompts == [] and factory.cli.model_calls == 0
    assert guard.session_spent_usd == 0.0  # provably not sent


def test_account_without_key_passes(make_guard, events, clients):
    factory = FakeCLIFactory({"account": {"subscriptionType": "max", "apiProvider": "firstParty"},
                              "turns": [{"text": "hi"}]})
    assert run(make_guard(), make_client(clients, factory), []).success


@pytest.mark.parametrize("tools", [[ECHO, "Bash"], ["ToolSearch"], [ECHO, "mcp__x__y"], "Bash"])
def test_open_tool_surface_is_refused(tools, make_guard, events, clients):
    factory = FakeCLIFactory({"init_tools": tools, "turns": [{"text": "hi"}]})
    out = run(make_guard(), make_client(clients, factory), [echo_tool(events)])
    assert out.success is False and out.error == "model_protocol"


def test_answer_without_init_check_is_refused(make_guard, events, clients):
    factory = FakeCLIFactory({"skip_init": True, "turns": [{"text": "hi"}]})
    out = run(make_guard(), make_client(clients, factory), [])
    assert out.success is False and out.error == "model_protocol"


# --- SDK stop results map to the guard's stop path -----------------------------------------


@pytest.mark.parametrize("then_exit", [False, True])
def test_error_max_turns_becomes_a_guard_stop(then_exit, make_guard, events, clients):
    factory = FakeCLIFactory({"total_cost_usd": 0.3, "turns": [
        {"tool_uses": [use("t1", {"n": 1})]},
        {"result": {"subtype": "error_max_turns", "is_error": True,
                    "errors": ["Reached maximum number of turns (1)"]},
         "then_exit": then_exit}]})
    guard = make_guard()
    out = run(guard, make_client(clients, factory), [echo_tool(events)])
    assert out.success is False and out.stop_reason is Limit.MODEL_CALLS
    assert guard.session_spent_usd == pytest.approx(0.3)


def test_error_max_budget_usd_becomes_a_guard_stop(make_guard, events, clients):
    factory = FakeCLIFactory({"total_cost_usd": 1.3, "turns": [
        {"result": {"subtype": "error_max_budget_usd", "is_error": True}}]})
    out = run(make_guard(), make_client(clients, factory), [])
    assert out.success is False and out.stop_reason is Limit.REQUEST_BUDGET


def test_small_budget_stop_is_still_the_guards_budget_stop(make_guard, events, clients):
    factory = FakeCLIFactory({"total_cost_usd": 0.02, "turns": [
        {"result": {"subtype": "error_max_budget_usd", "is_error": True}}]})
    out = run(make_guard(), make_client(clients, factory), [])
    assert out.success is False and out.stop_reason is Limit.REQUEST_BUDGET


def test_api_error_result_is_unavailable_and_counts_its_cost(make_guard, events, clients):
    factory = FakeCLIFactory({"total_cost_usd": 0.4, "turns": [
        {"result": {"subtype": "success", "is_error": True,
                    "result": "API Error: overloaded", "api_error_status": 529}}]})
    guard = make_guard()
    out = run(guard, make_client(clients, factory), [])
    assert out.error == "model_unavailable" and "overloaded" in out.message_de
    assert guard.session_spent_usd == pytest.approx(0.4)


@pytest.mark.parametrize("turn", [{"assistant_error": "rate_limit"},
                                  {"assistant_error": "authentication_failed"},
                                  {"rate_limit": "rejected"}])
def test_backend_refusals_are_unavailable(turn, make_guard, events, clients):
    factory = FakeCLIFactory({"turns": [turn, {"text": "never"}]})
    out = run(make_guard(), make_client(clients, factory), [])
    assert out.success is False and out.error == "model_unavailable"


def test_rate_limit_warning_is_not_an_error(make_guard, events, clients):
    factory = FakeCLIFactory({"turns": [{"rate_limit": "allowed_warning"}, {"text": "hi"}]})
    assert run(make_guard(), make_client(clients, factory), []).success


def test_result_error_exception_is_mapped(clients):
    from orchestrator.sdk_client import _Session

    client = make_client(clients, FakeCLIFactory({"turns": []}))
    sess = _Session(system="s", allowed_names=frozenset())
    sess.seen_message_ids.add("m1")
    for subtype in ("error_max_turns", "error_max_budget_usd"):
        exc = ResultError("x", data={"subtype": subtype, "total_cost_usd": 0.2})
        mapped = client._map_exception(sess, exc, None)
        assert isinstance(mapped, ModelLimitReached) and mapped.subtype == subtype
        assert mapped.usage.cost_usd == pytest.approx(0.2)
    other = client._map_exception(sess, ResultError("x", data={"subtype": "success"}), None)
    assert isinstance(other, ModelUnavailable)
    from claude_agent_sdk import CLIJSONDecodeError

    bad = client._map_exception(sess, CLIJSONDecodeError("{", ValueError("x")), None)
    assert isinstance(bad, ModelProtocolError)


def test_execution_error_result_is_unavailable(make_guard, events, clients):
    factory = FakeCLIFactory({"turns": [
        {"raw": {"type": "system", "subtype": "status"}},
        {"result": {"subtype": "error_during_execution", "is_error": True, "errors": ["crash"]}}]})
    out = run(make_guard(), make_client(clients, factory), [])
    assert out.error == "model_unavailable" and "crash" in out.message_de


def test_stream_end_without_result_is_unavailable(make_guard, events, clients):
    factory = FakeCLIFactory({"turns": [{"eof": True}]})
    out = run(make_guard(), make_client(clients, factory), [])
    assert out.error == "model_unavailable" and "without a result" in out.message_de


def test_timeout_closes_the_session(clients):
    from orchestrator.model_client import ModelRequest, UserMessage

    factory = FakeCLIFactory({"turns": [{"hang": True}]})
    client = make_client(clients, factory)
    request = ModelRequest("s", (UserMessage("x"),), (), 100, 0.3,
                           {"max_turns": 2, "max_budget_usd": 0.5})
    with pytest.raises(ModelUnavailable) as err:
        client.complete(request)
    assert "timeout" in err.value.detail and err.value.request_sent is True
    assert factory.cli.closed and ("control", "interrupt") in factory.cli.log


def test_guard_timeout_ends_the_request(make_guard, events, clients):
    factory = FakeCLIFactory({"turns": [{"hang": True}]})
    out = run(make_guard(timeout_s=5), make_client(clients, factory), [])
    assert out.success is False and out.error == "model_unavailable"
    assert factory.cli.closed


def test_missing_cli_keeps_the_engine_working(make_guard, events, clients):
    from audio_engine.kick import render_kick
    from audio_engine.presets import load_preset

    class Missing(FakeCLIFactory):
        def __call__(self, options):
            cli = super().__call__(options)

            async def connect():
                raise CLINotFoundError("Claude Code not found")

            cli.connect = connect
            return cli

    guard = make_guard()
    out = run(guard, make_client(clients, Missing({"turns": []})), [])
    assert out.error == "model_unavailable" and "not found" in out.message_de
    assert guard.session_spent_usd == 0.0
    audio, params = render_kick({**load_preset("centre"), "length_ms": 100})
    assert audio.size == round(100 * params["sample_rate"] / 1000)


def test_failed_prompt_write_is_unavailable(make_guard, events, clients):
    class Broken(FakeCLIFactory):
        def __call__(self, options):
            cli = super().__call__(options)
            write = cli.write

            async def failing(data):
                if '"type": "user"' in data or '"type":"user"' in data:
                    raise OSError("pipe closed")
                await write(data)

            cli.write = failing
            return cli

    out = run(make_guard(), make_client(clients, Broken({"turns": [{"text": "x"}]})), [])
    assert out.error == "model_unavailable" and "pipe closed" in out.message_de


# --- cost and tokens -------------------------------------------------------------------------


def test_guard_counts_at_least_the_sdk_total(make_guard, events, clients):
    rng = random.Random(20261029)
    for _ in range(25):
        k = rng.randint(1, 4)  # model calls in the run
        total = round(rng.uniform(0.0, 0.8), 4)
        turns = [{"id": f"m{i}", "tool_uses": [use(f"t{i}", {"n": i})]} for i in range(k - 1)]
        turns.append({"id": "last", "text": "ok"})
        factory = FakeCLIFactory({"total_cost_usd": total, "turns": turns})
        guard = make_guard()
        out = run(guard, make_client(clients, factory), [echo_tool()])
        assert out.success, out.message_de
        expected = max(total, EST * (k - 1))
        assert guard.session_spent_usd == pytest.approx(expected), (k, total)


def test_single_call_reports_exact_tokens(make_guard, events, clients):
    factory = FakeCLIFactory({"total_cost_usd": 0.01, "turns": [
        {"result": {"subtype": "success", "is_error": False, "result": "hi",
                    "usage": {"output_tokens": 1200, "input_tokens": 50}}}]})
    factory.scripts[0]["turns"].insert(0, {"raw": {
        "type": "assistant", "session_id": "s1", "parent_tool_use_id": None,
        "message": {"id": "m1", "model": "x", "content": [{"type": "text", "text": "hi"}]}}})
    out = run(make_guard(), make_client(clients, factory), [])
    assert out.success is False and out.stop_reason is Limit.OUTPUT_TOKENS  # 1200 > 1000


def test_guard_warning_reaches_the_model_with_the_tool_result(make_guard, events, clients):
    factory = FakeCLIFactory({"turns": [{"tool_uses": [use("t1", {"n": 1})]}, {"text": "ok"}]})
    run(make_guard(), make_client(clients, factory), [echo_tool(events)])
    [mcp] = factory.cli.events("mcp_call")
    # unknown per-call tokens count at the cap -> warn level -> the note goes along
    assert "Resource guard" in mcp[4]


# --- hook and relay units --------------------------------------------------------------------


def test_hook_never_answers_when_no_request_is_open(clients):
    """Any answer would let a CLI that is being shut down go on to a model call."""
    client = make_client(clients, FakeCLIFactory({"turns": []}))
    hook = client._pre_tool_use({"tool_name": ECHO, "tool_input": {}}, "t1", {})
    with pytest.raises(TimeoutError):
        asyncio.run(asyncio.wait_for(hook, timeout=0.2))


def test_hook_denies_changed_arguments_and_foreign_names(clients):
    from orchestrator.model_client import ToolCall, ToolResult
    from orchestrator.sdk_client import _Hook, _Session

    client = make_client(clients, FakeCLIFactory({"turns": []}))
    sess = _Session(system="s", allowed_names=frozenset({ECHO}))
    sess.returned["t1"] = ToolCall("t1", "echo", {"n": 1})
    ok = ToolResult("t1", "echo", False, {"echo": {"n": 1}})
    loop = asyncio.new_event_loop()

    def hook(raw, args, agent=None):
        name = raw[len(TOOL_PREFIX):] if raw.startswith(TOOL_PREFIX) else "builtin:" + raw
        return _Hook(loop.create_future(), raw, name, args, agent)

    assert client._decide(sess, "t1", hook(ECHO, {"n": 1}), ok)[
        "hookSpecificOutput"]["permissionDecision"] == "allow"
    for bad in (hook(ECHO, {"n": 2}), hook("echo", {"n": 1}), hook(ECHO, {"n": 1}, "a1")):
        assert client._decide(sess, "t1", bad, ok)[
            "hookSpecificOutput"]["permissionDecision"] == "deny"
    # the raw name alone decides, even if the loop name looks like ours
    for raw in ("echo", "Bash", PREFIX + "other", "mcp__other__echo"):
        bad = _Hook(loop.create_future(), raw, "echo", {"n": 1}, None)
        assert client._decide(sess, "t1", bad, ok)[
            "hookSpecificOutput"]["permissionDecision"] == "deny", raw
    assert client._decide(sess, "t1", hook(ECHO, {"n": 1}), None)["continue_"] is False
    loop.close()


def test_sdk_client_cannot_reach_a_tool_handler():
    """The adapter only gets ToolSpecs: no import of the toolbox, no handler/run access."""
    import ast
    from pathlib import Path

    import orchestrator.sdk_client as mod

    tree = ast.parse(Path(mod.__file__).read_text("utf-8"))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert "orchestrator.tools" not in imported and "orchestrator.chat" not in imported
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not {"handler", "toolbox", "run"} & attrs
    assert not {"Toolbox", "Tool"} & names


@pytest.mark.parametrize("bad", [None, "x", {"tool_name": ECHO}, {"tool_input": {}}])
def test_hook_fails_closed_on_malformed_input(bad, make_guard, events, clients):
    from orchestrator.sdk_client import _Session

    client = make_client(clients, FakeCLIFactory({"turns": []}))
    client._session = _Session(system="s", allowed_names=frozenset({ECHO}))
    out = asyncio.run(client._pre_tool_use(bad, None, {}))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    client._session = None


def test_argument_key_treats_json_numbers_alike():
    from orchestrator.sdk_client import _canon

    assert _canon({"b": 1.0, "a": [2.0, 0.5]}) == _canon({"a": [2, 0.5], "b": 1})
    assert _canon({"n": 1}) != _canon({"n": True}) and _canon({"n": 1.5}) != _canon({"n": 1})


def test_float_round_trip_through_the_cli_still_matches(make_guard, events, clients):
    """updatedInput 1.0 comes back from a JavaScript CLI as 1: still the approved call."""
    calls: list = []
    # t2 reaches the loop from the assistant message (1.0), its hook later says 1
    factory = FakeCLIFactory({"turns": [
        {"tool_uses": [use("t1", {"n": 1}), use("t2", {"n": 2, "gain": 1.0})]},
        {"text": "ok"}]})
    original = factory.__call__

    def make(options):
        cli = original(options)
        run_tool = cli._run_tool

        async def js_like(u):  # what a JavaScript CLI sends for 1.0
            return await run_tool({**u, "input": json.loads(json.dumps(u["input"]).replace(
                "1.0", "1"))})

        cli._run_tool = js_like
        return cli

    out = run(make_guard(), make_client(clients, make), [echo_tool(events, calls)])
    assert out.success, out.message_de
    assert calls == [{"n": 1}, {"n": 2, "gain": 1.0}]
    assert [e[3] for e in factory.cli.events("mcp_call")] == [False, False]


def test_per_call_estimate_comes_from_the_profile(make_guard):
    profile = make_guard().policy.profile("p")
    assert per_call_estimate(profile) == pytest.approx(1.0 / 5)


# --- property test: random scripts keep the wiring invariants -------------------------------


def _random_script(rng: random.Random) -> dict:
    turns = []
    tid = 0
    for m in range(rng.randint(1, 4)):
        uses = []
        for _ in range(rng.randint(1, 3)):
            tid += 1
            kind = rng.random()
            if kind < 0.55:
                uses.append(use(f"t{tid}", {"n": rng.randint(0, 100)}))
            elif kind < 0.7:
                uses.append(use(f"t{tid}", {"n": rng.choice([-1, 101, "3", None])}))
            elif kind < 0.8:
                uses.append(use(f"t{tid}", {"n": 1, "extra": True}))
            elif kind < 0.9:
                uses.append(use(f"t{tid}", {"command": "rm -rf /"},
                                name=rng.choice(["Bash", "Write", "Agent"])))
            else:
                uses.append(use(f"t{tid}", {"n": 2}, agent_id="sub"))
        turns.append({"id": f"m{m}", "split": rng.random() < 0.3, "tool_uses": uses})
    turns.append({"id": "final", "text": "fertig"})
    return {"total_cost_usd": round(rng.uniform(0, 0.5), 3), "turns": turns}


def test_random_scripts_never_bypass_the_guard(make_guard, events, clients):
    rng = random.Random(4106)
    outcomes = set()
    for case in range(40):
        events.items.clear()
        calls: list = []
        factory = FakeCLIFactory(_random_script(rng))
        guard = make_guard(max_tool_calls=12, max_identical_tool_calls=5)
        out = run(guard, make_client(clients, factory), [echo_tool(events, calls)])
        cli = factory.cli
        ok_mcp = [e[2] for e in cli.events("mcp_call") if e[3] is False]
        # every successful MCP run is one guarded handler run, in order; handlers whose
        # results never reached the CLI exist only when the guard ended the request
        assert ok_mcp == calls[: len(ok_mcp)], case
        if out.success:
            assert ok_mcp == calls, case
        assert cli.events("builtin_executed") == [], case
        assert cli.model_calls <= model_permits(events), case
        seen_before = 0
        for kind, name in events.items:  # each handler run follows its own before_tool
            if (kind, name) == ("before_tool", "echo"):
                seen_before += 1
            elif kind == "handler":
                assert seen_before >= 1, case
                seen_before -= 1
        if out.success:
            assert out.result is not None and out.result.success
        outcomes.add((out.success, out.error, out.stop_reason))
    assert len(outcomes) >= 2  # the scripts reach more than one kind of end
