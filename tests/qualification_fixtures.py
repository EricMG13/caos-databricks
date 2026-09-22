"""Small, typed performed qualification evidence for store/API regressions."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID, uuid4

from caos.qualification.harness import Performed, PerformedSet, PreparedCase
from caos.qualification.matrix import Matrix, MatrixRow
from caos.qualification.proof import OrchestrationProof
from caos.qualification.store import PerformedEvidence, performed_evidence
from caos.store import RunStatus
from caos.store.run_inputs import RunInput


def qualification_performed(*, blocked_label: str | None = None) -> PerformedEvidence:
    """A signable snapshot of one case, or of two when `blocked_label` is given.

    The second case is one whose declared refusal was met: its run ends BLOCKED
    having accepted nothing, which `PerformedEvidence.complete` deliberately
    allows. It exists so a test can show that such a case does not make the set
    unsignable -- the shape the Completion Phase 8 confidence review found
    refused as a wrong binding.
    """
    run_id = UUID("00000000-0000-0000-0000-000000000001")
    prepared = PreparedCase(
        "case",
        RunInput(
            run_id=run_id,
            case_id=UUID("00000000-0000-0000-0000-000000000002"),
            source_version=1,
            source_fingerprint="c" * 64,
            route_digest="d" * 64,
            build_id="b" * 64,
            manifest_sha256="e" * 64,
            adapter_version="canonical-markdown-v3",
            research_json=None,
            input_fingerprint="f" * 64,
        ),
        "a" * 64,
        "openrouter/google-ai-studio/high/65536",
        "google/gemini-3.8-flash",
    )
    result = PerformedSet(
        performed=(
            Performed(
                "case",
                run_id,
                RunStatus.COMPLETE,
                None,
                OrchestrationProof(
                    run_id=run_id,
                    route_digest="d" * 64,
                    build_id="b" * 64,
                    artifacts=1,
                    citations=1,
                    anchored=frozenset({("CP-0", "c" * 64, "quoted text")}),
                ),
                None,
                (),
            ),
        ),
        matrix=Matrix(
            qualification_set_sha256="a" * 64,
            build_id="b" * 64,
            rows=(
                MatrixRow(
                    case_label="case",
                    proven=True,
                    refusal=None,
                    met=(),
                    missed=(),
                    forecast_met=None,
                    expected_refusal_met=None,
                ),
            ),
        ),
    )
    if blocked_label is None:
        return performed_evidence(prepared=(prepared,), performed=result)

    blocked_run = UUID("00000000-0000-0000-0000-000000000011")
    blocked_prepared = PreparedCase(
        blocked_label,
        replace(
            prepared.input,
            run_id=blocked_run,
            case_id=UUID("00000000-0000-0000-0000-000000000012"),
        ),
        prepared.qualification_set_sha256,
        prepared.provider,
        prepared.model,
    )
    blocked = Performed(
        blocked_label,
        blocked_run,
        RunStatus.BLOCKED,
        None,
        OrchestrationProof(
            run_id=blocked_run,
            route_digest="d" * 64,
            build_id="b" * 64,
            artifacts=0,
            citations=0,
            anchored=frozenset(),
        ),
        None,
        (),
    )
    matrix = result.matrix
    assert matrix is not None
    return performed_evidence(
        prepared=(prepared, blocked_prepared),
        performed=replace(
            result,
            performed=(*result.performed, blocked),
            matrix=replace(
                matrix,
                rows=(
                    *matrix.rows,
                    MatrixRow(
                        case_label=blocked_label,
                        # `matrix._row` sets `proven = refusal is None`, so
                        # `proven=False` with no refusal is a row the matrix
                        # cannot produce. The Completion Phase 8 adversarial
                        # audit found the fixture asserting a shape the code
                        # forbids, which is how a suite starts proving something
                        # other than what it claims.
                        proven=True,
                        refusal=None,
                        met=(),
                        missed=(),
                        forecast_met=None,
                        expected_refusal_met=True,
                    ),
                ),
            ),
        ),
    )


def record_runs(
    conn: object,
    performed: PerformedEvidence,
    *,
    model: str | None = None,
    outcome: bool = True,
    accepted_nothing: str | None = None,
) -> None:
    """The case, run, accepted attempt and recorded call behind a snapshot.

    `record_verdict` reads the models the runs actually called, so a snapshot
    a reviewer may sign needs those rows to exist. `model` records a model
    other than the one the harness configured; `outcome=False` accepts the
    artifact and records no call at all; `accepted_nothing` names the case whose
    run bills a call and accepts no artifact, which is what a run that ends
    BLOCKED at its first node leaves behind.
    """
    execute = conn.execute  # type: ignore[attr-defined]
    for case in performed.prepared:
        pin = case.input
        execute(
            "INSERT INTO cases (case_id,title) VALUES (%s,%s)"
            " ON CONFLICT (case_id) DO NOTHING",
            (pin.case_id, case.case_label),
        )
        execute(
            "INSERT INTO runs (run_id,case_id,status,budget_ceiling)"
            " VALUES (%s,%s,'COMPLETE',1) ON CONFLICT (run_id) DO NOTHING",
            (pin.run_id, pin.case_id),
        )
        attempt = uuid4()
        execute(
            "INSERT INTO run_attempts (attempt_id,run_id,route_node_id)"
            " VALUES (%s,%s,'CP-0')",
            (attempt, pin.run_id),
        )
        if case.case_label != accepted_nothing:
            execute(
                "INSERT INTO artifacts (attempt_id,run_id,case_id,artifact_sha256,"
                "route_node_id,model,generation_id)"
                " VALUES (%s,%s,%s,%s,'CP-0',%s,%s)",
                (
                    attempt,
                    pin.run_id,
                    pin.case_id,
                    "1" * 64,
                    model or case.model,
                    "gen-1",
                ),
            )
        if outcome:
            execute(
                "INSERT INTO call_outcomes (attempt_id,run_id,model) VALUES (%s,%s,%s)",
                (attempt, pin.run_id, model or case.model),
            )
