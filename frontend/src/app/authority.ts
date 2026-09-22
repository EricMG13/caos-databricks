// The one authority machine (IA_SPEC.md 5, "Route replay"). A forwarded slug,
// a back navigation and a cross-case race are all resolved here against stale
// responses: a late response for a case the user has left is discarded. Pure;
// no I/O.
//
// `bind`, `release`, `Binding` and `Authority.bound` are the Book's
// one-snapshot-per-compared-case rule. They had no production caller while the
// Book was its unavailable shell and were kept rather than deleted, because
// `test_book_binds_one_snapshot_per_compared_case` is pinned by name in
// `tests/test_phase_exits.py` and deleting them would have meant editing a
// gate to make a gate pass. Task 12.3 gave them their caller back: the Book
// section binds each credit through `@/app/ledger`, and only the explicit lens
// switch moves a binding.
import type { EnabledSection } from "./sections";
import type { Refusal, Section } from "@/wire";
import type { EventName, SectionDocument } from "@/wire/v1";

export interface Authority {
  /** The case on screen, or null when the section is not about one case. */
  case: string | null;
  /** Monotonic per navigation; a response carries the seq it was sent under. */
  seq: number;
  /** The snapshot each compared case is bound to, by case id. */
  bound: Readonly<Record<string, string>>;
}

export interface Ticket {
  case: string | null;
  seq: number;
}

export const INITIAL: Authority = { case: null, seq: 0, bound: {} };

export function navigate(authority: Authority, caseId: string | null): Authority {
  return { ...authority, case: caseId, seq: authority.seq + 1 };
}

/** A new request under the current case: only the latest issued one renders. */
export function issue(authority: Authority): Authority {
  return { ...authority, seq: authority.seq + 1 };
}

export function ticket(authority: Authority): Ticket {
  return { case: authority.case, seq: authority.seq };
}

/** True only for the response of the current (case, seq). Anything else is late. */
export function accepts(authority: Authority, sent: Ticket): boolean {
  return sent.seq === authority.seq && sent.case === authority.case;
}

export interface Binding {
  authority: Authority;
  refusal: Refusal | null;
}

/** Bind a compared case to the snapshot a response carries. A late response
    carrying a different snapshot for an already-bound case is refused. */
export function bind(authority: Authority, caseId: string, snapshot: string): Binding {
  const held = authority.bound[caseId];
  if (held !== undefined && held !== snapshot) {
    return {
      authority,
      refusal: {
        code: "SNAPSHOT_MISMATCH",
        clears: `The comparison stays on ${held} for ${caseId}; switch the lens explicitly to move it.`,
      },
    };
  }
  if (held === snapshot) return { authority, refusal: null };
  return {
    authority: { ...authority, bound: { ...authority.bound, [caseId]: snapshot } },
    refusal: null,
  };
}

/** An explicit lens switch is the only way a binding moves. */
export function release(authority: Authority, caseId: string): Authority {
  const bound = { ...authority.bound };
  delete bound[caseId];
  return { ...authority, bound };
}

/** Which sections each event name refetches (brief 4.4, decision 2). */
export const REFETCHES: Readonly<Record<EventName, readonly EnabledSection[]>> = {
  run_progress: ["run"],
  handoff_accepted: ["run", "analysis", "model"],
  run_terminal: ["run", "analysis", "model"],
  sources_changed: ["upload", "run", "analysis", "model", "report", "committee"],
  runs_changed: ["run", "analysis", "model"],
  filing_changed: ["report", "committee"],
};

/** Whether any event at all moves this section, which is whether a stream over
    it is worth holding. Book is portfolio-scoped: no case event names it, so a
    tail opened over one could only ever hold a worker thread and one of the
    API's concurrency slots for its whole deadline. */
export function tailed(section: Section): boolean {
  return Object.values(REFETCHES).some((sections) =>
    (sections as readonly string[]).includes(section),
  );
}

export function refetches(name: EventName, section: Section): boolean {
  return (REFETCHES[name] as readonly string[]).includes(section);
}

/** The run a view is about: Run's shown run, Analysis's displayed run. */
export function displayedRunIdOf(section: Section, doc: SectionDocument): string | null {
  const body = doc.body;
  if (section === "run" && "run" in body) return body.run?.run_id ?? null;
  if (section === "analysis" && "handoffs" in body) return body.displayed_run_id;
  if (section === "model" && "forecast" in body) return body.displayed_run_id;
  if (section === "report" && "revision_id" in body) return body.displayed_run_id;
  if (section === "committee" && "revision_id" in body) return body.displayed_run_id;
  return null;
}

/** What a view's figures are about (decision 6). A refetch under the same
    identity replaces the view; a different one waits for Reload. Directory
    and Upload have none and always refresh. */
export function analyticalIdentity(section: Section, doc: SectionDocument): string | null {
  const body = doc.body;
  if (section === "run" && "run" in body) return body.run?.run_id ?? "";
  if (section === "analysis" && "handoffs" in body) {
    const records = body.handoffs
      .map((handoff) => handoff.record_sha256)
      .sort((a, b) => a.localeCompare(b));
    return `${body.displayed_run_id ?? ""}|${records.join(",")}`;
  }
  if (section === "model" && "forecast" in body) {
    const forecast = body.forecast;
    return `${body.displayed_run_id ?? ""}|${forecast ? `${forecast.record_sha256}|${forecast.artifact_sha256}` : "NO_ACCEPTED_FORECAST"}`;
  }
  if (section === "report" && "revision_id" in body) {
    return `${body.revision_id}|${body.payload_sha256}`;
  }
  if (section === "committee" && "revision_id" in body) {
    return `${body.revision_id}|${body.payload_sha256}`;
  }
  if (section === "book" && "basis" in body) {
    // Every compared credit's snapshot, so a document moving any one of them
    // waits for Reload rather than replacing figures under a lens still bound
    // to the old snapshot. Without this the row drew the new digest, the new
    // figures, and a note saying the comparison had stayed on the old one.
    const snapshots = body.rows
      .map((row) => `${row.case_id}=${row.snapshot ?? ""}`)
      .sort((a, b) => a.localeCompare(b));
    return snapshots.join(",");
  }
  return null;
}

/** Every withdrawn source a document names, by source id. */
export function withdrawalsOf(doc: SectionDocument): ReadonlyMap<string, string> {
  const withdrawn = new Map<string, string>();
  const body = doc.body;
  if ("handoffs" in body) {
    for (const handoff of body.handoffs) {
      for (const fact of handoff.source_facts) {
        if (fact.withdrawn_at !== null) withdrawn.set(fact.source_id, fact.withdrawn_at);
      }
    }
  }
  if ("sources" in body) {
    for (const source of body.sources) {
      if (source.withdrawn_at !== null) withdrawn.set(source.source_id, source.withdrawn_at);
    }
  }
  return withdrawn;
}

/** A safety change applied to the displayed view: citations of a withdrawn
    source say so, and no figure moves. A document with nothing to mark is
    returned as it is. */
export function withWithdrawals<D extends SectionDocument>(
  doc: D,
  withdrawals: ReadonlyMap<string, string>,
): D {
  const body = doc.body;
  if (!("handoffs" in body) || withdrawals.size === 0) return doc;
  const marked = (id: string, at: string | null) => at ?? withdrawals.get(id) ?? null;
  return {
    ...doc,
    body: {
      ...body,
      handoffs: body.handoffs.map((handoff) => ({
        ...handoff,
        source_facts: handoff.source_facts.map((fact) => ({
          ...fact,
          withdrawn_at: marked(fact.source_id, fact.withdrawn_at),
        })),
      })),
    },
  };
}
