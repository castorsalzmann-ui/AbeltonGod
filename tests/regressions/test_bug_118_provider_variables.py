"""Regression for #118: subscription mode did not refuse the cloud-provider switches.

``CLAUDE_CODE_USE_BEDROCK`` / ``_VERTEX`` / ``_FOUNDRY`` rank above the login in Claude Code's
auth precedence (auth note row 8). Before the fix ``load_auth`` accepted them in subscription
mode, so a set switch would bill a cloud account (D-014). The init-message check cannot catch it
(SDK type doc: ``apiKeySource == "none"`` also for a third-party cloud provider).
``before_fix``: ``load_auth`` returned ``AuthSettings(mode=subscription)`` without error.
CI only, no model call. A value that is explicitly off ("0", "false", ...) is not a switch.
"""

from __future__ import annotations

import pytest

from orchestrator.auth import AuthConfigError, AuthMode, load_auth

PROVIDERS = ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")


@pytest.mark.parametrize("var", PROVIDERS)
@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes"])
def test_subscription_refuses_a_provider_switch(var, value):
    with pytest.raises(AuthConfigError, match=var):
        load_auth({var: value}, None)


@pytest.mark.parametrize("var", PROVIDERS)
def test_subscription_refuses_a_provider_switch_from_dotenv(tmp_path, var):
    env = tmp_path / ".env"
    env.write_text(f"{var}=1\n", "utf-8")
    with pytest.raises(AuthConfigError, match=var):
        load_auth({}, env)


@pytest.mark.parametrize("value", ["", "  ", "0", "false", "False", "no", "off"])
def test_an_off_switch_is_not_a_switch(value):
    assert load_auth({"CLAUDE_CODE_USE_BEDROCK": value}, None).mode is AuthMode.SUBSCRIPTION
