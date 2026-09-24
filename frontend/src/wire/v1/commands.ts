// The v1 command requests, receipts and the gate preview, one shape per model
// in `caos/api/wire.py`'s `V1_COMMANDS` (brief 4.2, decision 11). Every
// receipt and preview is validated here before use; nothing is cast.
//
// A request carries no actor, case, run or approver: the server derives them
// from the caller and the path. Digests it carries are expectations.
import { V1_SHAPES } from "./documents";
import {
  type Infer,
  array,
  bool,
  datetime,
  enumOf,
  int,
  nullable,
  object,
  parse,
  string,
  uuid,
} from "./shape";

const hash = string({ max: 64, pattern: "^[0-9a-f]{64}$" });
const short = string({ max: 256 });
const RUN_STATUSES = ["RUNNING", "COMPLETE", "FAILED", "BLOCKED", "CANCELLED"] as const;

const CreateCase = object({ title: string({ max: 256 }) });
const CaseCreated = object({ case_id: uuid });
const SourcesAdmitted = object({ case_id: uuid, source_ids: array(uuid, 50) });
// `supersedes` is stated on every request, null for an ordinary run: the
// BLOCKED run of the path's case the new run answers (§72). `model_extension`
// is stated too: whether the route carries CP-CF, a route-selection input the
// pinned digest covers.
const CreateRun = object({
  profile_id: short,
  selection_id: short,
  supersedes: nullable(uuid),
  model_extension: bool,
});
const RunCreated = object({ case_id: uuid, run_id: uuid, route_digest: hash });
const PinRunInput = object({ subject: V1_SHAPES.RunSubjectView });
const RunInputPinned = object({ run_id: uuid, source_set_version: int(), input_fingerprint: hash });
const GatePreviewDocument = object({
  run_id: uuid,
  gate: V1_SHAPES.Gate,
  content: string({ max: 26214400 }),
  preview_sha256: hash,
  input_fingerprint: hash,
  observed_at: datetime,
});
const ApproveGate = object({ preview_sha256: hash, input_fingerprint: hash });
const GateApproved = object({
  run_id: uuid,
  gate: V1_SHAPES.Gate,
  preview_sha256: hash,
  input_fingerprint: hash,
});
const StartRun = object({ input_fingerprint: hash });
const RetryRun = object({ input_fingerprint: hash });
const CancelRun = object({});
const RunWork = object({
  run_id: uuid,
  run_status: enumOf(RUN_STATUSES),
  work: V1_SHAPES.WorkView,
});
// A verdict is the reviewer's document: the moments travel as text and are
// read once, by the server's verdict reader. The receipt is the host's.
// `evidence_sha256` names the exact evidence identity the document was read
// against (N44): the other six can agree for two different snapshots of the
// same set, build and provider.
const moment = string({ max: 64 });
const SignVerdict = object({
  provider: short,
  qualification_set_sha256: hash,
  build_id: short,
  decided_at: moment,
  expires_at: moment,
  reviewer: short,
  evidence_sha256: hash,
});
const VerdictRecorded = object({
  evidence_sha256: hash,
  reviewer_id: uuid,
  decided_at: datetime,
  expires_at: datetime,
});

// Task 12.1's seven governed writes. A membership command names the member it
// is about; every other actor on the wire is derived from the caller and the
// path. A draft names only which citation a figure is, never its coordinates.
const GrantStanding = object({ user_id: uuid, standing: V1_SHAPES.Standing });
const StandingGranted = object({
  case_id: uuid,
  user_id: uuid,
  standing: V1_SHAPES.Standing,
});
const RevokeStanding = object({});
const StandingRevoked = object({ case_id: uuid, user_id: uuid });
const WithdrawSource = object({});
const SourceWithdrawn = object({ case_id: uuid, source_id: uuid });
const NarrativeFigureRef = object({ route_node_id: short, citation_index: int({ min: 0 }) });
const NarrativeDraft = object({
  text: nullable(string({ max: 2000 })),
  figure: nullable(NarrativeFigureRef),
});
const SaveRevision = object({
  expected_revision_id: nullable(uuid),
  narrative: array(array(NarrativeDraft, 64), 64),
});
const RevisionSaved = object({
  case_id: uuid,
  run_id: uuid,
  revision_id: uuid,
  payload_sha256: hash,
});
const SignOpinion = object({ payload_sha256: hash });
const OpinionSigned = object({
  case_id: uuid,
  revision_id: uuid,
  payload_sha256: hash,
  signed_by: uuid,
});
const FreezeDeliverable = object({ payload_sha256: hash });
const DeliverableFrozen = object({
  case_id: uuid,
  revision_id: uuid,
  payload_sha256: hash,
  frozen_by: uuid,
});
const FileDeliverable = object({ payload_sha256: hash });
const DeliverableFiled = object({
  case_id: uuid,
  run_id: uuid,
  revision_id: uuid,
  payload_sha256: hash,
  filed_by: uuid,
});

/** Every command model `schema.json` declares, under its backend name. */
export const V1_COMMAND_SHAPES = {
  ApproveGate,
  CancelRun,
  DeliverableFiled,
  DeliverableFrozen,
  FileDeliverable,
  FreezeDeliverable,
  GrantStanding,
  NarrativeDraft,
  NarrativeFigureRef,
  OpinionSigned,
  RevisionSaved,
  RevokeStanding,
  SaveRevision,
  SignOpinion,
  SourceWithdrawn,
  StandingGranted,
  StandingRevoked,
  WithdrawSource,
  CaseCreated,
  CreateCase,
  CreateRun,
  GateApproved,
  GatePreviewDocument,
  PinRunInput,
  RetryRun,
  RunCreated,
  RunInputPinned,
  RunWork,
  SignVerdict,
  SourcesAdmitted,
  StartRun,
  VerdictRecorded,
};

export type CreateCase = Infer<typeof CreateCase>;
export type CaseCreated = Infer<typeof CaseCreated>;
export type SourcesAdmitted = Infer<typeof SourcesAdmitted>;
export type CreateRun = Infer<typeof CreateRun>;
export type RunCreated = Infer<typeof RunCreated>;
export type PinRunInput = Infer<typeof PinRunInput>;
export type RunInputPinned = Infer<typeof RunInputPinned>;
export type GatePreviewDocument = Infer<typeof GatePreviewDocument>;
export type ApproveGate = Infer<typeof ApproveGate>;
export type GateApproved = Infer<typeof GateApproved>;
export type StartRun = Infer<typeof StartRun>;
export type RetryRun = Infer<typeof RetryRun>;
export type CancelRun = Infer<typeof CancelRun>;
export type RunWork = Infer<typeof RunWork>;
export type SignVerdict = Infer<typeof SignVerdict>;
export type VerdictRecorded = Infer<typeof VerdictRecorded>;
export type GrantStanding = Infer<typeof GrantStanding>;
export type StandingGranted = Infer<typeof StandingGranted>;
export type RevokeStanding = Infer<typeof RevokeStanding>;
export type StandingRevoked = Infer<typeof StandingRevoked>;
export type WithdrawSource = Infer<typeof WithdrawSource>;
export type SourceWithdrawn = Infer<typeof SourceWithdrawn>;
export type NarrativeFigureRef = Infer<typeof NarrativeFigureRef>;
export type NarrativeDraft = Infer<typeof NarrativeDraft>;
export type SaveRevision = Infer<typeof SaveRevision>;
export type RevisionSaved = Infer<typeof RevisionSaved>;
export type SignOpinion = Infer<typeof SignOpinion>;
export type OpinionSigned = Infer<typeof OpinionSigned>;
export type FreezeDeliverable = Infer<typeof FreezeDeliverable>;
export type DeliverableFrozen = Infer<typeof DeliverableFrozen>;
export type FileDeliverable = Infer<typeof FileDeliverable>;
export type DeliverableFiled = Infer<typeof DeliverableFiled>;

export const parseCaseCreated = (value: unknown): CaseCreated => parse(CaseCreated, value);
export const parseSourcesAdmitted = (value: unknown): SourcesAdmitted =>
  parse(SourcesAdmitted, value);
export const parseRunCreated = (value: unknown): RunCreated => parse(RunCreated, value);
export const parseRunInputPinned = (value: unknown): RunInputPinned => parse(RunInputPinned, value);
export const parseGatePreviewDocument = (value: unknown): GatePreviewDocument =>
  parse(GatePreviewDocument, value);
export const parseGateApproved = (value: unknown): GateApproved => parse(GateApproved, value);
export const parseRunWork = (value: unknown): RunWork => parse(RunWork, value);
// Task 12.2 places the controls for Task 12.1's routes; each receipt a placed
// control reads back is validated here.
export const parseSourceWithdrawn = (value: unknown): SourceWithdrawn =>
  parse(SourceWithdrawn, value);
export const parseRevisionSaved = (value: unknown): RevisionSaved => parse(RevisionSaved, value);
export const parseOpinionSigned = (value: unknown): OpinionSigned => parse(OpinionSigned, value);
export const parseDeliverableFrozen = (value: unknown): DeliverableFrozen =>
  parse(DeliverableFrozen, value);
export const parseDeliverableFiled = (value: unknown): DeliverableFiled =>
  parse(DeliverableFiled, value);
// Directory's membership controls (O21) read these two back.
export const parseStandingGranted = (value: unknown): StandingGranted =>
  parse(StandingGranted, value);
export const parseStandingRevoked = (value: unknown): StandingRevoked =>
  parse(StandingRevoked, value);
// No `parseVerdictRecorded`: the workspace has no control for it, and a
// validator nothing calls is coverage without a caller. Its shape is pinned
// above so the day one arrives it is validated, not cast.
