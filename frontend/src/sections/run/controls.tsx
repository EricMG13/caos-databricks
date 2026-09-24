// The Run section's governed controls (brief 4.2, decisions 1, 7, 10 and 12):
// select and pin a route, pin the subject, read a gate preview exactly and
// approve on its own digests, then start, retry or cancel. Every control
// renders from `chrome.actions`, present or refused, never hidden
// (`RefusedControl`, shared with the ribbon); the command re-checks at
// commit, so an advisory `null` refusal here is never trusted as the last
// word. A success is shown, and the caller is handed one refetch to run
// (`onRefetch`); the control never claims a write took effect on its own say.
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ChangeEvent,
} from "react";
import { flushSync } from "react-dom";
import { useSearchParams } from "react-router";
import {
  approveGate,
  cancelRun,
  createRun,
  fetchGatePreview,
  newIntent,
  pinRunInput,
  retryRun,
  startRun,
  type CommandResult,
  type Intent,
} from "@/app/commands";
import { OFFLINE_WORDING } from "@/app/transport";
import { sentence } from "@/chrome/compose";
import { fetchSection } from "@/app/transport";
import { ConfirmedControl } from "@/controls/ConfirmedControl";
import { RefusalNote, RefusedControl } from "@/controls/RefusedControl";
import { useAnnouncer } from "@/states/Announcer";
import type {
  ActionView,
  CreateRun,
  GateApproved,
  GatePreviewDocument,
  Infer,
  RouteChoice,
  RunCreated,
  RunInputPinned,
  RunSectionDocument,
  RunWork,
} from "@/wire/v1";
import type { V1_SHAPES } from "@/wire/v1/documents";

// Not exported as named types from `documents.ts` (only `types.ts`, owned by
// an earlier slice, derives them for the read side); derived here the same
// way rather than duplicated by hand.
type GateView = Infer<typeof V1_SHAPES.GateView>;
type RunSubjectView = Infer<typeof V1_SHAPES.RunSubjectView>;
type ResearchBrief = Infer<typeof V1_SHAPES.ResearchBrief>;
type ResearchBriefQuestion = Infer<typeof V1_SHAPES.ResearchBriefQuestion>;
type WorkView = Infer<typeof V1_SHAPES.WorkView>;

export type ActionName = ActionView["action"];

/** A `RunBody` is the only enabled-section body carrying `route_choices`;
    narrows the transport's section-generic document without casting a value
    nothing has checked. */
function isRunSectionDocument(document: { body: object }): document is RunSectionDocument {
  return "route_choices" in document.body;
}

/** A POST never returns the document it changed, so the caller's view is
    kept live by one plain GET through the same transport and parser every
    load uses (brief 4.2, decision 12) — never a value this file invents. A
    refetch that itself fails to answer is shown, not silently dropped: the
    alternative is a control the analyst might press again believing the
    first press did nothing.

    Exercised end-to-end by `frontend/tests/unit/run.test.tsx`: every command
    test below drives `useRunRefetch`'s GET-after-success (and its
    `[data-refetch-failed]` note on a failed one) through the mounted
    section, never by importing the hook directly. */
export function useRunRefetch(initial: RunSectionDocument, caseId: string) {
  const [live, setLive] = useState(initial);
  const [failed, setFailed] = useState(false);
  // Adjusted during render, not in an effect (React's own pattern for
  // syncing state from a prop): a fresh `initial` — a navigation, or the
  // workspace's own SSE-triggered load — always supersedes a local refetch.
  const [seenInitial, setSeenInitial] = useState(initial);
  if (initial !== seenInitial) {
    setSeenInitial(initial);
    setLive(initial);
    // The note said this view was behind the run. A document the workspace
    // has since served is that view caught up, so the note goes with it
    // rather than standing beside every later live update (finding FE-10).
    setFailed(false);
  }
  // One sequence over both sources of a document: a refetch applies only while
  // it is still the latest. An earlier refetch that answers late, or one still
  // in flight when the workspace serves a fresher document, is dropped rather
  // than putting an older run back on screen. Bumped in a layout effect, not
  // in the render above it: a passive effect is scheduled after the commit, so
  // a refetch resolving in between would still read the superseded sequence.
  const sequence = useRef(0);
  useLayoutEffect(() => {
    sequence.current += 1;
  }, [initial]);
  const refetch = useCallback(
    (runId: string | null) => {
      const mine = (sequence.current += 1);
      void fetchSection("run", { case: caseId, run: runId }).then((status) => {
        if (mine !== sequence.current) return;
        if ("document" in status && isRunSectionDocument(status.document)) {
          setLive(status.document);
          setFailed(false);
        } else {
          setFailed(true);
        }
      });
    },
    [caseId],
  );
  return { live, failed, refetch };
}

/** The one entry for a served action, if the document carries it. An action
    absent from the list is not the same as one served with a null refusal:
    callers below never fire a click for an absent entry, so `RefusedControl`
    falls to its own default (`ACTION_UNPLACED`) rather than being told
    "available" by a coerced `null`.

    `actionOf`'s selection from `chrome.actions` is what
    `test_an_action_absent_from_served_actions_is_action_unplaced_not_available`
    and `test_a_refused_action_renders_its_code_and_clearance_and_is_not_hidden`
    exercise, through the mounted section rather than by calling it directly. */
export function actionOf(
  actions: readonly ActionView[],
  action: ActionName,
): ActionView | undefined {
  return actions.find((entry) => entry.action === action);
}

export interface CommandState<R> {
  pending: boolean;
  result: CommandResult<R> | null;
}

/** The server's transient refusals (`TRANSIENT` in `caos/api/app.py`): typed,
    but they say "not now" rather than "no". STORE_UNAVAILABLE in particular is
    what a store fault at commit answers, and a commit whose acknowledgement
    was lost faults exactly there with the write already made (MAX-01). */
const IN_DOUBT: ReadonlySet<string> = new Set([
  "STORE_UNAVAILABLE",
  "IDENTITY_UNAVAILABLE",
  "PROVIDER_UNAVAILABLE",
  "STREAM_LIMIT_REACHED",
]);

/** An answer that settled the intent: a validated receipt, or a typed refusal
    the server composed that is not one of the transient ones above. Anything
    else -- a request that never arrived, a gateway page, a 201 whose body was
    lost in transfer, a store that could not say whether it committed -- leaves
    the write in doubt, so the key is kept and a retry asks the same question
    again rather than a second one (AR-19, findings FE-8 and MAX-01). */
function settles<R>(result: CommandResult<R>): boolean {
  if (result.kind === "ok") return true;
  return result.kind === "refused" && !IN_DOUBT.has(result.refusal.code);
}

/** One `crypto.randomUUID()` key per user intent (brief 4.2, decision 12).
    `run` takes the request body alongside the sender: the key is kept while
    the identical body has yet to draw an answer that settles it (`settles`
    above), which covers an offline retry, every unreadable answer and a
    transient refusal; a body that has changed since (the analyst edited the
    subject, picked a different route, re-read a preview) draws a fresh one.

    A second activation while the first is still in flight is not a second
    intent and is refused here rather than by each of the fourteen controls:
    the ref is read and written in the same synchronous step as the send, so
    two clicks in one frame cannot both pass it the way a render-time
    `pending` can. Such a press answers `null` -- nothing was sent, so there
    is no outcome to act on.

    `useCommand`'s intent lifecycle is what
    `test_the_idempotency_key_is_reused_for_a_retry_of_the_same_body`,
    `test_the_idempotency_key_is_replaced_when_the_body_changes_even_after_an_offline_answer`
    and `test_a_second_press_while_a_command_is_in_flight_sends_nothing`
    exercise, by driving the mounted section's own controls. */
export function useCommand<R>() {
  const intentRef = useRef<Intent>(newIntent());
  const lastBodyRef = useRef<string | null>(null);
  // Nothing sent yet is nothing in doubt.
  const settledRef = useRef(true);
  const inFlightRef = useRef(false);
  const [state, setState] = useState<CommandState<R>>({ pending: false, result: null });
  const run = useCallback(
    async (body: unknown, send: (intent: Intent) => Promise<CommandResult<R>>) => {
      if (inFlightRef.current) return null;
      inFlightRef.current = true;
      try {
        const bodyKey = JSON.stringify(body);
        const retrySameBody = !settledRef.current && lastBodyRef.current === bodyKey;
        if (!retrySameBody) intentRef.current = newIntent();
        lastBodyRef.current = bodyKey;
        setState({ pending: true, result: null });
        const result = await send(intentRef.current);
        settledRef.current = settles(result);
        // The answer is on screen, and a success said, before anything it
        // causes: a caller's re-read that takes this very control away (a
        // withdrawn source, a revoked member, a remounted gate panel) would
        // otherwise land in the same render and the outcome would never be
        // shown or announced at all (DF-6).
        flushSync(() => setState({ pending: false, result }));
        return result;
      } finally {
        inFlightRef.current = false;
      }
    },
    [],
  );
  return { pending: state.pending, result: state.result, run };
}

/** What the last attempt of a command answered, beside the advisory refusal
    already shown on the control itself: a visible success, a typed refusal,
    an unreadable answer, or a request that never reached the server. */
export function CommandOutcome<R>({
  result,
  success,
  mark,
  read = false,
}: {
  result: CommandResult<R> | null;
  /** A read, not a write (the gate preview): nothing can have taken effect, so
      a failure says to load it again, never what a retry would resend. */
  read?: boolean;
  /** What a success shows and says: one sentence, or one drawn from the
      receipt where the receipt names what was made. Never empty -- a success
      nobody hears is a form that silently did nothing (findings FE-6, DF-6). */
  success: string | ((receipt: R) => string);
  /** A name the success note also carries as `data-<mark>`, for a control
      whose note is found by its own name. */
  mark?: string;
}) {
  const say = useAnnouncer();
  const sentence =
    result?.kind === "ok"
      ? typeof success === "string"
        ? success
        : success(result.receipt)
      : null;
  // Said once per answer, in the section's own live region: the note below
  // carries role=status too, but a region inserted already populated is
  // announced inconsistently. Keyed on the answer rather than on whether it
  // succeeded, so a second success of the same command is said again (DF-6).
  useEffect(() => {
    if (sentence) say(sentence);
  }, [result, sentence, say]);
  if (result === null) return null;
  if (result.kind === "ok") {
    return (
      <div
        className="note"
        role="status"
        data-command-success
        {...(mark ? { [`data-${mark}`]: "" } : {})}
      >
        {sentence}
      </div>
    );
  }
  // Every outcome but success is announced: a refusal a screen reader never
  // hears is a form that silently did nothing.
  if (result.kind === "refused") {
    return (
      <div className="note crit" role="alert">
        <RefusalNote refusal={result.refusal} />
        {!read && IN_DOUBT.has(result.refusal.code) ? (
          <p data-command-in-doubt>
            Whether the command took effect is not known yet. Retrying sends the same key.
          </p>
        ) : null}
      </div>
    );
  }
  if (result.kind === "offline") {
    return (
      <div className="note crit" role="alert" data-command-offline>
        {OFFLINE_WORDING} {read ? "Try again." : "Retrying sends the same key."}
      </div>
    );
  }
  if (read) {
    return (
      <div className="note crit" role="alert" data-command-error>
        The server&apos;s answer could not be read. Try again.
      </div>
    );
  }
  // Neither a receipt nor a typed refusal: the write may well have committed
  // behind a gateway page or a body that never finished arriving, so the
  // reader is told what a retry would do rather than left to guess (FE-8).
  return (
    <div className="note crit" role="alert" data-command-error>
      RESPONSE_INVALID — the server&apos;s answer did not match the wire, so whether the command
      took effect is unknown. Retrying sends the same key.
    </div>
  );
}

/** A run with no route is useless (brief 4.2, decision 1): select and pin one
    in the same command that creates the run. Available with no displayed
    run, and again afterwards to start a fresh one. A success names the new run
    in the address, and the workspace reads it from there — so the view moves
    off this form at once, a second press is a plainly new run rather than a
    silent duplicate, and a reload shows the run the analyst is looking at
    instead of whatever the old address named. This is the one control that
    does not hand its caller a refetch: the run it created is not the run the
    section was mounted for, so re-reading the old address would be the wrong
    document and re-reading the new one duplicates the read the address change
    already causes. */
export function CreateRunControl({
  caseId,
  action,
  choices,
  supersedes = null,
}: {
  caseId: string;
  action: ActionView | undefined;
  choices: readonly RouteChoice[];
  /** The BLOCKED run the new run would answer (§72), offered pre-filled
      when the displayed run ended BLOCKED and nothing has answered it yet.
      The analyst may clear it: a successor is an ordinary new run that names
      its predecessor, and the name is the analyst's to give. */
  supersedes?: string | null;
}) {
  const [pick, setPick] = useState(0);
  const [predecessor, setPredecessor] = useState(supersedes ?? "");
  const [extension, setExtension] = useState(false);
  const [, setParams] = useSearchParams();
  const { pending, result, run } = useCommand<RunCreated>();
  const extensionWhy = useId();
  // The analyst may leave while the command is in flight (another case, or
  // another section): its answer then names a run on a page no longer shown,
  // and correcting the address would navigate them back (CF-058).
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const chosen = choices[pick] ?? null;
  const named = predecessor.trim();
  // The choice says whether its route can carry CP-CF (the server's own
  // resolution, asked in advance); the command resolves again at commit, so
  // this only keeps the form from offering a press it knows is refused.
  const accepts = chosen?.accepts_model_extension ?? false;
  const request: CreateRun | null = chosen
    ? {
        profile_id: chosen.profile_id,
        selection_id: chosen.selection_id,
        supersedes: named === "" ? null : named,
        model_extension: accepts && extension,
      }
    : null;
  return (
    <section className="pnl" data-create-run>
      <header>
        <h2>Create run</h2>
      </header>
      <div className="pb">
        {choices.length ? (
          <>
            <label className="fld">
              Route
              <select
                data-route-select
                value={pick}
                onChange={(event: ChangeEvent<HTMLSelectElement>) => {
                  // A new route is a new question: the extension is asked
                  // for again rather than carried over from the last route.
                  setPick(Number(event.target.value));
                  setExtension(false);
                }}
              >
                {choices.map((choice, index) => (
                  <option key={`${choice.profile_id}:${choice.selection_id}`} value={index}>
                    {choice.profile_id} · {choice.selection_id}
                  </option>
                ))}
              </select>
            </label>
            <label className="fld">
              Supersedes run
              <input
                data-supersedes-input
                value={predecessor}
                placeholder="none: an ordinary run"
                onChange={(event: ChangeEvent<HTMLInputElement>) =>
                  setPredecessor(event.target.value)
                }
              />
            </label>
            <label className="fopt">
              <input
                type="checkbox"
                data-model-extension
                checked={accepts && extension}
                // Refused, not removed: it stays focusable and says why
                // (IA_SPEC.md 2), and a press on it changes nothing.
                aria-disabled={accepts ? undefined : true}
                aria-describedby={accepts ? undefined : extensionWhy}
                onChange={(event: ChangeEvent<HTMLInputElement>) => {
                  if (accepts) setExtension(event.target.checked);
                }}
              />
              Include the model extension (CP-CF)
            </label>
            {accepts ? null : (
              <div className="note" id={extensionWhy} data-model-extension-unavailable>
                This route does not run every module CP-CF reads, so the server refuses the
                extension on it (ROUTE_EXTENSION_OWNER_MISSING).
              </div>
            )}
            <RefusedControl
              refusal={action ? action.refusal : null}
              busy={pending}
              variant="default"
              data-action="CREATE_RUN"
              onClick={
                action && request
                  ? () => {
                      void run(request, (intent) => createRun(caseId, request, intent)).then(
                        (outcome) => {
                          if (outcome?.kind !== "ok" || !mounted.current) return;
                          // The address is corrected, not navigated: the
                          // analyst did not move, the run they are on gained
                          // a name. `replace` keeps Back at where they came
                          // from rather than at a case with no run, and every
                          // other parameter the address carries survives --
                          // except `revision`, which named a revision of
                          // whatever run was displayed before (or none, on a
                          // first run): the new run has none yet, and a
                          // reader (Report, Committee) refuses the mismatched
                          // pair `RUN_NOT_FOUND`/`DELIVERABLE_NOT_FOUND`
                          // rather than silently reattach it (R24-04).
                          setParams(
                            (current) => {
                              const next = new URLSearchParams(current);
                              next.set("run", outcome.receipt.run_id);
                              next.delete("revision");
                              return next;
                            },
                            { replace: true },
                          );
                        },
                      );
                    }
                  : undefined
              }
            >
              {pending ? "Creating…" : "Create run"}
            </RefusedControl>
          </>
        ) : (
          <div className="note" data-no-route-choices>
            No route choices are offered for this case.
          </div>
        )}
        <CommandOutcome result={result} success="Run created." />
      </div>
    </section>
  );
}

const EMPTY_SUBJECT: RunSubjectView = {
  issuer_id: "",
  issuer_name: "",
  reporting_period: "",
  analysis_date: "",
};

// The one question shape a caller edits here (`CP_DR_RESEARCH_BRIEF_V1.md`:
// "One question is sufficient"). `consumer_module_id`/`after_module_id` are
// fixed, not edited: every route this host advertises a brief for
// (`LITE_DEEP_RESEARCH`, `DEEP_RESEARCH`) is anchored on CP-DR itself, whose
// one placement the vendor's own schema accepts is consumer `NONE` after
// `CP-0` -- so there is nothing here for a caller to get wrong.
const EMPTY_RESEARCH_QUESTION: ResearchBriefQuestion = {
  question_id: "",
  question: "",
  decision_relevance: "",
  consumer_module_id: "NONE",
  after_module_id: "CP-0",
  evidence_needed: "",
  completion_test: "",
};

const EMPTY_RESEARCH: ResearchBrief = {
  decision_context: "",
  as_of_date: "",
  time_horizon: "",
  budget: "standard",
  authorization_basis: "",
  exclusions: "",
  questions: [EMPTY_RESEARCH_QUESTION],
};

/** Pins the subject the run executes against, and -- on the two advertised
    research routes -- the run-linked CP-DR brief the store requires before
    it will accept the pin (R24-01): the wire model, the request digest and
    idempotency all carry it through `research`, additive beside `subject`.
    The subject reuses `RunSubjectView`; the receipt's `input_fingerprint` is
    what a gate approval and start/retry must carry, and the document never
    re-serves it, so the caller is handed it here to hold for the session —
    and a change to it invalidates any preview already read (`RunSection`
    remounts each gate panel on a fingerprint change, clearing a digest that
    would else point at the old input). */
export function PinInputControl({
  caseId,
  runId,
  action,
  initial,
  requiresResearch,
  onPinned,
  onRefetch,
}: {
  caseId: string;
  runId: string;
  action: ActionView | undefined;
  initial: RunSubjectView | null;
  requiresResearch: boolean;
  onPinned: (fingerprint: string) => void;
  onRefetch: (runId: string | null) => void;
}) {
  const [subject, setSubject] = useState<RunSubjectView>(initial ?? EMPTY_SUBJECT);
  const [research, setResearch] = useState<ResearchBrief>(EMPTY_RESEARCH);
  const { pending, result, run } = useCommand<RunInputPinned>();
  const field = (key: keyof RunSubjectView) => ({
    value: subject[key],
    onChange: (event: ChangeEvent<HTMLInputElement>) =>
      setSubject((current: RunSubjectView) => ({ ...current, [key]: event.target.value })),
  });
  const briefField = (key: Exclude<keyof ResearchBrief, "questions" | "budget">) => ({
    value: research[key],
    onChange: (event: ChangeEvent<HTMLInputElement>) =>
      setResearch((current: ResearchBrief) => ({ ...current, [key]: event.target.value })),
  });
  const question = research.questions[0] ?? EMPTY_RESEARCH_QUESTION;
  const questionField = (
    key: Exclude<keyof ResearchBriefQuestion, "consumer_module_id" | "after_module_id">,
  ) => ({
    value: question[key],
    onChange: (event: ChangeEvent<HTMLInputElement>) =>
      setResearch((current: ResearchBrief) => ({
        ...current,
        questions: [
          { ...(current.questions[0] ?? EMPTY_RESEARCH_QUESTION), [key]: event.target.value },
        ],
      })),
  });
  const payload = requiresResearch ? research : null;
  return (
    <section className="pnl" data-pin-input>
      <header>
        <h2>Subject</h2>
      </header>
      <div className="pb">
        <label className="fld">
          Issuer id
          <input data-field="issuer_id" {...field("issuer_id")} />
        </label>
        <label className="fld">
          Issuer name
          <input data-field="issuer_name" {...field("issuer_name")} />
        </label>
        <label className="fld">
          Reporting period
          <input data-field="reporting_period" {...field("reporting_period")} />
        </label>
        <label className="fld">
          Analysis date
          <input data-field="analysis_date" placeholder="YYYY-MM-DD" {...field("analysis_date")} />
        </label>
        {requiresResearch ? (
          <fieldset className="fld" data-research-brief>
            <legend>Research brief</legend>
            <label className="fld">
              Decision context
              <input data-field="decision_context" {...briefField("decision_context")} />
            </label>
            <label className="fld">
              As of date
              <input
                data-field="as_of_date"
                placeholder="YYYY-MM-DD"
                {...briefField("as_of_date")}
              />
            </label>
            <label className="fld">
              Time horizon
              <input data-field="time_horizon" {...briefField("time_horizon")} />
            </label>
            <label className="fld">
              Budget
              <select
                data-field="budget"
                value={research.budget}
                onChange={(event) =>
                  setResearch((current) => ({
                    ...current,
                    budget: event.target.value === "extended" ? "extended" : "standard",
                  }))
                }
              >
                <option value="standard">Standard</option>
                <option value="extended">Extended</option>
              </select>
            </label>
            <label className="fld">
              Authorization basis
              <input data-field="authorization_basis" {...briefField("authorization_basis")} />
            </label>
            <label className="fld">
              Exclusions
              <input data-field="exclusions" {...briefField("exclusions")} />
            </label>
            <label className="fld">
              Question id
              <input data-field="question_id" {...questionField("question_id")} />
            </label>
            <label className="fld">
              Question
              <input data-field="question" {...questionField("question")} />
            </label>
            <label className="fld">
              Decision relevance
              <input data-field="decision_relevance" {...questionField("decision_relevance")} />
            </label>
            <label className="fld">
              Evidence needed
              <input data-field="evidence_needed" {...questionField("evidence_needed")} />
            </label>
            <label className="fld">
              Completion test
              <input data-field="completion_test" {...questionField("completion_test")} />
            </label>
          </fieldset>
        ) : null}
        <RefusedControl
          refusal={action ? action.refusal : null}
          busy={pending}
          variant="default"
          data-action="PIN_RUN_INPUT"
          onClick={
            action
              ? () => {
                  void run({ subject, research: payload }, (intent) =>
                    pinRunInput(caseId, runId, subject, payload, intent),
                  ).then((outcome) => {
                    if (outcome?.kind === "ok") {
                      onPinned(outcome.receipt.input_fingerprint);
                      onRefetch(runId);
                    }
                  });
                }
              : undefined
          }
        >
          {pending ? "Pinning…" : "Pin input"}
        </RefusedControl>
        <CommandOutcome result={result} success="Subject pinned." />
      </div>
    </section>
  );
}

const NOT_PREVIEWED = {
  code: "GATE_PREVIEW_NOT_READ",
  clears: "the exact preview text is read in this browser session before approving",
};

const APPROVE_ACTION: Record<GateView["gate"], ActionName> = {
  SOURCE_SET: "APPROVE_SOURCE_SET",
  RESEARCH_PLAN: "APPROVE_RESEARCH_PLAN",
};

/** Invariant 5: approval binds the exact reviewed content. The preview's own
    `preview_sha256` and `input_fingerprint` are what the approval sends —
    never a value the caller types or edits — so the content shown here is
    the only thing this gate can be approved on. `RunSection` remounts this
    component whenever the pinned fingerprint changes, so a stale preview
    read under an earlier input cannot be approved after the fact. */
export function GatePanelControl({
  caseId,
  runId,
  gate,
  state,
  action,
  onFingerprint,
  onPreviewed,
  onRefetch,
}: {
  caseId: string;
  runId: string;
  gate: GateView["gate"];
  state: GateView["state"];
  action: ActionView | undefined;
  onFingerprint: (fingerprint: string) => void;
  /** The fingerprint a preview was computed from: the pinned input's, as the
      server read it. Start and retry may send it; the panel is not remounted
      for it. */
  onPreviewed: (fingerprint: string) => void;
  onRefetch: (runId: string | null) => void;
}) {
  const preview = useCommand<GatePreviewDocument>();
  const approve = useCommand<GateApproved>();
  const previewed = preview.result?.kind === "ok" ? preview.result.receipt : null;
  const approveRefusal = action ? (action.refusal ?? (previewed ? null : NOT_PREVIEWED)) : null;
  return (
    <section className="pnl" data-gate-panel={gate}>
      <header>
        <h2>{gate === "SOURCE_SET" ? "Source set" : "Research plan"}</h2>
        <span className="cp">{sentence(state)}</span>
      </header>
      <div className="pb">
        <RefusedControl
          refusal={null}
          busy={preview.pending}
          data-action="PREVIEW"
          data-preview-gate={gate}
          onClick={() => {
            // A preview grants nothing and does not move the fingerprint the
            // panels are keyed on (`onFingerprint` is Pin's and Approve's
            // alone) -- doing so here would remount this very panel on its own
            // success, at the moment the digest it just read matters most. It
            // does tell start and retry what the pinned input is: after a
            // reload, with both gates released and the subject already
            // pinned, a preview is the one read left that says (MAX-18).
            void preview
              .run(null, (intent) => fetchGatePreview(caseId, runId, gate, intent))
              .then((outcome) => {
                if (outcome?.kind === "ok") onPreviewed(outcome.receipt.input_fingerprint);
              });
          }}
        >
          {preview.pending ? "Loading…" : "Preview"}
        </RefusedControl>
        {previewed ? (
          <pre className="preview" data-gate-preview-content>
            {previewed.content}
          </pre>
        ) : null}
        <CommandOutcome result={preview.result} success="Preview loaded." read />
        {state === "OPEN" ? (
          <>
            <RefusedControl
              refusal={approveRefusal}
              busy={approve.pending}
              variant="default"
              data-action={APPROVE_ACTION[gate]}
              onClick={
                action && previewed
                  ? () => {
                      const body = {
                        preview_sha256: previewed.preview_sha256,
                        input_fingerprint: previewed.input_fingerprint,
                      };
                      void approve
                        .run(body, (intent) => approveGate(caseId, runId, gate, body, intent))
                        .then((outcome) => {
                          if (outcome?.kind === "ok") {
                            onFingerprint(outcome.receipt.input_fingerprint);
                            onRefetch(runId);
                          }
                        });
                    }
                  : undefined
              }
            >
              {approve.pending ? "Approving…" : "Approve"}
            </RefusedControl>
            <CommandOutcome result={approve.result} success="Gate approved." />
          </>
        ) : null}
      </div>
    </section>
  );
}

/** Why the store parked this run's work, as the typed code it recorded.

    The wire carries the code alone -- `WorkView` has no clearance beside it,
    and nothing in this workspace maps a code to one -- so the code is named
    and no clearance is invented for it. Stated in words, never by colour. */
function StopCode({ state, code }: { state: WorkView["state"]; code: string }) {
  const id = useId();
  return (
    <div className="refusal" role="note" aria-labelledby={id} data-stop-code={code}>
      <div className="cl" id={id}>
        Work {state.toLowerCase()} — stop code
      </div>
      <code>{code}</code>
    </div>
  );
}

const NO_FINGERPRINT = {
  code: "COMMAND_EXPECTATION_STALE",
  clears:
    "the subject is pinned, or a gate preview or approval is read, in this browser session — start and retry send the current input fingerprint",
};

/** Start, retry and cancel. Start and retry carry the pinned input's
    fingerprint (brief 4.2, decision 1); this file has no other source for it
    than a pin, preview or approval read in this session, so with none yet
    read the control names that rather than guessing a value. */
export function WorkControls({
  caseId,
  runId,
  fingerprint,
  work,
  actions,
  onRefetch,
}: {
  caseId: string;
  runId: string;
  fingerprint: string | null;
  work: WorkView | null;
  actions: readonly ActionView[];
  onRefetch: (runId: string | null) => void;
}) {
  const start = useCommand<RunWork>();
  const retry = useCommand<RunWork>();
  const cancel = useCommand<RunWork>();
  const startAction = actionOf(actions, "START_RUN");
  const retryAction = actionOf(actions, "RETRY_RUN");
  const cancelAction = actionOf(actions, "CANCEL_RUN");
  const startRefusal = startAction
    ? (startAction.refusal ?? (fingerprint ? null : NO_FINGERPRINT))
    : null;
  const retryRefusal = retryAction
    ? (retryAction.refusal ?? (fingerprint ? null : NO_FINGERPRINT))
    : null;
  const cancelRefusal = cancelAction ? cancelAction.refusal : null;
  return (
    <section className="pnl" data-work-controls>
      <header>
        <h2>Work</h2>
      </header>
      <div className="pb">
        {work?.stop_code ? <StopCode state={work.state} code={work.stop_code} /> : null}
        <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
          <div className="grid justify-items-start gap-1">
            <RefusedControl
              refusal={startRefusal}
              busy={start.pending}
              variant="default"
              data-action="START_RUN"
              onClick={
                startAction && fingerprint
                  ? () => {
                      const body = { input_fingerprint: fingerprint };
                      void start
                        .run(body, (intent) => startRun(caseId, runId, body, intent))
                        .then((outcome) => {
                          if (outcome?.kind === "ok") onRefetch(runId);
                        });
                    }
                  : undefined
              }
            >
              {start.pending ? "Starting…" : "Start run"}
            </RefusedControl>
            <CommandOutcome result={start.result} success="Run queued to start." />
          </div>
          <div className="grid justify-items-start gap-1">
            <RefusedControl
              refusal={retryRefusal}
              busy={retry.pending}
              data-action="RETRY_RUN"
              onClick={
                retryAction && fingerprint
                  ? () => {
                      const body = { input_fingerprint: fingerprint };
                      void retry
                        .run(body, (intent) => retryRun(caseId, runId, body, intent))
                        .then((outcome) => {
                          if (outcome?.kind === "ok") onRefetch(runId);
                        });
                    }
                  : undefined
              }
            >
              {retry.pending ? "Retrying…" : "Retry run"}
            </RefusedControl>
            <CommandOutcome result={retry.result} success="Run queued again." />
          </div>
          <div className="grid justify-items-start gap-1">
            {/* Cancelling a run ends work nothing on the v1 wire restarts, so it
            asks once more and names the run it would end (finding FE-7). */}
            <ConfirmedControl
              refusal={cancelRefusal}
              busy={cancel.pending}
              step={{ act: "Cancel run", subject: `run ${runId}`, digest: null }}
              variant="destructive"
              action="CANCEL_RUN"
              onConfirm={
                cancelAction
                  ? () => {
                      void cancel
                        .run({}, (intent) => cancelRun(caseId, runId, intent))
                        .then((outcome) => {
                          if (outcome?.kind === "ok") onRefetch(runId);
                        });
                    }
                  : undefined
              }
            >
              {cancel.pending ? "Cancelling…" : "Cancel run"}
            </ConfirmedControl>
            <CommandOutcome result={cancel.result} success="Cancellation requested." />
          </div>
        </div>
      </div>
    </section>
  );
}
