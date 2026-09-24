#!/usr/bin/env python3
"""Whether redeploying an older commit is a valid rollback of a release (C1).

A release's first boot applies its migrations to the store, and the store
then refuses code whose migration list is any other (`apply_schema` answers
`STORE_SCHEMA_DRIFT` for a history longer than the code's own, and the app
does not start). Code from before DL-1 (F219) reads `public` rather than
`caos_store`, so it starts on an empty store beside the real one. A redeploy
is therefore a rollback only when the older commit carries exactly the
release's migrations, byte for byte and in order, and reads the same schema:

    uv run python scripts/rollback_check.py <older> [--release <commit>]

Run it from the release's own checkout, before checking the older commit
out (an older commit may not carry this script); `--release` defaults to
HEAD. Exit 0: redeploying `<older>` is a rollback. Exit 1: it is not; roll
forward with a fix, or restore the database (docs/DEPLOYMENT.md section 6).
Both commits are read through git; nothing is checked out or run.
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tracked import blob_at

REPO = Path(__file__).resolve().parents[1]
STORE = "caos/store"
# What code with no `STORE_SCHEMA` reads: Postgres's default search path.
PUBLIC = "public"


@dataclass(frozen=True, slots=True)
class StoreLayout:
    """What a commit's store module reads and migrates: the schema its
    connections search, and each migration's name with its body's digest,
    in `MIGRATIONS` order. `problem` is set when the module cannot be read."""

    schema: str
    migrations: tuple[tuple[str, str], ...]
    problem: str = ""


def _module_constants(tree: ast.Module) -> dict[str, ast.expr]:
    """Each module-level `NAME = <value>` of the store module, by name."""
    return {
        target.id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }


def _sql_file(value: ast.expr, constants: dict[str, ast.expr]) -> str:
    """The one `.sql` file name a migration's body is read from, following
    a bare name (`SCHEMA`) to its own assignment; `""` if there is not one."""
    if isinstance(value, ast.Name) and value.id in constants:
        value = constants[value.id]
    names = {
        node.value
        for node in ast.walk(value)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.endswith(".sql")
    }
    return names.pop() if len(names) == 1 else ""


def _migration_files(tree: ast.Module) -> list[tuple[str, str]] | None:
    """`MIGRATIONS` as (name, .sql file) pairs, or None when it is not a
    literal tuple of (name, body) pairs this reading can follow."""
    constants = _module_constants(tree)
    listed = constants.get("MIGRATIONS")
    if not isinstance(listed, ast.Tuple):
        return None
    pairs: list[tuple[str, str]] = []
    for entry in listed.elts:
        if not (isinstance(entry, ast.Tuple) and len(entry.elts) == 2):
            return None
        name, body = entry.elts
        file = _sql_file(body, constants)
        if not (
            isinstance(name, ast.Constant) and isinstance(name.value, str) and file
        ):
            return None
        pairs.append((name.value, file))
    return pairs


def store_layout(rev: str, repo: Path = REPO) -> StoreLayout:
    """The store schema `rev` reads and the migrations it applies, as git
    recorded them; a layout carrying a `problem` when they cannot be read."""
    source = blob_at(repo, rev, f"{STORE}/__init__.py")
    if source is None:
        return StoreLayout(
            "", (), f"{rev} has no {STORE}/__init__.py (or is not a commit)"
        )
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return StoreLayout("", (), f"{rev}'s {STORE}/__init__.py does not parse")
    files = _migration_files(tree)
    if files is None:
        return StoreLayout("", (), f"{rev}'s MIGRATIONS cannot be read")
    migrations: list[tuple[str, str]] = []
    for name, file in files:
        body = blob_at(repo, rev, f"{STORE}/{file}")
        if body is None:
            return StoreLayout("", (), f"{rev} names {file} but does not carry it")
        migrations.append((name, sha256(body.encode("utf-8")).hexdigest()))
    schema = _module_constants(tree).get("STORE_SCHEMA")
    read = schema.value if isinstance(schema, ast.Constant) else PUBLIC
    return StoreLayout(str(read), tuple(migrations))


def rollback_problems(
    older: str, release: str = "HEAD", repo: Path = REPO
) -> list[str]:
    """Why redeploying `older` over a store `release` migrated is not a
    rollback; an empty list when it is."""
    was, now = store_layout(older, repo), store_layout(release, repo)
    problems = [layout.problem for layout in (was, now) if layout.problem]
    if problems:
        return problems
    if was.schema != now.schema:
        problems.append(
            f"{older} reads the {was.schema} schema, not {now.schema}: it would "
            "start on an empty store beside the release's (F219, DL-1)"
        )
    names = [name for name, _ in was.migrations]
    added = [name for name, _ in now.migrations if name not in names]
    if added:
        problems.append(
            f"{release} applied {', '.join(added)}, which {older} does not "
            "carry: its app refuses the store (STORE_SCHEMA_DRIFT)"
        )
    elif was.migrations != now.migrations:
        problems.append(
            f"{older}'s migrations are not {release}'s, in order and byte for "
            "byte: its app refuses the store (STORE_SCHEMA_DRIFT)"
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("older", help="the commit a rollback would redeploy")
    parser.add_argument("--release", default="HEAD", help="the deployed release")
    args = parser.parse_args(argv)
    problems = rollback_problems(args.older, args.release)
    for problem in problems:
        print(problem)
    if problems:
        print("not a rollback: roll forward, or restore (docs/DEPLOYMENT.md section 6)")
        return 1
    print(f"{args.older} carries {args.release}'s migrations and schema: redeploy it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
