#!/usr/bin/env python3
"""Perform an on-disk qualification set against the configured live provider.

The three qualification runs this repository has paid for were driven by a
script that lived in a temporary directory. Two of them nearly lost their
evidence with it, and the third could not be reproduced without rewriting the
driver from the handoff. A run that costs money and can be run once is exactly
the thing that should not be reconstructed from memory, so the driver lives
here, under the same gates as everything else it calls.

It creates a database of its own, so a performed set can be kept for
re-checking without touching a developer's own store, and it prints where that
and the blobs are. Configuration is the caller's environment and nothing else:
`OPENROUTER_*` for the provider (§16), `CAOS_MODEL_PRICE` for the dated price
the reservation is computed from, `CAOS_QUALIFY_POSTGRES_URL` for the
persistent server to keep the run database on -- never the in-memory test
server, whose restart erases it -- and `CAOS_QUALIFY_BLOB_ROOT` for the
directory the run's blobs are kept in, for the same reason: the proof re-reads
them, and `$TMPDIR` is purged (FP-16).

    scripts/qualify.py qualification/vmo2-fy2025 \
        --expect-identity openrouter/openai/flex/high/65536 --ceiling 22.00

`--expect-identity` is not a convenience. A verdict binds the execution profile
it was measured under, so the run refuses before spending anything if the
environment resolves to a different one than the caller believes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from decimal import ROUND_DOWN, Decimal
from enum import Enum
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import psycopg

# Run as a script, not as a package module: the repository root is what makes
# `server` importable, and a driver nobody can run is the gap this closes.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from caos.blobs import BlobStore
from caos.methodology import CANONICAL_ADAPTER_VERSION
from caos.methodology.bundle import Bundle
from caos.methodology.vendor import catalog
from caos.models import ChatCompletions, from_environment
from caos.pricing import price_from_environment, worst_case
from caos.qualification.harness import (
    Harness,
    PerformedSet,
    PreparedCase,
    assert_admissible,
    perform,
    prepare,
)
from caos.qualification.matrix import QualificationSet
from caos.qualification.on_disk import load_qualification_set
from caos.qualification.store import performed_evidence, record_evidence
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, apply_schema, connect
from caos.store.gates import Gate, GateApproval, approve_gate, gate_preview
from caos.store.members import Standing, grant

REPO = Path(__file__).resolve().parents[1]

# What a capture may carry: the JSON `json.dumps` writes, and nothing else.
type Plain = str | int | float | bool | None | list["Plain"] | dict[str, "Plain"]


def _approve_every_gate(
    conn: StoreConnection, prepared: tuple[PreparedCase, ...]
) -> None:
    """Grant an approver and take every gate on each prepared case.

    A qualification run is not a test of the human gates -- they have their own
    -- so the driver takes them itself, digest-bound like any other approval
    (invariant 5): the preview it approves is the preview the store computed.
    """
    for item in prepared:
        actor = uuid4()
        grant(
            conn,
            case_id=item.input.case_id,
            user_id=actor,
            standing=Standing.APPROVER,
        )
        conn.commit()
        for gate in Gate:
            preview = gate_preview(conn, item.input.run_id, gate)
            approve_gate(
                conn,
                GateApproval(
                    run_id=item.input.run_id,
                    gate=gate,
                    actor_id=actor,
                    preview_sha256=preview.preview_sha256,
                    input_fingerprint=preview.input_fingerprint,
                ),
            )


def _capture(
    conn: StoreConnection,
    prepared: tuple[PreparedCase, ...],
    performed: PerformedSet,
) -> dict[str, object]:
    """Everything a reader needs to re-check the set, as one JSON document.

    The charge, model and generation id of every attempt come from the store
    rather than from the objects in hand: what reconciles a vendor bill is what
    the host recorded, not what a caller remembers recording. Every prepared
    run's attempts, each row naming its run: the capture read the first case's
    run alone, so a two-case set's second run -- three charged calls -- was
    missing from the document that reconciles the bill (DQ-6, MAX-11).

    The rows and the proofs are serialised from the dataclasses themselves
    (`dataclasses.asdict`) rather than field by field. The hand-written
    projection had already lost one: `registers_met` joined `MatrixRow` and
    nothing here named it, so a run whose only failed comparison was a register
    key was captured as incomplete with no failed comparison visible (R2-N2,
    SI-5), and the next field would have gone the same way. The two counts stay
    explicit, because a reader wants how many keys missed and then which.
    """
    snapshot = performed_evidence(prepared=prepared, performed=performed)
    runs = [item.input.run_id for item in prepared]
    return {
        "adapter_version": CANONICAL_ADAPTER_VERSION,
        "provider": prepared[0].provider,
        "model": prepared[0].model,
        "run_ids": [str(run_id) for run_id in runs],
        "set_sha256": prepared[0].qualification_set_sha256,
        "evidence_sha256": snapshot.evidence.sha256,
        "performed_sha256": snapshot.evidence.performed_sha256,
        "complete": snapshot.complete,
        "result": [
            {
                "case_label": item.case_label,
                "run_id": str(item.run_id),
                "status": item.status.value,
                "stopped": None if item.stopped is None else item.stopped.value,
                "refusal": None if item.refusal is None else item.refusal.value,
                "proof": None if item.proof is None else _object(asdict(item.proof)),
            }
            for item in performed.performed
        ],
        "attempts": _attempts(conn, runs),
        "matrix": None
        if performed.matrix is None
        else [
            {
                **_object(asdict(row)),
                # The counts, then the keys: "two missed" is the first thing a
                # reader wants and the list is the second.
                "met": len(row.met),
                "missed": len(row.missed),
                "missed_keys": [_object(asdict(item)) for item in row.missed],
            }
            for row in performed.matrix.rows
        ],
    }


def _attempts(conn: StoreConnection, runs: list[UUID]) -> list[dict[str, Plain]]:
    """Every attempt of every prepared run, as the store recorded it, in case
    order: the charge, model and generation id a vendor bill is reconciled
    against, each row naming its run (DQ-6)."""
    return [
        {
            "run_id": str(row[0]),
            "route_node_id": str(row[1]),
            "ordinal": row[2],
            "charge": None if row[3] is None else str(row[3]),
            "model": row[4],
            "generation_id": row[5],
            "diagnostic_sha256": row[6],
        }
        for row in conn.execute(
            "SELECT t.run_id,t.route_node_id,t.ordinal,l.amount,o.model,"
            " o.generation_id,o.diagnostic_sha256 FROM run_attempts t"
            " LEFT JOIN budget_ledger l USING(attempt_id)"
            " LEFT JOIN call_outcomes o USING(attempt_id)"
            " WHERE t.run_id = ANY(%s)"
            " ORDER BY array_position(%s::uuid[], t.run_id),t.started_at,t.attempt_id",
            (runs, runs),
        ).fetchall()
    ]


def _object(fields: dict[str, object]) -> dict[str, Plain]:
    """One dataclass's `asdict` output, as JSON a reader can compare."""
    return {key: _plain(value) for key, value in fields.items()}


def _plain(value: object) -> Plain:
    """One value as JSON: enums by their value, anything else by `str`.

    Sets are sorted so two captures of one run compare, and tuples become lists
    as `json.dumps` would make them anyway.
    """
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_plain(item) for item in sorted(value)]
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _perform_until(  # noqa: PLR0913 -- one set, one loop, keyword-only tail
    conn: StoreConnection,
    blobs: BlobStore,
    harness: Harness,
    qualification: QualificationSet,
    prepared: tuple[PreparedCase, ...],
    *,
    attempts: int,
) -> PerformedSet:
    """Re-enter `perform` on the same pins while a node refusal stops the set.

    One refused node ends a whole set (`harness.perform` records `stopped` and
    returns), and a set costs three provider calls, so a single unlucky module
    throws away the two that succeeded. `perform` is re-enterable on the same
    `prepared`: accepted nodes are read from the store rather than re-run, and
    an explained refusal leaves the node ready for one fresh attempt, so this
    buys another try at the node that stopped and nothing more.

    It is bounded twice over. `attempts` caps the re-entries, and the run
    ceiling is the real limit: every attempt reserves the priced cost of its own
    request whether or not it is accepted, and `budget.py` never releases a
    reservation, so a run cannot spend past its ceiling however many times this
    loop asks.
    """
    performed = perform(
        conn, blobs, harness, qualification=qualification, prepared=prepared
    )
    for remaining in range(attempts - 1, 0, -1):
        if all(record.stopped is None for record in performed.performed):
            return performed
        stopped = next(
            record.stopped for record in performed.performed if record.stopped
        )
        print(
            json.dumps({"resumed_after": stopped.value, "attempts_left": remaining}),
            flush=True,
        )
        performed = perform(
            conn, blobs, harness, qualification=qualification, prepared=prepared
        )
    return performed


def _configured_provider(expect_identity: str) -> ChatCompletions | None:
    """The provider, built last, after every check that needs no client; None
    having said why nothing was spent: a workspace that cannot be reached, or
    a profile the caller did not expect."""
    try:
        provider = from_environment()
    except Refusal as refused:
        print(f"{refused.code.value}: no provider; nothing was spent", file=sys.stderr)
        return None
    if provider.qualification_identity != expect_identity:
        print(
            f"identity is {provider.qualification_identity}, "
            f"not {expect_identity}; nothing was spent",
            file=sys.stderr,
        )
        return None
    return provider


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    # Path-traversal scanners flag `set_root`/`--capture` as a generic
    # "user request" source reaching a file sink -- the template does not
    # know this is argv, not a request body. There is no HTTP boundary here:
    # this module is a CLI script an operator runs from their own shell
    # (never imported by server/), so the path is exactly as trusted as any
    # other argument to a command they typed themselves.
    parser.add_argument("set_root", type=Path, help="the on-disk qualification set")
    parser.add_argument("--expect-identity", required=True)
    parser.add_argument(
        "--ceiling", required=True, type=Decimal, help="what the whole set may spend"
    )
    parser.add_argument(
        "--run-ceiling",
        type=Decimal,
        help=(
            "what each case's run may spend; defaults to the set ceiling divided"
            " by the number of cases, because the harness requires"
            " run_ceiling x cases <= ceiling"
        ),
    )
    parser.add_argument("--capture", type=Path, help="where to write the JSON capture")
    parser.add_argument(
        "--attempts",
        type=int,
        default=1,
        help="times to enter perform; >1 retries the node that stopped the set",
    )
    return parser


def _environment() -> tuple[str, str, str] | None:
    """The persistent server, the dated price and the blob root, or None having
    said which is missing and that nothing was spent."""
    # A paid run's database is its evidence, so it is kept on a server named
    # for that and never on the test server, whose data lives in memory: a
    # restart of that container erased every retained run of 18 September 2026.
    admin_url = os.environ.get("CAOS_QUALIFY_POSTGRES_URL")
    if not admin_url:
        print(
            "CAOS_QUALIFY_POSTGRES_URL is unset: name the persistent server the"
            " run's database is kept on; nothing was spent",
            file=sys.stderr,
        )
        return None
    model_price = os.environ.get("CAOS_MODEL_PRICE")
    if not model_price:
        print(
            "CAOS_MODEL_PRICE is unset: name the dated price every reservation"
            " is computed from; nothing was spent",
            file=sys.stderr,
        )
        return None
    blob_root = os.environ.get("CAOS_QUALIFY_BLOB_ROOT")
    if not blob_root:
        # A paid run's blobs are its evidence as much as its database is, and
        # `assert_orchestration_proof` re-reads them. `mkdtemp` put them in
        # `$TMPDIR`, which macOS purges, so the evidence could not be re-proven
        # once it went (FP-16). Named for the same reason the database's server
        # is, and refused for the same reason.
        print(
            "CAOS_QUALIFY_BLOB_ROOT is unset: name the persistent directory the"
            " run's blobs are kept in; nothing was spent",
            file=sys.stderr,
        )
        return None
    return admin_url, model_price, blob_root


def _planned(
    args: argparse.Namespace,
) -> tuple[QualificationSet, Harness, str, str] | None:
    """The set, its harness, the server and the blob root, checked whole.

    Every check that makes no write runs here, before the database exists
    (`assert_admissible`): `prepare` was the first place a set's ceilings,
    keys and subjects were checked, so a set it refused left an empty
    `caos_qualify_*` database on the operator's server (DQ-12).
    """
    bundle = Bundle(REPO / "vendor/deploy-v")
    qualification = load_qualification_set(args.set_root)
    # Both ceilings were `--ceiling`, and the harness requires
    # `run_ceiling x cases <= ceiling`, so every positive-budget set of more
    # than one case was impossible to admit and raising the shared value could
    # not fix the inequality (AR-18). Derived per case only when not named: a
    # named zero is falsy, and `or` replaced it with the derived share, so a run
    # the operator capped at nothing spent (DQ-7). A named value goes to the
    # harness as given, which refuses one it cannot afford a call under.
    if args.run_ceiling is None:
        args.run_ceiling = (args.ceiling / len(qualification.cases)).quantize(
            Decimal("0.000001"), rounding=ROUND_DOWN
        )
    environment = _environment()
    if environment is None:
        return None
    admin_url, model_price, blob_root = environment
    provider = _configured_provider(args.expect_identity)
    if provider is None:
        return None
    price = price_from_environment(provider.model, model_price)
    bundle.verify_pinned()
    harness = Harness(
        bundle=bundle,
        # The verified reader, not a bare read of the file: the route every
        # paid call follows is resolved from this, and reading the bytes
        # directly accepted a tampered catalog that `verified_bytes` refuses
        # (FP-15, invariant 4).
        catalog=catalog(bundle),
        completions=provider,
        price=price,
        ceiling=args.ceiling,
        run_ceiling=args.run_ceiling,
    )
    assert_admissible(harness, qualification=qualification)
    return qualification, harness, admin_url, blob_root


def _create_database(admin_url: str) -> tuple[str, str]:
    """A fresh database on the persistent server: its name and its URL."""
    database = f"caos_qualify_{uuid4().hex}"
    parts = urlsplit(admin_url)
    run_url = urlunsplit(parts._replace(path=f"/{database}"))
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(
            psycopg.sql.SQL("CREATE DATABASE {}").format(
                psycopg.sql.Identifier(database)
            )
        )
    return database, run_url


def _performed_capture(
    run_url: str,
    blob_root: str,
    harness: Harness,
    qualification: QualificationSet,
    *,
    attempts: int,
) -> dict[str, object]:
    """Prepare, approve and perform the set in its database; its capture."""
    with connect(run_url) as conn:
        apply_schema(conn)
        blobs = BlobStore(Path(blob_root))
        prepared = prepare(conn, blobs, harness, qualification=qualification)
        _approve_every_gate(conn, prepared)
        performed = _perform_until(
            conn, blobs, harness, qualification, prepared, attempts=attempts
        )
        document = _capture(conn, prepared, performed)
        snapshot = performed_evidence(prepared=prepared, performed=performed)
        record_evidence(conn, snapshot.evidence)
        conn.commit()
    return document


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.attempts < 1:
        print("--attempts must be at least 1; nothing was spent", file=sys.stderr)
        return 2
    try:
        planned = _planned(args)
    except Refusal as refused:
        print(
            f"{refused.code.value}: the set was refused; nothing was spent",
            file=sys.stderr,
        )
        return 2
    if planned is None:
        return 2
    qualification, harness, admin_url, blob_root = planned
    try:
        database, run_url = _create_database(admin_url)
    except psycopg.Error:
        # CF-078: a DSN psycopg itself refuses to parse -- bad percent-encoding
        # in a password included -- quotes the whole string, password and all,
        # in its own message; only the typed code is ever printed here.
        print(
            f"{RefusalCode.STORE_UNAVAILABLE.value}: the set was refused;"
            " nothing was spent",
            file=sys.stderr,
        )
        return 2
    # Printed before the call, not after: a driver that dies mid-run must still
    # leave the operator the two names that hold the evidence it paid for, and
    # the dated price every reservation it is about to take will be priced on
    # (Task 8.2) -- an operator reading the ceiling alone cannot tell whether a
    # set was affordable at the price the worker was configured with.
    price = harness.price
    print(
        json.dumps(
            {
                "database": database,
                "blob_root": blob_root,
                "run_ceiling": str(harness.run_ceiling),
                "price_model": price.model,
                "price_input_per_token": str(price.input_per_token),
                "price_output_per_token": str(price.output_per_token),
                "price_as_of": price.as_of.isoformat(),
                "price_worst_case_per_call": str(worst_case(price)),
            }
        ),
        flush=True,
    )
    try:
        document = _performed_capture(
            run_url, blob_root, harness, qualification, attempts=args.attempts
        )
    except Refusal as refused:
        # After the database exists, so not "nothing was spent": what was
        # performed is kept there, the matrix's own refusal included (DQ-5).
        print(
            f"{refused.code.value}: the set stopped; {database} keeps what it"
            " performed",
            file=sys.stderr,
        )
        return 2
    except psycopg.Error:
        print(
            f"{RefusalCode.STORE_UNAVAILABLE.value}: the set stopped; {database}"
            " keeps what it performed",
            file=sys.stderr,
        )
        return 2

    body = json.dumps(document, indent=2, sort_keys=True)
    if args.capture is not None:
        args.capture.write_text(body + "\n", encoding="utf-8")
    print(body, flush=True)
    return 0 if document["complete"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
