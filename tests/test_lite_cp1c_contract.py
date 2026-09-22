"""CP-1C under a LITE identity: the FULL module's contract on
`LITE_CREDIT_22 / LITE_RELATIVE_VALUE` (Completion Phase 9 Task 9.2).

CP-1C "remains a FULL run when the run profile is `LITE_CREDIT_22`" and
retains `NAMED_LITE_OBJECT_ACCEPTED` for `lite_financial_change_screen`
(its verified `SKILL.md`). Nothing about its registers changes with the
profile; what changes is the scope the host projects beside its status
(`SCREENING_ONLY`, from the catalog pathway) and the upstream it may read:
CP-0's and CP-L10's accepted records, CP-L10's under the edge's catalog
`allowed_use: SCREENING_ONLY`.

The five owner-contract tests of `tests/test_owner_contracts.py` are repeated
here for both consumers of this route under its own identity, and two tests
name the route's boundary: CP-1C accepts the named object and keeps the
screening scope, and CP-1C is held -- never attempted, reserved or called --
until CP-L10 is accepted. Every provider is deterministic.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest
from canonical_fixtures import (
    BUNDLE,
    CATALOG,
    CONTRACT,
    fields_from_prompt,
    skill,
    upstream_ref,
)
from canonical_route_fixtures import LIMITATION, PACK, HandoffKnobs
from lite_relative_value_fixtures import (
    CONSUMERS,
    LITE_LIMITATION,
    LITE_QUOTES,
    ROUTE,
    SELECTION,
    LiteRelativeValueCompletions,
    lite_identity,
    lite_markdown,
)
from test_canonical_runtime import _module_provider, _run_route, _status
from test_execution_freshness import _Harness
from test_relative_value_route import harness

from caos.graph.route import (
    NodeResult,
    NodeState,
    ResolvedRoute,
    lite_object_unmet,
    node_states,
    resolve_route,
)
from caos.methodology.handoff import (
    HostIdentity,
    invocation_fields,
    read_record,
    validate_markdown,
)
from caos.methodology.invocation import allowed_uses, host_identity, named_objects
from caos.refusals import Refusal, RefusalCode
from caos.store import connect

__all__ = ["harness"]

SCREEN = "lite_financial_change_screen"


@pytest.fixture
def route() -> ResolvedRoute:
    """The harness pins this route (overrides the FULL route's fixture)."""
    return resolve_route(CATALOG, *SELECTION)


def _identity(module: str) -> HostIdentity:
    refs = tuple(
        upstream_ref(lite_identity(e.source), lite_markdown(lite_identity(e.source)))
        for e in ROUTE.edges
        if e.target == module
    )
    return lite_identity(module, refs)


def _gate_expects(module: str) -> frozenset[str]:
    return frozenset(CONSUMERS) if module == "CP-0" else frozenset()


def _modules(answers: LiteRelativeValueCompletions) -> list[str]:
    return [str(fields_from_prompt(p)["module_id"]) for p in answers.prompts]


def _completed(harness: _Harness) -> LiteRelativeValueCompletions:
    answers = LiteRelativeValueCompletions(harness.source_id)
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _status(harness) == "COMPLETE"
    return answers


def _attempts_at(harness: _Harness, module: str) -> tuple[int, int]:
    """How many attempts and reservations this node has: the spend it caused."""
    node = next(n for n in ROUTE.nodes if n.module_id == module)
    with connect(harness.url) as observer:
        row = observer.execute(
            "SELECT count(*), count(r.attempt_id) FROM run_attempts t"
            " LEFT JOIN budget_reservations r USING (attempt_id)"
            " WHERE t.run_id = %s AND t.route_node_id = %s",
            (harness.run_id, node.route_node_id),
        ).fetchone()
    assert row is not None
    return int(row[0]), int(row[1])


@pytest.mark.parametrize("module", CONSUMERS)
def test_lite_contract_validates_identifies_projects_and_anchors(
    harness: _Harness, module: str
) -> None:
    _completed(harness)
    node = next(n for n in ROUTE.nodes if n.module_id == module)
    row = harness.conn.execute(
        "SELECT attempt_id, artifact_sha256, record_sha256 FROM artifacts"
        " WHERE run_id=%s AND route_node_id=%s",
        (harness.run_id, node.route_node_id),
    ).fetchone()
    assert row is not None
    attempt, artifact, record_sha = row
    ident = host_identity(
        harness.conn,
        BUNDLE,
        run_id=harness.run_id,
        route=ROUTE,
        node=node,
        attempt_id=attempt,
    )
    record = read_record(
        harness.blobs,
        artifact_sha256=artifact,
        record_sha256=record_sha,
        expected=ident,
    )
    projection = validate_markdown(
        CONTRACT,
        CATALOG,
        skill(module),
        harness.blobs.get(artifact),
        identity=ident,
        gate_expects=frozenset(),
    )
    assert record.projections == projection
    assert projection.module_id == module
    assert projection.decision_scope == "SCREENING_ONLY"
    assert (ident.profile_id, ident.selection_id) == SELECTION
    assert {r.module_id for r in ident.upstream} == {
        e.source for e in ROUTE.edges if e.target == module
    }
    [citation] = record.citations
    assert citation.matched_text == LITE_QUOTES[module]
    assert citation.document_sha256 == hashlib.sha256(PACK).hexdigest()
    assert citation.bboxes
    harness.conn.rollback()


@pytest.mark.parametrize("module", CONSUMERS)
def test_lite_contract_refuses_a_missing_register(module: str) -> None:
    ident = _identity(module)
    first = next(
        iter(
            CONTRACT.completeness_check.load_contract(skill(module).decode(), module)[
                "registers"
            ]
        )
    )
    with pytest.raises(Refusal) as refused:
        validate_markdown(
            CONTRACT,
            CATALOG,
            skill(module),
            lite_markdown(ident, HandoffKnobs(omit_register=first)),
            identity=ident,
            gate_expects=_gate_expects(module),
        )
    assert refused.value.code is RefusalCode.HANDOFF_INCOMPLETE


@pytest.mark.parametrize("module", CONSUMERS)
def test_lite_contract_refuses_a_wrong_upstream(module: str) -> None:
    ident = _identity(module)
    wrong = replace(
        ident,
        upstream=(replace(ident.upstream[0], sha256="f" * 64), *ident.upstream[1:]),
    )
    with pytest.raises(Refusal) as refused:
        validate_markdown(
            CONTRACT,
            CATALOG,
            skill(module),
            lite_markdown(
                ident, HandoffKnobs(fields=invocation_fields(CONTRACT, wrong))
            ),
            identity=ident,
            gate_expects=frozenset(),
        )
    assert refused.value.code is RefusalCode.HANDOFF_IDENTITY_MISMATCH


@pytest.mark.parametrize("module", CONSUMERS)
def test_lite_contract_refuses_an_unanchored_quote(
    harness: _Harness, module: str
) -> None:
    answers = LiteRelativeValueCompletions(
        harness.source_id,
        quotes_by_module={module: LITE_QUOTES[module] + " fabricated"},
    )
    assert (
        _run_route(harness, _module_provider(harness, answers))
        is RefusalCode.CITATION_NOT_LOCATED
    )
    node = next(n for n in ROUTE.nodes if n.module_id == module)
    assert harness.conn.execute(
        "SELECT count(*) FROM artifacts WHERE route_node_id=%s", (node.route_node_id,)
    ).fetchone() == (0,)
    harness.conn.rollback()


@pytest.mark.parametrize("module", CONSUMERS)
def test_each_restricted_lite_consumer_retains_its_limitations(module: str) -> None:
    ident = _identity(module)
    projection = validate_markdown(
        CONTRACT,
        CATALOG,
        skill(module),
        lite_markdown(ident, HandoffKnobs(qa_status="Restricted")),
        identity=ident,
        gate_expects=frozenset(),
    )
    assert projection.qa_status == "Restricted"
    assert projection.decision_scope == "SCREENING_ONLY"
    assert projection.limitation_flags == (
        (LIMITATION,) if module == "CP-1C" else (LITE_LIMITATION,)
    )


def test_a_lite_cp1c_may_not_say_committee_ready() -> None:
    """The screening scope is the bundle's rule, not only a label (§92): a
    CP-1C under this pathway claiming `Committee Ready` is refused."""
    ident = _identity("CP-1C")
    text = lite_markdown(ident).replace(
        b'committee_status: "Draft Only"', b'committee_status: "Committee Ready"'
    )
    assert b"Committee Ready" in text
    with pytest.raises(Refusal) as refused:
        validate_markdown(
            CONTRACT,
            CATALOG,
            skill("CP-1C"),
            text,
            identity=ident,
            gate_expects=frozenset(),
        )
    assert refused.value.code is RefusalCode.HANDOFF_MALFORMED


def test_cp1c_under_lite_accepts_the_named_object_and_keeps_screening_scope(
    harness: _Harness,
) -> None:
    """CP-L10's owned object releases CP-1C, which runs last, reads both
    upstream records -- CP-L10's under `SCREENING_ONLY` -- and is recorded as a
    screen, whatever its FULL contract."""
    named = named_objects(BUNDLE, ROUTE)
    assert named.owned == {"CP-L10": SCREEN}
    assert named.accepted_ids == {"CP-1C": frozenset({SCREEN})}
    assert named.carried[("CP-L10", "CP-1C")] == SCREEN
    assert allowed_uses(CATALOG, ROUTE, "CP-1C") == {
        "CP-0": "NOT_DECLARED",
        "CP-L10": "SCREENING_ONLY",
    }

    answers = _completed(harness)
    cp1c_prompt = answers.prompts[-1]
    assert _modules(answers) == [n.module_id for n in ROUTE.nodes]
    # Both upstream handoffs reach CP-1C's prompt byte for byte.
    assert answers.answers[0].decode() in cp1c_prompt
    assert answers.answers[1].decode() in cp1c_prompt
    assert "SCREENING_ONLY" in cp1c_prompt

    node = ROUTE.nodes[-1]
    assert node.module_id == "CP-1C"
    row = harness.conn.execute(
        "SELECT attempt_id, artifact_sha256, record_sha256 FROM artifacts"
        " WHERE run_id=%s AND route_node_id=%s",
        (harness.run_id, node.route_node_id),
    ).fetchone()
    assert row is not None
    ident = host_identity(
        harness.conn,
        BUNDLE,
        run_id=harness.run_id,
        route=ROUTE,
        node=node,
        attempt_id=row[0],
    )
    record = read_record(
        harness.blobs, artifact_sha256=row[1], record_sha256=row[2], expected=ident
    )
    harness.conn.rollback()
    assert record.projections.decision_scope == "SCREENING_ONLY"
    assert record.projections.committee_status != "Committee Ready"
    assert {r.module_id for r in ident.upstream} == {"CP-0", "CP-L10"}


def test_cp1c_under_lite_is_held_until_cp_l10_is_accepted(harness: _Harness) -> None:
    """A CP-L10 whose answer is refused leaves CP-1C behind its boundary:
    no attempt, no reservation, no call -- and the edge that would release it
    is the one CP-L10 carries the object on."""
    answers = LiteRelativeValueCompletions(
        harness.source_id,
        quotes_by_module={"CP-L10": LITE_QUOTES["CP-L10"] + " fabricated"},
    )
    assert (
        _run_route(harness, _module_provider(harness, answers))
        is RefusalCode.CITATION_NOT_LOCATED
    )
    assert _modules(answers) == ["CP-0", "CP-L10"]
    assert _attempts_at(harness, "CP-1C") == (0, 0)

    named = named_objects(BUNDLE, ROUTE)
    cp0 = ROUTE.nodes[0].route_node_id
    cp1c = ROUTE.nodes[-1].route_node_id
    only_cp0 = {cp0: NodeResult()}
    assert node_states(ROUTE, only_cp0, named)[cp1c] is NodeState.BLOCKED
    [edge] = lite_object_unmet(ROUTE, only_cp0, "CP-1C", named)
    assert (edge.source, edge.target) == ("CP-L10", "CP-1C")
    # Accepting CP-L10 is exactly what releases it.
    both = {**only_cp0, ROUTE.nodes[1].route_node_id: NodeResult()}
    assert node_states(ROUTE, both, named)[cp1c] is NodeState.RUNNABLE
    assert lite_object_unmet(ROUTE, both, "CP-1C", named) == ()
