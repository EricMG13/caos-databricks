"""Write the parity goldens for every group from one package (spec section 10).

Run once against the read-only legacy snapshot, under its own interpreter, and
commit the result under `tests/parity/golden/`:

    LEGACY=<snapshot>/repo; TMP="$(mktemp -d)"
    uv venv --python 3.14 "$TMP/venv"
    uv pip install --python "$TMP/venv" --require-hashes --only-binary :all: \\
        -r "$LEGACY/requirements.txt"
    PYTHONDONTWRITEBYTECODE=1 "$TMP/venv/bin/python" tests/parity/generate_goldens.py \\
        --package server --root "$LEGACY" --out tests/parity/golden

`--root` is put at the front of `sys.path` (with its `tests/` directory, for
the fixture modules) before `--package` is imported, and the import is refused
when the package found does not live under that root. The same command with
`--package caos --root .` regenerates from the new package, which is what the
group tests do case by case.

`--request-ceiling BYTES` sets the transport ceiling on the loaded package
before any case runs, so a ceiling decision (D29 raised it to 4 MiB) is priced
by the legacy snapshot's own arithmetic rather than rewritten from the rebuilt
package. D29 regenerated `pricing` with:

    ... tests/parity/generate_goldens.py --package server --root "$LEGACY" \\
        --out tests/parity/golden --group pricing --request-ceiling 4194304
"""

from __future__ import annotations

import argparse
import importlib
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parity.cases import GROUP_NAMES, GROUPS, Json, Target, compute
from parity.goldens import GOLDEN_DIR, write_group


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--package", choices=("server", "caos"), required=True)
    parser.add_argument("--root", type=Path, required=True, help="repository root")
    parser.add_argument("--out", type=Path, default=GOLDEN_DIR)
    parser.add_argument(
        "--group", action="append", choices=GROUP_NAMES, help="one group; default all"
    )
    parser.add_argument(
        "--request-ceiling",
        type=int,
        help="the transport ceiling to price under (bytes); default the package's",
    )
    return parser.parse_args(argv)


def set_request_ceiling(target: Target, ceiling: int) -> None:
    """Price every case under `ceiling`, in the loaded package's own modules.

    `pricing` imports the constant by name from `provider`, so both bindings
    are set; nothing else in the package is changed.
    """
    if isinstance(ceiling, bool) or not isinstance(ceiling, int) or ceiling < 1:
        message = f"a request ceiling is a positive byte count, not {ceiling!r}"
        raise ValueError(message)
    for module in ("provider", "pricing"):
        vars(target.module(module))["MAX_REQUEST_BYTES"] = ceiling


def load_target(package: str, root: Path) -> Target:
    """Import `package` from `root`, refusing any other copy on the path."""
    root = root.resolve()
    for entry in (root / "tests", root):
        sys.path.insert(0, str(entry))
    target = Target(importlib.import_module(package))
    if target.root != root:
        message = f"{package} was imported from {target.root}, not {root}"
        raise ValueError(message)
    return target


def generate(
    target: Target, out: Path, groups: Sequence[str] = GROUP_NAMES
) -> dict[str, dict[str, str]]:
    """Compute and write every case of each group; return the manifests' cases."""
    manifests: dict[str, dict[str, str]] = {}
    for group in groups:
        outputs: dict[str, Json] = {
            name: compute(target, group, name) for name in GROUPS[group]
        }
        manifests[group] = write_group(group, outputs, package=target.name, base=out)
        print(f"{group}: {len(outputs)} cases -> {out / group}")
    return manifests


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    target = load_target(args.package, args.root)
    if args.request_ceiling is not None:
        set_request_ceiling(target, args.request_ceiling)
    generate(target, args.out, args.group or GROUP_NAMES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
