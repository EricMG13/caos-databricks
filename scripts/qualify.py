#!/usr/bin/env python3
"""Perform an on-disk qualification set against the configured live provider.

The three qualification runs this repository has paid for were driven by a
script that lived in a temporary directory. Two of them nearly lost their
evidence with it, and the third could not be reproduced without rewriting the
driver from the handoff. A run that costs money and can be run once is exactly
the thing that should not be reconstructed from memory, so the driver lives
here, under the same gates as everything else it calls.

It creates a database and a blob root of its own, so a performed set can be
kept for re-checking without touching a developer's own store, and it prints
where both are. Configuration is the caller's environment and nothing else:
`OPENROUTER_*` for the provider (§16), `CAOS_MODEL_PRICE` for the dated price
the reservation is computed from, and `CAOS_QUALIFY_POSTGRES_URL` for the
persistent server to keep the run database on -- never the in-memory test
server, whose restart erases it.

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
from decimal import Decimal
from pathlib import Path
from tempfile import mkdtemp
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import psycopg

# Run as a script, not as a package module: the repository root is what makes
# `server` importable, and a driver nobody can run is the gap this closes.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from caos.blobs import BlobStore
from caos.methodology import CANONICAL_ADAPTER_VERSION
from caos.methodology.bundle import Bundle
from caos.models import from_environment
from caos.pricing import price_from_environment, worst_case
from caos.qualification.harness import (
    Harness,
    PerformedSet,
    PreparedCase,
    perform,
    prepare,
)
from caos.qualification.matrix import QualificationSet
from caos.qualification.on_disk import load_qualification_set
from caos.qualification.store import performed_evidence, record_evidence
from caos.store import StoreConnection, apply_schema, connect
from caos.store.gates import Gate, GateApproval, approve_gate, gate_preview
from caos.store.members import Standing, grant

REPO = Path(__file__).resolve().parents[1]
CATALOG = "skills/cp-os-credit-os/references/CREDIT_OS_V_MODULE_CATALOG_v2.json"


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
    *,
    run_id: UUID,
) -> dict[str, object]:
    """Everything a reader needs to re-check the run, as one JSON document.

    The charge, model and generation id of every attempt come from the store
    rather than from the objects in hand: what reconciles a vendor bill is what
    the host recorded, not what a caller remembers recording.
    """
    snapshot = performed_evidence(prepared=prepared, performed=performed)
    attempts = conn.execute(
        "SELECT t.route_node_id,t.ordinal,l.amount,o.model,o.generation_id,"
        " o.diagnostic_sha256 FROM run_attempts t"
        " LEFT JOIN budget_ledger l USING(attempt_id)"
        " LEFT JOIN call_outcomes o USING(attempt_id)"
        " WHERE t.run_id=%s ORDER BY t.started_at,t.attempt_id",
        (run_id,),
    ).fetchall()
    return {
        "adapter_version": CANONICAL_ADAPTER_VERSION,
        "provider": prepared[0].provider,
        "model": prepared[0].model,
        "run_id": str(run_id),
        "set_sha256": prepared[0].qualification_set_sha256,
        "evidence_sha256": snapshot.evidence.sha256,
        "performed_sha256": snapshot.evidence.performed_sha256,
        "complete": snapshot.complete,
        "result": [
            {
                "case_label": item.case_label,
                "status": item.status.value,
                "stopped": None if item.stopped is None else item.stopped.value,
                "refusal": None if item.refusal is None else item.refusal.value,
                "proof": None
                if item.proof is None
                else {
                    "run_id": str(item.proof.run_id),
                    "route_digest": item.proof.route_digest,
                    "build_id": item.proof.build_id,
                    "artifacts": item.proof.artifacts,
                    "citations": item.proof.citations,
                    "anchored": [list(value) for value in sorted(item.proof.anchored)],
                },
            }
            for item in performed.performed
        ],
        "attempts": [
            {
                "route_node_id": str(row[0]),
                "ordinal": row[1],
                "charge": None if row[2] is None else str(row[2]),
                "model": row[3],
                "generation_id": row[4],
                "diagnostic_sha256": row[5],
            }
            for row in attempts
        ],
        "matrix": None
        if performed.matrix is None
        else [
            {
                "case_label": row.case_label,
                "proven": row.proven,
                "refusal": None if row.refusal is None else row.refusal.value,
                "met": len(row.met),
                "missed": len(row.missed),
                "ready_met": row.ready_met,
                "blocked_met": row.blocked_met,
                "projections_met": row.projections_met,
                "forecast_met": row.forecast_met,
                "expected_refusal_met": row.expected_refusal_met,
                "missed_keys": [
                    {
                        "module_id": item.module_id,
                        "document_sha256": item.document_sha256,
                        "matched_text": item.matched_text,
                    }
                    for item in row.missed
                ],
            }
            for row in performed.matrix.rows
        ],
    }


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # Path-traversal scanners flag `set_root`/`--capture` as a generic
    # "user request" source reaching a file sink -- the template does not
    # know this is argv, not a request body. There is no HTTP boundary here:
    # this module is a CLI script an operator runs from their own shell
    # (never imported by server/), so the path is exactly as trusted as any
    # other argument to a command they typed themselves.
    parser.add_argument("set_root", type=Path, help="the on-disk qualification set")
    parser.add_argument("--expect-identity", required=True)
    parser.add_argument("--ceiling", required=True, type=Decimal)
    parser.add_argument("--capture", type=Path, help="where to write the JSON capture")
    parser.add_argument(
        "--attempts",
        type=int,
        default=1,
        help="times to enter perform; >1 retries the node that stopped the set",
    )
    args = parser.parse_args(argv)

    bundle = Bundle(REPO / "vendor/deploy-v")
    qualification = load_qualification_set(args.set_root)
    provider = from_environment()
    if provider.qualification_identity != args.expect_identity:
        print(
            f"identity is {provider.qualification_identity}, "
            f"not {args.expect_identity}; nothing was spent",
            file=sys.stderr,
        )
        return 2
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
        return 2
    price = price_from_environment(provider.model, os.environ["CAOS_MODEL_PRICE"])
    harness = Harness(
        bundle=bundle,
        catalog=json.loads((bundle.root / CATALOG).read_text()),
        completions=provider,
        price=price,
        ceiling=args.ceiling,
        run_ceiling=args.ceiling,
    )

    database = f"caos_qualify_{uuid4().hex}"
    parts = urlsplit(admin_url)
    run_url = urlunsplit(parts._replace(path=f"/{database}"))
    blob_root = Path(mkdtemp(prefix="caos-qualify-"))
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(
            psycopg.sql.SQL("CREATE DATABASE {}").format(
                psycopg.sql.Identifier(database)
            )
        )
    # Printed before the call, not after: a driver that dies mid-run must still
    # leave the operator the two names that hold the evidence it paid for, and
    # the dated price every reservation it is about to take will be priced on
    # (Task 8.2) -- an operator reading the ceiling alone cannot tell whether a
    # set was affordable at the price the worker was configured with.
    print(
        json.dumps(
            {
                "database": database,
                "blob_root": str(blob_root),
                "price_model": price.model,
                "price_input_per_token": str(price.input_per_token),
                "price_output_per_token": str(price.output_per_token),
                "price_as_of": price.as_of.isoformat(),
                "price_worst_case_per_call": str(worst_case(price)),
            }
        ),
        flush=True,
    )

    with connect(run_url) as conn:
        apply_schema(conn)
        blobs = BlobStore(blob_root)
        prepared = prepare(conn, blobs, harness, qualification=qualification)
        _approve_every_gate(conn, prepared)
        performed = _perform_until(
            conn, blobs, harness, qualification, prepared, attempts=args.attempts
        )
        run_id = prepared[0].input.run_id
        document = _capture(conn, prepared, performed, run_id=run_id)
        snapshot = performed_evidence(prepared=prepared, performed=performed)
        record_evidence(conn, snapshot.evidence)
        conn.commit()

    body = json.dumps(document, indent=2, sort_keys=True)
    if args.capture is not None:
        args.capture.write_text(body + "\n", encoding="utf-8")
    print(body, flush=True)
    return 0 if document["complete"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
