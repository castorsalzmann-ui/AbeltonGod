"""gui_core.chat: access status from the .env next to the app, and a chat on a fake model."""

from __future__ import annotations

import pytest

from guard import Guard
from gui_core.chat import ChatSession, chat_status
from orchestrator.fake_model import FakeModel

SECRET = "sk-test-secret-value-123"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ABELTONGOD_CLAUDE_AUTH",
                 "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"):
        monkeypatch.delenv(name, raising=False)


def env_file(tmp_path, text):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_no_env_file_means_subscription_access(tmp_path):
    st = chat_status(tmp_path / ".env")
    assert st.ready and st.mode == "subscription" and "Claude-Anmeldung" in st.message


def test_api_key_mode_without_key_gives_a_clear_message(tmp_path):
    st = chat_status(env_file(tmp_path, "ABELTONGOD_CLAUDE_AUTH=api_key\n"))
    assert not st.ready
    assert "Kein API-Schlüssel gefunden" in st.message and "ANTHROPIC_API_KEY" in st.message
    assert str(tmp_path / ".env") in st.message


def test_api_key_in_env_file_is_ready_and_never_shown(tmp_path):
    st = chat_status(env_file(
        tmp_path, f"ABELTONGOD_CLAUDE_AUTH=api_key\nANTHROPIC_API_KEY={SECRET}\n"))
    assert st.ready and st.mode == "api_key" and SECRET not in st.message


def test_contradicting_settings_are_reported_not_raised(tmp_path):
    st = chat_status(env_file(tmp_path, f"ANTHROPIC_API_KEY={SECRET}\n"))  # subscription + key
    assert not st.ready and "falsch eingestellt" in st.message and SECRET not in st.message
    st = chat_status(env_file(tmp_path, "ABELTONGOD_CLAUDE_AUTH=banana\n"))
    assert not st.ready


def test_ask_without_access_does_not_call_the_model(tmp_path):
    session = ChatSession(env_file(tmp_path, "ABELTONGOD_CLAUDE_AUTH=api_key\n"))
    reply = session.ask("Hallo")
    assert not reply.success and "Kein API-Schlüssel" in reply.text


def test_chat_on_a_fake_model_answers_and_keeps_the_guard(tmp_path):
    model = FakeModel([{"text": "Hallo, ich plane mit dir."}])
    guard = Guard(log_path=tmp_path / "usage.jsonl")
    session = ChatSession(tmp_path / ".env", model=model, guard=guard,
                          output_dir=tmp_path / "out", session_options={"refused_roots": ()})
    reply = session.ask("Hallo")
    assert reply.success and "Hallo, ich plane mit dir." in reply.text
    assert len(model.requests) == 1
    # #491: the tools of the terminal chat with --project, written down here
    names = [t.name for t in model.requests[0].tools]
    assert names == ["generate_kick", "list_tracks", "import_sample", "generate_sample",
                     "plan_arrangement"]
    assert guard.policy.profile("kick_generation").max_model_calls == 8  # policy file unchanged


def test_unreachable_model_is_a_german_failure_not_an_exception(tmp_path):
    model = FakeModel([{"error": "unavailable", "detail": "connection refused",
                        "request_sent": False}])
    session = ChatSession(tmp_path / ".env", model=model,
                          guard=Guard(log_path=tmp_path / "usage.jsonl"),
                          output_dir=tmp_path / "out")
    reply = session.ask("Hallo")
    assert not reply.success and reply.text
    assert "Traceback" not in reply.text
