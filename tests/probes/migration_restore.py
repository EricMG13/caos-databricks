"""Manual, synthetic pg_dump/restore proof; never collected by ordinary CI.

Run from the repository with .venv/bin/python tests/probes/migration_restore.py.
Only the pinned local test PostgreSQL is addressed, never the shared dev DB.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID, uuid4

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conftest import reserve_at as reserve
from qualification_fixtures import qualification_performed, record_runs
from test_frozen_evidence import _insert
from test_run_inputs import SUBJECT, _prepare, pin_version_one
from test_store_schema import _catalog, _columns, _legacy, _populate, _records

import caos.store as store
from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.read import read_block
from caos.graph.route import ResolvedRoute
from caos.qualification.store import (
    Evidence,
    current_verdict,
    record_performed,
    record_verdict,
)
from caos.qualification.verdict import read_verdict
from caos.refusals import Refusal, RefusalCode
from caos.store import MIGRATIONS, StoreConnection, apply_schema, connect
from caos.store.budget import remaining
from caos.store.extraction_integrity import _verify_extractions_v1
from caos.store.gates import Gate, GateApproval, approve_gate, gate_preview
from caos.store.members import Standing, grant
from caos.store.run_inputs import load_run_input, pin_run_input
from caos.store.runs import (
    Accepted,
    accept_attempt,
    attempt_ordinal,
    create_case,
    start_attempt,
)

_ADMIN = "postgresql://postgres:local-test-admin-only@127.0.0.1:55437/postgres"
_CONTAINER = "caos-workbench-dev-test-postgres-1"


def _check_frozen(conn: StoreConnection, source: UUID | None) -> None:
    before = _records(conn)
    _verify_extractions_v1(conn)
    conn.commit()
    for table in ("source_blocks", "source_tokens"):
        for mutation in (
            f"UPDATE {table} SET text = text",
            f"DELETE FROM {table}",
            f"TRUNCATE {table}",
        ):
            with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
                with conn.transaction():
                    conn.execute(mutation)
        if source is not None:
            with pytest.raises(psycopg.errors.CheckViolation, match="sealed"):
                with conn.transaction():
                    _insert(conn, table, source)
    assert _records(conn) == before


_LITE = ("LITE_CREDIT_22", "LITE_EARNINGS_UPDATE")


def _approve(
    conn: StoreConnection, case_id: UUID, run: UUID, route: ResolvedRoute
) -> str:
    """Acceptance requires every gate's current approval (Task17d3a); returns
    the route's first node."""
    approver = uuid4()
    grant(conn, case_id=case_id, user_id=approver, standing=Standing.APPROVER)
    conn.commit()
    for gate in Gate:
        preview = gate_preview(conn, run, gate)
        approve_gate(
            conn,
            GateApproval(
                run_id=run,
                gate=gate,
                actor_id=approver,
                preview_sha256=preview.preview_sha256,
                input_fingerprint=preview.input_fingerprint,
            ),
        )
    return route.nodes[0].route_node_id


def _check_early_attempt(
    conn: StoreConnection, run: UUID, attempt: UUID, route: ResolvedRoute
) -> None:
    """A version-1 pin and a pre-ordinal attempt, after upgrading past 0011."""
    assert conn.execute(
        "SELECT format_version, cos_run_id FROM run_inputs"
    ).fetchall() == [(1, None)]
    with pytest.raises(Refusal) as refused:
        attempt_ordinal(conn, attempt)
    assert refused.value.code is RefusalCode.ATTEMPT_NOT_FOUND
    node = route.nodes[0].route_node_id
    assert attempt_ordinal(conn, start_attempt(conn, run, node)) == 2


def _backup_schema(conn: StoreConnection, prefix_seven: bool) -> None:
    with patch.object(
        store, "MIGRATIONS", MIGRATIONS[:7] if prefix_seven else MIGRATIONS
    ):
        apply_schema(conn)


def _record_qualification(conn: StoreConnection) -> tuple[Evidence, datetime]:
    """A current, exact verdict that the restored application must still read."""
    now = datetime(2026, 9, 15, tzinfo=UTC)
    performed = qualification_performed()
    evidence = performed.evidence
    record_performed(conn, performed)
    record_runs(conn, performed)
    verdict = read_verdict(
        {
            "provider": evidence.provider + ":" + evidence.model,
            "qualification_set_sha256": evidence.qualification_set_sha256,
            "build_id": evidence.build_id,
            "decided_at": now.isoformat(),
            "expires_at": (now + timedelta(days=1)).isoformat(),
            "reviewer": "restore reviewer",
        },
        now=now,
    )
    record_verdict(conn, evidence=evidence, reviewer_id=uuid4(), verdict=verdict)
    return evidence, now


def main(  # noqa: C901, PLR0915 -- the three restore scenarios share one proof
    *, migrated: bool = False, prefix_seven: bool = False
) -> None:
    docker = shutil.which("docker")
    assert docker is not None, "Docker CLI required for this manual proof"
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "OPENROUTER_API_KEY",
            "MODEL",
            "BASE_URL",
            "CAOS_REQUIRE_PROVIDER",
        }
    }
    created: list[str] = []
    original, restored = (f"caos_restore_{uuid4().hex}" for _ in range(2))
    qualification: tuple[Evidence, datetime] | None = None
    with psycopg.connect(_ADMIN, autocommit=True) as admin, TemporaryDirectory() as tmp:
        try:
            admin.execute(
                psycopg.sql.SQL("CREATE DATABASE {}").format(
                    psycopg.sql.Identifier(original)
                )
            )
            created.append(original)
            blobs = BlobStore(Path(tmp) / "original_blobs")
            with connect(_ADMIN.rsplit("/", 1)[0] + "/" + original) as conn:
                _legacy(conn)
                digest = _populate(conn, blobs)
                if migrated:
                    _backup_schema(conn, prefix_seven)
                    case_id = create_case(
                        conn, BoundaryText.of("complete input restore")
                    )
                    # Acceptance needs a route the adapter executes (§42.2);
                    # a prefix-7 pin is data only, on the default route.
                    run, sources, bundle, route = _prepare(
                        conn,
                        case_id,
                        blobs.root,
                        *([] if prefix_seven else [_LITE]),
                    )
                    if prefix_seven:
                        # Today's pin and attempt writers need columns a prefix-7
                        # schema lacks: both are written as that code wrote them.
                        pin = pin_version_one(conn, run, sources, bundle, route)
                        attempt = uuid4()
                        conn.execute(
                            "INSERT INTO run_attempts"
                            " (attempt_id, run_id, route_node_id) VALUES (%s, %s, %s)",
                            (attempt, run, route.nodes[0].route_node_id),
                        )
                        conn.commit()
                        # This backup predates `run_work`: write the historical
                        # reservation row instead of calling today's lease-aware API.
                        conn.execute(
                            "INSERT INTO budget_reservations "
                            "(attempt_id, run_id, amount) VALUES (%s, %s, %s)",
                            (attempt, run, Decimal("0.25")),
                        )
                        conn.commit()
                    else:
                        pin = pin_run_input(
                            conn,
                            run,
                            sources.version,
                            bundle,
                            {"q": "Café?"},
                            subject=SUBJECT,
                        )
                        attempt = start_attempt(
                            conn, run, _approve(conn, case_id, run, route)
                        )
                        reserve(conn, attempt, Decimal("0.25"))
                        accept_attempt(
                            conn,
                            attempt_id=attempt,
                            accepted=Accepted(
                                digest,
                                Decimal("0.75"),
                                "synthetic",
                                "restore",
                                record_sha256=blobs.put(b"restore record"),
                            ),
                        )
                    if not prefix_seven:
                        qualification = _record_qualification(conn)
                columns = _columns(conn)
                before = _records(conn, columns)
                catalog = _catalog(conn)
            dump = subprocess.run(  # nosec B603
                [
                    docker,
                    "exec",
                    _CONTAINER,
                    "pg_dump",
                    "-U",
                    "postgres",
                    "--format=custom",
                    "--no-owner",
                    "--no-acl",
                    original,
                ],
                check=True,
                capture_output=True,
                env=env,
            ).stdout
            shutil.copytree(blobs.root, Path(tmp) / "restored_blobs")
            admin.execute(
                psycopg.sql.SQL("CREATE DATABASE {}").format(
                    psycopg.sql.Identifier(restored)
                )
            )
            created.append(restored)
            subprocess.run(  # nosec B603
                [
                    docker,
                    "exec",
                    "-i",
                    _CONTAINER,
                    "pg_restore",
                    "-U",
                    "postgres",
                    "--exit-on-error",
                    "--single-transaction",
                    "--no-owner",
                    "--no-acl",
                    "--dbname",
                    restored,
                ],
                input=dump,
                check=True,
                env=env,
            )
            with connect(_ADMIN.rsplit("/", 1)[0] + "/" + restored) as conn:
                assert _records(conn, columns) == before
                assert _catalog(conn) == catalog
                apply_schema(conn)
                assert _records(conn, columns) == before
                assert conn.execute(
                    "SELECT version FROM store_migrations ORDER BY version"
                ).fetchall() == [(i,) for i in range(1, len(MIGRATIONS) + 1)]
                assert conn.execute(
                    "SELECT count(*) FROM source_extractions"
                ).fetchone() == (1 if migrated else 0,)
                assert conn.execute(
                    "SELECT count(*) FROM call_outcomes"
                ).fetchone() == (1 if migrated and not prefix_seven else 0,)
                if migrated:
                    assert load_run_input(conn, run) == pin
                    spent = Decimal("4.75") if prefix_seven else Decimal("4.25")
                    assert remaining(conn, run) == spent
                    if not prefix_seven:
                        assert qualification is not None
                        evidence, now = qualification
                        assert (
                            current_verdict(
                                conn, evidence=evidence, now=now
                            ).reviewer.value
                            == "restore reviewer"
                        )
                if prefix_seven:
                    _check_early_attempt(conn, run, attempt, route)
                _check_frozen(conn, sources.members[0].source_id if migrated else None)
                for (source,) in conn.execute(
                    "SELECT source_id FROM sources"
                ).fetchall():
                    assert read_block(
                        conn, source_id=source, block_id="b000000"
                    ).text.value in {"synthetic", "one"}
                for table, column in (
                    ("sources", "document_sha256"),
                    ("artifacts", "artifact_sha256"),
                ):
                    rows = conn.execute(
                        psycopg.sql.SQL("SELECT {} FROM {}").format(
                            psycopg.sql.Identifier(column),
                            psycopg.sql.Identifier(table),
                        )
                    )
                    for (stored_digest,) in rows:
                        restored_bytes = BlobStore(Path(tmp) / "restored_blobs").get(
                            stored_digest
                        )
                        assert restored_bytes == blobs.get(stored_digest)
            print(
                f"PASS dump={len(dump)} bytes; {original} -> {restored};"
                f" version={len(MIGRATIONS)}; rows/blobs intact;"
                f" migrated_backup={migrated}; prefix_seven={prefix_seven};"
                " legacy provenance UNKNOWN; known v1 verified; native guards refuse"
            )
        finally:
            for name in reversed(created):
                admin.execute(
                    psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                        psycopg.sql.Identifier(name)
                    )
                )
                print(f"Removed owned disposable database: {name}")


if __name__ == "__main__":
    main()
    main(migrated=True)
    main(migrated=True, prefix_seven=True)
