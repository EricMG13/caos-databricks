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

    # Name where the run database's disk is read from, so a set that would fill
    # it refuses before it reserves anything (N150, F521); and pick a stopped
    # set back up in the database it stopped in rather than pin a new one.
    scripts/qualify.py <set> <the options above> \
        --docker-container caos-postgres --min-free-bytes 5368709120
    scripts/qualify.py <set> <the options above> \
        --resume caos_qualify_<32 hex> --resume-token <the `resume token:` line>

`--expect-identity` is not a convenience. A verdict binds the execution profile
it was measured under, so the run refuses before spending anything if the
environment resolves to a different one than the caller believes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from decimal import ROUND_DOWN, Decimal
from enum import Enum
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import psycopg

# Run as a script, not as a package module: the repository root is what makes
# `server` importable, and a driver nobody can run is the gap this closes.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tracked import run_argv

from caos.blobs import BlobStore
from caos.copilot import require_ready
from caos.graph.route import (
    Edge,
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
    Unrun,
    assert_admissible,
    assert_pin_eligible,
    harness_identities,
    perform,
    prepare,
)
from caos.qualification.matrix import (
    QualificationCase,
    QualificationSet,
    assert_measurable,
    qualification_set_digest,
)
from caos.qualification.on_disk import load_qualification_set
from caos.qualification.store import performed_evidence, record_evidence
from caos.refusals import Refusal, RefusalCode
from caos.store import (
    RunStatus,
    StoreConnection,
    apply_schema,
    connect,
    verify_schema,
)
from caos.store.budget import remaining, validate_spend
from caos.store.gates import Gate, GateApproval, approve_gate, gate_preview
from caos.store.members import Standing, grant
from caos.store.outcomes import execution_reads, node_attempts
from caos.store.routes import resolved_route
from caos.store.run_inputs import load_run_input

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
    (`_stop_code`); `raised` is the code the run raised, which
    `caos/qualification/store.py` persists in the evidence snapshot unchanged,
    and is None when the two agree. `blocked_by` is `_blocked_by`'s reading of
    a BLOCKED run and None for any other."""
    return {
        "case_label": item.case_label,
        "run_id": str(item.run_id),
        "status": item.status.value,
        "stopped": None if stop is None else stop.value,
        "raised": None
        if item.stopped is None or stop is item.stopped
        else item.stopped.value,
        "refusal": None if item.refusal is None else item.refusal.value,
        "proof": None if item.proof is None else _object(asdict(item.proof)),
        "blocked_by": blocked_by,
    }


def _blocked_by(
    conn: StoreConnection, blobs: BlobStore, bundle: Bundle, item: Performed
) -> dict[str, Plain] | None:
    """What blocked a BLOCKED run, read from the ledger; `path` is the only
    derived field (QF3-1).

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
    # One read unit, so the capture needs no ordering among its reads: each
    # needs an idle connection (`_capture` reads `_stop_code` first).
    with execution_reads(conn):
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
                "citations_sha256": verdict[3],
                "recorded_at": verdict[4].isoformat(),
            }
        return _route_blocked(conn, blobs, bundle, item)


# The explicit marker for a route block over no recorded unrun node.
_NO_UNRUN: dict[str, Plain] = {"no_unrun_nodes": True}


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
        _blocked_node(
            unrun,
            module_of[unrun.route_node_id],
            readiness,
            waiting_on(route, accepted, unrun.route_node_id),
        )
        for unrun in item.unrun
        if unrun.state is NodeState.BLOCKED
    ]
    # An empty list is not an answer: say when the harness recorded no node.
    return {"path": "route", "nodes": nodes, **({} if item.unrun else _NO_UNRUN)}


def _blocked_node(
    unrun: Unrun,
    module_id: str,
    readiness: Mapping[str, str],
    waits: tuple[Edge, ...],
) -> dict[str, Plain]:
    """One node the route left BLOCKED: CP-0's verdict for its module (None for
    a module CP-0 did not rule on) and the producers it still waits on."""
    return {
        "route_node_id": unrun.route_node_id,
        "module_id": module_id,
        "verdict": readiness.get(module_id),
        "waiting_on": [
            {
                "module_id": edge.source,
                "edge": edge.type.value,
                "verdict": readiness.get(edge.source),
            }
            for edge in waits
        ],
    }


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
        **({} if item.unrun else _NO_UNRUN),
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


# The data directory the local Docker probe reads (N150).
PGDATA = "/var/lib/postgresql/data"
_PROBE_SECONDS = 30
_CONTAINER_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_DATABASE_NAME = re.compile(r"caos_qualify_[0-9a-f]{32}")


class PreflightCode(Enum):
    """What the script itself refuses before it spends. Typed and text-free:
    a code and the fixed sentence around it, never a probe's output or a
    number from the server."""

    FREE_SPACE_BELOW_FLOOR = "FREE_SPACE_BELOW_FLOOR"
    FREE_SPACE_UNREADABLE = "FREE_SPACE_UNREADABLE"
    RESUME_DATABASE_INVALID = "RESUME_DATABASE_INVALID"
    RESUME_NO_PIN = "RESUME_NO_PIN"
    RESUME_PIN_MISMATCH = "RESUME_PIN_MISMATCH"


class PreflightRefusal(Exception):
    def __init__(self, code: PreflightCode) -> None:
        super().__init__(code.value)
        self.code = code


@dataclass(frozen=True)
class Probe:
    """How free bytes are read: an operator's command, or `df` in a container."""

    command: str | None
    docker_container: str | None


def _parsed_free_bytes(answer: str) -> int:
    """One whole number of bytes and nothing else; anything more or less is
    refused, so a probe that misreports can never read as room."""
    text = answer.strip()
    if not (text.isascii() and text.isdigit()):
        raise PreflightRefusal(PreflightCode.FREE_SPACE_UNREADABLE)
    return _whole(text)


def _whole(text: str) -> int:
    """`int(text)` for digits, a refusal for a number Python will not convert
    (over 4300 digits raises ValueError): never a traceback."""
    try:
        return int(text)
    except ValueError:
        raise PreflightRefusal(PreflightCode.FREE_SPACE_UNREADABLE) from None


def _free_bytes_from_df(answer: str) -> int:
    """The Available column of `df -P` (1024-byte blocks), in bytes: a header
    and exactly one filesystem line."""
    lines = answer.strip().splitlines()
    header = lines[0].split() if lines else []
    # A POSIXLY_CORRECT busybox prints 512-byte blocks: reading those as KiB
    # would double the answer, so any other unit refuses.
    if len(lines) != 2 or header[:2] != ["Filesystem", "1024-blocks"]:
        raise PreflightRefusal(PreflightCode.FREE_SPACE_UNREADABLE)
    fields = lines[1].split()
    if len(fields) < 6 or not (fields[3].isascii() and fields[3].isdigit()):
        raise PreflightRefusal(PreflightCode.FREE_SPACE_UNREADABLE)
    return _whole(fields[3]) * 1024


def _free_bytes(probe: Probe) -> int:
    """Run the named probe (no shell, bounded time) and read its answer. Any
    failure to run it is a refusal: an unmeasured disk is not a roomy one."""
    try:
        argv = (
            ["docker", "exec", probe.docker_container, "df", "-P", PGDATA]
            if probe.docker_container is not None
            else shlex.split(probe.command or "")
        )
        # docker's own name rule: a name that starts with `-` would be read as
        # an option, so it is refused rather than passed.
        named = probe.docker_container
        if not argv or (named is not None and not _CONTAINER_NAME.fullmatch(named)):
            raise PreflightRefusal(PreflightCode.FREE_SPACE_UNREADABLE)
        done = run_argv(argv, timeout=_PROBE_SECONDS)
    except (OSError, ValueError, TimeoutError):
        # Unrunnable, unparseable or timed out: the same typed refusal; the
        # cause (a path, an argument) is not repeated.
        raise PreflightRefusal(PreflightCode.FREE_SPACE_UNREADABLE) from None
    if done.returncode != 0:
        raise PreflightRefusal(PreflightCode.FREE_SPACE_UNREADABLE)
    if probe.docker_container is not None:
        return _free_bytes_from_df(done.stdout)
    return _parsed_free_bytes(done.stdout)


def _preflight(args: argparse.Namespace) -> None:
    """The checks that need neither the provider nor the store: the resume
    name, and the free-space floor when a probe is named (N150)."""
    if args.resume is not None and not _DATABASE_NAME.fullmatch(args.resume):
        raise PreflightRefusal(PreflightCode.RESUME_DATABASE_INVALID)
    if args.free_space_probe is None and args.docker_container is None:
        print(
            "no free-space probe named: free space is not checked",
            file=sys.stderr,
        )
        return
    free = _free_bytes(Probe(args.free_space_probe, args.docker_container))
    if free < args.min_free_bytes:
        raise PreflightRefusal(PreflightCode.FREE_SPACE_BELOW_FLOOR)


def _non_negative(text: str) -> int:
    if not (text.isascii() and text.isdigit()):
        raise ValueError  # argparse names the option and the bad value
    return int(text)


def resume_token(set_digest: str, provider: str, model: str, database: str) -> str:
    """What a start prints and `--resume` must be given back (N-2, N-3).

    A driver killed before its first snapshot leaves nothing in the database
    that records the set digest, so a resume could bind paid calls to an edited
    answer key. The operator carries the binding instead: a SHA-256 over the
    set digest, the provider and model identity exactly as `--expect-identity`
    states them (an output-cap segment included), and the database name, so a
    token another start of the same set printed (another database) does not
    pass either. It guards against a mistake -- a mixed-up token, an edited
    key after a crash -- not against an operator who recomputes it: that
    operator owns the set and the database and could as well start afresh."""
    bound = json.dumps([set_digest, provider, model, database], separators=(",", ":"))
    return hashlib.sha256(bound.encode("utf-8")).hexdigest()


def _resumed_pins(
    conn: StoreConnection,
    harness: Harness,
    qualification: QualificationSet,
    database: str,
    token: str,
) -> tuple[PreparedCase, ...]:
    """The set's pins as the database holds them, re-checked as `perform`
    would: one run per case in order, built from this bundle, and equal to what
    the set says now; `token` must be the one this database's start printed.
    Nothing is written."""
    # An out-of-date store refuses typed up front (STORE_SCHEMA_DRIFT).
    verify_schema(conn)
    rows = conn.execute(
        "SELECT c.title, r.run_id FROM runs r JOIN cases c USING (case_id)"
        " ORDER BY r.created_at, r.run_id"
    ).fetchall()
    conn.rollback()
    if not rows:
        raise PreflightRefusal(PreflightCode.RESUME_NO_PIN)
    if [row[0] for row in rows] != [case.label for case in qualification.cases]:
        raise PreflightRefusal(PreflightCode.RESUME_PIN_MISMATCH)
    digest = qualification_set_digest(qualification)
    provider, model = harness_identities(harness.completions)
    if resume_token(digest, provider, model, database) != token:
        raise PreflightRefusal(PreflightCode.RESUME_PIN_MISMATCH)
    _assert_same_binding(conn, (digest, provider, model))
    try:
        return tuple(
            _resumed_pin(conn, harness, case, row, (digest, provider, model))
            for case, row in zip(qualification.cases, rows, strict=True)
        )
    finally:
        conn.rollback()


_OTHER_BINDING = (
    "SELECT 1 FROM qualification_performed WHERE"
    " (qualification_set_sha256, provider, model) IS DISTINCT FROM (%s, %s, %s)"
    " LIMIT 1",
    "SELECT 1 FROM qualification_evidence WHERE"
    " (qualification_set_sha256, provider, model) IS DISTINCT FROM (%s, %s, %s)"
    " LIMIT 1",
)


def _assert_same_binding(conn: StoreConnection, binding: tuple[str, str, str]) -> None:
    """Refuse `RESUME_PIN_MISMATCH` unless everything the database already
    recorded was made under this set, provider and model.

    `perform` compares a `PreparedCase` with the harness it was built from, so
    on a resume that check compares the current values with themselves: a
    resume under another model paid again and left a set no one can sign. The
    stored snapshots and evidence name what they were made under, and the
    calls recorded in the ledger name the model they were paid under (which
    covers a driver killed before its first snapshot)."""
    for query in _OTHER_BINDING:
        if conn.execute(query, binding).fetchone() is not None:
            conn.rollback()
            raise PreflightRefusal(PreflightCode.RESUME_PIN_MISMATCH)
    paid = conn.execute(
        "SELECT 1 FROM call_outcomes WHERE model IS NOT NULL AND model <> %s LIMIT 1",
        (binding[2],),
    ).fetchone()
    conn.rollback()
    if paid is not None:
        raise PreflightRefusal(PreflightCode.RESUME_PIN_MISMATCH)


def _resumed_pin(
    conn: StoreConnection,
    harness: Harness,
    case: QualificationCase,
    row: tuple[str, UUID],
    identity: tuple[str, str, str],
) -> PreparedCase:
    """One case's pin, from the store, checked as `perform` will check it."""
    label, run_id = row
    try:
        pin = load_run_input(conn, run_id)
        # The read keeps its transaction; `execution_reads` wants an idle one.
        conn.rollback()
        if pin is None:
            raise PreflightRefusal(PreflightCode.RESUME_NO_PIN)
        item = PreparedCase(label, pin, *identity)
        with execution_reads(conn):
            assert_pin_eligible(conn, harness, case, item)
    except Refusal as refused:
        # A pin that will not load or no longer equals the set is a mismatch;
        # any other typed refusal (the store, the bundle) stands as itself.
        if refused.code is not RefusalCode.RUN_INPUT_INVALID:
            raise
        raise PreflightRefusal(PreflightCode.RESUME_PIN_MISMATCH) from None
    return item


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
        stopped = [(item, item.stopped) for item in performed.performed if item.stopped]
        if not stopped:
            return performed
        record, raised = stopped[0]
        left = _left(conn, record)
        if _stop_code(conn, record) is RefusalCode.BUDGET_CEILING_REACHED:
            # The ceiling refused an attempt before it reserved: entering
            # `perform` again meets the same ceiling and buys nothing.
            print(
                json.dumps(
                    {
                        "stopped_by": RefusalCode.BUDGET_CEILING_REACHED.value,
                        "remaining": left,
                    }
                ),
                flush=True,
            )
            return performed
        print(
            json.dumps(
                {
                    "resumed_after": raised.value,
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
    """The code that ended `record`'s run, read back from the ledger.

    `_with_second_attempt` re-raises the refusal before when the ceiling cannot
    pay for the retry, so `Performed.stopped` names a refusal the retry never
    answered (CP-5 #4 of qualify run 2). When that refusal is one a retry is
    owed for and the stopped node's latest attempt never reserved
    (`NodeAttempt.never_reserved`), the budget is what stopped it. Any other code,
    a lost lease included, stands as raised. The ledger holds no `reserve`
    refusal: this is `_with_second_attempt`'s `unpaid` rule read back, so revisit
    it if that rule changes. A record whose `unrun` could not be read keeps its
    raised code and may be re-entered once more.
    """
    if record.stopped not in SECOND_ATTEMPT_CODES | {RefusalCode.PROVIDER_UNAVAILABLE}:
        return record.stopped
    node = next((unrun for unrun in record.unrun if unrun.attempts), None)
    if node is None:
        return record.stopped
    with execution_reads(conn):
        latest = node_attempts(conn, record.run_id, node.route_node_id)
    if latest and latest[-1].never_reserved:
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
    parser.add_argument(
        "--free-space-probe",
        help=(
            "a command (no shell) whose whole output is the free bytes on the"
            " run database's disk; below --min-free-bytes the run refuses"
            " before it reserves anything"
        ),
    )
    parser.add_argument(
        "--docker-container",
        help=f"read the free bytes with `docker exec <name> df -P {PGDATA}`",
    )
    parser.add_argument(
        "--min-free-bytes",
        type=_non_negative,
        default=2**30,
        help="the free-space floor, in bytes (default 1 GiB)",
    )
    parser.add_argument(
        "--resume-token",
        metavar="HEX",
        help="the `resume token:` line the run printed when it started",
    )
    parser.add_argument(
        "--resume",
        metavar="DATABASE",
        help=(
            "re-enter perform on the pins already in this caos_qualify_*"
            " database instead of creating a new one"
        ),
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


def _database_url(admin_url: str, database: str) -> str:
    return urlunsplit(urlsplit(admin_url)._replace(path=f"/{database}"))


def _create_database(admin_url: str) -> tuple[str, str]:
    """A fresh database on the persistent server: its name and its URL."""
    database = f"caos_qualify_{uuid4().hex}"
    run_url = _database_url(admin_url, database)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(
            psycopg.sql.SQL("CREATE DATABASE {}").format(
                psycopg.sql.Identifier(database)
            )
        )
    return database, run_url


@dataclass(frozen=True)
class _Start:
    """Everything a run needs once every refusal that spends nothing is past:
    the set, its harness, the database (new, or the one resumed) and the pins a
    resume found there (None for a new run, which prepares them)."""

    qualification: QualificationSet
    harness: Harness
    database: str
    run_url: str
    blob_root: str
    resumed: tuple[PreparedCase, ...] | None


def _performed_capture(start: _Start, *, attempts: int) -> dict[str, object]:
    """Prepare, approve and perform the set in its database; its capture.

    A resumed set is already prepared and approved: it performs on those pins."""
    harness, qualification = start.harness, start.qualification
    with connect(start.run_url) as conn:
        blobs = BlobStore(Path(start.blob_root))
        if start.resumed is None:
            apply_schema(conn)
            prepared = prepare(conn, blobs, harness, qualification=qualification)
            _approve_every_gate(conn, prepared)
        else:
            prepared = start.resumed
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


def _refused(code: str) -> None:
    print(f"{code}: the set was refused; nothing was spent", file=sys.stderr)


def _opened(
    args: argparse.Namespace,
    qualification: QualificationSet,
    harness: Harness,
    admin_url: str,
    blob_root: str,
) -> _Start | None:
    """The database the run goes in: a new one, or the one `--resume` names with
    its pins re-checked. None, having said why nothing was spent."""
    resumed: tuple[PreparedCase, ...] | None = None
    try:
        if args.resume is None:
            database, run_url = _create_database(admin_url)
        else:
            database = args.resume
            run_url = _database_url(admin_url, database)
            with connect(run_url) as conn:
                resumed = _resumed_pins(
                    conn, harness, qualification, database, args.resume_token
                )
    except (PreflightRefusal, Refusal) as refused:
        _refused(refused.code.value)
        return None
    except psycopg.Error:
        # CF-078: a DSN psycopg itself refuses to parse -- bad percent-encoding
        # in a password included -- quotes the whole string, password and all,
        # in its own message; only the typed code is ever printed here.
        _refused(RefusalCode.STORE_UNAVAILABLE.value)
        return None
    return _Start(qualification, harness, database, run_url, blob_root, resumed)


def _started(args: argparse.Namespace) -> _Start | None:
    """Every check that spends nothing, then the database; None having said
    which refused. The free-space floor is read first (N150), before the
    provider is built or anything is reserved."""
    if args.attempts < 1:
        print("--attempts must be at least 1; nothing was spent", file=sys.stderr)
        return None
    if args.free_space_probe is not None and args.docker_container is not None:
        print("name one free-space probe, not both; nothing was spent", file=sys.stderr)
        return None
    try:
        _preflight(args)
        planned = _planned(args)
    except (PreflightRefusal, Refusal) as refused:
        _refused(refused.code.value)
        return None
    if planned is None:
        return None
    return _opened(args, *planned)


def _print_resume_token(start: _Start) -> None:
    """The line `--resume` must be given back, printed before any call."""
    provider, model = harness_identities(start.harness.completions)
    digest = qualification_set_digest(start.qualification)
    token = resume_token(digest, provider, model, start.database)
    print(f"resume token: {token}", file=sys.stderr)


def _print_preamble(start: _Start) -> None:
    # Printed before the call, not after: a driver that dies mid-run must still
    # leave the operator the two names that hold the evidence it paid for, and
    # the dated price every reservation it is about to take will be priced on
    # (Task 8.2) -- an operator reading the ceiling alone cannot tell whether a
    # set was affordable at the price the worker was configured with.
    price = start.harness.price
    print(
        json.dumps(
            {
                "database": start.database,
                "blob_root": start.blob_root,
                "run_ceiling": str(start.harness.run_ceiling),
                "price_model": price.model,
                "price_input_per_token": str(price.input_per_token),
                "price_output_per_token": str(price.output_per_token),
                "price_as_of": price.as_of.isoformat(),
                "price_worst_case_per_call": str(worst_case(price)),
            }
        ),
        flush=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if (args.resume is None) != (args.resume_token is None):
        parser.error("--resume and --resume-token are given together")
    start = _started(args)
    if start is None:
        return 2
    _print_resume_token(start)
    _print_preamble(start)
    database = start.database
    try:
        document = _performed_capture(start, attempts=args.attempts)
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
