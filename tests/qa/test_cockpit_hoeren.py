"""#342: 'Hören' rows of docs/WAITING_ON_USER.md must get kind 'Hören', not 'Sonstiges'."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "qa"))
import cockpit_collect as cc  # noqa: E402

BASE = "https://github.com/castorsalzmann-ui/AbeltonGod/issues/"


def test_hoeren_row_has_own_kind(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "WAITING_ON_USER.md").write_text(
        "| Was | Link | Aufgabe | Seit |\n| --- | --- | --- | --- |\n"
        f"| Hören | {BASE}271 | Kick-Hörpaket hören | 2026-11-02 |\n"
        f"| Merge | {BASE}5 | PR mergen | 2026-11-02 |\n"
        f"| Irgendwas | {BASE}6 | unbekannt | 2026-11-02 |\n",
        encoding="utf-8",
    )
    rows = cc.collect_user_actions(tmp_path, [])
    assert [r["kind"] for r in rows] == ["Hören", "Merge", "Sonstiges"]
    assert rows[0]["number"] == 271
