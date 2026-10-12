// Withdraw (spec B7): take one live entry out of the Book, never delete it.
// Drawn only where the Book read offers `WITHDRAW_BOOK_ENTRY` on the entry (a
// WRITER-or-above member of the entry's case, the entry live); the command
// rechecks that at commit. The reason is one of four words, and a note is
// required for Other. The press asks once more, naming the entry's own stored
// digest, which is what the server compares: the digest the Book served on the
// entry, never the Model's.
import { useId, useState } from "react";
import { withdrawBookEntry } from "@/app/commands";
import { ConfirmedControl } from "@/controls/ConfirmedControl";
import { CommandOutcome, useCommand } from "@/sections/run/controls";
import type { BookEntryView, BookEntryWithdrawn, WithdrawBookEntry } from "@/wire/v1";
import { WITHDRAWAL_NOTE_MAX, WITHDRAWAL_REASONS } from "./classification";

type Reason = WithdrawBookEntry["reason"];

const REASON_WORDS = new Set<string>(WITHDRAWAL_REASONS.map(([word]) => word));

function isReason(word: string): word is Reason {
  return REASON_WORDS.has(word);
}

export function canWithdraw(entry: BookEntryView): boolean {
  return entry.actions.includes("WITHDRAW_BOOK_ENTRY");
}

export function WithdrawEntry({
  entry,
  onWithdrawn,
}: {
  entry: BookEntryView;
  onWithdrawn: () => void;
}) {
  const [reason, setReason] = useState<Reason | "">("");
  const [note, setNote] = useState("");
  const { pending, result, run } = useCommand<BookEntryWithdrawn>();
  const noteHint = useId();
  const label = `${entry.issuer_name} · ${entry.analysis_date}`;
  const lack =
    reason === ""
      ? "a reason is chosen"
      : reason === "OTHER" && note.trim() === ""
        ? "a note is written for Other"
        : null;

  const noteMissing = reason === "OTHER" && note.trim() === "";

  async function submit() {
    if (reason === "" || lack !== null || pending) return;
    const trimmed = note.trim();
    const body: WithdrawBookEntry = {
      snapshot_sha256: entry.snapshot_sha256,
      reason,
      note: trimmed === "" ? null : trimmed,
    };
    const outcome = await run(body, (intent) =>
      withdrawBookEntry(entry.case_id, entry.entry_id, body, intent),
    );
    if (outcome?.kind === "ok") onWithdrawn();
  }

  return (
    <div className="book-withdraw" data-withdraw={entry.entry_id}>
      <label className="fld">
        Reason for withdrawing {label}
        <select
          value={reason}
          onChange={(event) => setReason(isReason(event.target.value) ? event.target.value : "")}
        >
          <option value="">Choose a reason</option>
          {WITHDRAWAL_REASONS.map(([word, text]) => (
            <option key={word} value={word}>
              {text}
            </option>
          ))}
        </select>
      </label>
      <label className="fld">
        Note {reason === "OTHER" ? "(required)" : "(optional)"}
        <textarea
          value={note}
          rows={2}
          maxLength={WITHDRAWAL_NOTE_MAX}
          aria-required={reason === "OTHER" ? true : undefined}
          aria-invalid={noteMissing ? true : undefined}
          aria-describedby={noteMissing ? noteHint : undefined}
          onChange={(event) => setNote(event.target.value)}
        />
      </label>
      {noteMissing ? (
        <span className="fld-hint" id={noteHint}>
          A note is required for Other.
        </span>
      ) : null}
      <ConfirmedControl
        action="WITHDRAW_BOOK_ENTRY"
        refusal={lack === null ? null : { code: "REQUEST_INVALID", clears: lack }}
        busy={pending}
        step={{ act: "Withdraw entry", subject: label, digest: entry.snapshot_sha256 }}
        onConfirm={() => void submit()}
        aria-label={`Withdraw entry ${label}`}
      >
        {pending ? "Withdrawing…" : "Withdraw entry"}
      </ConfirmedControl>
      <CommandOutcome result={result} success={`${label} withdrawn from the Book.`} />
    </div>
  );
}
