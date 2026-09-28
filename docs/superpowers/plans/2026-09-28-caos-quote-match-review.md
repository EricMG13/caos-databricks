# Confidence review — repeated near-match CI failure

The unchanged default branch and Analysis PR both failed `test_a_long_near_match_costs_no_more_than_the_page[edges]`: 1.021 and 1.010 seconds against the existing one-second limit. Other jobs passed. Read `_page_run`, `_one_match`, `_starts`, `_edge_equal`, `_match_at` and every caller of the shared search before editing.

Least confident about:

1. **Changing which citation anchors.** Both edge checks are pure predicates, with the same region check first and the same exact/normalized pass order. Only short-circuit evaluation order changes. The existing differential test compares the optimized matcher with every-start matching over 7,200 combinations of punctuation, regions, figures, repeated words and composed/decomposed Unicode.
2. **Optimizing a symptom without finding the work.** A punctuation-wrapped quote with 4,998 matching interior words proposes 45,001 starts. Its last word cannot match, yet each start first normalized and stripped the matching first edge. Checking the last edge first avoids that normalization. On the identical local fixture with coverage tracing enabled, three baseline runs took 0.406/0.390/0.505 seconds; the changed order took 0.252/0.245/0.243 seconds. No timing assertion or CI configuration changed.
3. **Hiding another refusal or region error.** Candidate bounds and region rejection still precede either edge access. Ambiguity detection and token slicing are untouched. Existing region, ambiguity, figure-punctuation and exact-first tests are the checks for these contracts.

No new helper, cache, dependency or matching rule was introduced. Quote normalization and handoff record tests pass, including the existing timing and differential regressions. Ruff lint/format, vocabulary, tested-definition and suppression-ratchet checks pass. No further bug was confirmed by the review; hosted CI must pass before merge. The user's prohibition on tournaments remains in force.
