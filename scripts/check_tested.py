#!/usr/bin/env python3
"""Refuse a public function or class that no test names.

Logic and correctness errors are ~75% more frequent in agent-written code
(docs/AI_CODE_QUALITY.md section 1), and the control is a test that was watched
to fail. This gate cannot see whether a test was written first; it can and does
refuse the case where no test mentions the symbol at all.

Scope is module-level definitions. Methods are covered through the class that
holds them -- see the known-gaps ledger in CLAUDE.md.

The axis is a *reference*, not a mention. This gate used to search every byte
of the suite for the symbol's name, and on 17 September 2026 that passed
`canonical._within_reservation` -- the guard that stops a rebuilt prompt going
out under too small a reservation, which is invariant 8's whole claim on that
path -- with no test driving it, because the name appeared in a **comment** in
`caos/graph/runtime.py`. A sentence about the code satisfied the check for
the code. Names are resolved through the AST now, so a comment, a docstring and
a prose string satisfy nothing.

What is still admitted from a string is a dotted identifier path, because
`monkeypatch.setattr("caos.store.runs.append", ...)` is a real reference and
Python gives it no other spelling. A path is `a.b.c` and prose is not, so the
axis holds.

And a reference names its module (DQ-11, FP-18). One set of bare names served
the whole suite, so `def verify` anywhere was cleared by the suite's references
to `caos.deliverable.verify_package.verify`. A reference is resolved through
the importing file's own bindings to `module.name` -- `from m import f`, an
`import m as x` followed by `x.f`, `setattr(x, "f", ...)`, a dotted string --
and through the re-exports of the module it was imported from, and a definition
is cleared only by a reference to it in its own module. The definitions are
every module-level public function, class and lambda, those under a module-level
`if` or `try` included, and a route is a handler registered on an `APIRouter`
or `FastAPI` object the module made -- not any decorator spelled `.get(...)`.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

from tracked import tracked_python

REPO = Path(__file__).resolve().parents[1]

# CLI entry points are exercised end to end by driving the script as a
# subprocess, which names the file rather than the function.
EXEMPT = frozenset({"main"})

# A route handler is reached by its path and never by its name, the way a React
# component is reached by rendering -- `frontend/scripts/check-tested.mjs` states
# the same rule for the same reason. Demanding a test name it buys an import and
# no coverage, while what actually drives these is an HTTP request in
# `tests/test_api_routes.py` and every section suite.
ROUTE_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})

# The objects a route is registered on. A handler decorated `@cache.get(...)` is
# not a route because the decorator is spelled like one (DQ-11).
ROUTERS = frozenset({"APIRouter", "FastAPI"})

# Directories on the import path by themselves: `scripts/qualify.py` is imported
# as `qualify`, and a test helper as its own stem.
PATH_ENTRIES = frozenset({"scripts", "tests"})

# Never walked for re-exports: not ours, or not source.
_UNWALKED = frozenset({"vendor", "node_modules", "__pycache__"})

type Definition = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def _module_body(nodes: list[ast.stmt]) -> Iterator[ast.stmt]:
    """Module-level statements, through the `if` and `try` blocks that hold them.

    A `def` under `if TYPE_CHECKING:` or a `try` import fallback is as public as
    one at column zero, and only `tree.body` was walked (DQ-11).
    """
    for node in nodes:
        yield node
        if isinstance(node, ast.If):
            yield from _module_body(node.body)
            yield from _module_body(node.orelse)
        elif isinstance(node, ast.Try | ast.TryStar):
            yield from _module_body(node.body)
            for handler in node.handlers:
                yield from _module_body(handler.body)
            yield from _module_body(node.orelse)
            yield from _module_body(node.finalbody)


def _routers(statements: list[ast.stmt]) -> frozenset[str]:
    """Module-level names bound to an `APIRouter(...)` or `FastAPI(...)`."""
    names: set[str] = set()
    for node in statements:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        made = node.value.func
        made_name = made.attr if isinstance(made, ast.Attribute) else None
        if isinstance(made, ast.Name):
            made_name = made.id
        if made_name in ROUTERS:
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return frozenset(names)


def _is_route(node: Definition, routers: frozenset[str] = frozenset()) -> bool:
    """Whether `node` is registered on a router this module made."""
    return any(
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr in ROUTE_METHODS
        and isinstance(decorator.func.value, ast.Name)
        and decorator.func.value.id in routers
        for decorator in node.decorator_list
    )


def _defined(node: ast.stmt, routers: frozenset[str]) -> list[tuple[int, str]]:
    """The public names one module-level statement defines."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return [] if _is_route(node, routers) else [(node.lineno, node.name)]
    if isinstance(node, ast.Assign | ast.AnnAssign) and isinstance(
        node.value, ast.Lambda
    ):
        # A module-level callable is a definition however it is spelled.
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return [(node.lineno, t.id) for t in targets if isinstance(t, ast.Name)]
    return []


def public_definitions(source: str, filename: str) -> list[tuple[int, str]]:
    """Module-level functions, classes and lambdas that form a file's public surface."""
    statements = list(_module_body(ast.parse(source, filename=filename).body))
    routers = _routers(statements)
    return [
        (lineno, name)
        for node in statements
        for lineno, name in _defined(node, routers)
        if not name.startswith("_") and name not in EXEMPT
    ]


def module_name(path: Path, root: Path) -> str:
    """The name `path` is imported under, from a tree rooted at `root`.

    `caos/store/runs.py` is `caos.store.runs`; a package is its directory; a
    script and a test helper are their stems, because `scripts/` and `tests/`
    are on the import path themselves. A file outside `root` is its stem.
    """
    try:
        parts = list(path.resolve().relative_to(root.resolve()).with_suffix("").parts)
    except ValueError:
        return path.stem
    if parts and parts[0] in PATH_ENTRIES:
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or path.stem


def _imported(node: ast.Import | ast.ImportFrom) -> Iterator[tuple[str, str]]:
    """`(bound name, what it names)` for one import statement."""
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.asname is None:
                head = alias.name.partition(".")[0]
                yield head, head
            else:
                yield alias.asname, alias.name
        return
    source = node.module or ""
    for alias in node.names:
        if alias.name != "*":
            yield alias.asname or alias.name, f"{source}.{alias.name}".lstrip(".")


def bindings(nodes: Iterable[ast.AST]) -> dict[str, str]:
    """Every name the imports among `nodes` bind, to what each names."""
    found: dict[str, str] = {}
    for node in nodes:
        if isinstance(node, ast.Import | ast.ImportFrom):
            found.update(_imported(node))
    return found


# A string the suite may reference a symbol through: a dotted identifier path,
# which is what `monkeypatch.setattr` and `mock.patch` take. Anchored at both
# ends and requiring a dot, so an English sentence naming the symbol is not one.
DOTTED_PATH = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\Z")
IDENTIFIER = re.compile(r"[A-Za-z_]\w*\Z")


def _chain(node: ast.expr) -> list[str] | None:
    """`a.b.c` as `["a", "b", "c"]`, or None for anything but names and dots."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        head = _chain(node.value)
        return None if head is None else [*head, node.attr]
    return None


def _qualified(parts: list[str], bound: dict[str, str]) -> list[str]:
    """Each prefix of a chain rooted at an imported name, qualified."""
    if parts[0] not in bound:
        return []
    root = bound[parts[0]]
    return [".".join([root, *parts[1:end]]) for end in range(1, len(parts) + 1)]


def _referenced_by(node: ast.AST, bound: dict[str, str]) -> list[str]:
    """The qualified names one node uses. Loads only (F63): a local a test
    assigns, a parameter or a loop variable that happens to share a public name
    clears nothing."""
    if isinstance(node, ast.Name | ast.Attribute):
        parts = _chain(node) if isinstance(node.ctx, ast.Load) else None
        return [] if parts is None else _qualified(parts, bound)
    if isinstance(node, ast.alias):
        return []  # read with its statement, where the module is known
    if isinstance(node, ast.Import | ast.ImportFrom):
        return [named for _bound, named in _imported(node)]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value] if DOTTED_PATH.match(node.value) else []
    if isinstance(node, ast.Call) and len(node.args) >= 2:
        return _named_attribute(node.args[0], node.args[1], bound)
    return []


def _named_attribute(
    target: ast.expr, attribute: ast.expr, bound: dict[str, str]
) -> list[str]:
    """`setattr(module, "name", ...)`, `getattr`, `patch.object`: an object and
    one of its attributes, spelled as a string."""
    parts = _chain(target)
    if (
        parts is None
        or not isinstance(attribute, ast.Constant)
        or not isinstance(attribute.value, str)
        or not IDENTIFIER.match(attribute.value)
    ):
        return []
    return [f"{q}.{attribute.value}" for q in _qualified(parts, bound)[-1:]]


def _reexports(root: Path, tests_dir: Path) -> dict[str, dict[str, str]]:
    """Each module's import bindings under `root`, the suite excluded.

    What a module imports is what a test importing it by that module reaches:
    `from caos.api.app import store_connection` names `caos.api.deps`'s.
    """
    found: dict[str, dict[str, str]] = {}
    for directory, subdirectories, files in os.walk(root):
        here = Path(directory)
        subdirectories[:] = [
            name
            for name in subdirectories
            if not name.startswith(".")
            and name not in _UNWALKED
            and here / name != tests_dir
        ]
        for file in files:
            if file.endswith(".py"):
                path = here / file
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                # Module level only: an import inside a function re-exports
                # nothing, and one sharing a name the module defines would
                # carry a reference to that definition somewhere else.
                found[module_name(path, root)] = bindings(_module_body(tree.body))
    return found


def canonical(name: str, reexports: dict[str, dict[str, str]]) -> str:
    """`name` followed through the imports of the modules it passes through.

    The longest module prefix that binds the next segment by import is replaced
    by what that import names, until nothing does. Bounded, so a cycle of
    re-exports ends.
    """
    for _ in range(16):
        parts = name.split(".")
        for end in range(len(parts) - 1, 0, -1):
            named = reexports.get(".".join(parts[:end]), {}).get(parts[end])
            if named is not None and named != ".".join(parts[: end + 1]):
                name = ".".join([named, *parts[end + 1 :]])
                break
        else:
            return name
    return name


def referenced_names(tests_dir: Path, root: Path | None = None) -> frozenset[str]:
    """Every `module.name` the suite references, resolved through each test's
    own imports and the re-exports of the modules they name.

    An import, an imported name or a chain from one, a dotted path in a string,
    and an object's attribute named by string beside it. Not a comment, not a
    docstring, not prose -- which is the whole difference between this and the
    byte search it replaces -- and not a bare name nothing imported.
    """
    base = tests_dir.parent if root is None else root
    reexports = _reexports(base, tests_dir)
    names: set[str] = set()
    for path in sorted(tests_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        # Anywhere in the test: a suite imports inside the test that uses it.
        bound = bindings(ast.walk(tree))
        for node in ast.walk(tree):
            for name in _referenced_by(node, bound):
                names.add(name)
                names.add(canonical(name, reexports))
    return frozenset(names)


def untested(path: Path, referenced: frozenset[str], root: Path = REPO) -> list[str]:
    """One line per public definition in `path` no test references in its module."""
    source = path.read_text(encoding="utf-8")
    module = module_name(path, root)
    return [
        f"{path}:{lineno}: {name!r} has no test referencing it"
        for lineno, name in public_definitions(source, str(path))
        if f"{module}.{name}" not in referenced
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--tests", type=Path, default=REPO / "tests")
    args = parser.parse_args(argv)

    tests_dir = args.tests.resolve()
    root = tests_dir.parent
    paths = args.paths or [
        p for p in tracked_python(REPO) if not p.is_relative_to(tests_dir)
    ]
    if not paths:
        print(
            "scanned no files; a scan that scanned nothing is a failure",
            file=sys.stderr,
        )
        return 2

    referenced = (
        referenced_names(tests_dir, root) if tests_dir.is_dir() else frozenset()
    )
    # A reader that matched too little must fail rather than pass vacuously: an
    # empty reference set clears every definition below. The condition is that
    # the reader *read something and extracted nothing* -- a suite with no
    # Python files at all has nothing to extract, and refusing there would
    # answer about the reader when the caller simply named an empty directory.
    if any(tests_dir.rglob("*.py")) and not referenced:
        print(
            f"{tests_dir} yielded no referenced names; a reader that read"
            " nothing is a failure",
            file=sys.stderr,
        )
        return 2
    found = [line for path in paths for line in untested(path, referenced, root)]
    for line in found:
        print(line)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
