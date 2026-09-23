// The case register (IA_SPEC.md 4.1, card 5a): one action per row and it is
// the same action — open the case. No batch state, no checkboxes, no second
// selection model. The v1 wire carries no sector, rating, pathway, snapshot
// or leverage; this table draws only what the host holds (brief 4.1,
// "Fixture fields dropped rather than faked").
import { Link } from "react-router";
import { Tag } from "@/ds/atoms";
import { stamp } from "@/ds/format";
import type { CaseRow } from "@/wire/v1";

/** Not exported by `@/wire/v1` on its own; the shape lives only on `CaseRow`. */
type RunSummary = NonNullable<CaseRow["latest_run"]>;

/** The one action a row has: open the case in Analysis. */
export function caseHref(caseId: string): string {
  return `/analysis/?case=${encodeURIComponent(caseId)}`;
}

const RUN_TONE: Record<RunSummary["status"], string> = {
  COMPLETE: "ok",
  RUNNING: "acc",
  BLOCKED: "warn",
  FAILED: "crit",
  CANCELLED: "warn",
};

function LatestRunCell({ run }: { run: RunSummary | null }) {
  if (!run) return <span className="m">No runs yet</span>;
  return (
    <span className="m">
      <Tag sev={RUN_TONE[run.status]}>{run.status}</Tag>
      {run.profile_id ? <span className="sub"> {run.profile_id}</span> : null}
      {run.selection_id ? <span className="sub"> · {run.selection_id}</span> : null}
    </span>
  );
}

export function CaseRegister({ rows }: { rows: CaseRow[] }) {
  return (
    // The register is wider than a 320 px viewport: it scrolls inside its
    // panel, so no row action is clipped out of reach, and the scroll region
    // is reached by keyboard and named (WCAG 1.4.10 and 2.1.1, finding FE-5).
    // Named for the rows it scrolls, not for the register: the panel around
    // it is a landmark already, and two landmarks with one name is what axe's
    // landmark-unique refuses.
    <div className="tscroll" tabIndex={0} role="region" aria-label="Case register rows">
      <table className="reg" data-register>
        <thead>
          <tr>
            <th scope="col">Case</th>
            <th scope="col" className="wrap">
              Title
            </th>
            <th scope="col" className="r">
              Created
            </th>
            <th scope="col">Standing</th>
            <th scope="col" className="r">
              Live sources
            </th>
            <th scope="col">Latest run</th>
            <th scope="col" className="r">
              <span className="sr-only">Action</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.case_id} data-case={row.case_id}>
              <td className="m">{row.case_id}</td>
              <td className="wrap">{row.title}</td>
              <td className="m r">
                <time dateTime={row.created_at}>{stamp(row.created_at)}</time>
              </td>
              <td>{row.standing}</td>
              <td className="m r">{row.live_sources}</td>
              <td>
                <LatestRunCell run={row.latest_run} />
              </td>
              <td className="r">
                <Link className="rowact" to={caseHref(row.case_id)}>
                  Open case
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
