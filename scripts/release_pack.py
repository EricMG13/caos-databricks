#!/usr/bin/env python3
"""Emit the release pack from the suite, the tree and, when asked, the store.

Release evidence was a signed check and a hand-kept record, not a pack, and
`docs/feature-status.csv` -- 248 dated rows, 14 of them citing tests the
repair deleted -- is what a hand-kept inventory becomes. This script is the
regenerated answer that file's ledger entry asked for. It writes two files
and types neither:

- `release-pack.json`: the methodology build and manifest digest, the migration
  head (the same digest a migrated store records), the SHA-256 of every lock,
  the test inventory read from both suites, and one row per catalog pathway.
- `RELEASE_PACK.md`: the same facts for a reader, with the inventory reduced to
  its counts and digest.

Every pathway the vendored catalog advertises gets a row, and each row says one
of four things. `DISABLED`: not in `ADAPTER_ROUTES`, so the host refuses it
`HANDOFF_MODULE_UNSUPPORTED` before any attempt, whatever anyone signed.
`UNVERIFIED`: enabled, and no store was read, so nothing is claimed.
`NOT_QUALIFIED`: enabled, a store was read, and no current verdict stands
behind it. `QUALIFIED`: enabled, and a `qualification_verdicts` row -- signed
over complete evidence bound to this build, current at the `--as-of` moment the
caller names, and covering a run pinned to this pathway -- is in the store. The
host never originates that word (`caos/qualification/verdict.py`); this
script only relays a row it can read back through `current_verdict`.

Reproducible by construction: sorted everywhere, no clock, no hostname, no git
state. A store read needs `--as-of` because a verdict's currency is a decision
taken at a moment, and a moment the script read off the clock would make two
emissions a second apart differ. The store is named by `CAOS_DATABASE_URL`
from the environment, never by an argument, so a credential never reaches a
process listing.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg

# Run as a script, not as a package module: the repository root is what makes
# `server` importable (the same line `scripts/qualify.py` carries).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from caos.methodology import CANONICAL_ADAPTER_VERSION
from caos.methodology.bundle import Bundle
from caos.methodology.handoff import ADAPTER_ROUTES
from caos.methodology.vendor import catalog
from caos.qualification.store import answered_document, current_verdict, evidence_at
from caos.refusals import Refusal, RefusalCode
from caos.store import MIGRATIONS, StoreConnection, connect, verify_schema
from caos.store.routes import route_pin

REPO = Path(__file__).resolve().parents[1]
JSON_NAME = "release-pack.json"
MARKDOWN_NAME = "RELEASE_PACK.md"
PACK_FORMAT = 1

DISABLED = "DISABLED"
UNVERIFIED = "UNVERIFIED"
NOT_QUALIFIED = "NOT_QUALIFIED"
QUALIFIED = "QUALIFIED"

# Every lock CI, the App and the workspace install from, by repository path.
LOCK_FILES = (
    "frontend/package-lock.json",
    "uv.lock",
)

_REASONS = {
    DISABLED: (
        "not in ADAPTER_ROUTES: refused HANDOFF_MODULE_UNSUPPORTED before any"
        " attempt, reservation or call"
    ),
    UNVERIFIED: "enabled; no store was read, so no verdict is claimed",
    NOT_QUALIFIED: (
        "enabled; no current verdict for this build and adapter in the store read"
    ),
    QUALIFIED: "enabled; a current signed verdict for this build and adapter covers it",
}

# A workspace test is a title string at the start of a statement. Anchored to
# the line so a call spelled inside another test's string is not read as one;
# a template title is recorded as its template, which is what the source says.
_WORKSPACE_TEST = re.compile(
    r"""^\s*(?:test|it)(?:\.[a-z]+)?\(\s*(["'`])((?:\\.|(?!\1).)*)\1""",
    re.MULTILINE,
)


class EmptyScan(RuntimeError):
    """A suite that yielded no test: a scan that scanned nothing is a failure."""

    def __init__(self, where: str) -> None:
        super().__init__(f"read no test from {where}")


def _python_tests(path: Path, relative: str) -> list[str]:
    """`path::name` and `path::Class::name`, from the module's syntax tree."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name.startswith("test"):
                found.append(f"{relative}::{node.name}")
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            found.extend(
                f"{relative}::{node.name}::{item.name}"
                for item in node.body
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
                and item.name.startswith("test")
            )
    return found


def suite_inventory(repo: Path) -> dict[str, list[str]]:
    """Every test the two suites define, sorted, by repository-relative path.

    Read from the source rather than from `pytest --collect-only`: collection
    imports every module, needs the database configuration, and expands
    parametrisations whose ids can carry values; the definitions are what a
    reader cites and what the ledger gate resolves citations against.
    """
    python = sorted(
        test
        for path in sorted((repo / "tests").rglob("test_*.py"))
        for test in _python_tests(path, path.relative_to(repo).as_posix())
    )
    if not python:
        raise EmptyScan("tests/")
    frontend: list[str] = []
    workspace = repo / "frontend" / "tests"
    if workspace.is_dir():
        for path in sorted(workspace.rglob("*")):
            if path.suffix not in {".ts", ".tsx"}:
                continue
            relative = path.relative_to(repo).as_posix()
            text = path.read_text(encoding="utf-8")
            frontend.extend(
                f"{relative}::{match[1]}" for match in _WORKSPACE_TEST.findall(text)
            )
    return {"python": python, "frontend": sorted(frontend)}


def lock_digests(repo: Path) -> dict[str, str]:
    """SHA-256 of every lock file's bytes."""
    return {name: sha256((repo / name).read_bytes()).hexdigest() for name in LOCK_FILES}


def migration_head() -> dict[str, Any]:
    """The declared migration history, digested exactly as a migrated store
    records it in `store_schema.applied_digest` (`caos/store/__init__.py`)."""
    history = [
        (version, name, sha256(body.encode("utf-8")).hexdigest())
        for version, (name, body) in enumerate(MIGRATIONS, 1)
    ]
    return {
        "count": len(history),
        "head": history[-1][1],
        "history_sha256": sha256(json.dumps(history).encode("utf-8")).hexdigest(),
        "names": [name for _, name, _ in history],
    }


# A verdict that is not current at `--as-of` covers nothing, and saying so is
# the pack's job. Every other refusal is the store contradicting itself, and a
# pack that swallowed one would read as a store with no verdicts (FP-28).
_NOT_CURRENT = frozenset({RefusalCode.VERDICT_EXPIRED, RefusalCode.VERDICT_INCOMPLETE})


def _snapshot_pins(document: object) -> list[tuple[UUID, str]]:
    """`(run_id, route_digest)` for each case that produced an output.

    Not every case the snapshot prepared. A verdict used to cover every pathway
    any run in its snapshot was pinned to, so a case that met a declared
    refusal, or one that never finished, made its own pathway QUALIFIED although
    no run on it produced an artifact (FP-02). A case counts here only when its
    run reached COMPLETE and its row answered every key the case declared --
    `document_complete`'s per-case halves, asked per case.

    A malformed item refuses rather than being skipped: a snapshot this cannot
    read is one the pack may not relay (FP-28).
    """
    prepared, produced, rows = _snapshot_parts(document)
    return [
        _pin_of(item)
        for item in prepared
        if _covers(item, produced=produced, rows=rows)
    ]


def _snapshot_parts(
    document: object,
) -> tuple[list[Mapping[str, object]], set[object], dict[object, object]]:
    """The three lists a snapshot's coverage is read from, or a typed refusal."""
    if not isinstance(document, dict):
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    prepared, records = document.get("prepared"), document.get("performed")
    matrix = document.get("matrix")
    if not isinstance(prepared, list) or not isinstance(records, list):
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    if not isinstance(matrix, dict) or not isinstance(matrix.get("rows"), list):
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    rows: dict[object, object] = {
        row.get("case_label"): row for row in matrix["rows"] if isinstance(row, dict)
    }
    produced = {
        record.get("case_label")
        for record in records
        if isinstance(record, dict) and record.get("status") == "COMPLETE"
    }
    return prepared, produced, rows


def _covers(item: object, *, produced: set[object], rows: dict[object, object]) -> bool:
    """Whether this prepared case is one the verdict's coverage may rest on."""
    if not isinstance(item, dict) or "run_id" not in item or "route_digest" not in item:
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    label = item.get("case_label")
    return label in produced and answered_document(rows.get(label))


def _pin_of(item: Mapping[str, object]) -> tuple[UUID, str]:
    """One prepared case's `(run_id, route_digest)`, or a typed refusal."""
    try:
        return UUID(str(item["run_id"])), str(item["route_digest"])
    except ValueError:
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID) from None


def _pathway(
    conn: StoreConnection, run_id: UUID, route_digest: str
) -> tuple[str, str] | None:
    """The pathway a run was pinned to, read through the store's own pin.

    `run_routes` was read by `(run_id, route_digest)` and never validated, so a
    row whose `resolved` is `{}` -- which `route_pin` refuses
    `ROUTE_IDENTITY_INVALID` -- named a pathway (FP-02). `resolved_route` is the
    reader every other caller uses, and the digest it carries has to be the one
    the snapshot named.
    """
    try:
        pin = route_pin(conn, run_id)
    except Refusal:
        return None
    if pin is None or pin[1] != route_digest:
        return None
    return pin[0].profile_id, pin[0].selection_id


def qualified_pathways(
    conn: StoreConnection,
    *,
    build_id: str,
    as_of: datetime,
    identity: tuple[str, str] | None = None,
) -> dict[tuple[str, str], list[dict[str, str]]]:
    """Each pathway a current verdict for this build and adapter covers.

    A verdict covers the pathways the runs that *produced output* in its
    snapshot were pinned to, read through `resolved_route` and joined on the
    digest the snapshot names, so a pin the snapshot did not prepare, or one
    whose stored route will not read, covers nothing. Currency is
    `current_verdict`'s, judged at `as_of`: an expired verdict, one decided
    after it, or one over a snapshot that no longer re-derives as complete
    covers nothing. Any other refusal is raised: a pack that quietly dropped a
    tampered row would read as a store with no verdicts.

    `identity` is the deployed `(provider, model)` when the caller names one.
    Qualification is measured under one execution identity and production's is
    set by environment (D7), so a pack that relayed QUALIFIED without saying
    which identity it covered said less than it appeared to (FP-14, AR-22).
    """
    rows = conn.execute(
        "SELECT q.evidence_sha256,q.reviewer,q.reviewer_id,q.decided_at,q.expires_at,"
        " p.performed_json,q.recorded_at FROM qualification_verdicts q"
        " JOIN qualification_evidence e USING (evidence_sha256)"
        " JOIN qualification_performed p ON p.performed_sha256=e.performed_sha256"
        " WHERE e.build_id=%s AND e.adapter_version=%s"
        " ORDER BY q.evidence_sha256,q.reviewer_id",
        (build_id, CANONICAL_ADAPTER_VERSION),
    ).fetchall()
    found: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        verdict = _current(conn, row, as_of=as_of, identity=identity)
        if verdict is None:
            continue
        for run_id, route_digest in _snapshot_pins(row[5]):
            key = _pathway(conn, run_id, route_digest)
            if key is None:
                continue
            covered = found.setdefault(key, [])
            if verdict not in covered:
                covered.append(verdict)
    return found


def _current(
    conn: StoreConnection,
    row: tuple[Any, ...],
    *,
    as_of: datetime,
    identity: tuple[str, str] | None,
) -> dict[str, str] | None:
    """One verdict row as the pack emits it, or None when it covers nothing."""
    digest, reviewer, reviewer_id, decided_at, expires_at, _document, recorded = row
    evidence = evidence_at(conn, evidence_sha256=digest)
    if evidence is None:
        # The row was found by joining its evidence to a snapshot, so the
        # evidence exists: `evidence_at` answering None means it contradicts
        # the snapshot it names. That is the store contradicting itself, which
        # is raised, not dropped as though the store held no verdict (FP-28,
        # DQ-3).
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    if identity is not None and (evidence.provider, evidence.model) != identity:
        return None
    if decided_at > as_of:
        # Not yet taken at the moment being reported on. `read_verdict` calls a
        # document signed in the future a wrong binding; here it is a verdict
        # this pack simply does not cover, and telling the two apart is what
        # lets every other wrong binding be raised (FP-28).
        return None
    try:
        current_verdict(conn, evidence=evidence, now=as_of)
    except Refusal as refused:
        if refused.code in _NOT_CURRENT:
            return None
        raise
    return {
        "evidence_sha256": digest,
        "reviewer": reviewer,
        # The authenticated signer beside the free text an ADMIN typed, and the
        # execution identity and set the verdict was measured over.
        "reviewer_id": str(reviewer_id),
        "qualification_set_sha256": evidence.qualification_set_sha256,
        "provider": evidence.provider,
        "model": evidence.model,
        # In UTC, whatever zone the session negotiated: the same store read
        # under two `PGTZ` settings emitted two packs (DQ-4).
        "decided_at": _utc(decided_at),
        "expires_at": _utc(expires_at),
        # When the row was written, which `decided_at` -- the reviewer's own
        # word -- is not; None for a verdict signed before it was kept (DQ-13).
        "recorded_at": None if recorded is None else _utc(recorded),
    }


def _utc(moment: datetime) -> str:
    """One moment as the pack prints it: ISO 8601 in UTC, never the session's."""
    return moment.astimezone(UTC).isoformat()


def pathways(
    verified: Mapping[str, Any],
    *,
    qualified: Mapping[tuple[str, str], list[dict[str, str]]] | None,
    identity: tuple[str, str] | None = None,
) -> list[dict[str, Any]]:
    """One row per pathway the catalog advertises, sorted.

    `qualified` is `None` when no store was read. A disabled pathway stays
    `DISABLED` whatever was signed over it: the word is what the host will
    execute, and no signature changes that.

    `identity` is the `(provider, model)` filter the store was read under, and
    a store row's reason names it: a filtered pack over a store holding another
    identity's verdict said "no current verdict for this build and adapter",
    which was false for that pack (DQ-4).
    """
    rows = []
    for profile_id, profile in sorted(verified["profiles"].items()):
        for selection_id in sorted(profile["pathways"]):
            key = (profile_id, selection_id)
            verdicts = [] if qualified is None else qualified.get(key, [])
            enabled = key in ADAPTER_ROUTES
            if not enabled:
                status = DISABLED
            elif qualified is None:
                status = UNVERIFIED
            else:
                status = QUALIFIED if verdicts else NOT_QUALIFIED
            rows.append(
                {
                    "profile_id": profile_id,
                    "selection_id": selection_id,
                    "enabled": enabled,
                    "status": status,
                    "reason": _reason(status, identity),
                    "verdicts": verdicts,
                }
            )
    return rows


def _reason(status: str, identity: tuple[str, str] | None) -> str:
    """The row's reason, naming the identity filter a store row was counted under."""
    if identity is None or status not in {NOT_QUALIFIED, QUALIFIED}:
        return _REASONS[status]
    provider, model = identity
    return (
        f"{_REASONS[status]}; only verdicts measured under provider {provider}"
        f" and model {model} were counted"
    )


def read_store(
    conn: StoreConnection,
    *,
    bundle: Bundle,
    as_of: datetime,
    identity: tuple[str, str] | None = None,
) -> dict[tuple[str, str], list[dict[str, str]]]:
    """Current-adapter verdicts for this build from its described store.

    The read unit is rolled back, never committed.
    """
    verify_schema(conn)
    try:
        return qualified_pathways(
            conn, build_id=bundle.build_id, as_of=as_of, identity=identity
        )
    finally:
        conn.rollback()


def build_pack(
    repo: Path,
    *,
    bundle: Bundle,
    store: tuple[dict[tuple[str, str], list[dict[str, str]]], datetime] | None = None,
    identity: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """The whole pack as one document. `store` is what `read_store` found and
    the moment it was judged at, or `None` when no store was read; `identity`
    is the `(provider, model)` it was read under, or `None` for any.

    Both inputs that decide which verdicts count are recorded beside the moment:
    the identity filter and the adapter revision. A pack filtered to an
    identity the store held no verdict for was byte-identical to one over an
    empty store (DQ-4).
    """
    qualified, as_of = (None, None) if store is None else store
    return {
        "format": PACK_FORMAT,
        "bundle": {
            "build_id": bundle.build_id,
            "manifest_sha256": bundle.manifest_sha256,
        },
        "migrations": migration_head(),
        "locks": lock_digests(repo),
        "tests": suite_inventory(repo),
        "pathways": pathways(catalog(bundle), qualified=qualified, identity=identity),
        "store": None
        if as_of is None
        else {
            "as_of": _utc(as_of),
            "adapter_version": CANONICAL_ADAPTER_VERSION,
            "identity": "any"
            if identity is None
            else {"provider": identity[0], "model": identity[1]},
        },
    }


def _digest(values: list[str]) -> str:
    return sha256("\n".join(values).encode("utf-8")).hexdigest()


def render_markdown(pack: Mapping[str, Any]) -> str:
    """The reader's copy. Every figure in it is a field of the JSON beside it."""
    tests = pack["tests"]
    store = pack["store"]
    lines = [
        "# Release pack",
        "",
        "Generated by `scripts/release_pack.py` (`make release-pack`); do not edit.",
        "",
        f"- Methodology build: `{pack['bundle']['build_id']}`",
        f"- Manifest SHA-256: `{pack['bundle']['manifest_sha256']}`",
        f"- Migration head: `{pack['migrations']['head']}`"
        f" ({pack['migrations']['count']} migrations,"
        f" history `{pack['migrations']['history_sha256']}`)",
        f"- Python tests defined: {len(tests['python'])}"
        f" (digest `{_digest(tests['python'])}`)",
        f"- Workspace tests defined: {len(tests['frontend'])}"
        f" (digest `{_digest(tests['frontend'])}`)",
        "- Verdicts: "
        + (
            "no store read; no pathway is claimed qualified"
            if store is None
            else f"store read as of {store['as_of']}, adapter"
            f" `{store['adapter_version']}`, identity {_identity(store['identity'])}"
        ),
        "",
        "## Locks",
        "",
        "| file | sha256 |",
        "|---|---|",
        *(f"| `{name}` | `{digest}` |" for name, digest in pack["locks"].items()),
        "",
        "## Pathways",
        "",
        "| profile | pathway | status | reason | verdicts |",
        "|---|---|---|---|---|",
    ]
    for row in pack["pathways"]:
        verdicts = ", ".join(_verdict_cell(verdict) for verdict in row["verdicts"])
        lines.append(
            f"| `{row['profile_id']}` | `{row['selection_id']}` |"
            f" {row['status']} | {_cell(row['reason'])} | {verdicts or '—'} |"
        )
    return "\n".join(lines) + "\n"


def _verdict_cell(verdict: Mapping[str, Any]) -> str:
    """One verdict as the reader's copy shows it: what it was measured under.

    The provider, the model, the set and the signer beside the evidence and
    the expiry. The reader's copy showed QUALIFIED with none of them, so a
    reader handed only the Markdown could not tell which execution identity
    -- a test adapter's, say -- the word covered (MAX-12, DQ-4).
    """
    return _cell(
        f"`{verdict['evidence_sha256'][:16]}…` under `{verdict['provider']}`"
        f" `{verdict['model']}`, set `{verdict['qualification_set_sha256'][:16]}…`,"
        f" signed by {verdict['reviewer']} ({verdict['reviewer_id']})"
        f" until {verdict['expires_at']}"
    )


def _identity(identity: object) -> str:
    """The identity filter as the reader's copy prints it."""
    if not isinstance(identity, Mapping):
        return "any"
    return f"`{identity['provider']}` `{identity['model']}`"


def _cell(text: str) -> str:
    """Text a Markdown table cell can hold: a pipe ends a cell, a newline a row."""
    return " ".join(text.replace("|", "\\|").split())


def write_pack(pack: Mapping[str, Any], out: Path) -> None:
    """Both files, bytes fixed by the pack alone.

    `out` traces back to `--out`, a CLI argument from `main`'s own operator,
    not a request body -- there is no HTTP boundary for a path-traversal
    scanner's "user request" source to have crossed. See `main`'s `--out`
    definition for the fuller note.
    """
    out.mkdir(parents=True, exist_ok=True)  # NOSONAR pythonsecurity:S8707
    (out / JSON_NAME).write_text(
        json.dumps(pack, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (out / MARKDOWN_NAME).write_text(render_markdown(pack), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # Path-traversal scanners flag `--out` as a generic "user request" source
    # reaching write_pack's mkdir/write_text sink -- the template does not
    # know this is argv, not a request body. There is no HTTP boundary here:
    # this module is a CLI script an operator runs from their own shell
    # (never imported by server/), so the path is exactly as trusted as any
    # other argument to a command they typed themselves.
    parser.add_argument("--out", type=Path, default=REPO / "release-pack")
    parser.add_argument(
        "--store",
        action="store_true",
        help="read verdicts from the store named by CAOS_DATABASE_URL",
    )
    parser.add_argument(
        "--as-of",
        type=datetime.fromisoformat,
        help="the ISO-8601 moment, with an offset, verdicts are judged current at",
    )
    parser.add_argument(
        "--provider",
        help=(
            "count only verdicts measured under this provider; qualification is"
            " measured under one execution identity and production's is set by"
            " environment (D7), so a pack that named none said less than it looked"
        ),
    )
    parser.add_argument("--model", help="count only verdicts measured under this model")
    args = parser.parse_args(argv)
    bundle = Bundle(REPO / "vendor" / "deploy-v")
    if not args.store:
        write_pack(build_pack(REPO, bundle=bundle), args.out)
        return 0
    url = os.environ.get("CAOS_DATABASE_URL")
    as_of = args.as_of
    if not url or as_of is None or as_of.tzinfo is None:
        print(
            "--store needs CAOS_DATABASE_URL and --as-of with an offset",
            file=sys.stderr,
        )
        return 2
    if (args.provider is None) != (args.model is None):
        print(
            "--provider and --model are named together or not at all", file=sys.stderr
        )
        return 2
    identity = None if args.provider is None else (args.provider, args.model)
    try:
        with connect(url) as conn:
            qualified = read_store(conn, bundle=bundle, as_of=as_of, identity=identity)
    except Refusal as refused:
        print(refused.code.value, file=sys.stderr)
        return 2
    except psycopg.Error:
        # CF-078: a DSN psycopg itself refuses to parse -- bad percent-encoding
        # in a password included -- quotes the whole string, password and all,
        # in its own message; only the typed code is ever printed here.
        print(RefusalCode.STORE_UNAVAILABLE.value, file=sys.stderr)
        return 2
    write_pack(
        build_pack(REPO, bundle=bundle, store=(qualified, as_of), identity=identity),
        args.out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
