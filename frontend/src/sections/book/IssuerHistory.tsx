// An issuer's disclosure row: the limitations stored with its displayed entry,
// and its earlier entries newest first, withdrawn ones included (spec B15).
// Withdraw is offered here (on the displayed entry and on any earlier entry
// still live) where the server's `actions` on that entry say this viewer may.
import { WithdrawEntry, canWithdraw } from "./WithdrawEntry";
import type { BookIssuer } from "./filter";

const REASONS = {
  ADDED_IN_ERROR: "Added in error",
  DATA_ERROR: "Data error",
  SUPERSEDED_SOURCES: "Sources superseded",
  OTHER: "Other",
} as const;

export function IssuerHistory({
  issuer,
  id,
  span,
  onWithdrawn,
}: {
  issuer: BookIssuer;
  id: string;
  span: number;
  onWithdrawn: () => void;
}) {
  const { limitations } = issuer.displayed;
  return (
    <tr className="book-detail" id={id} data-history={issuer.issuer_key}>
      <td colSpan={span} className="l">
        <div className="book-detail-body">
          {limitations.length > 0 ? (
            <section data-limitations={issuer.issuer_key} aria-label="Limitations">
              <h3>Limitations stored with this entry</h3>
              <ul>
                {limitations.map((text) => (
                  <li key={text}>{text}</li>
                ))}
              </ul>
            </section>
          ) : null}
          {issuer.history.length > 0 ? (
            <section aria-label="Earlier entries">
              <h3>Earlier entries</h3>
              <ul>
                {issuer.history.map((entry) => (
                  <li key={entry.entry_id} data-history-entry={entry.entry_id}>
                    <span>{entry.analysis_date}</span> · <span>{entry.reporting_period}</span> ·{" "}
                    <span>{entry.route}</span>
                    {entry.withdrawn_at === null ? null : (
                      <>
                        {" "}
                        · <strong>Withdrawn</strong> {entry.withdrawn_at.slice(0, 10)}{" "}
                        <span>
                          {entry.withdrawal_reason ? REASONS[entry.withdrawal_reason] : null}
                        </span>
                        {entry.withdrawal_note ? <> · {entry.withdrawal_note}</> : null}
                      </>
                    )}
                    {canWithdraw(entry) ? (
                      <WithdrawEntry entry={entry} onWithdrawn={onWithdrawn} />
                    ) : null}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          {canWithdraw(issuer.displayed) ? (
            <section aria-label="Withdraw this entry" data-withdraw-displayed tabIndex={-1}>
              <h3>Withdraw the displayed entry</h3>
              <WithdrawEntry entry={issuer.displayed} onWithdrawn={onWithdrawn} />
            </section>
          ) : null}
        </div>
      </td>
    </tr>
  );
}
