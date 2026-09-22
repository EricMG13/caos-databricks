// Directory (IA_SPEC.md 4.1): the case register, v1 wire. Search and filter
// are fields the v1 Directory document does not carry (brief 4.1, decisions 1
// and 9); this section draws exactly the cases the actor holds live standing
// on and nothing else. Create case is a governed write this section owns
// (brief 4.2, slice 4.2i); grant and revoke are the other two (O21), in their
// own panel so the register keeps one action per row.
import { useState } from "react";
import { CaseAccess } from "./CaseAccess";
import { CaseRegister } from "./CaseRegister";
import { NewCase, refetchDirectory } from "./NewCase";
import type { DirectoryDocument } from "@/wire/v1";

export function DirectorySection({
  document,
}: {
  document: DirectoryDocument;
  tab: string | null;
}) {
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
  const { cases } = live.body;
  const createCaseAction = live.chrome.actions.find((a) => a.action === "CREATE_CASE");
  const [refreshFailed, setRefreshFailed] = useState(false);
  async function refresh() {
    const refreshed = await refetchDirectory();
    setRefreshFailed(refreshed === null);
    if (refreshed) setLive(refreshed);
  }
  return (
    <div className="col">
      <section className="pnl" aria-labelledby="directory-register-heading">
        <header>
          <h2 id="directory-register-heading">Case register</h2>
          <span className="cp">ONE ISSUER ENGAGEMENT PER ROW</span>
          <span className="right">
            <span className="tag">{cases.length} CASES</span>
          </span>
        </header>
        <div className="pb flush">
          <NewCase action={createCaseAction} onCreated={setLive} />
          <CaseRegister rows={cases} />
          {cases.length === 0 ? <p className="pb note">No case matches.</p> : null}
        </div>
      </section>
      <CaseAccess rows={cases} onChanged={() => void refresh()} />
      {refreshFailed ? (
        <p className="note warn" role="alert" data-access-refresh-failed>
          The membership changed, but the register could not be refreshed. Reload to see it.
        </p>
      ) : null}
      <p className="note">
        <b>One action per row, and it is the same action.</b> A row opens its case; everything else
        a case can do belongs to the section that owns it — granting and revoking standing to Case
        access below, admitting and withdrawing sources to Upload, approving a plan or accepting a
        run to Run, saving, signing, freezing and filing a revision to Report. There is no batch
        state and no second selection model, so nothing on this page can act on four cases at once
        without a person having read four cases.
      </p>
    </div>
  );
}
