"""Select exhaustive test-file shards and validate their coverage inputs for CI."""

from __future__ import annotations

import argparse
import sys
from hashlib import sha256
from pathlib import Path

from tracked import tracked_files

REPO = Path(__file__).resolve().parents[1]
SHARDS = 4


def shard_files(index: int, root: Path = REPO) -> list[str]:
    """Every tracked pytest file belongs to exactly one stable hash bucket."""
    if index not in range(SHARDS):
        message = "shard index must be 0 through 3"
        raise ValueError(message)
    files = sorted(
        name
        for name in tracked_files(root, "tests")
        if (Path(name).match("test_*.py") or Path(name).match("*_test.py"))
        and int.from_bytes(sha256(name.encode()).digest(), "big") % SHARDS == index
    )
    if not files:
        message = "empty test shard"
        raise ValueError(message)
    return files


def coverage_files(directory: Path) -> list[str]:
    """Refuse missing or duplicated shard data before coverage is combined."""
    files = sorted(directory.rglob(".coverage.shard-*"))
    expected = {f".coverage.shard-{index}" for index in range(SHARDS)}
    if len(files) != SHARDS or {path.name for path in files} != expected:
        message = "coverage requires exactly one data file from each shard"
        raise ValueError(message)
    return [str(path.resolve()) for path in files]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    shard = commands.add_parser("shard")
    shard.add_argument("index", type=int, choices=range(SHARDS))
    combine = commands.add_parser("coverage")
    combine.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    try:
        files = (
            shard_files(args.index)
            if args.command == "shard"
            else coverage_files(args.directory)
        )
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    print("\0".join(files), end="\0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
