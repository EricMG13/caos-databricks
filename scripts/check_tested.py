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
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
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


def _is_route(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> bool:
    """Whether `node` carries an HTTP-method decorator (`@router.get(...)`)."""
    return any(
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr in ROUTE_METHODS
        for decorator in node.decorator_list
    )


def public_definitions(source: str, filename: str) -> list[tuple[int, str]]:
    """Module-level functions and classes that form a file's public surface."""
    tree = ast.parse(source, filename=filename)
    definitions = (
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    )
    return [
        (node.lineno, node.name)
        for node in definitions
        if not node.name.startswith("_")
        and node.name not in EXEMPT
        and not _is_route(node)
    ]


# A string the suite may reference a symbol through: a dotted identifier path,
# which is what `monkeypatch.setattr` and `mock.patch` take. Anchored at both
# ends and requiring a dot, so an English sentence naming the symbol is not one.
DOTTED_PATH = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\Z")


def referenced_names(tests_dir: Path) -> frozenset[str]:
    """Every name the suite references, resolved through each test's own AST.

    A bare name, an attribute's final segment, an import's bound name, and the
    last segment of a dotted path given as a string. Not a comment, not a
    docstring, not prose -- which is the whole difference between this and the
    byte search it replaces.
    """
    names: set[str] = set()
    for path in sorted(tests_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names.update(_referenced_by(node))
    return frozenset(names)


def _referenced_by(node: ast.AST) -> list[str]:
    """The names one node uses. Loads only (F63): a local a test assigns, a
    parameter or a loop variable that happens to share a public name clears
    nothing."""
    if isinstance(node, ast.Name):
        return [node.id] if isinstance(node.ctx, ast.Load) else []
    if isinstance(node, ast.Attribute):
        return [node.attr] if isinstance(node.ctx, ast.Load) else []
    if isinstance(node, ast.alias):
        return [node.asname or node.name.rpartition(".")[2]]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if DOTTED_PATH.match(node.value):
            return [node.value.rpartition(".")[2]]
    return []


def untested(path: Path, referenced: frozenset[str]) -> list[str]:
    """One line per public definition in `path` the suite never references."""
    source = path.read_text(encoding="utf-8")
    return [
        f"{path}:{lineno}: {name!r} has no test referencing it"
        for lineno, name in public_definitions(source, str(path))
        if name not in referenced
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--tests", type=Path, default=REPO / "tests")
    args = parser.parse_args(argv)

    tests_dir = args.tests.resolve()
    paths = args.paths or [
        p for p in tracked_python(REPO) if not p.is_relative_to(tests_dir)
    ]
    if not paths:
        print(
            "scanned no files; a scan that scanned nothing is a failure",
            file=sys.stderr,
        )
        return 2

    referenced = referenced_names(tests_dir) if tests_dir.is_dir() else frozenset()
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
    found = [line for path in paths for line in untested(path, referenced)]
    for line in found:
        print(line)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
