"""Record format v2: the delivered authority and the full upstream lineage
(Phase 3 Task 3.3 slice 3.3c; `docs/DECISIONS.md` §45.1, §45.4, §45.5).

A record binds exactly the authority files its prompt carried, and the whole
accepted chain behind its direct inputs -- each ancestor's (artifact, record)
pair, read from the stored records rather than recomputed from the prompt. A
reader re-derives both from the pinned bundle and the accepted rows, so an
ancestor whose record moved after its consumer was accepted refuses before
another call and at the proof. A non-gate node the pinned route gives no direct
CP-0 input refuses before any attempt.
"""

from __future__ import annotations

import re
from dataclasses import replace
from uuid import UUID

import pytest
from canonical_fixtures import CATALOG, CanonicalCompletions
from conftest import tamper
from test_canonical_execution import LITE, _accept, _node, _reserved, _run
from test_canonical_runtime import _answers, _module_provider, _run_route
from test_execution_freshness import _counts, _Harness, harness
from test_loop_charges import REPORTED

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.deliverable.canonical import Revision, canonical_payload
from caos.graph.route import ResolvedRoute, resolve_route
from caos.methodology import canonical, invocation
from caos.methodology.bundle import DeliveredAuthority, delivered_authority_digest
from caos.methodology.handoff import (
    CanonicalRecord,
    LineageRef,
    _decoded_record,
    record_bytes,
)
from caos.qualification.proof import assert_orchestration_proof
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, connect, outcomes
from caos.store.events import lock_run

__all__ = ["harness"]

UNANCHORED = "unanchored"


@pytest.fixture
def route(request: pytest.FixtureRequest) -> ResolvedRoute:
    lite = resolve_route(CATALOG, *LITE)
    if getattr(request, "param", None) != UNANCHORED:
        return lite
    # A synthetic pin: CP-L10 keeps its node but loses its direct CP-0 edge.
    edges = tuple(e for e in lite.edges if (e.source, e.target) != ("CP-0", "CP-L10"))
    return replace(lite, edges=edges)


def _row(harness: _Harness, module_id: str) -> tuple[UUID, str, str]:
    row = harness.conn.execute(
        "SELECT attempt_id, artifact_sha256, record_sha256 FROM artifacts"
        " WHERE run_id = %s AND route_node_id = %s",
        (harness.run_id, _node(harness, module_id).route_node_id),
    ).fetchone()
    harness.conn.rollback()
    assert row is not None
    return UUID(str(row[0])), str(row[1]), str(row[2])


def _record(harness: _Harness, module_id: str) -> CanonicalRecord:
    return _decoded_record(harness.blobs.get(_row(harness, module_id)[2]))


def _link(harness: _Harness, module_id: str) -> LineageRef:
    _attempt, artifact, record = _row(harness, module_id)
    node = _node(harness, module_id)
    return LineageRef(node.route_node_id, module_id, artifact, record)


def _repoint(harness: _Harness, module_id: str, record: CanonicalRecord) -> None:
    """A privileged rewrite of one accepted row's record, under the run lock."""
    with connect(harness.url) as other:
        lock_run(other, harness.run_id)
        tamper(
            other,
            "UPDATE artifacts SET record_sha256 = %s"
            " WHERE run_id = %s AND route_node_id = %s",
            (
                harness.blobs.put(record_bytes(record)),
                harness.run_id,
                _node(harness, module_id).route_node_id,
            ),
        )
        other.commit()


_SECTION = re.compile(
    r"\n--- AUTHORITY (?P<tag>[0-9a-f]{16}) FILE (?P<name>\S+)"
    r" SHA256 [0-9a-f]{64} ---\n"
    r"(?P<body>.*?)\n--- END AUTHORITY (?P=tag) FILE (?P=name) ---\n",
    re.DOTALL,
)


def test_the_record_binds_exactly_the_delivered_authority(
    harness: _Harness,
) -> None:
    """§45.1/§45.4: the digest is over the files the prompt carried, byte for
    byte, and a set one file short is another digest."""
    completions = CanonicalCompletions(harness.source_id)
    attempt, result = _run(harness, "CP-0", completions)
    _accept(harness, attempt, result)
    [prompt] = completions.prompts
    carried = tuple(
        (m["name"], m["body"].encode("utf-8")) for m in _SECTION.finditer(prompt)
    )
    assert carried[0][0] == "SKILL.md" and any(
        n.startswith("../../") for n, _ in carried
    )
    authority = DeliveredAuthority("CP-0", harness.bundle.build_id, carried)
    record = _record(harness, "CP-0")
    assert record.delivered_authority_digest == delivered_authority_digest(authority)
    short = replace(authority, files=carried[:-1])
    assert record.delivered_authority_digest != delivered_authority_digest(short)
    assert record.lineage == ()


def test_full_lineage_survives_direct_only_context(harness: _Harness) -> None:
    """CP-5's prompt carries its direct inputs' Markdown; its record names the
    whole accepted chain, each pair as the store holds it."""
    answers = CanonicalCompletions(harness.source_id)
    assert _run_route(harness, _module_provider(harness, answers)) is None
    gate, screen = _link(harness, "CP-0"), _link(harness, "CP-L10")
    assert _record(harness, "CP-L10").lineage == (gate,)
    assert _record(harness, "CP-5").lineage == tuple(
        sorted((gate, screen), key=lambda link: link.route_node_id)
    )
    # Context stays direct: each upstream section is a direct input's handoff.
    final = answers.prompts[-1]
    assert final.count("\nsha256: ") == len(_record(harness, "CP-5").identity.upstream)


def test_the_pre_call_unit_reads_accepted_rows_once_and_records_once_each(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lineage costs no query per record: CP-5's whole context reads the
    accepted rows once, and each upstream record only for its own verification
    (the call-time narrowing, then `read_record`) -- never again for the
    lineage, which is read from the verified copy."""
    for module_id in ("CP-0", "CP-L10"):
        attempt, result = _run(harness, module_id, _answers(harness))
        _accept(harness, attempt, result)
    queries: list[UUID] = []
    real_rows = outcomes.accepted_rows

    def rows(
        conn: StoreConnection, run_id: UUID
    ) -> list[tuple[str, UUID, str, str | None]]:
        queries.append(run_id)
        return real_rows(conn, run_id)

    for module in (canonical, invocation):
        monkeypatch.setattr(module, "accepted_rows", rows)
    reads: list[str] = []
    real_get = BlobStore.get

    def get(blobs: BlobStore, sha: str) -> bytes:
        reads.append(sha)
        return real_get(blobs, sha)

    monkeypatch.setattr(BlobStore, "get", get)
    node = _node(harness, "CP-5")
    canonical.check_context(
        harness.conn,
        harness.bundle,
        harness.blobs,
        run_id=harness.run_id,
        route=harness.route,
        node=node,
        provider=_answers(harness),
    )
    harness.conn.rollback()
    assert queries == [harness.run_id]
    screen = _row(harness, "CP-L10")[2]
    assert reads.count(screen) == 2


def _moved_gate(harness: _Harness) -> CanonicalRecord:
    """CP-0's record with one rectangle shifted: bound to its Markdown and
    identity, projecting what the Markdown says -- only its anchoring moved,
    which no pre-call reader re-derives."""
    record = _record(harness, "CP-0")
    [citation] = record.citations
    box = replace(citation.bboxes[0], x0=citation.bboxes[0].x0 + 0.5)
    return replace(record, citations=(replace(citation, bboxes=(box,)),))


def test_a_changed_grandparent_prevents_acceptance(harness: _Harness) -> None:
    """CP-0's record rewritten after CP-L10 accepted: CP-L10's lineage no longer
    names the accepted pair, so CP-5 is refused before its call."""
    for module_id in ("CP-0", "CP-L10"):
        attempt, result = _run(harness, module_id, _answers(harness))
        _accept(harness, attempt, result)
    _repoint(harness, "CP-0", _moved_gate(harness))
    answers = _answers(harness)
    attempt = _reserved(harness, "CP-5")
    node = _node(harness, "CP-5")
    with pytest.raises(Refusal) as refused:
        _module_provider(harness, answers).execute(
            node.route_node_id, "CP-5", attempt_id=attempt
        )
    assert refused.value.__cause__ is None and refused.value.__context__ is None
    assert refused.value.code is RefusalCode.ARTIFACT_RECORD_MISMATCH
    assert answers.calls == 0
    assert _counts(harness) == (2, [REPORTED] * 2, 2, 3, 3)


def test_an_ancestor_rewritten_during_the_call_prevents_acceptance(
    harness: _Harness,
) -> None:
    for module_id in ("CP-0", "CP-L10"):
        attempt, result = _run(harness, module_id, _answers(harness))
        _accept(harness, attempt, result)
    moved = _moved_gate(harness)
    answers = _answers(harness, during=lambda: _repoint(harness, "CP-0", moved))
    attempt = _reserved(harness, "CP-5")
    node = _node(harness, "CP-5")
    with pytest.raises(Refusal) as refused:
        _module_provider(harness, answers).execute(
            node.route_node_id, "CP-5", attempt_id=attempt
        )
    assert refused.value.code is RefusalCode.ROUTE_IDENTITY_INVALID
    assert answers.calls == 1
    assert _counts(harness) == (3, [REPORTED] * 3, 2, 3, 3)


def _proof_and_payload(harness: _Harness) -> tuple[RefusalCode, RefusalCode]:
    codes = []
    title, revision = BoundaryText.of("Acme Holdings plc"), BoundaryText.of("rev-1")
    for read in (
        lambda: assert_orchestration_proof(
            harness.conn, harness.blobs, harness.bundle, run_id=harness.run_id
        ),
        lambda: canonical_payload(
            harness.conn,
            harness.blobs,
            harness.bundle,
            Revision(harness.case_id, harness.run_id, title, revision),
        ),
    ):
        with pytest.raises(Refusal) as refused:
            read()
        harness.conn.rollback()
        assert refused.value.__cause__ is None and refused.value.__context__ is None
        codes.append(refused.value.code)
    return codes[0], codes[1]


@pytest.mark.parametrize(
    "lineage", ["dropped", "stale-ancestor"], ids=["dropped", "stale-ancestor"]
)
def test_the_proof_and_deliverable_refuse_a_lineage_the_store_does_not_hold(
    harness: _Harness, lineage: str
) -> None:
    answers = CanonicalCompletions(harness.source_id)
    assert _run_route(harness, _module_provider(harness, answers)) is None
    screen = _record(harness, "CP-L10")
    [gate] = screen.lineage
    chain = () if lineage == "dropped" else (replace(gate, record_sha256="0" * 64),)
    _repoint(harness, "CP-L10", replace(screen, lineage=chain))
    mismatch = RefusalCode.ARTIFACT_RECORD_MISMATCH
    assert _proof_and_payload(harness) == (mismatch, mismatch)


def test_a_record_naming_another_delivered_authority_refuses(
    harness: _Harness,
) -> None:
    answers = CanonicalCompletions(harness.source_id)
    assert _run_route(harness, _module_provider(harness, answers)) is None
    screen = _record(harness, "CP-L10")
    _repoint(harness, "CP-L10", replace(screen, delivered_authority_digest="b" * 64))
    assert _proof_and_payload(harness) == (
        RefusalCode.ORCHESTRATION_BUILD_MOVED,
        RefusalCode.ARTIFACT_RECORD_MISMATCH,
    )


@pytest.mark.parametrize("route", [UNANCHORED], indirect=True)
def test_a_missing_cp0_anchor_refuses_on_a_non_direct_route(
    harness: _Harness,
) -> None:
    """§45.5: CP-L10's pin gives it no direct CP-0 input. It is refused before
    any attempt, reservation or call; CP-0 itself still runs."""
    answers = _answers(harness)
    provider = _module_provider(harness, answers)
    assert _run_route(harness, provider) is RefusalCode.ROUTE_IDENTITY_INVALID
    screen = _node(harness, "CP-L10").route_node_id
    row = harness.conn.execute(
        "SELECT count(*) FROM run_attempts WHERE route_node_id = %s", (screen,)
    ).fetchone()
    harness.conn.rollback()
    assert row == (0,)
    assert answers.calls == _counts(harness)[3]
