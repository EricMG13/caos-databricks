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
    return parser.parse_args(argv)


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
    generate(target, args.out, args.group or GROUP_NAMES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
