"""Tool definitions, capability rule, auth switch and terminal chat (#78)."""

from __future__ import annotations

import io
import json
from decimal import Decimal
from fractions import Fraction

import numpy as np
import pytest
from orch_helpers import ECHO_SCHEMA, echo_tool, live_tool

from bridge.capabilities import CAPABILITIES_FILE, CapabilityGate, CapabilityRegistry
from orchestrator.auth import (
    AUTH_VARIABLE,
    DEFAULT_MODEL,
    AuthConfigError,
    AuthMode,
    check_api_key_source,
    load_auth,
    read_env_file,
)
from orchestrator.chat import TerminalApprover, main
from orchestrator.clients import UnavailableModel, make_model_client
from orchestrator.fake_model import FakeModel
from orchestrator.model_client import ModelClient, ModelUnavailable
from orchestrator.tools import (
    Approval,
    Tool,
    Toolbox,
    ToolDefinitionError,
    ToolOutput,
    validation_errors,
)

# --- tool definitions ---------------------------------------------------------------------


def _noop(args):
    return ToolOutput({})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": ""},
        {"input_schema": {"type": "array"}},
        {"input_schema": {"type": "object", "properties": {"n": {"type": "nonsense"}}}},
        {"max_files_written": -1},
        {"max_live_writes": True},
        {"max_live_writes": 1},  # Live writes need confirm
        {"capabilities": ("track.mute.set",)},  # capabilities need confirm
        {"approval": "routine"},
    ],
)
def test_bad_tool_definitions_are_refused(kwargs):
    base = {"name": "t", "description": "", "input_schema": {"type": "object"}, "handler": _noop}
    with pytest.raises(ToolDefinitionError):
        Tool(**{**base, **kwargs})


@pytest.mark.parametrize(
    ("name", "ok"),
    [("generate_kick", True), ("list-tracks", True), ("A9", True), ("x" * 128, True),
     ("x" * 129, False), ("kick.render", False), ("two words", False), ("kick\n", False),
     ("ümlaut", False), (None, False), (3, False)],
)
def test_tool_names_follow_the_api_rule(name, ok):
    """API rule ^[a-zA-Z0-9_-]{1,128}$ (tool-schema note Q5), written here independently."""
    make = lambda: Tool(name, "", {"type": "object"}, _noop)  # noqa: E731
    if ok:
        assert make().name == name
    else:
        with pytest.raises(ToolDefinitionError):
            make()


def test_schema_is_copied_in_and_out():
    """Neither the model-facing spec nor the caller's dict can change what is validated."""
    source = {"type": "object", "properties": {"n": {"type": "integer", "maximum": 100}}}
    tool = Tool("t", "", source, _noop)
    source["properties"]["n"]["maximum"] = 10**9
    tool.spec.input_schema["properties"]["n"]["maximum"] = 10**9
    assert tool.input_schema["properties"]["n"]["maximum"] == 100
    assert tool.spec.input_schema["properties"]["n"]["maximum"] == 100
    assert ECHO_SCHEMA["properties"]["n"]["maximum"] == 100


def test_duplicate_and_foreign_tools_are_refused():
    box = Toolbox([echo_tool()])
    with pytest.raises(ToolDefinitionError):
        box.register(echo_tool())
    with pytest.raises(ToolDefinitionError):
        box.register(object())
    assert box.names == ("echo",)


def _cap_tool(cap: str) -> Tool:
    return Tool("live", "", {"type": "object"}, _noop, approval=Approval.CONFIRM,
                max_live_writes=1, capabilities=(cap,))


def _registry_with_one_supported(tmp_path, cap_id: str = "song.create_audio_track"):
    """Copy of the real registry (contracts/capabilities.json) with ``cap_id`` set back to
    ``supported`` (evidence removed). Since #143 the committed registry has no `supported`
    entry left, so the "untested capability" example comes from this copy (#152)."""
    doc = json.loads(CAPABILITIES_FILE.read_text(encoding="utf-8"))
    (cap,) = [c for c in doc["capabilities"] if c["id"] == cap_id]
    cap["status"] = "supported"
    cap.pop("evidence", None)
    path = tmp_path / "capabilities-one-supported.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    registry = CapabilityRegistry.from_file(path)
    assert registry.get(cap_id).status == "supported"
    return registry


def test_only_tested_capabilities_become_tools(tmp_path):
    """Real registry statuses, except song.create_audio_track set back to `supported` (#152)."""
    gate = CapabilityGate(_registry_with_one_supported(tmp_path))
    Toolbox([_cap_tool("track.mute.set")], capability_gate=gate)  # tested
    Toolbox([_cap_tool("clip_slot.create_audio_clip")], capability_gate=gate)  # tested in #50
    for cap in ("song.create_audio_track", "song.export_audio", "no.such.capability"):
        with pytest.raises(ToolDefinitionError, match=cap.replace(".", r"\.")):
            Toolbox([_cap_tool(cap)], capability_gate=gate)


@pytest.mark.parametrize(
    ("caps", "bad"),
    [
        (("track.mute.set", "song.tempo.get"), None),
        (("track.mute.set", "song.create_audio_track"), "song.create_audio_track"),
        (("song.tempo.get", "track.mute.get", "song.export_audio"), "song.export_audio"),
        (("song.create_audio_track", "track.mute.set"), "song.create_audio_track"),
    ],
)
def test_every_capability_of_a_tool_is_checked(tmp_path, caps, bad):
    """Review of PR #89, finding 6 (D-004): one untested capability anywhere in the list
    refuses the tool, not just the first one. song.create_audio_track is `supported` only in
    the registry copy (#152)."""
    gate = CapabilityGate(_registry_with_one_supported(tmp_path))
    tool = Tool("live", "", {"type": "object"}, _noop, approval=Approval.CONFIRM,
                max_live_writes=1, capabilities=caps)
    if bad is None:
        assert Toolbox([tool], capability_gate=gate).names == ("live",)
    else:
        with pytest.raises(ToolDefinitionError, match=bad.replace(".", r"\.")):
            Toolbox([tool], capability_gate=gate)


@pytest.mark.parametrize("value", [np.float64("nan"), np.float32("nan"), np.float32("inf"),
                                   np.float16("-inf"), float("nan")])
def test_numpy_non_finite_arguments_are_rejected(value):
    """Review of PR #89, finding 7: NaN/Inf as NumPy scalars (float32 is not a float
    subclass), top level and nested."""
    tool = Tool("t", "", {"type": "object"}, _noop)
    assert validation_errors(tool, {"g": value})
    assert validation_errors(tool, {"g": [1, {"h": value}]})
    assert validation_errors(tool, {"g": np.float32(0.5), "n": np.int64(3)}) == []


@pytest.mark.parametrize(
    "value",
    [Decimal("NaN"), Decimal("Infinity"), Decimal("1.5"), complex(float("nan"), 0), 1j,
     Fraction(1, 3)],
)
def test_non_json_number_types_are_rejected(value):
    """Review round 2 of PR #89, nit: jsonschema treats any numbers.Number as "number"."""
    tool = Tool("t", "", {"type": "object", "properties": {"g": {"type": "number"}}}, _noop)
    assert validation_errors(tool, {"g": value})
    assert validation_errors(tool, {"g": [value]})
    for ok in (0, -3, 2.5, True, np.float64(1.0), np.int32(4)):
        assert not [e for e in validation_errors(tool, {"x": ok}) if "JSON" in e], ok


def test_capability_tool_without_gate_is_refused():
    with pytest.raises(ToolDefinitionError, match="no capability gate"):
        Toolbox([_cap_tool("track.mute.set")])


def test_live_tool_definition_is_confirm():
    assert live_tool().approval is Approval.CONFIRM


# --- auth switch --------------------------------------------------------------------------


def test_default_is_subscription_with_opus(tmp_path):
    s = load_auth({}, tmp_path / "missing.env")
    assert s.mode is AuthMode.SUBSCRIPTION and s.model == DEFAULT_MODEL == "claude-opus-5-5"
    assert s.api_key_present is False


@pytest.mark.parametrize("var", ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"])
def test_subscription_refuses_an_overriding_key(tmp_path, var):
    with pytest.raises(AuthConfigError, match=var) as err:
        load_auth({var: "sk-secret-value"}, None)
    assert "sk-secret-value" not in str(err.value)


def test_subscription_refuses_a_key_from_dotenv(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# c\nANTHROPIC_API_KEY='sk-x'\n", "utf-8")
    with pytest.raises(AuthConfigError):
        load_auth({}, env)


def test_empty_key_is_not_a_key(tmp_path):
    assert load_auth({"ANTHROPIC_API_KEY": "  "}, None).mode is AuthMode.SUBSCRIPTION


def test_api_key_mode(tmp_path):
    env = tmp_path / ".env"
    env.write_text(f"export {AUTH_VARIABLE}=API_KEY\nANTHROPIC_API_KEY=\"sk-abc\"\n", "utf-8")
    s = load_auth({}, env)
    assert s.mode is AuthMode.API_KEY and s.api_key_present
    assert "sk-abc" not in repr(s)
    with pytest.raises(AuthConfigError, match="needs ANTHROPIC_API_KEY"):
        load_auth({AUTH_VARIABLE: "api_key"}, None)


def test_process_environment_wins_over_dotenv(tmp_path):
    env = tmp_path / ".env"
    env.write_text(f"{AUTH_VARIABLE}=api_key\n", "utf-8")
    assert load_auth({AUTH_VARIABLE: "subscription"}, env).mode is AuthMode.SUBSCRIPTION


def test_unknown_mode_is_refused():
    with pytest.raises(AuthConfigError, match="subscription' or 'api_key"):
        load_auth({AUTH_VARIABLE: "oauth"}, None)


def test_env_file_reader(tmp_path):
    p = tmp_path / ".env"
    p.write_text("A=1\n  # x\nB = 'two'\nnoequals\nC=\n", "utf-8")
    assert read_env_file(p) == {"A": "1", "B": "two", "C": ""}
    assert read_env_file(tmp_path / "none") == {}


def test_api_key_source_check():
    check_api_key_source(AuthMode.SUBSCRIPTION, "none")
    check_api_key_source(AuthMode.API_KEY, "ANTHROPIC_API_KEY")
    for mode, source in [(AuthMode.SUBSCRIPTION, "ANTHROPIC_API_KEY"),
                         (AuthMode.SUBSCRIPTION, None),
                         (AuthMode.API_KEY, "none"),
                         (AuthMode.API_KEY, "/login managed key")]:
        with pytest.raises(AuthConfigError):
            check_api_key_source(mode, source)


def test_real_client_is_the_sdk_client_and_starts_nothing(monkeypatch):
    from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport

    from orchestrator.sdk_client import SdkModelClient

    def no_cli(self):  # building the client must not spawn Claude Code
        raise AssertionError("the CLI was started")

    monkeypatch.setattr(SubprocessCLITransport, "connect", no_cli)
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", AUTH_VARIABLE):
        monkeypatch.delenv(name, raising=False)
    client = make_model_client(load_auth(environ={}, env_file=None))
    try:
        assert isinstance(client, ModelClient) and isinstance(client, SdkModelClient)
        assert client.settings.mode is AuthMode.SUBSCRIPTION
    finally:
        client.close()


def test_missing_sdk_becomes_an_unreachable_model(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "orchestrator.sdk_client", None)  # import fails
    client = make_model_client(load_auth(environ={}, env_file=None))
    assert isinstance(client, UnavailableModel) and "not installed" in client.reason
    with pytest.raises(ModelUnavailable) as err:
        client.complete(None)
    assert err.value.request_sent is False


def test_config_error_becomes_an_unreachable_model(monkeypatch):
    monkeypatch.setenv(AUTH_VARIABLE, "bogus")
    client = make_model_client()
    assert "bogus" in client.reason


# --- terminal chat ------------------------------------------------------------------------


def _reader(lines):
    it = iter(lines)

    def read(prompt):
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    return read


def test_chat_replays_a_recording(tmp_path):
    rec = tmp_path / "r.json"
    rec.write_text('{"recording_version": 1, "turns": [{"text": "Hallo!", '
                   '"usage": {"output_tokens": 3, "cost_usd": 0.001}}]}', "utf-8")
    out = io.StringIO()
    from guard import Guard

    code = main(["--replay", str(rec)], read=_reader(["hi", "exit"]), out=out,
                guard=Guard(log_path=tmp_path / "u.jsonl"))
    assert code == 0 and "Hallo!" in out.getvalue()


def test_chat_without_claude_reports_and_keeps_running(tmp_path):
    out = io.StringIO()
    from guard import Guard

    code = main([], read=_reader(["drei Kicks", "noch mal"]), out=out,
                guard=Guard(log_path=tmp_path / "u.jsonl"), model=UnavailableModel("offline"))
    assert code == 0
    assert out.getvalue().count("nicht erreichbar") == 2


def test_chat_bad_recording_is_a_setup_error(tmp_path):
    out = io.StringIO()
    assert main(["--replay", str(tmp_path / "missing.json")], read=_reader([]), out=out) == 2
    assert "Fehler" in out.getvalue()


@pytest.mark.parametrize(("answer", "ok"), [("j", True), ("JA", True), ("yes", True),
                                            ("", False), ("n", False), ("jein", False)])
def test_terminal_approver_needs_explicit_yes(answer, ok):
    out = io.StringIO()
    approver = TerminalApprover(_reader([answer]), out)
    assert approver.confirm(live_tool(), {}) is ok
    assert "Ableton-Set" in out.getvalue()


def test_terminal_approver_eof_is_no():
    assert TerminalApprover(_reader([]), io.StringIO()).confirm(live_tool(), {}) is False


def test_fake_model_limit_kind():
    from orchestrator.fake_model import RecordingError
    from orchestrator.model_client import ModelLimitReached

    fake = FakeModel([{"error": "limit", "subtype": "error_max_turns",
                       "usage": {"cost_usd": 0.1}}])
    with pytest.raises(ModelLimitReached) as err:
        fake.complete(None)
    assert err.value.subtype == "error_max_turns" and err.value.usage.cost_usd == 0.1
    with pytest.raises(RecordingError):
        FakeModel([{"error": "limit", "subtype": "other"}])
