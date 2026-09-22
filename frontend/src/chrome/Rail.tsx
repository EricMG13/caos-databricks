// The rail is the only navigation. Two groups: the nine sections with a count
// and a one-line state, then the section-local group. The foot carries the
// served role and two controls and no more (IA_SPEC.md 3).
import { NavLink } from "react-router";
import { ServedRole } from "./ServedRole";
import { SECTION_ABBREVIATIONS, SECTION_LABELS, sectionPath } from "@/app/sections";
import { RefusedControl } from "@/controls/RefusedControl";
import {
  SECTIONS,
  type RailEntry,
  type RailLocal,
  type Section,
  type ServedRole as Role,
} from "@/wire";

const ASK_SCOPE: Record<Section, string> = {
  directory: "the register",
  upload: "the source pack",
  analysis: "this case",
  book: "the book",
  run: "this run",
  model: "the projection",
  report: "this revision",
  committee: "the deliverable",
  admin: "the deployment",
};

export function Rail({
  section,
  entries,
  local,
  servedRole,
  search,
}: {
  section: Section | null;
  entries: RailEntry[] | null;
  local: RailLocal | null;
  servedRole: Role | null;
  /** The query to carry between sections, so the case travels with the reader. */
  search: string;
}) {
  const byId = new Map((entries ?? []).map((entry) => [entry.section, entry]));
  return (
    <nav className="rail" aria-label="Workspace">
      <div className="grp">Workspace</div>
      {SECTIONS.map((id) => {
        const entry = byId.get(id);
        return (
          <NavLink
            key={id}
            to={`${sectionPath(id)}${search}`}
            className={`sect${entry ? "" : " off"}`}
            aria-label={SECTION_LABELS[id]}
            data-section={id}
          >
            <span className="nm">{SECTION_LABELS[id]}</span>
            <span className="url" aria-hidden="true">
              {sectionPath(id)}
            </span>
            <span className="ct tabular">{entry?.count ?? ""}</span>
            <span className="ab" aria-hidden="true">
              {SECTION_ABBREVIATIONS[id]}
            </span>
            <span className="sub">{entry?.state ?? ""}</span>
          </NavLink>
        );
      })}
      {local ? (
        <div className="local" aria-label={local.title}>
          <div className="grp">{local.title}</div>
          {local.items.map((item) => (
            <div key={item.label} className={`sect${item.on ? " on" : ""}`}>
              <span className="nm">{item.label}</span>
              <span className="ct tabular">{item.meta}</span>
            </div>
          ))}
        </div>
      ) : null}
      {servedRole ? <ServedRole role={servedRole} /> : <div className="railrole">SERVED ROLE</div>}
      <div className="railfoot">
        <RefusedControl
          className="btn acc"
          reasonDisplay="hidden"
          refusal={{
            code: "ASK_UNPLACED",
            // Its own reason, no longer borrowed from `ACTION_UNPLACED`'s:
            // there is no Ask route at all, which is a different thing from a
            // control the section's read cannot judge.
            clears: `the API serves an Ask route scoped to ${section ? ASK_SCOPE[section] : "the workspace"}`,
          }}
          aria-label={`Ask about ${section ? ASK_SCOPE[section] : "the workspace"}`}
        >
          <span>ASK · {section ? ASK_SCOPE[section].toUpperCase() : "WORKSPACE"}</span>
          <span className="ab" aria-hidden="true">
            ASK
          </span>
        </RefusedControl>
        <RefusedControl
          className="btn"
          reasonDisplay="hidden"
          refusal={{
            code: "SIGN_OUT_UNPLACED",
            clears:
              "the authenticating proxy serves sign-out — this workspace holds no session of its own",
          }}
          aria-label="Sign out"
        >
          <span>SIGN OUT</span>
          <span className="ab" aria-hidden="true">
            OUT
          </span>
        </RefusedControl>
      </div>
    </nav>
  );
}
