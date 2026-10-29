"""Static check (#78, D-011): no code path in ``src/`` reaches the model or a tool handler outside
the two guarded places. This is the CI half of "no code path bypasses the guard"; the reviewer
does the other half.

Rules checked on the AST of every module under ``src/`` (``violations``):

1. **Any attribute access** ``.complete`` / ``.handler`` (call, alias ``f = m.complete``,
   argument, return value) appears exactly once each: ``self.model.complete(...)`` in
   ``Orchestrator._call_model`` and ``tool.handler(...)`` in ``Toolbox.run``.
2. No dynamic attribute access that could reach them by another route: ``getattr`` /
   ``setattr`` / ``hasattr`` / ``delattr`` with a computed name or with one of the two names,
   ``operator.attrgetter`` / ``methodcaller``, ``__getattribute__``, ``__dict__``, ``vars()``.
3. Order inside the two sites: ``before_model_call`` < ``complete`` < ``after_model_call``;
   ``before_tool`` before validation, approval, handler and ``after_tool``.
4. ``Orchestrator`` runs tools only through ``self.toolbox.run``.

Also caught (review round 2): ``getattr``/``setattr``/``hasattr``/``delattr`` used other than
as a direct call (alias ``g = getattr``), any attribute of a dynamic-access name
(``builtins.getattr``, ``inspect.getattr_static``, ``operator.attrgetter``), ``from … import
<one of them> [as x]``, and ``match`` class patterns with a ``complete=`` / ``handler=``
keyword.

The bad-snippet tests at the end prove each rule turns red (review of PR #89, finding 2).

**What this check cannot see** (it is a syntax check, not a proof; the reviewer remains the
other half of the criterion):

- names built at runtime and resolved without a forbidden name: ``eval``/``exec``/``compile``
  of strings, ``__import__``/``importlib`` returning ``builtins``, ``globals()["getattr"]``,
  ``__builtins__`` lookups;
- reaching a handler through a container or object that is not spelled ``.handler`` (e.g. a
  ``functools.partial`` or a dict of callables built from tool objects elsewhere);
- code outside ``src/`` (tests, scripts) and C extensions or third-party packages (the future
  Agent SDK adapter must call into ``Toolbox.run``; its own wiring test is a step-2 item).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
GUARDED = {"complete", "handler"}
ALLOWED_SITES = {
    ("orchestrator/loop.py", "Orchestrator._call_model", "self.model.complete"),
    ("orchestrator/tools.py", "Toolbox.run", "tool.handler"),
}
DYNAMIC_ATTR_FUNCS = {"getattr", "setattr", "hasattr", "delattr"}
FORBIDDEN_NAMES = {"attrgetter", "methodcaller", "vars", "__getattribute__", "getattr_static"}
DYNAMIC_NAMES = DYNAMIC_ATTR_FUNCS | FORBIDDEN_NAMES


def _modules() -> list[tuple[str, ast.Module]]:
    return [
        (p.relative_to(SRC).as_posix(), ast.parse(p.read_text("utf-8")))
        for p in sorted(SRC.rglob("*.py"))
    ]


def _owners(tree: ast.Module) -> dict[int, str]:
    """id(node) -> innermost 'Class.method' / 'function' that contains it."""
    owner: dict[int, str] = {}

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.")
            elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                name = f"{prefix}{child.name}"
                for sub in ast.walk(child):
                    owner[id(sub)] = name  # inner definitions overwrite outer ones below
                visit(child, f"{name}.")
            else:
                visit(child, prefix)

    visit(tree, "")
    return owner


def violations(modules: list[tuple[str, ast.Module]]) -> list[str]:
    found: list[str] = []
    seen_sites: list[tuple[str, str, str]] = []
    for rel, tree in modules:
        owner = _owners(tree)
        parents = {id(c): p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
        for node in ast.walk(tree):
            where = f"{rel}:{getattr(node, 'lineno', '?')}"
            if isinstance(node, ast.Attribute):
                if node.attr in GUARDED:
                    site = (rel, owner.get(id(node), "<module>"), ast.unparse(node))
                    parent = parents.get(id(node))
                    is_call = isinstance(parent, ast.Call) and parent.func is node
                    if site in ALLOWED_SITES and is_call:
                        seen_sites.append(site)
                    else:
                        found.append(f"{where} {ast.unparse(node)} outside the guarded site")
                if node.attr == "__dict__" or node.attr in DYNAMIC_NAMES:
                    found.append(f"{where} {node.attr} access")
            elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
                found.append(f"{where} uses {node.id}")
            elif isinstance(node, ast.Name) and node.id in DYNAMIC_ATTR_FUNCS and not (
                isinstance(parents.get(id(node)), ast.Call)
                and parents[id(node)].func is node
            ):
                found.append(f"{where} {node.id} used other than as a direct call (alias)")
            elif isinstance(node, ast.ImportFrom) and any(
                a.name in DYNAMIC_NAMES for a in node.names
            ):
                found.append(f"{where} imports a dynamic attribute accessor")
            elif isinstance(node, ast.MatchClass) and set(node.kwd_attrs) & GUARDED:
                found.append(f"{where} match pattern binds {set(node.kwd_attrs) & GUARDED}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and (
                node.func.id in DYNAMIC_ATTR_FUNCS
            ):
                name = node.args[1] if len(node.args) >= 2 else None
                if not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
                    found.append(f"{where} {node.func.id} with a computed attribute name")
                elif name.value in GUARDED or name.value.startswith("__"):
                    found.append(f"{where} {node.func.id}(..., {name.value!r})")
    for site in ALLOWED_SITES:
        count = seen_sites.count(site)
        if count != 1:
            found.append(f"guarded site {site} found {count} times, expected exactly 1")
    return found


# --- the real tree ------------------------------------------------------------------------


def test_src_has_no_unguarded_route_to_the_model_or_a_handler():
    assert violations(_modules()) == []


def _function(module: str, qualname: str) -> ast.FunctionDef:
    tree = ast.parse((SRC / module).read_text("utf-8"))
    cls, _, meth = qualname.partition(".")
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == meth:
                    return item
    raise AssertionError(f"{qualname} not found in {module}")


def _call_lines(fn: ast.AST, attr: str) -> list[int]:
    return [
        n.lineno for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr
    ]


def _first(fn: ast.AST, attr: str) -> int:
    lines = _call_lines(fn, attr)
    assert lines, f"never calls {attr}"
    return min(lines)


def test_model_call_sits_between_its_guard_steps():
    fn = _function("orchestrator/loop.py", "Orchestrator._call_model")
    complete = _first(fn, "complete")
    assert _first(fn, "before_model_call") < complete
    assert any(line > complete for line in _call_lines(fn, "after_model_call"))


def test_toolbox_calls_before_tool_first():
    fn = _function("orchestrator/tools.py", "Toolbox.run")
    before = _first(fn, "before_tool")
    for attr in ("handler", "confirm", "after_tool"):
        assert before < _first(fn, attr), attr
    validation = [c.lineno for c in ast.walk(fn)
                  if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                  and c.func.id == "validation_errors"]
    assert validation and before < min(validation)
    assert len(_call_lines(fn, "after_tool")) >= 5  # every return path settles the call


def test_orchestrator_runs_tools_only_through_the_toolbox():
    loop = ast.parse((SRC / "orchestrator/loop.py").read_text("utf-8"))
    runs = [n for n in ast.walk(loop) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == "run"]
    assert runs, "loop never runs a tool"
    assert {ast.unparse(n.func) for n in runs} == {"self.toolbox.run"}


# --- the check itself can fail ------------------------------------------------------------


def _with_extra(rel: str, source: str) -> list[tuple[str, ast.Module]]:
    return _modules() + [(rel, ast.parse(source))]


@pytest.mark.parametrize(
    "source",
    [
        "def quick(model, request):\n    return model.complete(request)\n",
        "def quick(model, request):\n    f = model.complete\n    return f(request)\n",
        "def run_direct(tool, args):\n    h = tool.handler\n    return h(args)\n",
        "def quick(model, r):\n    return getattr(model, 'comp' + 'lete')(r)\n",
        "def quick(model, r):\n    return getattr(model, 'complete')(r)\n",
        "def quick(model, r, n):\n    return getattr(model, n)(r)\n",
        "from operator import methodcaller\nq = methodcaller('complete', 1)\n",
        "import operator\nq = operator.attrgetter('handler')\n",
        "def q(t, a):\n    return vars(t)['handler'](a)\n",
        "def q(t, a):\n    return t.__dict__['handler'](a)\n",
        "def q(t, a):\n    return type(t).__getattribute__(t, 'handler')(a)\n",
        "def q(t, a):\n    return [t.handler][0](a)\n",
        "class X:\n    def run(self, tool, a):\n        return tool.handler(a)\n",
        # review round 2 spellings
        "g = getattr\ndef q(m, r):\n    return g(m, 'complete')(r)\n",
        "import builtins\ndef q(m, r):\n    return builtins.getattr(m, 'complete')(r)\n",
        "from operator import attrgetter as ag\nq = ag('handler')\n",
        "def q(m, r):\n    match m:\n        case object(complete=f):\n            return f(r)\n",
        "import inspect\ndef q(m, r):\n    return inspect.getattr_static(m, 'complete')(m, r)\n",
        "from inspect import getattr_static\n",
    ],
)
def test_each_dodge_in_a_new_module_is_caught(source):
    assert violations(_with_extra("orchestrator/extra.py", source)), source


def test_a_second_call_in_the_allowed_function_is_caught():
    """The allowed site must stay unique: a second ``self.model.complete(...)`` (e.g. a retry
    outside the guard steps) in ``_call_model`` itself is flagged."""
    path = SRC / "orchestrator/loop.py"
    text = path.read_text("utf-8")
    old = "            response = self.model.complete(request)\n"
    assert text.count(old) == 1
    patched = text.replace(old, old + "            self.model.complete(request)\n")
    mods = [(r, t) for r, t in _modules() if r != "orchestrator/loop.py"]
    assert violations(mods + [("orchestrator/loop.py", ast.parse(patched))])


def test_removing_the_guarded_site_is_caught():
    mods = [(r, t) for r, t in _modules() if r != "orchestrator/tools.py"]
    assert violations(mods)
