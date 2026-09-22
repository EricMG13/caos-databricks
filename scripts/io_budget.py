#!/usr/bin/env python3
"""Refuse a server that declares no I/O budget for its request paths.

Excessive I/O is the largest single multiple in the measurements behind
docs/AI_CODE_QUALITY.md (~8x), and the predecessor had exactly that defect:
evidence blocks lived in one JSON column, so `read_evidence` parsed every block
of a source on every call.

Every module under `caos/api/` declares `IO_BUDGET`, the number of store
round-trips a request through it may cost. A module that makes no round trip
declares `0`: zero is a cost, and stating it is cheaper than proving an
exemption.

Every module rather than every module a heuristic recognises as serving a path.
"It declares no route decorator" and "it never names the store" are both things
a module can stop being true of without anyone noticing, so a gate resting on
either is one the next request path can be written around -- which is exactly
what the weaker floor this replaces allowed. The floor is the route directory,
not the whole server: a store module has no request path, and `caos/api/` is
the one directory where every file is on one.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DECLARATION = "IO_BUDGET"


def declares_budget(source: str, filename: str) -> bool:
    """True when a module assigns `IO_BUDGET` at module level."""
    tree = ast.parse(source, filename=filename)
    targets = (
        target
        for node in tree.body
        if isinstance(node, ast.Assign | ast.AnnAssign)
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
    )
    return any(isinstance(t, ast.Name) and t.id == DECLARATION for t in targets)


def _budgeted_modules(api: Path) -> tuple[list[Path], list[Path]]:
    """Route modules split into those declaring a budget and those not."""
    modules = sorted(p for p in api.rglob("*.py") if p.name != "__init__.py")
    declared = [
        p for p in modules if declares_budget(p.read_text(encoding="utf-8"), str(p))
    ]
    return declared, modules


def undeclared(api: Path) -> list[Path]:
    """Route modules with no `IO_BUDGET`. Named, so a refusal can be acted on."""
    declared, modules = _budgeted_modules(api)
    return [module for module in modules if module not in declared]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assert", dest="assert_", action="store_true")
    parser.add_argument("--root", type=Path, default=REPO)
    args = parser.parse_args(argv)

    api = args.root / "server" / "api"
    if not api.is_dir():
        print("no request paths yet; nothing to budget")
        return 0

    declared, modules = _budgeted_modules(api)
    missing = undeclared(api)
    if missing:
        names = ", ".join(str(module.relative_to(api)) for module in missing)
        print(
            f"{api}: {len(missing)} of {len(modules)} module(s) declare no "
            f"{DECLARATION}: {names}; every request path needs a declared I/O "
            "budget, and a path that makes no round trip declares 0",
            file=sys.stderr,
        )
        return 1 if args.assert_ else 0
    print(f"all {len(declared)} route module(s) declare {DECLARATION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
