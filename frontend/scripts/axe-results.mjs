export function summarizeAxeViolations(violations, { nodeLimit, includeHtml = false }) {
  return violations.map((violation) => ({
    id: violation.id,
    impact: violation.impact,
    help: violation.help,
    wcag: violation.tags.filter((tag) => tag.startsWith("wcag")),
    n: violation.nodes.length,
    nodes: violation.nodes.slice(0, nodeLimit).map((node) => ({
      target: node.target,
      ...(includeHtml ? { html: node.html } : {}),
      summary: node.failureSummary,
    })),
  }));
}
