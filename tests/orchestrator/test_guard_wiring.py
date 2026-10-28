"""Static check (#78, D-011): no code path in ``src/`` calls the model or a tool handler outside
the two guarded places. This is the CI half of "no code path bypasses the guard"; the reviewer
does the other half.

Rules checked on the AST of every module under ``src/``:

1. ``.complete(...)`` (the ``ModelClient`` call) appears only in ``Orchestrator._call_model``,
   and there only after ``before_model_call`` and before ``after_model_call``.
2. ``.handler(...)`` (a tool handler) appears only in ``Toolbox.run``, after ``before_tool``.
3. ``Toolbox.run`` calls ``before_tool`` as its first guard-relevant step: before the lookup
   result is used, before validation, approval and the handler.
4. ``Orchestrator`` runs tools only through ``self.toolbox.run``.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"


def _modules() -> list[tuple[Path, ast.Module]]:
    return [(p, ast.parse(p.read_text("utf-8"))) for p in sorted(SRC.rglob("*.py"))]


def _calls_named(tree: ast.AST, attr: str) -> list[ast.Call]:
    return [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr
    ]


def _enclosing_functions(tree: ast.Module) -> dict[int, str]:
    """id(call node) -> 'Class.method' (or 'function') that contains it."""
    owner: dict[int, str] = {}

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, f"{child.name}.")
            elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                name = f"{prefix}{child.name}"
                for sub in ast.walk(child):
                    owner.setdefault(id(sub), name)
                visit(child, f"{name}.")
            else:
                visit(child, prefix)

    visit(tree, "")
    return owner


def _sites(attr: str) -> list[tuple[str, str, int]]:
    found = []
    for path, tree in _modules():
        owner = _enclosing_functions(tree)
        for node in _calls_named(tree, attr):
            found.append((path.relative_to(SRC).as_posix(), owner.get(id(node), "<module>"),
                          node.lineno))
    return found


def _function(module: str, qualname: str) -> ast.FunctionDef:
    tree = ast.parse((SRC / module).read_text("utf-8"))
    cls, _, meth = qualname.partition(".")
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == meth:
                    return item
    raise AssertionError(f"{qualname} not found in {module}")


def _first_line(fn: ast.FunctionDef, attr: str) -> int:
    lines = [c.lineno for c in _calls_named(fn, attr)]
    assert lines, f"{fn.name} never calls {attr}"
    return min(lines)


def test_model_is_called_only_in_the_guarded_call_site():
    sites = _sites("complete")
    assert sites, "no model call found at all - the check would be vacuous"
    assert {(m, f) for m, f, _ in sites} == {("orchestrator/loop.py", "Orchestrator._call_model")}
    fn = _function("orchestrator/loop.py", "Orchestrator._call_model")
    complete = _first_line(fn, "complete")
    assert _first_line(fn, "before_model_call") < complete
    settles = [c.lineno for c in _calls_named(fn, "after_model_call")]
    assert any(line > complete for line in settles)


def test_tool_handlers_are_called_only_by_the_guarded_toolbox():
    sites = _sites("handler")
    assert {(m, f) for m, f, _ in sites} == {("orchestrator/tools.py", "Toolbox.run")}
    fn = _function("orchestrator/tools.py", "Toolbox.run")
    before = _first_line(fn, "before_tool")
    for attr in ("handler", "confirm", "after_tool"):
        assert before < _first_line(fn, attr), attr
    # validation happens after before_tool, so rejected calls are counted too
    validation = [c.lineno for c in ast.walk(fn)
                  if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                  and c.func.id == "validation_errors"]
    assert validation and before < min(validation)
    # every return path after before_tool settles the call
    assert len(_calls_named(fn, "after_tool")) >= 5


def test_orchestrator_runs_tools_only_through_the_toolbox():
    loop = ast.parse((SRC / "orchestrator/loop.py").read_text("utf-8"))
    runs = _calls_named(loop, "run")
    assert runs, "loop never runs a tool"
    for node in runs:
        assert ast.unparse(node.func) == "self.toolbox.run"
    assert not _calls_named(loop, "handler")


def test_tool_handlers_are_not_exposed_through_other_names():
    """A handler reached through getattr or a renamed attribute would dodge rule 2."""
    for path, tree in _modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and (
                node.func.id == "getattr" and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in ("handler", "complete")
            ):
                raise AssertionError(
                    f"{path}:{node.lineno} reaches {node.args[1].value} by getattr"
                )
