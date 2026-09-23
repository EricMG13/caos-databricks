// Upload's second governed write (Task 12.1's `WITHDRAW_SOURCE`, placed here
// by Task 12.2): take one admitted source out of the live set. The control
// renders from the document's own `chrome.actions` -- present and refused,
// never hidden (CLAUDE.md "Persona is not authority") -- and the command
// rechecks authority and the source's own standing at commit whatever this
// control shows. On success the section refetches its own document once, and
// it is that re-read pack, never this control, that says the source is gone.
import { withdrawSource } from "@/app/commands";
import { ConfirmedControl } from "@/controls/ConfirmedControl";
import { CommandOutcome, useCommand } from "@/sections/run/controls";
import type { ActionView, SourceRow, SourceWithdrawn } from "@/wire/v1";

export function WithdrawSource({
  action,
  caseId,
  row,
  onWithdrawn,
  reasonDisplay = "inline",
}: {
  action: ActionView | undefined;
  caseId: string;
  row: SourceRow;
  onWithdrawn: () => void;
  /** Hidden when the pack states the one refusal every row shares. */
  reasonDisplay?: "inline" | "hidden";
}) {
  const { pending, result, run } = useCommand<SourceWithdrawn>();
  const refusal = action?.refusal ?? null;

  async function submit() {
    if (refusal || pending) return;
    const outcome = await run(row.source_id, (intent) =>
      withdrawSource(caseId, row.source_id, intent),
    );
    if (outcome?.kind === "ok") onWithdrawn();
  }

  return (
    <>
      {/* A withdrawal takes a pinned source out of the live set and the v1
          wire has no command that puts it back, so it asks once more and
          names the file and its digest (finding FE-7). */}
      <ConfirmedControl
        refusal={refusal}
        busy={pending}
        step={{
          act: "Withdraw source",
          subject: row.filename,
          digest: row.document_sha256,
        }}
        onConfirm={action ? () => void submit() : undefined}
        className="rb"
        reasonDisplay={reasonDisplay}
        action="WITHDRAW_SOURCE"
        aria-label={`Withdraw ${row.filename}`}
      >
        {pending ? "Withdrawing…" : "Withdraw"}
      </ConfirmedControl>
      <CommandOutcome result={result} success={`${row.filename} withdrawn.`} />
    </>
  );
}
