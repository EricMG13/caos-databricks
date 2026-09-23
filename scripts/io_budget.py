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
the one directory where every file is on one -- its `__init__.py` files
included, since a package can serve a route as well as any module can.

And the value, not only the spelling. A declaration is read twice: as the
source states it, which refuses `float("inf")` and `None` where they are
written, and as Python evaluates it, which is the only reading that sees
`math.inf`, `~0` or `10 ** 100` for what they are. The evaluated value must be
a whole number of round trips between 0 and `CEILING`, or a map of them.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import sys
from hashlib import sha256
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DECLARATION = "IO_BUDGET"

# The most store round trips one request may be declared to cost. The widest
# declared today is the book's 598 (four credits' model reads); a number past
# this is not a budget anybody measured, and `10 ** 100` read as one (DQ-10).
CEILING = 1024

# Builders of a value that is not a count of round trips. `float("inf")` was
# accepted as a declared budget (FP-19), which is the declaration saying
# nothing in the one spelling that reads as saying something.
NOT_A_COUNT = frozenset({"float", "complex", "Decimal", "Fraction"})


def is_budget(value: ast.expr) -> bool:
    """Whether a declared value is a whole number of round trips, or a map of them.

    Judged on what the source states. A value computed from other names --
    `FIXED_IO + LITE_NODES * PER_HANDOFF_IO`, `max(SAVE_IO, ...)` -- is the
    module's own arithmetic over its own counts and is left to it; what is
    refused is a value stated here and now that is not a count.
    """
    if isinstance(value, ast.Constant):
        return type(value.value) is int and value.value >= 0
    if isinstance(value, ast.Dict):
        return bool(value.values) and all(is_budget(item) for item in value.values)
    if isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.USub):
        return False
    if isinstance(value, ast.Call):
        named = value.func
        return not (isinstance(named, ast.Name) and named.id in NOT_A_COUNT)
    return True


def declares_budget(source: str, filename: str) -> bool:
    """True when a module assigns `IO_BUDGET` a budget at module level.

    The declaration, not the name. `IO_BUDGET: int` with no value at all,
    `IO_BUDGET = None` and `IO_BUDGET = float("inf")` each satisfied a check
    that looked only for the name being a target, and each declares nothing
    (FP-19). Every assignment of the name has to be a budget: a module that
    states one and then replaces it with `None` has replaced its declaration.
    """
    tree = ast.parse(source, filename=filename)
    declared = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign | ast.AnnAssign)
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Name) and target.id == DECLARATION
    ]
    return bool(declared) and all(
        node.value is not None and is_budget(node.value) for node in declared
    )


def within(value: object) -> bool:
    """Whether an evaluated budget is a count in `[0, CEILING]`, or a map of them.

    `type(...) is int`, so neither `True` nor a float that happens to be whole
    is a number of round trips.
    """
    if isinstance(value, dict):
        return bool(value) and all(within(item) for item in value.values())
    return type(value) is int and 0 <= value <= CEILING


def declared_value(path: Path, root: Path) -> object:
    """The module's `IO_BUDGET` as Python evaluates it; `None` if it has none.

    Loaded from its file under a private name, with `root` first on the import
    path for the imports it makes, so a synthetic tree and this repository are
    read the same way and the module's own name is never shadowed. A module
    that raises while loading raises here: the gate fails rather than passing
    over a route it could not read.
    """
    name = "_io_budget_" + sha256(str(path).encode("utf-8")).hexdigest()[:16]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    sys.path.insert(0, str(root))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(root))
        del sys.modules[name]
    return getattr(module, DECLARATION, None)


def _budgeted_modules(api: Path) -> tuple[list[Path], list[Path]]:
    """Route modules split into those declaring a budget and those not.

    `__init__.py` too: a route declared in a package's own module was never
    read, which was FP-19's first bullet (DQ-10).
    """
    root = api.parents[1]
    modules = sorted(api.rglob("*.py"))
    declared = [
        p
        for p in modules
        if declares_budget(p.read_text(encoding="utf-8"), str(p))
        and within(declared_value(p, root))
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

    api = args.root / "caos" / "api"
    if not api.is_dir():
        # Not "nothing to budget": the route directory is the floor this gate
        # rests on, and a tree without one is a gate measuring nothing. That
        # branch exited 0 and let every route move out from under the check
        # (FP-19, SI-8).
        print(
            f"{api} is not a directory; there is no route floor to check",
            file=sys.stderr,
        )
        return 2

    declared, modules = _budgeted_modules(api)
    missing = undeclared(api)
    if missing:
        names = ", ".join(str(module.relative_to(api)) for module in missing)
        print(
            f"{api}: {len(missing)} of {len(modules)} module(s) declare no "
            f"{DECLARATION} between 0 and {CEILING}: {names}; every request path"
            " needs a declared I/O budget, and a path that makes no round trip"
            " declares 0",
            file=sys.stderr,
        )
        return 1 if args.assert_ else 0
    print(f"all {len(declared)} route module(s) declare {DECLARATION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
