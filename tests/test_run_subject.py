"""The subject a run is about, and each attempt's ordinal, are pinned host facts
(Phase 3 Task 3.1b; brief corrections 3, 8 and 9)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from test_run_inputs import SUBJECT, Prepared, _prepare, pin_version_one

import caos.store as store
from caos.boundary_text import BoundaryText
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, apply_schema, connect
from caos.store.gates import Gate, gate_preview
from caos.store.run_inputs import (
    RunInput,
    RunSubject,
    _fingerprint,
    load_run_input,
    pin_run_input,
)
from caos.store.runs import attempt_ordinal, create_case, start_attempt

NODE = "RN-FULL_CREDIT_32-MARKET_DISLOCATION-01-CP-0"
# `_fingerprint` of this exact version-1 pin before version 2 existed.
V1 = RunInput(
    UUID(int=1),
    UUID(int=2),
    3,
    "a" * 64,
    "b" * 64,
    "c" * 64,
    "d" * 64,
    "claims-json-v1",
    '{"q":1}',
    "",
)
V1_FINGERPRINT = "6511bff76b8b606ea5cb364f0289cf5e1a376f03e3534b8068dfe1a5848c6cbb"
V1_INPUT_KEYS = {
    "run_id",
    "case_id",
    "source_version",
    "source_fingerprint",
    "route_digest",
    "build_id",
    "manifest_sha256",
    "adapter_version",
    "research_json",
    "input_fingerprint",
}


@pytest.fixture
def prepared(case: tuple[StoreConnection, UUID], tmp_path: Path) -> Prepared:
    conn, case_id = case
    return conn, *_prepare(conn, case_id, tmp_path)


def test_version_one_fingerprint_and_preview_bytes_are_unchanged(
    prepared: Prepared,
) -> None:
    assert _fingerprint(V1) == V1_FINGERPRINT
    conn, run, source, bundle, route = prepared
    # No new pin is version 1 (§42.1); one written before 0011 still previews.
    pin = pin_version_one(conn, run, source, bundle, route)
    assert (pin.subject, pin.cos_run_id) == (None, None)
    content = json.loads(gate_preview(conn, run, Gate.SOURCE_SET).content)
    assert content["format_version"] == 1 and set(content["input"]) == V1_INPUT_KEYS


def test_a_subject_is_pinned_with_a_utc_cos_run_id(prepared: Prepared) -> None:
    conn, run, source, bundle, _route = prepared
    conn.execute("SET TIME ZONE 'Pacific/Auckland'")
    pin = pin_run_input(conn, run, source.version, bundle, subject=SUBJECT)
    created = conn.execute(
        "SELECT created_at FROM runs WHERE run_id = %s", (run,)
    ).fetchone()
    assert created is not None
    stamp = created[0].astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    assert pin.cos_run_id == f"COS-{stamp}-{run.hex}"
    assert pin.subject == SUBJECT and load_run_input(conn, run) == pin
    stored = conn.execute(
        "SELECT format_version FROM run_inputs WHERE run_id = %s", (run,)
    ).fetchone()
    assert stored == (2,)
    content = json.loads(gate_preview(conn, run, Gate.SOURCE_SET).content)
    assert content["format_version"] == 2
    assert content["input"]["subject"]["issuer_id"] == "EXAMPLE"
    # A replay with another subject is another input.
    other = replace(SUBJECT, reporting_period="FY2024")
    with pytest.raises(Refusal) as refused:
        pin_run_input(conn, run, source.version, bundle, subject=other)
    assert refused.value.code is RefusalCode.RUN_INPUT_ALREADY_PINNED


@pytest.mark.parametrize(
    "field",
    ["issuer_id", "issuer_name", "reporting_period", "analysis_date", "cos_run_id"],
)
def test_every_subject_field_is_in_the_fingerprint(field: str) -> None:
    pinned = replace(V1, subject=SUBJECT, cos_run_id="COS-20260908T120000Z-" + "1" * 32)
    if field == "cos_run_id":
        moved = replace(pinned, cos_run_id="COS-20260908T120001Z-" + "1" * 32)
    else:
        moved = replace(pinned, subject=replace(SUBJECT, **{field: "CHANGED"}))
    assert _fingerprint(moved) != _fingerprint(pinned) != V1_FINGERPRINT


@pytest.mark.parametrize(
    "subject",
    [
        replace(SUBJECT, issuer_id="bad id"),
        replace(SUBJECT, issuer_id="-EXAMPLE"),
        replace(SUBJECT, issuer_id="12345\n"),
        replace(SUBJECT, issuer_name="Example\nplc"),
        replace(SUBJECT, issuer_name="Example\u2028plc"),
        replace(SUBJECT, issuer_name=""),
        replace(SUBJECT, reporting_period=" "),
        replace(SUBJECT, reporting_period="FY\u202e2025"),
        replace(SUBJECT, analysis_date="2026-02-30"),
        replace(SUBJECT, analysis_date="20260908"),
    ],
)
def test_an_invalid_subject_refuses_before_anything_is_pinned(
    prepared: Prepared, subject: RunSubject
) -> None:
    conn, run, source, bundle, _route = prepared
    with pytest.raises(Refusal) as refused:
        pin_run_input(conn, run, source.version, bundle, subject=subject)
    assert refused.value.code is RefusalCode.RUN_INPUT_INVALID
    assert load_run_input(conn, run) is None


def test_the_database_refuses_a_subject_that_disagrees_with_its_format(
    prepared: Prepared,
) -> None:
    conn, run, source, bundle, _route = prepared
    pin = pin_run_input(conn, run, source.version, bundle, subject=SUBJECT)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO run_inputs (run_id, case_id, source_version,"
            " source_fingerprint, route_digest, build_id, manifest_sha256,"
            " adapter_version,"
            " input_fingerprint, format_version, issuer_id)"
            " SELECT run_id, case_id, source_version, source_fingerprint,"
            " route_digest, build_id, manifest_sha256, adapter_version,"
            " input_fingerprint, 1, 'X'"
            " FROM run_inputs WHERE run_id = %s",
            (pin.run_id,),
        )
    conn.rollback()
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO run_inputs (run_id, case_id, source_version,"
            " source_fingerprint, route_digest, build_id, manifest_sha256,"
            " adapter_version, input_fingerprint, format_version)"
            " SELECT run_id, case_id, source_version, source_fingerprint,"
            " route_digest, build_id, manifest_sha256, adapter_version,"
            " input_fingerprint, 2 FROM run_inputs WHERE run_id = %s",
            (pin.run_id,),
        )
    conn.rollback()


def test_attempts_carry_a_bounded_ordinal_per_node(prepared: Prepared) -> None:
    conn, run, _source, _bundle, _route = prepared
    first = start_attempt(conn, run, NODE)
    second = start_attempt(conn, run, NODE)
    assert (attempt_ordinal(conn, first), attempt_ordinal(conn, second)) == (1, 2)
    conn.execute(
        "INSERT INTO run_attempts (attempt_id, run_id, route_node_id, ordinal)"
        " SELECT gen_random_uuid(), %s, %s, n FROM generate_series(3, 256) AS n",
        (run, NODE),
    )
    conn.commit()
    with pytest.raises(Refusal) as refused:
        start_attempt(conn, run, NODE)
    assert refused.value.code is RefusalCode.ATTEMPT_LIMIT_REACHED
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(
            "INSERT INTO run_attempts (attempt_id, run_id, route_node_id, ordinal)"
            " VALUES (gen_random_uuid(), %s, %s, 1)",
            (run, NODE),
        )
    conn.rollback()


def test_version_one_pins_and_early_attempts_survive_the_upgrade(
    empty_database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with connect(empty_database) as conn:
        with monkeypatch.context() as patch:
            patch.setattr(store, "MIGRATIONS", store.MIGRATIONS[:10])
            apply_schema(conn)
        case_id = create_case(conn, BoundaryText.of("before subjects"))
        run, sources, bundle, route = _prepare(conn, case_id, tmp_path)
        pin = pin_version_one(conn, run, sources, bundle, route)
        early = uuid4()
        conn.execute(
            "INSERT INTO run_attempts (attempt_id, run_id, route_node_id)"
            " VALUES (%s, %s, %s)",
            (early, run, NODE),
        )
        conn.commit()
        apply_schema(conn)
        assert load_run_input(conn, run) == pin
        stored = conn.execute(
            "SELECT format_version, issuer_id, issuer_name, reporting_period,"
            " analysis_date, cos_run_id FROM run_inputs WHERE run_id = %s",
            (run,),
        ).fetchone()
        assert stored == (1, None, None, None, None, None)
        with pytest.raises(Refusal) as refused:
            attempt_ordinal(conn, early)
        assert refused.value.code is RefusalCode.ATTEMPT_NOT_FOUND
        assert attempt_ordinal(conn, start_attempt(conn, run, NODE)) == 2
