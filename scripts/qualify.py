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
the provider is `caos.models.from_environment` -- `ChatDatabricks` on
`CAOS_MODEL_ENDPOINT` through the caller's Databricks CLI profile
(`DATABRICKS_CONFIG_PROFILE`), the production path -- unless the test-only
`tests/qualify_openrouter.py` wraps this script with `OPENROUTER_*` (§16);
`CAOS_MODEL_PRICE` for the dated price
the reservation is computed from, `CAOS_QUALIFY_POSTGRES_URL` for the
persistent server to keep the run database on -- never the in-memory test
server, whose restart erases it -- and `CAOS_QUALIFY_BLOB_ROOT` for the
directory the run's blobs are kept in, for the same reason: the proof re-reads
them, and `$TMPDIR` is purged (FP-16).

    scripts/qualify.py qualification/ccl-fy2025-market-dislocation \
        --expect-identity databricks/claude-opus-5-5/none/65536 --ceiling 60.00

    # The same set through GitHub Copilot on this machine (D77): the identity
    # names the platform, the model, the effort and the output cap.
    CAOS_MODEL_ENDPOINT=copilot:gpt-6-luna@high \
    CAOS_MODEL_PRICE=copilot:gpt-6-luna@high,<in>,<out>,<YYYY-MM-DD> \
    CAOS_COPILOT_CREDIT_PRICE=<usd per AI credit>,<YYYY-MM-DD> \
    scripts/qualify.py qualification/ccl-fy2025-market-dislocation \
        --expect-identity copilot/gpt-6-luna/high/65536 --ceiling 5.00

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
from caos.copilot import require_ready
from caos.graph.route import (
    GATE_MODULE,
    READY,
    NodeState,
    readiness_from,
    waiting_on,
)
from caos.graph.runtime import accepted_artifacts
from caos.methodology import CANONICAL_ADAPTER_VERSION
from caos.methodology.bundle import Bundle
from caos.methodology.canonical import SECOND_ATTEMPT_CODES
from caos.methodology.vendor import catalog
from caos.models import ChatCompletions, from_environment
from caos.pricing import price_from_environment, worst_case
from caos.qualification.harness import (
    Harness,
    Performed,
    PerformedSet,
    PreparedCase,
    assert_admissible,
    perform,
    prepare,
)
from caos.qualification.matrix import QualificationSet, assert_measurable
from caos.qualification.on_disk import load_qualification_set
from caos.qualification.store import performed_evidence, record_evidence
from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection, apply_schema, connect
from caos.store.budget import remaining, validate_spend
from caos.store.gates import Gate, GateApproval, approve_gate, gate_preview
from caos.store.members import Standing, grant
from caos.store.outcomes import execution_reads, node_attempts
from caos.store.routes import resolved_route

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
    *,
    blobs: BlobStore,
    bundle: Bundle,
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
    stops = {item.run_id: _stop_code(conn, item) for item in performed.performed}
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
            _result_row(
                item,
                stops[item.run_id],
                _blocked_by(conn, blobs, bundle, item),
            )
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


def _result_row(
    item: Performed, stop: RefusalCode | None, blocked_by: dict[str, Plain] | None
) -> dict[str, Plain]:
    """One case's outcome. `stopped` is the capture's corrected reading
    (`_stop_code`); `refused_with` is the code the run raised, which
    `caos/qualification/store.py` persists in the evidence snapshot unchanged,
    and is None when the two agree. `blocked_by` is `_blocked_by`'s reading of
    a BLOCKED run and None for any other."""
    return {
        "case_label": item.case_label,
        "run_id": str(item.run_id),
        "status": item.status.value,
        "stopped": None if stop is None else stop.value,
        "refused_with": None
        if item.stopped is None or stop is item.stopped
        else item.stopped.value,
        "refusal": None if item.refusal is None else item.refusal.value,
        "proof": None if item.proof is None else _object(asdict(item.proof)),
        "blocked_by": blocked_by,
    }


def _blocked_by(
    conn: StoreConnection, blobs: BlobStore, bundle: Bundle, item: Performed
) -> dict[str, Plain] | None:
    """What blocked a BLOCKED run, read from the ledger and never inferred (QF3-1).

    A run ends BLOCKED two ways and the status says neither. A module's own
    validated Blocked answer ends it through `block_run(verdict=...)`, which
    writes the run's one `run_blocking_verdicts` row (`path: "module"`). The
    route's own rule ends it with no row (`verdict=None`, §39): the frontier
    emptied while nodes the route holds BLOCKED were unfinished
    (`path: "route"`). So the row decides the path, and nothing else does.

    Nothing here quotes document text: not an answer, not CP-0's blocker text.
    """
    if item.status is not RunStatus.BLOCKED:
        return None
    verdict = conn.execute(
        "SELECT t.route_node_id, t.attempt_id, t.ordinal, v.citations_sha256,"
        " v.recorded_at FROM run_blocking_verdicts v"
        " JOIN run_attempts t USING (attempt_id) WHERE v.run_id = %s",
        (item.run_id,),
    ).fetchone()
    if verdict is not None:
        return {
            "path": "module",
            "route_node_id": str(verdict[0]),
            "attempt_id": str(verdict[1]),
            "ordinal": verdict[2],
            # The row stores no code. `block_run` is given a verdict only by
            # `runtime._block_on`, which has two callers: `_end_blocked` (the
            # run's own pass) and `_settle` (a resumed run replaying a stored
            # answer). Each requires `Verdict.BLOCKED` from `replay_billed`
            # first, which is what `HANDOFF_BLOCKED` names.
            "code": RefusalCode.HANDOFF_BLOCKED.value,
            "citations_sha256": verdict[3],
            "recorded_at": verdict[4].isoformat(),
        }
    return _route_blocked(conn, blobs, bundle, item)


def _route_blocked(
    conn: StoreConnection, blobs: BlobStore, bundle: Bundle, item: Performed
) -> dict[str, Plain]:
    """The nodes the route left BLOCKED at the run's end, each with the verdict
    CP-0 gave its module and the producers it still waits on."""
    route = resolved_route(conn, item.run_id)
    if route is None:
        # The pin is gone: no node can be named, and an empty list must not
        # read as "the route held none".
        return {"path": "route", "nodes": [], "route_pin_missing": True}
    try:
        accepted = accepted_artifacts(conn, blobs, route, item.run_id, bundle=bundle)
    except (Refusal, ValueError) as error:
        return _readiness_unreadable(item, error)
    readiness = readiness_from(route, accepted)
    module_of = {node.route_node_id: node.module_id for node in route.nodes}
    nodes: list[Plain] = [
        {
            "route_node_id": unrun.route_node_id,
            "module_id": module_of[unrun.route_node_id],
            "verdict": readiness.get(module_of[unrun.route_node_id]),
            "verdict_from": None
            if module_of[unrun.route_node_id] not in readiness
            else GATE_MODULE,
            "held_by_verdict": readiness.get(module_of[unrun.route_node_id])
            not in (None, *READY),
            "waiting_on": [
                {
                    "module_id": edge.source,
                    "edge": edge.type.value,
                    "verdict": readiness.get(edge.source),
                }
                for edge in waiting_on(route, accepted, unrun.route_node_id)
            ],
        }
        for unrun in item.unrun
        if unrun.state is NodeState.BLOCKED
    ]
    return {"path": "route", "nodes": nodes, **_none_unrun(item)}


def _none_unrun(item: Performed) -> dict[str, Plain]:
    """The explicit marker for a route block over no recorded unrun node."""
    return {} if item.unrun else {"no_unrun_nodes": True}


def _readiness_unreadable(
    item: Performed, error: Refusal | ValueError
) -> dict[str, Plain]:
    """CP-0's record will not load (the case `harness._accepted` guards the
    same way): the capture of a paid run is not lost to it. That guard has
    already given up the readiness that separates BLOCKED from RESTRICTED or
    RUNNABLE, so `item.unrun`'s states were computed without it and the nodes a
    verdict held may no longer read BLOCKED. Every unrun node is listed, with
    its state, flagged as such; no verdict is guessed. A ValueError is a fixed
    marker (its class name), never its text."""
    return {
        "path": "route",
        "readiness_unreadable": error.code.value
        if isinstance(error, Refusal)
        else type(error).__name__,
        "states_without_readiness": True,
        "nodes": [
            {"route_node_id": unrun.route_node_id, "state": unrun.state.value}
            for unrun in item.unrun
        ],
        **_none_unrun(item),
    }


def _attempts(conn: StoreConnection, runs: list[UUID]) -> list[dict[str, Plain]]:
    """Every attempt of every prepared run, as the store recorded it, in case
    order: the charge, model and generation id a vendor bill is reconciled
    against, each row naming its run (DQ-6). Each row also names how a call
    with no answer ended and the reservation it held: a cut the provider
    declared after content (`declared_after_content`) has no charge but may
    have been billed for what it streamed, so its generation id and its
    reservation -- the most it can have cost -- stand beside the charges
    (D118 fix round 1); the run's spend is never read from charges alone."""
    return [
        {
            "run_id": str(row[0]),
            "route_node_id": str(row[1]),
            "ordinal": row[2],
            "charge": None if row[3] is None else str(row[3]),
            "model": row[4],
            "generation_id": row[5],
            "diagnostic_sha256": row[6],
            "drop_kind": row[7],
            "reserved": None if row[8] is None else str(row[8]),
        }
        for row in conn.execute(
            "SELECT t.run_id,t.route_node_id,t.ordinal,l.amount,o.model,"
            " o.generation_id,o.diagnostic_sha256,o.drop_kind,b.amount"
            " FROM run_attempts t"
            " LEFT JOIN budget_ledger l USING(attempt_id)"
            " LEFT JOIN call_outcomes o USING(attempt_id)"
            " LEFT JOIN budget_reservations b USING(attempt_id)"
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
    for attempts_left in range(attempts - 1, 0, -1):
        stopped = [record for record in performed.performed if record.stopped]
        if not stopped:
            return performed
        left = _left(conn, stopped[0])
        code = _stop_code(conn, stopped[0])
        if code is RefusalCode.BUDGET_CEILING_REACHED:
            # The ceiling refused an attempt before it reserved: entering
            # `perform` again meets the same ceiling and buys nothing.
            print(
                json.dumps({"stopped_by": code.value, "remaining": left}),
                flush=True,
            )
            return performed
        print(
            json.dumps(
                {
                    "resumed_after": code.value if code else None,
                    "attempts_left": attempts_left,
                    "remaining": left,
                }
            ),
            flush=True,
        )
        performed = perform(
            conn, blobs, harness, qualification=qualification, prepared=prepared
        )
    return performed


def _left(conn: StoreConnection, record: Performed) -> str:
    """What the record's run may still reserve, as the budget ledger says."""
    with execution_reads(conn):
        return str(remaining(conn, record.run_id))


def _stop_code(conn: StoreConnection, record: Performed) -> RefusalCode | None:
    """The code that ended `record`'s run, as the ledger reads it.

    `_with_second_attempt` re-raises the refusal before when the ceiling cannot
    pay for the retry, so `Performed.stopped` names a refusal the retry never
    answered (CP-5 #4 of qualify run 2). When that refusal is one a retry is
    owed for and the stopped node's latest attempt never reserved
    (`NodeAttempt.unreserved`), the budget is what stopped it. Any other code,
    a lost lease included, stands as raised.
    """
    if record.stopped not in SECOND_ATTEMPT_CODES | {RefusalCode.PROVIDER_UNAVAILABLE}:
        return record.stopped
    node = next((unrun for unrun in record.unrun if unrun.attempts), None)
    if node is None:
        return record.stopped
    with execution_reads(conn):
        latest = node_attempts(conn, record.run_id, node.route_node_id)
    if latest and latest[-1].unreserved:
        return RefusalCode.BUDGET_CEILING_REACHED
    return record.stopped


def _configured_provider(expect_identity: str) -> ChatCompletions | None:
    """The provider, built last, after every check that needs no client; None
    having said why nothing was spent: a workspace that cannot be reached, a
    profile the caller did not expect, or a Copilot model this machine cannot
    answer on at its pinned price -- readiness, exactly as the worker runs it
    before claiming a run (D77; F602)."""
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
    try:
        require_ready({provider.model: provider.price})
    except Refusal as refused:
        print(f"{refused.code.value}: no provider; nothing was spent", file=sys.stderr)
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
        # What admission would refuse is refused before the arithmetic too
        # (R24-N03): a set of no cases divided by zero, and a ceiling that is
        # no amount (`Infinity`, `sNaN`) failed to quantize -- a bare Decimal
        # error where every pre-spend refusal is a typed code.
        assert_measurable(qualification)
        validate_spend(args.ceiling)
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
        document = _capture(
            conn, prepared, performed, blobs=blobs, bundle=harness.bundle
        )
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
