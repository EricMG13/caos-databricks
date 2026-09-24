"""Complete immutable input identity on real PostgreSQL, before any execution."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from canonical_fixtures import research_brief
from conftest import route_fault
from psycopg.pq import TransactionStatus
from test_case_ordering import _blocked
from test_route_pinning import CATALOG_PATH, PROFILE
from test_source_sets import _admit

from caos import methodology
from caos.boundary_text import BoundaryText
from caos.graph.route import EdgeType, ResolvedRoute, resolve_route, route_digest
from caos.methodology.bundle import Bundle
from caos.methodology.vendor import (
    authority_bundle_sha256,
    cached_contract,
    catalog,
)
from caos.refusals import Refusal
from caos.store import StoreConnection, connect, run_inputs
from caos.store.cases import lock_case
from caos.store.events import RunEvent, append, events_of, lock_run
from caos.store.gates import withdraw_source
from caos.store.routes import pin_route
from caos.store.run_inputs import (
    UNANCHORED_CP0,
    RunInput,
    RunSubject,
    bound_research_brief,
    load_run_input,
    pin_run_input,
    research_text,
)
from caos.store.runs import create_case, fail_run, start_attempt, start_run
from caos.store.source_sets import SourceSet, snapshot_source_set

type Prepared = tuple[StoreConnection, UUID, SourceSet, Bundle, ResolvedRoute]

# Every new pin names a subject (the one canonical adapter, §42.1).
SUBJECT = RunSubject("EXAMPLE", "Example Holdings plc", "FY2025", "2026-09-08")


def _prepare(
    conn: StoreConnection,
    case_id: UUID,
    path: Path,
    selection: tuple[str, str] = (PROFILE, "MARKET_DISLOCATION"),
) -> tuple[UUID, SourceSet, Bundle, ResolvedRoute]:
    """A run on `selection`, pinned but not yet input-pinned. The default is a
    route the adapter does not execute: pinning stays general (§42.2)."""
    _admit(conn, case_id, path)
    conn.commit()
    source = snapshot_source_set(conn, case_id)
    run = start_run(conn, case_id)
    route = resolve_route(json.loads(CATALOG_PATH.read_text()), *selection)
    pin_route(conn, run, route)
    return run, source, Bundle(CATALOG_PATH.parents[3]), route


def pin_version_one(
    conn: StoreConnection,
    run: UUID,
    source: SourceSet,
    bundle: Bundle,
    route: ResolvedRoute,
) -> RunInput:
    """A version-1 `claims-json-v1` pin written exactly as the pre-0011 code
    wrote it, so a database at an older migration prefix can hold one."""
    lock_run(conn, run)
    pin = RunInput(
        run,
        source.case_id,
        source.version,
        source.fingerprint,
        route_digest(route),
        bundle.build_id,
        bundle.manifest_sha256,
        "claims-json-v1",
        run_inputs._research({"q": "Café?"}),
        "",
    )
    pin = replace(pin, input_fingerprint=run_inputs._fingerprint(pin))
    fields = run_inputs.input_fields(pin)
    conn.execute(
        psycopg.sql.SQL("INSERT INTO run_inputs ({}) VALUES ({})").format(
            psycopg.sql.SQL(",").join(map(psycopg.sql.Identifier, fields)),
            psycopg.sql.SQL(",").join(psycopg.sql.Placeholder() for _ in fields),
        ),
        tuple(fields.values()),
    )
    append(conn, run, RunEvent.INPUT_PINNED)
    conn.commit()
    return pin


@pytest.fixture
def prepared(case: tuple[StoreConnection, UUID], tmp_path: Path) -> Prepared:
    conn, case_id = case
    return conn, *_prepare(conn, case_id, tmp_path)


@pytest.fixture
def research_prepared(case: tuple[StoreConnection, UUID], tmp_path: Path) -> Prepared:
    conn, case_id = case
    return conn, *_prepare(conn, case_id, tmp_path, (PROFILE, "DEEP_RESEARCH"))


def test_complete_input_roundtrip_exact_terminal_replay(
    research_prepared: Prepared,
) -> None:
    conn, run, source, bundle, route = research_prepared
    research = research_brief(decision_context="Café?")
    pin = pin_run_input(conn, run, source.version, bundle, research, subject=SUBJECT)
    assert conn.info.transaction_status.name == "IDLE"
    assert isinstance(pin, RunInput)
    assert pin.case_id == source.case_id and pin.source_version == source.version
    assert pin.source_fingerprint == source.fingerprint
    assert pin.route_digest == route_digest(route)
    assert pin.build_id == bundle.build_id
    assert pin.manifest_sha256 == bundle.manifest_sha256
    assert pin.adapter_version == "canonical-markdown-v3"
    assert pin.research_json is not None and json.loads(pin.research_json) == research
    research["source_mode"] = "changed"
    assert load_run_input(conn, run) == pin
    assert conn.info.transaction_status is TransactionStatus.INTRANS
    with pytest.raises(FrozenInstanceError):
        pin.source_version = 7  # type: ignore[misc]  # frozen model regression
    fail_run(conn, run)
    before = events_of(conn, run)
    assert (
        pin_run_input(
            conn,
            run,
            source.version,
            bundle,
            json.loads(pin.research_json),
            subject=SUBJECT,
        )
        == pin
    )
    assert conn.info.transaction_status.name == "IDLE"
    assert events_of(conn, run) == before
    assert [e.name for e in before].count("INPUT_PINNED") == 1
    assert conn.execute("SELECT count(*) FROM run_inputs").fetchone() == (1,)


def test_every_bound_component_changes_fingerprint_with_other_identity_fixed(
    prepared: Prepared,
) -> None:
    conn, run, source, bundle, route = prepared
    pin = pin_run_input(conn, run, source.version, bundle, subject=SUBJECT)
    fingerprints = {pin.input_fingerprint}
    for field, value in (
        ("case_id", uuid4()),
        ("source_version", 2),
        ("source_fingerprint", "a" * 64),
        ("build_id", "b" * 64),
        ("manifest_sha256", "c" * 64),
        ("adapter_version", "claims-json-v2"),
        ("research_json", "{}"),
        ("research_json", '{"question":"A"}'),
        ("research_json", '{"question":"B"}'),
    ):
        fingerprints.add(
            run_inputs._fingerprint(RunInput(**{**asdict(pin), field: value}))
        )
    assert len(fingerprints) == 10
    for changed in (
        replace(route, profile_id="other"),
        replace(route, selection_id="other"),
        replace(
            route,
            nodes=(replace(route.nodes[0], route_node_id="other"), route.nodes[1]),
        ),
        replace(
            route, nodes=(replace(route.nodes[0], module_id="CP-1"), route.nodes[1])
        ),
        replace(route, edges=(replace(route.edges[0], type=EdgeType.OPTIONAL),)),
        replace(route, predicates=(("question", "changed"),)),
    ):
        candidate = replace(pin, route_digest=route_digest(changed))
        assert run_inputs._fingerprint(candidate) != pin.input_fingerprint
    assert (
        run_inputs._fingerprint(replace(pin, run_id=uuid4())) == pin.input_fingerprint
    )


def test_returning_source_content_still_binds_distinct_version(
    prepared: Prepared, tmp_path: Path
) -> None:
    conn, run, first, bundle, _ = prepared
    pin = pin_run_input(conn, run, first.version, bundle, subject=SUBJECT)
    added = _admit(conn, first.case_id, tmp_path)
    conn.commit()
    middle = snapshot_source_set(conn, first.case_id)
    withdraw_source(
        conn, case_id=first.case_id, source_id=added, actor_id=first.case_id
    )
    later = snapshot_source_set(conn, first.case_id)
    assert (first.version, middle.version, later.version) == (1, 2, 3)
    assert later.fingerprint == first.fingerprint != middle.fingerprint
    assert (
        run_inputs._fingerprint(replace(pin, source_version=later.version))
        != pin.input_fingerprint
    )
    for selected in (middle, later):
        with pytest.raises(Refusal, match=r"^RUN_INPUT_ALREADY_PINNED$"):
            pin_run_input(conn, run, selected.version, bundle, subject=SUBJECT)
    assert load_run_input(conn, run) == pin


@pytest.mark.parametrize(
    "changed", ["build", "manifest", "adapter", "research", "moving"]
)
def test_changed_host_or_research_refuses_replay_but_history_is_readable(
    research_prepared: Prepared,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed: str,
) -> None:
    conn, run, source, bundle, _ = research_prepared
    pin = pin_run_input(
        conn, run, source.version, bundle, research_brief(), subject=SUBJECT
    )
    if changed in {"build", "manifest", "moving"}:
        raw = (bundle.root / "DEPLOY_V_INTEGRITY_v1.json").read_text()
        if changed == "build":
            raw = raw.replace(bundle.build_id, "d" * 64)
        (tmp_path / "DEPLOY_V_INTEGRITY_v1.json").write_text(raw + " ")
        bundle = Bundle(tmp_path)
        if changed == "moving":
            (tmp_path / "DEPLOY_V_INTEGRITY_v1.json").write_text(raw + "  ")
    if changed == "adapter":
        monkeypatch.setattr(
            methodology, "CANONICAL_ADAPTER_VERSION", "canonical-markdown-v4"
        )
    assert load_run_input(conn, run) == pin
    expected = (
        "AUTHORITY_BYTES_MISMATCH"
        if changed == "moving"
        else "RUN_INPUT_ALREADY_PINNED"
    )
    with pytest.raises(Refusal, match=f"^{expected}$"):
        pin_run_input(
            conn,
            run,
            source.version,
            bundle,
            research_brief(decision_context="changed")
            if changed == "research"
            else research_brief(),
            subject=SUBJECT,
        )
    assert load_run_input(conn, run) == pin
    assert [e.name for e in events_of(conn, run)] == ["ROUTE_PINNED", "INPUT_PINNED"]


@pytest.mark.parametrize(
    "invalid",
    [
        [],
        "private",
        {1: "private"},
        {"x": (1,)},
        {"x": float("nan")},
        {"x": float("inf")},
        {"x": 2**63},
        {"x": b"private"},
        {"x": "e\u0301"},
        {"x": "private\u202e"},
        {"x": "\ud800"},
        {"x": "x" * 4097},
        {"x": [0] * 4096},
        {"x": ["😀" * 4096] * 4},
    ],
)
def test_research_refuses_without_coercion_or_private_diagnostics(
    invalid: object,
) -> None:
    with pytest.raises(Refusal, match=r"^RUN_INPUT_INVALID$"):
        run_inputs._research(invalid)


def test_research_exact_ordering_depth_count_and_utf8_size() -> None:
    assert run_inputs._research(None) is None
    assert run_inputs._research({}) == "{}"
    assert run_inputs._research(
        {"z": [True, None, 1.0], "a": "Café\r\n"}
    ) == run_inputs._research({"a": "Café\r\n", "z": [True, None, 1.0]})
    nested: dict[str, object] = {}
    for _ in range(16):
        nested = {"x": nested}
    assert run_inputs._research(nested)
    with pytest.raises(Refusal):
        run_inputs._research({"x": nested})
    assert run_inputs._research({"x": [0] * 4093})
    with pytest.raises(Refusal):
        run_inputs._research({"x": [0] * 4094})
    exact = {str(i): "x" * 4096 for i in range(15)}
    exact["last"] = "x" * (65536 - len(run_inputs._research(exact) or "") - 10)
    assert len((run_inputs._research(exact) or "").encode()) == 65536
    exact["last"] += "x"
    with pytest.raises(Refusal):
        run_inputs._research(exact)
    cycle: dict[str, object] = {}
    cycle["cycle"] = cycle
    with pytest.raises(Refusal):
        run_inputs._research(cycle)


def _refused_at_pin(prepared: Prepared, research: object) -> None:
    """`research` is refused `RUN_INPUT_INVALID` and nothing is pinned."""
    conn, run, source, bundle, _ = prepared
    before = events_of(conn, run)
    conn.commit()
    with pytest.raises(Refusal, match=r"^RUN_INPUT_INVALID$"):
        pin_run_input(conn, run, source.version, bundle, research, subject=SUBJECT)
    assert conn.info.transaction_status is TransactionStatus.IDLE
    assert load_run_input(conn, run) is None and events_of(conn, run) == before


def test_a_brief_naming_a_consumer_the_route_does_not_carry_refuses_at_pin(
    research_prepared: Prepared,
) -> None:
    """§96: a question's consumer or predecessor must be a module the pinned
    route selects -- the vendor's own `Route` judges the placement -- and the
    brief must be about the pinned subject; otherwise nothing is pinned."""
    _refused_at_pin(research_prepared, research_brief(placement=("CP-2A", "CP-0")))
    _refused_at_pin(research_prepared, research_brief(placement=("NONE", "CP-1")))
    _refused_at_pin(research_prepared, research_brief("OTHER"))


def test_a_brief_with_web_source_mode_refuses_at_pin(
    research_prepared: Prepared,
) -> None:
    """Invariant 1: web discovery is structurally absent, so a brief asking for
    `web_only` or `hybrid` asks for a capability nothing here has. It is
    refused at the pin, where the vendor would accept it."""
    for mode in ("web_only", "hybrid"):
        _refused_at_pin(research_prepared, research_brief(source_mode=mode))


def test_a_brief_cannot_supply_its_own_run_id_or_cp0_digest(
    research_prepared: Prepared,
) -> None:
    """Invariant 3: `run_id`, `cp0_sha256` and `authority_sha256` are written
    by the host when CP-DR is invoked; a caller's brief carrying any of them,
    or a field the brief schema does not declare, is refused, and a brief on a
    route with no CP-DR node reaches nobody and is refused too."""
    for binding in ("run_id", "cp0_sha256", "authority_sha256"):
        _refused_at_pin(research_prepared, {**research_brief(), binding: "a" * 64})
    _refused_at_pin(research_prepared, research_brief(tools=["web_search"]))
    _refused_at_pin(research_prepared, research_brief(mode="standalone"))
    conn, run, source, bundle, _ = research_prepared
    pin = pin_run_input(
        conn, run, source.version, bundle, research_brief(), subject=SUBJECT
    )
    assert pin.research_json == research_text(research_brief())
    assert pin.research_json is not None
    stored = json.loads(pin.research_json)
    assert stored == research_brief()
    assert not {"run_id", "cp0_sha256", "authority_sha256"} & set(stored)


def test_the_bound_brief_carries_exactly_the_host_bindings(
    research_prepared: Prepared,
) -> None:
    """`bound_research_brief` is the one place a brief meets the vendor's
    `validate_brief` and `Route`: it returns the caller's brief with the three
    host bindings written in and nothing else changed, and refuses a brief the
    vendor refuses without letting the vendor's text reach the refusal."""
    _, _, _, bundle, route = research_prepared
    contract = cached_contract(bundle)
    assert cached_contract(bundle) is contract
    bindings = {
        "run_id": "COS-20260908T120000Z-" + "1" * 32,
        "cp0_sha256": UNANCHORED_CP0,
        "authority_sha256": authority_bundle_sha256(bundle),
    }
    bound = bound_research_brief(
        contract,
        catalog(bundle),
        brief=research_brief(),
        route=route,
        subject=SUBJECT,
        **bindings,
    )
    assert bound == {**research_brief(), **bindings}
    with pytest.raises(Refusal) as refused:
        bound_research_brief(
            contract,
            catalog(bundle),
            brief=research_brief(as_of_date="not a date"),
            route=route,
            subject=SUBJECT,
            **bindings,
        )
    assert refused.value.code.value == "RUN_INPUT_INVALID"
    assert refused.value.__context__ is None and refused.value.__cause__ is None


def test_a_deep_research_run_pinned_without_a_brief_refuses_at_pin(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """§96: on an enabled pathway carrying CP-DR the vendor's own rule -- CP-DR
    requires a run-scoped brief -- is asked before anything is spent, so a
    brief-less input is refused at the pin rather than after CP-0 is paid."""
    conn, case_id = case
    run, source, bundle, _ = _prepare(
        conn, case_id, tmp_path, ("LITE_CREDIT_22", "LITE_DEEP_RESEARCH")
    )
    conn.commit()
    with pytest.raises(Refusal, match=r"^RUN_INPUT_INVALID$"):
        pin_run_input(conn, run, source.version, bundle, subject=SUBJECT)
    assert load_run_input(conn, run) is None
    pin = pin_run_input(
        conn, run, source.version, bundle, research_brief(), subject=SUBJECT
    )
    assert pin.research_json is not None


def test_a_brief_on_a_route_without_cp_dr_refuses_at_pin(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    conn, case_id = case
    run, source, bundle, _ = _prepare(
        conn, case_id, tmp_path, ("LITE_CREDIT_22", "LITE_EARNINGS_UPDATE")
    )
    conn.commit()
    with pytest.raises(Refusal, match=r"^RUN_INPUT_INVALID$"):
        pin_run_input(
            conn, run, source.version, bundle, research_brief(), subject=SUBJECT
        )
    assert load_run_input(conn, run) is None


@pytest.mark.parametrize(
    "state",
    [
        "missing",
        "route",
        "source",
        "unknown",
        "complete",
        "failed",
        "attempt",
        "autocommit",
        "version",
        "research",
    ],
)
def test_invalid_dependencies_or_late_input_leave_no_partial_history(
    prepared: Prepared, state: str
) -> None:
    conn, run, source, bundle, route = prepared
    version: object = source.version
    expected = "RUN_INPUT_INVALID"
    if state == "missing":
        run, expected = uuid4(), "RUN_NOT_FOUND"
    elif state == "route":
        run = start_run(conn, source.case_id)
    elif state in {"source", "unknown"}:
        other_case = create_case(conn, BoundaryText.of("No captured provenance"))
        run = start_run(conn, other_case)
        pin_route(conn, run, route)
        if state == "unknown":
            conn.execute(
                "INSERT INTO sources (source_id,case_id,document_sha256,filename)"
                " VALUES (%s,%s,%s,'legacy')",
                (uuid4(), other_case, "a" * 64),
            )
    elif state in {"complete", "failed"}:
        conn.execute(
            "UPDATE runs SET status = %s WHERE run_id = %s", (state.upper(), run)
        )
        expected = "RUN_NOT_RUNNING"
    elif state == "attempt":
        start_attempt(conn, run, route.nodes[0].route_node_id)
        expected = "RUN_INPUT_TOO_LATE"
    elif state == "version":
        version = True
    conn.commit()
    before = events_of(conn, run)
    conn.commit()
    if state == "autocommit":
        conn.autocommit, expected = True, "STORE_NOT_TRANSACTIONAL"
    with pytest.raises(Refusal, match=f"^{expected}$"):
        pin_run_input(
            conn,
            run,
            version,  # type: ignore[arg-type]
            bundle,
            {1: "private"} if state == "research" else None,
            subject=SUBJECT,
        )
    assert conn.info.transaction_status is TransactionStatus.IDLE
    assert load_run_input(conn, run) is None and events_of(conn, run) == before


@pytest.mark.parametrize("state", ["corrupt-route", "corrupt-source"])
def test_load_rechecks_verified_dependencies(prepared: Prepared, state: str) -> None:
    conn, run, source, bundle, _ = prepared
    pin_run_input(conn, run, source.version, bundle, subject=SUBJECT)
    if state == "corrupt-route":
        with route_fault(conn):
            conn.execute(
                "UPDATE run_routes SET resolved = '{}' WHERE run_id = %s", (run,)
            )
        expected = "ROUTE_IDENTITY_INVALID"
    else:
        conn.execute(
            "ALTER TABLE source_set_members DISABLE TRIGGER source_set_immutable"
        )
        conn.execute("UPDATE source_set_members SET filename = 'corrupt'")
        conn.execute(
            "ALTER TABLE source_set_members ENABLE TRIGGER source_set_immutable"
        )
        expected = "SOURCE_IDENTITY_INVALID"
    conn.commit()
    before = events_of(conn, run)
    with pytest.raises(Refusal, match=f"^{expected}$"):
        load_run_input(conn, run)
    with pytest.raises(Refusal, match=f"^{expected}$"):
        pin_run_input(conn, run, source.version, bundle, subject=SUBJECT)
    assert conn.info.transaction_status is TransactionStatus.IDLE
    assert events_of(conn, run) == before


@pytest.mark.parametrize(
    "raw",
    [
        "{",
        "{}",
        "[]",
        "null",
        '{"x":NaN}',
        '{"x":1e400}',
        '{"x":1,"x":2}',
        '{ "x":1}',
        "[ " * 1000,
    ],
)
def test_stored_research_and_hash_are_reverified(prepared: Prepared, raw: str) -> None:
    conn, run, source, bundle, _ = prepared
    pin_run_input(conn, run, source.version, bundle, subject=SUBJECT)
    database = conn.execute("SELECT current_database()").fetchone()
    assert database is not None and database[0].startswith("caos_test_")
    conn.execute("ALTER TABLE run_inputs DISABLE TRIGGER input_immutable")
    conn.execute("UPDATE run_inputs SET research_json = %s", (raw,))
    conn.execute("ALTER TABLE run_inputs ENABLE TRIGGER input_immutable")
    conn.commit()
    with pytest.raises(Refusal, match=r"^RUN_INPUT_INVALID$"):
        load_run_input(conn, run)
    assert conn.info.transaction_status is TransactionStatus.INTRANS
    with pytest.raises(Refusal, match=r"^RUN_INPUT_INVALID$"):
        pin_run_input(conn, run, source.version, bundle, subject=SUBJECT)
    assert conn.info.transaction_status.name == "IDLE"


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE run_inputs SET build_id = build_id",
        "DELETE FROM run_inputs",
        "TRUNCATE run_inputs",
        "TRUNCATE run_routes",
        "TRUNCATE runs CASCADE",
    ],
)
def test_native_input_immutability(
    prepared: Prepared,
    mutation: str,
) -> None:
    conn, run, source, bundle, _ = prepared
    pin = pin_run_input(conn, run, source.version, bundle, subject=SUBJECT)
    with pytest.raises(psycopg.Error):
        conn.execute(mutation)
    conn.rollback()
    assert load_run_input(conn, run) == pin


@pytest.mark.parametrize(
    "field",
    ["case_id", "run_id", "source_version", "source_fingerprint", "route_digest"],
)
def test_native_foreign_keys_bind_actual_case_source_and_route(
    prepared: Prepared, field: str
) -> None:
    conn, run, source, bundle, route = prepared
    pin = pin_run_input(conn, run, source.version, bundle, subject=SUBJECT)
    extra = start_run(conn, source.case_id)
    pin_route(conn, extra, route)
    values = run_inputs.input_fields(replace(pin, run_id=extra))
    subject = values.pop("subject")
    assert isinstance(subject, dict)
    values.update(subject, format_version=2)
    values[field] = (
        uuid4()
        if field.endswith("_id")
        else 99
        if field == "source_version"
        else "0" * 64
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(
            psycopg.sql.SQL("INSERT INTO run_inputs ({}) VALUES ({})").format(
                psycopg.sql.SQL(",").join(map(psycopg.sql.Identifier, values)),
                psycopg.sql.SQL(",").join(psycopg.sql.Placeholder() for _ in values),
            ),
            tuple(values.values()),
        )
    conn.rollback()
    assert load_run_input(conn, run) == pin and load_run_input(conn, extra) is None


@pytest.mark.parametrize("failure", ["first", "second", "commit", "cancel", "broken"])
def test_input_failure_rolls_back_both_writes_and_releases_locks(
    prepared: Prepared,
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    conn, run, source, bundle, _ = prepared
    if failure in {"first", "second"}:
        conn.execute(
            "ALTER TABLE "
            + (
                "run_inputs ADD CHECK (source_version < 0)"
                if failure == "first"
                else "run_events ADD CHECK (name <> 'INPUT_PINNED')"
            )
        )
    elif failure == "commit":
        conn.execute(
            "CREATE FUNCTION input_failure() RETURNS trigger LANGUAGE plpgsql AS $$"
            " BEGIN RAISE EXCEPTION 'private'; END; $$;"
            " CREATE CONSTRAINT TRIGGER input_failure AFTER INSERT ON run_inputs"
            " DEFERRABLE INITIALLY DEFERRED FOR EACH ROW"
            " EXECUTE FUNCTION input_failure()"
        )
    else:

        def fail(*args: object) -> None:
            append(conn, run, RunEvent.INPUT_PINNED)
            if failure == "broken":
                conn.close()
            raise KeyboardInterrupt

        monkeypatch.setattr(run_inputs, "append", fail)
    conn.commit()
    with pytest.raises(
        KeyboardInterrupt if failure in {"cancel", "broken"} else Refusal
    ):
        pin_run_input(conn, run, source.version, bundle, subject=SUBJECT)
    assert conn.closed or conn.info.transaction_status is TransactionStatus.IDLE
    with connect(empty_database) as other:
        other.execute("SET lock_timeout = '1s'")
        lock_case(other, source.case_id)
        assert load_run_input(other, run) is None
        assert [e.name for e in events_of(other, run)] == ["ROUTE_PINNED"]


@pytest.mark.parametrize("conflict", [False, True])
def test_observed_blocking_first_inputs_and_independent_case(
    prepared: Prepared, empty_database: str, tmp_path: Path, conflict: bool
) -> None:
    conn, run, source, bundle, _ = prepared
    case2 = create_case(conn, BoundaryText.of("Independent"))
    independent, source2, _, _ = _prepare(conn, case2, tmp_path)
    lock_case(conn, source.case_id)
    with connect(empty_database) as other:
        other.execute("SET lock_timeout = '1s'")
        pin_run_input(other, independent, source2.version, bundle, subject=SUBJECT)

        def waiting() -> None:
            if conflict:
                with pytest.raises(Refusal, match=r"^RUN_INPUT_ALREADY_PINNED$"):
                    pin_run_input(
                        other,
                        run,
                        source.version,
                        bundle,
                        research_brief(),
                        subject=SUBJECT,
                    )
            else:
                assert pin_run_input(
                    other, run, source.version, bundle, subject=SUBJECT
                ) == load_run_input(other, run)
                other.rollback()
            assert other.info.transaction_status is TransactionStatus.IDLE

        with _blocked(conn, other, waiting):
            pin = pin_run_input(conn, run, source.version, bundle, subject=SUBJECT)
    assert load_run_input(conn, run) == pin
    assert [e.name for e in events_of(conn, run)] == ["ROUTE_PINNED", "INPUT_PINNED"]


def _softened(route: ResolvedRoute) -> ResolvedRoute:
    """`route` with its first edge's type changed: not the catalog's route."""
    edge = route.edges[0]
    other = (
        EdgeType.ADVISORY if edge.type is not EdgeType.ADVISORY else EdgeType.OPTIONAL
    )
    return replace(route, edges=(replace(edge, type=other), *route.edges[1:]))


def test_a_route_the_catalog_does_not_resolve_is_refused_at_input_pin(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """CF-025: `pin_route_in` stores whatever route it is given, and the input
    pin binds the build that route then runs under. A route that is not that
    build's own catalog resolution of its pathway -- one edge's type changed
    here -- refuses `ROUTE_IDENTITY_INVALID` and pins nothing."""
    conn, case_id = case
    _admit(conn, case_id, tmp_path)
    conn.commit()
    source = snapshot_source_set(conn, case_id)
    run = start_run(conn, case_id)
    route = resolve_route(
        json.loads(CATALOG_PATH.read_text()), PROFILE, "MARKET_DISLOCATION"
    )
    pin_route(conn, run, _softened(route))
    before = events_of(conn, run)
    conn.commit()
    with pytest.raises(Refusal, match=r"^ROUTE_IDENTITY_INVALID$"):
        pin_run_input(
            conn, run, source.version, Bundle(CATALOG_PATH.parents[3]), subject=SUBJECT
        )
    assert conn.info.transaction_status is TransactionStatus.IDLE
    assert load_run_input(conn, run) is None and events_of(conn, run) == before


def test_execution_refuses_a_pinned_route_the_catalog_does_not_resolve(
    case: tuple[StoreConnection, UUID],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CF-025, where the pin is read for execution: a run whose input was
    pinned before inputs were checked against the catalog -- stood in for by
    the check switched off while it is pinned and approved -- is refused
    `ROUTE_IDENTITY_INVALID` by `execution_input`, before any attempt, where
    `invocation._upstream` would have trusted its edges."""
    from conftest import approve_run

    from caos.store.gates import execution_input

    conn, case_id = case
    _admit(conn, case_id, tmp_path)
    conn.commit()
    run = start_run(conn, case_id)
    conn.commit()
    route = resolve_route(
        json.loads(CATALOG_PATH.read_text()), "LITE_CREDIT_22", "LITE_EARNINGS_UPDATE"
    )
    bundle = Bundle(CATALOG_PATH.parents[3])
    monkeypatch.setattr(run_inputs, "require_catalog_route", lambda *_: None)
    approve_run(
        conn, case_id=case_id, run_id=run, route=_softened(route), bundle=bundle
    )
    monkeypatch.undo()
    with pytest.raises(Refusal, match=r"^ROUTE_IDENTITY_INVALID$"):
        execution_input(conn, run, bundle)
    conn.rollback()
    assert conn.execute(
        "SELECT count(*) FROM run_attempts WHERE run_id = %s", (run,)
    ).fetchone() == (0,)
