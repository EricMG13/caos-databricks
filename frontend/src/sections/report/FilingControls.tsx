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
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { CheckIcon } from "lucide-react";
import {
  fileDeliverable,
  freezeDeliverable,
  saveRevision,
  signOpinion,
  type CommandResult,
  type Intent,
} from "@/app/commands";
import { sectionUrl } from "@/app/transport";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ConfirmedControl } from "@/controls/ConfirmedControl";
import { RefusedControl } from "@/controls/RefusedControl";
import { CommandOutcome, useCommand } from "@/sections/run/controls";
import { citationsOf, figureMarker, paragraphs, type CitationChoice } from "./figures";
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

/** The chain's four acts in the order they happen. */
const FILING = ["SAVE_REVISION", "SIGN_OPINION", "FREEZE_DELIVERABLE", "FILE_DELIVERABLE"] as const;
export type FilingStep = "done" | "current" | "open";

/** How far the shown revision has gone along save, sign, freeze and file
    (brief 6.11), from what the document says and nothing else: saved once a
    revision exists, signed and frozen once it is frozen (the Report carries
    no signatures, and a frozen revision was signed), filed once filed. The
    current step is the first not done that is offered; there is none when
    nothing is. */
export function filingSteps(
  state: "saved" | "frozen" | "filed" | null,
  offered: (action: (typeof FILING)[number]) => boolean,
): FilingStep[] {
  const done = [
    state !== null,
    state !== null && state !== "saved",
    state !== null && state !== "saved",
    state === "filed",
  ];
  const current = FILING.findIndex((action, at) => !done[at] && offered(action));
  return FILING.map((_, at) => (done[at] ? "done" : at === current ? "current" : "open"));
}

/** One step of the chain: its number, or a check once done, and its name. */
function StepHead({ at, name, step }: { at: number; name: string; step: FilingStep }) {
  return (
    <span className="filing-step-head">
      <span className="filing-step-n" aria-hidden="true">
        {step === "done" ? <CheckIcon /> : at + 1}
      </span>
      {name}
      {step === "done" ? <span className="filing-step-done">Done</span> : null}
    </span>
  );
}

const choiceKey = (choice: { route_node_id: string; citation_index: number }) =>
  `${choice.route_node_id}#${choice.citation_index}`;

const choiceLabel = (choice: CitationChoice) =>
  `${choice.route_node_id} · p.${choice.page} · ${choice.matched_text}`;

/** The draft's figures (N90): each marker the text uses, once, and the
    citation it names -- or that it names none the served records carry,
    which the server will then refuse. What is read back after a save is the
    host's resolution, not this. */
function DraftFigures({
  narrative,
  choices,
}: {
  narrative: NarrativeDraft[][];
  choices: CitationChoice[];
}) {
  const used = new Map<string, { route_node_id: string; citation_index: number }>();
  for (const span of narrative.flat()) {
    if (span.figure) used.set(choiceKey(span.figure), span.figure);
  }
  if (used.size === 0) return null;
  const byKey = new Map(choices.map((choice) => [choiceKey(choice), choice]));
  return (
    <div className="note" data-draft-figures>
      <p>Figures in this draft:</p>
      <ul className="plain">
        {[...used].map(([key, figure]) => {
          const marker = figureMarker(figure.route_node_id, figure.citation_index);
          const choice = byKey.get(key);
          return (
            <li key={key} data-draft-figure={marker}>
              <b className="font-mono">{marker}</b>{" "}
              {choice ? choiceLabel(choice) : "names no citation this report carries"}
            </li>
          );
        })}
      </ul>
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
      <Button type="button" variant="outline" size="sm" onClick={() => onInsert(chosen)}>
        Insert figure
      </Button>
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
  primary,
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
  /** The chain's current step: its control is the section's one primary. */
  primary: boolean;
}) {
  const { pending, result, run } = useCommand<{ payload_sha256: string }>();
  const refusal = action?.refusal ?? null;
  const verb = label.split(" ")[0]!;
  return (
    <div className="grid justify-items-start gap-1">
      {/* Signing, freezing and filing bind an approver to exact bytes and the
          v1 wire has no reverse command, so each asks once more and names the
          revision and the digest it would bind (finding FE-7). */}
      <ConfirmedControl
        refusal={refusal}
        busy={pending}
        step={{
          act: label,
          subject: saved ? `revision ${saved.id}` : "no saved revision",
          digest: saved?.digest ?? null,
        }}
        onConfirm={
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
                  if (outcome?.kind === "ok") onDone(saved);
                });
              }
            : undefined
        }
        action={name}
        aria-label={label}
        variant={primary ? "default" : "outline"}
      >
        {pending ? `${verb}…` : label}
      </ConfirmedControl>
      <CommandOutcome result={result} success={`${label}: done.`} />
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
  // The analyst may leave before a deferred save's answer arrives -- another
  // case, or another section -- and its success then names a revision on an
  // address no longer shown; correcting it would navigate them back to the
  // abandoned Report (R24-03, guarded the way CF-058 guards Create run).
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
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
  const shown = body.revisions.find((revision) => revision.revision_id === body.revision_id);
  const steps = filingSteps(saved ? (shown?.state ?? "saved") : null, (name) => {
    const action = actionOf(name);
    return action !== undefined && action.refusal === null;
  });
  const narrative = paragraphs(draft);
  // Parsed once per served document, not per keystroke: a record may be large.
  const choices = useMemo(() => citationsOf(body.artifacts), [body.artifacts]);

  function insert(choice: CitationChoice) {
    const marker = figureMarker(choice.route_node_id, choice.citation_index);
    const start = editor.current?.selectionStart ?? draft.length;
    const end = editor.current?.selectionEnd ?? start;
    const next = draft.slice(0, start) + marker + draft.slice(end);
    if (next === draft) {
      // The same marker over itself: nothing to re-render, so place the caret
      // now rather than leave it pending for the next keystroke to trip.
      editor.current?.focus();
      editor.current?.setSelectionRange(start + marker.length, start + marker.length);
      return;
    }
    caret.current = start + marker.length;
    setDraft(next);
  }
  // The served revision is the head this draft was composed against; on a run
  // with none it is null, which is what a first save names.
  const request = { expected_revision_id: body.revision_id, narrative };

  return (
    <section className="pnl" data-filing-controls>
      <header>
        <h2>Filing</h2>
        <span className="cp">Save · sign · freeze · file</span>
      </header>
      <div className="pb">
        <label className="fld" htmlFor="narrative-draft">
          Narrative draft
        </label>
        {/* The rule as a caption; the refusal at save carries the detail
            (brief 5, Report). */}
        <p className="fld-hint" id="narrative-draft-rule">
          Prose only: every figure goes in through the citation picker, as a marker.
        </p>
        {/* The draft and the row that puts figures into it are one control:
            one edge, the picker its foot (brief 6.10). */}
        <div className="composer" data-narrative-composer>
          <Textarea
            id="narrative-draft"
            className="min-h-24 rounded-b-none border-0 bg-transparent focus-visible:ring-0 dark:bg-transparent"
            ref={editor}
            value={draft}
            rows={4}
            placeholder="One paragraph per line."
            aria-describedby="narrative-draft-rule"
            onChange={(event) => setDraft(event.target.value)}
          />
          <FigurePicker
            key={choices.map(choiceKey).join(" ")}
            choices={choices}
            onInsert={insert}
          />
        </div>
        <DraftFigures narrative={narrative} choices={choices} />
        <ol className="filing-steps" data-filing-acts aria-label="Filing steps">
          <li className="filing-step" data-step="SAVE_REVISION" data-step-state={steps[0]}>
            <StepHead at={0} name="Save" step={steps[0]!} />
            <RefusedControl
              refusal={saveAction?.refusal ?? null}
              onClick={
                saveAction
                  ? () => {
                      if (saveAction.refusal || save.pending) return;
                      const sent = draft;
                      void save
                        .run(request, (intent) =>
                          saveRevision(body.case_id, body.displayed_run_id, request, intent),
                        )
                        .then((outcome) => {
                          if (outcome?.kind !== "ok" || !mounted.current) return;
                          // Cleared only if it is still what was saved: words
                          // typed while the save was in flight were never sent.
                          setDraft((current) => (current === sent ? "" : current));
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
              busy={save.pending}
              variant={steps[0] === "current" ? "default" : "outline"}
              reasonDisplay="inline"
              data-action="SAVE_REVISION"
              aria-label="Save revision"
            >
              {save.pending ? "Saving…" : "Save revision"}
            </RefusedControl>
            <CommandOutcome
              result={save.result}
              success={(receipt) => `Revision ${receipt.revision_id} saved.`}
              mark="revision-saved"
            />
          </li>
          <li className="filing-step" data-step="SIGN_OPINION" data-step-state={steps[1]}>
            <StepHead at={1} name="Sign" step={steps[1]!} />
            <FilingAct
              name="SIGN_OPINION"
              saved={saved}
              action={actionOf("SIGN_OPINION")}
              label="Sign opinion"
              send={(on, intent) => signOpinion(body.case_id, on.id, on.digest, intent)}
              onDone={(on) => void reread(on)}
              primary={steps[1] === "current"}
            />
          </li>
          <li className="filing-step" data-step="FREEZE_DELIVERABLE" data-step-state={steps[2]}>
            <StepHead at={2} name="Freeze" step={steps[2]!} />
            <FilingAct
              name="FREEZE_DELIVERABLE"
              saved={saved}
              action={actionOf("FREEZE_DELIVERABLE")}
              label="Freeze deliverable"
              send={(on, intent) => freezeDeliverable(body.case_id, on.id, on.digest, intent)}
              onDone={(on) => void reread(on)}
              primary={steps[2] === "current"}
            />
          </li>
          <li className="filing-step" data-step="FILE_DELIVERABLE" data-step-state={steps[3]}>
            <StepHead at={3} name="File" step={steps[3]!} />
            <FilingAct
              name="FILE_DELIVERABLE"
              saved={saved}
              action={actionOf("FILE_DELIVERABLE")}
              label="File deliverable"
              send={(on, intent) => fileDeliverable(body.case_id, on.id, on.digest, intent)}
              onDone={(on) => void reread(on)}
              primary={steps[3] === "current"}
            />
          </li>
        </ol>
        {refreshFailed ? (
          <p className="note warn" role="alert" data-filing-refresh-failed>
            The act landed, but the report could not be re-read. Reload to see it.
          </p>
        ) : null}
      </div>
    </section>
  );
}
