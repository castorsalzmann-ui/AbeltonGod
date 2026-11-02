"""Regression for #245: api_key mode did not refuse the cloud-provider switches.

``CLAUDE_CODE_USE_BEDROCK`` / ``_VERTEX`` / ``_FOUNDRY`` rank above ``ANTHROPIC_API_KEY`` in
Claude Code's auth precedence, so with a set switch the SDK bills a cloud account although the
user chose the API key (same trap as #118, there for subscription mode).
``before_fix``: ``load_auth`` returned ``AuthSettings(mode=api_key)`` without error.
CI only, no model call. Off values ("0", "false", ...) are not a switch.
"""

from __future__ import annotations

import pytest

from orchestrator.auth import AuthConfigError, AuthMode, load_auth

PROVIDERS = ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")
BASE = {"ABELTONGOD_CLAUDE_AUTH": "api_key", "ANTHROPIC_API_KEY": "sk-test"}


@pytest.mark.parametrize("var", PROVIDERS)
@pytest.mark.parametrize("value", ["1", "true", "YES"])
def test_api_key_refuses_a_provider_switch(var, value):
    with pytest.raises(AuthConfigError, match=var):
        load_auth({**BASE, var: value}, None)


def test_api_key_refuses_a_provider_switch_from_dotenv(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ABELTONGOD_CLAUDE_AUTH=api_key\nANTHROPIC_API_KEY=sk-test\n"
                   "CLAUDE_CODE_USE_VERTEX=1\n", "utf-8")
    with pytest.raises(AuthConfigError, match="CLAUDE_CODE_USE_VERTEX"):
        load_auth({}, env)


def test_the_message_never_contains_the_key():
    with pytest.raises(AuthConfigError) as exc:
        load_auth({**BASE, "CLAUDE_CODE_USE_BEDROCK": "1"}, None)
    assert "sk-test" not in str(exc.value)


@pytest.mark.parametrize("value", ["", "  ", "0", "false", "No", "off"])
def test_an_off_switch_does_not_block_api_key_mode(value):
    settings = load_auth({**BASE, "CLAUDE_CODE_USE_BEDROCK": value}, None)
    assert settings.mode is AuthMode.API_KEY and settings.api_key_present
