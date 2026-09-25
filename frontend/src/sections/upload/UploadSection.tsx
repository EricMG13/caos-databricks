// Upload (IA_SPEC.md 4.2, card 5c): the admitted sources and their set
// versions, v1 wire. Withdrawal is checked live at every use, not at pin
// time; pinning and withdrawing are governed commands the v1 document does
// not carry (brief 4.1, decision 5). Admit sources is the one governed write
// this section owns (brief 4.2, slice 4.2i).
import { useState } from "react";
import { AdmitSources, refetchUpload } from "./AdmitSources";
import { SetVersions } from "./SetVersions";
import { SourcePack } from "./SourcePack";
import {
  ACTION_UNPLACED,
  SharedRefusal,
  drawnRefusal,
  sharedRefusal,
} from "@/controls/RefusedControl";
import type { UploadDocument } from "@/wire/v1";

export function UploadSection({ document }: { document: UploadDocument; tab: string | null }) {
  // 4.2 owns only this control's own refetch (decision 12); the SSE-driven
  // refresh every other section gets is 4.4's. A new document from the
  // parent (navigation, a future poll) always wins over a stale local one --
  // adjusted during render (React's documented pattern for this), never in
  // an effect, so there is no cascading extra render.
  const [live, setLive] = useState(document);
  const [seen, setSeen] = useState(document);
  if (document !== seen) {
    setSeen(document);
    setLive(document);
  }
  const { body } = live;
  const rows = body.sources;
  const withdrawn = rows.filter((row) => row.withdrawn_at !== null).length;
  const admitAction = live.chrome.actions.find((a) => a.action === "ADMIT_SOURCES");
  const withdrawAction = live.chrome.actions.find((a) => a.action === "WITHDRAW_SOURCE");
  // The pack's two commands, refused for one reason, say it once and each
  // keeps it as its description (brief 5, Upload; 6.3). Withdraw counts only
  // where a row could be withdrawn.
  const withdrawable = rows.some((row) => row.withdrawn_at === null);
  const packRefusal = withdrawable
    ? sharedRefusal([
        drawnRefusal(admitAction?.refusal ?? null, admitAction !== undefined),
        withdrawAction ? withdrawAction.refusal : ACTION_UNPLACED,
      ])
    : null;
  // A withdrawal changes a row this section is already drawing, so the pack is
  // re-read whole rather than edited here: what a source's standing is now is
  // the server's answer, never this component's (invariant 1).
  const [withdrawRefreshFailed, setWithdrawRefreshFailed] = useState(false);
  async function reread() {
    setWithdrawRefreshFailed(false);
    const refreshed = await refetchUpload(body.case_id);
    if (refreshed) setLive(refreshed);
    else setWithdrawRefreshFailed(true);
  }
  return (
    <div className="cols two">
      <div className="col">
        <section className="pnl" aria-labelledby="source-pack-heading">
          <header>
            <h2 id="source-pack-heading">Source pack</h2>
            <span className="cp">One user-provided document per row</span>
            <span className="right">
              <span className="tag">{rows.length} sources</span>
              {withdrawn > 0 ? <span className="tag warn">{withdrawn} withdrawn</span> : null}
            </span>
          </header>
          <div className="pb flush">
            <AdmitSources
              action={admitAction}
              caseId={body.case_id}
              onAdmitted={setLive}
              reasonDisplay={packRefusal ? "hidden" : "inline"}
            />
            {packRefusal ? <SharedRefusal refusal={packRefusal} lead="Admit and withdraw" /> : null}
            {rows.length ? (
              <SourcePack
                rows={rows}
                observedAt={live.observed_at}
                action={withdrawAction}
                caseId={body.case_id}
                onWithdrawn={() => void reread()}
                reasonSaid={packRefusal !== null}
              />
            ) : (
              <p className="pb note">The pack holds no source.</p>
            )}
            {withdrawRefreshFailed ? (
              <p className="note warn" role="alert" data-withdraw-refresh-failed>
                The source was withdrawn, but the pack could not be refreshed. Reload to see it.
              </p>
            ) : null}
          </div>
        </section>
        <details className="help">
          <summary>What withdrawing a source does</summary>A withdrawn source stays in the set
          versions that admitted it, because a set never changes. Any new use of it is refused, and
          every conclusion that cited it is marked.
        </details>
      </div>
      <div className="col right">
        <SetVersions versions={body.set_versions} />
      </div>
    </div>
  );
}
