"""D75, the command half: a create pins the model it names, or the configured
one, refuses one the deployment does not approve, and the Run section serves
the choices and each run's model. The list and the worker are
`tests/test_model_choice.py`'s."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from command_fixtures import command_client, member
from fastapi.testclient import TestClient
from qualification_fixtures import (
    qualification_performed,
    record_performed_earlier,
    record_runs,
)
from test_model_choice import deployed
from test_run_commands import ROUTE, _outcome, _path, _send

from caos.api.deps import methodology_bundle
from caos.api.reads.qualification import verdict_state
from caos.api.wire import QualificationState
from caos.copilot import identity_of
from caos.pricing import MODEL_PRICE_ENV, model_choices
from caos.qualification.store import record_verdict
from caos.qualification.verdict import read_verdict
from caos.store import StoreConnection
from caos.store.audit import audit_trail, digest_of
from caos.store.budget import price_of
from caos.store.commands import request_digest
from caos.store.members import Standing
from caos.store.routes import pinned_route

__all__ = ["command_client", "deployed"]


def test_a_new_run_is_pinned_to_the_model_it_names_or_the_configured_one(
    command_client: TestClient,
    case: tuple[StoreConnection, UUID],
    deployed: None,
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    started = {}
    for named in ("gpt-6-luna", None):
        created = _send(
            command_client, _path(case_id), writer, {**ROUTE, "model": named}
        )
        assert created.status_code == 201, created.text
        started[named] = price_of(conn, UUID(created.json()["run_id"]))
        conn.rollback()
    assert started == {
        "gpt-6-luna": model_choices()["gpt-6-luna"],
        None: model_choices()["claude-opus-5-5"],
    }
    # The audit binds the model each run was pinned to, the configured one
    # where the request named none; the request digest stays the request's.
    trail = audit_trail(conn, case_id)
    conn.rollback()
    for entry, (named, pinned_to) in zip(
        trail,
        [("gpt-6-luna", "gpt-6-luna"), (None, "claude-opus-5-5")],
        strict=True,
    ):
        body = {**ROUTE, "model": named}
        [run_id] = [
            UUID(str(row[0]))
            for row in conn.execute(
                "SELECT run_id FROM runs WHERE price_model = %s", (pinned_to,)
            ).fetchall()
        ]
        conn.rollback()
        assert entry.payload_sha256 == digest_of(
            {
                **body,
                "model": pinned_to,
                "route_digest": pinned_route(conn, run_id),
                "rate_deck": None,
                "request_sha256": request_digest(
                    "CREATE_RUN", case_id=case_id, run_id=None, gate=None, body=body
                ),
            }
        )
        conn.rollback()
    listed = _send(command_client, f"/api/v1/cases/{case_id}/run", writer).json()
    assert [run["model"] for run in listed["body"]["runs"]] == [
        "claude-opus-5-5",
        "gpt-6-luna",
    ]
    assert listed["body"]["model_choices"][0] == {
        "model": "claude-opus-5-5",
        "input_per_token": "0.000005",
        "output_per_token": "0.000025",
        "as_of": "2026-09-22",
        "configured": True,
        "qualification": "UNQUALIFIED",
    }
    assert [choice["configured"] for choice in listed["body"]["model_choices"]] == [
        True,
        False,
        False,
    ]


def test_a_model_the_deployment_does_not_approve_is_refused_and_starts_nothing(
    command_client: TestClient,
    case: tuple[StoreConnection, UUID],
    deployed: None,
) -> None:
    conn, case_id = case
    writer = member(conn, case_id)
    for named in ("grok-4-7", "claude-opus-5"):
        refused = _send(
            command_client, _path(case_id), writer, {**ROUTE, "model": named}
        )
        assert _outcome(refused) == "400 PROVIDER_NOT_CONFIGURED"
    assert conn.execute("SELECT count(*) FROM runs").fetchone() == (0,)
    conn.rollback()


def test_a_process_with_no_model_configured_pins_none(
    command_client: TestClient,
    case: tuple[StoreConnection, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run then takes the model of the worker that first executes it."""
    monkeypatch.delenv(MODEL_PRICE_ENV, raising=False)
    conn, case_id = case
    writer = member(conn, case_id)
    created = _send(command_client, _path(case_id), writer, {**ROUTE, "model": None})
    assert created.status_code == 201, created.text
    assert price_of(conn, UUID(created.json()["run_id"])) is None
    conn.rollback()
    named = _send(
        command_client, _path(case_id), writer, {**ROUTE, "model": "gpt-6-luna"}
    )
    assert _outcome(named) == "400 PROVIDER_NOT_CONFIGURED"


def _verdict(
    conn: StoreConnection,
    model: str,
    *,
    days: int,
    build_id: str | None = None,
    provider: str | None = None,
) -> None:
    """One verdict signed through `record_performed` and `record_verdict` over
    `model`'s evidence: by default under the model's own identity and the
    current bundle's build, expiring in `days` days (negative: already
    expired); `build_id` and `provider` stand for another build or identity."""
    performed = qualification_performed(
        provider=provider or identity_of(model),
        model=model,
        build_id=build_id or methodology_bundle().build_id,
        ordinal=list(model_choices()).index(model) + 1,
    )
    record_runs(conn, performed)
    record_performed_earlier(conn, performed)
    decided = datetime.now(UTC) - timedelta(days=60)
    signed = read_verdict(
        {
            "provider": performed.evidence.provider + ":" + model,
            "qualification_set_sha256": performed.evidence.qualification_set_sha256,
            "build_id": performed.evidence.build_id,
            "decided_at": decided.isoformat(),
            "expires_at": (datetime.now(UTC) + timedelta(days=days)).isoformat(),
            "reviewer": "Reviewer",
            "evidence_sha256": performed.evidence.sha256,
        },
        now=decided,
    )
    record_verdict(
        conn, evidence=performed.evidence, reviewer_id=uuid4(), verdict=signed
    )
    conn.commit()


def _labels(
    client: TestClient, case_id: UUID, user: UUID, *, role: str = "ANALYST"
) -> dict[str, str]:
    listed = _send(client, f"/api/v1/cases/{case_id}/run", user, role=role).json()
    return {
        choice["model"]: choice["qualification"]
        for choice in listed["body"]["model_choices"]
    }


def test_each_approved_model_is_labelled_with_its_qualification_state(
    command_client: TestClient,
    case: tuple[StoreConnection, UUID],
    deployed: None,
) -> None:
    """N117: a model with a current verdict the single validator accepts is
    QUALIFIED; one with none, or only an expired one, is UNQUALIFIED; every
    approved model is still listed."""
    conn, case_id = case
    writer = member(conn, case_id)
    _verdict(conn, "gpt-6-luna", days=30)
    _verdict(conn, "claude-sonnet-5-5", days=-1)
    assert _labels(command_client, case_id, writer) == {
        "claude-opus-5-5": "UNQUALIFIED",
        "claude-sonnet-5-5": "UNQUALIFIED",
        "gpt-6-luna": "QUALIFIED",
    }


@pytest.mark.parametrize(
    "stale",
    [
        {"build_id": "9" * 64},
        {"provider": "databricks/gpt-6-luna/high/65536"},
    ],
    ids=["another-build", "another-identity"],
)
def test_a_verdict_on_another_build_or_identity_does_not_qualify_the_model(
    command_client: TestClient,
    case: tuple[StoreConnection, UUID],
    deployed: None,
    stale: dict[str, str],
) -> None:
    """Every re-pin leaves verdicts on the earlier build, and an effort or cap
    the worker does not run is another profile (D8): neither is this model's."""
    conn, case_id = case
    writer = member(conn, case_id)
    _verdict(conn, "gpt-6-luna", days=30, **stale)
    assert _labels(command_client, case_id, writer)["gpt-6-luna"] == "UNQUALIFIED"


def test_a_verdict_row_the_validator_refuses_does_not_qualify_the_model(
    command_client: TestClient,
    case: tuple[StoreConnection, UUID],
    deployed: None,
) -> None:
    """DQ-3: rows written straight into the tables, with no snapshot behind
    them, are `VERDICT_INCOMPLETE` to `current_verdict` and so not QUALIFIED;
    a store that disagrees with a signed snapshot is UNAVAILABLE (as
    `read_qualification` maps it), never QUALIFIED."""
    conn, case_id = case
    writer = member(conn, case_id)
    digest = "a" * 64
    conn.execute(
        "INSERT INTO qualification_evidence (evidence_sha256,"
        " qualification_set_sha256,performed_sha256,build_id,adapter_version,"
        " provider,model) VALUES (%s,%s,%s,%s,'a',%s,'gpt-6-luna')",
        (
            digest,
            digest,
            digest,
            methodology_bundle().build_id,
            identity_of("gpt-6-luna"),
        ),
    )
    conn.execute(
        "INSERT INTO qualification_verdicts"
        " (evidence_sha256,reviewer_id,reviewer,decided_at,expires_at)"
        " VALUES (%s,gen_random_uuid(),'Reviewer',now() - interval '30 days',"
        " now() + interval '30 days')",
        (digest,),
    )
    conn.commit()
    _verdict(conn, "claude-sonnet-5-5", days=30)
    # The status of a run the store holds is fixed once terminal, so the
    # disagreement is forged the way `record_performed_earlier` moves a date.
    conn.execute("SET LOCAL session_replication_role = replica")
    conn.execute(
        "UPDATE runs SET status = 'FAILED' WHERE run_id = %s",
        (UUID(int=1 + 2 * 0x100),),
    )
    conn.execute("SET LOCAL session_replication_role = origin")
    conn.commit()
    assert _labels(command_client, case_id, writer) == {
        "claude-opus-5-5": "UNQUALIFIED",
        "claude-sonnet-5-5": "UNAVAILABLE",
        "gpt-6-luna": "UNQUALIFIED",
    }


def test_a_reader_is_served_the_state_the_qualification_read_gives_a_reader(
    command_client: TestClient,
    case: tuple[StoreConnection, UUID],
    deployed: None,
) -> None:
    """The label follows `read_qualification`'s role rule: a READER is told
    RESTRICTED for every model, qualified or not."""
    conn, case_id = case
    reader = member(conn, case_id, Standing.READER)
    _verdict(conn, "gpt-6-luna", days=30)
    labels = _labels(command_client, case_id, reader, role="READER")
    assert set(labels.values()) == {"RESTRICTED"}
    assert len(labels) == 3


def test_verdict_state_maps_the_validator_as_the_qualification_read_does(
    case: tuple[StoreConnection, UUID],
    deployed: None,
) -> None:
    """The one mapping both reads share: a current verdict is QUALIFIED and is
    returned; evidence nothing was signed over is UNQUALIFIED with none."""
    conn, _case_id = case
    _verdict(conn, "gpt-6-luna", days=30)
    signed = qualification_performed(
        provider=identity_of("gpt-6-luna"),
        model="gpt-6-luna",
        build_id=methodology_bundle().build_id,
        ordinal=list(model_choices()).index("gpt-6-luna") + 1,
    ).evidence
    now = datetime.now(UTC)
    state, verdict = verdict_state(conn, signed, now)
    assert (state, verdict is not None) == (QualificationState.QUALIFIED, True)
    unsigned = qualification_performed(model="never-signed").evidence
    assert verdict_state(conn, unsigned, now) == (QualificationState.UNQUALIFIED, None)
