// One transport for every section document. A response becomes a RegionStatus,
// never an exception: the seven states of IA_SPEC.md 6 plus `ready`.
//
// URLs are versioned and case-scoped (brief 4.1, decision 1). Every enabled
// section reads the v1 wire (Directory and Upload since slice 4.1h, Run since
// 4.1i, Analysis since 4.1j); a disabled section sends no request at all, so
// no document it could carry is ever read here. Nothing parsed here is cast:
// every body is narrowed by a validator or a type predicate.
import { isEnabledSection, type EnabledSection } from "./sections";
import type { Refusal, Section } from "@/wire";
import {
  WireIdentityError,
  WireShapeError,
  parseAnalysisDocument,
  parseBookDocument,
  parseDirectoryDocument,
  parseModelDocument,
  parsePageDocument,
  parseCommitteeDocument,
  parseReportDocument,
  parseRefusalBody,
  parseQualificationRead,
  parseRunSectionDocument,
  parseUploadDocument,
  requireIdentity,
  sameId,
  type PageDocument,
  type QualificationRead,
  type SectionDocument as V1Document,
} from "@/wire/v1";

/** What a section region can hold. Every enabled section reads the v1 wire;
    a disabled section never fetches, so no other document shape reaches here. */
export type WorkspaceDocument = V1Document;

export type RegionStatus<D = WorkspaceDocument> =
  | { kind: "loading" }
  | { kind: "ready"; document: D }
  | { kind: "observed-empty"; observed_at: string; document: D }
  | {
      kind: "error";
      refusal: Refusal;
      /** The server's own `Retry-After`, where the refusal carried one. The
          event tail waits it out rather than guessing (finding FE-3). */
      retryAfterSeconds?: number;
    }
  | { kind: "unavailable" }
  | { kind: "stale"; document: D }
  | { kind: "offline" }
  | { kind: "partial"; document: D; notes: string[] };

export type StateKind = RegionStatus["kind"];

/** A private 404 and an absent route share one neutral wording. */
export const UNAVAILABLE_WORDING = "Unavailable or not permitted.";
/** An offline request renders one sentence and never engine text. */
export const OFFLINE_WORDING = "The request did not reach the server.";

export interface SectionQuery {
  case?: string | null;
  run?: string | null;
  revision?: string | null;
  fixture?: string | null;
}

const V1_PARSERS: Record<EnabledSection, (value: unknown) => V1Document> = {
  directory: parseDirectoryDocument,
  book: parseBookDocument,
  upload: parseUploadDocument,
  run: parseRunSectionDocument,
  analysis: parseAnalysisDocument,
  model: parseModelDocument,
  report: parseReportDocument,
  committee: parseCommitteeDocument,
};

/** The section's document URL, or null when no request may be sent: a
    disabled section, or a case section with no case. */
export function sectionUrl(section: Section, query: SectionQuery): string | null {
  if (!isEnabledSection(section)) return null;
  const params = new URLSearchParams();
  if (
    (section === "run" ||
      section === "analysis" ||
      section === "model" ||
      section === "report" ||
      section === "committee") &&
    query.run
  ) {
    params.set("run", query.run);
  }
  if ((section === "report" || section === "committee") && query.revision) {
    params.set("revision", query.revision);
  }
  // Only the demo build names a fixture; production folds this branch away.
  if (import.meta.env.MODE === "demo" && query.fixture) params.set("fixture", query.fixture);
  const search = params.toString();
  const suffix = search ? `?${search}` : "";
  if (section === "directory") return `/api/v1/directory${suffix}`;
  // Book is the portfolio, so it names no case and is served whether or not
  // one is selected.
  if (section === "book") return `/api/v1/book${suffix}`;
  if (!query.case) return null;
  // Report without a revision is the run's head, or its first save: nothing
  // else sets `?revision`, so a Report that needed one could never make one.
  // Committee serves only a named frozen revision.
  if (section === "report" && !query.run) return null;
  if (section === "committee" && (!query.run || !query.revision)) return null;
  return `/api/v1/cases/${encodeURIComponent(query.case)}/${section}${suffix}`;
}

const RESPONSE_INVALID: Refusal = {
  code: "RESPONSE_INVALID",
  clears: "the server answers with a typed refusal",
};

function refusalOf(body: unknown): Refusal {
  try {
    const refusal = parseRefusalBody(body);
    return { code: refusal.code, clears: refusal.clears };
  } catch (error) {
    if (error instanceof WireShapeError) return RESPONSE_INVALID;
    throw error;
  }
}

/** A refusal's `Retry-After`, in seconds, or null where it carried none or
    carried something that is not a count of seconds. An HTTP-date form is
    read as absent rather than guessed at against a clock this workspace does
    not trust. */
export function retryAfterOf(response: Response): number | null {
  const header = response.headers.get("Retry-After");
  if (header === null) return null;
  const seconds = Number(header.trim());
  return Number.isInteger(seconds) && seconds >= 0 ? seconds : null;
}

/** The status a refused response becomes, carrying its wait where it named one. */
function errorOf(response: Response, body: unknown): RegionStatus {
  const seconds = retryAfterOf(response);
  return {
    kind: "error",
    refusal: refusalOf(body),
    ...(seconds === null ? {} : { retryAfterSeconds: seconds }),
  };
}

/** The JSON a response carries, or null when it carries none that parses:
    a refusal is then typed from nothing rather than from an exception. */
export async function bodyOf(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

/** The whole document validated, then bound to the request. */
function classifyV1(section: EnabledSection, body: unknown, query: SectionQuery): RegionStatus {
  let document: V1Document;
  try {
    document = V1_PARSERS[section](body);
    const runId =
      section === "run" ||
      section === "analysis" ||
      section === "model" ||
      section === "report" ||
      section === "committee"
        ? query.run
        : null;
    requireIdentity(document, {
      caseId: section === "directory" || section === "book" ? null : (query.case ?? null),
      ...(runId ? { runId } : {}),
      ...((section === "report" || section === "committee") && query.revision
        ? { revisionId: query.revision }
        : {}),
    });
  } catch (error) {
    if (error instanceof WireShapeError) {
      return {
        kind: "error",
        refusal: { code: "WIRE_SHAPE_INVALID", clears: "the document is the declared v1 shape" },
      };
    }
    if (error instanceof WireIdentityError) {
      return {
        kind: "error",
        refusal: {
          code: "WIRE_IDENTITY_MISMATCH",
          clears: "the document answers for the case and run requested",
        },
      };
    }
    throw error;
  }
  if (document.observed_empty) {
    return { kind: "observed-empty", observed_at: document.observed_at, document };
  }
  if (document.status === "partial") {
    return { kind: "partial", document, notes: [...document.notes] };
  }
  return { kind: "ready", document };
}

export async function fetchSection(
  section: Section,
  query: SectionQuery,
  signal?: AbortSignal,
): Promise<RegionStatus> {
  const url = sectionUrl(section, query);
  if (url === null || !isEnabledSection(section)) return { kind: "unavailable" };
  let response: Response;
  try {
    response = await fetch(url, { signal, headers: { accept: "application/json" } });
  } catch {
    // A request that never reached the server. No engine text.
    return { kind: "offline" };
  }
  if (response.status === 404) return { kind: "unavailable" };
  if (!response.ok) return errorOf(response, await bodyOf(response));
  const body = await bodyOf(response);
  return classifyV1(section, body, query);
}

export type QualificationStatus =
  | { kind: "ready"; document: QualificationRead }
  | { kind: "error"; refusal: Refusal }
  | { kind: "unavailable" }
  | { kind: "offline" };

/** Qualification is global evidence, so its immutable identity travels as a hash. */
export function qualificationUrl(evidenceSha256: string): string {
  return `/api/v1/qualification/${encodeURIComponent(evidenceSha256)}`;
}

/** Read one exact qualification result and reject a substituted response. */
export async function fetchQualification(
  evidenceSha256: string,
  signal?: AbortSignal,
): Promise<QualificationStatus> {
  let response: Response;
  try {
    response = await fetch(qualificationUrl(evidenceSha256), {
      signal,
      headers: { accept: "application/json" },
    });
  } catch {
    return { kind: "offline" };
  }
  if (response.status === 404) return { kind: "unavailable" };
  if (!response.ok) return { kind: "error", refusal: refusalOf(await bodyOf(response)) };
  try {
    const document = parseQualificationRead(await bodyOf(response));
    if (!sameId(document.evidence_sha256, evidenceSha256)) throw new WireIdentityError();
    return { kind: "ready", document };
  } catch (error) {
    if (error instanceof WireShapeError || error instanceof WireIdentityError) {
      return {
        kind: "error",
        refusal: {
          code:
            error instanceof WireIdentityError ? "WIRE_IDENTITY_MISMATCH" : "WIRE_SHAPE_INVALID",
          clears: "the qualification result is bound to the requested evidence",
        },
      };
    }
    throw error;
  }
}

// Evidence pages (brief 4.4, decision 7). Not a section document: no chrome,
// never cached. A page the server will not serve -- withdrawn, outside the
// run's pinned set, out of range, not permitted -- is one private 404 with no
// text, and becomes `unavailable` here with nothing carried from its body.

export interface PageQuery {
  caseId: string;
  runId: string;
  sourceId: string;
  page: number;
}

export type PageStatus =
  | { kind: "ready"; document: PageDocument }
  | { kind: "partial"; document: PageDocument }
  | { kind: "error"; refusal: Refusal }
  | { kind: "unavailable" }
  | { kind: "offline" };

export function pageUrl(query: PageQuery): string {
  const [caseId, runId, sourceId] = [query.caseId, query.runId, query.sourceId].map(
    encodeURIComponent,
  );
  return `/api/v1/cases/${caseId}/runs/${runId}/sources/${sourceId}/pages/${query.page}`;
}

/** One page, validated whole and bound to exactly what was requested. */
export async function fetchPage(query: PageQuery, signal?: AbortSignal): Promise<PageStatus> {
  let response: Response;
  try {
    response = await fetch(pageUrl(query), { signal, headers: { accept: "application/json" } });
  } catch {
    return { kind: "offline" };
  }
  if (response.status === 404) return { kind: "unavailable" };
  if (!response.ok) return { kind: "error", refusal: refusalOf(await bodyOf(response)) };
  let document: PageDocument;
  try {
    document = parsePageDocument(await bodyOf(response));
  } catch (error) {
    if (!(error instanceof WireShapeError)) throw error;
    return {
      kind: "error",
      refusal: { code: "WIRE_SHAPE_INVALID", clears: "the page is the declared v1 shape" },
    };
  }
  const { body } = document;
  const bound =
    sameId(body.case_id, query.caseId) &&
    sameId(body.run_id, query.runId) &&
    sameId(body.source_id, query.sourceId) &&
    body.page === query.page;
  if (!bound) {
    return {
      kind: "error",
      refusal: {
        code: "WIRE_IDENTITY_MISMATCH",
        clears: "the page answers for the case, run, source and page requested",
      },
    };
  }
  return document.status === "partial"
    ? { kind: "partial", document }
    : { kind: "ready", document };
}
