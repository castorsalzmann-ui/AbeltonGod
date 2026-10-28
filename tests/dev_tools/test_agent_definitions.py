"""Agent definitions in .claude/agents/ follow the flat team of D-017."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / ".claude" / "agents"

# The D-017 roles, written out here independently of the files under test.
ROLES = {
    "audio-engineer",
    "bridge-engineer",
    "orchestrator-engineer",
    "reviewer",
    "qa-tester",
    "sound-designer",
    "researcher",
}
# Tools that would let an agent start helpers or sub-agents (forbidden by D-017).
SPAWN_TOOLS = {"Agent", "Task"}


def frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---", f"{path.name}: no frontmatter"
    end = lines.index("---", 1)
    fields = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(":")
        assert sep, f"{path.name}: malformed frontmatter line {line!r}"
        fields[key.strip()] = value.strip()
    return fields


def tools(path: Path) -> set[str]:
    return {t.strip() for t in frontmatter(path)["tools"].split(",") if t.strip()}


def test_exactly_the_d017_roles_exist() -> None:
    assert {p.stem for p in AGENTS.glob("*.md")} == ROLES


@pytest.mark.parametrize("role", sorted(ROLES))
def test_frontmatter_is_complete(role: str) -> None:
    fields = frontmatter(AGENTS / f"{role}.md")
    assert fields.get("name") == role
    assert len(fields.get("description", "")) > 20
    assert "tools" in fields, f"{role}: without a tools list the agent could spawn sub-agents"


@pytest.mark.parametrize("role", sorted(ROLES))
def test_no_agent_can_start_helpers(role: str) -> None:
    assert not tools(AGENTS / f"{role}.md") & SPAWN_TOOLS


def test_reviewer_cannot_edit_files() -> None:
    assert not tools(AGENTS / "reviewer.md") & {"Edit", "Write", "NotebookEdit"}


def test_claude_md_lists_every_role() -> None:
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    for role in ROLES:
        assert f"`{role}`" in text, role
