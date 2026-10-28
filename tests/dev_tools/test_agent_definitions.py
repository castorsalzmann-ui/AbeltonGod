"""Agent definitions in .claude/agents/ follow the flat team of D-017."""

import re
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
# Tool names that let an agent start helpers or sub-agents (forbidden by D-017).
# `Task` is the older name of `Agent`; `Agent(x)` restricts nothing for spawning.
SPAWN_TOOLS = {"agent", "task"}
WRITE_TOOLS = {"edit", "write", "notebookedit"}


def frontmatter(path: Path) -> dict[str, str]:
    """Minimal parser for the frontmatter we write: `key: value`, `#` comments,
    and folded/literal blocks (`key: >` or `key: |` followed by indented lines)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].strip() == "---", f"{path.name}: no frontmatter"
    end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    fields: dict[str, str] = {}
    key = None
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1].isspace() and key is not None:  # continuation of a block value
            fields[key] = (fields[key] + " " + line.strip()).strip()
            continue
        k, sep, value = line.partition(":")
        assert sep, f"{path.name}: malformed frontmatter line {line!r}"
        key = k.strip()
        value = value.strip()
        fields[key] = "" if value in (">", "|", ">-", "|-") else value
    return fields


def tool_names(path: Path) -> list[str]:
    """Bare tool names, lower-case: `Agent(qa-tester)` -> `agent`, list form allowed."""
    raw = frontmatter(path).get("tools", "").strip().strip("[]")
    # Separators: commas (flow form) and "- " items (an indented YAML block list).
    items = re.split(r",|(?:^|\s)-\s+", raw)
    names = [re.split(r"[\s(]", t.strip().strip("'\""), maxsplit=1)[0] for t in items]
    return [n.lower() for n in names if n]


def test_exactly_the_d017_roles_exist() -> None:
    assert {p.stem for p in AGENTS.glob("*.md")} == ROLES


@pytest.mark.parametrize("role", sorted(ROLES))
def test_frontmatter_is_complete(role: str) -> None:
    fields = frontmatter(AGENTS / f"{role}.md")
    assert fields.get("name") == role
    assert len(fields.get("description", "")) > 20
    # An omitted or empty tools list inherits every tool, including the spawn tool.
    assert tool_names(AGENTS / f"{role}.md"), f"{role}: needs a non-empty tools list"


@pytest.mark.parametrize("role", sorted(ROLES))
def test_no_agent_can_start_helpers(role: str) -> None:
    assert not set(tool_names(AGENTS / f"{role}.md")) & SPAWN_TOOLS


def test_reviewer_cannot_edit_files() -> None:
    assert not set(tool_names(AGENTS / "reviewer.md")) & WRITE_TOOLS


@pytest.mark.parametrize("role", sorted(ROLES - {"reviewer"}))
def test_workers_can_run_skills(role: str) -> None:
    # /finish-task and /start-task are skills; without the Skill tool a subagent cannot run them.
    assert "skill" in tool_names(AGENTS / f"{role}.md")


@pytest.mark.parametrize(
    "tools",
    ["Read, Agent", "Read, Agent(qa-tester)", "Read, Task(reviewer)", "[Read, Agent]",
     "Read, 'Agent'"],
)
def test_spawn_detection_catches_every_spelling(tmp_path: Path, tools: str) -> None:
    f = tmp_path / "x.md"
    f.write_text(f"---\nname: x\ndescription: d\ntools: {tools}\n---\n", encoding="utf-8")
    assert set(tool_names(f)) & SPAWN_TOOLS


def test_spawn_detection_catches_a_block_list(tmp_path: Path) -> None:
    f = tmp_path / "x.md"
    text = "---\nname: x\ndescription: d\ntools:\n  - Read\n  - Agent\n---\n"
    f.write_text(text, encoding="utf-8")
    assert tool_names(f) == ["read", "agent"]


def test_reviewer_keeps_its_minimum_tools() -> None:
    assert {"read", "bash"} <= set(tool_names(AGENTS / "reviewer.md"))


def test_claude_md_has_one_role_line_per_role() -> None:
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    for role in ROLES:
        assert re.search(rf"^- `{re.escape(role)}` — ", text, re.M), role
