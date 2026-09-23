// The v1 section documents and the refusal body, one shape per model in
// `server/api/wire.py`, named as there. `schema.json` beside this file is the
// backend's emitted schema; tests/unit/wire-contract.test.ts proves these
// shapes normalise to it exactly.
import {
  type Infer,
  array,
  bool,
  datetime,
  enumOf,
  int,
  literal,
  nullable,
  number,
  object,
  parse,
  string,
  uuid,
  type Shape,
} from "./shape";

const SHORT = 256;
const TEXT = 4096;
const hash = string({ max: 64, pattern: "^[0-9a-f]{64}$" });
const short = string({ max: SHORT });
const text = string({ max: TEXT });
const RUN_STATUSES = ["RUNNING", "COMPLETE", "FAILED", "BLOCKED", "CANCELLED"] as const;

const GlobalRole = enumOf(["READER", "ANALYST", "ADMIN"]);
const Standing = enumOf(["READER", "WRITER", "APPROVER", "ADMIN"]);
const SectionNote = enumOf(["LIST_TRUNCATED", "ROUTE_NOT_PINNED", "HANDOFFS_PENDING"]);
const NodeState = enumOf(["COMPLETE", "RUNNABLE", "RESTRICTED", "BLOCKED"]);
const EdgeType = enumOf(["REQUIRED", "CONDITIONAL", "QA_GATE", "OPTIONAL", "ADVISORY"]);
const Gate = enumOf(["SOURCE_SET", "RESEARCH_PLAN"]);
const GateState = enumOf(["OPEN", "RELEASED"]);

/** A shape declared further down this file, resolved only when first used. */
function later<T>(get: () => Shape<T>): Shape<T> {
  return {
    check: (value, path): value is T => get().check(value, path),
    toSchema: () => get().toSchema(),
  };
}

const ActionName = enumOf([
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
]);

const Subject = object({ case_id: uuid, title: text });
const ServedRole = object({ global_role: GlobalRole, standing: nullable(Standing) });
// Server-computed and advisory: a refused action is shown with its code, and
// the command rechecks at commit (brief 4.2, decision 10).
const ActionView = object({
  action: ActionName,
  refusal: nullable(later(() => RefusalBody)),
});
const Chrome = object({
  subject: nullable(Subject),
  served_role: ServedRole,
  actions: array(ActionView, 16),
});

function sectionDocument<B extends ReturnType<typeof object>>(body: B) {
  return object({
    chrome: Chrome,
    body,
    observed_at: datetime,
    observed_empty: bool,
    status: enumOf(["complete", "partial"]),
    notes: array(SectionNote, 3),
  });
}

const RunSummary = object({
  run_id: uuid,
  status: enumOf(RUN_STATUSES),
  created_at: datetime,
  profile_id: nullable(short),
  selection_id: nullable(short),
});
// A case's live members, served only to its ADMIN (O21); null is "not served".
const MemberRow = object({ user_id: uuid, standing: Standing });
const CaseRow = object({
  case_id: uuid,
  title: text,
  created_at: datetime,
  standing: Standing,
  live_sources: int(),
  latest_run: nullable(RunSummary),
  members: nullable(array(MemberRow, 64)),
  actions: array(ActionView, 2),
});
const DirectoryBody = object({ cases: array(CaseRow, 200) });
const DirectoryDocument = sectionDocument(DirectoryBody);

const SourceRow = object({
  source_id: uuid,
  filename: text,
  document_sha256: hash,
  admitted_at: datetime,
  withdrawn_at: nullable(datetime),
  extractor_identity: nullable(text),
  set_versions: array(int(), 1000),
});
const SetVersion = object({ version: int(), fingerprint: hash, member_count: int() });
const UploadBody = object({
  case_id: uuid,
  sources: array(SourceRow, 1000),
  set_versions: array(SetVersion, 1000),
});
const UploadDocument = sectionDocument(UploadBody);

const RunSubjectView = object({
  issuer_id: string({ max: 128 }),
  issuer_name: text,
  reporting_period: text,
  analysis_date: string({ max: 10, pattern: "^\\d{4}-\\d{2}-\\d{2}$" }),
});
const GateView = object({ gate: Gate, state: GateState });
const EdgeView = object({ source: short, type: EdgeType });
const NodeView = object({
  route_node_id: short,
  module_id: short,
  stage: int(),
  state: NodeState,
  waiting_on: array(EdgeView, 256),
  awaiting_gate: bool,
  gate_verdict: nullable(short),
  // What the gate wrote beside a verdict it did not clear — the T8 blocker cell
  // of a CONDITIONAL or BLOCKED readiness row, where CP-0 names the source the
  // pinned set does not carry (§61). Null for a node it cleared or never ruled
  // on, so nothing here ever renders an empty reason as a stated one.
  gate_reason: nullable(string({ max: 512 })),
});
const AttemptView = object({
  attempt_id: uuid,
  route_node_id: short,
  ordinal: nullable(int()),
  started_at: datetime,
  accepted: bool,
});
const WorkView = object({
  state: enumOf(["QUEUED", "CLAIMED", "STOPPED", "DONE"]),
  stop_code: nullable(later(() => RefusalCode)),
  cancel_requested: bool,
});
// `accepts_model_extension` is the create command's own route resolution
// asked in advance (§82): advisory, and resolved again at commit.
const RouteChoice = object({
  profile_id: short,
  selection_id: short,
  accepts_model_extension: bool,
});
// The node whose validated Blocked verdict ended the run, as the transition
// recorded it (§68). Nullable on `RunView`: a run the frontier emptied is
// BLOCKED with no node to name, and the wire never claims one.
const BlockedByView = object({ route_node_id: short, module_id: short, attempt_id: uuid });
const RunView = object({
  run_id: uuid,
  status: enumOf(RUN_STATUSES),
  created_at: datetime,
  route_digest: nullable(hash),
  build_id: nullable(short),
  source_set_version: nullable(int()),
  subject: nullable(RunSubjectView),
  gates: array(GateView, 2),
  nodes: array(NodeView, 256),
  attempts: array(AttemptView, 4096),
  work: nullable(WorkView),
  blocked_by: nullable(BlockedByView),
  // The successor link (§72), both ends: the BLOCKED run of this case this run
  // was created to answer, and the one run created to answer this one. Null at
  // an end that has nothing to name. The link says which run answers which;
  // whether the answer holds is the reader's judgement, not the host's claim.
  supersedes: nullable(uuid),
  superseded_by: nullable(uuid),
});
const RunBody = object({
  case_id: uuid,
  latest_run_id: nullable(uuid),
  displayed_run_id: nullable(uuid),
  runs: array(RunSummary, 200),
  run: nullable(RunView),
  route_choices: array(RouteChoice, 18),
});
const RunSectionDocument = sectionDocument(RunBody);

const RectView = object({ x0: number, y0: number, x1: number, y1: number });
const CitationView = object({
  document_sha256: hash,
  source_id: uuid,
  filename: text,
  page: int(),
  matched_text: string({ max: 65536 }),
  rects: array(RectView, 256),
  withdrawn_at: nullable(datetime),
});
// A handoff's tagged tables, read by the server from its Markdown with the
// bundle's own reader (`caos/methodology/tables.py`); the browser never parses
// Markdown. A figure is the server's exact decimal string, never a float, and
// null is "no figure", never zero.
const CellView = object({
  text,
  value: nullable(string({ max: 64, pattern: "^-?[0-9]+(\\.[0-9]+)?$" })),
});
const TableView = object({
  table_id: string({ max: SHORT, pattern: "^[A-Za-z0-9_.]+$" }),
  columns: array(text, 32),
  rows: array(array(CellView, 32), 2000),
});
const HandoffView = object({
  route_node_id: short,
  module_id: short,
  artifact_sha256: hash,
  record_sha256: hash,
  accepted_at: datetime,
  qa_status: short,
  committee_status: short,
  confidence_score: int(),
  confidence_band: short,
  limitation_flags: array(text, 256),
  validation_warnings: array(text, 256),
  decision_scope: short,
  screening_only: bool,
  source_facts: array(CitationView, 1024),
  model_analysis: string({ max: 26214400 }),
  host_calculation: enumOf(["NONE", "CP_CF_FORECAST"]),
  tables: array(TableView, 64),
  tables_unavailable_reason: nullable(enumOf(["TABLES_MALFORMED", "TABLES_TOO_LARGE"])),
});
const PendingNode = object({ route_node_id: short, module_id: short, state: NodeState });
const AnalysisBody = object({
  case_id: uuid,
  latest_run_id: nullable(uuid),
  displayed_run_id: nullable(uuid),
  subject: nullable(RunSubjectView),
  displayed_run_status: nullable(enumOf(RUN_STATUSES)),
  blocked_by: nullable(BlockedByView),
  handoffs: array(HandoffView, 256),
  pending: array(PendingNode, 256),
});
const AnalysisDocument = sectionDocument(AnalysisBody);

const ModelValue = object({
  name: short,
  value: nullable(string({ max: 64, pattern: "^-?[0-9]+(\\.[0-9]+)?$" })),
  unavailable_reason: nullable(literal("ZERO_OR_NEGATIVE_DENOMINATOR")),
});
const ModelPeriod = object({
  case: text,
  period_id: text,
  fiscal_year: text,
  days: string({ max: 3, pattern: "^[0-9]+$" }),
  values: array(ModelValue, 40),
  unavailable_reason: nullable(text),
});
const ModelForecast = object({
  route_node_id: short,
  artifact_sha256: hash,
  record_sha256: hash,
  accepted_at: datetime,
  qa_status: short,
  limitation_flags: array(text, 256),
  validation_warnings: array(text, 256),
  currency: string({ max: 3, pattern: "^[A-Z]{3}$" }),
  scale: enumOf(["units", "thousands", "millions", "billions"]),
  perimeter: text,
  periods: array(ModelPeriod, 240),
});
const ModelBody = object({
  case_id: uuid,
  latest_run_id: nullable(uuid),
  displayed_run_id: nullable(uuid),
  subject: nullable(RunSubjectView),
  displayed_run_status: nullable(enumOf(RUN_STATUSES)),
  blocked_by: nullable(BlockedByView),
  forecast: nullable(ModelForecast),
  unavailable_reason: nullable(literal("NO_ACCEPTED_FORECAST")),
});
const ModelDocument = sectionDocument(ModelBody);

// Book, `/api/v1/book` (IA_SPEC.md 4.4): the credit across the portfolio. No
// case in its body, so it is the one section document beside Directory's that
// answers for no single case.
const BookColumn = object({ key: short, label: text });
const BookResearch = object({ route_node_id: short, module_id: short, qa_status: short });
/** The ten fields of IA_SPEC.md 4.4, in its order and closed to them. */
const BookPassport = object({
  definition: text,
  period: text,
  scenario: text,
  reporting_period: text,
  computed_at: datetime,
  snapshot: hash,
  method: text,
  derivation: text,
  citations: array(CitationView, 1024),
  supporting_research: array(BookResearch, 256),
});
const BookCell = object({
  column: short,
  value: nullable(string({ max: 64, pattern: "^-?[0-9]+(\\.[0-9]+)?$" })),
  unavailable_reason: nullable(literal("ZERO_OR_NEGATIVE_DENOMINATOR")),
  passport: BookPassport,
});
const BookPeriod = object({
  case: text,
  period_id: text,
  fiscal_year: text,
  days: string({ max: 3, pattern: "^[0-9]+$" }),
  unavailable_reason: nullable(text),
  cells: array(BookCell, 16),
});
const BookRow = object({
  case_id: uuid,
  title: text,
  standing: Standing,
  subject: nullable(RunSubjectView),
  displayed_run_id: nullable(uuid),
  displayed_run_status: nullable(enumOf(RUN_STATUSES)),
  snapshot: nullable(hash),
  currency: nullable(string({ max: 3, pattern: "^[A-Z]{3}$" })),
  scale: nullable(enumOf(["units", "thousands", "millions", "billions"])),
  periods: array(BookPeriod, 8),
  unavailable_reason: nullable(literal("NO_ACCEPTED_FORECAST")),
  refusal: nullable(later(() => RefusalBody)),
});
const BookBasis = object({
  period: literal("EVERY_ACCEPTED_PERIOD"),
  scenario: literal("EVERY_ACCEPTED_CASE"),
  accepted_only: literal(true),
});
const BookBody = object({
  basis: BookBasis,
  columns: array(BookColumn, 16),
  rows: array(BookRow, 4),
});
const BookDocument = sectionDocument(BookBody);

const NarrativeFigure = object({
  route_node_id: short,
  citation_index: int({ min: 0 }),
  document_sha256: hash,
  page: int({ min: 1 }),
  matched_text: string({ max: 65536 }),
});
const NarrativeSpan = object({
  text: nullable(string({ max: 2000 })),
  figure: nullable(NarrativeFigure),
});
const ReportArtifact = object({
  route_node_id: short,
  artifact_sha256: hash,
  record_sha256: hash,
  markdown: string({ max: 26214400 }),
  record: string({ max: 26214400 }),
  qa_status: short,
  committee_status: short,
  decision_scope: short,
  limitation_flags: array(text, 256),
  validation_warnings: array(text, 256),
});
// One revision of the displayed run and how far it has gone: what Report lists
// and Committee's front door links to. It proves nothing; opening one does.
const RevisionSummary = object({
  revision_id: uuid,
  payload_sha256: hash,
  saved_at: datetime,
  state: enumOf(["saved", "frozen", "filed"]),
});
const reportFields = {
  case_id: uuid,
  displayed_run_id: uuid,
  // Null only on a Report for a run nothing has been saved from yet.
  revision_id: nullable(uuid),
  payload_sha256: nullable(hash),
  case_title: text,
  artifacts: array(ReportArtifact, 256),
  narrative: array(array(NarrativeSpan, 64), 64),
  // The run's revisions, newest first: empty on the Report with none.
  revisions: array(RevisionSummary, 64),
};
const ReportBody = object(reportFields);
const ReportDocument = sectionDocument(ReportBody);
const FiledReceipt = object({
  case_id: uuid,
  run_id: uuid,
  revision_id: uuid,
  payload_sha256: hash,
  signed_by: uuid,
  frozen_by: uuid,
  filed_by: uuid,
  renderer_sha256: hash,
  filed_event_sha256: hash,
});
const CommitteeBody = object({
  ...reportFields,
  revision_id: uuid,
  payload_sha256: hash,
  state: enumOf(["frozen", "filed"]),
  signed_by: array(uuid, 1000),
  frozen_by: uuid,
  filed_by: nullable(uuid),
  receipt: nullable(FiledReceipt),
});
const CommitteeDocument = sectionDocument(CommitteeBody);

// Events and evidence pages (brief 4.4, decisions 2, 7 and 8).
/** The closed event names a case stream carries; a name only says what to refetch. */
export const EVENT_NAMES = [
  "run_progress",
  "handoff_accepted",
  "run_terminal",
  "sources_changed",
  "runs_changed",
  "filing_changed",
] as const;
const EventName = enumOf(EVENT_NAMES);
const FrameView = object({
  x0: number,
  y0: number,
  x1: number,
  y1: number,
  y_axis: enumOf(["down", "up"]),
});
const PageLine = object({
  text: string({ max: 65536 }),
  x0: number,
  y0: number,
  x1: number,
  y1: number,
});
const PageBody = object({
  case_id: uuid,
  run_id: uuid,
  source_id: uuid,
  document_sha256: hash,
  page: int({ min: 1, max: 500 }),
  frame: FrameView,
  lines: array(PageLine, 2000),
});
// Not a section document: no chrome.
const PageDocument = object({
  body: PageBody,
  observed_at: datetime,
  status: enumOf(["complete", "partial"]),
  notes: array(SectionNote, 3),
});

const RefusalCode = enumOf([
  "BOUNDARY_TEXT_INVALID",
  "BOUNDARY_TEXT_TOO_LONG",
  "BLOB_DIGEST_MISMATCH",
  "BLOB_NOT_FOUND",
  "BLOB_ADDRESS_INVALID",
  "RUN_NOT_FOUND",
  "RUN_NOT_RUNNING",
  "RUN_NOT_BLOCKED",
  "RUN_ALREADY_SUPERSEDED",
  "LEASE_NOT_HELD",
  "RUN_CANCEL_REQUESTED",
  "RUN_NODES_UNACCEPTED",
  "RUN_TERMINAL_STALE",
  "ATTEMPT_NOT_FOUND",
  "ATTEMPT_LIMIT_REACHED",
  "CALL_OUTCOME_INVALID",
  "CALL_OUTCOME_CONFLICT",
  "CALL_OUTCOME_LEGACY",
  "CALL_OUTCOME_UNEXPLAINED",
  "NODE_ALREADY_ACCEPTED",
  "MONEY_NOT_DECIMAL",
  "MONEY_INVALID",
  "BUDGET_ALREADY_RESERVED",
  "BUDGET_NOT_RESERVED",
  "BUDGET_CEILING_REACHED",
  "PROVIDER_NOT_CONFIGURED",
  "PROVIDER_CALL_INVALID",
  "CONTEXT_OVER_CEILING",
  "UPSTREAM_SECTION_OVER_CEILING",
  "RESERVATION_BELOW_REQUEST",
  "PROVIDER_UNAVAILABLE",
  "PROVIDER_OUTPUT_TRUNCATED",
  "PROVIDER_REFUSED",
  "PROVIDER_RESPONSE_INVALID",
  "AUTHORITY_BYTES_MISMATCH",
  "AUTHORITY_MODULE_UNKNOWN",
  "ENVELOPE_INVALID",
  "ENVELOPE_UNDECLARED_FIELD",
  "ENVELOPE_UNCITED_CLAIM",
  "HANDOFF_MALFORMED",
  "HANDOFF_BLOCKED",
  "HANDOFF_IDENTITY_MISMATCH",
  "HANDOFF_INCOMPLETE",
  "HANDOFF_UNDECLARED_FIELD",
  "HANDOFF_MODULE_UNSUPPORTED",
  "ARTIFACT_RECORD_MISMATCH",
  "READINESS_INVALID",
  "READINESS_INCOMPLETE",
  "NOT_AUTHENTICATED",
  "ENDPOINT_NOT_FOUND",
  "EDGE_NOT_TRUSTED",
  "ORIGIN_REFUSED",
  "EDGE_CONFIG_INVALID",
  "INTERNAL_FAULT",
  "NOT_AUTHORISED",
  "REQUEST_INVALID",
  "IDEMPOTENCY_KEY_REQUIRED",
  "IDEMPOTENCY_KEY_REUSED",
  "RUN_INPUT_NOT_PINNED",
  "RUN_ALREADY_STARTED",
  "RUN_NOT_STOPPED",
  "ROUTE_NOT_ENABLED",
  "COMMAND_EXPECTATION_STALE",
  "METHODOLOGY_INPUT_INVALID",
  "FORECAST_CHAIN_BROKEN",
  "FORECAST_RESIDUAL_UNRECONCILED",
  "FORECAST_DRIVER_NOT_READY",
  "DELIVERABLE_PAYLOAD_INVALID",
  "DELIVERABLE_NOT_FOUND",
  "NARRATIVE_FIGURE_UNREFERENCED",
  "NARRATIVE_REFERENCE_INVALID",
  "DELIVERABLE_UNCITED_FIGURE",
  "DELIVERABLE_MARKDOWN_UNSUPPORTED",
  "DELIVERABLE_NOT_SIGNED",
  "DELIVERABLE_NOT_FROZEN",
  "DELIVERABLE_MOVED_SINCE_SIGNING",
  "DELIVERABLE_ALREADY_FILED",
  "DELIVERABLE_ALREADY_FROZEN",
  "DELIVERABLE_ALREADY_SIGNED",
  "APPROVER_NOT_INDEPENDENT",
  "CASE_NOT_FOUND",
  "SOURCE_PACK_EMPTY",
  "SOURCE_NOT_READABLE",
  "SOURCE_ENCRYPTED",
  "SOURCE_HAS_NO_TEXT",
  "SOURCE_TOO_LARGE",
  "SOURCE_EXTRACTION_TIMEOUT",
  "SOURCE_IDENTITY_INVALID",
  "EVIDENCE_NOT_AVAILABLE",
  "EVIDENCE_PACKING_MISMATCH",
  "EVIDENCE_DEMAND_UNRESOLVED",
  "PAGE_NOT_AVAILABLE",
  "CITATION_NOT_LOCATED",
  "CITATION_AMBIGUOUS",
  "CITATION_NOT_DELIVERED",
  "ROUTE_PROFILE_UNKNOWN",
  "ROUTE_SELECTION_UNKNOWN",
  "ROUTE_EXTENSION_OWNER_MISSING",
  "ROUTE_HAS_A_CYCLE",
  "ROUTE_DUPLICATE_MODULE",
  "ROUTE_EDGE_UNSUPPORTED",
  "ROUTE_ALREADY_PINNED",
  "ROUTE_IDENTITY_INVALID",
  "ROUTE_PIN_TOO_LATE",
  "RUN_INPUT_INVALID",
  "RUN_INPUT_ALREADY_PINNED",
  "RUN_INPUT_TOO_LATE",
  "GATE_APPROVAL_MISMATCH",
  "QUALIFICATION_SET_EMPTY",
  "QUALIFICATION_KEY_UNANSWERABLE",
  "QUALIFICATION_SET_AMBIGUOUS",
  "QUALIFICATION_KEY_AMBIGUOUS",
  "QUALIFICATION_RUN_MISSING",
  "QUALIFICATION_SET_FILE_INVALID",
  "QUALIFICATION_SET_PATH_ESCAPES",
  "QUALIFICATION_SET_OVER_CEILING",
  "ORCHESTRATION_NOTHING_TO_PROVE",
  "ORCHESTRATION_ROUTE_NOT_PINNED",
  "ORCHESTRATION_NODE_NOT_IN_ROUTE",
  "ORCHESTRATION_BUILD_MOVED",
  "ORCHESTRATION_SOURCE_NOT_PINNED",
  "ORCHESTRATION_CITATION_LOST",
  "ORCHESTRATION_ARTIFACT_UNREADABLE",
  "VERDICT_INCOMPLETE",
  "VERDICT_BINDING_INVALID",
  "VERDICT_UNDECLARED_FIELD",
  "VERDICT_EXPIRED",
  "VERDICT_ALREADY_RECORDED",
  "QUALIFICATION_EVIDENCE_NOT_FOUND",
  "STORE_SCHEMA_DRIFT",
  "STORE_NOT_TRANSACTIONAL",
  "STORE_NOT_CONFIGURED",
  "STORE_UNAVAILABLE",
  "IDENTITY_UNAVAILABLE",
  "STREAM_LIMIT_REACHED",
]);
const RefusalBody = object({ code: RefusalCode, clears: text });
const QualificationState = enumOf(["QUALIFIED", "UNQUALIFIED", "RESTRICTED", "UNAVAILABLE"]);
const QualificationRead = object({
  evidence_sha256: hash,
  state: QualificationState,
  qualification_set_sha256: nullable(hash),
  performed_sha256: nullable(hash),
  build_id: nullable(short),
  adapter_version: nullable(short),
  provider: nullable(short),
  model: nullable(short),
  reviewer: nullable(text),
  decided_at: nullable(datetime),
  expires_at: nullable(datetime),
});

/** Every model `schema.json` declares, under its backend name. */
export const V1_SHAPES = {
  NarrativeFigure,
  NarrativeSpan,
  ReportArtifact,
  RevisionSummary,
  ReportBody,
  ReportDocument,
  FiledReceipt,
  CommitteeBody,
  CommitteeDocument,
  ModelValue,
  ModelPeriod,
  ModelForecast,
  ModelBody,
  ModelDocument,
  BookColumn,
  BookResearch,
  BookPassport,
  BookCell,
  BookPeriod,
  BookRow,
  BookBasis,
  BookBody,
  BookDocument,
  ActionName,
  ActionView,
  AnalysisBody,
  AnalysisDocument,
  AttemptView,
  BlockedByView,
  CaseRow,
  MemberRow,
  CellView,
  Chrome,
  CitationView,
  DirectoryBody,
  DirectoryDocument,
  EdgeType,
  EdgeView,
  EventName,
  FrameView,
  Gate,
  GateState,
  GateView,
  GlobalRole,
  HandoffView,
  NodeState,
  NodeView,
  PageBody,
  PageDocument,
  PageLine,
  PendingNode,
  RectView,
  RefusalBody,
  RefusalCode,
  QualificationRead,
  QualificationState,
  RouteChoice,
  RunBody,
  RunSectionDocument,
  RunSubjectView,
  RunSummary,
  RunView,
  SectionNote,
  ServedRole,
  SetVersion,
  SourceRow,
  Standing,
  Subject,
  TableView,
  UploadBody,
  UploadDocument,
  WorkView,
};

export type DirectoryDocument = Infer<typeof DirectoryDocument>;
export type UploadDocument = Infer<typeof UploadDocument>;
export type RunSectionDocument = Infer<typeof RunSectionDocument>;
export type AnalysisDocument = Infer<typeof AnalysisDocument>;
export type ModelDocument = Infer<typeof ModelDocument>;
export type BookDocument = Infer<typeof BookDocument>;
export type BookRow = Infer<typeof BookRow>;
export type BookCell = Infer<typeof BookCell>;
export type BookPassport = Infer<typeof BookPassport>;
export type BookColumn = Infer<typeof BookColumn>;
export type BookPeriod = Infer<typeof BookPeriod>;
export type ReportDocument = Infer<typeof ReportDocument>;
export type CommitteeDocument = Infer<typeof CommitteeDocument>;
export type RevisionSummary = Infer<typeof RevisionSummary>;
export type RefusalBody = Infer<typeof RefusalBody>;
export type RefusalCode = Infer<typeof RefusalCode>;
export type QualificationRead = Infer<typeof QualificationRead>;
export type QualificationState = Infer<typeof QualificationState>;
export type Chrome = Infer<typeof Chrome>;
export type CaseRow = Infer<typeof CaseRow>;
export type MemberRow = Infer<typeof MemberRow>;
export type SourceRow = Infer<typeof SourceRow>;
export type RunView = Infer<typeof RunView>;
export type NodeView = Infer<typeof NodeView>;
export type HandoffView = Infer<typeof HandoffView>;
export type TableView = Infer<typeof TableView>;
export type CellView = Infer<typeof CellView>;
export type CitationView = Infer<typeof CitationView>;
export type PendingNode = Infer<typeof PendingNode>;
export type EventName = Infer<typeof EventName>;
export type FrameView = Infer<typeof FrameView>;
export type PageLine = Infer<typeof PageLine>;
export type PageDocument = Infer<typeof PageDocument>;
export type ActionView = Infer<typeof ActionView>;
export type WorkView = Infer<typeof WorkView>;
export type RouteChoice = Infer<typeof RouteChoice>;
export type SectionDocument =
  | DirectoryDocument
  | UploadDocument
  | RunSectionDocument
  | AnalysisDocument
  | ModelDocument
  | BookDocument
  | ReportDocument
  | CommitteeDocument;

export const parseDirectoryDocument = (value: unknown): DirectoryDocument =>
  parse(DirectoryDocument, value);
export const parseUploadDocument = (value: unknown): UploadDocument => parse(UploadDocument, value);
export const parseRunSectionDocument = (value: unknown): RunSectionDocument =>
  parse(RunSectionDocument, value);
export const parseAnalysisDocument = (value: unknown): AnalysisDocument =>
  parse(AnalysisDocument, value);
export const parseModelDocument = (value: unknown): ModelDocument => parse(ModelDocument, value);
export const parseBookDocument = (value: unknown): BookDocument => parse(BookDocument, value);
export const parseReportDocument = (value: unknown): ReportDocument => parse(ReportDocument, value);
export const parseCommitteeDocument = (value: unknown): CommitteeDocument =>
  parse(CommitteeDocument, value);
export const parseRefusalBody = (value: unknown): RefusalBody => parse(RefusalBody, value);
export const parseQualificationRead = (value: unknown): QualificationRead =>
  parse(QualificationRead, value);
export const parsePageDocument = (value: unknown): PageDocument => parse(PageDocument, value);

export class WireIdentityError extends Error {
  readonly code = "WIRE_IDENTITY_MISMATCH";
  constructor() {
    super("WIRE_IDENTITY_MISMATCH");
    this.name = "WireIdentityError";
  }
}

/** Two ids name one thing when they agree ignoring case; two absent ids do
    too, so a receipt with no filer matches a body with none. */
export function sameId(a: string | null | undefined, b: string | null | undefined): boolean {
  return (a ?? null)?.toLowerCase() === (b ?? null)?.toLowerCase();
}

/**
 * Refuse a document answering for another case or run than the one requested.
 * `caseId: null` is the case-less directory. `runId`, when given, must be the
 * displayed run; the latest run is a separate identity and is not compared.
 */
export function requireIdentity(
  doc: SectionDocument,
  expected: { caseId: string | null; runId?: string | null; revisionId?: string },
): void {
  const subject = doc.chrome.subject;
  if (!sameId(subject?.case_id, expected.caseId)) throw new WireIdentityError();
  if ("case_id" in doc.body && !sameId(doc.body.case_id, expected.caseId)) {
    throw new WireIdentityError();
  }
  if (expected.runId !== undefined) {
    if (!("displayed_run_id" in doc.body)) throw new WireIdentityError();
    if (!sameId(doc.body.displayed_run_id, expected.runId)) throw new WireIdentityError();
  }
  if (expected.revisionId !== undefined) {
    if (!("revision_id" in doc.body) || !sameId(doc.body.revision_id, expected.revisionId)) {
      throw new WireIdentityError();
    }
  }
  if ("receipt" in doc.body) {
    const { receipt } = doc.body;
    if (
      (doc.body.state === "frozen" && (receipt !== null || doc.body.filed_by !== null)) ||
      (doc.body.state === "filed" && (receipt === null || doc.body.filed_by === null))
    ) {
      throw new WireIdentityError();
    }
    if (receipt === null) return;
    if (
      !sameId(receipt.case_id, doc.body.case_id) ||
      !sameId(receipt.run_id, doc.body.displayed_run_id) ||
      !sameId(receipt.revision_id, doc.body.revision_id) ||
      receipt.payload_sha256 !== doc.body.payload_sha256 ||
      !sameId(receipt.frozen_by, doc.body.frozen_by) ||
      !sameId(receipt.filed_by, doc.body.filed_by) ||
      !doc.body.signed_by.some((signer) => sameId(signer, receipt.signed_by))
    )
      throw new WireIdentityError();
  }
}

/** Refuse an evidence page answering for another case, run, source or page. */
export function requirePageIdentity(
  doc: PageDocument,
  expected: { caseId: string; runId: string; sourceId: string; page: number },
): void {
  const body = doc.body;
  if (
    !sameId(body.case_id, expected.caseId) ||
    !sameId(body.run_id, expected.runId) ||
    !sameId(body.source_id, expected.sourceId) ||
    body.page !== expected.page
  ) {
    throw new WireIdentityError();
  }
}
