# Confidence review — workflow merge

Least confident about (ranked):

1. Demo fixture consumers split across PRs — CI failed the timestamp test in all three engines.
   investigated → Upload fixtures and the shared route list use the canonical UUID; the layout test alone still used the old case. The original integrated patch already corrected it, but that line landed in the later graph patch.
   verdict → CONFIRMED test bug.
   patch → Move that one-line URL correction into the workflow patch. The existing assertions pass in Chromium, Firefox and WebKit. A search of fixture, source, script and test consumers finds no remaining old UUID.
2. New default-branch changes lost during integration — Analysis and workflow changes both touch the stylesheet.
   investigated → The latest default branch merged without conflicts. Comparing the merged stylesheet with the reviewed complete interface leaves only the intentionally pending graph styles. All 526 unit tests, lint and type checking pass; the demo export builds all 25 routes.
   verdict → fine (tree comparison and checks).
   patch → n/a.
3. Duplicate shared quote repair — both PRs carried the same fix.
   investigated → The merged matcher exactly matches the default branch; no matching code or test limit changes in this workflow diff. Both earlier PR CI backend jobs passed the repair.
   verdict → fine (exact diff and CI).
   patch → n/a.

Fixed: the stale Upload test URL (F447).
Verified fine: fixture consumers, merged stylesheet, shared matcher and frontend checks.
By-design: graph appearance and motion changes remain in the final patch.
Still open: the fresh hosted checks on the updated workflow head must pass before merge.
