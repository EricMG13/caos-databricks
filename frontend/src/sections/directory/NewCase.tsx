// Directory's one governed write (brief 4.2, decision 12): create a case.
// The control renders from the document's own `chrome.actions` -- present
// and refused, never hidden (decision 10; CLAUDE.md "Persona is not
// authority") -- and the command rechecks authority at commit regardless of
// what this control shows. An action this section's document does not name
// at all is not available either: `RefusedControl`'s own fallback
// (`ACTION_UNPLACED`) is what renders it that way, by this control passing
// no `onClick` when there is no `action` to check. On success this section
// refetches its own document once; 4.4 owns the SSE-driven refresh other
// sections get. A refetch that fails never reads as nothing happened: the
// success stands (the case exists) beside a distinct, visible refresh
// failure.
import { useState } from "react";
import { createCase } from "@/app/commands";
import { sectionUrl } from "@/app/transport";
import { RefusedControl } from "@/controls/RefusedControl";
import { TextInput } from "@/ds/TextInput";
import { CommandOutcome, useCommand } from "@/sections/run/controls";
import {
  parseDirectoryDocument,
  type ActionView,
  type CaseCreated,
  type DirectoryDocument,
} from "@/wire/v1";

const TITLE_MAX = 256;

/** Directory's own document, re-read once after a success (brief 4.2,
    decision 12). Reuses `sectionUrl` and the v1 parser rather than the
    section-status classifier in `@/app/transport`, whose union of the v1
    documents this control has no reason to narrow. */
export async function refetchDirectory(): Promise<DirectoryDocument | null> {
  const url = sectionUrl("directory", {});
  if (!url) return null;
  let response: Response;
  try {
    response = await fetch(url, { headers: { accept: "application/json" } });
  } catch {
    return null;
  }
  if (!response.ok) return null;
  try {
    return parseDirectoryDocument(await response.json());
  } catch {
    return null;
  }
}

export function NewCase({
  action,
  onCreated,
}: {
  action: ActionView | undefined;
  onCreated: (document: DirectoryDocument) => void;
}) {
  const [title, setTitle] = useState("");
  // The intent's key is reused only for a retry of the same title after an
  // offline answer; every other outcome, or a changed title, draws a fresh one.
  const { pending, result, run } = useCommand<CaseCreated>();
  const [refreshFailed, setRefreshFailed] = useState(false);
  const refusal = action?.refusal ?? null;

  async function submit() {
    const trimmed = title.trim();
    if (refusal || pending || trimmed.length === 0) return;
    setRefreshFailed(false);
    const outcome = await run(trimmed, (intent) => createCase(trimmed, intent));
    if (outcome?.kind !== "ok") return;
    setTitle("");
    const refreshed = await refetchDirectory();
    if (refreshed) onCreated(refreshed);
    else setRefreshFailed(true);
  }

  return (
    <div className="newcase" data-new-case>
      <label className="sr-only" htmlFor="new-case-title">
        New case title
      </label>
      <TextInput
        id="new-case-title"
        type="text"
        value={title}
        maxLength={TITLE_MAX}
        placeholder="Issuer engagement title"
        onChange={(event) => setTitle(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            void submit();
          }
        }}
      />
      <RefusedControl
        refusal={refusal}
        onClick={action ? () => void submit() : undefined}
        busy={pending}
        className="rb solid"
        reasonDisplay="inline"
        aria-label="Create case"
      >
        {pending ? "Creating…" : "Create case"}
      </RefusedControl>
      {result?.kind === "ok" ? (
        <p className="note ok" data-new-case-success>
          Case {result.receipt.case_id} created.
        </p>
      ) : (
        <CommandOutcome result={result} success="" />
      )}
      {import.meta.env.MODE === "demo" ? (
        <p className="note" data-demo-command-note>
          <b>Available means the command would answer, not that it will succeed.</b> This
          demonstration serves fixtures and reads only: its API refuses every command with
          READ_ONLY_DEMO, a code the v1 wire does not declare, so the answer this control shows is
          RESPONSE_INVALID. That is the workspace refusing an undeclared answer, which is what it
          would do to any server that sent one.
        </p>
      ) : null}
      {refreshFailed ? (
        <p className="note warn" role="alert" data-new-case-refresh-failed>
          The case was created, but the register could not be refreshed. Reload to see it.
        </p>
      ) : null}
    </div>
  );
}
