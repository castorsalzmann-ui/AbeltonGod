"""Regression for #147: subscription mode refused a valid Claude Max login.

User's run (Windows, 2026-10-29, after PR #122): ``python -m orchestrator.chat`` -> "Claude ist
gerade nicht erreichbar (auth mode 'subscription': Claude Code uses the credential 'none'
instead of your Claude login)". The bundled CLI 2.1.310 started by hand showed "Claude Max"
and answered, so the login works.

Before the fix ``_check_account`` only accepted ``tokenSource`` in ``(None,
"CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR")``; the initialize response
of that run carried ``tokenSource: "none"`` (the string), so the request was refused before the
prompt. ``before_fix``: ``error == "model_unavailable"``, message names ``'none'``.

Why "none" is a subscription value (bundled CLI 2.1.310, function ``O0e()`` in the Linux build,
same logic in the Windows build): ``tokenSource`` is the CLI's own token-source lookup, and that
lookup returns "none" when it sees no OAuth or bearer credential *at the moment the initialize
answer is built*; API keys are reported separately in ``apiKeySource``. So "none" passes only
together with no ``apiKeySource`` - a Console login ("/login managed key") also has
``tokenSource: "none"`` and must still be refused (second case below).

CI only: the fake CLI stands in for Claude Code; no model call. The real call is re-tested on
the user's machine (issue #147).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "orchestrator"))

from fake_cli import FakeCLIFactory  # noqa: E402
from orch_helpers import (  # noqa: E402, F401 - *_fixture are pytest fixtures
    clock_fixture,
    events_fixture,
    make_guard_fixture,
)

from orchestrator.auth import AuthMode, AuthSettings  # noqa: E402
from orchestrator.loop import Orchestrator  # noqa: E402
from orchestrator.sdk_client import SdkModelClient  # noqa: E402
from orchestrator.tools import Toolbox  # noqa: E402

# The initialize "account" of the user's run, as far as the refusal message shows it: the
# credential was the string "none" and the provider check had passed (it runs first).
USER_ACCOUNT = {"tokenSource": "none", "apiProvider": "firstParty"}


@pytest.fixture(name="clients")
def clients_fixture():
    made: list[SdkModelClient] = []
    yield made
    for client in made:
        client.close()


def _run(make_guard, clients, account):
    factory = FakeCLIFactory({"account": account, "api_key_source": "none",
                              "turns": [{"text": "Hallo zurueck"}]})
    client = SdkModelClient(AuthSettings(AuthMode.SUBSCRIPTION, "claude-opus-5-5", False),
                            per_call_estimate_usd=0.1, transport_factory=factory)
    clients.append(client)
    out = Orchestrator(make_guard(), client, Toolbox([]), profile="p").handle("Hallo")
    return out, factory


def test_bug_147_max_login_with_token_source_none_passes(make_guard, clients):
    out, factory = _run(make_guard, clients, USER_ACCOUNT)
    assert out.success, out.message_de
    assert factory.cli.prompts == ["Hallo"]


def test_bug_147_console_key_with_token_source_none_is_still_refused(make_guard, clients):
    account = {**USER_ACCOUNT, "apiKeySource": "/login managed key"}
    out, factory = _run(make_guard, clients, account)
    assert out.success is False and out.error == "model_unavailable"
    assert factory.cli.prompts == [] and factory.cli.model_calls == 0
