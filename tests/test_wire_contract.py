"""The v1 section wire: the committed schema is the models' schema, every model
is closed and bounded, and the key sets are pinned (Task 4.1, decisions 5, 6, 8).

No store: these read the models and the committed file only.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, get_args
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from caos.api import wire
from caos.api.reads import analysis, directory, run, upload
from caos.api.wire import (
    V1_COMMANDS,
    V1_DOCUMENTS,
    ActionName,
    ActionView,
    AnalysisBody,
    AnalysisDocument,
    ApproveGate,
    AttemptView,
    BlockedByView,
    CancelRun,
    CaseCreated,
    CaseRow,
    CellView,
    Chrome,
    CitationView,
    CreateCase,
    CreateRun,
    DeliverableFiled,
    DeliverableFrozen,
    DirectoryBody,
    DirectoryDocument,
    EdgeView,
    FileDeliverable,
    FrameView,
    FreezeDeliverable,
    GateApproved,
    GatePreviewDocument,
    GateView,
    GrantStanding,
    HandoffView,
    NarrativeDraft,
    NarrativeFigureRef,
    NodeView,
    OpinionSigned,
    PageBody,
    PageDocument,
    PageLine,
    PendingNode,
    PinRunInput,
    RectView,
    RefusalBody,
    RetryRun,
    RevisionSaved,
    RevokeStanding,
    RouteChoice,
    RunBody,
    RunCreated,
    RunInputPinned,
    RunSectionDocument,
    RunSubjectView,
    RunSummary,
    RunView,
    RunWork,
    SaveRevision,
    SectionNote,
    ServedRole,
    SetVersion,
    SignOpinion,
    SignVerdict,
    SourceRow,
    SourcesAdmitted,
    SourceWithdrawn,
    StandingGranted,
    StandingRevoked,
    StartRun,
    Subject,
    TableView,
    UploadBody,
    UploadDocument,
    VerdictRecorded,
    WithdrawSource,
    WorkView,
    wire_schema,
)
from caos.methodology.handoff import MAX_FILE_BYTES

REPO = Path(__file__).resolve().parents[1]
COMMITTED = REPO / "frontend" / "src" / "wire" / "v1" / "schema.json"

ENVELOPE = frozenset(
    {"chrome", "body", "observed_at", "observed_empty", "status", "notes"}
)

# A new field is a model change, a regenerated schema and an edit here.
PINNED: dict[type[BaseModel], frozenset[str]] = {
    wire.QualificationRead: frozenset(
        (
            "evidence_sha256 state qualification_set_sha256 performed_sha256 build_id "
            "adapter_version provider model reviewer reviewer_id decided_at expires_at"
        ).split()
    ),
    wire.NarrativeFigure: frozenset(
        "route_node_id citation_index document_sha256 page matched_text".split()
    ),
    wire.NarrativeSpan: frozenset({"text", "figure"}),
    wire.ReportArtifact: frozenset(
        (
            "route_node_id artifact_sha256 record_sha256 markdown record qa_status "
            "committee_status decision_scope limitation_flags validation_warnings"
        ).split()
    ),
    wire.ReportBody: frozenset(
        (
            "case_id displayed_run_id revision_id payload_sha256 case_title "
            "artifacts narrative revisions"
        ).split()
    ),
    wire.RevisionSummary: frozenset(
        "revision_id payload_sha256 saved_at state".split()
    ),
    wire.FiledReceipt: frozenset(
        (
            "case_id run_id revision_id payload_sha256 signed_by frozen_by filed_by "
            "renderer_sha256 filed_event_sha256"
        ).split()
    ),
    wire.CommitteeBody: frozenset(
        (
            "case_id displayed_run_id revision_id payload_sha256 case_title artifacts "
            "narrative revisions state signed_by frozen_by filed_by receipt"
        ).split()
    ),
    wire.ReportDocument: ENVELOPE,
    wire.CommitteeDocument: ENVELOPE,
    wire.BookColumn: frozenset({"key", "label"}),
    wire.BookResearch: frozenset({"route_node_id", "module_id", "qa_status"}),
    # The ten fields of IA_SPEC.md 4.4, and nothing beside them: a passport
    # that grew an eleventh would be this host asserting something the
    # accepted record does not say.
    wire.BookPassport: frozenset(
        (
            "definition period scenario reporting_period computed_at snapshot method "
            "derivation citations supporting_research"
        ).split()
    ),
    wire.BookCell: frozenset({"column", "value", "unavailable_reason", "passport"}),
    wire.BookPeriod: frozenset(
        {"case", "period_id", "fiscal_year", "days", "unavailable_reason", "cells"}
    ),
    wire.BookRow: frozenset(
        (
            "case_id title standing subject displayed_run_id displayed_run_status "
            "snapshot currency scale periods unavailable_reason refusal"
        ).split()
    ),
    wire.BookBasis: frozenset({"period", "scenario", "accepted_only"}),
    wire.BookBody: frozenset({"basis", "columns", "rows"}),
    wire.BookDocument: ENVELOPE,
    wire.ModelValue: frozenset({"name", "value", "unavailable_reason"}),
    wire.ModelPeriod: frozenset(
        {"case", "period_id", "fiscal_year", "days", "values", "unavailable_reason"}
    ),
    wire.ModelForecast: frozenset(
        {
            "route_node_id",
            "artifact_sha256",
            "record_sha256",
            "accepted_at",
            "qa_status",
            "limitation_flags",
            "validation_warnings",
            "currency",
            "scale",
            "perimeter",
            "periods",
        }
    ),
    wire.ModelBody: frozenset(
        {
            "case_id",
            "latest_run_id",
            "displayed_run_id",
            "subject",
            "displayed_run_status",
            "blocked_by",
            "forecast",
            "unavailable_reason",
        }
    ),
    wire.ModelDocument: ENVELOPE,
    RefusalBody: frozenset({"code", "clears"}),
    Subject: frozenset({"case_id", "title"}),
    ServedRole: frozenset({"global_role", "standing"}),
    Chrome: frozenset({"subject", "served_role", "actions"}),
    ActionView: frozenset({"action", "refusal"}),
    WorkView: frozenset({"state", "stop_code", "cancel_requested"}),
    RouteChoice: frozenset({"profile_id", "selection_id", "accepts_model_extension"}),
    DirectoryDocument: ENVELOPE,
    UploadDocument: ENVELOPE,
    RunSectionDocument: ENVELOPE,
    AnalysisDocument: ENVELOPE,
    RunSummary: frozenset(
        {"run_id", "status", "created_at", "profile_id", "selection_id"}
    ),
    CaseRow: frozenset(
        (
            "case_id title created_at standing live_sources latest_run members actions"
        ).split()
    ),
    wire.MemberRow: frozenset({"user_id", "standing"}),
    DirectoryBody: frozenset({"cases"}),
    SourceRow: frozenset(
        {
            "source_id",
            "filename",
            "document_sha256",
            "admitted_at",
            "withdrawn_at",
            "extractor_identity",
            "set_versions",
        }
    ),
    SetVersion: frozenset({"version", "fingerprint", "member_count"}),
    UploadBody: frozenset({"case_id", "sources", "set_versions"}),
    RunSubjectView: frozenset(
        {"issuer_id", "issuer_name", "reporting_period", "analysis_date"}
    ),
    GateView: frozenset({"gate", "state"}),
    AttemptView: frozenset(
        {"attempt_id", "route_node_id", "ordinal", "started_at", "accepted"}
    ),
    EdgeView: frozenset({"source", "type"}),
    NodeView: frozenset(
        {
            "route_node_id",
            "module_id",
            "stage",
            "state",
            "waiting_on",
            "awaiting_gate",
            "gate_verdict",
            "gate_reason",
        }
    ),
    BlockedByView: frozenset({"route_node_id", "module_id", "attempt_id"}),
    RunView: frozenset(
        {
            "run_id",
            "status",
            "created_at",
            "route_digest",
            "build_id",
            "source_set_version",
            "input_fingerprint",
            "subject",
            "gates",
            "nodes",
            "attempts",
            "work",
            "blocked_by",
            "supersedes",
            "superseded_by",
        }
    ),
    RunBody: frozenset(
        {
            "case_id",
            "latest_run_id",
            "displayed_run_id",
            "runs",
            "run",
            "route_choices",
        }
    ),
    RectView: frozenset({"x0", "y0", "x1", "y1"}),
    CitationView: frozenset(
        {
            "document_sha256",
            "filename",
            "page",
            "matched_text",
            "rects",
            "source_id",
            "withdrawn_at",
        }
    ),
    HandoffView: frozenset(
        {
            "route_node_id",
            "module_id",
            "artifact_sha256",
            "record_sha256",
            "accepted_at",
            "qa_status",
            "committee_status",
            "confidence_score",
            "confidence_band",
            "limitation_flags",
            "validation_warnings",
            "decision_scope",
            "screening_only",
            "source_facts",
            "model_analysis",
            "host_calculation",
            "tables",
            "tables_unavailable_reason",
        }
    ),
    TableView: frozenset({"table_id", "columns", "rows"}),
    CellView: frozenset({"text", "value"}),
    PendingNode: frozenset({"route_node_id", "module_id", "state"}),
    AnalysisBody: frozenset(
        {
            "case_id",
            "latest_run_id",
            "displayed_run_id",
            "subject",
            "displayed_run_status",
            "blocked_by",
            "handoffs",
            "pending",
        }
    ),
    # Evidence pages (Task 4.4, decision 7).
    FrameView: frozenset({"x0", "y0", "x1", "y1", "y_axis"}),
    PageLine: frozenset({"text", "x0", "y0", "x1", "y1"}),
    PageBody: frozenset(
        {"case_id", "run_id", "source_id", "document_sha256", "page", "frame", "lines"}
    ),
    PageDocument: frozenset({"body", "observed_at", "status", "notes"}),
    # Commands (Task 4.2, decisions 1 and 11): requests, then receipts.
    CreateCase: frozenset({"title"}),
    CaseCreated: frozenset({"case_id"}),
    SourcesAdmitted: frozenset({"case_id", "source_ids"}),
    CreateRun: frozenset(
        {"profile_id", "selection_id", "supersedes", "model_extension"}
    ),
    RunCreated: frozenset({"case_id", "run_id", "route_digest"}),
    PinRunInput: frozenset({"subject"}),
    RunInputPinned: frozenset({"run_id", "source_set_version", "input_fingerprint"}),
    GatePreviewDocument: frozenset(
        {
            "run_id",
            "gate",
            "content",
            "preview_sha256",
            "input_fingerprint",
            "observed_at",
        }
    ),
    ApproveGate: frozenset({"preview_sha256", "input_fingerprint"}),
    GateApproved: frozenset({"run_id", "gate", "preview_sha256", "input_fingerprint"}),
    StartRun: frozenset({"input_fingerprint"}),
    RetryRun: frozenset({"input_fingerprint"}),
    CancelRun: frozenset(),
    RunWork: frozenset({"run_id", "run_status", "work"}),
    # A verdict (F17's producer, `docs/DECISIONS.md` §65): the reviewer's six
    # bindings in, and the host's receipt out.
    SignVerdict: frozenset(
        (
            "provider qualification_set_sha256 build_id decided_at expires_at reviewer"
        ).split()
    ),
    VerdictRecorded: frozenset(
        {"evidence_sha256", "reviewer_id", "decided_at", "expires_at"}
    ),
    # The seven governed writes Task 12.1 routes: membership, withdrawal and
    # the filing chain. Requests first, then their receipts.
    GrantStanding: frozenset({"user_id", "standing"}),
    StandingGranted: frozenset({"case_id", "user_id", "standing"}),
    RevokeStanding: frozenset(),
    StandingRevoked: frozenset({"case_id", "user_id"}),
    WithdrawSource: frozenset(),
    SourceWithdrawn: frozenset({"case_id", "source_id"}),
    NarrativeFigureRef: frozenset({"route_node_id", "citation_index"}),
    NarrativeDraft: frozenset({"text", "figure"}),
    SaveRevision: frozenset({"expected_revision_id", "narrative"}),
    RevisionSaved: frozenset({"case_id", "run_id", "revision_id", "payload_sha256"}),
    SignOpinion: frozenset({"payload_sha256"}),
    OpinionSigned: frozenset({"case_id", "revision_id", "payload_sha256", "signed_by"}),
    FreezeDeliverable: frozenset({"payload_sha256"}),
    DeliverableFrozen: frozenset(
        {"case_id", "revision_id", "payload_sha256", "frozen_by"}
    ),
    FileDeliverable: frozenset({"payload_sha256"}),
    DeliverableFiled: frozenset(
        {"case_id", "run_id", "revision_id", "payload_sha256", "filed_by"}
    ),
}

REQUESTS: tuple[type[BaseModel], ...] = (
    CreateCase,
    CreateRun,
    PinRunInput,
    ApproveGate,
    StartRun,
    RetryRun,
    CancelRun,
    SignVerdict,
    GrantStanding,
    RevokeStanding,
    WithdrawSource,
    SaveRevision,
    SignOpinion,
    FreezeDeliverable,
    FileDeliverable,
)

# What `frontend/src/wire/v1/shape.ts` can express. `title` and `description`
# are carried and ignored.
DSL_KEYWORDS = frozenset(
    {
        "type",
        "properties",
        "required",
        "enum",
        "const",
        "anyOf",
        "maxLength",
        "maxItems",
        "minimum",
        "maximum",
        "pattern",
        "format",
        "$ref",
        "$defs",
        "items",
        "additionalProperties",
        "title",
        "description",
    }
)


def _wire_models() -> list[type[BaseModel]]:
    return [
        value
        for value in vars(wire).values()
        if isinstance(value, type)
        and issubclass(value, BaseModel)
        and value is not BaseModel
        and value.__module__ == wire.__name__
    ]


def _schemas(node: object) -> Iterator[dict[str, Any]]:
    """Every schema object in the document, depth first, `$defs` included."""
    if isinstance(node, dict):
        yield node
        for key, value in node.items():
            if key in {"properties", "$defs"}:
                for child in value.values():
                    yield from _schemas(child)
            elif key == "items" or key == "anyOf":
                yield from _schemas(value)
    elif isinstance(node, list):
        for child in node:
            yield from _schemas(child)


def test_the_committed_wire_schema_is_the_models_schema() -> None:
    printed = subprocess.run(
        [sys.executable, "-m", "caos.api.wire"],
        cwd=REPO,
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    assert printed == wire_schema()
    assert printed.endswith("}\n")
    assert not printed.endswith("\n\n")
    assert COMMITTED.read_text(encoding="utf-8") == printed
    defs = json.loads(printed)["$defs"]
    models: tuple[type[BaseModel], ...] = (*V1_DOCUMENTS, *V1_COMMANDS, RefusalBody)
    for model in models:
        assert model.__name__ in defs


def test_every_v1_model_forbids_undeclared_fields_and_bounds_every_collection() -> None:
    models = _wire_models()
    assert set(models) == set(PINNED), "a wire model the key-set pin does not name"
    for model in models:
        assert model.model_config.get("extra") == "forbid", model.__name__
        assert model.model_config.get("frozen") is True, model.__name__

    schema = json.loads(wire_schema())
    checked = 0
    for node in _schemas(schema):
        kind = node.get("type")
        if kind == "object" or "properties" in node:
            assert node.get("additionalProperties") is False, node.get("title")
            assert set(node["required"]) == set(node["properties"]), node["title"]
        if kind == "array":
            assert isinstance(node.get("maxItems"), int), node
            checked += 1
        if kind == "string" and not {"enum", "const", "format"} & set(node):
            assert isinstance(node.get("maxLength"), int), node
            checked += 1
        if node.get("format") in {"date-time", "uuid"}:
            assert node.get("type") == "string", node
    assert checked > 50, "the walk reached almost nothing"

    hashes = [
        props[name]
        for model in schema["$defs"].values()
        for props in [model.get("properties", {})]
        for name in props
        if name.endswith("sha256") or name in {"route_digest", "fingerprint"}
    ]
    assert len(hashes) >= 6
    for field in hashes:
        options = field.get("anyOf", [field])
        (text,) = [option for option in options if option.get("type") == "string"]
        assert text["pattern"] == "^[0-9a-f]{64}$"


def test_the_v1_wire_key_sets_are_pinned() -> None:
    for model, keys in PINNED.items():
        assert frozenset(model.model_fields) == keys, model.__name__
    assert set(SectionNote) == {
        SectionNote.LIST_TRUNCATED,
        SectionNote.ROUTE_NOT_PINNED,
        SectionNote.HANDOFFS_PENDING,
    }
    assert {action.value for action in ActionName} == {
        "CREATE_CASE",
        "ADMIT_SOURCES",
        "CREATE_RUN",
        "PIN_RUN_INPUT",
        "APPROVE_SOURCE_SET",
        "APPROVE_RESEARCH_PLAN",
        "START_RUN",
        "RETRY_RUN",
        "CANCEL_RUN",
        "WITHDRAW_SOURCE",
        "GRANT_STANDING",
        "REVOKE_STANDING",
        "SAVE_REVISION",
        "SIGN_OPINION",
        "FREEZE_DELIVERABLE",
        "FILE_DELIVERABLE",
    }
    assert [model.__name__ for model in V1_DOCUMENTS] == [
        "DirectoryDocument",
        "UploadDocument",
        "RunSectionDocument",
        "AnalysisDocument",
        "ModelDocument",
        "BookDocument",
        "ReportDocument",
        "CommitteeDocument",
    ]


def test_the_wire_schema_uses_only_keywords_the_browser_validator_understands() -> None:
    schema = json.loads(wire_schema())
    assert set(schema) == {"$defs"}
    seen: set[str] = set()
    nodes = [node for model in schema["$defs"].values() for node in _schemas(model)]
    for node in nodes:
        seen |= set(node)
        assert set(node) <= DSL_KEYWORDS, sorted(set(node) - DSL_KEYWORDS)
        if "additionalProperties" in node:
            assert node["additionalProperties"] is False
        if "anyOf" in node:
            # Nullability only: one schema and `null`.
            assert len(node["anyOf"]) == 2
            assert {"type": "null"} in node["anyOf"]
    assert {"$ref", "anyOf", "maxLength", "maxItems", "pattern", "format"} <= seen


def test_event_names_and_the_page_document_are_in_the_committed_schema() -> None:
    """Brief 4.4, decisions 2 and 7: the closed event names and the evidence page
    document are part of the one committed contract both halves read."""
    defs = json.loads(COMMITTED.read_text(encoding="utf-8"))["$defs"]
    names = [
        "run_progress",
        "handoff_accepted",
        "run_terminal",
        "sources_changed",
        "runs_changed",
        "filing_changed",
    ]
    assert defs["EventName"] == {"enum": names, "type": "string"}
    assert list(get_args(wire.EventName)) == names

    for model in (PageDocument, PageBody, PageLine, FrameView):
        assert model.__name__ in defs, model.__name__
    page = defs["PageBody"]["properties"]
    assert page["lines"]["maxItems"] == wire.PAGE_LINES_MAX == 2000
    assert (page["page"]["minimum"], page["page"]["maximum"]) == (1, 500)
    assert page["source_id"]["format"] == "uuid"
    frame = defs["FrameView"]["properties"]["y_axis"]
    assert frame == {"enum": ["down", "up"], "title": "Y Axis", "type": "string"}
    line = defs["PageLine"]["properties"]["text"]
    assert line["maxLength"] == wire.QUOTE_CHARS

    body: dict[str, Any] = {
        "case_id": str(uuid4()),
        "run_id": str(uuid4()),
        "source_id": str(uuid4()),
        "document_sha256": "a" * 64,
        "page": 1,
        "frame": {"x0": 0, "y0": 0, "x1": 612, "y1": 792, "y_axis": "down"},
        "lines": [{"text": "net leverage", "x0": 1, "y0": 2, "x1": 3, "y1": 4}],
    }
    document = {
        "body": body,
        "observed_at": "2026-09-14T10:00:00Z",
        "status": "complete",
        "notes": [],
    }
    assert PageDocument.model_validate(document).body.page == 1
    for bad in (
        {**document, "chrome": None},
        {**document, "body": {**body, "page": 0}},
        {**document, "body": {**body, "page": 501}},
        {**document, "body": {**body, "lines": [body["lines"][0]] * 2001}},
        {**document, "body": {**body, "frame": {**body["frame"], "y_axis": "left"}}},
        {**document, "body": {**body, "lines": None}},
    ):
        with pytest.raises(ValidationError):
            PageDocument.model_validate(bad)


def test_citation_view_names_its_source_for_the_page_endpoint() -> None:
    """Decision 7's page endpoint is addressed by source, so a citation carries
    the pinned source its document resolves to, not only the document digest."""
    defs = json.loads(COMMITTED.read_text(encoding="utf-8"))["$defs"]
    field = defs["CitationView"]["properties"]["source_id"]
    assert field == {"format": "uuid", "title": "Source Id", "type": "string"}
    assert "source_id" in defs["CitationView"]["required"]
    citation = {
        "document_sha256": "a" * 64,
        "filename": "report.txt",
        "page": 1,
        "matched_text": "net leverage",
        "rects": [],
        "withdrawn_at": None,
    }
    with pytest.raises(ValidationError):
        CitationView.model_validate(citation)
    source = uuid4()
    assert CitationView.model_validate({**citation, "source_id": source}).source_id == (
        source
    )


def test_a_table_cell_is_its_text_and_a_plain_decimal_string_or_null() -> None:
    """Never a number on the wire: a float cannot hold what the cell said."""
    cell = {"text": "$7,125.00", "value": "7125.00"}
    assert CellView.model_validate(cell).value == "7125.00"
    assert CellView.model_validate({**cell, "value": None}).value is None
    for value in (7125, 7125.0, "7.125e3", "NaN", "+7125", "7125.", "1" * 65):
        with pytest.raises(ValidationError):
            CellView.model_validate({**cell, "value": value})
    table = {"table_id": "cp1.debt_facility_register", "columns": ["x"], "rows": []}
    assert TableView.model_validate(table).rows == []
    for bad in (
        {**table, "table_id": "cp1 debt"},
        {**table, "rows": [[cell] * 33]},
        {**table, "columns": ["x"] * 33},
    ):
        with pytest.raises(ValidationError):
            TableView.model_validate(bad)


def test_every_section_router_declares_its_store_budget() -> None:
    for module in (directory, upload, run, analysis):
        assert isinstance(module.IO_BUDGET, int) and module.IO_BUDGET >= 0


def test_v1_command_models_are_closed_bounded_and_in_the_committed_schema() -> None:
    assert set(REQUESTS) <= set(V1_COMMANDS)
    assert len(V1_COMMANDS) == len(set(V1_COMMANDS)) == 30
    defs = json.loads(COMMITTED.read_text(encoding="utf-8"))["$defs"]
    for model in V1_COMMANDS:
        assert model.__name__ in defs, model.__name__
        assert model.model_config.get("extra") == "forbid", model.__name__
        assert model.model_config.get("frozen") is True, model.__name__
        # Every object, the empty `CancelRun` included, states `required`.
        assert set(defs[model.__name__]["required"]) == set(model.model_fields)

    # T1: a request names no actor, case, run or approver; the server derives them.
    authority = {"actor_id", "actor", "case_id", "run_id", "approver", "approver_id"}
    authority |= {"reviewer_id"}  # a verdict's signer is the actor, never a field
    for request in REQUESTS:
        assert not authority & set(request.model_fields), request.__name__

    # Undeclared fields refused, and the bounds the brief names hold.
    fingerprint = "a" * 64
    for bad in ({"input_fingerprint": fingerprint, "actor_id": "x"}, {}):
        with pytest.raises(ValidationError):
            StartRun.model_validate(bad)
    with pytest.raises(ValidationError):
        CancelRun.model_validate({"run_id": fingerprint})
    assert defs["CreateCase"]["properties"]["title"]["maxLength"] == 256
    assert defs["SourcesAdmitted"]["properties"]["source_ids"]["maxItems"] == 50
    content = defs["GatePreviewDocument"]["properties"]["content"]["maxLength"]
    assert content == wire.PREVIEW_CHARS == MAX_FILE_BYTES
    assert defs["Chrome"]["properties"]["actions"]["maxItems"] == len(ActionName)
    choices = defs["RunBody"]["properties"]["route_choices"]
    assert choices["maxItems"] == wire.ROUTE_CHOICES_MAX == 18
    for request in (StartRun, RetryRun, ApproveGate):
        field = defs[request.__name__]["properties"]["input_fingerprint"]
        assert field["pattern"] == "^[0-9a-f]{64}$"
    # A verdict's moments are text the server's reader parses, not datetimes
    # the wire would have judged first; the receipt's are the host's, aware.
    for moment in ("decided_at", "expires_at"):
        assert defs["SignVerdict"]["properties"][moment] == {
            "maxLength": wire.MOMENT_CHARS,
            "title": moment.replace("_", " ").title(),
            "type": "string",
        }
        assert defs["VerdictRecorded"]["properties"][moment]["format"] == "date-time"
