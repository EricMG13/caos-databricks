// The accepted CP-CF projection, read only. Values are server strings: this
// view deliberately performs no model arithmetic or evidence navigation.
import { NoteList } from "@/ds/atoms";
import type { ModelDocument } from "@/wire/v1";

export function ModelSection({ document }: { document: ModelDocument; tab: string | null }) {
  const { body } = document;
  const forecast = body.forecast;
  if (!forecast) {
    return (
      <section className="pnl" data-model-v1 data-run={body.displayed_run_id ?? ""}>
        <header>
          <h2>Model</h2>
          <span className="cp">CP-CF</span>
        </header>
        {/* Why there is none, not only that there is none: an ended run is not
            waiting for a forecast, and a verdict that ended it has a name. */}
        <div className="pb note" data-model-unavailable>
          {body.unavailable_reason}
          {body.displayed_run_status !== null && body.displayed_run_status !== "RUNNING"
            ? ` · the run ended ${body.displayed_run_status}`
            : ""}
          {body.blocked_by ? ` on ${body.blocked_by.module_id}` : ""}
        </div>
      </section>
    );
  }
  return (
    <div className="col" data-model-v1 data-run={body.displayed_run_id ?? ""}>
      <section className="pnl">
        <header>
          <h2>Accepted forecast</h2>
          <span className="cp">{forecast.route_node_id}</span>
        </header>
        <div className="pb">
          <dl className="kv">
            <dt>Accepted</dt>
            <dd>
              <time dateTime={forecast.accepted_at}>{forecast.accepted_at}</time>
            </dd>
            <dt>Artifact</dt>
            <dd>sha256:{forecast.artifact_sha256}</dd>
            <dt>Record</dt>
            <dd>sha256:{forecast.record_sha256}</dd>
            <dt>QA</dt>
            <dd data-qa-status>{forecast.qa_status}</dd>
            <dt>Units</dt>
            <dd>
              {forecast.currency} · {forecast.scale}
            </dd>
            <dt>Perimeter</dt>
            <dd>{forecast.perimeter}</dd>
          </dl>
          <NoteList label="Limitations." values={forecast.limitation_flags} />
          <NoteList label="Validation warnings." values={forecast.validation_warnings} />
        </div>
      </section>
      <section className="pnl">
        <header>
          <h2>Periods</h2>
          <span className="tag">{forecast.periods.length}</span>
        </header>
        <div className="pb flush scroll">
          <table className="dense" data-model-periods>
            <thead>
              <tr>
                <th>Case</th>
                <th>Period</th>
                <th>Year</th>
                <th>Days</th>
                <th>Value</th>
                <th>Unavailable reason</th>
              </tr>
            </thead>
            <tbody>
              {forecast.periods.flatMap((period) => {
                const rows = period.values.length ? period.values : [null];
                return rows.map((value, index) => (
                  <tr key={`${period.case}-${period.period_id}-${value?.name ?? index}`}>
                    <td>{period.case}</td>
                    <td>{period.period_id}</td>
                    <td>{period.fiscal_year}</td>
                    <td>{period.days}</td>
                    <td>{value ? `${value.name}: ${value.value ?? "—"}` : "—"}</td>
                    <td>{value?.unavailable_reason ?? period.unavailable_reason ?? "—"}</td>
                  </tr>
                ));
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
