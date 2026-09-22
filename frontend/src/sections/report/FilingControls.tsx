// The filing chain's four governed writes (Task 12.1's routes, placed here by
// Task 12.2): save a revision from the run's accepted artifacts and this
// draft, sign the exact bytes on screen, freeze them, file them.
//
// Sign and freeze sit on Report rather than Committee because `read_committee`
// refuses a revision that is not frozen, so the Committee section can never
// offer the two acts that would make it one. Save is there for the same
// reason -- and it is the one act a run with no revision is offered, so the
// Report served without `?revision` is where a case's first revision is made
// and where that address is first set. Filing acts on an already-frozen revision, which is exactly what
// Committee serves; it sits here to keep the chain on one surface, not
// because Committee could not offer it.
//
// Every control renders from the document's own `chrome.actions` -- present
// and refused, never hidden -- and grants nothing: the three-actor rule, the
// digest each act binds and the head a draft was composed against are all
// checked at commit, under the case lock. A signer whose browser still offers
// "Freeze" is refused there, and that refusal is what this surface shows.
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import {
  fileDeliverable,
  freezeDeliverable,
  saveRevision,
  signOpinion,
  type CommandResult,
  type Intent,
} from "@/app/commands";
import { sectionUrl } from "@/app/transport";
import { RefusedControl } from "@/controls/RefusedControl";
import { CommandOutcome, useCommand } from "@/sections/run/controls";
import { citationsOf, figureToken, paragraphs, type CitationChoice } from "./figures";
import {
  parseReportDocument,
  type ActionView,
  type NarrativeDraft,
  type ReportDocument,
} from "@/wire/v1";

/** The Report document as it is now, re-read once after an act that changed
    it. Same `sectionUrl` and v1 parser every load uses; a value this file
    invents is never put on screen in its place. */
async function refetchReport(
  caseId: string,
  runId: string,
  revisionId: string,
): Promise<ReportDocument | null> {
  const url = sectionUrl("report", { case: caseId, run: runId, revision: revisionId });
  if (!url) return null;
  let response: Response;
  try {
    response = await fetch(url, { headers: { accept: "application/json" } });
  } catch {
    return null;
  }
  if (!response.ok) return null;
  try {
    return parseReportDocument(await response.json());
  } catch {
    return null;
  }
}

/** The saved revision the three revision-scoped acts name: its id and the
    digest on screen. Null on a run nothing has been saved from, where the
    document refuses all three `DELIVERABLE_NOT_FOUND` and nothing is sent. */
interface Saved {
  id: string;
  digest: string;
}

const choiceKey = (choice: { route_node_id: string; citation_index: number }) =>
  `${choice.route_node_id}#${choice.citation_index}`;

const choiceLabel = (choice: CitationChoice) =>
  `${choice.route_node_id} · p.${choice.page} · ${choice.matched_text}`;

/** The draft as it will be sent, each figure shown by the citation it names --
    or said to name none the served records carry, which the server will then
    refuse. What is read back after a save is the host's resolution, not this. */
function DraftPreview({
  narrative,
  choices,
}: {
  narrative: NarrativeDraft[][];
  choices: CitationChoice[];
}) {
  if (!narrative.some((spans) => spans.some((span) => span.figure))) return null;
  const byKey = new Map(choices.map((choice) => [choiceKey(choice), choice]));
  return (
    <div className="note" data-draft-preview>
      <p>Draft as it will be saved:</p>
      {narrative.map((spans, index) => (
        <p key={index}>
          {spans.map((span, spanIndex) => {
            if (!span.figure) return <span key={spanIndex}>{span.text}</span>;
            const choice = byKey.get(choiceKey(span.figure));
            return (
              <span key={spanIndex} data-draft-figure>
                {choice
                  ? `[${choiceLabel(choice)}]`
                  : `[${span.figure.route_node_id} · no such citation in this report]`}
              </span>
            );
          })}
        </p>
      ))}
    </div>
  );
}

/** The picker: every citation the served records carry, and a press that puts
    its marker into the draft at the caret. Editing, not a governed act, so it
    is offered whatever `chrome.actions` says; the save is what is judged. */
function FigurePicker({
  choices,
  onInsert,
}: {
  choices: CitationChoice[];
  onInsert: (choice: CitationChoice) => void;
}) {
  const [picked, setPicked] = useState(choices[0] ? choiceKey(choices[0]) : "");
  if (choices.length === 0) {
    return (
      <p className="note" data-figure-picker>
        No verified citation in this report, so no figure can be inserted.
      </p>
    );
  }
  const chosen = choices.find((choice) => choiceKey(choice) === picked) ?? choices[0]!;
  return (
    <div className="fld" data-figure-picker>
      <label htmlFor="figure-citation">Citation</label>
      <select
        id="figure-citation"
        value={choiceKey(chosen)}
        onChange={(event) => setPicked(event.target.value)}
      >
        {choices.map((choice) => (
          <option key={choiceKey(choice)} value={choiceKey(choice)}>
            {choiceLabel(choice)}
          </option>
        ))}
      </select>
      <button type="button" className="rb" onClick={() => onInsert(chosen)}>
        Insert figure
      </button>
    </div>
  );
}

function FilingAct({
  name,
  action,
  label,
  saved,
  send,
  onDone,
}: {
  /** The command this control is for, named whether or not the document
      judges it: a control drawn for an action `chrome.actions` omits is
      `ACTION_UNPLACED`, which a reader can only see if it is on screen. */
  name: string;
  action: ActionView | undefined;
  label: string;
  saved: Saved | null;
  send: (saved: Saved, intent: Intent) => Promise<CommandResult<{ payload_sha256: string }>>;
  onDone: (saved: Saved) => void;
}) {
  const { pending, result, run } = useCommand<{ payload_sha256: string }>();
  const refusal = action?.refusal ?? null;
  const verb = label.split(" ")[0]!;
  return (
    <div className="fld">
      <RefusedControl
        refusal={refusal}
        onClick={
          action
            ? () => {
                if (refusal || pending || !saved) return;
                // What this press asks for is what the idempotency key is
                // derived from. The label would key two presses of the same
                // button alike even when the revision or the digest beneath
                // them had moved; `_replay` refuses the mismatch, so keying on
                // the label fails closed rather than wrongly -- but it fails
                // where this asks the right question instead.
                const request = {
                  action: name,
                  revision_id: saved.id,
                  payload_sha256: saved.digest,
                };
                void run(request, (intent) => send(saved, intent)).then((outcome) => {
                  if (outcome.kind === "ok") onDone(saved);
                });
              }
            : undefined
        }
        className="rb"
        reasonDisplay="inline"
        data-action={name}
        aria-label={label}
      >
        {pending ? `${verb}…` : label}
      </RefusedControl>
      <CommandOutcome result={result} success={`${label}: done. Re-reading the report.`} />
    </div>
  );
}

export function FilingControls({
  document,
  onRefreshed,
}: {
  document: ReportDocument;
  onRefreshed: (next: ReportDocument) => void;
}) {
  const { body } = document;
  const [draft, setDraft] = useState("");
  const editor = useRef<HTMLTextAreaElement>(null);
  // Where the caret goes after a figure is inserted: set with the draft, and
  // placed once React has written the new value, which moves the caret.
  const caret = useRef<number | null>(null);
  useLayoutEffect(() => {
    const at = caret.current;
    if (at === null || !editor.current) return;
    caret.current = null;
    editor.current.focus();
    editor.current.setSelectionRange(at, at);
  }, [draft]);
  const [, setParams] = useSearchParams();
  const [refreshFailed, setRefreshFailed] = useState(false);
  const save = useCommand<{ revision_id: string }>();
  const actionOf = (name: string) => document.chrome.actions.find((a) => a.action === name);
  const saved: Saved | null =
    body.revision_id !== null && body.payload_sha256 !== null
      ? { id: body.revision_id, digest: body.payload_sha256 }
      : null;

  async function reread(acted: Saved) {
    setRefreshFailed(false);
    const next = await refetchReport(body.case_id, body.displayed_run_id, acted.id);
    if (next) onRefreshed(next);
    else setRefreshFailed(true);
  }

  const saveAction = actionOf("SAVE_REVISION");
  const narrative = paragraphs(draft);
  // Parsed once per served document, not per keystroke: a record may be large.
  const choices = useMemo(() => citationsOf(body.artifacts), [body.artifacts]);

  function insert(choice: CitationChoice) {
    const token = figureToken(choice.route_node_id, choice.citation_index);
    const start = editor.current?.selectionStart ?? draft.length;
    const end = editor.current?.selectionEnd ?? start;
    caret.current = start + token.length;
    setDraft(draft.slice(0, start) + token + draft.slice(end));
  }
  // The served revision is the head this draft was composed against; on a run
  // with none it is null, which is what a first save names.
  const request = { expected_revision_id: body.revision_id, narrative };

  return (
    <section className="pnl" data-filing-controls>
      <header>
        <h2>Filing</h2>
        <span className="cp">SAVE · SIGN · FREEZE · FILE</span>
      </header>
      <div className="pb">
        <label className="fld" htmlFor="narrative-draft">
          Narrative draft
        </label>
        <textarea
          id="narrative-draft"
          ref={editor}
          value={draft}
          rows={4}
          placeholder="One paragraph per line."
          aria-describedby="narrative-draft-rule"
          onChange={(event) => setDraft(event.target.value)}
        />
        <p className="note" id="narrative-draft-rule">
          Type prose only. Every figure goes in through the citation picker, which names a citation
          of a verified record; prose carrying a digit is refused at save.
        </p>
        <FigurePicker key={choices.map(choiceKey).join(" ")} choices={choices} onInsert={insert} />
        <DraftPreview narrative={narrative} choices={choices} />
        <div className="fld">
          <RefusedControl
            refusal={saveAction?.refusal ?? null}
            onClick={
              saveAction
                ? () => {
                    if (saveAction.refusal || save.pending) return;
                    void save
                      .run(request, (intent) =>
                        saveRevision(body.case_id, body.displayed_run_id, request, intent),
                      )
                      .then((outcome) => {
                        if (outcome.kind !== "ok") return;
                        setDraft("");
                        // The address is corrected, not navigated: the reader
                        // did not move, the run gained a newer revision, and a
                        // reload shows the one they are looking at.
                        setParams(
                          (current) => {
                            const next = new URLSearchParams(current);
                            next.set("revision", outcome.receipt.revision_id);
                            return next;
                          },
                          { replace: true },
                        );
                      });
                  }
                : undefined
            }
            className="rb solid"
            reasonDisplay="inline"
            data-action="SAVE_REVISION"
            aria-label="Save revision"
          >
            {save.pending ? "Saving…" : "Save revision"}
          </RefusedControl>
          {save.result?.kind === "ok" ? (
            <p className="note ok" data-revision-saved>
              Revision {save.result.receipt.revision_id} saved.
            </p>
          ) : (
            <CommandOutcome result={save.result} success="" />
          )}
        </div>
        <FilingAct
          name="SIGN_OPINION"
          saved={saved}
          action={actionOf("SIGN_OPINION")}
          label="Sign opinion"
          send={(on, intent) => signOpinion(body.case_id, on.id, on.digest, intent)}
          onDone={(on) => void reread(on)}
        />
        <FilingAct
          name="FREEZE_DELIVERABLE"
          saved={saved}
          action={actionOf("FREEZE_DELIVERABLE")}
          label="Freeze deliverable"
          send={(on, intent) => freezeDeliverable(body.case_id, on.id, on.digest, intent)}
          onDone={(on) => void reread(on)}
        />
        <FilingAct
          name="FILE_DELIVERABLE"
          saved={saved}
          action={actionOf("FILE_DELIVERABLE")}
          label="File deliverable"
          send={(on, intent) => fileDeliverable(body.case_id, on.id, on.digest, intent)}
          onDone={(on) => void reread(on)}
        />
        {refreshFailed ? (
          <p className="note warn" role="alert" data-filing-refresh-failed>
            The act landed, but the report could not be re-read. Reload to see it.
          </p>
        ) : null}
      </div>
    </section>
  );
}
