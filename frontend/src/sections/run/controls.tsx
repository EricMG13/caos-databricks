// The Run section's governed controls (brief 4.2, decisions 1, 7, 10 and 12):
// select and pin a route, pin the subject, read a gate preview exactly and
// approve on its own digests, then start, retry or cancel. Every control
// renders from `chrome.actions`, present or refused, never hidden
// (`RefusedControl`, shared with the ribbon); the command re-checks at
// commit, so an advisory `null` refusal here is never trusted as the last
// word. A success is shown, and the caller is handed one refetch to run
// (`onRefetch`); the control never claims a write took effect on its own say.
import { useCallback, useId, useLayoutEffect, useRef, useState, type ChangeEvent } from "react";
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
import { fetchSection } from "@/app/transport";
import { RefusalNote, RefusedControl } from "@/controls/RefusedControl";
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

/** One `crypto.randomUUID()` key per user intent (brief 4.2, decision 12).
    `run` takes the request body alongside the sender: the key is reused only
    when the immediately preceding call carried the identical body and
    answered `{ kind: "offline" }` (a network retry of the same intent, never
    reaching the server); any other answer, or a body that has changed since
    (the analyst edited the subject, picked a different route, re-read a
    preview), draws a fresh one.

    `useCommand`'s intent lifecycle is what
    `test_the_idempotency_key_is_reused_for_a_retry_of_the_same_body` and
    `test_the_idempotency_key_is_replaced_when_the_body_changes_even_after_an_offline_answer`
    exercise, by driving the mounted section's own controls. */
export function useCommand<R>() {
  const intentRef = useRef<Intent>(newIntent());
  const lastBodyRef = useRef<string | null>(null);
  const lastKindRef = useRef<CommandResult<R>["kind"] | null>(null);
  const [state, setState] = useState<CommandState<R>>({ pending: false, result: null });
  const run = useCallback(
    async (body: unknown, send: (intent: Intent) => Promise<CommandResult<R>>) => {
      const bodyKey = JSON.stringify(body);
      const retrySameBody = lastKindRef.current === "offline" && lastBodyRef.current === bodyKey;
      if (!retrySameBody) intentRef.current = newIntent();
      lastBodyRef.current = bodyKey;
      setState({ pending: true, result: null });
      const result = await send(intentRef.current);
      lastKindRef.current = result.kind;
      setState({ pending: false, result });
      return result;
    },
    [],
  );
  return { pending: state.pending, result: state.result, run };
}

/** What the last attempt of a command answered, beside the advisory refusal
    already shown on the control itself: a visible success, a typed refusal,
    an unreadable answer, or a request that never reached the server. */
export function CommandOutcome({
  result,
  success,
}: {
  result: CommandResult<unknown> | null;
  success: string;
}) {
  if (result === null) return null;
  if (result.kind === "ok") {
    return (
      <div className="note" data-command-success>
        {success}
      </div>
    );
  }
  // Every outcome but success is announced: a refusal a screen reader never
  // hears is a form that silently did nothing.
  if (result.kind === "refused") {
    return (
      <div className="note crit" role="alert">
        <RefusalNote refusal={result.refusal} />
      </div>
    );
  }
  if (result.kind === "offline") {
    return (
      <div className="note crit" role="alert" data-command-offline>
        {OFFLINE_WORDING} Retrying sends the same key.
      </div>
    );
  }
  return (
    <div className="note crit" role="alert" data-command-error>
      RESPONSE_INVALID — the server&apos;s answer did not match the wire.
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
              className="rb acc"
              data-action="CREATE_RUN"
              onClick={
                action && request
                  ? () => {
                      void run(request, (intent) => createRun(caseId, request, intent)).then(
                        (outcome) => {
                          if (outcome.kind !== "ok") return;
                          // The address is corrected, not navigated: the
                          // analyst did not move, the run they are on gained
                          // a name. `replace` keeps Back at where they came
                          // from rather than at a case with no run, and every
                          // other parameter the address carries survives.
                          setParams(
                            (current) => {
                              const next = new URLSearchParams(current);
                              next.set("run", outcome.receipt.run_id);
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
        <CommandOutcome result={result} success="Run created. Reading the new run back." />
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

/** Pins the subject the run executes against. The subject reuses
    `RunSubjectView`; the receipt's `input_fingerprint` is what a gate
    approval and start/retry must carry, and the document never re-serves it,
    so the caller is handed it here to hold for the session — and a change to
    it invalidates any preview already read (`RunSection` remounts each gate
    panel on a fingerprint change, clearing a digest that would else point at
    the old input). */
export function PinInputControl({
  caseId,
  runId,
  action,
  initial,
  onPinned,
  onRefetch,
}: {
  caseId: string;
  runId: string;
  action: ActionView | undefined;
  initial: RunSubjectView | null;
  onPinned: (fingerprint: string) => void;
  onRefetch: (runId: string | null) => void;
}) {
  const [subject, setSubject] = useState<RunSubjectView>(initial ?? EMPTY_SUBJECT);
  const { pending, result, run } = useCommand<RunInputPinned>();
  const field = (key: keyof RunSubjectView) => ({
    value: subject[key],
    onChange: (event: ChangeEvent<HTMLInputElement>) =>
      setSubject((current: RunSubjectView) => ({ ...current, [key]: event.target.value })),
  });
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
        <RefusedControl
          refusal={action ? action.refusal : null}
          className="rb acc"
          data-action="PIN_RUN_INPUT"
          onClick={
            action
              ? () => {
                  void run(subject, (intent) => pinRunInput(caseId, runId, subject, intent)).then(
                    (outcome) => {
                      if (outcome.kind === "ok") {
                        onPinned(outcome.receipt.input_fingerprint);
                        onRefetch(runId);
                      }
                    },
                  );
                }
              : undefined
          }
        >
          {pending ? "Pinning…" : "Pin input"}
        </RefusedControl>
        <CommandOutcome result={result} success="Subject pinned. Reading it back." />
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
  onRefetch,
}: {
  caseId: string;
  runId: string;
  gate: GateView["gate"];
  state: GateView["state"];
  action: ActionView | undefined;
  onFingerprint: (fingerprint: string) => void;
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
        <span className="cp">{state}</span>
      </header>
      <div className="pb">
        <RefusedControl
          refusal={null}
          className="rb"
          data-action="PREVIEW"
          data-preview-gate={gate}
          onClick={() => {
            // A preview grants nothing and does not seed the known
            // fingerprint (`onFingerprint` is Pin's and Approve's alone) --
            // doing so here would remount this very panel on its own
            // success, at the moment the digest it just read matters most.
            void preview.run(null, (intent) => fetchGatePreview(caseId, runId, gate, intent));
          }}
        >
          {preview.pending ? "Loading…" : "Preview"}
        </RefusedControl>
        {previewed ? (
          <pre className="preview" data-gate-preview-content>
            {previewed.content}
          </pre>
        ) : null}
        <CommandOutcome result={preview.result} success="Preview read." />
        {state === "OPEN" ? (
          <>
            <RefusedControl
              refusal={approveRefusal}
              className="rb acc"
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
                          if (outcome.kind === "ok") {
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
            <CommandOutcome result={approve.result} success="Gate approved. Reading it back." />
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
      <div className="pb flush">
        {work?.stop_code ? <StopCode state={work.state} code={work.stop_code} /> : null}
        <RefusedControl
          refusal={startRefusal}
          className="rb acc"
          data-action="START_RUN"
          onClick={
            startAction && fingerprint
              ? () => {
                  const body = { input_fingerprint: fingerprint };
                  void start
                    .run(body, (intent) => startRun(caseId, runId, body, intent))
                    .then((outcome) => {
                      if (outcome.kind === "ok") onRefetch(runId);
                    });
                }
              : undefined
          }
        >
          {start.pending ? "Starting…" : "Start run"}
        </RefusedControl>
        <CommandOutcome result={start.result} success="Run enqueued. Reading it back." />
        <RefusedControl
          refusal={retryRefusal}
          className="rb"
          data-action="RETRY_RUN"
          onClick={
            retryAction && fingerprint
              ? () => {
                  const body = { input_fingerprint: fingerprint };
                  void retry
                    .run(body, (intent) => retryRun(caseId, runId, body, intent))
                    .then((outcome) => {
                      if (outcome.kind === "ok") onRefetch(runId);
                    });
                }
              : undefined
          }
        >
          {retry.pending ? "Retrying…" : "Retry run"}
        </RefusedControl>
        <CommandOutcome result={retry.result} success="Run requeued. Reading it back." />
        <RefusedControl
          refusal={cancelRefusal}
          className="rb crit"
          data-action="CANCEL_RUN"
          onClick={
            cancelAction
              ? () => {
                  void cancel
                    .run({}, (intent) => cancelRun(caseId, runId, intent))
                    .then((outcome) => {
                      if (outcome.kind === "ok") onRefetch(runId);
                    });
                }
              : undefined
          }
        >
          {cancel.pending ? "Cancelling…" : "Cancel run"}
        </RefusedControl>
        <CommandOutcome result={cancel.result} success="Cancellation requested. Reading it back." />
      </div>
    </section>
  );
}
