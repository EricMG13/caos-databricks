"""The deliverable bound to the canonical record (Task 3.1 slice d-4; §41, §42.4).

The payload is read from the store: both blobs, the record's binding, the
projections re-derived from the Markdown and every citation re-anchored in the
pinned evidence. Freezing binds each (artifact_sha256, record_sha256) pair, and
the page renders the Markdown escaped beside its statuses and limitations.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import CATALOG, CONTRACT, handoff_markdown, skill
from conftest import every_block, recorded_statements
from conftest import reserve_at as reserve
from test_execution_freshness import _Harness, harness
from test_loop_charges import ESTIMATE, MODEL, REPORTED

from caos import methodology
from caos.boundary_text import BoundaryText
from caos.deliverable.canonical import (
    Revision,
    canonical_payload,
    freeze_canonical,
    payload_bytes,
    verify_frozen,
)
from caos.deliverable.filing import sign_opinion
from caos.deliverable.package import build_package, verify_package
from caos.deliverable.render import RenderRefused, canonical_bound, render
from caos.deliverable.revisions import read_revision, save_revision
from caos.evidence.citations import Citation, verify_citations
from caos.graph.route import ResolvedRoute, resolve_route
from caos.methodology.bundle import (
    assemble_authority,
    authority_digest,
    delivered_authority,
    delivered_authority_digest,
)
from caos.methodology.canonical import accepted_projections
from caos.methodology.handoff import CanonicalRecord, record_bytes, validate_markdown
from caos.methodology.invocation import accepted_lineage, host_identity
from caos.methodology.vendor import authority_bundle_sha256
from caos.methodology.verification import AcceptedRow
from caos.refusals import Refusal, RefusalCode
from caos.store.members import Standing, grant
from caos.store.outcomes import CallOutcome, record_outcome
from caos.store.runs import Accepted, accept_attempt, start_attempt

__all__ = ["harness"]

APPROVER = Standing.APPROVER
LITE = resolve_route(CATALOG, "LITE_CREDIT_22", "LITE_EARNINGS_UPDATE")
QUOTE = "Total debt at 31 December 2026"
REVISION = BoundaryText.of("rev-canonical-001")
RESTRICTED = {
    "qa_status": "Restricted",
    "confidence_score": 55,
    "confidence_band": "Low",
    # A screening-only pathway never permits `Committee Ready` (§92); the
    # page still labels every LITE record a screen whatever status it wrote.
    "committee_status": "Requires More Work",
    "limitation_flags": ["Interim period only"],
}


@pytest.fixture
def route() -> ResolvedRoute:
    return LITE


def _accept(
    harness: _Harness, module_id: str, omit_soft: bool = False, /, **authored: object
) -> str:
    """Accept one canonical handoff with its host record, as c-5 will.

    `omit_soft` names only CP-0 upstream, as a call made before CP-L10 would.
    """
    conn, bundle = harness.conn, harness.bundle
    node = next(n for n in harness.route.nodes if n.module_id == module_id)
    attempt = start_attempt(conn, harness.run_id, node.route_node_id)
    identity = host_identity(
        conn, bundle, run_id=harness.run_id, route=LITE, node=node, attempt_id=attempt
    )
    if omit_soft:
        kept = tuple(ref for ref in identity.upstream if ref.module_id == "CP-0")
        identity = replace(identity, upstream=kept)
    markdown = handoff_markdown(
        identity, authored=authored, body_note=f"{QUOTE} <b>held</b> & noted."
    )
    gate = frozenset({"CP-L10", "CP-5"}) if module_id == "CP-0" else frozenset()
    projections = validate_markdown(
        CONTRACT,
        CATALOG,
        skill(module_id),
        markdown,
        identity=identity,
        gate_expects=gate,
    )
    anchored = verify_citations(
        conn,
        delivered=every_block(conn, harness.source_id),
        citations=[Citation(harness.source_id, 1, QUOTE)],
    )
    lineage = accepted_lineage(
        conn, harness.blobs, run_id=harness.run_id, upstream=identity.upstream
    )
    conn.rollback()
    record = CanonicalRecord(
        artifact_sha256=harness.blobs.put(markdown),
        adapter_version=methodology.CANONICAL_ADAPTER_VERSION,
        build_id=bundle.build_id,
        manifest_sha256=bundle.manifest_sha256,
        authority_bundle_sha256=authority_bundle_sha256(bundle),
        authority_digest=authority_digest(assemble_authority(bundle, module_id)),
        delivered_authority_digest=delivered_authority_digest(
            delivered_authority(bundle, module_id)
        ),
        identity=identity,
        lineage=lineage,
        projections=projections,
        citations=tuple(anchored),
    )
    reserve(conn, attempt, ESTIMATE)
    record_outcome(
        conn,
        attempt_id=attempt,
        outcome=CallOutcome(REPORTED, MODEL, f"g{attempt.hex}"),
    )
    accepted = Accepted(
        record.artifact_sha256,
        REPORTED,
        MODEL,
        f"g{attempt.hex}",
        record_sha256=harness.blobs.put(record_bytes(record)),
    )
    assert accept_attempt(conn, attempt_id=attempt, accepted=accepted)
    return node.route_node_id


@pytest.fixture
def lite(harness: _Harness) -> _Harness:
    _accept(harness, "CP-0")
    _accept(harness, "CP-L10", **RESTRICTED)
    _accept(harness, "CP-5")
    return harness


def _revision(harness: _Harness) -> Revision:
    title = BoundaryText.of("Acme Holdings plc")
    return Revision(harness.case_id, harness.run_id, title, REVISION)


def _payload(harness: _Harness) -> dict[str, Any]:
    return canonical_payload(
        harness.conn, harness.blobs, harness.bundle, _revision(harness)
    )


def _refused(harness: _Harness) -> RefusalCode:
    with pytest.raises(Refusal) as refused:
        _payload(harness)
    assert refused.value.__context__ is None and refused.value.__cause__ is None
    return refused.value.code


def _row(harness: _Harness, module_id: str) -> tuple[str, str]:
    node = next(n for n in harness.route.nodes if n.module_id == module_id)
    row = harness.conn.execute(
        "SELECT artifact_sha256, record_sha256 FROM artifacts"
        " WHERE run_id = %s AND route_node_id = %s",
        (harness.run_id, node.route_node_id),
    ).fetchone()
    harness.conn.rollback()
    assert row is not None
    return str(row[0]), str(row[1])


def _rewrite(harness: _Harness, module_id: str, **changes: object) -> None:
    """Point the artifact row at a well-formed record with `changes` applied."""
    artifact, record_sha = _row(harness, module_id)
    stored = harness.blobs.get(record_sha)
    document = json.loads(stored)
    for path, value in changes.items():
        *parents, leaf = path.split("__")
        target = document
        for key in parents:
            target = target[int(key)] if key.isdigit() else target[key]
        target[leaf] = value
    moved = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    harness.conn.execute(
        "UPDATE artifacts SET record_sha256 = %s WHERE artifact_sha256 = %s",
        (harness.blobs.put(moved), artifact),
    )
    harness.conn.commit()


def test_the_payload_is_read_from_the_store_and_round_trips(lite: _Harness) -> None:
    payload = _payload(lite)
    artifacts = payload["artifacts"]
    assert [a["route_node_id"] for a in artifacts] == [
        n.route_node_id for n in LITE.nodes
    ]
    for artifact, module in zip(artifacts, ("CP-0", "CP-L10", "CP-5"), strict=True):
        assert (artifact["artifact_sha256"], artifact["record_sha256"]) == _row(
            lite, module
        )
        markdown, record = artifact["markdown"], artifact["record"]
        assert (
            hashlib.sha256(markdown.encode()).hexdigest() == artifact["artifact_sha256"]
        )
        assert hashlib.sha256(record.encode()).hexdigest() == artifact["record_sha256"]
    assert payload_bytes(_payload(lite)) == payload_bytes(payload)
    assert lite.conn.info.transaction_status.name == "IDLE"


def test_freezing_reads_each_source_page_once_and_verifies_authority_bytes(
    lite: _Harness,
) -> None:
    """Three records quoting one page of one source: one `TokenIndex` for the
    whole payload reads that page, its digest and its line numbering once, not
    once per node -- the proof's shape (`test_canonical_proof`), which this
    reader was never given."""
    with recorded_statements(lite.conn) as statements:
        assert len(_payload(lite)["artifacts"]) == len(LITE.nodes)
    reads = ("FROM source_tokens AS tokens", "SELECT DISTINCT line_id")
    assert [sum(read in s for s in statements) for read in reads] == [1, 1]


@pytest.mark.parametrize("blob", [0, 1], ids=["markdown", "record"])
def test_a_changed_blob_refuses(lite: _Harness, blob: int) -> None:
    digest = _row(lite, "CP-L10")[blob]
    stored = lite.blobs.get(digest)
    lite.blobs.path_of(digest).write_bytes(stored.replace(b"Interim", b"Interin"))
    assert stored != lite.blobs.path_of(digest).read_bytes()
    assert _refused(lite) is RefusalCode.ARTIFACT_RECORD_MISMATCH


@pytest.mark.parametrize(
    "change",
    [
        {"citations__0__bboxes__0__x0": 0.5},
        {"projections__qa_status": "Passed"},
        {"projections__decision_scope": "COMMITTEE"},
        {"authority_digest": "0" * 64},
        {"identity__upstream": []},
    ],
)
def test_a_record_fact_the_host_does_not_rederive_refuses(
    lite: _Harness, change: dict[str, object]
) -> None:
    _rewrite(lite, "CP-L10", **change)
    assert _refused(lite) is RefusalCode.ARTIFACT_RECORD_MISMATCH


def test_a_citation_that_no_longer_anchors_refuses_with_its_code(
    lite: _Harness,
) -> None:
    _rewrite(lite, "CP-5", citations__0__page=2)
    assert _refused(lite) is RefusalCode.CITATION_NOT_LOCATED


def test_a_soft_input_accepted_after_the_call_does_not_break_the_record(
    harness: _Harness,
) -> None:
    # CP-L10 -> CP-5 is ADVISORY: CP-5 called first names no CP-L10.
    _accept(harness, "CP-0")
    _accept(harness, "CP-5")
    _accept(harness, "CP-L10", **RESTRICTED)
    record = json.loads(_payload(harness)["artifacts"][2]["record"])
    assert [ref["module_id"] for ref in record["identity"]["upstream"]] == ["CP-0"]
    # The runtime's reader applies the same call-time rule and accepts it too.
    final = next(n.route_node_id for n in harness.route.nodes if n.module_id == "CP-5")
    row = harness.conn.execute(
        "SELECT attempt_id, artifact_sha256, record_sha256 FROM artifacts"
        " WHERE run_id = %s AND route_node_id = %s",
        (harness.run_id, final),
    ).fetchone()
    assert row is not None
    projections = accepted_projections(
        harness.conn,
        harness.blobs,
        harness.bundle,
        harness.route,
        AcceptedRow(
            run_id=harness.run_id,
            route_node_id=final,
            attempt_id=row[0],
            artifact_sha256=row[1],
            record_sha256=row[2],
        ),
    )
    assert projections.qa_status == record["projections"]["qa_status"]
    harness.conn.rollback()


def test_an_incomplete_run_has_no_canonical_payload(harness: _Harness) -> None:
    _accept(harness, "CP-0")
    assert _refused(harness) is RefusalCode.DELIVERABLE_PAYLOAD_INVALID


def _frozen(harness: _Harness) -> bytes:
    saved = save_revision(
        harness.conn,
        harness.blobs,
        harness.bundle,
        case_id=harness.case_id,
        run_id=harness.run_id,
        actor_id=harness.approver,
        narrative=[],
    )
    data = payload_bytes(
        read_revision(
            harness.conn, harness.blobs, case_id=harness.case_id, revision_id=saved
        )
    )
    harness.conn.rollback()
    # FP-33: the signer must be independent of the actor who saved the
    # narrative (`harness.approver`), so a fresh approver signs here.
    signer = uuid4()
    grant(
        harness.conn,
        case_id=harness.case_id,
        user_id=signer,
        standing=Standing.APPROVER,
    )
    harness.conn.commit()
    sign_opinion(
        harness.conn,
        case_id=harness.case_id,
        actor_id=signer,
        revision_id=saved,
    )
    freezer = uuid4()
    grant(harness.conn, case_id=harness.case_id, user_id=freezer, standing=APPROVER)
    harness.conn.commit()
    revision = replace(_revision(harness), revision_id=BoundaryText.of(str(saved)))
    digest = freeze_canonical(
        harness.conn, harness.blobs, harness.bundle, revision, actor_id=freezer
    )
    assert digest == hashlib.sha256(data).hexdigest()
    return data


def _verify(harness: _Harness, data: bytes) -> None:
    verify_frozen(
        harness.conn,
        harness.blobs,
        harness.bundle,
        case_id=harness.case_id,
        revision_id=UUID(json.loads(data)["revision_id"]),
        payload=data,
    )


def test_freezing_binds_both_hashes_and_verification_refuses_either_moving(
    lite: _Harness,
) -> None:
    data = _frozen(lite)
    _verify(lite, data)
    artifact, record = _row(lite, "CP-L10")
    decoded = json.loads(data)
    assert [artifact, record] in [
        [a["artifact_sha256"], a["record_sha256"]] for a in decoded["artifacts"]
    ]
    with pytest.raises(Refusal) as edited:
        _verify(lite, data.replace(record.encode(), b"0" * 64))
    assert edited.value.code is RefusalCode.DELIVERABLE_MOVED_SINCE_SIGNING

    # The stored record moves: the frozen pair no longer re-derives.
    _rewrite(lite, "CP-L10", projections__confidence_score=56)
    with pytest.raises(Refusal) as record_moved:
        _verify(lite, data)
    assert record_moved.value.code is RefusalCode.ARTIFACT_RECORD_MISMATCH
    lite.conn.execute(
        "UPDATE artifacts SET record_sha256 = %s WHERE artifact_sha256 = %s",
        (record, artifact),
    )
    lite.conn.commit()
    _verify(lite, data)
    # The stored artifact moves.
    lite.conn.execute(
        "UPDATE artifacts SET artifact_sha256 = %s WHERE artifact_sha256 = %s",
        (lite.blobs.put(b"another handoff"), artifact),
    )
    lite.conn.commit()
    with pytest.raises(Refusal) as artifact_moved:
        _verify(lite, data)
    assert artifact_moved.value.code is RefusalCode.ARTIFACT_RECORD_MISMATCH


def test_a_package_refuses_a_pair_that_does_not_hash_to_its_handoff(
    lite: _Harness,
) -> None:
    payload = _payload(lite)
    data = payload_bytes(payload)
    receipt = {
        "payload_sha256": hashlib.sha256(data).hexdigest(),
        "signed_by": "a",
        "frozen_by": "b",
        "filed_by": "c",
        **{key: payload[key] for key in ("case_id", "run_id", "revision_id")},
    }
    good = build_package(data, json.dumps(receipt).encode(), render(payload))
    assert verify_package(good).verified
    artifacts = payload["artifacts"]
    artifacts[1] = {**artifacts[1], "markdown": artifacts[1]["markdown"] + "\n"}
    moved = payload_bytes(payload)
    receipt["payload_sha256"] = hashlib.sha256(moved).hexdigest()
    result = verify_package(build_package(moved, json.dumps(receipt).encode(), b""))
    assert not result.verified
    assert result.reason == "a handoff does not hash to the pair the payload binds"


def test_the_page_keeps_limitations_labels_screens_and_escapes_model_text(
    lite: _Harness,
) -> None:
    payload = _payload(lite)
    page = render(payload)
    assert page == render(json.loads(payload_bytes(payload)))
    text = page.decode()
    assert "QA status: Restricted" in text
    assert "<li>Interim period only</li>" in text
    # Every LITE record is a screen, whatever committee status it wrote.
    assert text.count("SCREENING ONLY: a screen, not committee clearance") == 3
    assert "Committee status as written: Requires More Work" in text
    assert "<b>held</b>" not in text and "&lt;b&gt;held&lt;/b&gt; &amp; noted." in text
    assert f"<blockquote>{QUOTE}</blockquote>" in text
    assert "page 1" in text
    artifacts = payload["artifacts"]
    screened = {
        **artifacts[0],
        "record": artifacts[0]["record"].replace(
            '"decision_scope":"SCREENING_ONLY"', '"decision_scope":"COMMITTEE"'
        ),
    }
    assert canonical_bound(artifacts[0]) and not canonical_bound(screened)
    unbound = {**payload, "artifacts": [screened]}
    with pytest.raises(RenderRefused) as refused:
        render(unbound)
    assert refused.value.code == "DELIVERABLE_PAYLOAD_INVALID"


def test_the_deliverable_labels_source_fact_analysis_and_no_host_calculation(
    lite: _Harness,
) -> None:
    """§45.6: host-verified citations are source facts, the model's Markdown is
    analysis the host has not verified, and the host performed no calculation."""
    text = render(_payload(lite)).decode()
    section = text.split("<h2>", 2)[1]
    facts = section.index("<h3>Source facts (host-verified citations)</h3>")
    analysis = section.index("<h3>Analysis (model-authored, not host-verified)</h3>")
    calculation = section.index(
        "<h3>Deterministic calculations</h3>\n"
        "<p>None performed by the host on this route.</p>"
    )
    assert facts < analysis < calculation
    assert "<blockquote>" in section[facts:analysis]
    assert "<blockquote>" not in section[analysis:]
    # The model's Markdown is rendered as the deliverable's closed element set
    # -- headings and registers, with the host-owned front matter shown whole --
    # and none of it appears above the label that says who authored it.
    analysed = section[analysis:calculation]
    assert '<pre class="front">' in analysed and "<table>" in analysed
    assert '<h5 data-level="2">Audit Summary</h5>' in analysed
    assert "<pre" not in section[:analysis]
