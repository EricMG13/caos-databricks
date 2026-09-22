"""Each new owner meets the same canonical acceptance/refusal boundary."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest
from canonical_fixtures import BUNDLE, CATALOG, CONTRACT, skill, upstream_ref
from canonical_route_fixtures import (
    LIMITATION,
    OWNERS,
    PACK,
    QUOTES,
    ROUTE,
    HandoffKnobs,
    RouteCompletions,
    canonical_markdown,
    route_identity,
)
from test_canonical_runtime import _module_provider, _run_route
from test_execution_freshness import _Harness
from test_relative_value_route import harness, route, run_completed

from caos.methodology.handoff import (
    HostIdentity,
    invocation_fields,
    read_record,
    validate_markdown,
)
from caos.methodology.invocation import host_identity
from caos.refusals import Refusal, RefusalCode

__all__ = ["harness", "route"]


def _identity(module: str) -> HostIdentity:
    refs = tuple(
        upstream_ref(
            route_identity(e.source), canonical_markdown(route_identity(e.source))
        )
        for e in ROUTE.edges
        if e.target == module
    )
    return route_identity(module, refs)


@pytest.mark.parametrize("module", OWNERS)
def test_cp1_contract_validates_identifies_projects_and_anchors(
    harness: _Harness, module: str
) -> None:
    run_completed(harness)
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
    assert projection.module_id == module and projection.decision_scope == "FULL"
    assert {r.module_id for r in ident.upstream} == {
        e.source for e in ROUTE.edges if e.target == module
    }
    [citation] = record.citations
    assert citation.matched_text == QUOTES[module]
    assert citation.document_sha256 == hashlib.sha256(PACK).hexdigest()
    assert citation.bboxes
    harness.conn.rollback()


@pytest.mark.parametrize("module", OWNERS)
def test_cp1_contract_refuses_a_missing_register(module: str) -> None:
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
            canonical_markdown(ident, HandoffKnobs(omit_register=first)),
            identity=ident,
            gate_expects=frozenset(),
        )
    assert refused.value.code is RefusalCode.HANDOFF_INCOMPLETE


@pytest.mark.parametrize("module", OWNERS)
def test_cp1_contract_refuses_a_wrong_upstream(module: str) -> None:
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
            canonical_markdown(
                ident, HandoffKnobs(fields=invocation_fields(CONTRACT, wrong))
            ),
            identity=ident,
            gate_expects=frozenset(),
        )
    assert refused.value.code is RefusalCode.HANDOFF_IDENTITY_MISMATCH


@pytest.mark.parametrize("module", OWNERS)
def test_cp1_contract_refuses_an_unanchored_quote(
    harness: _Harness, module: str
) -> None:
    answers = RouteCompletions(
        harness.source_id, quotes_by_module={module: QUOTES[module] + " fabricated"}
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


@pytest.mark.parametrize("module", OWNERS)
def test_each_restricted_owner_retains_its_limitations(module: str) -> None:
    ident = _identity(module)
    projection = validate_markdown(
        CONTRACT,
        CATALOG,
        skill(module),
        canonical_markdown(ident, HandoffKnobs(qa_status="Restricted")),
        identity=ident,
        gate_expects=frozenset(),
    )
    assert projection.qa_status == "Restricted"
    assert projection.limitation_flags == (LIMITATION,)
