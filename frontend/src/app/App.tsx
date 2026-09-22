import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router";
import { forward, sectionFromPath } from "./sections";
import { Workspace } from "./Workspace";
import { Rail } from "@/chrome/Rail";
import { RegionState } from "@/states/RegionState";

/** A private 404 and an absent route share one neutral wording. */
function Absent() {
  const { search } = useLocation();
  const caseId = new URLSearchParams(search).get("case");
  const caseSearch = caseId ? `?case=${encodeURIComponent(caseId)}` : "";
  return (
    <div className="ap" data-section="absent">
      <div className="frame">
        <Rail section={null} entries={null} local={null} servedRole={null} search={caseSearch} />
        <main className="body" id="body" aria-label="Unavailable">
          <h1 className="sr-only">Unavailable</h1>
          <RegionState status={{ kind: "unavailable" }}>{() => null}</RegionState>
        </main>
      </div>
    </div>
  );
}

function Resolve() {
  const { pathname, search } = useLocation();
  const forwarded = forward(pathname, search);
  if (forwarded) return <Navigate to={forwarded.to} replace />;
  const section = sectionFromPath(pathname);
  if (!section) return <Absent />;
  return <Workspace key={section} section={section} />;
}

/** The evidence surface lives in the Workspace, under the visible snapshot it
    is bound to (brief 4.4, decision 9): a section, case or displayed-run
    change closes it, so no drawer outlives the view it was opened on. */
function Shell() {
  return (
    <Routes>
      <Route path="*" element={<Resolve />} />
    </Routes>
  );
}

export function App() {
  return (
    <BrowserRouter>
      {import.meta.env.MODE === "demo" ? (
        <aside className="demo-banner" aria-label="Demonstration mode">
          READ-ONLY DEMONSTRATION · SAMPLE DECISIONS · NOTHING IS PERSISTED
        </aside>
      ) : null}
      <Shell />
    </BrowserRouter>
  );
}
