# Findings round 3 (2026-09-23)

What each patcher decided per finding, and the re-review that ran on the patch.
`docs/rebuild/decisions.md` F71–F109 is the ledger; these are the fuller paragraphs.

- `decisions-mine.md` — store, worker, graph, model seam, deployment path.
- `decisions-edge.md` — API edge, identity, health, event stream.
- `decisions-evidence.md` — evidence, handoff, calculators.
- `decisions-frontend.md` — the React workspace (FE-1..FE-12).
- The deliverable and qualification patcher was stopped by the account's spend
  limit before it wrote its file; F108 summarises its patch from the diff.
- `findings-round3.md` — the adversarial re-review of the patch, stopped by the
  same limit after R3-5; F109 records what it found and N30 the rest.

The reviews these answer: `docs/rebuild/findings-round2.md` (the deployment
review, the eight-auditor sweep and the edge/identity review) and
`docs/rebuild/findings.md` (the second pass, AR-* and FP-*).
