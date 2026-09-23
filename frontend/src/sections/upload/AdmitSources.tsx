// Upload's one governed write (brief 4.2, decision 12): admit a source pack.
// The control renders from the document's own `chrome.actions` -- present
// and refused, never hidden (decision 10; CLAUDE.md "Persona is not
// authority") -- and the command rechecks authority and every §44 limit at
// commit regardless of what this control shows. An action this section's
// document does not name at all is not available either: `RefusedControl`'s
// own fallback (`ACTION_UNPLACED`) is what renders it that way, by this
// control passing no `onClick` when there is no `action` to check. On
// success this section refetches its own document once; 4.4 owns the
// SSE-driven refresh other sections get. A refetch that fails never reads as
// nothing happened: the success stands (the pack was admitted) beside a
// distinct, visible refresh failure.
import { useId, useRef, useState } from "react";
import { admitSources } from "@/app/commands";
import { sectionUrl } from "@/app/transport";
import { RefusedControl } from "@/controls/RefusedControl";
import { CommandOutcome, useCommand } from "@/sections/run/controls";
import {
  parseUploadDocument,
  type ActionView,
  type SourcesAdmitted,
  type UploadDocument,
} from "@/wire/v1";

/** Upload's own document, re-read once after a success (brief 4.2, decision
    12). Reuses `sectionUrl` and the v1 parser rather than the section-status
    classifier in `@/app/transport`, whose union of the v1 documents this
    control has no reason to narrow. */
export async function refetchUpload(caseId: string): Promise<UploadDocument | null> {
  const url = sectionUrl("upload", { case: caseId });
  if (!url) return null;
  let response: Response;
  try {
    response = await fetch(url, { headers: { accept: "application/json" } });
  } catch {
    return null;
  }
  if (!response.ok) return null;
  try {
    return parseUploadDocument(await response.json());
  } catch {
    return null;
  }
}

/** A stable key for the exact file set, order-sensitive, so two different
    selections of the same size never compare equal by accident. The intent's
    key is reused only for a retry of the same set after an offline answer. */
function fileSetKey(files: readonly File[]): string {
  return files.map((file) => `${file.name}:${file.size}:${file.lastModified}`).join("|");
}

export function AdmitSources({
  action,
  caseId,
  onAdmitted,
}: {
  action: ActionView | undefined;
  caseId: string;
  onAdmitted: (document: UploadDocument) => void;
}) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const { pending, result, run } = useCommand<SourcesAdmitted>();
  const [refreshFailed, setRefreshFailed] = useState(false);
  const refusal = action?.refusal ?? null;

  async function submit() {
    if (refusal || pending || files.length === 0) return;
    setRefreshFailed(false);
    const outcome = await run(fileSetKey(files), (intent) => admitSources(caseId, files, intent));
    if (outcome?.kind !== "ok") return;
    setFiles([]);
    if (inputRef.current) inputRef.current.value = "";
    const refreshed = await refetchUpload(caseId);
    if (refreshed) onAdmitted(refreshed);
    else setRefreshFailed(true);
  }

  return (
    <div className="admitsources" data-admit-sources>
      <label className="sr-only" htmlFor={inputId}>
        Documents to admit
      </label>
      <input
        ref={inputRef}
        id={inputId}
        type="file"
        multiple
        onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
      />
      <RefusedControl
        refusal={refusal}
        onClick={action ? () => void submit() : undefined}
        busy={pending}
        className="rb solid"
        reasonDisplay="inline"
        aria-label="Admit sources"
      >
        {pending ? "Admitting…" : `Admit${files.length ? ` ${files.length}` : ""}`}
      </RefusedControl>
      {result?.kind === "ok" ? (
        <p className="note ok" data-admit-sources-success>
          {result.receipt.source_ids.length} source(s) admitted.
        </p>
      ) : (
        <CommandOutcome result={result} success="" />
      )}
      {refreshFailed ? (
        <p className="note warn" role="alert" data-admit-sources-refresh-failed>
          The sources were admitted, but the pack could not be refreshed. Reload to see them.
        </p>
      ) : null}
    </div>
  );
}
