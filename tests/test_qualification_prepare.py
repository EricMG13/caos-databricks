"""Preparation pins inputs without granting approval or executing any run."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import asdict, replace
from decimal import ROUND_DOWN, Decimal, localcontext
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import psycopg
import pytest
from canonical_fixtures import LITE_PROFILE, LITE_SELECTION
from conftest import priced
from test_pdf_extraction import minimal_pdf
from test_qualification_harness import (
    CATALOG,
    ESTIMATE,
    OTHER,
    REPORT,
    SET_CEILING,
    VENDORED,
    _approve,
    _case,
    _Completions,
    _count,
)

from caos import methodology
from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.graph.route import RouteExtensions, resolve_route
from caos.methodology.bundle import Bundle
from caos.qualification import harness as subject
from caos.qualification.matrix import (
    ExpectedForecast,
    ExpectedProjection,
    ExpectedRegister,
    ForecastValue,
    QualificationCase,
    QualificationSet,
)
from caos.refusals import Refusal
from caos.store import RunStatus, StoreConnection, apply_schema, connect, run_inputs
from caos.store.budget import CEILING
from caos.store.gates import Gate, GateState, gate_preview, gate_state
from caos.store.routes import resolved_route
from caos.store.run_inputs import load_run_input
from caos.store.runs import create_case
from caos.store.source_sets import load_source_set

Fixture = tuple[StoreConnection, BlobStore, subject.Harness, QualificationSet]


@pytest.fixture
def ready(empty_database: str, tmp_path: Path) -> Iterator[Fixture]:
    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()
        yield (
            conn,
            BlobStore(tmp_path / "blobs"),
            subject.Harness(
                Bundle(VENDORED), CATALOG, _Completions(), priced(ESTIMATE), SET_CEILING
            ),
            QualificationSet((_case("first", REPORT), _case("second", OTHER))),
        )


def _unapproved_and_unspent(conn: StoreConnection, harness: subject.Harness) -> None:
    for table in (
        "case_members",
        "run_gates",
        "audit_events",
        "run_attempts",
        "budget_reservations",
        "call_outcomes",
        "budget_ledger",
        "artifacts",
    ):
        assert _count(conn, "SELECT count(*) FROM " + table) == 0, table
    assert cast(_Completions, harness.completions).prompts == []
    conn.rollback()


@pytest.mark.parametrize("precision", [28, 1])
def test_aggregate_ceiling_is_exact_under_decimal_context(precision: int) -> None:
    qualification = QualificationSet(tuple(_case(str(i), REPORT) for i in range(3)))
    harness = subject.Harness(
        Bundle(VENDORED), CATALOG, _Completions(), priced(ESTIMATE), Decimal("10")
    )
    with localcontext() as context:
        context.prec, context.rounding = precision, ROUND_DOWN
        with pytest.raises(Refusal, match=r"^QUALIFICATION_SET_OVER_CEILING$"):
            subject._affordable(qualification, harness, ())
        subject._affordable(qualification, replace(harness, ceiling=Decimal("15")), ())


def test_a_price_whose_route_cannot_fit_a_run_is_refused_before_any_case(
    ready: Fixture,
) -> None:
    """A run whose ceiling cannot cover one worst-case call is refused before any
    case, which is the run's own admission check (`runtime._affordable`) made
    before preparation. The floor is one call, not one per node (§91): since
    Task 8.2 a node reserves its own priced request, and `reserve` refuses the
    next one past the ceiling under the run lock, so the ceiling -- not this
    floor -- is what bounds the spend."""
    conn, blobs, harness, qualification = ready
    over = replace(harness, price=priced(CEILING + Decimal("0.01")))
    route = resolve_route(CATALOG, LITE_PROFILE, LITE_SELECTION)
    # Exact whatever the ambient precision (the whole-phase audit's W-1).
    with localcontext() as context:
        context.prec = 1
        with pytest.raises(Refusal, match=r"^QUALIFICATION_SET_OVER_CEILING$"):
            subject._affordable(qualification, over, [route])
    with pytest.raises(Refusal, match=r"^QUALIFICATION_SET_OVER_CEILING$"):
        subject.prepare(conn, blobs, over, qualification=qualification)
    assert _count(conn, "SELECT count(*) FROM cases") == 0
    _unapproved_and_unspent(conn, over)


def test_a_route_whose_nodes_together_exceed_the_ceiling_at_worst_is_admitted(
    ready: Fixture,
) -> None:
    """Three nodes each priced a third of the ceiling and a cent at worst: the old
    floor refused this, though no node reserves a worst case any more (§91)."""
    _conn, _blobs, harness, qualification = ready
    third = replace(harness, price=priced(CEILING / 3 + Decimal("0.01")))
    route = resolve_route(CATALOG, LITE_PROFILE, LITE_SELECTION)
    assert len(route.nodes) >= 3
    subject._affordable(qualification, third, [route])


def test_preparation_uses_an_explicit_run_ceiling(ready: Fixture) -> None:
    """An authorized live route may need more than the default per-run cap."""
    conn, blobs, harness, qualification = ready
    route = resolve_route(CATALOG, LITE_PROFILE, LITE_SELECTION)
    # Three conservative reservations total more than the default five-dollar
    # cap but less than the explicit authorized ceiling.
    price = priced(Decimal("1.90"))
    authorized = replace(
        harness,
        price=price,
        ceiling=Decimal("22.00"),
        run_ceiling=Decimal("22.00"),
    )

    prepared = subject.prepare(
        conn,
        blobs,
        authorized,
        qualification=QualificationSet((qualification.cases[0],)),
    )

    assert len(route.nodes) == 3
    assert conn.execute(
        "SELECT budget_ceiling FROM runs WHERE run_id=%s", (prepared[0].input.run_id,)
    ).fetchone() == (Decimal("22.00"),)

    _approve(conn, prepared)
    performed = subject.perform(
        conn,
        blobs,
        authorized,
        qualification=QualificationSet((qualification.cases[0],)),
        prepared=prepared,
    )

    assert performed.performed[0].status is RunStatus.COMPLETE


@pytest.mark.parametrize(
    "row_key",
    [(), (("resolution_status", "UNRESOLVED"),)],
)
def test_perform_refuses_an_impossible_register_selector_before_spend(
    ready: Fixture, row_key: tuple[tuple[str, str], ...]
) -> None:
    conn, blobs, harness, qualification = ready
    prepared = subject.prepare(conn, blobs, harness, qualification=qualification)
    _approve(conn, prepared)
    first, second = qualification.cases
    impossible = replace(
        first,
        expects_register=(
            ExpectedRegister(
                module_id="CP-DR",
                register_id="TDR.3",
                row_key=row_key,
                column="resolution_status",
                expected="ANSWERED",
            ),
        ),
    )

    with pytest.raises(Refusal, match=r"^QUALIFICATION_KEY_UNANSWERABLE$"):
        subject.perform(
            conn,
            blobs,
            harness,
            qualification=QualificationSet((impossible, second)),
            prepared=prepared,
        )

    assert cast(_Completions, harness.completions).prompts == []
    assert _count(conn, "SELECT count(*) FROM budget_reservations") == 0
    assert _count(conn, "SELECT count(*) FROM call_outcomes") == 0


@pytest.mark.parametrize(
    "ceiling",
    [
        10,
        True,
        "10",
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        Decimal("-1"),
    ],
)
def test_invalid_ceiling_refuses_before_preparation(
    ready: Fixture, ceiling: object
) -> None:
    conn, blobs, harness, qualification = ready
    code = "MONEY_INVALID" if isinstance(ceiling, Decimal) else "MONEY_NOT_DECIMAL"
    with pytest.raises(Refusal, match=f"^{code}$"):
        subject.prepare(
            conn,
            blobs,
            replace(harness, ceiling=cast(Decimal, ceiling)),
            qualification=qualification,
        )
    assert conn.info.transaction_status.name == "IDLE"
    assert _count(conn, "SELECT count(*) FROM cases") == 0
    _unapproved_and_unspent(conn, harness)


def test_preparation_creates_exact_inputs_and_external_previews(ready: Fixture) -> None:
    conn, blobs, harness, qualification = ready
    prepared = subject.prepare(conn, blobs, harness, qualification=qualification)
    assert conn.info.transaction_status.name == "IDLE"
    assert isinstance(prepared, tuple) and len(prepared) == 2
    assert len({item.input.case_id for item in prepared}) == 2
    assert len({item.input.run_id for item in prepared}) == 2
    for item, case in zip(prepared, qualification.cases, strict=True):
        assert isinstance(item, subject.PreparedCase)
        pin = item.input
        assert item.case_label == case.label
        assert pin == load_run_input(conn, pin.run_id)
        assert pin.research_json is None and pin.source_version == 1
        assert conn.execute(
            "SELECT c.title, r.budget_ceiling, r.status FROM runs r"
            " JOIN cases c USING(case_id) WHERE r.run_id=%s AND c.case_id=%s",
            (pin.run_id, pin.case_id),
        ).fetchone() == (case.label, CEILING, "RUNNING")
        source = load_source_set(conn, pin.case_id, pin.source_version)
        assert source is not None and source.fingerprint == pin.source_fingerprint
        assert sorted(
            (m.filename, m.document_sha256) for m in source.members
        ) == sorted(
            (d.filename.value, sha256(d.data).hexdigest()) for d in case.documents
        )
        route = resolved_route(conn, pin.run_id)
        assert route == resolve_route(CATALOG, case.profile_id, case.selection_id)
        assert route is not None
        for gate in Gate:
            preview = gate_preview(conn, pin.run_id, gate)
            expected: dict[str, object] = {
                "format_version": pin.format_version,
                "gate": gate.value,
                "input": {
                    **run_inputs.input_fields(pin),
                    "run_id": str(pin.run_id),
                    "case_id": str(pin.case_id),
                },
            }
            if gate is Gate.SOURCE_SET:
                expected["sources"] = [
                    {**asdict(m), "source_id": str(m.source_id)} for m in source.members
                ]
            else:
                expected["route"] = asdict(route)
            assert preview.content == json.dumps(
                expected, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2
            )
            assert (
                preview.preview_sha256 == sha256(preview.content.encode()).hexdigest()
            )
            assert preview.input_fingerprint == pin.input_fingerprint
            assert gate_state(conn, pin.run_id, gate) is GateState.OPEN
        assert blobs.get(source.members[0].document_sha256) == case.documents[0].data
    _unapproved_and_unspent(conn, harness)


@pytest.mark.parametrize(
    "fault,code",
    [
        ("empty", "QUALIFICATION_SET_EMPTY"),
        ("documents", "QUALIFICATION_SET_EMPTY"),
        ("expects", "QUALIFICATION_SET_EMPTY"),
        ("duplicate", "QUALIFICATION_SET_AMBIGUOUS"),
        ("duplicate-key", "QUALIFICATION_SET_AMBIGUOUS"),
        ("unanswerable", "QUALIFICATION_KEY_UNANSWERABLE"),
        ("unlocatable-register", "QUALIFICATION_KEY_UNANSWERABLE"),
        ("empty-register-selector", "QUALIFICATION_KEY_UNANSWERABLE"),
        ("conflicting-register-selector", "QUALIFICATION_KEY_UNANSWERABLE"),
        ("ready-and-blocked", "QUALIFICATION_SET_AMBIGUOUS"),
        ("blocked-off-route", "QUALIFICATION_KEY_UNANSWERABLE"),
        ("blocked-gate", "QUALIFICATION_KEY_UNANSWERABLE"),
        ("ready-off-route", "QUALIFICATION_KEY_UNANSWERABLE"),
        ("ready-model-extension", "QUALIFICATION_KEY_UNANSWERABLE"),
        ("blocked-model-extension", "QUALIFICATION_KEY_UNANSWERABLE"),
        ("forecast-readiness-extra", "QUALIFICATION_KEY_UNANSWERABLE"),
        ("forecast-readiness-missing", "QUALIFICATION_KEY_UNANSWERABLE"),
        ("forecast-readiness-duplicate", "QUALIFICATION_KEY_UNANSWERABLE"),
        ("citation-off-route", "QUALIFICATION_KEY_UNANSWERABLE"),
        ("projection-off-route", "QUALIFICATION_KEY_UNANSWERABLE"),
        ("register-off-route", "QUALIFICATION_KEY_UNANSWERABLE"),
        ("route", "ROUTE_SELECTION_UNKNOWN"),
        ("label", "BOUNDARY_TEXT_TOO_LONG"),
        ("control", "BOUNDARY_TEXT_INVALID"),
        ("ceiling", "QUALIFICATION_SET_OVER_CEILING"),
        ("bundle", "RUN_INPUT_INVALID"),
    ],
)
def test_whole_set_pure_defects_leave_no_setup(
    ready: Fixture, fault: str, code: str
) -> None:
    conn, blobs, harness, qualification = ready
    first, second = qualification.cases
    forecast_route = resolve_route(
        CATALOG,
        "FULL_CREDIT_32",
        "RELATIVE_VALUE",
        extensions=RouteExtensions(model_extension=True),
    )
    forecast = ExpectedForecast(
        scenario="BASE",
        period_id="FY2026",
        values=(ForecastValue("cash.closing", "0"),),
        currency="USD",
        scale="millions",
        perimeter="Consolidated",
        qa_status="Passed",
        limitation_flags=(),
        readiness=tuple(
            sorted(
                (node.module_id, "READY")
                for node in forecast_route.nodes
                if node.module_id not in {"CP-0", "CP-CF"}
            )
        ),
    )
    forecast_case = replace(
        second,
        profile_id="FULL_CREDIT_32",
        selection_id="RELATIVE_VALUE",
        model_extension=True,
        forecast=forecast,
    )
    register = ExpectedRegister(
        module_id="CP-DR",
        register_id="TDR.3",
        row_key=(("question_id", "RQ-x"),),
        column="resolution_status",
        expected="ANSWERED",
    )
    changes = {
        "documents": replace(second, documents=()),
        "expects": replace(second, expects=()),
        "duplicate": replace(second, label=first.label),
        "duplicate-key": replace(second, expects=second.expects * 2),
        "unanswerable": replace(second, expects=first.expects),
        "unlocatable-register": replace(
            second,
            expects_register=(replace(register, register_id="NO_SUCH_REGISTER"),),
        ),
        "empty-register-selector": replace(
            second,
            expects_register=(replace(register, row_key=()),),
        ),
        "conflicting-register-selector": replace(
            second,
            expects_register=(
                replace(
                    register,
                    row_key=(("resolution_status", "UNRESOLVED"),),
                ),
            ),
        ),
        # §99: a readiness key names a consumer CP-0 rules on for this route,
        # and no module in both lists.
        "ready-and-blocked": replace(
            second, expects_ready=("CP-L10",), expects_blocked=("CP-L10",)
        ),
        "blocked-off-route": replace(second, expects_blocked=("CP-9",)),
        "blocked-gate": replace(second, expects_blocked=("CP-0",)),
        "ready-off-route": replace(second, expects_ready=("CP-9",)),
        "ready-model-extension": replace(
            second,
            profile_id="FULL_CREDIT_32",
            selection_id="RELATIVE_VALUE",
            model_extension=True,
            expects_ready=("CP-CF",),
        ),
        "blocked-model-extension": replace(
            second,
            profile_id="FULL_CREDIT_32",
            selection_id="RELATIVE_VALUE",
            model_extension=True,
            expects_blocked=("CP-CF",),
        ),
        "forecast-readiness-extra": replace(
            forecast_case,
            forecast=replace(
                forecast, readiness=(*forecast.readiness, ("CP-CF", "READY"))
            ),
        ),
        "forecast-readiness-missing": replace(
            forecast_case,
            forecast=replace(forecast, readiness=forecast.readiness[1:]),
        ),
        "forecast-readiness-duplicate": replace(
            forecast_case,
            forecast=replace(
                forecast, readiness=(*forecast.readiness, *forecast.readiness[:1])
            ),
        ),
        "citation-off-route": replace(
            second, expects=(replace(second.expects[0], module_id="CP-DR"),)
        ),
        "projection-off-route": replace(
            second,
            expects_projection=(
                ExpectedProjection("CP-DR", "decision_scope", "Invest"),
            ),
        ),
        "register-off-route": replace(second, expects_register=(register,)),
        "route": replace(second, selection_id="NO_SUCH_PATHWAY"),
        "label": replace(second, label="x" * 129),
        "control": replace(second, label="bad\x00label"),
    }
    qualification = QualificationSet(
        () if fault == "empty" else (first, changes.get(fault, second))
    )
    if fault == "ceiling":
        harness = replace(harness, ceiling=CEILING)
    elif fault == "bundle":
        harness = replace(
            harness,
            bundle=cast(
                Bundle,
                SimpleNamespace(
                    build_id=harness.bundle.build_id,
                    manifest_sha256=harness.bundle.manifest_sha256,
                ),
            ),
        )
    with pytest.raises(Refusal, match=f"^{code}$"):
        subject.prepare(conn, blobs, harness, qualification=qualification)
    assert conn.info.transaction_status.name == "IDLE"
    assert _count(conn, "SELECT count(*) FROM cases") == 0
    assert not blobs.root.exists()
    _unapproved_and_unspent(conn, harness)


@pytest.mark.parametrize(
    "mode", ["pending", "autocommit", "repeatable", "serializable"]
)
def test_preparation_requires_idle_read_committed_entry(
    ready: Fixture,
    empty_database: str,
    mode: str,
) -> None:
    conn, blobs, harness, qualification = ready
    if mode == "pending":
        pending = create_case(conn, BoundaryText.of("caller work"))
    elif mode == "autocommit":
        conn.autocommit = True
    else:
        conn.isolation_level = (
            psycopg.IsolationLevel.REPEATABLE_READ
            if mode == "repeatable"
            else psycopg.IsolationLevel.SERIALIZABLE
        )
    with pytest.raises(Refusal, match=r"^STORE_NOT_TRANSACTIONAL$"):
        subject.prepare(conn, blobs, harness, qualification=qualification)
    if mode == "pending":
        assert conn.info.transaction_status.name == "INTRANS"
        assert conn.execute(
            "SELECT title FROM cases WHERE case_id=%s", (pending,)
        ).fetchone() == ("caller work",)
        with connect(empty_database) as observer:
            assert (
                observer.execute(
                    "SELECT 1 FROM cases WHERE case_id=%s", (pending,)
                ).fetchone()
                is None
            )
    else:
        assert conn.info.transaction_status.name == "IDLE"
    conn.rollback()
    conn.autocommit = False
    assert _count(conn, "SELECT count(*) FROM cases") == 0
    _unapproved_and_unspent(conn, harness)


@pytest.mark.parametrize("stage", ["extraction", "setup", "snapshot", "route", "input"])
def test_later_preparation_failure_keeps_prior_commits(
    ready: Fixture,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    conn, blobs, harness, qualification = ready
    first, second = qualification.cases
    if stage == "extraction":
        qualification = QualificationSet((first, _case(second.label, b" \n\t")))
    prefix = {
        "setup": "INSERT INTO runs",
        "snapshot": "INSERT INTO source_set_versions",
        "route": "INSERT INTO run_routes",
        "input": "INSERT INTO run_inputs",
    }.get(stage)
    execute = psycopg.Connection.execute
    calls = 0

    def fail_second(
        c: StoreConnection, query: str, *args: object, **kwargs: object
    ) -> object:
        nonlocal calls
        if prefix is not None and query.startswith(prefix):
            calls += 1
            if calls == 2:
                return execute(c, "SELECT missing_qualification_column")
        return execute(c, query, *args, **kwargs)  # type: ignore[arg-type]

    with monkeypatch.context() as patch:
        patch.setattr(psycopg.Connection, "execute", fail_second)
        code = "SOURCE_HAS_NO_TEXT" if stage == "extraction" else "STORE_UNAVAILABLE"
        with pytest.raises(Refusal, match=f"^{code}$") as caught:
            subject.prepare(conn, blobs, harness, qualification=qualification)
    assert caught.value.__cause__ is None
    assert conn.info.transaction_status.name == "IDLE"
    prior = conn.execute(
        "SELECT r.run_id FROM runs r JOIN cases c USING(case_id) WHERE c.title=%s",
        (first.label,),
    ).fetchone()
    assert prior is not None and load_run_input(conn, prior[0]) is not None
    assert blobs.get(sha256(REPORT).hexdigest()) == REPORT
    committed_setup = 1 if stage in {"extraction", "setup"} else 2
    assert _count(conn, "SELECT count(*) FROM cases") == committed_setup
    assert _count(conn, "SELECT count(*) FROM runs") == committed_setup
    assert _count(conn, "SELECT count(*) FROM source_set_versions") == (
        2 if stage in {"route", "input"} else 1
    )
    assert _count(conn, "SELECT count(*) FROM run_routes") == (
        2 if stage == "input" else 1
    )
    assert _count(conn, "SELECT count(*) FROM run_inputs") == 1
    if stage != "extraction":
        assert blobs.get(sha256(OTHER).hexdigest()) == OTHER
    _unapproved_and_unspent(conn, harness)


LITE_SUBJECT = run_inputs.RunSubject(
    issuer_id="BOREALIS",
    issuer_name="Borealis Industries plc",
    reporting_period="FY2026",
    analysis_date="2026-09-13",
)


def _disabled(case: QualificationCase) -> QualificationCase:
    """The case on a route the adapter does not execute: it still prepares (§42.2)."""
    return replace(case, profile_id="FULL_CREDIT_32", selection_id="MARKET_DISLOCATION")


def _lite(case: QualificationCase, subject_: object) -> QualificationCase:
    return replace(
        case,
        profile_id=LITE_PROFILE,
        selection_id=LITE_SELECTION,
        subject=cast(run_inputs.RunSubject, subject_),
    )


def test_a_canonical_case_pins_its_declared_subject(ready: Fixture) -> None:
    conn, blobs, harness, qualification = ready
    first, second = qualification.cases
    mixed = QualificationSet((_disabled(first), _lite(second, LITE_SUBJECT)))

    disabled, canonical = subject.prepare(conn, blobs, harness, qualification=mixed)

    assert disabled.input.format_version == 2
    assert disabled.input.subject == first.subject
    assert disabled.input.adapter_version == methodology.CANONICAL_ADAPTER_VERSION
    assert canonical.input.format_version == 2
    assert canonical.input.subject == LITE_SUBJECT
    assert canonical.input.adapter_version == methodology.CANONICAL_ADAPTER_VERSION
    assert canonical.input == load_run_input(conn, canonical.input.run_id)
    assert conn.execute(
        "SELECT issuer_id, issuer_name, reporting_period, analysis_date,"
        " format_version FROM run_inputs WHERE run_id=%s",
        (canonical.input.run_id,),
    ).fetchone() == (*asdict(LITE_SUBJECT).values(), 2)
    _unapproved_and_unspent(conn, harness)


@pytest.mark.parametrize(
    "declared",
    [
        None,
        asdict(LITE_SUBJECT),
        replace(LITE_SUBJECT, analysis_date="13/09/2026"),
        replace(LITE_SUBJECT, issuer_id="not a key"),
        replace(LITE_SUBJECT, issuer_name=" padded"),
    ],
)
def test_a_canonical_case_without_a_valid_subject_leaves_no_setup(
    ready: Fixture, declared: object
) -> None:
    """Refused whole-set, before the case ahead of it is written."""
    conn, blobs, harness, qualification = ready
    first, second = qualification.cases
    assert not run_inputs.valid_subject(declared)
    with pytest.raises(Refusal, match=r"^RUN_INPUT_INVALID$"):
        subject.prepare(
            conn,
            blobs,
            harness,
            qualification=QualificationSet((first, _lite(second, declared))),
        )
    assert conn.info.transaction_status.name == "IDLE"
    assert _count(conn, "SELECT count(*) FROM cases") == 0
    assert not blobs.root.exists()
    _unapproved_and_unspent(conn, harness)


def test_a_case_on_any_route_without_a_subject_leaves_no_setup(
    ready: Fixture,
) -> None:
    conn, blobs, harness, qualification = ready
    first, second = qualification.cases
    declared = replace(_disabled(second), subject=None)
    with pytest.raises(Refusal, match=r"^RUN_INPUT_INVALID$"):
        subject.prepare(
            conn, blobs, harness, qualification=QualificationSet((first, declared))
        )
    assert _count(conn, "SELECT count(*) FROM cases") == 0
    _unapproved_and_unspent(conn, harness)


def test_the_harness_admits_pdfs_through_the_pdf_extractor(ready: Fixture) -> None:
    """The harness passes no extractor; before per-document dispatch a PDF case
    was read as UTF-8 text and refused, or tokenised as PDF syntax."""
    conn, blobs, harness, _ = ready
    line = "Total debt at 31 December 2026 was USD 1,240.0m"
    pdf = minimal_pdf([line])
    # `_case` names every document `report.txt`: the name must not decide. Its
    # quote is the extracted line, not a line of the PDF's own syntax.
    case = _case("pdf", pdf, quote=line)
    assert [document.filename.value for document in case.documents] == ["report.txt"]
    subject.prepare(conn, blobs, harness, qualification=QualificationSet((case,)))
    rows = conn.execute("SELECT extractor_identity FROM source_extractions").fetchall()
    assert [json.loads(str(row[0]))["name"] for row in rows] == ["caos.pdfminer"]
    tokens = conn.execute("SELECT text FROM source_tokens ORDER BY token_id").fetchall()
    assert [row[0] for row in tokens][:2] == ["Total", "debt"]
    conn.rollback()
