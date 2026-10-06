"""D109: the run's pinned command -- module qualifiers, CP-0's objective and
CP-2G's forecast scope derived by the owner's rule -- pinned once in the run
input, fingerprinted, and delivered to the named node only."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from canonical_fixtures import BUNDLE, identity
from full_assessment_route_fixtures import MODULES, FullAssessmentCompletions
from test_canonical_digest import _record as _digest_record
from test_execution_freshness import _Harness
from test_full_credit_assessment_route import _modules, _run, harness, route
from test_handoff_invocation import _prompt
from test_qualifiers import _command
from test_run_inputs import SUBJECT, _prepare

from caos.digest import canonical_json
from caos.methodology.handoff import _decoded_record, record_bytes
from caos.methodology.qualifiers import DERIVED, PINNED, stated_command
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, run_inputs
from caos.store.run_inputs import RunCommand, load_run_input, pin_run_input

__all__ = ["harness", "route"]

FULL = ("FULL_CREDIT_32", "FULL_CREDIT_ASSESSMENT")
LIQUIDITY = ("FULL_CREDIT_32", "LIQUIDITY_REVIEW")


@pytest.fixture
def full(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> tuple[StoreConnection, UUID, int]:
    conn, case_id = case
    run, source, _bundle, _route = _prepare(conn, case_id, tmp_path, FULL)
    return conn, run, source.version


def test_a_full_route_pin_carries_the_derived_scope_as_version_3(
    full: tuple[StoreConnection, UUID, int],
) -> None:
    conn, run, version = full
    pin = pin_run_input(conn, run, version, BUNDLE, subject=SUBJECT)
    assert pin.format_version == 3 and pin.command is not None
    assert json.loads(str(pin.command.text)) == {
        "CP-2G": {
            "forecast_horizon": {"basis": DERIVED, "value": "FY2026-FY2028"},
            "base_period": {"basis": DERIVED, "value": "FY2025"},
        }
    }
    assert load_run_input(conn, run) == pin
    # A replay with a qualifier is another input.
    with pytest.raises(Refusal) as refused:
        pin_run_input(
            conn,
            run,
            version,
            BUNDLE,
            subject=SUBJECT,
            qualifiers={"CP-2G": {"cases": "base"}},
        )
    assert refused.value.code is RefusalCode.RUN_INPUT_ALREADY_PINNED


def test_the_fingerprint_moves_with_the_period_and_every_qualifier(
    full: tuple[StoreConnection, UUID, int],
) -> None:
    conn, run, version = full
    pin = pin_run_input(
        conn,
        run,
        version,
        BUNDLE,
        subject=SUBJECT,
        qualifiers={"CP-2G": {"cases": "base/upside/downside"}},
        objective="Refinancing decision",
    )
    fingerprints = {pin.input_fingerprint}
    for period, stated in (
        ("Q2 2026", {"CP-2G": {"cases": "base/upside/downside"}}),
        ("FY2025", {"CP-2G": {"cases": "base"}}),
        ("FY2025", {"CP-2G": {"cases": "base/upside/downside", "base_period": "Q2"}}),
        ("FY2025", {}),
    ):
        changed = replace(
            pin,
            subject=replace(SUBJECT, reporting_period=period),
            command=RunCommand(
                _command(stated_command(stated, "Refinancing decision"), period)
            ),
        )
        fingerprints.add(run_inputs._fingerprint(changed))
    fingerprints.add(run_inputs._fingerprint(replace(pin, command=RunCommand(None))))
    assert len(fingerprints) == 6


def test_the_pin_refuses_an_unknown_key_an_off_route_module_and_an_unread_period(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    conn, case_id = case
    run, source, _bundle, _route = _prepare(conn, case_id, tmp_path, FULL)
    lite, _, _, _ = _prepare(conn, case_id, tmp_path / "lite", LIQUIDITY)
    attempts = (
        (
            run,
            SUBJECT,
            {"CP-2G": {"horizon": "FY27"}},
            RefusalCode.RUN_QUALIFIER_INVALID,
        ),
        (
            lite,
            SUBJECT,
            {"CP-2G": {"cases": "base"}},
            RefusalCode.RUN_QUALIFIER_INVALID,
        ),
        (
            run,
            replace(SUBJECT, reporting_period="H1 2026"),
            None,
            RefusalCode.REPORTING_PERIOD_UNREADABLE,
        ),
    )
    for target, subject, qualifiers, code in attempts:
        with pytest.raises(Refusal) as refused:
            pin_run_input(
                conn,
                target,
                source.version,
                BUNDLE,
                subject=subject,
                qualifiers=qualifiers,
            )
        assert refused.value.code is code
    # A route without CP-2G derives nothing, whatever its period says.
    pin = pin_run_input(
        conn,
        lite,
        source.version,
        BUNDLE,
        subject=replace(SUBJECT, reporting_period="H1 2026"),
    )
    assert pin.command == RunCommand(None) and pin.format_version == 3


def test_a_version_2_row_loads_unchanged_and_a_forged_command_does_not(
    full: tuple[StoreConnection, UUID, int],
) -> None:
    conn, run, version = full
    pin = pin_run_input(conn, run, version, BUNDLE, subject=SUBJECT)
    conn.execute("ALTER TABLE run_inputs DISABLE TRIGGER input_immutable")
    two = replace(pin, command=None)
    two = replace(two, input_fingerprint=run_inputs._fingerprint(two))
    conn.execute(
        "UPDATE run_inputs SET format_version = 2, command_json = NULL,"
        " input_fingerprint = %s WHERE run_id = %s",
        (two.input_fingerprint, run),
    )
    assert load_run_input(conn, run) == two
    assert "command_json" not in run_inputs.input_fields(two)
    forged = replace(
        pin,
        command=RunCommand(
            str(pin.command.text if pin.command else "").replace(
                "FY2026-FY2028", "FY2026-FY2027"
            )
        ),
    )
    forged = replace(forged, input_fingerprint=run_inputs._fingerprint(forged))
    conn.execute(
        "UPDATE run_inputs SET format_version = 3, command_json = %s,"
        " input_fingerprint = %s WHERE run_id = %s",
        (
            forged.command.text if forged.command else None,
            forged.input_fingerprint,
            run,
        ),
    )
    with pytest.raises(Refusal) as refused:
        load_run_input(conn, run)
    assert refused.value.code is RefusalCode.RUN_INPUT_INVALID
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "UPDATE run_inputs SET format_version = 2 WHERE run_id = %s", (run,)
        )
    conn.rollback()


def test_only_cp2g_is_prompted_with_the_pinned_command(harness: _Harness) -> None:
    answers = FullAssessmentCompletions(harness.source_id)
    _run(harness, answers)
    assert _modules(answers) == list(MODULES)
    carrying = {
        module
        for module, prompt in zip(MODULES, answers.prompts, strict=True)
        if "--- CURRENT COMMAND" in prompt
    }
    assert carrying == {"CP-2G"}
    cp2g = answers.prompts[MODULES.index("CP-2G")]
    assert "Run CP-2G [forecast horizon: FY2026-FY2028] [base period: FY2025]\n" in cp2g


def test_cp0_is_prompted_with_a_stated_objective_inside_the_tag() -> None:
    names = {"objective": {"basis": PINNED, "value": "Refinancing decision"}}
    gate = replace(identity("CP-0"), current_command=canonical_json(names))
    prompt = _prompt(gate)
    plain = _prompt(identity("CP-0"))
    assert "--- CURRENT COMMAND" not in plain
    assert "Run CP-0 [objective: Refinancing decision]\n" in prompt
    tag = prompt.split("--- EVIDENCE ")[1][:16]
    assert f"--- CURRENT COMMAND {tag} (host-owned run control" in prompt
    assert f"--- END CURRENT COMMAND {tag} ---" in prompt
    for forged in ("[]", "{}", '{"cases":{"basis":"pinned","value":"x"}}', "{"):
        with pytest.raises(Refusal) as refused:
            _prompt(replace(gate, current_command=forged))
        assert refused.value.code is RefusalCode.HANDOFF_IDENTITY_MISMATCH


def test_a_record_carries_the_command_only_when_its_identity_does() -> None:
    record = _digest_record()
    names = {"cases": {"basis": PINNED, "value": "base"}}
    for current in (None, canonical_json(names)):
        carried = replace(
            record, identity=replace(record.identity, current_command=current)
        )
        data = record_bytes(carried)
        document = json.loads(data)
        assert ("current_command" in document["identity"]) is (current is not None)
        assert _decoded_record(data) == carried
    assert record_bytes(record) == record_bytes(_digest_record())
