import { useEffect, useRef } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router";
import { focusSectionHeading, pageTitle } from "./heading";
import { forward, sectionFromPath } from "./sections";
import { Workspace } from "./Workspace";
import { Rail } from "@/chrome/Rail";
import { RegionState } from "@/states/RegionState";

/** A private 404 and an absent route share one neutral wording. */
function Absent() {
  const { search } = useLocation();
  const caseId = new URLSearchParams(search).get("case");
  const caseSearch = caseId ? `?case=${encodeURIComponent(caseId)}` : "";
  useEffect(() => {
    document.title = pageTitle("Unavailable", caseId);
  }, [caseId]);
  return (
    <div className="ap" data-section="absent">
      <div className="frame">
        <Rail
          section={null}
          entries={null}
          local={null}
          servedRole={null}
          searchFor={() => caseSearch}
        />
        <main className="body" id="body" aria-label="Unavailable">
          <h1 className="sr-only" tabIndex={-1}>
            Unavailable
          </h1>
          <RegionState status={{ kind: "unavailable" }}>{() => null}</RegionState>
        </main>
      </div>
    </div>
  );
}

function Resolve() {
  const { pathname, search } = useLocation();
  const forwarded = forward(pathname, search);
  const section = sectionFromPath(pathname);
  // Between the unavailable page and a section, one tree replaces the other:
  // the rail link that was activated goes with it, and the workspace does not
  // count its own first render as a navigation. It is one, so focus goes to
  // the heading of what arrived rather than falling to <body> (WCAG 2.4.3,
  // FE-4, DF-7). A forward is not a page of its own.
  const page = forwarded ? null : section ? "section" : "absent";
  const shown = useRef<string | null>(null);
  useEffect(() => {
    if (page === null) return;
    if (shown.current !== null && shown.current !== page) focusSectionHeading();
    shown.current = page;
  }, [page]);
  if (forwarded) return <Navigate to={forwarded.to} replace />;
  if (!section) return <Absent />;
  // Not keyed on the section: the rail, which is the only navigation, must
  // outlive a navigation so the link that was just activated keeps its place
  // in the tab order (finding FE-4). Everything the reader sees is already
  // keyed on the request that produced it, inside the workspace.
  return <Workspace section={section} />;
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
