"""The orchestration proof over canonical artifacts (Task 3.1 slice d-2; §42.4).

A LITE run completed through `run_route` proves; then each thing the proof
re-derives is moved under it -- a blob, the binding, a projection, a pinned
source, a rectangle, the build -- and it refuses with the claim that failed and
no text in the exception chain.
"""

from __future__ import annotations

import ast
import json
import shutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import CanonicalCompletions
from conftest import (
    approve_run,
    every_block,
    priced,
    recorded_statements,
    route_fault,
)
from test_canonical_execution import _node, harness, route
from test_deliverable_canonical import RESTRICTED, _accept
from test_execution_freshness import _guard_disabled, _Harness
from test_loop_charges import ESTIMATE, REPORT
from tracked import tracked_python

from caos import methodology
from caos.boundary_text import BoundaryText
from caos.deliverable.canonical import Revision, canonical_payload
from caos.evidence.citations import Citation, verify_citations
from caos.evidence.ingest import Document, admit_pack
from caos.graph.route import route_digest
from caos.graph.runtime import Execution, run_route
from caos.methodology.bundle import MANIFEST_NAME, Bundle
from caos.methodology.handoff import CanonicalRecord, _decoded_record, record_bytes
from caos.methodology.invocation import call_time_identity, host_identity
from caos.methodology.runner import ModuleProvider
from caos.qualification import Assurance
from caos.qualification.proof import OrchestrationProof, assert_orchestration_proof
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.gates import withdraw_source
from caos.store.members import Standing, grant
from caos.store.routes import _canonical
from caos.store.runs import start_run
from caos.store.source_sets import pinned_live_sources

__all__ = ["harness", "route"]

REPO = Path(__file__).resolve().parents[1]
MISMATCH = RefusalCode.ARTIFACT_RECORD_MISMATCH


@contextmanager
def _token_fault(conn: StoreConnection) -> Iterator[None]:
    """Privileged fault setup; transactional DDL restores the guard on failure."""
    assert conn.info.dbname.startswith("caos_test_")
    with conn.transaction():
        conn.execute("ALTER TABLE source_tokens DISABLE TRIGGER evidence_immutable")
        yield
        conn.execute("ALTER TABLE source_tokens ENABLE TRIGGER evidence_immutable")


def names_qualified() -> set[str]:
    """Every tracked module outside `tests/` whose source names QUALIFIED.

    Read from the AST, so a mention in a comment or docstring -- which mints
    nothing -- is not a code path; a gate script is one, so `scripts/` counts.
    """
    naming: set[str] = set()
    for path in tracked_python(REPO):
        if path.is_relative_to(REPO / "tests"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            spoken = (isinstance(node, ast.Attribute) and node.attr == "QUALIFIED") or (
                isinstance(node, ast.Name) and node.id == "QUALIFIED"
            )
            declared = isinstance(node, ast.Constant) and node.value == "QUALIFIED"
            if spoken or declared:
                naming.add(str(path.relative_to(REPO)))
    return naming


def _run(harness: _Harness) -> _Harness:
    provider = ModuleProvider(
        harness.conn,
        harness.bundle,
        harness.blobs,
        CanonicalCompletions(harness.source_id),
        harness.route,
        harness.run_id,
    )
    run_route(
        harness.conn,
        harness.blobs,
        run_id=harness.run_id,
        route=harness.route,
        execution=Execution(provider, priced(ESTIMATE), harness.bundle),
    )
    return harness


@pytest.fixture
def ran(harness: _Harness) -> _Harness:
    return _run(harness)


def _prove(ran: _Harness) -> OrchestrationProof:
    proof = assert_orchestration_proof(
        ran.conn, ran.blobs, ran.bundle, run_id=ran.run_id
    )
    ran.conn.rollback()
    return proof


def _refusal(ran: _Harness) -> RefusalCode:
    with pytest.raises(Refusal) as caught:
        _prove(ran)
    ran.conn.rollback()
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    return caught.value.code


def _stored(ran: _Harness, module_id: str) -> tuple[UUID, str, str]:
    row = ran.conn.execute(
        "SELECT attempt_id, artifact_sha256, record_sha256 FROM artifacts"
        " WHERE route_node_id = %s",
        (_node(ran, module_id).route_node_id,),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0])), str(row[1]), str(row[2])


def _set(ran: _Harness, module_id: str, column: str, value: str | None) -> None:
    attempt, _artifact, _record = _stored(ran, module_id)
    assert column in {"artifact_sha256", "record_sha256"}
    ran.conn.execute(
        f"UPDATE artifacts SET {column} = %s WHERE attempt_id = %s",
        (value, attempt),
    )
    ran.conn.commit()


def _rewrite(
    ran: _Harness, module_id: str, change: Callable[[CanonicalRecord], CanonicalRecord]
) -> None:
    """Store a canonical, correctly bound record that says something else."""
    _attempt, _artifact, record = _stored(ran, module_id)
    changed = change(_decoded_record(ran.blobs.get(record)))
    _set(ran, module_id, "record_sha256", ran.blobs.put(record_bytes(changed)))


def test_a_lite_run_completed_through_the_runtime_proves(ran: _Harness) -> None:
    proof = _prove(ran)
    assert proof.assurance is Assurance.ORCHESTRATION_PROOF
    assert (proof.run_id, proof.build_id) == (ran.run_id, ran.bundle.build_id)
    assert (proof.artifacts, proof.citations) == (3, 3)


def test_a_proof_reads_each_cited_page_and_numbering_once(
    ran: _Harness,
) -> None:
    """Three records quoting one page of one source: one `TokenIndex` for the
    proof reads that page, its digest and its line numbering once, not once
    per citation."""
    with recorded_statements(ran.conn) as statements:
        assert _prove(ran).citations == 3
    reads = ("FROM source_tokens AS tokens", "SELECT DISTINCT line_id")
    assert [sum(read in s for s in statements) for read in reads] == [1, 1]


def test_a_host_control_reads_orchestration_proof_never_qualified(
    ran: _Harness,
) -> None:
    """Phase 10's named exit, over a canonical run.

    Behaviourally the control returns ORCHESTRATION_PROOF over a run that did
    something; structurally `QUALIFIED` is named only by its assurance/verdict
    binding and the exact-evidence API wire/read that relays that binding --
    and the release pack (§94), which relays the same `current_verdict` read
    per pathway and is held to it by `tests/test_release_pack.py`.
    """
    proof = _prove(ran)
    assert proof.assurance is Assurance.ORCHESTRATION_PROOF
    assert proof.build_id.startswith("b160c75e")
    assert proof.route_digest == route_digest(ran.route)
    assert proof.artifacts == len(ran.route.nodes)
    assert names_qualified() == {
        "scripts/release_pack.py",
        "caos/api/reads/qualification.py",
        "caos/api/wire.py",
        "caos/qualification/__init__.py",
        "caos/qualification/verdict.py",
    }


def test_a_run_that_accepted_nothing_has_nothing_to_prove(harness: _Harness) -> None:
    """Three claims about no artifacts hold vacuously, so they are refused."""
    assert _refusal(harness) is RefusalCode.ORCHESTRATION_NOTHING_TO_PROVE
    run_id = start_run(harness.conn, harness.case_id)
    harness.conn.commit()
    assert _refusal(replace(harness, run_id=run_id)) is (
        RefusalCode.ORCHESTRATION_NOTHING_TO_PROVE
    )


def test_a_run_whose_route_is_no_longer_pinned_refuses(ran: _Harness) -> None:
    with route_fault(ran.conn):
        ran.conn.execute("ALTER TABLE run_inputs DISABLE TRIGGER input_immutable")
        ran.conn.execute("DELETE FROM run_inputs WHERE run_id = %s", (ran.run_id,))
        ran.conn.execute("ALTER TABLE run_inputs ENABLE TRIGGER input_immutable")
        ran.conn.execute("DELETE FROM run_routes WHERE run_id = %s", (ran.run_id,))
    ran.conn.commit()
    assert _refusal(ran) is RefusalCode.ORCHESTRATION_ROUTE_NOT_PINNED


def test_an_accepted_node_the_pin_does_not_carry_refuses(ran: _Harness) -> None:
    """Invariant 10: execution that did not read the pin."""
    truncated = replace(ran.route, nodes=ran.route.nodes[:1], edges=())
    digest = route_digest(truncated)
    with route_fault(ran.conn):
        # ALL: the pin's foreign key to the route is a trigger too.
        ran.conn.execute("ALTER TABLE run_inputs DISABLE TRIGGER ALL")
        ran.conn.execute(
            "UPDATE run_inputs SET route_digest = %s WHERE run_id = %s",
            (digest, ran.run_id),
        )
        ran.conn.execute("ALTER TABLE run_inputs ENABLE TRIGGER ALL")
        ran.conn.execute(
            "UPDATE run_routes SET resolved = %s, route_digest = %s WHERE run_id = %s",
            (_canonical(truncated), digest, ran.run_id),
        )
    ran.conn.commit()
    assert _refusal(ran) is RefusalCode.ORCHESTRATION_NODE_NOT_IN_ROUTE


def test_a_run_with_no_stored_input_refuses(ran: _Harness) -> None:
    with _guard_disabled(ran.conn, "run_inputs", "input_immutable"):
        ran.conn.execute("DELETE FROM run_inputs WHERE run_id = %s", (ran.run_id,))
    ran.conn.commit()
    assert _refusal(ran) is RefusalCode.RUN_INPUT_INVALID


def test_an_artifact_whose_producer_differs_from_its_call_refuses(
    ran: _Harness,
) -> None:
    for column in ("model", "generation_id"):
        attempt, _artifact, _record = _stored(ran, "CP-L10")
        ran.conn.execute(
            f"UPDATE artifacts SET {column} = 'another' WHERE attempt_id = %s",
            (attempt,),
        )
        ran.conn.commit()
        assert _refusal(ran) is RefusalCode.CALL_OUTCOME_CONFLICT
        ran.conn.execute(
            f"UPDATE artifacts SET {column} = o.{column} FROM call_outcomes o"
            " WHERE o.attempt_id = artifacts.attempt_id"
            " AND artifacts.attempt_id = %s",
            (attempt,),
        )
        ran.conn.commit()
        assert _prove(ran).artifacts == 3


def test_an_artifact_with_no_recorded_call_refuses(ran: _Harness) -> None:
    with _guard_disabled(ran.conn, "call_outcomes", "outcome_immutable"):
        ran.conn.execute("DELETE FROM call_outcomes WHERE run_id = %s", (ran.run_id,))
    ran.conn.commit()
    assert _refusal(ran) is RefusalCode.CALL_OUTCOME_LEGACY


def test_a_proof_under_another_bundle_build_refuses(
    ran: _Harness, tmp_path: Path
) -> None:
    """Invariant 4 at proof time: the bundle here now, not the one remembered."""
    root = tmp_path / "another-build"
    shutil.copytree(ran.bundle.root, root)
    manifest = json.loads((root / MANIFEST_NAME).read_bytes())
    manifest["build_id"] = "b" * 64
    (root / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(Refusal) as caught:
        assert_orchestration_proof(ran.conn, ran.blobs, Bundle(root), run_id=ran.run_id)
    ran.conn.rollback()
    assert caught.value.code is RefusalCode.ORCHESTRATION_BUILD_MOVED
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_a_record_naming_another_module_than_the_pin_refuses(ran: _Harness) -> None:
    """Invariant 3: the module is the pin's, never the record's own claim.

    This deliberately differs from
    `test_the_module_checked_is_the_pinned_one_not_the_one_claimed` in
    `tests/test_orchestration_proof.py`, which proves success on the same
    kind of tamper: there, the *claims* envelope's `module_id` is untrusted
    frontmatter, and the host silently derives the right module's authority
    from the route pin regardless of what the envelope claims. Here the
    record is not untrusted frontmatter -- it is the host's own canonical
    write, bound end to end by `record_sha256`, and the model's claimed
    module was already checked and refused at validation time
    (`HANDOFF_IDENTITY_MISMATCH`) before this record could ever be stored.
    So a stored record naming another module than the one its own binding
    names is not a claim to reconcile against the pin; it is corruption of
    the host's own write, and refusing it is the correct answer.
    """
    _rewrite(
        ran,
        "CP-L10",
        lambda r: replace(r, identity=replace(r.identity, module_id="CP-5")),
    )
    assert _refusal(ran) is MISMATCH


def test_a_changed_markdown_blob_refuses(ran: _Harness) -> None:
    _attempt, artifact, _record = _stored(ran, "CP-5")
    changed = ran.blobs.put(ran.blobs.get(artifact) + b"\n")
    _set(ran, "CP-5", "artifact_sha256", changed)
    assert _refusal(ran) is MISMATCH


@pytest.mark.parametrize("which", ["markdown", "record"])
def test_bytes_damaged_under_their_address_are_unreadable(
    ran: _Harness, which: str
) -> None:
    _attempt, artifact, record = _stored(ran, "CP-L10")
    path = ran.blobs.path_of(artifact if which == "markdown" else record)
    path.chmod(0o644)
    path.write_bytes(b"damaged")
    assert _refusal(ran) is RefusalCode.ORCHESTRATION_ARTIFACT_UNREADABLE


def test_a_changed_record_blob_refuses(ran: _Harness) -> None:
    _attempt, _artifact, record = _stored(ran, "CP-L10")
    _set(ran, "CP-L10", "record_sha256", ran.blobs.put(ran.blobs.get(record) + b" "))
    assert _refusal(ran) is MISMATCH


def test_a_canonical_artifact_without_its_record_refuses(ran: _Harness) -> None:
    _set(ran, "CP-5", "record_sha256", None)
    assert _refusal(ran) is MISMATCH


def test_a_projection_the_markdown_does_not_say_refuses(ran: _Harness) -> None:
    def lying(record: CanonicalRecord) -> CanonicalRecord:
        readiness = (("CP-5", "READY"),)
        return replace(
            record, projections=replace(record.projections, readiness=readiness)
        )

    _rewrite(ran, "CP-0", lying)
    assert _refusal(ran) is MISMATCH


def test_an_identity_the_store_no_longer_holds_refuses(ran: _Harness) -> None:
    attempt, _artifact, record = _stored(ran, "CP-5")
    ran.conn.execute(
        "UPDATE run_attempts SET ordinal = ordinal + 1 WHERE attempt_id = %s",
        (attempt,),
    )
    ran.conn.commit()
    # The host still rebuilds an identity; it is the record that no longer binds.
    rebuilt = host_identity(
        ran.conn,
        ran.bundle,
        run_id=ran.run_id,
        route=ran.route,
        node=_node(ran, "CP-5"),
        attempt_id=attempt,
    )
    ran.conn.rollback()
    assert rebuilt.ordinal != _decoded_record(ran.blobs.get(record)).identity.ordinal
    assert _refusal(ran) is MISMATCH


def test_an_identity_the_host_cannot_rebuild_keeps_its_own_code(ran: _Harness) -> None:
    attempt, _artifact, _record = _stored(ran, "CP-5")
    ran.conn.execute(
        "UPDATE run_attempts SET ordinal = NULL WHERE attempt_id = %s", (attempt,)
    )
    ran.conn.commit()
    assert _refusal(ran) is RefusalCode.ATTEMPT_NOT_FOUND


def test_a_source_admitted_after_the_pin_cannot_support_the_proof(
    ran: _Harness,
) -> None:
    # The same quote on the same line: it anchors on the recorded rectangles.
    late = REPORT + b"Admitted after the pin\n"
    [late_id] = admit_pack(
        ran.conn,
        ran.blobs,
        case_id=ran.case_id,
        documents=[Document(filename=BoundaryText.of("late.txt"), data=late)],
    )
    ran.conn.commit()
    _attempt, _artifact, record = _stored(ran, "CP-5")
    [cited] = _decoded_record(ran.blobs.get(record)).citations
    moved = replace(cited, document_sha256=sha256(late).hexdigest())
    request = Citation(late_id, cited.page, cited.matched_text)
    assert verify_citations(
        ran.conn, delivered=every_block(ran.conn, late_id), citations=[request]
    ) == [moved]
    ran.conn.rollback()

    _rewrite(ran, "CP-5", lambda r: replace(r, citations=(moved,)))
    assert _refusal(ran) is RefusalCode.ORCHESTRATION_SOURCE_NOT_PINNED
    assert _delivered(ran) is MISMATCH


@pytest.mark.parametrize(
    "fault",
    [
        "UPDATE source_tokens SET x0 = x0 + 17.0, x1 = x1 + 17.0 WHERE source_id = %s",
        "DELETE FROM source_tokens WHERE source_id = %s",
    ],
)
def test_a_moved_or_lost_quote_refuses(ran: _Harness, fault: str) -> None:
    with _token_fault(ran.conn):
        ran.conn.execute(fault, (ran.source_id,))
    ran.conn.commit()
    assert _refusal(ran) is RefusalCode.ORCHESTRATION_CITATION_LOST


@pytest.mark.parametrize(
    "field",
    [
        "adapter_version",
        "build_id",
        "manifest_sha256",
        "authority_digest",
        "delivered_authority_digest",
    ],
)
def test_a_record_from_another_build_refuses(ran: _Harness, field: str) -> None:
    changes: dict[str, Any] = {field: "b" * 64}
    _rewrite(ran, "CP-L10", lambda record: replace(record, **changes))
    assert _refusal(ran) is RefusalCode.ORCHESTRATION_BUILD_MOVED


def test_a_run_pinned_under_another_adapter_refuses(
    ran: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(methodology, "CANONICAL_ADAPTER_VERSION", "another-adapter")
    assert _refusal(ran) is RefusalCode.ORCHESTRATION_BUILD_MOVED


def _delivered(ran: _Harness) -> RefusalCode | None:
    """The deliverable's verdict on the same store: None when it proves."""
    title, revision = BoundaryText.of("Acme Holdings plc"), BoundaryText.of("rev-1")
    try:
        canonical_payload(
            ran.conn,
            ran.blobs,
            ran.bundle,
            Revision(ran.case_id, ran.run_id, title, revision),
        )
    except Refusal as refused:
        assert refused.__cause__ is None and refused.__context__ is None
        return refused.code
    return None


def test_a_withdrawn_source_refuses_the_proof_and_the_deliverable(
    ran: _Harness,
) -> None:
    assert _delivered(ran) is None
    actor = uuid4()
    grant(ran.conn, case_id=ran.case_id, user_id=actor, standing=Standing.APPROVER)
    ran.conn.commit()
    withdraw_source(
        ran.conn, case_id=ran.case_id, actor_id=actor, source_id=ran.source_id
    )
    assert _refusal(ran) is RefusalCode.ORCHESTRATION_SOURCE_NOT_PINNED
    assert _delivered(ran) is MISMATCH


def test_a_readmitted_copy_of_a_withdrawn_source_does_not_revive_the_proof(
    ran: _Harness,
) -> None:
    actor = uuid4()
    grant(ran.conn, case_id=ran.case_id, user_id=actor, standing=Standing.APPROVER)
    ran.conn.commit()
    withdraw_source(
        ran.conn, case_id=ran.case_id, actor_id=actor, source_id=ran.source_id
    )
    admit_pack(
        ran.conn,
        ran.blobs,
        case_id=ran.case_id,
        documents=[Document(filename=BoundaryText.of("again.txt"), data=REPORT)],
    )
    ran.conn.commit()
    assert _refusal(ran) is RefusalCode.ORCHESTRATION_SOURCE_NOT_PINNED


@contextmanager
def _extraction_fault(conn: StoreConnection, table: str) -> Iterator[None]:
    """Privileged fault setup; transactional DDL restores the guard on failure."""
    assert conn.info.dbname.startswith("caos_test_")
    trigger = {
        "source_extractions": "extraction_is_immutable",
        "source_set_members": "source_set_immutable",
    }[table]
    with conn.transaction():
        conn.execute(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}")
        yield
        conn.execute(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}")


def test_a_changed_extraction_refuses_the_proof_and_the_deliverable(
    ran: _Harness,
) -> None:
    with _extraction_fault(ran.conn, "source_extractions"):
        ran.conn.execute(
            "UPDATE source_extractions SET output_sha256 = %s WHERE source_id = %s",
            ("e" * 64, ran.source_id),
        )
    ran.conn.commit()
    assert _refusal(ran) is RefusalCode.ORCHESTRATION_SOURCE_NOT_PINNED
    assert _delivered(ran) is MISMATCH


@pytest.fixture
def twice(harness: _Harness) -> tuple[_Harness, UUID]:
    """A second run whose pin captures the cited document under two sources."""
    conn = harness.conn
    [copy] = admit_pack(
        conn,
        harness.blobs,
        case_id=harness.case_id,
        documents=[Document(filename=BoundaryText.of("copy.txt"), data=REPORT)],
    )
    run_id = start_run(conn, harness.case_id)
    conn.commit()
    approver = approve_run(
        conn,
        case_id=harness.case_id,
        run_id=run_id,
        route=harness.route,
        bundle=harness.bundle,
    )
    return _run(replace(harness, run_id=run_id, approver=approver)), copy


def test_a_document_pinned_twice_proves_in_the_proof_and_the_deliverable(
    twice: tuple[_Harness, UUID],
) -> None:
    ran, copy = twice
    digest = sha256(REPORT).hexdigest()
    # One extraction: the lower source id stands for the document.
    assert pinned_live_sources(ran.conn, ran.run_id)[digest] == min(ran.source_id, copy)
    ran.conn.rollback()
    assert _prove(ran).artifacts == 3
    assert _delivered(ran) is None


def test_a_document_pinned_twice_with_two_extractions_resolves_to_neither(
    twice: tuple[_Harness, UUID],
) -> None:
    ran, copy = twice
    for table in ("source_extractions", "source_set_members"):
        with _extraction_fault(ran.conn, table):
            ran.conn.execute(
                f"UPDATE {table} SET output_sha256 = %s WHERE source_id = %s",
                ("e" * 64, copy),
            )
        ran.conn.commit()
    # Read directly: the edited member no longer matches the pin's fingerprint,
    # which the pin's own reader refuses before either verdict reaches sources.
    assert sha256(REPORT).hexdigest() not in pinned_live_sources(ran.conn, ran.run_id)
    ran.conn.rollback()


def test_a_soft_input_accepted_before_the_call_cannot_be_left_unnamed(
    harness: _Harness,
) -> None:
    # CP-L10 -> CP-5 is ADVISORY, but CP-L10 was accepted before CP-5 started.
    _accept(harness, "CP-0")
    _accept(harness, "CP-L10", **RESTRICTED)
    _accept(harness, "CP-5", True)
    attempt, _artifact, record = _stored(harness, "CP-5")
    stored = harness.blobs.get(record)
    host = host_identity(
        harness.conn,
        harness.bundle,
        run_id=harness.run_id,
        route=harness.route,
        node=_node(harness, "CP-5"),
        attempt_id=attempt,
    )
    expected = call_time_identity(
        harness.conn, harness.route, host, attempt_id=attempt, record=stored
    )
    harness.conn.rollback()
    # The record names only CP-0; the host keeps CP-L10, so the binding refuses.
    assert (
        _decoded_record(stored).identity.upstream
        != expected.upstream
        == (host.upstream)
    )
    assert _refusal(harness) is MISMATCH
    assert _delivered(harness) is MISMATCH


def test_a_blocked_run_proves_only_what_it_accepted(harness: _Harness) -> None:
    # CP-5 never ran: the proof covers two artifacts and claims no third.
    _accept(harness, "CP-0")
    _accept(harness, "CP-L10", **RESTRICTED)
    proof = _prove(harness)
    assert (proof.artifacts, proof.citations) == (2, 2)
    assert len(harness.route.nodes) == 3
    assert _delivered(harness) is RefusalCode.DELIVERABLE_PAYLOAD_INVALID
