"""#148: generate_kick, list_tracks and import_sample through ``Toolbox.run`` (guard first),
against the fake AbletonOSC server (CI only, not Live evidence).

Expected values are written here or measured independently (hashlib over the file bytes,
the fake server's own slot list, the files in the folder), not taken from the code under test.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random

import pytest
from kick_helpers import (  # noqa: F401 - fake_fixture is a pytest fixture
    FAST_KICK,
    ProjectCheckDouble,
    fake_fixture,
    make_project,
    make_session,
    registry_copy,
    tool_log,
    toolbox,
    writes_sent,
)
from kick_helpers import RecordingApprover as Approver
from orch_helpers import (  # noqa: F401 - *_fixture are pytest fixtures (see orch_helpers)
    FakeClock,
    clock_fixture,
    events_fixture,
    make_guard_fixture,
)
from support import kick_params

import orchestrator.kick_tools as kt
from guard import GuardStop, Limit
from orchestrator.kick_tools import (
    DROPPED_ROOT_KEYS,
    IMPORT_CAPS,
    LIST_TRACKS_CAPS,
    TOOL_CONTRACTS,
    KickSession,
)
from orchestrator.model_client import ToolCall
from orchestrator.tools import CONFIRM_WINDOW_S, Approval, Toolbox, ToolDefinitionError

ROOT = kt.CONTRACTS_DIR.parent


def run(guard, box, name, args, approver=None, **kwargs):
    with guard.request("p") as req:
        return box.run(req, ToolCall("c1", name, args), approver, **kwargs)


def kick_files(session) -> list:
    folder = session.kick_folder
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def generate(guard, box, n=3, **changes):
    args = {**FAST_KICK, "variants": n, **changes}
    return run(guard, box, "generate_kick", args)


# --- tool definitions from contracts/ -----------------------------------------------------


def test_input_schemas_are_the_contracts_without_root_metadata(tmp_path):
    from test_contracts import strict_subset_problems

    session = make_session(tmp_path)
    specs = {s.name: s for s in toolbox(session).specs()}
    assert set(specs) == {"generate_kick", "list_tracks", "import_sample"}
    for name, file in TOOL_CONTRACTS.items():
        contract = json.loads((ROOT / "contracts" / file).read_text("utf-8"))
        expected = {k: v for k, v in contract.items()
                    if k not in ("$schema", "$id", "title", "$comment")}
        assert specs[name].input_schema == expected, name
        assert not set(specs[name].input_schema) & {"$schema", "$id", "title", "$comment"}
    assert DROPPED_ROOT_KEYS == ("$schema", "$id", "title", "$comment")
    # INTERFACES.md wiring precondition: what the model gets is strict with no root allowance
    for name in ("list_tracks", "import_sample"):
        assert strict_subset_problems(specs[name].input_schema,
                                      allow_root_metadata=False) == [], name


def test_tool_levels_and_capabilities(tmp_path):
    tools = {t.name: t for t in make_session(tmp_path).tools()}
    gen, lst, imp = tools["generate_kick"], tools["list_tracks"], tools["import_sample"]
    assert gen.approval is Approval.ROUTINE and gen.max_live_writes == 0
    assert gen.max_files_written == 16 and gen.capabilities == ()  # 8 kicks x (WAV + sidecar)
    assert lst.approval is Approval.ROUTINE and lst.max_files_written == 0
    assert lst.max_live_writes == 0
    assert set(lst.capabilities) == {"song.track_names.get", "track.has_audio_input.get",
                                     "song.num_scenes.get"}
    assert imp.approval is Approval.CONFIRM and imp.max_live_writes == 1
    assert imp.max_files_written == 0
    assert set(imp.capabilities) == {
        "clip_slot.create_audio_clip", "song.track_names.get", "track.has_audio_input.get",
        "clip_slot.has_clip.get", "clip.file_path.get", "song.num_scenes.get"}


def test_real_registry_admits_the_three_tools(tmp_path):
    """With the committed registry (all tested since #153) the toolbox accepts them."""
    project = make_project(tmp_path)
    session = KickSession(project, refused_roots=(), project_check=ProjectCheckDouble(project))
    assert Toolbox(session.tools(), capability_gate=session.gate()).names == (
        "generate_kick", "list_tracks", "import_sample")


@pytest.mark.parametrize("cap", sorted(set(IMPORT_CAPS) | set(LIST_TRACKS_CAPS)))
@pytest.mark.parametrize("status", ["supported", "unknown", "unsupported"])
def test_one_untested_capability_refuses_its_tool(tmp_path, cap, status):
    registry = registry_copy(tmp_path, not_tested={cap: status})
    session = make_session(tmp_path, registry=registry)
    with pytest.raises(ToolDefinitionError, match=cap.replace(".", r"\.")):
        toolbox(session)


@pytest.mark.parametrize(
    ("args", "files"),
    [({}, 2), ({"variants": 3}, 6), ({"variants": 3.0}, 6), ({"variants": 8}, 16),
     ({"variants": 1}, 2), ({"variants": 0}, 0), ({"variants": -2}, 0),
     ({"variants": 9}, 16), ({"variants": 10**9}, 16),
     ({"variants": "3"}, 0), ({"variants": True}, 0), ({"variants": None}, 0),
     ({"variants": 2.5}, 0), ({"variants": float("nan")}, 0), ([], 0), (None, 0)],
)
def test_declared_files_per_call(tmp_path, args, files):
    """Declared before validation (PR #168 review): exact for whole numbers (capped at the
    tool maximum of 16); 0 for values the schema refuses, which never reach the handler."""
    gen = {t.name: t for t in make_session(tmp_path).tools()}["generate_kick"]
    assert gen.declared_files(args) == files


# --- generate_kick --------------------------------------------------------------------------


def test_three_kicks_land_in_the_project_with_pinned_hashes(tmp_path, make_guard):
    session = make_session(tmp_path)
    guard = make_guard()
    result = generate(guard, toolbox(session))
    assert result.is_error is False, result.content
    kicks = result.content["kicks"]
    assert [k["sample_id"] for k in kicks] == ["kick-1", "kick-2", "kick-3"]
    assert len(kick_files(session)) == 6  # 3 x (WAV + sidecar)
    for k in kicks:
        wav = session.kick_folder / k["file"]
        own = hashlib.sha256(wav.read_bytes()).hexdigest()  # independent hash
        assert session.entry(k["sample_id"]).sha256 == own
        assert json.loads(wav.with_suffix(".json").read_text("utf-8"))["sha256"] == own
        assert session.entry(k["sample_id"]).path == str(wav)
    assert result.content["folder"] == str(tmp_path / "Test Project" / "Samples" / "Drums"
                                           / "Kicks")
    [entry] = tool_log(guard)
    assert entry["files_written"] == 6 and entry["live_writes"] == 0 and entry["ok"] is True
    assert "kick-2" in session.context() and "kick-3" in session.context()


def test_random_requests_over_the_contract_write_exactly_what_they_report(tmp_path, make_guard):
    """Property test over the whole kick-params range (support.kick_params ALL profile):
    each call either succeeds with 2 files per variant, or is refused with no new file; the
    guard counts what is in the folder."""
    r = kick_params.rng(148)
    session = make_session(tmp_path)
    box = toolbox(session)
    guard = make_guard(max_files_written=500, max_tool_calls=200,
                       max_identical_tool_calls=20)
    counted = before = 0
    outcomes = {"ok": 0, "refused": 0, "stop": 0}
    for _ in range(14):
        args = kick_params.draw(r, kick_params.ALL)
        args["variants"] = r.randint(1, 4)  # bounded render time
        result = run(guard, box, "generate_kick", args)
        now = len(kick_files(session))
        if result.is_error:
            outcomes["refused"] += 1
            assert now == before, result.content
        else:
            outcomes["ok"] += 1
            assert now - before == 2 * args["variants"]
            assert len(result.content["kicks"]) == args["variants"]
        counted = sum(e["files_written"] for e in tool_log(guard))
        assert counted == now
        before = now
    assert outcomes["ok"] >= 7, outcomes


def test_more_kicks_than_the_file_budget_are_refused_before_any_render(tmp_path, make_guard):
    """TEST_POLICY allows 10 files: 6 kicks (12 files) are refused with the numbers, nothing
    rendered, the request goes on."""
    session = make_session(tmp_path)
    guard = make_guard()
    result = generate(guard, toolbox(session), n=6)
    assert result.content["error"] == "file_budget"
    assert "12 files" in result.content["message"] and "only 10 more" in result.content["message"]
    assert kick_files(session) == []
    assert tool_log(guard)[-1]["files_written"] == 0


SHIPPED_POLICY = kt.CONTRACTS_DIR.parent / "config" / "guard-policy.json"


@pytest.mark.parametrize(("variants", "outcome"), [
    (1, "ok"), (6, "ok"), (7, "file_budget"), (8, "file_budget"),
    ("3", "invalid_arguments"), (2.5, "invalid_arguments"), (None, "invalid_arguments"),
    (0, "invalid_arguments"), (9, "invalid_arguments")])
def test_shipped_profile_never_stops_on_a_kick_count(tmp_path, variants, outcome):
    """The real kick_generation profile (config/guard-policy.json, 12 files): a too-large
    valid count is refused with the limit, a malformed one is a schema refusal; neither stops
    the request, and the second call of the request still works."""
    from guard import Guard, load_policy

    policy = load_policy(SHIPPED_POLICY)
    limit = policy.profile("kick_generation").max_files_written
    session = make_session(tmp_path)
    box = Toolbox(session.tools(files_per_request=limit), capability_gate=session.gate())
    guard = Guard(policy, log_path=tmp_path / "usage.jsonl")
    args = {**FAST_KICK, "variants": variants}
    with guard.request("kick_generation") as req:
        first = box.run(req, ToolCall("a", "generate_kick", args), None)
        second = box.run(req, ToolCall("b", "generate_kick", {**FAST_KICK, "seed": 1}), None)
    got = "ok" if not first.is_error else first.content["error"]
    assert got == outcome, first.content
    files = 2 * variants if outcome == "ok" else 0
    assert len(kick_files(session)) == files + (2 if files + 2 <= limit else 0)
    if outcome == "file_budget":
        assert f"limit max_files_written {limit}" in first.content["message"]
    gen = {t.name: t for t in session.tools(files_per_request=limit)}["generate_kick"]
    assert f"At most {limit // 2} kicks per request" in gen.description
    assert second.is_error == (files + 2 > limit)


@pytest.mark.parametrize(
    "changes",
    [{"seed": -1}, {"length_ms": 79.0}, {"variants": 9}, {"drive": 1.5}, {"unknown": 1},
     {"pitch_end_hz": float("nan")}, {"schema_version": "0.1"}],
)
def test_invalid_kick_arguments_write_nothing(tmp_path, make_guard, changes):
    session = make_session(tmp_path)
    guard = make_guard(max_files_written=100)
    result = generate(guard, toolbox(session), n=1, **changes)
    assert result.is_error and result.content["error"] == "invalid_arguments"
    assert kick_files(session) == [] and session.sample_ids() == ()


def test_contract_rules_outside_the_schema_are_refused_by_the_engine(tmp_path, make_guard):
    """pitch_end_hz above pitch_start_hz passes the schema; resolve_kick_params refuses it."""
    session = make_session(tmp_path)
    result = generate(make_guard(), toolbox(session), n=1, pitch_start_hz=60.0,
                      pitch_end_hz=120.0)
    assert result.is_error and result.content["error"] == "tool_error", result.content
    assert kick_files(session) == []


def test_sidecar_without_sha256_is_pinned_by_our_own_hash(tmp_path, make_guard, monkeypatch):
    real = kt.place_kick

    def strip_sha(*args, **kwargs):
        wav = real(*args, **kwargs)
        side = wav.with_suffix(".json")
        doc = json.loads(side.read_text("utf-8"))
        del doc["sha256"]
        side.write_text(json.dumps(doc), encoding="utf-8")
        return wav

    monkeypatch.setattr(kt, "place_kick", strip_sha)
    session = make_session(tmp_path)
    result = generate(make_guard(), toolbox(session), n=1)
    assert result.is_error is False
    entry = session.entry("kick-1")
    assert entry.sha256 == hashlib.sha256(open(entry.path, "rb").read()).hexdigest()


def test_sidecar_with_a_different_sha256_is_refused(tmp_path, make_guard, monkeypatch):
    real = kt.place_kick

    def wrong_sha(*args, **kwargs):
        wav = real(*args, **kwargs)
        side = wav.with_suffix(".json")
        doc = json.loads(side.read_text("utf-8"))
        doc["sha256"] = "0" * 64
        side.write_text(json.dumps(doc), encoding="utf-8")
        return wav

    monkeypatch.setattr(kt, "place_kick", wrong_sha)
    session = make_session(tmp_path)
    guard = make_guard()
    result = generate(guard, toolbox(session), n=2)
    assert result.is_error and "sha256" in result.content["message"]
    assert session.sample_ids() == ()  # no id for a kick whose hash does not match
    assert tool_log(guard)[-1]["files_written"] == 2  # what was really written


def test_failure_in_the_middle_keeps_the_finished_kicks(tmp_path, make_guard, monkeypatch):
    real = kt.place_kick
    calls = []

    def disk_full_on_second(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise OSError(28, "No space left on device")
        return real(*args, **kwargs)

    monkeypatch.setattr(kt, "place_kick", disk_full_on_second)
    session = make_session(tmp_path)
    guard = make_guard()
    result = generate(guard, toolbox(session), n=3)
    assert result.is_error and result.content["error"] == "tool_error"
    assert [k["sample_id"] for k in result.content["kicks"]] == ["kick-1"]
    assert session.sample_ids() == ("kick-1",) and len(kick_files(session)) == 2
    [entry] = tool_log(guard)
    assert entry["files_written"] == 2 and entry["ok"] is False


def test_project_check_runs_again_before_every_render(tmp_path, make_guard):
    """The folder may change after the chat started: generate_kick asks the #149 check
    again and writes nothing when it refuses."""
    check = ProjectCheckDouble()
    project = make_project(tmp_path)
    check.accept.add(str(project))
    session = make_session(tmp_path, project=project, project_check=check)
    check.accept.clear()
    result = generate(make_guard(), toolbox(session), n=1)
    assert result.is_error and "refused_by_double" in result.content["message"]
    assert not (project / "Samples").exists()
    assert [c[0] for c in check.calls] == [str(project)] * 2
    assert all(c[1] == () for c in check.calls)  # the session's refused_roots are passed on


def test_session_refuses_what_the_check_refuses(tmp_path):
    project = make_project(tmp_path)
    with pytest.raises(ValueError, match="project folder refused: refused_by_double"):
        KickSession(project, project_check=ProjectCheckDouble())


@pytest.mark.parametrize("problem", [
    "checkout_unknown", "a_code_added_later", False, 0, "", object()])
def test_any_answer_but_none_is_a_refusal(tmp_path, problem):
    """#165 adds `checkout_unknown`; unknown or new codes (and odd return values) refuse."""
    from kick_helpers import Problem

    answer = Problem(problem, "p") if isinstance(problem, str) and problem else problem
    with pytest.raises(ValueError, match="project folder refused"):
        KickSession(make_project(tmp_path), project_check=lambda d, **k: answer)


def test_a_check_that_raises_never_accepts(tmp_path):
    def broken(project_dir, **kwargs):
        raise OSError("disk gone")

    with pytest.raises(ValueError, match="project check failed: OSError"):
        KickSession(make_project(tmp_path), project_check=broken)


def test_without_the_shared_check_the_session_does_not_start(tmp_path, monkeypatch):
    """#149 not merged: no check, no kick tools (lead, #148). Nothing is written."""
    import orchestrator.kick_tools as mod
    from orchestrator.project import ProjectCheckUnavailable

    monkeypatch.setattr(mod, "load_project_check", lambda: None)
    project = make_project(tmp_path)
    with pytest.raises(ProjectCheckUnavailable, match="#149"):
        KickSession(project)
    assert sorted(p.name for p in project.iterdir()) == ["Test.als"]


def test_load_project_check_uses_the_library_function(monkeypatch):
    import library
    from orchestrator.project import load_project_check

    def check(project_dir, *, refused_roots=None):
        return None

    monkeypatch.setattr(library, "check_project_dir", check, raising=False)
    assert load_project_check() is check
    monkeypatch.delattr(library, "check_project_dir")
    assert load_project_check() is None


def test_reused_path_invalidates_the_old_id(tmp_path, make_guard, fake):
    session = make_session(tmp_path, fake)
    box = toolbox(session)
    guard = make_guard()
    generate(guard, box, n=1)
    old = session.entry("kick-1")
    (session.kick_folder / old.file).unlink()
    (session.kick_folder / old.file).with_suffix(".json").unlink()
    generate(guard, box, n=1)  # same parameters, same free name
    new = session.entry("kick-2")
    assert new.path == old.path
    assert session.sample_ids() == ("kick-2",)
    result = run(guard, box, "import_sample", {"sample_id": "kick-1", "track_index": 0},
                 Approver(True))
    assert result.is_error and "unknown sample_id" in result.content["message"]
    assert writes_sent(fake) == []


# --- list_tracks ------------------------------------------------------------------------------


def test_list_tracks_reads_only(tmp_path, make_guard, fake):
    session = make_session(tmp_path, fake)
    guard = make_guard()
    result = run(guard, toolbox(session), "list_tracks", {})
    assert result.is_error is False
    assert result.content["tracks"] == [
        {"index": 0, "name": "1-Kick", "is_audio_track": True},
        {"index": 1, "name": "2-Bass", "is_audio_track": False},
        {"index": 2, "name": "3-Audio", "is_audio_track": True}]
    assert result.content["scene_count"] == 4
    assert "not been observed" in result.content["note"]
    assert writes_sent(fake) == []
    assert tool_log(guard)[-1]["live_writes"] == 0


def test_list_tracks_without_live_is_a_clear_error(tmp_path, make_guard):
    from kick_helpers import FakeAbletonOSC

    server = FakeAbletonOSC()
    server.close()  # nobody answers on that port
    session = make_session(tmp_path, server)
    result = run(make_guard(), toolbox(session), "list_tracks", {})
    assert result.is_error and "Live could not be read" in result.content["message"]


# --- import_sample -----------------------------------------------------------------------------


def _ready(tmp_path, make_guard, fake, n=2, clock=None):
    session = make_session(tmp_path, fake)
    box = toolbox(session, clock=clock)
    guard = make_guard()
    assert generate(guard, box, n=n).is_error is False
    return session, box, guard


def test_import_happy_path(tmp_path, make_guard, fake):
    session, box, guard = _ready(tmp_path, make_guard, fake)
    approver = Approver(True)
    result = run(guard, box, "import_sample", {"sample_id": "kick-2", "track_index": 0},
                 approver)
    assert result.is_error is False, result.content
    path = session.entry("kick-2").path
    assert fake.tracks[0]["slots"][0] == path  # the fake's own record
    assert writes_sent(fake) == [("/live/clip_slot/create_audio_clip", (0, 0, path))]
    [(name, args, summary)] = approver.asked
    assert summary == {"sample_id": "kick-2", "file": session.entry("kick-2").file,
                       "track_index": 0, "track_name": "1-Kick", "slot_index": 0,
                       "scene_count": 4}
    assert result.content["imported"]["file_path_read"] == path
    entry = tool_log(guard)[-1]
    assert entry["tool"] == "import_sample" and entry["live_writes"] == 1 and entry["ok"]
    log = [json.loads(x) for x in (tmp_path / "actions.jsonl").read_text("utf-8").splitlines()]
    assert [e["status"] for e in log] == ["planned", "read_back"]
    assert log[0]["source"] == "orchestrator.import_sample"


def test_first_empty_slot_and_given_slot(tmp_path, make_guard, fake):
    session, box, guard = _ready(tmp_path, make_guard, fake)
    r1 = run(guard, box, "import_sample", {"sample_id": "kick-1", "track_index": 2},
             Approver(True))
    assert r1.content["imported"]["slot_index"] == 1  # slot 0 holds a clip
    r2 = run(guard, box, "import_sample",
             {"sample_id": "kick-2", "track_index": 2.0, "slot_index": 3.0}, Approver(True))
    assert r2.is_error is False and r2.content["imported"]["slot_index"] == 3
    assert fake.tracks[2]["slots"][0] == "C:/other.wav"  # never overwritten


REFUSALS = [
    ({"sample_id": "kick-9", "track_index": 0}, "unknown sample_id"),
    ({"sample_id": "", "track_index": 0}, "unknown sample_id"),
    ({"sample_id": "KICK-1", "track_index": 0}, "unknown sample_id"),
    ({"sample_id": "kick-1", "track_index": -1}, "does not exist"),
    ({"sample_id": "kick-1", "track_index": 3}, "does not exist"),
    ({"sample_id": "kick-1", "track_index": 10**12}, "does not exist"),
    ({"sample_id": "kick-1", "track_index": 1}, "not an audio track"),
    ({"sample_id": "kick-1", "track_index": 2, "slot_index": 0}, "already holds a clip"),
    ({"sample_id": "kick-1", "track_index": 0, "slot_index": 4}, "does not exist"),
    ({"sample_id": "kick-1", "track_index": 0, "slot_index": -1}, "does not exist"),
]


@pytest.mark.parametrize(("args", "why"), REFUSALS)
def test_refusals_send_nothing_and_ask_nobody(tmp_path, make_guard, fake, args, why):
    session, box, guard = _ready(tmp_path, make_guard, fake)
    approver = Approver(True)
    result = run(guard, box, "import_sample", args, approver)
    assert result.is_error and result.content["error"] == "refused"
    assert why in result.content["message"] and result.content["live"] == "unchanged"
    assert approver.asked == [] and writes_sent(fake) == []
    assert tool_log(guard)[-1]["live_writes"] == 0


@pytest.mark.parametrize(("args", "error"), [
    ({"sample_id": "kick-1"}, "invalid_arguments"),
    ({"sample_id": "kick-1", "track_index": "0"}, "invalid_arguments"),
    ({"sample_id": "kick-1", "track_index": 0.5}, "invalid_arguments"),
    ({"sample_id": "kick-1", "track_index": 0, "path": "C:/x.wav"}, "invalid_arguments"),
    ({"sample_id": 1, "track_index": 0}, "invalid_arguments"),
])
def test_schema_refusals(tmp_path, make_guard, fake, args, error):
    session, box, guard = _ready(tmp_path, make_guard, fake)
    result = run(guard, box, "import_sample", args, Approver(True))
    assert result.content["error"] == error and writes_sent(fake) == []


def test_no_empty_slot_is_refused(tmp_path, make_guard, fake):
    fake.tracks[0]["slots"] = ["a", "b", "c", "d"]
    session, box, guard = _ready(tmp_path, make_guard, fake)
    result = run(guard, box, "import_sample", {"sample_id": "kick-1", "track_index": 0},
                 Approver(True))
    assert result.is_error and "no empty slot" in result.content["message"]
    assert writes_sent(fake) == []


@pytest.mark.parametrize("change", ["one_byte", "deleted", "replaced_by_other_kick",
                                    "moved_out"])
def test_changed_file_is_refused_before_asking(tmp_path, make_guard, fake, change):
    session, box, guard = _ready(tmp_path, make_guard, fake)
    e1, e2 = session.entry("kick-1"), session.entry("kick-2")
    wav = session.kick_folder / e1.file
    if change == "one_byte":
        data = bytearray(wav.read_bytes())
        data[-1] ^= 1
        wav.write_bytes(bytes(data))
    elif change == "deleted":
        wav.unlink()
    elif change == "replaced_by_other_kick":
        wav.write_bytes((session.kick_folder / e2.file).read_bytes())  # a valid WAV
    else:
        wav.rename(tmp_path / "elsewhere.wav")
    approver = Approver(True)
    result = run(guard, box, "import_sample", {"sample_id": "kick-1", "track_index": 0},
                 approver)
    assert result.is_error and result.content["error"] == "refused"
    assert approver.asked == [] and writes_sent(fake) == []


def test_file_changed_while_the_user_decides_is_refused(tmp_path, make_guard, fake):
    """The hash is computed again right before the write (INTERFACES.md import_sample 1.)."""
    session, box, guard = _ready(tmp_path, make_guard, fake)
    wav = session.kick_folder / session.entry("kick-1").file

    def edit():
        data = bytearray(wav.read_bytes())
        data[100] ^= 1
        wav.write_bytes(bytes(data))

    result = run(guard, box, "import_sample", {"sample_id": "kick-1", "track_index": 0},
                 Approver(True, during=edit))
    assert result.is_error and result.content["error"] == "tool_error"
    assert "sha256 differs" in result.content["message"]
    assert writes_sent(fake) == [] and tool_log(guard)[-1]["live_writes"] == 0


def test_set_changed_while_the_user_decides_sends_nothing(tmp_path, make_guard, fake):
    session, box, guard = _ready(tmp_path, make_guard, fake)

    def user_drops_a_clip():
        fake.tracks[0]["slots"][0] = "C:/dropped.wav"

    result = run(guard, box, "import_sample", {"sample_id": "kick-1", "track_index": 0},
                 Approver(True, during=user_drops_a_clip))
    assert result.is_error and result.content["live"] == "unchanged"
    assert writes_sent(fake) == [] and fake.tracks[0]["slots"][0] == "C:/dropped.wav"
    assert tool_log(guard)[-1]["live_writes"] == 0


@pytest.mark.parametrize("answer", [False, "ja", 1, None])
def test_anything_but_true_declines(tmp_path, make_guard, fake, answer):
    session, box, guard = _ready(tmp_path, make_guard, fake)
    result = run(guard, box, "import_sample", {"sample_id": "kick-1", "track_index": 0},
                 Approver(answer))
    assert result.content["error"] == "declined" and writes_sent(fake) == []


def test_no_approver_declines(tmp_path, make_guard, fake):
    session, box, guard = _ready(tmp_path, make_guard, fake)
    result = run(guard, box, "import_sample", {"sample_id": "kick-1", "track_index": 0})
    assert result.content["error"] == "declined" and writes_sent(fake) == []


def test_yes_after_the_request_deadline_stops_and_sends_nothing(tmp_path, make_guard, fake,
                                                                clock):
    """#81 (c): the deadline is checked again after the confirmation."""
    session, box, guard = _ready(tmp_path, make_guard, fake)

    def slow_user():
        clock.t += 101  # TEST_POLICY timeout_s = 100

    with pytest.raises(GuardStop) as stop:
        run(guard, box, "import_sample", {"sample_id": "kick-1", "track_index": 0},
            Approver(True, during=slow_user))
    assert stop.value.reason is Limit.TIMEOUT
    assert writes_sent(fake) == []
    entry = tool_log(guard)[-1]
    assert entry["tool"] == "import_sample" and entry["live_writes"] == 0
    assert entry["ok"] is False


@pytest.mark.parametrize(("waited", "runs"), [(0.0, True), (CONFIRM_WINDOW_S, True),
                                              (CONFIRM_WINDOW_S + 0.01, False),
                                              (float("nan"), False), (3600.0, False)])
def test_confirmation_window(tmp_path, make_guard, fake, waited, runs):
    """#83 V10: a yes later than CONFIRM_WINDOW_S after the model turn is refused."""
    ticks = FakeClock()
    session, box, guard = _ready(tmp_path, make_guard, fake, clock=ticks)
    start = ticks()

    def user():
        ticks.t = start + waited

    result = run(guard, box, "import_sample", {"sample_id": "kick-1", "track_index": 0},
                 Approver(True, during=user), turn_started=start)
    assert (not result.is_error) == runs, result.content
    assert (writes_sent(fake) != []) == runs
    if not runs:
        assert result.content["error"] == "too_late"


@pytest.mark.parametrize("answer", [False, None, "yes", RuntimeError("boom")])
def test_backend_no_longer_waiting_refuses_the_write(tmp_path, make_guard, fake, answer):
    session, box, guard = _ready(tmp_path, make_guard, fake)
    asked = []

    def still_waiting(call_id):
        asked.append(call_id)
        if isinstance(answer, Exception):
            raise answer
        return answer

    result = run(guard, box, "import_sample", {"sample_id": "kick-1", "track_index": 0},
                 Approver(True), still_waiting=still_waiting)
    assert result.content["error"] == "session_lost" and asked == ["c1"]
    assert writes_sent(fake) == []


def test_live_gone_after_the_plan(tmp_path, make_guard, fake):
    session, box, guard = _ready(tmp_path, make_guard, fake)
    result = run(guard, box, "import_sample", {"sample_id": "kick-1", "track_index": 0},
                 Approver(True, during=lambda: fake.drop.add("/live/song/get/track_names")))
    assert result.is_error and result.content["live"] == "unchanged"
    assert writes_sent(fake) == []


def test_symlink_to_an_identical_file_outside_the_library_is_refused(tmp_path, make_guard,
                                                                    fake):
    """INTERFACES.md: right before the import the path is checked again with
    validate_wav_path(path, library_root=<kick folder>). A WAV replaced by a symlink to a
    byte-identical copy outside the library passes the hash pin; only that check refuses it
    (reviewer mutant R7)."""
    import os

    session, box, guard = _ready(tmp_path, make_guard, fake)
    wav = session.kick_folder / session.entry("kick-1").file
    outside = tmp_path / "outside"
    outside.mkdir()
    copy_path = outside / wav.name
    copy_path.write_bytes(wav.read_bytes())
    wav.unlink()
    try:
        os.symlink(copy_path, wav)
    except (OSError, NotImplementedError) as exc:  # Windows without the symlink privilege
        pytest.skip(f"symlinks not available here: {exc}")
    approver = Approver(True)
    result = run(guard, box, "import_sample", {"sample_id": "kick-1", "track_index": 0},
                 approver)
    assert result.is_error and "outside the sample library" in result.content["message"]
    assert approver.asked == [] and writes_sent(fake) == []


def test_unexpected_bridge_error_tells_the_model_to_look_in_live(tmp_path, make_guard, fake,
                                                                monkeypatch):
    import orchestrator.kick_tools as mod

    session, box, guard = _ready(tmp_path, make_guard, fake)

    class Broken(mod.ClipImporter):
        def run(self, **kwargs):
            raise RuntimeError("bug in the bridge")

    monkeypatch.setattr(mod, "ClipImporter", Broken)
    result = run(guard, box, "import_sample", {"sample_id": "kick-1", "track_index": 0},
                 Approver(True))
    assert result.content["error"] == "tool_error"
    assert result.content["live"] == "unchanged"  # nothing was sent before the bug
    assert "RuntimeError" in result.content["message"]


def test_live_refuses_the_write(tmp_path, make_guard, fake):
    """AbletonOSC answers the write with an error: counted as a possible write, Live state
    reported as unknown (never as success)."""
    session, box, guard = _ready(tmp_path, make_guard, fake)
    fake.tracks[0]["frozen"] = True
    result = run(guard, box, "import_sample", {"sample_id": "kick-1", "track_index": 0},
                 Approver(True))
    assert result.is_error and result.content["error"] == "tool_error"
    assert result.content["live"].startswith("unknown")
    assert tool_log(guard)[-1]["live_writes"] == 1


def test_random_targets_import_only_into_empty_audio_slots(tmp_path, make_guard, fake):
    """Property test: random track/slot indices (negative, in range, far out, whole floats);
    a clip appears exactly when the target is an existing audio track and an empty slot, and
    no slot that held something changes."""
    r = random.Random(1480)
    session, box, guard = _ready(tmp_path, make_guard, fake, n=1)
    for _ in range(40):
        guard = make_guard()  # one request per draw: the loop limit is not under test here
        before = copy.deepcopy([t.get("slots", [None] * 4) for t in fake.tracks])
        track = r.choice([-3, -1, 0, 1, 2, 3, 7, 2**31])
        args = {"sample_id": "kick-1", "track_index": r.choice([track, float(track)])}
        slot = r.choice([None, -1, 0, 1, 2, 3, 4, 99])
        if slot is not None:
            args["slot_index"] = slot
        result = run(guard, box, "import_sample", args, Approver(True))
        valid_track = track in (0, 2)
        target = None
        if valid_track:
            slots = before[track]
            if slot is None:
                target = next((i for i, s in enumerate(slots) if s is None), None)
            elif 0 <= slot < 4 and slots[slot] is None:
                target = slot
        after = [t.get("slots", [None] * 4) for t in fake.tracks]
        changed = [(ti, si) for ti in range(3) for si in range(4)
                   if before[ti][si] != after[ti][si]]
        if target is None:
            assert result.is_error and changed == [], (args, result.content)
        else:
            assert not result.is_error, (args, result.content)
            assert changed == [(track, target)] and before[track][target] is None
        if sum(s is None for t in after for s in t) < 3:
            for t in fake.tracks:  # free the set again so later draws can import
                t["slots"] = [s if s == "C:/other.wav" else None for s in t.get("slots", [])]
