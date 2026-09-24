"""One PostgreSQL store with ordered, immutable host-owned migrations."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import tuple_row

from caos.refusals import Refusal, RefusalCode

type StoreConnection = psycopg.Connection[tuple[Any, ...]]

SCHEMA = (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")
# Append reviewed SQL files here; never edit an applied entry or schema.sql.
MIGRATIONS = (
    ("0001_legacy", SCHEMA),
    (
        "0002_extraction",
        Path(__file__).with_name("0002_extraction.sql").read_text(encoding="utf-8"),
    ),
    (
        "0003_source_sets",
        Path(__file__).with_name("0003_source_sets.sql").read_text(encoding="utf-8"),
    ),
    (
        "0004_route_integrity",
        Path(__file__)
        .with_name("0004_route_integrity.sql")
        .read_text(encoding="utf-8"),
    ),
    (
        "0005_run_inputs",
        Path(__file__).with_name("0005_run_inputs.sql").read_text(encoding="utf-8"),
    ),
    (
        "0006_budget",
        Path(__file__).with_name("0006_budget.sql").read_text(encoding="utf-8"),
    ),
    (
        "0007_call_outcomes",
        Path(__file__).with_name("0007_call_outcomes.sql").read_text(encoding="utf-8"),
    ),
    (
        "0008_frozen_evidence",
        Path(__file__)
        .with_name("0008_frozen_evidence.sql")
        .read_text(encoding="utf-8"),
    ),
    (
        "0009_accepted_owner",
        Path(__file__).with_name("0009_accepted_owner.sql").read_text(encoding="utf-8"),
    ),
    (
        "0010_blocked_runs",
        Path(__file__).with_name("0010_blocked_runs.sql").read_text(encoding="utf-8"),
    ),
    (
        "0011_run_subject",
        Path(__file__).with_name("0011_run_subject.sql").read_text(encoding="utf-8"),
    ),
    (
        "0012_artifact_record",
        Path(__file__)
        .with_name("0012_artifact_record.sql")
        .read_text(encoding="utf-8"),
    ),
    (
        "0013_run_work",
        Path(__file__).with_name("0013_run_work.sql").read_text(encoding="utf-8"),
    ),
    (
        "0014_command_requests",
        Path(__file__)
        .with_name("0014_command_requests.sql")
        .read_text(encoding="utf-8"),
    ),
    (
        "0015_revisions",
        Path(__file__).with_name("0015_revisions.sql").read_text(encoding="utf-8"),
    ),
    (
        "0016_filed_receipts",
        Path(__file__).with_name("0016_filed_receipts.sql").read_text(encoding="utf-8"),
    ),
    (
        "0017_legacy_filing_events",
        Path(__file__)
        .with_name("0017_legacy_filing_events.sql")
        .read_text(encoding="utf-8"),
    ),
    (
        "0018_qualification_verdicts",
        Path(__file__)
        .with_name("0018_qualification_verdicts.sql")
        .read_text(encoding="utf-8"),
    ),
    (
        "0019_one_qualification_verdict",
        Path(__file__)
        .with_name("0019_one_qualification_verdict.sql")
        .read_text(encoding="utf-8"),
    ),
    (
        "0020_qualification_performed",
        Path(__file__)
        .with_name("0020_qualification_performed.sql")
        .read_text(encoding="utf-8"),
    ),
    (
        "0021_blocking_verdicts",
        Path(__file__)
        .with_name("0021_blocking_verdicts.sql")
        .read_text(encoding="utf-8"),
    ),
    (
        "0024_reservation_price",
        Path(__file__)
        .with_name("0024_reservation_price.sql")
        .read_text(encoding="utf-8"),
    ),
    (
        "0025_supersedes",
        Path(__file__).with_name("0025_supersedes.sql").read_text(encoding="utf-8"),
    ),
    # `0022` and `0023` are permanent gaps -- two streams allocated at once and
    # `0024`/`0025` landed first. Never fill them: ordering is tuple position,
    # so a migration inserted below the applied head passes on a fresh database
    # and refuses STORE_SCHEMA_DRIFT only in production (`docs/MIGRATIONS.md`).
    (
        "0026_case_members_by_user",
        Path(__file__)
        .with_name("0026_case_members_by_user.sql")
        .read_text(encoding="utf-8"),
    ),
    (
        "0027_evidence_statement_trigger",
        Path(__file__)
        .with_name("0027_evidence_statement_trigger.sql")
        .read_text(encoding="utf-8"),
    ),
    (
        "0028_worker_heartbeats",
        Path(__file__)
        .with_name("0028_worker_heartbeats.sql")
        .read_text(encoding="utf-8"),
    ),
    (
        "0029_one_opinion_per_signer",
        Path(__file__)
        .with_name("0029_one_opinion_per_signer.sql")
        .read_text(encoding="utf-8"),
    ),
    (
        "0031_verdict_recorded_at",
        Path(__file__)
        .with_name("0031_verdict_recorded_at.sql")
        .read_text(encoding="utf-8"),
    ),
    (
        "0032_run_parked_event",
        Path(__file__)
        .with_name("0032_run_parked_event.sql")
        .read_text(encoding="utf-8"),
    ),
    (
        "0033_governed_writes_immutable",
        Path(__file__)
        .with_name("0033_governed_writes_immutable.sql")
        .read_text(encoding="utf-8"),
    ),
    (
        "0034_worker_stopped_state",
        Path(__file__)
        .with_name("0034_worker_stopped_state.sql")
        .read_text(encoding="utf-8"),
    ),
    (
        "0035_packing_by_token",
        Path(__file__)
        .with_name("0035_packing_by_token.sql")
        .read_text(encoding="utf-8"),
    ),
    (
        "0036_hidden_text",
        Path(__file__).with_name("0036_hidden_text.sql").read_text(encoding="utf-8"),
    ),
    (
        "0037_attempts_artifacts_immutable",
        Path(__file__)
        .with_name("0037_attempts_artifacts_immutable.sql")
        .read_text(encoding="utf-8"),
    ),
    (
        "0038_queued_runs_per_actor",
        Path(__file__)
        .with_name("0038_queued_runs_per_actor.sql")
        .read_text(encoding="utf-8"),
    ),
    (
        "0039_hidden_optional_content",
        Path(__file__)
        .with_name("0039_hidden_optional_content.sql")
        .read_text(encoding="utf-8"),
    ),
    (
        "0040_hidden_painted_over",
        Path(__file__)
        .with_name("0040_hidden_painted_over.sql")
        .read_text(encoding="utf-8"),
    ),
    (
        "0041_filed_packages",
        Path(__file__).with_name("0041_filed_packages.sql").read_text(encoding="utf-8"),
    ),
    (
        "0042_hidden_colorant_none",
        Path(__file__)
        .with_name("0042_hidden_colorant_none.sql")
        .read_text(encoding="utf-8"),
    ),
)

# DL-1: the store's own schema, beside LangGraph's `caos_graph`
# (`caos.graph.checkpoint.SCHEMA`) and named the same way: the app creates it
# at `apply_schema`, and every store connection names it as its whole
# `search_path` at connect time (`connect`), so the unqualified names in
# `schema.sql` and every migration resolve here and never in `public`, where
# PostgreSQL 15 and later give nobody CREATE. `CAN_CONNECT_AND_CREATE`'s
# CREATE on the database is what creating it takes; nothing else is granted
# by hand. The migration bytes are unchanged: a schema is chosen by the
# session, not written into the SQL.
STORE_SCHEMA = "caos_store"
SEARCH_PATH_OPTION = f"-c search_path={STORE_SCHEMA}"
# LangGraph's own schema (`caos.graph.checkpoint.SCHEMA`), named here rather
# than imported: the store does not depend on the graph package. The store
# writes to it too, forgetting a cancelled run's thread (`work._forget_threads`).
CHECKPOINT_SCHEMA = "caos_graph"

# W2: whether a schema is there, and whether it and everything in it -- the
# bookkeeping tables, every table, index, sequence and function -- belong to
# the role this session acts as. `CAN_CONNECT_AND_CREATE` gives any principal
# bound to the database CREATE on it, so a co-tenant can create either schema
# first: the app would then run on tables whose owner can disable their
# immutability triggers, and a trigger of theirs would run as the app's role.
_OWNED_SCHEMA = (
    "SELECT pg_get_userbyid(n.nspowner) = current_user"
    " AND NOT EXISTS (SELECT 1 FROM pg_class c WHERE c.relnamespace = n.oid"
    "   AND pg_get_userbyid(c.relowner) <> current_user)"
    " AND NOT EXISTS (SELECT 1 FROM pg_proc p WHERE p.pronamespace = n.oid"
    "   AND pg_get_userbyid(p.proowner) <> current_user)"
    " FROM pg_namespace n WHERE n.nspname = %s"
)

# One well-known lock, held for the applying transaction only, so two processes
# starting at once do not both read an empty bookkeeping table and both apply.
# The value is arbitrary and permanent; it identifies this lock, nothing else.
_SCHEMA_LOCK = 0x0CA05_5CE_1
# Metadata lives outside the immutable baseline. The legacy digest is replaced
# by a digest of the full ordered history on adoption. IF NOT EXISTS only
# bootstraps metadata; it never substitutes for a business-schema migration.
#
# One row, enforced by the database rather than argued from the lock above: the
# primary key admits only `true` and the CHECK admits only `true`, so a second
# row cannot be inserted and `SELECT` cannot become order-dependent.
_BOOKKEEPING = (
    "CREATE TABLE IF NOT EXISTS store_schema ("
    " only_row boolean PRIMARY KEY DEFAULT true CHECK (only_row),"
    " applied_digest text NOT NULL)"
)
_HISTORY = (
    "CREATE TABLE IF NOT EXISTS store_migrations ("
    " version integer PRIMARY KEY CHECK (version > 0),"
    " name text NOT NULL UNIQUE, digest text NOT NULL,"
    " applied_at timestamptz NOT NULL DEFAULT now())"
)


# The two codes that mean the store itself could not answer, rather than that
# what it holds disagrees with the declared history.
_STORE_SILENT = frozenset(
    {RefusalCode.STORE_UNAVAILABLE, RefusalCode.STORE_NOT_TRANSACTIONAL}
)

# R24-05: the SQLSTATE classes that say the session or the server could not
# answer this time -- connection exception, transaction rollback, insufficient
# resources, operator intervention (an ended session, a cancelled statement) --
# rather than that the database refused a statement the declared history holds.
_INTERRUPTED = frozenset({"08", "40", "53", "57"})
# N2: and one state of class 55 whose others are findings: `lock_not_available`,
# a lock wait a `lock_timeout` ended -- the API lifespan and the in-process
# worker both apply the schema at boot, and one waits for the other's lock.
_LOCK_NOT_AVAILABLE = "55P03"


class RunStatus(StrEnum):
    """A run's own state. Node states are the bundle's four and are not these."""

    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    # Recoverable: the route has required work no accepted result can release.
    BLOCKED = "BLOCKED"
    # A requested cancel took effect before any worker drove the run further.
    CANCELLED = "CANCELLED"


# CF-041: a peer that vanished without closing the socket -- a container
# killed under it, a network partition -- otherwise leaves a connection
# psycopg still calls open, with every statement on it blocking until the
# OS's own keepalive defaults give up (Linux ships `tcp_keepalive_time=7200`,
# two hours, far past any lease). These probe well inside that: idle a while,
# then a handful of tries close enough together to notice within about a
# minute. `tcp_user_timeout` is Linux's own, more precise bound on the same
# question and a documented no-op everywhere libpq does not support it, so it
# is always safe to send.
KEEPALIVES_IDLE_SECONDS = 30
KEEPALIVES_INTERVAL_SECONDS = 10
KEEPALIVES_COUNT = 3
TCP_USER_TIMEOUT_MS = 30_000
# The connection parameters that carry them, for every connection to the
# store's database: `connect`'s own, and the checkpointer pool's (W4), which
# opens its connections itself and so never passed through `connect`.
SOCKET_BOUNDS: Mapping[str, int] = MappingProxyType(
    {
        "keepalives": 1,
        "keepalives_idle": KEEPALIVES_IDLE_SECONDS,
        "keepalives_interval": KEEPALIVES_INTERVAL_SECONDS,
        "keepalives_count": KEEPALIVES_COUNT,
        "tcp_user_timeout": TCP_USER_TIMEOUT_MS,
    }
)


def startup_options(url: str, options: Sequence[str]) -> str:
    """The `options` a connection to `url` starts with (N4): the operator's
    first -- the DSN's own, or `PGOPTIONS` where the DSN names none, which is
    how libpq reads them -- then `options`, this process's, which the server
    applies last and so win for any parameter both name.

    A keyword `options` replaces the DSN's outright, and libpq falls back to
    `PGOPTIONS` only when none is given, so the operator's `lock_timeout` or
    `application_name` never reached the server.
    """
    named = conninfo_to_dict(url)
    theirs = named["options"] if "options" in named else os.environ.get("PGOPTIONS")
    return " ".join(str(part) for part in (theirs, *options) if part)


def connect(
    url: str,
    *,
    connect_timeout: int | None = None,
    statement_timeout_ms: int | None = None,
) -> StoreConnection:
    """A connection with the store's policy on it: transactions are explicit.

    `connect_timeout` (seconds) bounds the connection attempt, for a caller
    such as the health probe that must not wait on an unanswering host.

    Every connection's `search_path` is the store's own schema alone
    (`STORE_SCHEMA`, DL-1), sent as a startup option like the bound below,
    after the operator's own (`startup_options`), which it overrides.

    `statement_timeout_ms` bounds every statement for the connection's whole
    session (`options`, at connect time -- not `SET LOCAL`, which a caller's
    own commits keep resetting, and not a bare `SET`, which a one-shot caller
    would have to remember to `RESET`). Left `None` for a caller such as
    `apply_schema`'s, which may legitimately run longer than the bound a
    caller that reuses this connection for many short statements wants; the
    worker's own polling connection passes one well under `LEASE_SECONDS`, so
    one wedged query cannot hold a lease past the point another worker would
    otherwise have reclaimed it.

    A connection that fails drops the cached Lakebase credential, so the next
    one mints (ST-2): the API, the health probes and the lifespan open theirs
    here, and a token revoked early would otherwise be sent until it aged out.
    """
    from caos.store.lakebase import note_connect_failure

    kwargs: dict[str, Any] = dict(SOCKET_BOUNDS)
    if connect_timeout is not None:
        kwargs["connect_timeout"] = connect_timeout
    options = [SEARCH_PATH_OPTION]
    if statement_timeout_ms is not None:
        options.append(f"-c statement_timeout={statement_timeout_ms}")
    kwargs["options"] = startup_options(url, options)
    try:
        return psycopg.connect(url, autocommit=False, **kwargs)
    except psycopg.OperationalError as failed:
        note_connect_failure(failed)
        raise


def owned_schema(conn: psycopg.Connection[Any], schema: str) -> bool:
    """Whether `schema` exists, refusing `STORE_SCHEMA_DRIFT` for one that
    another role owns or holds anything in (W2).

    Read on a cursor of its own, so the checkpointer's dict-row connections ask
    it the same way the store's own do. Nothing is written: a refusal leaves
    the caller's transaction as it was, for the caller to end.
    """
    with conn.cursor(row_factory=tuple_row) as cursor:
        row = cursor.execute(_OWNED_SCHEMA, (schema,)).fetchone()
    if row is None:
        return False
    if row != (True,):
        raise Refusal(RefusalCode.STORE_SCHEMA_DRIFT)
    return True


def rollback_or_close(conn: StoreConnection) -> None:
    """A failed rollback must not mask the refusal or leave a committable unit."""
    try:
        conn.rollback()
    except psycopg.Error:
        conn.close()


@contextmanager
def committed_unit(conn: StoreConnection) -> Iterator[None]:
    """Own the caller transaction: commit on exit, roll back or close on any
    failure, and answer a store fault with STORE_UNAVAILABLE and no text."""
    try:
        yield
        conn.commit()
    except psycopg.Error:
        rollback_or_close(conn)
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
    except BaseException:
        # Any failure at all, cancellation included: letting it propagate with
        # the unit open leaves state the body made sitting there, ready to be
        # committed by whatever the caller does next -- state without the event
        # that transactional pairing exists to bind to it.
        rollback_or_close(conn)
        raise


def apply_schema(conn: StoreConnection, *, sql: str = SCHEMA) -> None:
    """Advance a verified migration prefix atomically, or refuse sanitized.

    Owns and completes the caller transaction, as before: call before business
    writes. `sql` is retained for compatibility but must match the legacy file.
    """
    if conn.autocommit:
        raise Refusal(RefusalCode.STORE_NOT_TRANSACTIONAL)
    try:
        _migrate(conn, sql)
        conn.commit()
    except Refusal as refused:
        # Only "the store could not answer" keeps its own code. Everything else
        # a migration refuses -- including a malformed row its own verification
        # finds, which may be raised from outside this module -- is a drift
        # finding and says so.
        rollback_or_close(conn)
        if refused.code in _STORE_SILENT:
            raise
        raise Refusal(RefusalCode.STORE_SCHEMA_DRIFT) from None
    except psycopg.Error as fault:
        rollback_or_close(conn)
        # SQLSTATE is the standard's five-character class code, never text --
        # but the field is the server's, so the length is this module's.
        print(f"schema: sqlstate {(fault.sqlstate or '?????')[:5]}", file=sys.stderr)
        raise Refusal(_schema_fault_code(fault)) from None
    except BaseException:
        rollback_or_close(conn)
        raise


def interrupted(fault: psycopg.Error) -> bool:
    """Whether a store fault is the store failing to answer this time (R24-05),
    rather than refusing a statement.

    A session the client saw close carries no SQLSTATE at all, and a server
    that ended it or cancelled the statement says so by class, as it says a
    lock wait timed out by its own state (N2). Anything else -- a statement the
    database refused, a constraint, a trigger's refusal -- is a finding about
    what it holds, which asking again will not change. The boot's classifier
    (`_schema_fault_code`) and the request edge's (`caos.api.deps`, N5).
    """
    if fault.sqlstate is None:
        return isinstance(fault, psycopg.OperationalError)
    return fault.sqlstate[:2] in _INTERRUPTED or fault.sqlstate == _LOCK_NOT_AVAILABLE


def _schema_fault_code(fault: psycopg.Error) -> RefusalCode:
    """`STORE_UNAVAILABLE` for an interruption, `STORE_SCHEMA_DRIFT` otherwise.

    The worker's boot loop asks the store again after an interruption; drift is
    final, so only a statement the database refused -- a disagreement with what
    it holds -- may be named drift.
    """
    return (
        RefusalCode.STORE_UNAVAILABLE
        if interrupted(fault)
        else RefusalCode.STORE_SCHEMA_DRIFT
    )


def verify_schema(conn: StoreConnection) -> None:
    """Refuse `STORE_SCHEMA_DRIFT` unless every declared migration is applied.

    The check `_migrate` makes, read-only: SELECTs alone, no DDL, no advisory
    lock, no write and no commit -- the caller owns (and should roll back or
    close) the transaction. A partial prefix is drift here too: a process that
    serves requests is one whose startup advanced it in full. A missing
    bookkeeping table is drift; any other store error propagates as itself.
    """
    expected = _expected_history()
    try:
        applied = conn.execute("SELECT applied_digest FROM store_schema").fetchone()
        history = conn.execute(
            "SELECT version, name, digest FROM store_migrations ORDER BY version"
        ).fetchall()
    except psycopg.errors.UndefinedTable:
        raise Refusal(RefusalCode.STORE_SCHEMA_DRIFT) from None
    head = sha256(json.dumps(expected).encode("utf-8")).hexdigest()
    if history != expected or applied != (head,):
        raise Refusal(RefusalCode.STORE_SCHEMA_DRIFT)


def _expected_history() -> list[tuple[int, str, str]]:
    """The ordered `(version, name, digest)` rows a fully migrated store holds."""
    if not MIGRATIONS or MIGRATIONS[0] != ("0001_legacy", SCHEMA):
        raise Refusal(RefusalCode.STORE_SCHEMA_DRIFT)
    return [
        (version, name, sha256(body.encode("utf-8")).hexdigest())
        for version, (name, body) in enumerate(MIGRATIONS, 1)
    ]


def _refuse_unmigratable_rows(
    conn: StoreConnection, version: int, name: str, applied_count: int
) -> None:
    """Refuse `STORE_SCHEMA_DRIFT` before a migration whose rows it cannot
    decide for: the store holds governed rows only an operator may reconcile."""
    if (version, name) == (17, "0017_legacy_filing_events") and applied_count == 16:
        ambiguous = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM audit_events e"
            " LEFT JOIN deliverable_receipts r ON r.case_id=e.case_id"
            " AND r.filed_event_sha256=e.entry_sha256"
            " WHERE e.action='DELIVERABLE_FILED' AND r.revision_id IS NULL)"
        ).fetchone()
        if ambiguous != (False,):
            raise Refusal(RefusalCode.STORE_SCHEMA_DRIFT)
    if name == "0029_one_opinion_per_signer":
        # A signer who signed one revision twice left two governed rows, each
        # named by an OPINION_SIGNED event; which to keep is an operator's call.
        doubled = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM deliverable_opinions"
            " GROUP BY case_id, revision_id, signed_by HAVING count(*) > 1)"
        ).fetchone()
        if doubled != (False,):
            raise Refusal(RefusalCode.STORE_SCHEMA_DRIFT)


def _migrate(conn: StoreConnection, sql: str) -> None:
    """Validate the complete applied prefix under the lock before advancing it."""
    if sql != SCHEMA:
        raise Refusal(RefusalCode.STORE_SCHEMA_DRIFT)
    expected = _expected_history()
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK,))
    # Before anything is created or read in it (W2): a schema another role
    # made first is not adopted, and the checkpoint schema is checked here as
    # well, because the API process writes to it and never sets it up. Created
    # only when it is not there (N3): `CREATE SCHEMA`, `IF NOT EXISTS` or not,
    # takes CREATE on the database, and a role that owns both needs no more
    # than CONNECT to boot. Under the lock, so two processes cannot both miss
    # it; plain `CREATE`, so one another role made since is refused (42P06).
    if not owned_schema(conn, STORE_SCHEMA):
        conn.execute(f"CREATE SCHEMA {STORE_SCHEMA}")
    owned_schema(conn, CHECKPOINT_SCHEMA)
    conn.execute(_BOOKKEEPING)
    conn.execute(_HISTORY)
    applied = conn.execute("SELECT applied_digest FROM store_schema").fetchone()
    history = conn.execute(
        "SELECT version, name, digest FROM store_migrations ORDER BY version"
    ).fetchall()
    applied_count = len(history)
    # The head digest also binds the history length: deleting a trailing
    # applied row cannot turn a newer database into a valid older prefix.
    head = sha256(json.dumps(history).encode("utf-8")).hexdigest()
    legacy = applied == (expected[0][2],) and not history
    if (
        history != expected[:applied_count]
        or (applied is None and history)
        or (applied is not None and not legacy and applied != (head,))
    ):
        raise Refusal(RefusalCode.STORE_SCHEMA_DRIFT)
    if applied_count == len(expected):
        return
    for version, name, digest in expected[applied_count:]:
        if (version, name) == (8, "0008_frozen_evidence"):
            # Historical v1 verification belongs only to this migration.
            from caos.store.extraction_integrity import _verify_extractions_v1

            _verify_extractions_v1(conn)
        _refuse_unmigratable_rows(conn, version, name, applied_count)
        if not (legacy and version == 1):
            conn.execute(MIGRATIONS[version - 1][1])
        conn.execute(
            "INSERT INTO store_migrations (version, name, digest) VALUES (%s, %s, %s)",
            (version, name, digest),
        )
    digest = sha256(json.dumps(expected).encode("utf-8")).hexdigest()
    conn.execute(
        "INSERT INTO store_schema (applied_digest) VALUES (%s)"
        " ON CONFLICT (only_row)"
        " DO UPDATE SET applied_digest = EXCLUDED.applied_digest",
        (digest,),
    )
