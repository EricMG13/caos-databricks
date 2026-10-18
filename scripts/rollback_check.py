#!/usr/bin/env python3
"""Whether redeploying an older commit is a valid rollback of a release (C1).

A release's first boot applies its migrations to the store, and the store
then refuses code whose migration list is any other (`apply_schema` answers
`STORE_SCHEMA_DRIFT` for a history longer than the code's own, and the app
does not start). Code from before DL-1 (F219) reads `public` rather than
`caos_store`, so it starts on an empty store beside the real one, except
that migration 0052 (N81) makes it refuse the store when it boots as the role
that migrated, and only then. A redeploy
is therefore a rollback only when the older commit carries exactly the
release's migrations, byte for byte and in order, reads the same schema,
and reads and writes the same host records (`RECORD_CODEC_VERSION` in
`caos/methodology/handoff.py`, D106: an older codec refuses the release's
records, and every reader of them then refuses the run), and records the
same writer versions (N111: extractor identities, crop versions, citation
normalisation, block packing, the canonical adapter and the renderer pin;
an older build refuses a row written under a version it does not know):

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
CODEC = "caos/methodology/handoff.py"
# Each writer version a release records, as (label, file, name): a module
# constant by its name, or the version in the `ExtractorIdentity` whose first
# argument is the quoted name. The receipt and package carry no version of
# their own: the renderer pin (`RENDERER_SHA256`) is what binds both.
WRITERS = (
    ("PdfExtractor version", "caos/evidence/pdf.py", "identity:caos.pdfminer"),
    (
        "plain-text extractor version",
        "caos/evidence/extract.py",
        "identity:caos.plain-text",
    ),
    ("PDF crop versions", "caos/evidence/page.py", "PDF_CROP_VERSIONS"),
    (
        "citation normalisation version",
        "caos/evidence/citations.py",
        "NORMALISATION_VERSION",
    ),
    ("block packing (width)", "caos/evidence/ingest.py", "PACKING_BY_WIDTH"),
    ("block packing (token)", "caos/evidence/ingest.py", "PACKING_BY_TOKEN"),
    (
        "canonical adapter version",
        "caos/methodology/__init__.py",
        "CANONICAL_ADAPTER_VERSION",
    ),
    ("renderer digest", "caos/deliverable/verify_package.py", "RENDERER_SHA256"),
    ("host record format", CODEC, "RECORD_FORMAT"),
    ("blocked-citations format", CODEC, "BLOCKED_FORMAT"),
)
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


def record_codec(rev: str, repo: Path = REPO) -> object:
    """`rev`'s `RECORD_CODEC_VERSION` as git recorded it, or None for a
    commit whose codec module names none (every one before D106)."""
    source = blob_at(repo, rev, CODEC)
    try:
        tree = ast.parse(source or "")
    except SyntaxError:
        return None
    value = _module_constants(tree).get("RECORD_CODEC_VERSION")
    return value.value if isinstance(value, ast.Constant) else None


def _literal(node: ast.expr) -> object:
    """A constant's value, a `frozenset({...})` as a sorted tuple, else None."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "frozenset"
        and len(node.args) == 1
    ):
        try:
            return tuple(sorted(ast.literal_eval(node.args[0])))
        except (ValueError, TypeError):
            return None
    return node.value if isinstance(node, ast.Constant) else None


def _identity_version(tree: ast.Module, name: str) -> object:
    """The version (second argument) of the `ExtractorIdentity` named `name`."""
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ExtractorIdentity"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == name
        ):
            return _literal(node.args[1])
    return None


def writer_versions(rev: str, repo: Path = REPO) -> dict[str, object]:
    """Each version in `WRITERS` as git recorded it at `rev`; None for one
    the commit does not declare (or declares in a form this cannot read)."""
    versions: dict[str, object] = {}
    for label, path, name in WRITERS:
        try:
            tree = ast.parse(blob_at(repo, rev, path) or "")
        except SyntaxError:
            versions[label] = None
            continue
        if name.startswith("identity:"):
            versions[label] = _identity_version(tree, name.removeprefix("identity:"))
        else:
            value = _module_constants(tree).get(name)
            versions[label] = None if value is None else _literal(value)
    return versions


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
            "start on an empty store beside the release's unless it boots as the role "
            "that applied 0052, whose tripwire it refuses (F219, DL-1, N81)"
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
    codecs = record_codec(older, repo), record_codec(release, repo)
    if codecs[0] != codecs[1]:
        problems.append(
            f"{older} reads host records by codec {codecs[0]}, not {codecs[1]}: "
            f"it refuses the records {release} wrote (D106)"
        )
    was_writes, now_writes = (
        writer_versions(older, repo),
        writer_versions(release, repo),
    )
    # A writer the release declares in no form this reads would compare equal
    # to the same gap on the older commit: refuse it, never pass it.
    problems.extend(
        f"{label} is not declared in a form this check reads on {release}"
        for label, value in now_writes.items()
        if value is None
    )
    problems.extend(
        f"{label} is {was_writes[label]} on {older} and {now_writes[label]} on "
        f"{release}: {older} refuses the rows {release} writes"
        for label in was_writes
        if now_writes[label] is not None and was_writes[label] != now_writes[label]
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
    print(
        f"{args.older} carries {args.release}'s migrations, schema and writer "
        "versions: redeploy it"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
