// Demo fixtures derived from other fixtures, kept free of Vite so the unit
// tests can build the same documents the demo server serves.

/** The `blocked` fixture: the partial analysis of a run that ended BLOCKED, the
    first pending node's verdict carrying the quotes `run.blocked.json` holds
    (N141). Derived from the two, so neither can drift from it. */
export function blockedAnalysis(partial: string, run: string): string {
  const doc = JSON.parse(partial);
  const [node] = doc.body.pending;
  doc.body.displayed_run_status = "BLOCKED";
  doc.body.blocked_by = {
    ...JSON.parse(run).body.run.blocked_by,
    route_node_id: node.route_node_id,
    module_id: node.module_id,
  };
  return JSON.stringify(doc);
}

/** The `blocked` answer: the derived analysis, or a 404 where `run.blocked.json`
    is missing, as every other missing fixture answers. */
export function blockedResponse(partial: string, run: string | null): [number, string] {
  return run === null ? [404, "{}"] : [200, blockedAnalysis(partial, run)];
}
