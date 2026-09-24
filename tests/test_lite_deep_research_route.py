"""The contract test for `LITE_CREDIT_22 / LITE_DEEP_RESEARCH` (CP-0 -> CP-DR).

Two nodes and one REQUIRED edge, `decision_scope: SCREENING_ONLY`, CP-DR the
terminal deliverable (§96). The pinned brief reaches CP-DR's identity bound to
the run, the accepted CP-0 and the bundle; its front matter carries the
research fields the vendor's own preparer emits; its prompt carries the bound
brief as a tagged host-owned section; its handoff is judged by the vendor's
`validate_text`, `completeness_check` and `validate_dossier`. The route runs
through the same `run_route` -> `ModuleProvider` -> canonical executor ->
vendor validators -> proof -> canonical deliverable path every enabled pathway
uses: it completes, proves and freezes over a two-document pack; its requests
fit the request ceiling; a CP-0 verdict that blocks CP-DR stops the run before
any further call.

The pathway was dead as authored until build `6a5f1050`: the bundle's
`parse_t8` refused the CP-DR row CP-0's own contract asks for. Every
provider is deterministic; no live call is made.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import textwrap
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import (
    BUNDLE,
    CATALOG,
    CONTRACT,
    fields_from_prompt,
    skill,
)
from canonical_route_fixtures import (
    RESEARCH_BRIEF,
    RESEARCH_FILENAMES,
    RESEARCH_MODULES,
    RESEARCH_PACK,
    RESEARCH_QUOTES,
    RESEARCH_ROUTE,
    RESEARCH_SELECTION,
    ResearchCompletions,
    bound_research_brief_text,
    research_identity,
    research_markdown,
    research_section,
)
from conftest import _url_for, priced
from test_canonical_execution import _node
from test_canonical_runtime import (
    _blocking_verdict,
    _module_provider,
    _run_route,
    _status,
)
from test_execution_freshness import _counts, _events, _Harness
from test_gates import _approval
from test_handoff_record import _record
from test_lite_route_e2e_positive import _revision
from test_loop_charges import ESTIMATE

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.deliverable.canonical import freeze_canonical, payload_bytes, verify_frozen
from caos.deliverable.filing import sign_opinion
from caos.deliverable.revisions import read_revision, save_revision
from caos.evidence.ingest import Document, admit_pack
from caos.graph.route import ResolvedRoute, RouteExtensions, resolve_route
from caos.graph.runtime import Execution, run_route
from caos.methodology.handoff import (
    ADAPTER_MODULES,
    ADAPTER_ROUTES,
    RESEARCH_HOST_FIELDS,
    HostIdentity,
    Projections,
    invocation_fields,
    read_record,
    record_bytes,
    research_brief_of,
    validate_markdown,
)
from caos.methodology.invocation import _research_binding, host_identity
from caos.provider import MAX_REQUEST_BYTES
from caos.qualification.proof import assert_orchestration_proof
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection, connect
from caos.store.gates import Gate, approve_gate, require_adapter_route
from caos.store.members import Standing, grant
from caos.store.routes import pin_route
from caos.store.run_inputs import RunSubject, pin_run_input
from caos.store.runs import start_run
from caos.store.source_sets import snapshot_source_set

# Every enabled pathway, asserted exactly: a route enabled without its own
# contract test would pass this suite silently.
ENABLED = frozenset(
    {
        ("LITE_CREDIT_22", "LITE_EARNINGS_UPDATE"),
        ("LITE_CREDIT_22", "LITE_PORTFOLIO_DECISION"),
        ("FULL_CREDIT_32", "RELATIVE_VALUE"),
        ("LITE_CREDIT_22", "LITE_RELATIVE_VALUE"),
        ("LITE_CREDIT_22", "LITE_DECISION_LEDGER"),
        RESEARCH_SELECTION,
        ("FULL_CREDIT_32", "DEEP_RESEARCH"),
        ("FULL_CREDIT_32", "LIQUIDITY_REVIEW"),
        ("FULL_CREDIT_32", "EARNINGS_UPDATE"),
        ("FULL_CREDIT_32", "FULL_CREDIT_ASSESSMENT"),
        ("FULL_CREDIT_32", "DECISION_LEDGER"),
        ("FULL_CREDIT_32", "COVENANT_REFINANCING"),
        ("FULL_CREDIT_32", "PORTFOLIO_DECISION"),
        ("FULL_CREDIT_32", "MARKET_DISLOCATION"),
        ("LITE_CREDIT_22", "LITE_COVENANT_REFINANCING"),
        ("LITE_CREDIT_22", "LITE_DISTRESSED_RESTRUCTURING"),
        ("LITE_CREDIT_22", "LITE_FULL_CREDIT_SCREEN"),
        ("FULL_CREDIT_32", "DISTRESSED_RESTRUCTURING"),
    }
)
SUBJECT = RunSubject("ACME", "Acme Holdings plc", "FY2025", "2026-09-08")


@pytest.fixture
def route() -> ResolvedRoute:
    return resolve_route(CATALOG, *RESEARCH_SELECTION)


@pytest.fixture
def harness(
    case: tuple[StoreConnection, UUID], tmp_path: Path, route: ResolvedRoute
) -> _Harness:
    """A pinned, approved deep-research run over the release and the facility
    summary, its input pinned with the brief. `source_id` is the release."""
    conn, case_id = case
    blobs = BlobStore(tmp_path / "blobs")
    release, facility = admit_pack(
        conn,
        blobs,
        case_id=case_id,
        documents=[
            Document(
                filename=BoundaryText.of(RESEARCH_FILENAMES[name]),
                data=RESEARCH_PACK[name],
            )
            for name in ("release", "facility")
        ],
    )
    run_id = start_run(conn, case_id)
    conn.commit()
    source_set = snapshot_source_set(conn, case_id)
    pin_route(conn, run_id, route)
    pin_run_input(
        conn, run_id, source_set.version, BUNDLE, RESEARCH_BRIEF, subject=SUBJECT
    )
    approver = uuid4()
    grant(conn, case_id=case_id, user_id=approver, standing=Standing.APPROVER)
    conn.commit()
    for gate in Gate:
        approve_gate(conn, _approval(conn, run_id, approver, gate))
    return _Harness(
        conn,
        case_id,
        run_id,
        release,
        facility,
        blobs,
        route,
        BUNDLE,
        approver,
        _url_for(conn.info.dbname),
    )


def _cp_dr(
    cp0_sha256: str = "a" * 64,
) -> tuple[HostIdentity, dict[str, Any], bytes]:
    """A CP-DR identity carrying the brief bound to `cp0_sha256`, its host
    front matter, and a handoff the vendor validators accept."""
    ident = research_identity(
        "CP-DR", research_brief=bound_research_brief_text(cp0_sha256)
    )
    fields = invocation_fields(CONTRACT, ident)
    return ident, fields, research_markdown(ident, fields)


def _validated(ident: HostIdentity, markdown: bytes) -> Projections:
    return validate_markdown(
        CONTRACT,
        CATALOG,
        skill(ident.module_id),
        markdown,
        identity=ident,
        gate_expects=frozenset(),
    )


def _refused(ident: HostIdentity, markdown: bytes) -> RefusalCode:
    with pytest.raises(Refusal) as refused:
        _validated(ident, markdown)
    return refused.value.code


def _modules(answers: ResearchCompletions) -> list[str]:
    return [str(fields_from_prompt(p)["module_id"]) for p in answers.prompts]


def run_completed(
    harness: _Harness, answers: ResearchCompletions | None = None
) -> ResearchCompletions:
    answers = answers or ResearchCompletions(harness.source_id, harness.witness_id)
    run_route(
        harness.conn,
        harness.blobs,
        run_id=harness.run_id,
        route=harness.route,
        execution=Execution(
            _module_provider(harness, answers), priced(ESTIMATE), BUNDLE
        ),
    )
    assert _status(harness) == "COMPLETE"
    assert _modules(answers) == list(RESEARCH_MODULES)
    return answers


def _attempts_at(harness: _Harness, module_id: str) -> tuple[int, int]:
    """How many attempts and reservations this node has: the spend it caused."""
    with connect(harness.url) as observer:
        row = observer.execute(
            "SELECT count(*), count(r.attempt_id) FROM run_attempts t"
            " LEFT JOIN budget_reservations r USING (attempt_id)"
            " WHERE t.route_node_id = %s",
            (_node(harness, module_id).route_node_id,),
        ).fetchone()
    assert row is not None
    return int(row[0]), int(row[1])


def test_lite_deep_research_route_completes_proves_and_freezes(
    harness: _Harness,
) -> None:
    """CP-0 -> CP-DR completes, both artifacts prove, and the canonical
    deliverable for the run freezes and verifies against its own bytes."""
    assert RESEARCH_MODULES == ("CP-0", "CP-DR")
    assert RESEARCH_SELECTION in ADAPTER_ROUTES and "CP-DR" in ADAPTER_MODULES
    run_completed(harness)
    assert _events(harness, "RUN_COMPLETE") == 1
    proof = assert_orchestration_proof(
        harness.conn, harness.blobs, BUNDLE, run_id=harness.run_id
    )
    harness.conn.rollback()
    assert proof.artifacts == 2
    assert {m for m, _, _ in proof.anchored} == set(RESEARCH_MODULES)

    saved = save_revision(
        harness.conn,
        harness.blobs,
        BUNDLE,
        case_id=harness.case_id,
        run_id=harness.run_id,
        actor_id=harness.approver,
        narrative=[],
    )
    payload = read_revision(
        harness.conn, harness.blobs, case_id=harness.case_id, revision_id=saved
    )
    harness.conn.rollback()
    assert [a["route_node_id"] for a in payload["artifacts"]] == [
        n.route_node_id for n in RESEARCH_ROUTE.nodes
    ]
    data = payload_bytes(payload)
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
    grant(
        harness.conn,
        case_id=harness.case_id,
        user_id=freezer,
        standing=Standing.APPROVER,
    )
    harness.conn.commit()
    assert (
        freeze_canonical(
            harness.conn,
            harness.blobs,
            BUNDLE,
            replace(_revision(harness), revision_id=BoundaryText.of(str(saved))),
            actor_id=freezer,
        )
        == hashlib.sha256(data).hexdigest()
    )
    verify_frozen(
        harness.conn,
        harness.blobs,
        BUNDLE,
        case_id=harness.case_id,
        revision_id=saved,
        payload=data,
    )


def _dossier_grammar() -> set[str]:
    """Every literal the vendor's `research.validate_dossier` holds a CP-DR
    answer to: its register ids, as the `table-id` tag `cp_tables` reads, and
    each enumerated cell value. Read from the vendor's own function, so a
    build that adds a rule adds a string this route must deliver."""
    source = textwrap.dedent(inspect.getsource(CONTRACT.research.validate_dossier))
    wanted: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "rows":
            table = node.args[1]
            assert isinstance(table, ast.Constant) and isinstance(table.value, str)
            wanted.add(f"<!-- table-id: {table.value} -->")
        if isinstance(node, ast.Set):
            wanted |= {
                item.value
                for item in node.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            }
    assert len(wanted) > 3  # the three tags and at least one enumeration
    return wanted


def test_the_cp_dr_prompt_states_every_rule_its_dossier_is_refused_for(
    harness: _Harness,
) -> None:
    """A conforming CP-DR answer must be writable from its prompt alone. The
    vendor judges the dossier by tagged registers and closed value sets that
    only CP-OS's research contract spells out; before §101 the host delivered
    CP-DR's own files and never that one, so two live attempts on build
    78c24be4 wrote the registers untagged, invented a `source_type`, and were
    refused `HANDOFF_INCOMPLETE` for rules no part of the prompt stated."""
    answers = run_completed(harness)
    [prompt] = [
        p for p in answers.prompts if fields_from_prompt(p)["module_id"] == "CP-DR"
    ]
    missing = sorted(literal for literal in _dossier_grammar() if literal not in prompt)
    assert missing == []


def test_the_accepted_cp_dr_record_carries_the_brief_bound_to_the_accepted_gate(
    harness: _Harness,
) -> None:
    """The brief CP-DR was prompted with and its record carries is the pinned
    brief with exactly three host bindings written in: this run's vendor id,
    the accepted CP-0's Markdown digest, and the bundle's authority digest --
    never a caller's value (invariant 3). The record's citations anchor one
    line of each document (invariant 11)."""
    answers = run_completed(harness)
    cp0 = _node(harness, "CP-0")
    node = _node(harness, "CP-DR")
    rows: dict[str, str] = dict(
        harness.conn.execute(
            "SELECT route_node_id, artifact_sha256 FROM artifacts WHERE run_id=%s",
            (harness.run_id,),
        ).fetchall()
    )
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
        route=RESEARCH_ROUTE,
        node=node,
        attempt_id=attempt,
    )
    record = read_record(
        harness.blobs,
        artifact_sha256=artifact,
        record_sha256=record_sha,
        expected=ident,
    )
    harness.conn.rollback()
    bound = json.loads(str(record.identity.research_brief))
    assert bound == {
        **RESEARCH_BRIEF,
        "run_id": ident.run_id,
        "cp0_sha256": rows[cp0.route_node_id],
        "authority_sha256": ident.authority_bundle_sha256,
    }
    prompted = research_section(answers.prompts[1])
    assert prompted == record.identity.research_brief
    assert research_section(answers.prompts[0]) is None
    assert {(c.document_sha256, c.matched_text) for c in record.citations} == {
        (hashlib.sha256(RESEARCH_PACK[document]).hexdigest(), quote)
        for document, quote in RESEARCH_QUOTES["CP-DR"]
    }
    assert record.projections.decision_scope == "SCREENING_ONLY"


def test_lite_deep_research_requests_fit_the_request_ceiling(
    harness: _Harness,
) -> None:
    """Both prompts this pathway builds, the brief section included, are inside
    `MAX_REQUEST_BYTES` (§45.3)."""
    answers = run_completed(harness)
    assert len(answers.prompts) == 2
    assert all(
        len(answers.request_bytes(p, json_object=True)) <= MAX_REQUEST_BYTES
        for p in answers.prompts
    )


def test_a_blocked_cp0_verdict_holds_cp_dr_and_calls_nothing_after(
    harness: _Harness,
) -> None:
    """CP-0's T8 verdict gates CP-DR like any consumer: BLOCKED leaves the
    frontier empty, so the run ends BLOCKED with CP-DR never attempted,
    reserved or called."""
    answers = ResearchCompletions(
        harness.source_id, harness.witness_id, readiness={"CP-DR": "BLOCKED"}
    )
    assert _run_route(harness, _module_provider(harness, answers)) is None
    assert _modules(answers) == ["CP-0"]
    assert _status(harness) == "BLOCKED"
    assert _attempts_at(harness, "CP-DR") == (0, 0)
    assert _counts(harness) == (1, [answers.charge], 1, 1, 1)
    assert _blocking_verdict(harness) is None


def test_cp_dr_refuses_an_unanchored_quote(harness: _Harness) -> None:
    """A research answer the pack does not carry is refused before an artifact
    exists: CP-DR answers from supplied evidence alone (invariant 1)."""
    _document, quote = RESEARCH_QUOTES["CP-DR"][-1]
    answers = ResearchCompletions(
        harness.source_id,
        harness.witness_id,
        quotes_by_module={"CP-DR": quote + " fabricated"},
    )
    assert (
        _run_route(harness, _module_provider(harness, answers))
        is RefusalCode.CITATION_NOT_LOCATED
    )
    assert harness.conn.execute(
        "SELECT count(*) FROM artifacts WHERE route_node_id=%s",
        (_node(harness, "CP-DR").route_node_id,),
    ).fetchone() == (0,)
    harness.conn.rollback()


def test_lite_deep_research_is_the_only_newly_enabled_route() -> None:
    """Enabling this pathway enabled exactly this pathway; the disabled-route
    guard in `tests/test_relative_value_route.py` drives every other one."""
    assert ADAPTER_ROUTES == ENABLED


def test_the_research_extension_is_refused_before_any_attempt() -> None:
    """The host's route extension appends CP-DR at stage 99 without the
    predecessor and consumer edges the vendor's `Route` synthesises from the
    brief, so an extended enabled pathway is refused at execution input rather
    than run on a path the bundle's navigation would not take."""
    extended = resolve_route(
        CATALOG,
        "LITE_CREDIT_22",
        "LITE_EARNINGS_UPDATE",
        extensions=RouteExtensions(research_brief=RESEARCH_BRIEF),
    )
    assert "CP-DR" in {n.module_id for n in extended.nodes}
    with pytest.raises(Refusal) as refused:
        require_adapter_route(extended)
    assert refused.value.code is RefusalCode.HANDOFF_MODULE_UNSUPPORTED
    require_adapter_route(
        resolve_route(CATALOG, "LITE_CREDIT_22", "LITE_EARNINGS_UPDATE")
    )


def test_cp_dr_contract_validates_identifies_and_projects() -> None:
    """A CP-DR handoff carrying the host front matter -- research fields
    included -- and registers that lock the bound brief validates through the
    vendor's three validators and projects the pathway's SCREENING_ONLY scope;
    its front matter binds the plan hash the vendor's own digest gives the
    bound brief."""
    ident, fields, markdown = _cp_dr()
    assert {r.module_id for r in ident.upstream} == {"CP-0"}
    bound = json.loads(str(ident.research_brief))
    assert fields["research_mode"] == "linked"
    assert fields["scope_key"] == SUBJECT.issuer_id
    assert fields["subject_name"] == SUBJECT.issuer_name
    assert fields["source_mode"] == "supplied_only"
    assert fields["approved_plan_hash"] == "sha256:" + CONTRACT.envelope.digest(bound)
    assert all(name in fields for name in RESEARCH_HOST_FIELDS)
    projection = _validated(ident, markdown)
    assert projection.module_id == "CP-DR"
    assert projection.decision_scope == "SCREENING_ONLY"
    assert projection.qa_status == "Restricted"
    findings = CONTRACT.research.rows(
        markdown.decode(), "cpdr.findings", CONTRACT.research.FINDING_COLUMNS
    )
    assert [(f["question_id"], f["resolution_status"]) for f in findings] == [
        (q["question_id"], status)
        for q, status in zip(
            RESEARCH_BRIEF["questions"], ("ANSWERED", "UNRESOLVED"), strict=True
        )
    ]


def test_cp_dr_contract_refuses_a_dossier_that_does_not_lock_the_brief() -> None:
    """A dossier whose TDR.1 is not the bound brief's questions, or whose
    coverage does not follow from its findings, is refused by the vendor's own
    `validate_dossier` through `HANDOFF_INCOMPLETE` -- the bundle's rule, not
    one the host wrote (invariant 4)."""
    ident, _fields, markdown = _cp_dr()
    text = markdown.decode()
    dropped = RESEARCH_BRIEF["questions"][0]["question_id"]
    unlocked = text.replace(f"| {dropped} |", "| RQ-other |")
    assert unlocked != text
    assert _refused(ident, unlocked.encode()) is RefusalCode.HANDOFF_INCOMPLETE
    overstated = text.replace("coverage_score: 50", "coverage_score: 100")
    assert overstated != text
    assert _refused(ident, overstated.encode()) is RefusalCode.HANDOFF_INCOMPLETE


def test_a_dossier_refusal_rides_the_public_second_attempt_feedback() -> None:
    """R24-07: the vendor's `validate_dossier` refusal reached the feedback
    as its `ValueError` object, and the string-only boundary dropped it, so
    public `retry_feedback` told CP-DR's second attempt nothing. The message
    now crosses as text, bounded and labelled, beside the validator's."""
    from caos.methodology.handoff import MAX_FEEDBACK_CHARS, retry_feedback

    ident, _fields, markdown = _cp_dr()
    text = markdown.decode()
    overstated = text.replace("coverage_score: 50", "coverage_score: 60")
    assert overstated != text
    assert _refused(ident, overstated.encode()) is RefusalCode.HANDOFF_INCOMPLETE

    def feedback(canonical: str) -> tuple[str, ...]:
        body = json.dumps(
            {
                "canonical_markdown": canonical,
                "citations": [
                    {"source_id": str(uuid4()), "page": 1, "matched_text": "x"}
                ],
            }
        )
        return retry_feedback(
            CONTRACT, CATALOG, ident, body, skill=skill(ident.module_id)
        )

    research = [line for line in feedback(overstated) if line.startswith("research: ")]
    assert len(research) == 1, feedback(overstated)
    assert len(research[0]) <= len("research: ") + MAX_FEEDBACK_CHARS
    assert not any(line.startswith("research: ") for line in feedback(text))


def test_a_blocked_research_dossier_is_diagnostic_not_incomplete() -> None:
    """A genuinely blocked research run records `research_status: Blocked`
    and is unaccepted: the host reads it as the Blocked verdict every module
    may give, not as a dossier failing the coverage rule."""
    ident = research_identity(
        "CP-DR", research_brief=bound_research_brief_text("a" * 64)
    )
    fields = invocation_fields(CONTRACT, ident)
    from canonical_route_fixtures import HandoffKnobs

    blocked = research_markdown(ident, fields, HandoffKnobs(qa_status="Blocked"))
    assert b'research_status: "Blocked"' in blocked
    assert _refused(ident, blocked) is RefusalCode.HANDOFF_BLOCKED


def test_a_research_field_on_any_other_module_is_undeclared() -> None:
    """The research front matter belongs to CP-DR alone: a gate handoff
    carrying one is an undeclared field, and a gate identity carrying a brief
    has no host front matter at all."""
    ident = research_identity("CP-0")
    fields = invocation_fields(CONTRACT, ident)
    markdown = research_markdown(ident, {**fields, "research_mode": "linked"})
    with pytest.raises(Refusal) as refused:
        validate_markdown(
            CONTRACT,
            CATALOG,
            skill("CP-0"),
            markdown,
            identity=ident,
            gate_expects=frozenset({"CP-DR"}),
        )
    assert refused.value.code is RefusalCode.HANDOFF_UNDECLARED_FIELD
    with pytest.raises(Refusal) as mismatch:
        invocation_fields(
            CONTRACT,
            replace(ident, research_brief=bound_research_brief_text("a" * 64)),
        )
    assert mismatch.value.code is RefusalCode.HANDOFF_IDENTITY_MISMATCH
    with pytest.raises(Refusal) as missing:
        invocation_fields(CONTRACT, research_identity("CP-DR"))
    assert missing.value.code is RefusalCode.HANDOFF_IDENTITY_MISMATCH


def test_the_bound_brief_is_read_back_only_from_a_cp_dr_identity() -> None:
    """`research_brief_of` returns the one JSON object a CP-DR identity carries
    and refuses anything else: text that is not an object, a CP-DR without a
    brief, a brief on another module."""
    ident, _fields, _markdown = _cp_dr()
    assert research_brief_of(ident) == json.loads(str(ident.research_brief))
    for broken in ("[]", "not json", '{"a":1,"a":2}'):
        with pytest.raises(Refusal) as refused:
            research_brief_of(replace(ident, research_brief=broken))
        assert refused.value.code is RefusalCode.HANDOFF_IDENTITY_MISMATCH
    for wrong in (
        replace(ident, research_brief=None),
        replace(research_identity("CP-0"), research_brief=ident.research_brief),
    ):
        with pytest.raises(Refusal) as refused:
            research_brief_of(wrong)
        assert refused.value.code is RefusalCode.HANDOFF_IDENTITY_MISMATCH


def test_a_cp_dr_record_carries_the_bound_brief_and_others_are_unchanged(
    tmp_path: Path,
) -> None:
    """The record beside a CP-DR handoff carries the bound brief in its
    identity and reads back equal; a record whose identity carries none omits
    the field, so every record written before §96 is byte for byte what it
    was, and reads back as None."""
    ident, _fields, markdown = _cp_dr()
    record = _record(
        artifact_sha256=hashlib.sha256(markdown).hexdigest(),
        identity=ident,
        projections=_validated(ident, markdown),
    )
    data = record_bytes(record)
    assert json.loads(data)["identity"]["research_brief"] == ident.research_brief
    blobs = BlobStore(tmp_path / "blobs")
    artifact = blobs.put(markdown)
    stored = blobs.put(data)
    assert (
        read_record(
            blobs, artifact_sha256=artifact, record_sha256=stored, expected=ident
        ).identity.research_brief
        == ident.research_brief
    )
    plain = _record()
    assert "research_brief" not in json.loads(record_bytes(plain))["identity"]
    assert plain.identity.research_brief is None


def test_a_run_pinned_without_a_brief_has_no_cp_dr_identity() -> None:
    """The pin allows a brief-less input on a route carrying CP-DR; CP-DR's
    binding does not: `RUN_INPUT_INVALID`, raised where `check_context` builds
    the identity, so before any attempt, reservation or call. With a brief, the
    binding is the pinned brief bound to the accepted gate and nothing else."""
    gate = research_identity("CP-0")
    with pytest.raises(Refusal) as refused:
        _research_binding(
            BUNDLE,
            RESEARCH_ROUTE,
            pin_research=None,
            subject=SUBJECT,
            run_id=gate.run_id,
            cp0_sha256="a" * 64,
            authority_sha256=gate.authority_bundle_sha256,
        )
    assert refused.value.code is RefusalCode.RUN_INPUT_INVALID
    bound = _research_binding(
        BUNDLE,
        RESEARCH_ROUTE,
        pin_research=json.dumps(RESEARCH_BRIEF),
        subject=SUBJECT,
        run_id=gate.run_id,
        cp0_sha256="a" * 64,
        authority_sha256=gate.authority_bundle_sha256,
    )
    assert bound == bound_research_brief_text("a" * 64)
    assert json.loads(bound)["cp0_sha256"] == "a" * 64


def test_cp_dr_cites_whole_lines_of_the_pack_its_registers_read() -> None:
    """The fixture's citations are whole lines of the two documents, one from
    each, so a real run over this pack anchors them exactly once (invariant
    11); the fixture is what a route test would drive the day the pathway is
    enabled."""
    for document, quote in RESEARCH_QUOTES["CP-DR"]:
        lines = RESEARCH_PACK[document].decode().splitlines()
        assert lines.count(quote) == 1
    assert {document for document, _ in RESEARCH_QUOTES["CP-DR"]} == set(RESEARCH_PACK)
    _ident, _fields, markdown = _cp_dr()
    assert all(quote.encode() in markdown for _, quote in RESEARCH_QUOTES["CP-DR"])
    assert research_section("no section here") is None
