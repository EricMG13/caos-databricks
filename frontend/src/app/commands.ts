// The minimal governed command wiring the journey needs (brief 4.2, decision
// 12). One `crypto.randomUUID()` key per user intent: reused when the caller
// retries the same intent after a network failure, and replaced by the
// caller after any server answer (success or refusal) for the next intent.
//
// Every result is a discriminated union, never an exception the caller must
// catch: `ok` (a validated receipt), `refused` (a typed refusal with its
// clearance), `error` (a body that is neither) or `offline` (the request
// never reached the server). Nothing parsed here is cast — every receipt is
// narrowed by its matching v1 parser.
import type {
  ApproveGate,
  DeliverableFiled,
  DeliverableFrozen,
  OpinionSigned,
  RevisionSaved,
  SaveRevision,
  CancelRun,
  CaseCreated,
  CreateCase,
  CreateRun,
  GateApproved,
  GatePreviewDocument,
  GrantStanding,
  Infer,
  PinRunInput,
  RunCreated,
  RunInputPinned,
  RunWork,
  StandingGranted,
  StandingRevoked,
} from "@/wire/v1";
import {
  WireShapeError,
  parseCaseCreated,
  parseGateApproved,
  parseGatePreviewDocument,
  parseRefusalBody,
  parseRunCreated,
  parseRunInputPinned,
  parseRunWork,
  parseDeliverableFiled,
  parseDeliverableFrozen,
  parseOpinionSigned,
  parseRevisionSaved,
  parseSourceWithdrawn,
  parseSourcesAdmitted,
  parseStandingGranted,
  parseStandingRevoked,
  type RefusalBody,
  type SourceWithdrawn,
  type SourcesAdmitted,
  type V1_SHAPES,
} from "@/wire/v1";
import { OFFLINE_WORDING, bodyOf } from "./transport";

/** Drawn from the shared shapes rather than redeclared here. */
type Gate = Infer<typeof V1_SHAPES.Gate>;
type RunSubjectView = Infer<typeof V1_SHAPES.RunSubjectView>;
type Standing = Infer<typeof V1_SHAPES.Standing>;

/** One key per user intent. Reuse it to retry after `{ kind: "offline" }`;
    draw a fresh one (`newIntent`) once any server answer has been seen. */
export interface Intent {
  readonly key: string;
}

export function newIntent(): Intent {
  return { key: crypto.randomUUID() };
}

export type CommandResult<R> =
  | { kind: "ok"; status: number; receipt: R; replayed: boolean }
  | { kind: "refused"; refusal: RefusalBody }
  | { kind: "error"; code: "RESPONSE_INVALID" }
  | { kind: "offline" };

interface CommandRequest {
  method: "GET" | "POST";
  url: string;
  body?: BodyInit;
  contentType?: string;
}

/** Why a command did not succeed, as the one sentence a control shows. Every
    control says the same thing for the same outcome, which is why this lives
    beside the commands rather than in each control that calls one. `ok` has no
    failure to describe and is refused here rather than given a placeholder. */
export function failureMessage<R>(result: CommandResult<R>): string {
  switch (result.kind) {
    case "refused":
      return `${result.refusal.code} — clears when ${result.refusal.clears}`;
    case "error":
      return result.code;
    case "offline":
      return OFFLINE_WORDING;
    default:
      throw new Error("a successful command has no failure to describe");
  }
}

const RESPONSE_INVALID = { kind: "error", code: "RESPONSE_INVALID" } as const;

/** The primitive every command below builds on: one fetch, classified into
    the four-way result above. A POST carries the intent's key; a GET (the
    gate preview) carries none, since it makes no governed write to replay. */
export async function sendCommand<R>(
  intent: Intent,
  request: CommandRequest,
  parseReceipt: (value: unknown) => R,
): Promise<CommandResult<R>> {
  const headers: Record<string, string> = { accept: "application/json" };
  if (request.contentType !== undefined) headers["content-type"] = request.contentType;
  if (request.method === "POST") headers["Idempotency-Key"] = intent.key;

  let response: Response;
  try {
    response = await fetch(request.url, {
      method: request.method,
      headers,
      ...(request.body === undefined ? {} : { body: request.body }),
    });
  } catch {
    return { kind: "offline" };
  }

  const body = await bodyOf(response);
  if (response.ok) {
    try {
      return {
        kind: "ok",
        status: response.status,
        receipt: parseReceipt(body),
        replayed: response.headers.get("Idempotency-Replayed") === "true",
      };
    } catch (error) {
      if (error instanceof WireShapeError) return RESPONSE_INVALID;
      throw error;
    }
  }
  try {
    return { kind: "refused", refusal: parseRefusalBody(body) };
  } catch (error) {
    if (error instanceof WireShapeError) return RESPONSE_INVALID;
    throw error;
  }
}

function jsonCommand<R>(
  intent: Intent,
  url: string,
  request: object,
  parseReceipt: (value: unknown) => R,
): Promise<CommandResult<R>> {
  return sendCommand(
    intent,
    { method: "POST", url, body: JSON.stringify(request), contentType: "application/json" },
    parseReceipt,
  );
}

const GATE_SLUG: Record<Gate, string> = {
  SOURCE_SET: "source-set",
  RESEARCH_PLAN: "research-plan",
};

function casePath(caseId: string): string {
  return `/api/v1/cases/${encodeURIComponent(caseId)}`;
}

function runPath(caseId: string, runId: string): string {
  return `${casePath(caseId)}/runs/${encodeURIComponent(runId)}`;
}

export function createCase(
  title: CreateCase["title"],
  intent: Intent = newIntent(),
): Promise<CommandResult<CaseCreated>> {
  return jsonCommand(intent, "/api/v1/cases", { title }, parseCaseCreated);
}

/** Multipart, with every file carried as a `document` part; brief 4.2
    decision 4. The browser draws its own boundary, so no content type is
    declared here. */
export function admitSources(
  caseId: string,
  files: readonly File[],
  intent: Intent = newIntent(),
): Promise<CommandResult<SourcesAdmitted>> {
  const form = new FormData();
  for (const file of files) form.append("document", file);
  return sendCommand(
    intent,
    { method: "POST", url: `${casePath(caseId)}/sources`, body: form },
    parseSourcesAdmitted,
  );
}

export function createRun(
  caseId: string,
  request: CreateRun,
  intent: Intent = newIntent(),
): Promise<CommandResult<RunCreated>> {
  return jsonCommand(intent, `${casePath(caseId)}/runs`, request, parseRunCreated);
}

export function pinRunInput(
  caseId: string,
  runId: string,
  subject: RunSubjectView,
  intent: Intent = newIntent(),
): Promise<CommandResult<RunInputPinned>> {
  const request: PinRunInput = { subject };
  return jsonCommand(intent, `${runPath(caseId, runId)}/input`, request, parseRunInputPinned);
}

/** The one GET among these commands: a preview grants nothing and carries no
    idempotency key (brief 4.2, decisions 1 and 6). */
export function fetchGatePreview(
  caseId: string,
  runId: string,
  gate: Gate,
  intent: Intent = newIntent(),
): Promise<CommandResult<GatePreviewDocument>> {
  const url = `${runPath(caseId, runId)}/gates/${GATE_SLUG[gate]}/preview`;
  return sendCommand(intent, { method: "GET", url }, parseGatePreviewDocument);
}

export function approveGate(
  caseId: string,
  runId: string,
  gate: Gate,
  approval: ApproveGate,
  intent: Intent = newIntent(),
): Promise<CommandResult<GateApproved>> {
  const url = `${runPath(caseId, runId)}/gates/${GATE_SLUG[gate]}/approval`;
  return jsonCommand(intent, url, approval, parseGateApproved);
}

export function startRun(
  caseId: string,
  runId: string,
  request: { input_fingerprint: string },
  intent: Intent = newIntent(),
): Promise<CommandResult<RunWork>> {
  return jsonCommand(intent, `${runPath(caseId, runId)}/start`, request, parseRunWork);
}

export function retryRun(
  caseId: string,
  runId: string,
  request: { input_fingerprint: string },
  intent: Intent = newIntent(),
): Promise<CommandResult<RunWork>> {
  return jsonCommand(intent, `${runPath(caseId, runId)}/retry`, request, parseRunWork);
}

export function cancelRun(
  caseId: string,
  runId: string,
  intent: Intent = newIntent(),
): Promise<CommandResult<RunWork>> {
  const request: CancelRun = {};
  return jsonCommand(intent, `${runPath(caseId, runId)}/cancel`, request, parseRunWork);
}

/** Invariant 1's second half: a pinned source is withdrawn, never deleted, and
    the body is empty because the source is named in the path (Task 12.1). */
export function withdrawSource(
  caseId: string,
  sourceId: string,
  intent: Intent = newIntent(),
): Promise<CommandResult<SourceWithdrawn>> {
  const url = `${casePath(caseId)}/sources/${encodeURIComponent(sourceId)}/withdrawal`;
  return jsonCommand(intent, url, {}, parseSourceWithdrawn);
}

/** Give or replace one member's standing (O21). The member is named; the
    actor granting it is derived and holds ADMIN on the case. */
export function grantStanding(
  caseId: string,
  userId: string,
  standing: Standing,
  intent: Intent = newIntent(),
): Promise<CommandResult<StandingGranted>> {
  const request: GrantStanding = { user_id: userId, standing };
  return jsonCommand(intent, `${casePath(caseId)}/members`, request, parseStandingGranted);
}

/** End one membership; the member is in the path, so the body is empty. */
export function revokeStanding(
  caseId: string,
  userId: string,
  intent: Intent = newIntent(),
): Promise<CommandResult<StandingRevoked>> {
  const url = `${casePath(caseId)}/members/${encodeURIComponent(userId)}/revocation`;
  return jsonCommand(intent, url, {}, parseStandingRevoked);
}

function revisionPath(caseId: string, revisionId: string): string {
  return `${casePath(caseId)}/revisions/${encodeURIComponent(revisionId)}`;
}

/** A draft is the only thing of the payload that comes from the request; the
    revision is derived from the run's accepted artifacts. `expected_revision_id`
    is the head the draft was composed against, so a save that raced another
    save is refused rather than becoming a second head nobody chose. */
export function saveRevision(
  caseId: string,
  runId: string,
  request: SaveRevision,
  intent: Intent = newIntent(),
): Promise<CommandResult<RevisionSaved>> {
  return jsonCommand(intent, `${runPath(caseId, runId)}/revisions`, request, parseRevisionSaved);
}

/** The three acts on one stored revision. Each carries the `payload_sha256`
    its actor reviewed (invariant 5): the server compares it before writing,
    so an approver acting on bytes other than the ones in front of them is
    refused rather than binding a signature to something unread. */
export function signOpinion(
  caseId: string,
  revisionId: string,
  payloadSha256: string,
  intent: Intent = newIntent(),
): Promise<CommandResult<OpinionSigned>> {
  const url = `${revisionPath(caseId, revisionId)}/signature`;
  return jsonCommand(intent, url, { payload_sha256: payloadSha256 }, parseOpinionSigned);
}

export function freezeDeliverable(
  caseId: string,
  revisionId: string,
  payloadSha256: string,
  intent: Intent = newIntent(),
): Promise<CommandResult<DeliverableFrozen>> {
  const url = `${revisionPath(caseId, revisionId)}/freeze`;
  return jsonCommand(intent, url, { payload_sha256: payloadSha256 }, parseDeliverableFrozen);
}

export function fileDeliverable(
  caseId: string,
  revisionId: string,
  payloadSha256: string,
  intent: Intent = newIntent(),
): Promise<CommandResult<DeliverableFiled>> {
  const url = `${revisionPath(caseId, revisionId)}/filing`;
  return jsonCommand(intent, url, { payload_sha256: payloadSha256 }, parseDeliverableFiled);
}
