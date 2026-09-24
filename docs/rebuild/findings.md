# Current audit findings — Astra max — 2026-09-24

**Verdict: BLOCK under the requested adversarial-review rubric.** **18 current findings: 2 P1 and 16 P2; 3 notes; 1 separate owner-recorded limitation.** Six base WARNING findings promote to CRITICAL under the skill's cross-persona rule; the other twelve are WARNING (the CI guard promotes from NOTE). Practical priorities and demonstrated consequences govern triage. The P1 items are the unreachable research workflows and stand-in profile redirection.

This replaces this reviewer's previous MAX list. The independent historical FP review is retained verbatim below and is not a second current findings list. The five requested scopes each received an adversarial assignment and a separate engineering/Databricks-skills assignment, using **Astra at max**. The runtime allowed three child reviewers alongside the coordinator, below the requested maximum of five.

**Version boundary:** reviews began at `01d4c5795f6e80bf4230867b28a8038331d6dfb0`. Another task merged `9b591af3d8e6e175c0bdcbee04b2f67765bb75b0` during the audit. The final deliverable skills pass used that merged snapshot; retained findings were revalidated against it through current probes or explicitly identified source checks. Locations below name the merged tree. Original proof results remain tied to their original revision; the verification section states the limits of the merge follow-up.

No code was edited. The only repository write by this audit is this findings-document replacement.

## Status, 2026-09-24 (backlog/r24)

Each finding below was patched and ledgered in `decisions.md`; the text after this table is the audit as delivered.

| Finding | Resolution |
|---|---|
| R24-01 | F279 |
| R24-02 | F274 |
| R24-03 | F280 |
| R24-04 | F281 |
| R24-05 | F266 |
| R24-06 | F267 |
| R24-07 | F268 |
| R24-08 | F269 |
| R24-09 | F270 |
| R24-10 | F271 |
| R24-11 | F277 |
| R24-12 | F282 |
| R24-13 | F283 |
| R24-14 | D49 |
| R24-15 | F276 |
| R24-16 | F284 |
| R24-17 | F278 |
| R24-18 | F272 |
| R24-N01 | F285 |
| R24-N02 | F275 |
| R24-N03 | F273 |
| R24-L01 | Record only (D39, N34); not a defect to patch |

## Current findings

### R24-01 — Advertised research routes cannot receive their required brief

**P1 · WARNING → CRITICAL under persona promotion (Saboteur, New Hire).** [Pin command](/Users/ericguei/Documents/caos-databricks/caos/api/commands/runs.py:204); [closed input model](/Users/ericguei/Documents/caos-databricks/caos/api/wire.py:1230).

The Run API advertises and creates both `LITE_DEEP_RESEARCH` and `DEEP_RESEARCH`, but Pin input accepts only a subject. The [store](/Users/ericguei/Documents/caos-databricks/caos/store/run_inputs.py:440) requires a research brief for these routes; neither the command nor its browser control can supply one. Both research workflows stop before execution.

**Evidence:** Three disposable-DB API checks passed: both advertised research routes create with 201, subject-only pin returns 500 `RUN_INPUT_INVALID`, and adding a valid brief returns 400 `REQUEST_INVALID`. The same run/source/subject pins successfully through the store when given that brief. The ordinary earnings route pins with 200. No paid call was needed. **Repair direction:** carry a validated brief through the wire model, form, command and request digest, retaining the existing route-specific validation. [Detailed proof](/tmp/caos-r24-api-delta-wFIe8s/delta-report.md).

### R24-02 — An explicit CLI profile redirects a stand-in deployment to that workspace

**P1 · WARNING → CRITICAL (Saboteur, Security Auditor).** [Stand-in child environment](/Users/ericguei/Documents/caos-databricks/tests/workspace_stub.py:718).

The wrapper removes the environment's profile selector but leaves the CLI configuration accessible and forwards `-p/--profile`. Real CLI 1.17.0 resolves the explicit profile's host and credentials instead of the loopback host. A copied [manual deployment command](/Users/ericguei/Documents/caos-databricks/docs/DEPLOYMENT.md:53) can therefore make workspace changes when the operator expected only the local stand-in.

**Evidence:** With two loopback servers and a synthetic temporary profile, wrapped validation and deployment returned 0; the wrapper's own server received zero requests, while the alternate server received app creation, permissions and **586 uploaded files**. Omitting the profile reached only the intended server; an empty config made the named profile fail before workspace calls. No real profile, credential or workspace was used. The committed profile-free CI commands are unaffected. **Repair direction:** provide a private empty config and prevent explicit profile selection from leaving the stand-in for supported command forms. This is accidental operator redirection, not a remote production-app exploit. [Detailed proof](/var/folders/81/bwblpst93lb6wb3lwrk8k6800000gn/T/caos-r24-adversarial-deploy-otvktxp7/report.md).

### R24-03 — A late Report save overrides a later navigation

**P2 · WARNING → CRITICAL (Saboteur, New Hire).** [Save success callback](/Users/ericguei/Documents/caos-databricks/frontend/src/sections/report/FilingControls.tsx:310).

Save a Report revision, then navigate to another case before the response arrives. The unmounted form's success callback uses its captured search-parameter setter and returns the reader to the abandoned Report. The F160 mounted/identity protection on Create run does not cover this producer.

**Evidence:** A mounted real ReportSection, command receipt parser and router navigated to the other case's Analysis, then returned to the old Report when a valid deferred 201 receipt arrived. The regression assertion fails on current code. No cross-case write or draft loss was demonstrated. **Repair direction:** require the sending view's navigation identity to remain current before changing the address; allow its already-authorized save to finish. [Detailed proof](/tmp/caos-r24-api-delta-wFIe8s/delta-report.md).

### R24-04 — Create run retains a revision belonging to the previous run

**P2 · WARNING (New Hire).** [Create run success callback](/Users/ericguei/Documents/caos-databricks/frontend/src/sections/run/controls.tsx:440).

Report-to-Run navigation carries the saved revision. Creating another run changes only `run`; the old `revision` survives into Report or Committee. Their [reader](/Users/ericguei/Documents/caos-databricks/caos/api/reads/reports.py:147) correctly refuses the mismatched pair with `DELIVERABLE_NOT_FOUND`, breaking the ordinary navigation chain.

**Evidence:** A mounted CreateRunControl with the real command/receipt and `sectionUrl` retained the old revision after a valid creation response. Its regression assertion fails. The mismatched HTTP request was source-traced, not separately DB-executed. A first run without a revision is unaffected; selecting a run by the existing selector clears dependent selection correctly. **Repair direction:** clear `revision` when creation changes `run`, while preserving independent query parameters. [Detailed proof](/tmp/caos-r24-api-delta-wFIe8s/delta-report.md).

### R24-05 — A transient schema-check connection failure permanently ends worker startup

**P2 · WARNING (Saboteur).** [Database error classification](/Users/ericguei/Documents/caos-databricks/caos/store/__init__.py:375); [startup retry loop](/Users/ericguei/Documents/caos-databricks/caos/graph/worker.py:577).

`apply_schema` translates every native `psycopg.Error`, including connection loss, into `STORE_SCHEMA_DRIFT`. The startup loop retries `STORE_UNAVAILABLE` but permanently returns for drift. F114 fixes the original pre-thread failure; this inner classification still leaves the worker stopped after a recoverable database interruption.

**Current evidence:** A real disposable-DB connection was ended during the worker's schema boundary. Native SQLSTATE 57P01 became drift; boot returned 2 after one connection attempt without driving work. Immediate manual configuration and schema verification succeeded, with the run still queued. Existing retry tests passed but bypass this transformation; the closed-connection schema test explicitly expects the wrong classification. **Repair direction:** preserve operational unavailability separately from actual migration/history incompatibility. [Current merged-source proof](/tmp/caos-r24-store-9b-TAxPxo/report.md).

### R24-06 — A temporary authority refusal permanently excludes a valid paid answer from replay

**P2 · WARNING (Saboteur; New Hire countercheck).** [Refusal classification](/Users/ericguei/Documents/caos-databricks/caos/store/outcomes.py:272); [live execution](/Users/ericguei/Documents/caos-databricks/caos/graph/runtime.py:649); [replay selection](/Users/ericguei/Documents/caos-databricks/caos/methodology/canonical.py:896).

If an approver loses standing while a valid completion is in flight, its answer and bill are saved, then `GATE_APPROVAL_MISMATCH` becomes an immutable answer-refusal row. Restoring the approver makes the stored answer valid again, but replay excludes it permanently. This contradicts the code's distinction between run/authority faults and answer verdicts.

**Current evidence:** A real local worker/store route with deterministic completions reproduced the refusal, restored both released gates, and revalidated the original answer successfully. `replay_billed` nevertheless returned none. An explicit user Retry produced two billed CP-0 attempts and four bills for three route nodes. This is lost reuse after deliberate Retry; there was no automatic duplicate spend, accounting loss, ceiling bypass or acceptance while authority was revoked. **Repair direction:** preserve typed run-versus-answer failure provenance and keep temporary authority failures out of immutable answer explanations; retain fresh authority checks. [Current merged-source proof](/tmp/caos-r24-store-9b-TAxPxo/report.md).

### R24-07 — CP-DR validation feedback disappears before the second attempt

**P2 · WARNING → CRITICAL (Saboteur, New Hire).** [Dossier messages](/Users/ericguei/Documents/caos-databricks/caos/methodology/handoff.py:1313); [string-only filter](/Users/ericguei/Documents/caos-databricks/caos/methodology/handoff.py:1334).

The dossier validator's `ValueError` object is returned as feedback, then silently dropped by the downstream string-only filter. The reserved second attempt receives no explanation for this deterministic research failure, despite D30's fifth addendum claiming the gap closed.

**Evidence:** On the initial snapshot, a small real CP-DR fixture with coverage 60 instead of the computed 50 passed the ordinary vendor/completeness validators, failed the dossier check, and received host `HANDOFF_INCOMPLETE`. Public `retry_feedback` returned an empty tuple. The existing helper-level test passes because its assertion itself converts the exception to a string. A current small helper/filter check reproduced the dropped exception and accepted the same explanation as a string; the full new-fork dossier path was not rerun. **Repair direction:** perform bounded string conversion at the vendor exception boundary and check the composed feedback path. Invalid dossiers still refuse. [Original proof](/tmp/caos-r24-model.0jFjvY/adversarial-model-report.md); [current reconciliation](/tmp/caos-r24-skills-model.oHVTNQ/current-merge-reconciliation-9b.md).

### R24-08 — A resend can start after the total provider deadline

**P2 · WARNING (Saboteur).** [Resend loop](/Users/ericguei/Documents/caos-databricks/caos/models.py:158); [sender start](/Users/ericguei/Documents/caos-databricks/caos/models.py:289).

The deadline is checked before back-off and `check_resend()`. The next iteration starts a sender even when that check or scheduling has consumed the remaining time; `_invoked` starts the thread before joining for zero seconds.

**Evidence:** The initial snapshot's logical-clock probe returned the first 429 at second 237, waited two seconds, and spent two seconds in the fence check. A second request started at second 241 against the 240-second total budget; its immediate fake answer was accepted and charged. Production resend checks perform store reads. No provider, wall-clock wait, lease takeover or database double-billing was exercised. F116 repairs the old multiplication of per-try deadlines. The merged implementation retains the same missing pre-start guard by source review; the timing probe was not repeated. **Repair direction:** recompute the remaining budget after the fence and refuse before starting a sender when none remains. [Original proof](/tmp/caos-r24-model.0jFjvY/adversarial-model-report.md); [current reconciliation](/tmp/caos-r24-skills-model.oHVTNQ/current-merge-reconciliation-9b.md).

### R24-09 — Body quote matching retains quadratic near-match work

**P2 · WARNING → CRITICAL (Saboteur, Security Auditor).** [Body quote matcher](/Users/ericguei/Documents/caos-databricks/caos/methodology/handoff.py:845); [public parser](/Users/ericguei/Documents/caos-databricks/caos/methodology/handoff.py:866).

Repeated first words propose many candidate positions; each candidate copies a quote-sized body slice and performs further comparisons. A single late-failing quote still requires work proportional to body tokens times quote tokens. The citation-count cap and ordinary-case index do not bound this dimension.

**Evidence:** Previously completed tiny operation-count probes with 24/48/96 body tokens copied 156/600/2,352 token references before correctly refusing. Entire wires were 199/271/415 bytes. This proves superlinear work and public-parser reachability on the original snapshot. Current source retains the same copying algorithm; no current timing or resource claim is added. No enlarged workload was run. The separate evidence-anchor matcher now uses linear KMP and fixes original MAX-06. **Repair direction:** preserve typography semantics with linear matching or a declared work bound. [Original proof](/tmp/caos-r24-model.0jFjvY/adversarial-model-report.md); [current source check and limitations](/tmp/caos-r24-skills-model.oHVTNQ/current-merge-reconciliation-9b.md).

### R24-10 — Parenthesized numbers can round or raise during table projection

**P2 · WARNING → CRITICAL (Saboteur, New Hire).** [Sign conversion](/Users/ericguei/Documents/caos-databricks/caos/methodology/tables.py:169); [Analysis projection](/Users/ericguei/Documents/caos-databricks/caos/api/reads/analysis.py:344).

Unary minus on a Decimal applies the ambient precision. A positive 30-digit number remains exact, while its accounting-parenthesis form rounds under the normal 28-digit context. A small parenthesized exponent can also raise `decimal.Overflow` before the plain-notation size bound handles it.

**Evidence:** `123456789012345678901234567890` stays exact; its parenthesized form becomes `-123456789012345678901234567900`. `(1e1000000)` raises while the positive counterpart returns no display value. On the original snapshot, a 2,440-byte CP-0 handoff with the offending supplemental table passed real pinned validation and then failed `handoff_tables`; the clean control passed both. Analysis, and its Model/Book consumers, reach this path; full DB/HTTP reads were not run for this example. The current public cell reader independently reproduced both defects using the current vendor contract; full current accepted-handoff/HTTP reproduction was not run. This affects derived display/read availability, not the canonical calculator ledger. **Repair direction:** use context-independent sign handling and bounded error/size checks. [Original proof](/tmp/caos-r24-model.0jFjvY/adversarial-model-report.md); [current reconciliation](/tmp/caos-r24-skills-model.oHVTNQ/current-merge-reconciliation-9b.md).

### R24-11 — A required CI command can be disabled without failing the integrity checker

**P2 · NOTE → WARNING (Saboteur, Security Auditor).** [Command extraction](/Users/ericguei/Documents/caos-databricks/scripts/check_gate_config.py:583); [CI checks](/Users/ericguei/Documents/caos-databricks/scripts/check_gate_config.py:665).

The checker verifies required `run:` text but ignores its step's execution condition. A contributor can leave the command intact and add `if: false`; the advertised regression guard still says the gate configuration holds. The committed mypy step currently runs unconditionally.

**Evidence:** In a separate tracked copy, the full checker returned 0 for unchanged configuration and for a mypy step disabled with `if: false`. Adding `--ignore-errors` to the command returned 1. Original MAX-13 Ruff/coverage examples now all return 1, so their repairs hold. The merged CI-check branch also accepts a disabled Ruff step and rejects a removed command; that current branch check is distinct from the initial full copied-checker proof. This is a regression-protection gap, not a claim that current CI skips checks or that a runtime user can disable it. **Repair direction:** associate required commands with their step/job conditions and reject unapproved ways of disabling them. A same-repository checker cannot prevent arbitrary malicious self-rewriting. [Detailed proof](/tmp/caos-r24-deliverable.c6cpcQ/report.md).

### R24-12 — Model charts label dimensionless ratios as monetary amounts

**P2 · WARNING; library/fullstack pass.** [Chart units](/Users/ericguei/Documents/caos-databricks/frontend/src/sections/model/ModelSection.tsx:107).

All forecast lines receive the currency and scale, including margin, leverage, coverage and FCF/debt ratios. The host calculator and API preserve correct ratio values; the rendered annotations give them the wrong dimension.

**Evidence:** A real host forecast fixture passed through the actual API conversion, typed frontend parser and mounted ModelSection. Gross leverage rendered and announced `10.0000 USD millions (host-verified)`. The monetary debt-closing control correctly carried monetary units. The regression assertion fails. **Repair direction:** derive or carry each line's dimension; retain money units for money, multiples for leverage/coverage, and explicit ratios or correctly scaled percentages for margins. No stored calculation corruption was shown. [Detailed proof](/tmp/caos-r24-api-delta-wFIe8s/delta-report.md).

### R24-13 — Analysis presents incomplete aggregates as complete and can hide the nearest maturity

**P2 · WARNING; library/fullstack pass.** [Partial-sum helper](/Users/ericguei/Documents/caos-databricks/frontend/src/sections/analysis/figures.tsx:37); [maturity pre-filter](/Users/ericguei/Documents/caos-databricks/frontend/src/sections/analysis/figures.tsx:231); [nearest-date claim](/Users/ericguei/Documents/caos-databricks/frontend/src/sections/analysis/figures.tsx:243).

Captions sum known segment/add-back values without qualifying the missing components. The maturity transform also drops an entire facility when principal is unavailable, removing its known maturity before choosing the nearest date and building the chart/table.

**Evidence:** A small CP-1 fixture with supported `n/a` cells passed real validation and table conversion. The mounted UI stated `100 USD m across 2 segments` and `Net +10 USD m across 2 add-backs` despite one missing component in each. It showed only 300 principal due in 2030 and named that facility nearest, although the intact source table disclosed another facility due in 2028 with unknown principal. Two regression assertions fail. Segment marks/table correctly show unavailable values and an unavailable total; their caption contradicts them. This is not universal null-to-zero behavior, and exact arithmetic is not the fault.

**Repair direction:** preserve completeness through aggregation, explicitly identify known subtotals or withhold complete totals, and retain facilities with unknown amounts. Choose the nearest known date independently of principal availability. The raw source/API values remain intact; evidence used validated synthetic data and mounted UI, not a persisted provider run. [Detailed proof](/tmp/caos-r24-api-delta-wFIe8s/delta-report.md).

### R24-14 — The one-command deployment still cannot select Lakebase Autoscaling

**P2 · WARNING; reconfirmed compatibility limitation, explicitly deferred F146/N45.** [Bundle variable](/Users/ericguei/Documents/caos-databricks/databricks.yml:25); [resource binding](/Users/ericguei/Documents/caos-databricks/databricks.yml:96); [deployment evidence E8](/Users/ericguei/Documents/caos-databricks/scripts/enterprise_deploy.py:456).

The committed bundle requires a Provisioned instance, preflight/E8 use that API, and runtime selects `CAOS_LAKEBASE_INSTANCE` ahead of the Autoscaling endpoint. A workspace with only Autoscaling resources cannot use the committed deployment path. Runtime support and a backlog entry do not supply the missing deployment selector.

**Evidence/limits:** Real CLI validation/deploy/run passed for the existing Provisioned loopback path. Installed SDK 0.140.0 and CLI 1.17.0 expose distinct database/postgres resource shapes; the committed path was source-traced. Current [official app-resource documentation](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/lakebase) states new Provisioned resources cannot be created after March 12, 2026 and warns that changing an existing resource type changes role identity. No live Autoscaling injection, grants or credential mint was tested. **Repair direction:** implement and qualify an explicit deployment choice with the corresponding environment/resource/permission contract. Existing Provisioned deployments were not shown broken. [Detailed reconciliation](/var/folders/81/bwblpst93lb6wb3lwrk8k6800000gn/T/caos-r24-adversarial-deploy-otvktxp7/report.md).

### R24-15 — Comma-containing group names break the one-command deployment

**P2 · WARNING; library/DevOps pass.** [CLI variable transport](/Users/ericguei/Documents/caos-databricks/scripts/enterprise_deploy.sh:56).

The wrapper passes group display names through CLI `--var`, whose separate parser splits values at commas even when the shell argument is quoted. A supported group such as `Research, Credit` passes preflight but fails deployment validation. The existing model-price path already uses the environment variable form to preserve commas.

**Evidence on both commits:** The actual wrapper with CLI 1.17.0, private synthetic configuration and a loopback workspace returned E1=0/E2=1, with no app/deployment created. A space-only name passed; `BUNDLE_VAR_group_admin='Research, Credit'` also passed and preserved the exact name in the app environment and permission. The [official group reference](https://docs.databricks.com/aws/en/dev-tools/cli/reference/groups-commands) describes human-readable display names; the application/runbook impose no comma prohibition. **Repair direction:** use the existing `BUNDLE_VAR` pattern for both group names and remove competing `--var` arguments. Default hyphenated groups remain unaffected. [Current proof](/tmp/caos-r24-skills-deploy-rcad9xdn/report.md).

### R24-16 — A page map can show a complete evidence block that cannot be cited

**P2 · WARNING; library/model pass.** [Per-block selection](/Users/ericguei/Documents/caos-databricks/caos/methodology/selection.py:184); [citation delivery check](/Users/ericguei/Documents/caos-databricks/caos/evidence/citations.py:689); [required original-line blocks](/Users/ericguei/Documents/caos-databricks/caos/evidence/citations.py:883).

The map chooses a prefix of blocks from each page. The current whole-line matcher treats each width-bounded block as an eligible evidence line, but its delivery check still requires every block of the original source line. Showing the first block while withholding its continuation therefore makes an otherwise valid quote fail `CITATION_NOT_DELIVERED`. The prompt explicitly calls the shown text citable evidence.

**Current small proof:** Real preparation/packing of a 4,100-byte source produces blocks of 4,096 and 3 characters. With a reduced 4,096-byte test map budget, the first block is shown intact. Its complete quote anchors under current `WHOLE_LINE` when both blocks are delivered; the identical quote fails when only the map's first block is delivered. The current pure production walker supplies the index; unexpected DB access fails the probe.

**Production reachability is a separate inference:** 384 ordinary text pages of this shape fit document/page/token admission bounds. All packed text totals 1,574,016 bytes, exceeding the 1,572,864-byte default gate budget; the first blocks fit exactly. The default selector therefore produces the same cut, leaving this source's displayed evidence unusable. No full-size source, model call or DB/HTTP run was executed. Mixed sources lose only partially delivered original lines. **Repair direction:** align selection and citation delivery granularity, retaining complete required groups or refusing before a paid call when the minimum map cannot fit. The current packing/whole-line changes were explicitly rechecked. [Current proof and arithmetic](/tmp/caos-r24-skills-model.oHVTNQ/current-merge-reconciliation-9b.md).

### R24-17 — A verified ZIP can extract a different page because local sizes are unchecked

**P2 · WARNING; library/deliverable pass.** [Local header validation](/Users/ericguei/Documents/caos-databricks/caos/deliverable/verify_package.py:108); [central-only CRC and sizes](/Users/ericguei/Documents/caos-databricks/caos/deliverable/verify_package.py:120).

The verifier compares local flags/method against the central directory but trusts only central CRC and sizes when reading and checking each member. Contradictory local size metadata can therefore direct a general extractor to different bytes from those the verifier validated.

**Current proof:** The normal five-member host package and a STORED repack both verified and extracted the same 1,578-byte page. Changing only `deliverable.html`'s local CRC/compressed/uncompressed sizes to zero left all content, receipts and central metadata intact. The full verifier and its detached stdlib-only invocation still succeeded; both system `bsdtar` and `unzip` extracted an empty page with exit 0. Flags/method were zero and no data descriptor was present. A changed-method control correctly refused. **Repair direction:** compare local CRC and both sizes with the central values before selecting the body. This concerns an untrusted tampered archive accepted by the portable verifier; normal generated packages remain valid, and no signature, receipt or filing-authorization forgery was demonstrated. [Full controls](/tmp/caos-r24-skills-deliverable-styMwZ/report.md).

### R24-18 — Qualification rejects whole-line keys its citation matcher accepts

**P2 · WARNING; library/deliverable pass.** [Precheck token comparison](/Users/ericguei/Documents/caos-databricks/caos/qualification/harness.py:802); [admission refusal](/Users/ericguei/Documents/caos-databricks/caos/qualification/harness.py:836).

F228's impossible-key precheck uses raw token equality, a stricter rule than the authoritative whole-line citation matcher. It rejects supported edge-punctuation normalization before a satisfiable case can qualify.

**Current public-boundary proof:** A real admitted synthetic line ending with a full stop accepts its exact answer key. Removing only the final full stop, or wrapping the complete line in curly quotes, still anchors through public `verify_citations(rule=WHOLE_LINE)` and matches the matrix's expected tuple. Public `assert_admissible` nevertheless raises `QUALIFICATION_KEY_UNANSWERABLE` for both variants, with zero provider calls. Every word remains present; the current whole-line policy expressly allows these punctuation variations. **Repair direction:** reuse the authoritative matcher or make the precheck demonstrably permissive relative to it, preserving impossible-key rejection before spend. [Proof and accepted controls](/tmp/caos-r24-skills-deliverable-styMwZ/report.md).

## Owner-recorded limitation

### R24-L01 — Raw usage normalization remains under D39's record-only decision

[Current host usage check](/Users/ericguei/Documents/caos-databricks/caos/models.py:237) receives counts after the adapter normalizes them. The initial real-SDK/in-memory-transport proof accepted boolean, numeric-string and integral-float counts as integers; missing/null and negative counts refused. Conservative reservations held, with no overspend or released-budget bypass demonstrated.

The merged [D39 decision](/Users/ericguei/Documents/caos-databricks/docs/rebuild/decisions.md:263) explicitly records N34 only while retaining D7's adapter. The adapter bytes and relevant host behavior remain unchanged by source comparison. This is not repaired, but the owner's disposition removes it from the actionable/blocking findings in this rerun. No current raw-transport probe was repeated. [Original evidence](/tmp/caos-r24-model.0jFjvY/adversarial-model-report.md); [current disposition](/tmp/caos-r24-skills-model.oHVTNQ/current-merge-reconciliation-9b.md).

## Notes

### R24-N01 — Credential-mint ownership ends before a timed-out helper finishes

[Mint timeout](/Users/ericguei/Documents/caos-databricks/caos/store/lakebase.py:178); [lock release](/Users/ericguei/Documents/caos-databricks/caos/store/lakebase.py:138). After timeout, the caller releases `_MINTING` while its daemon helper remains alive. After the failure-cache interval, another caller can create a second helper. Two event-controlled calls with short scaled deadlines demonstrated overlap on the merged code; both helpers were then released and joined, leaving no surviving helper. The installed [SDK OAuth call](https://github.com/databricks/databricks-sdk-py/blob/v0.140.0/databricks/sdk/oauth.py) has no request timeout. F113 repairs live-token waiters, but not this previously noted helper-lifetime residual. Retain ownership until completion or bound the underlying transport. No load/exhaustion or request-pool outage was demonstrated. [Current bounded evidence](/tmp/caos-r24-store-9b-TAxPxo/report.md).

### R24-N02 — Missing sync snapshots are mistaken for stand-in state ownership

[State cleanup](/Users/ericguei/Documents/caos-databricks/tests/workspace_stub.py:685). `all(...)` over an empty host set is true, allowing cleanup to remove local target state without positive loopback provenance. Real CLI `bundle summary` can produce this state: it downloads `resources.json` without a sync snapshot. The guard then deletes it without refusing. A subsequent summary re-downloaded the state, kept identical app/permission IDs and left remote resources unchanged. This is a recoverable local-cache/refusal-contract defect, not authoritative-state or remote-resource loss. Require positive provenance before deletion. [Evidence and recovery countercheck](/var/folders/81/bwblpst93lb6wb3lwrk8k6800000gn/T/caos-r24-adversarial-deploy-otvktxp7/report.md).

### R24-N03 — Qualification CLI default arithmetic runs before input validation

[Default ceiling calculation](/Users/ericguei/Documents/caos-databricks/scripts/qualify.py:370); [typed boundary](/Users/ericguei/Documents/caos-databricks/scripts/qualify.py:442). With no explicit run ceiling, an empty case manifest raises `DivisionByZero`; `--ceiling Infinity` raises `InvalidOperation`. Actual subprocesses exited 1 with raw Decimal errors, while a valid set/ceiling with absent configuration used the intended typed exit 2. The failures precede provider configuration, database creation and spend. Validate nonempty cases and finite ceilings before division/quantization. This is a local operator-experience note, not lost paid evidence or a budget bypass. [Evidence](/tmp/caos-r24-deliverable.c6cpcQ/report.md).

## Reconciliation with the replaced list

These dispositions concern the earlier concrete triggers on the new tree. A backlog entry is neither an implemented repair nor permission to weaken a contract. The independent historical FP report below remains a historical record, with its original counts and conclusions.

| Prior item | Current disposition |
|---|---|
| MAX-01 | Original transient-refusal key rotation repaired by F145; current command/caller tests passed. This rerun did not repeat the store-level ambiguous-commit injection. |
| MAX-02 | Original health-probe duplication/starvation repaired by F121; bounded live-thread controls passed. |
| MAX-03, MAX-15 | Rejected credential invalidation and SDK expiry-field handling repaired by F113; current tests and installed SDK shapes checked. No live cloud credential mint/revocation. |
| MAX-04 | Refused-call cancellation repaired by F115; real local worker/race tests retain the bill and terminate work correctly. |
| MAX-05 | F117 repairs absent/null and impossible counts; raw-type coercion remains R24-L01/N34, now explicitly record-only under D39. |
| MAX-06 | Retained-all-matches anchoring repaired by F128; focused equivalence and ambiguity-stop tests passed. R24-09 is the separate body-presence matcher. |
| MAX-07 | Standalone preflight import repaired by F137; actual documented subprocess test passed without ambient PYTHONPATH. |
| MAX-08, MAX-17 | Closed/buffered/truncated deployment evidence cases repaired by F136; targeted E6/E9 tests passed. Real Apps proxy liveness remains untested. |
| MAX-09 | Autoscaling deployment choice remains explicitly deferred, R24-14/F146/N45. |
| MAX-10, MAX-11, MAX-12 | Post-run refused qualification snapshot, multi-case capture and release-pack identity repaired and revalidated against local DB/real readers. |
| MAX-13 | Original Ruff-ignore, duplicate coverage threshold and narrowed-source examples now refuse. CI execution conditions remain R24-11; F167–F171 close the other named N46 omissions; the CI-condition residual was rechecked on the merge. |
| MAX-14 | CONNECTING now clears the live flag; current SSE tests passed. F195 also adds the server retry frame; live proxy behavior remains outside this audit. |
| MAX-16 | Finite Retry-After normalization contains NaN; current model checks passed. |
| MAX-18 | Reopened-run preview then Start/Retry works after F145. F195 now supplies the approval fingerprint in the read; the frontend still does not consume it on reopening, so the broader no-preview handoff remains deferred. |
| MAX-19 | Case-only navigation now subscribes to the displayed run; current mounted refresh/tail tests passed. The separate DB event-tail comparison was not rerun. |
| MAX-20 | The original pre-thread startup failure is repaired by F114; native failure transformed inside schema verification remains R24-05. |
| MAX-21 | F116 repairs the old per-try deadline multiplication/730-second scenario. R24-08 is the narrower remaining late-send gap; no new lease-overrun/double-billing scenario was demonstrated. |
| MAX-22 | Public-schema CREATE is now an explicit prerequisite; restricted-role actual process boot passed and the missing-schema-grant countercase refused. |
| MAX-N01, MAX-N02, MAX-N03 | Correct UUID scan path, complete manual bundle variables and shared exact charge context are repaired and checked. R24-10 concerns another Decimal projection path. |

The current deliverable pass revalidated duplicate-signature replay, qualification store/evidence binding, superseded-revision refusals, historical receipt provenance, new render/package reads and portable-package controls. It kept accepted latest-signer, legacy rendering and negative-CFO/parity policies. New F225 optional-field digest tagging, F226 reviewer/evidence binding and D44/F236 tolerance/CFO contracts are implemented and checked; their old omissions are not retained.

The merge also changes the disposition of older notes: F185/F220 add native immutability triggers, while separating the runtime role from schema ownership remains an enterprise prerequisite; F208 implements specified hidden-text markings, with additional visibility cases still listed as unobserved; F187 adds the stopped-worker state, and current recovery tests close N21's queued-cancel cleanup gap. D39 explicitly records N25/N34 and verdict revocation only, and closes N42 even though its backlog wording lags. N47's real-CLI-to-recorded-process integration remains open; F248 separately addresses stand-in OAuth. None of those statuses is substituted for live platform evidence.

## Method, skills and verification

The five adversarial assignments applied [adversarial-reviewer](/Users/ericguei/.codex/skills/adversarial-reviewer/SKILL.md) in Saboteur, New Hire and Security Auditor passes. The separate engineering assignments used [codebase-design](/Users/ericguei/.codex/skills/codebase-design/SKILL.md), the available library equivalent of the requested code-design example, and [code-reviewer](/Users/ericguei/.codex/skills/code-reviewer/SKILL.md) with relevant language rules. Specialist and Databricks skills were chosen for the actual scope. No finding was invented to satisfy a persona quota. Independent corroboration using another reviewer's probe is identified as such and is not counted as a second execution or an automatic severity promotion.

| Assignment / full evidence report (original snapshot unless stated) | Fresh verification and relevant skills |
|---|---|
| [Adversarial API / identity](/tmp/caos-r24-api-AAEe9s/report.md) | 56 targeted backend tests passed, 3 deselected; 3 disposable-DB API probes passed; 98 existing mounted frontend tests passed and 2 new regression assertions failed as expected. |
| [Adversarial store / graph](/tmp/caos-r24-store-BaP6Zk/report.md) | 38 selected tests passed; bounded real-DB startup and paid-answer recovery probes plus a two-helper credential control. |
| [Adversarial model / methodology / evidence](/tmp/caos-r24-model.0jFjvY/adversarial-model-report.md) | 204 tests passed, 2 explicitly excluded; real installed SDK adapters on an in-memory transport and small deterministic validator/Decimal/deadline probes. |
| [Adversarial deployment / stand-ins](/var/folders/81/bwblpst93lb6wb3lwrk8k6800000gn/T/caos-r24-adversarial-deploy-otvktxp7/report.md) | 24 selected tests passed, 17 deselected; real CLI 1.17.0 dev/prod validation and prod deployment/run passed locally; 586-file shipping check passed. Profile and state-recovery counterchecks used two loopback servers. |
| [Adversarial deliverable / qualification / calculators / gates](/tmp/caos-r24-deliverable.c6cpcQ/report.md) | 212 tests passed (13 qualification and 199 deliverable/calculator/package/parity), no skips; copied-tree gate mutations and actual CLI input-boundary controls. |
| [Engineering API / identity](/tmp/caos-r24-skills-api-Tpujcq/report.md) | senior-fullstack; Databricks Core, Apps authorization and Python SDK. 12 backend tests passed, 1 DB-dependent identity check skipped; 61 existing frontend tests passed, 3 new regression assertions failed as expected; accepted CP-1 and host forecast data fed through real API conversions and mounted components. |
| [Engineering store / graph](/tmp/caos-r24-skills-store-WyJ49d/report.md) | senior-backend; Databricks Core, Lakebase/connectivity and Python SDK. 30 tests passed; a new real PostgreSQL checkpoint-failure recovery control completed three nodes with exactly three calls/bills. First-pass defects corroborated by independent trace, without repeating those two probes. |
| [Engineering model / methodology / evidence](/tmp/caos-r24-skills-model.oHVTNQ/library-skills-model-report.md) | senior-ml-engineer; Databricks Core, Model Serving and Python SDK. 106 tests passed, 3 deselected; small packing/map/citation witness and focused model/evidence controls. |
| [Engineering deployment / stand-ins](/tmp/caos-r24-skills-deploy-rcad9xdn/report.md) | senior-devops; Databricks Core, DABs, Apps resources/deployment, Lakebase and Python SDK. 5 focused original-snapshot tests passed; real hermetic CLI group-name controls, with current-merge follow-up in the same report. |
| [Engineering deliverable / qualification / calculators / gates — merged 9b snapshot](/tmp/caos-r24-skills-deliverable-styMwZ/report.md) | senior-qa and manual dimensional-analysis; Databricks Core, SDK, Apps and Model Serving contracts. 222 tests passed (221 regressions plus a public-boundary counterexample); detached ZIP checks, dimension/context controls and current CI/CLI counterchecks. |

Pass counts are not additive: selections overlap across reviewers. Tests that assert the broken current behavior can pass while proving a defect. The five intentionally failing frontend regression assertions establish the listed navigation/display problems; ordinary existing tests passed. The one skipped identity test supplies no fresh coverage of that behavior. Early scratch harness/path/assertion errors were corrected and retained in evidence logs; they are not counted as product failures.

On the original snapshot, the coordinator separately ran Ruff lint and format checks (346 files), mypy (345 source files), frontend lint, all five read-only project gates and 82 gate tests. All passed. The five gates were configuration integrity, tested-name coverage, I/O budget (29 route modules), vocabulary and ICM integrity. The original frontend dependencies were stale and failed typechecking; an external HEAD snapshot received the committed lockfile's cached dependencies with lifecycle scripts disabled. Typechecking and a production build then passed, exporting 25 routes. The 708 kB chunk warning is the already-recorded N65 limitation, not a new finding. No original dependency tree or lockfile was changed.

Verification used targeted local runs, not a full CI/coverage claim. It did not include a live workspace, actual authentication provider, paid model, real Apps proxy, live Lakebase grants/failover, exhaustive hidden-PDF validation, or resource-exhaustion work. Mounted UI probes used jsdom and controlled network responses, not Chromium end-to-end against the deployed application. Platform statements were checked against installed SDK/CLI source and cited primary documentation; local stand-ins do not establish live platform qualification.

One model/evidence review was interrupted by the service's cybersecurity restriction and resumed only permitted source/fixture correctness work under standard safeguards. No blocked operation was repeated, no workaround or model switch was used, and uncompleted live/stress coverage remains outside the claim. The direct SDK-discovery test that could contact/discover external configuration and the large transport allocation test were explicitly excluded. PDF child verification used only an external no-bytecode harness adjustment, with source unchanged.

All probes, copied-tree mutations, caches, installs, builds and detailed evidence stayed outside the repository. The coordinator captured 1,588 original file hashes and then all 1,593 tracked files at the external merge. No auditor changed repository code, tests, configuration, vendor files, dependencies or other audit reports. The authorized final write replaces only this findings document; the independent historical FP content inside the details block is preserved byte for byte. The pre-existing `.impeccable/` and intermittently present local settings were untouched. No audit commit or external deployment was made. The existing documented local test-Postgres service was started for these checks and remains running; disposable test databases were removed.

### Current-merge follow-up

The workspace changed externally from `01d4c579` to `9b591af` while the reviews ran: 499 files changed. Original evidence was preserved with its revision. The final deliverable skills assignment switched to the new frozen snapshot; other retained findings received bounded revalidation as below. This does not claim that all 499 changed files received two new full audits.

| Current 9b follow-up | Result and limits |
|---|---|
| [API/identity/display](/tmp/caos-r24-api-delta-wFIe8s/delta-report.md) | All five findings persist: 3 DB research-route checks passed, 5 mounted regression assertions reproduced four UI findings, 10 current identity/edge tests passed and 1 DB-dependent check explicitly skipped. No additional verified identity defect. |
| [Model/methodology/evidence](/tmp/caos-r24-skills-model.oHVTNQ/current-merge-reconciliation-9b.md) | 3 small checks passed: packing-2/WHOLE_LINE map disagreement, CP-DR helper/filter composition and public Decimal-cell reading. Deadline and body-copying findings are current-source corroboration using the versioned original proofs; neither resource nor timing probes were repeated. N34 moved to the owner-recorded limitation. |
| [Deployment](/tmp/caos-r24-skills-deploy-rcad9xdn/report.md) | Profile redirection, unknown-cache provenance and comma-group failure rechecked with hermetic loopback CLI/fixtures. N45/N47 source dispositions confirmed; no new full deployment/shipping or live platform claim. |
| [Store/graph](/tmp/caos-r24-store-9b-TAxPxo/report.md) | Both native-DB findings reproduced on 9b; 20 selected changed-contract tests passed with no skips, and four bounded probes exited 0. Checkpoint recovery completed three nodes with three calls/bills; two credential helpers were joined. All temporary fixture databases were removed. |
| [Deliverable/calculator/qualification](/tmp/caos-r24-skills-deliverable-styMwZ/report.md) | Full assigned scope reviewed on frozen 9b; 222 selected tests passed and the new ZIP/normalization findings proved. Changed owner decisions and current repairs were reconciled. |

Current coordinator checks also passed: Ruff lint/format (349 files), mypy (348 source files), frontend lint/typecheck, five project gates (30 route modules), 104 gate tests across the completed selections, and a production frontend build exporting 25 routes. Initial Git-aware checks on the archive export lacked Git metadata: lint and one history-dependent gate test were rerun successfully after attaching a matching external index/commit. This setup issue is not a product finding; the other 103 gate tests had already passed. The 708 kB bundle warning remains. No full CI, coverage or live qualification result is claimed for either snapshot.

---

## Preserved independent historical review

The independent focused pass below is retained verbatim from the earlier snapshot. Its findings, counts and source locations are historical; the current list and reconciliation above supersede this reviewer's prior MAX list.

<details>
<summary>Independent focused pass from the earlier snapshot — historical record</summary>

# Focused pass — deliverable chain, qualification, calculators and gate scripts — 2026-09-23

**Verdict: BLOCK.** **41 open findings (FP-01…FP-41): 11 CRITICAL, 12 WARNING, 18 NOTE.** Only FP-01 is CRITICAL at base severity. The other ten are base WARNING promoted because two or more personas raised them. Sort by base severity to rank by impact alone.

**Scope:**
- `caos/deliverable/` (all seven modules)
- `caos/qualification/` (all seven modules)
- `caos/calculators/cash_flow.py`
- the gate scripts `scripts/{scan_floors,check_gate_config,check_tested,check_vocabulary,io_budget,check_icm,check_pr_size,tracked,icm_stages,host_manifest,document_register}.py`
- `scripts/qualify.py` and `scripts/release_pack.py`
- the gate wiring: `.github/workflows/ci.yml`, `.pre-commit-config.yaml`, the `pyproject.toml` tool tables and `tests/gate_baseline.json`

Every file was read in full. Callers and tests were read for their contracts and to find test gaps. The tree reviewed is `rebuild/databricks` at `6aef850` plus the uncommitted changes as they stood at about 05:50 UTC.

**Method:**
- Claude Opus 5.5 coordinated four sub-agents, each running Saboteur → New Hire → Security Auditor:
  - the deliverable chain;
  - qualification matrix and harness;
  - qualification store, proof and verdict, with `qualify.py` and `release_pack.py`;
  - the gate scripts.
- The coordinator reviewed the calculator itself and re-read the code behind every CRITICAL.
- "Proven" means a probe reproduced the finding, either against disposable databases on the local test PostgreSQL (port 55437) or against scratch fixtures.
- The probe scripts are in the session scratchpad (`scratchpad/{deliverable,qual-a,qual-b,gates,calc}/`), not in the repo.
- No full suite or gate run was performed in this pass.
- This section is the only repo change made.

**Moving tree:** a concurrent session edited files in scope during the pass. Findings are stated against the tree as it ended. The concurrent fixes are listed under *Closed or narrowed during the pass*.

**Overlap with the first pass:** AR-07, AR-08, AR-09, AR-10, AR-15 and AR-18 still stand and are not counted again here. FP-10 extends AR-07. The separate "Second pass" below, appended by another session at the same time, overlaps in two places: AR-22 with FP-14 (the pack drops the model identity) and AR-25 with FP-08's forecast-value bullet. Its `R2-E1`, `R2-N1` and `R2-N2` are its own IDs, not part of this section.

## Critical findings

### FP-01 — A declared refusal is "met" by runs that did not end that way

**Base CRITICAL; Saboteur (two reviewers) + New Hire.** Location: `caos/qualification/matrix.py:481-519` (`_refusal_met`). The waiver that consumes it is `caos/qualification/store.py:122` (`PerformedEvidence.complete`).

`complete` skips its COMPLETE-status requirement for any row with `expected_refusal_met`. This one predicate therefore decides whether an unfinished or successful run can be signed as the refusal its case declared. It returns true in three situations where the run did not end in that refusal:

- **A stale attempt refusal on a COMPLETE run.**
  - `_ENDED` includes COMPLETE, and the final query matches any `attempt_refusals` row on any attempt of the run.
  - `qualify.py`'s `_perform_until` re-enters `perform` after a stop. A retried node then succeeds, the run completes, and the first attempt's refusal still matches.
  - Proven: `SECOND: stopped= None status= COMPLETE` → `expected_refusal_met=True` → `SNAPSHOT complete (signable): True`.
- **The proof-refusal branch runs before the "run must have ended" guard.**
  - `if proof_refusal is expected: return True` comes before the `_ENDED` check that the comment below it describes.
  - A run that was started and never driven (RUNNING), or was CANCELLED, fails its proof with `ORCHESTRATION_NOTHING_TO_PROVE`, and so meets a key declaring that code. Proven for both statuses.
  - `proof_refusal` is also overwritten by later reader refusals (`matrix.py:437-455`).
  - The loader (`on_disk.py:390-398`) accepts any `RefusalCode` as an expected refusal, including `STORE_UNAVAILABLE`.
- **`HANDOFF_BLOCKED` is met by the run status alone.**
  - Any BLOCKED run meets it, including one that CP-0 blocked before any handoff returned Blocked (no `run_blocking_verdicts` rows).
  - Proven: `run_blocking_verdicts rows: (0,)` → `signable: True`.

Tests assert the waiver only over a COMPLETE run (`tests/test_qualification_store.py:340`). No test exercises the `attempt_refusals` branch or the `_ENDED` guard.

**Repair direction:** answer a declared refusal from how the run actually ended:
- the run is BLOCKED or FAILED, never COMPLETE, RUNNING or CANCELLED;
- the code sits on the terminal attempt of a node that stayed unaccepted;
- `HANDOFF_BLOCKED` requires a `run_blocking_verdicts` row.

Also apply the ended check before every branch, keep the proof's own refusal separate from reader refusals, and restrict `expected_refusal` to methodology codes.

### FP-02 — The release pack marks a pathway QUALIFIED through any run in a signed snapshot

**Base WARNING → CRITICAL; Saboteur + Security Auditor.** Location: `scripts/release_pack.py:173-232` (`_snapshot_pins`, `qualified_pathways`).

A verdict covers every pathway that any run in its snapshot was pinned to. So a case on pathway P2 that met a declared refusal, or that FP-01 let through, makes P2 QUALIFIED although no run on P2 produced an output. Proven through the normal `record_verdict` path: `artifacts on ('FULL_CREDIT_32', 'DECISION_LEDGER') run: 0` → `QUALIFIED ('FULL_CREDIT_32', 'DECISION_LEDGER')`.

The pin is looked up by `(run_id, route_digest)` and never validated:
- A row with `resolved='{}'` is accepted, although `route_pin` refuses it with `ROUTE_IDENTITY_INVALID`.
- A run on the CP-CF-extended route qualifies the base pathway.
- The digest is never compared with what the current catalog resolves.

The test fixture `_pin` (`tests/test_release_pack.py:151-166`) itself inserts `resolved='{}'`.

**Repair direction:** count a pathway only through a case on that pathway that proved, answered its keys and reached COMPLETE. Read the pin through `route_pin`, and require its digest to equal the current catalog's resolution with the same extensions.

### FP-03 — Signing, reading and the release pack trust stored derived state

**Base WARNING → CRITICAL; Saboteur + Security Auditor.** Locations: `caos/qualification/store.py:505` and `:554`; `scripts/release_pack.py:198-215`; `evidence_at` at `store.py:229-246`.

Three things are trusted without being re-checked:
- `qualification_performed.complete` is computed once, by whatever code recorded the snapshot, and trusted from then on.
- `performed_json` is never re-digested against `performed_sha256`.
- The pack re-runs neither `_models_recorded` nor any proof.

Two consequences:
- **Stale snapshots stay signable.** A snapshot recorded as complete under the old short-circuit `_answered` (fixed concurrently as F64) can still be signed, stays current and appears in the pack. Proven: `current code: complete = False` / `record_verdict: accepted; current_verdict: QUALIFIED`.
- **Inserted rows can forge QUALIFIED.**
  - The migrations block UPDATE and DELETE but not INSERT.
  - The app role can insert a verdict/evidence/performed triple with self-consistent, unkeyed SHA-256 digests over a FAILED run that has no artifacts.
  - Proven: `digest(performed_json) == performed_sha256 ? False` → `pack row status: QUALIFIED`.
  - The docstring's promise that tampered rows are refused holds only for inconsistent tampering.

**Repair direction:**
- Re-derive `complete` from `performed_json` in `record_verdict`, in `current_verdict` and in the pack, and refuse when it disagrees with the stored flag.
- Re-digest `performed_json`.
- In the pack, re-run `_models_recorded` and `assert_orchestration_proof` for each run.
- Longer term, key the verdict digest (HMAC or KMS).

### FP-04 — Filing does not re-prove the revision it files

**Base WARNING → CRITICAL; Saboteur + Security Auditor.** Location: `caos/deliverable/filing.py:192-240` (`file_deliverable_in`); the route is `caos/api/commands/deliverable.py:319-367`.

`freeze_in` re-derives the revision and compares it with the stored bytes. Filing only compares rows, and the route's `_reviewed` only checks the digest the client sent.

Scenario:
1. A revision is signed and frozen.
2. A WRITER withdraws a cited source. `withdraw_source` says every gate bound to that source reopens.
3. An approver files anyway, and `DELIVERABLE_FILED` enters the permanent audit chain for a deliverable the host can no longer prove.

Proven: `prove_revision after withdrawal: refused ARTIFACT_RECORD_MISMATCH` / `file_deliverable after withdrawal: FILED` / `DELIVERABLE_FILED events: (1,)`. The only record of this trade-off is the read budget `FILE_IO = 16`.

**Repair direction:** call `prove_revision` in `file_deliverable_in` and require its bytes to hash to the frozen digest, as `freeze_in` does. Raise `FILE_IO` to match.

### FP-05 — A filed deliverable becomes unreadable when live state moves

**Base WARNING → CRITICAL; Saboteur + New Hire + Security Auditor.** Locations: `caos/deliverable/receipts.py:38-39` and `:101-105`; `caos/deliverable/revisions.py:196-222`.

Every Committee read of a filed revision re-runs `prove_revision` against the current sources, the current bundle bytes and the current narrative rules. When that fails it refuses with the same codes tampering produces (`ARTIFACT_RECORD_MISMATCH`, `NARRATIVE_FIGURE_UNREFERENCED`).

Three ordinary events each lock every filed record out of the Committee section permanently:
- a WRITER withdrawing a source;
- a routine `vendor/deploy-v` upgrade;
- a tightened narrative rule, such as FP-06's fix.

The user is then shown remediation advice for a record that is immutable. Proven for withdrawal (FP-04's probe, and the existing `test_filed_receipt_requires_live_saved_payload_proof`) and for a rule change (`read after rule fix: refused NARRATIVE_FIGURE_UNREFERENCED`).

**Repair direction:**
- Serve a filed revision from its digest-checked bytes and its verified audit chain.
- Report live re-checks as a separate status, such as "evidence withdrawn since filing".
- Validate each revision under the rule and bundle version it was saved with.

This must land before FP-06's fix.

### FP-06 — Non-ASCII digits pass the every-figure-is-cited rule

**Base WARNING → CRITICAL; Saboteur + Security Auditor.** Location: `caos/deliverable/revisions.py:41`.

`any("0" <= character <= "9" ...)` only sees ASCII digits. `BoundaryText` applies NFC, which keeps fullwidth and other-script digits. So all of these are stored as uncited figures in committee prose, against invariant 11:
- `Leverage is ４.２x` (fullwidth)
- `٤٫٢x` (Arabic-Indic)
- `½`, `Ⅳ` and `𝟒`

Fullwidth digits arrive by pasting from Japanese or Chinese statements. Proven end to end through `save_revision`: `saved narrative: 'Net leverage is ４.２x, headroom ٤٥%.'`.

**Repair direction:** refuse any character for which `str.isnumeric()` is true, or test the NFKC form. Land it after FP-05, so revisions already saved stay readable.

### FP-07 — A store or bundle that moves mid-set discards every paid run

**Base WARNING → CRITICAL; Saboteur + New Hire.** Locations: `caos/qualification/matrix.py:472-474`, with `_gate_readiness` at `:527` and `_projections_met` at `:636`; `caos/qualification/harness.py:631-636` and `:672-676`.

The harness promises that a store or bundle moving under a running set stops the set and returns what it performed. Two paths raise instead, so `_persist_performed` never runs and the spend is left with no snapshot:
- **Unguarded readers.** `_cited` catches `ROUTE_IDENTITY_INVALID`; the readiness and projection readers do not. Proven: `perform RAISED: ROUTE_IDENTITY_INVALID after 6 paid calls` / `qualification_performed rows: (0,) call_outcomes: (6,)`.
- **Bundle re-verification.** `_record` → `_unrun` → `named_objects` re-verifies the bundle, but only `ROUTE_IDENTITY_INVALID` is caught. Proven: `perform RAISED: AUTHORITY_BYTES_MISMATCH after 4 paid calls` / `qualification_performed rows: (0,)`.

The readers also catch different exception sets:
- projections catch `Refusal` only;
- registers also catch `ValueError`, `TypeError` and `UnicodeDecodeError`;
- forecast also catches `ValueError` and `TypeError`.

Tests cover only `ROUTE_IDENTITY_INVALID`, and only through a monkeypatched `_cited`.

**Repair direction:** read the route once per row under the `_ROW_REFUSALS` guard and pass it to every reader. Record any `Refusal` raised by `_unrun`, or compute `named_objects` once before the loop.

### FP-08 — The answer-key loader leaves fields unchecked; one path discards a paid snapshot

**Base WARNING → CRITICAL; Saboteur (two reviewers) + New Hire.** Locations: `caos/qualification/on_disk.py:269` (`ForecastValue(**_closed(...))`) and `:439` (`_text` used for `matched_text` and labels); `caos/qualification/matrix.py:296`, `:309` and `:1282-1283`.

- **`matched_text` is unbounded and may contain NUL.** The key passes `prepare` and the whole route is paid for. Then `record_performed` fails with psycopg `UntranslatableCharacter`, which surfaces as `STORE_UNAVAILABLE`. The snapshot is lost and `qualify.py` writes no capture. Proven.
- **Forecast values load as JSON floats.** Host values are strings, so such a key can never match, and this shows only after the spend. `NaN` makes the digest raise an untyped `ValueError`. Proven.
- **Labels are handled differently in two places.**
  - A 200-character label loads, then the digest refuses it with `BOUNDARY_TEXT_TOO_LONG`, although the `_LABEL_LIMIT` comment says the loader bounds labels.
  - The digest strips and NFC-normalises labels, but `assert_unambiguous` compares raw labels. So `"A"` and `"A "` both pass, then collide.
  - The digest's sort then compares a `list` with a `str` and raises a raw `TypeError`.
  - Proven: `'<' not supported between instances of 'str' and 'list'`.

The manifest is written by the operator, but the loader is the boundary that is meant to catch these mistakes before any spend. Related to AR-09.

**Repair direction:** put forecast values, `_expect` fields and labels through `_bounded`/`BoundaryText` at load. Accept strings only. Normalise labels identically in `assert_unambiguous` and in the digest, and sort on `json.dumps(entry)`.

### FP-09 — The receipt and the filing event name only the latest signer

**Base WARNING → CRITICAL; New Hire + Security Auditor.** Locations: `caos/deliverable/filing.py:235` (`signatures[0][0]`) with `:289` (`ORDER BY signed_at DESC,signed_by`); rebuilt the same way in `caos/deliverable/receipts.py:74`.

Several approvers may sign before the freeze (`one_opinion_per_signer`). But the detached receipt, and the `filing_payload` that `DELIVERABLE_FILED` binds, carry one `signed_by`: whoever signed last.
- Earlier co-signers are absent from the portable proof and from the filing event.
- The offline verifier can prove the independence of only one signer.
- Nothing in the field name or the docstring says "latest".

Proven: `signers on revision: 2` / `first signer named anywhere in receipt: False`.

**Repair direction:** carry the sorted list of all signers in the receipt and in the filing payload, and have the verifier require that list to be disjoint from `frozen_by` and `filed_by`.

### FP-10 — Gate definitions come from the change under test

**Base WARNING → CRITICAL; Saboteur + Security Auditor. Extends AR-07.**

Locations:
- `scripts/check_gate_config.py:107-125`, `:141` and `:211`
- `scripts/check_pr_size.py:85`
- `scripts/tracked.py:39`
- `scripts/host_manifest.py:57-60`
- `.github/workflows/ci.yml:103-107`
- there is no CODEOWNERS file

`check_gate_config` reads a few `pyproject.toml` keys, while each tool also reads files and keys that the PR controls. In scratch fixtures, each item below passed `check_gate_config` and loosened its gate:

- **Sibling config files:**
  - `pytest.ini`, `mypy.ini`, a nested `caos/ruff.toml`, `.coveragerc` and `complexipy.toml`;
  - `caos/.bandit`, after which bandit reported `issues 0` on `os.system`, `shell=True` and `eval`.
- **`pyproject` keys the gate never reads:** ruff `per-file-ignores`, `[[tool.mypy.overrides]] ignore_errors`, coverage `source` and `exclude_also`, complexipy `ignore-complexity`.
- **The `addopts` substring test:** `--cov-fail-under=80 --cov-fail-under=0` passes it, and the last value wins.
- **The secret scan:** `gitleaks git` uses the PR's own `.gitleaks.toml`. One `[[allowlists]] paths` block turned `leaks found: 1` (exit 1) into `no leaks found` (exit 0).
- **PR size:** `* -diff` in `.gitattributes` makes `--numstat` print `-\t-` for every file, and line 85 skips such rows. `changed lines: 5000` became `0`.
- **The `vendor` hole:**
  - `tracked.py` excludes all of `vendor/`;
  - ruff's `extend-exclude = ["vendor"]` matches at any depth;
  - mypy, coverage and the PR-size check exclude `vendor/`.

  So a new `vendor/helpers/x.py` escapes every gate, and `caos/vendor/x.py` escapes ruff.
- **Wiring checked for presence only:**
  - Hooks are matched by `id:` alone, so `entry: "true"`, `--exit-zero` or `stages: [manual]` all pass.
  - CI steps are not checked at all: deleting the mypy step, or appending `|| true` to pytest, passes.
- **The host pin:** `host_manifest.py` rewrites both `icm/HOST_INTEGRITY_v1.json` and `caos/methodology/host_pin.py`. An edit to `cash_flow.py` or a prompt block plus one regeneration is therefore green. The pin catches drift in a deployed copy, not an unreviewed change. (Reasoned from the code, not run.)

None of this is invisible in a diff, but nothing routes such a diff to a required reviewer.

**Repair direction:**
- Evaluate the gates with the base branch's `scripts/`, tool configs, `.gitleaks.toml`, `.gitattributes`, baselines and `ci.yml`.
- Refuse sibling config files at any depth, and compare whole `[tool.*]` tables.
- Allow only `vendor/deploy-v/**` under `vendor/`.
- Count `-` and binary numstat rows as failures.
- Add CODEOWNERS for all of these files and for the host pin.

### FP-11 — The suppression budget undercounts, and the new ratchet compares mismatched counters

**Base WARNING → CRITICAL; Saboteur + New Hire.** Locations: `scripts/check_gate_config.py:67-76` (`SUPPRESSIONS`), `:271` and `:281-294`; `.github/workflows/ci.yml:140-148`; `tests/gate_baseline.json`.

- **Forms that are not counted, some already in the tree:**
  - `#\s*noqa\b` misses `# ruff: noqa`. Seven test fixtures carry `# ruff: noqa: E501` (e.g. `tests/cp1a_contract_fixtures.py:3`) and each counts zero.
  - Also uncounted: `# flake8: noqa`, `# mypy: ignore-errors`, `# complexipy: ignore`, `@unittest.skip`, `skipIf`, `SkipTest`, `@typing.no_type_check`, and `@pytest.mark.live_provider` (which conftest drops from every default run).
  - Each form was shown to silence its tool while counting zero.
- **Totals per kind:** a harmless `E501` noqa can be swapped for an `S608` or `BLE001` one without changing the count.
- **The complexity baseline counts entries, not values:** editing a recorded complexity to 500 let a function grow from 15 to 28 while complexipy exited 0.
- **The `--against` ratchet (added concurrently):**
  - The base numbers were produced by the old regexes. A tightened regex therefore reads as new suppressions, and a narrowed one frees budget.
  - The working tree already rises against `HEAD` (`no_cover` 5→6, `noqa` 124→125, `skip` 0→7), so the ratchet fails its own change.
  - The job runs only on `pull_request`, not on pushes to `rebuild/databricks` or `main`.
  - The PR `types` list omits `edited`, so a PR retargeted after going green is not re-checked.

**Repair direction:**
- Count every form listed above.
- Budget suppressions per rule code and per path.
- Ratchet complexity per `(path, function, value)`.
- Count the base tree with the PR's counter.
- Run the job on push and on `edited`.

## Warnings

### FP-12 — `_eligible` never compares the pinned subject with the case's subject

**WARNING; Security Auditor.** Location: `caos/qualification/harness.py:459-477`.

The transplant check compares title, ceilings, profile and selection, model extension, research and documents, but not `pin.subject`.

A real approved input pinned for issuer OTHER / FY2019 executes under a case signed for ACME / FY2026, and the evidence binds the ACME set digest. Proven: `evidence set digest == signed set digest: True` / `signable: True`.

`test_real_approved_input_transplants_are_refused` checks ten faults, none of them the subject.

**Repair direction:** add `pin.subject != case.subject` to `_eligible`, and a `"subject"` fault to that test.

### FP-13 — Verdicts are not bound to their evidence, can be backdated and cannot be withdrawn

**WARNING; Security Auditor.** Locations: `caos/qualification/verdict.py:38-45` and `:105-112`; `caos/qualification/store.py:486-505`, `:496` and `:567`.

- The reviewer's document names the set, build and provider:model, but not `performed_sha256` or `adapter_version`. One document therefore records against any number of complete snapshots, including snapshots from another adapter version.
- `decided_at` need only be ≤ now. Proven: evidence recorded 2026-09-23, verdict decided 2001-01-01.
- `expires_at` has no upper bound.
- Verdict rows are immutable and no revocation exists.
- `provider + ":" + model` is not injective: `("openrouter:x", "m")` and `("openrouter", "x:m")` give the same string. Proven.

**Repair direction:**
- Bind `evidence_sha256` inside the document.
- Require `decided_at ≥ recorded_at`, by the store's clock.
- Cap the validity window.
- Add a revocation record.
- Compare provider and model as a pair.

### FP-14 — The release pack omits who signed and which model was qualified

**Base NOTE → WARNING; Security Auditor + New Hire.** Location: `scripts/release_pack.py:216-221`.

Each entry carries `{evidence_sha256, reviewer, decided_at, expires_at}`. `reviewer` is free text an ADMIN types. The authenticated `reviewer_id`, the provider, the model and the set digest are all absent. Production's model is set by environment (D7), so a pack's QUALIFIED does not say what it covers. Proven: `signer's reviewer_id in pack? False`.

**Repair direction:** emit `reviewer_id`, provider, model and set digest in each entry, and mark QUALIFIED only for the deployed model's identity.

### FP-15 — `qualify.py` resolves paid routes from a catalog it never verifies

**WARNING; Security Auditor (invariant 4).** Location: `scripts/qualify.py:276`.

`catalog=json.loads((bundle.root / CATALOG).read_text())` bypasses the verified reader `caos.methodology.vendor.catalog(bundle)`. Execution later checks only the pin's build, manifest and adapter.

Proven on a scratch copy of the bundle with its catalog tampered:
- the verified reader: `AUTHORITY_BYTES_MISMATCH`;
- the `qualify.py`-style read: accepted, `FULL_CREDIT_32 pathways now 9`.

**Repair direction:** use `catalog=catalog(bundle)` after `bundle.verify_pinned()`.

### FP-16 — `qualify.py` keeps a paid run's blobs in the OS temp directory

**WARNING; Saboteur.** Location: `scripts/qualify.py:286` (`blob_root = Path(mkdtemp(prefix="caos-qualify-"))`).

The script insists on a persistent PostgreSQL server, but it puts blobs in `$TMPDIR`, which macOS purges. `assert_orchestration_proof` re-reads those blobs, so the evidence can't be re-proven once they are purged. The purge itself was not triggered.

**Repair direction:** require an explicit persistent blob root, as is already done for `CAOS_QUALIFY_POSTGRES_URL`, and refuse temp directories.

### FP-17 — The portable verifier never checks the narrative against the records it binds

**WARNING; Security Auditor.** Locations: `caos/deliverable/verify_package.py:131-164` (`_contents`); `caos/deliverable/render.py:552-553` and `:571`.

A narrative figure is rendered from its own copy of `document_sha256`, `page` and `matched_text`. That copy is never checked against the bound record's `citations[citation_index]`, and a plain-string narrative with arbitrary figures is also accepted. This is the payload's one internal cross-reference, and it goes unchecked while the verifier reports that the package is internally consistent.

Proven:
- `narrative figure not in its record -> Verification(verified=True, reason=None)`, and the page shows the forged quote and page 99;
- `string narrative with uncited figures -> Verification(verified=True, reason=None)`.

**Repair direction:** in `_contents`, resolve each figure's `route_node_id` and `citation_index` in the bound record and require all three fields to match. Refuse a string narrative when the receipt carries identity fields.

### FP-18 — `check_tested` can be satisfied without a test driving the code

**WARNING; Saboteur.** Location: `scripts/check_tested.py:56`, `:66` and `:92`.

The checker walks only `tree.body`, so these escape it:
- a public lambda assigned at module level;
- a `def` inside an `if` or `try`.

Two other ways to satisfy it:
- `@anything.get(...)` reads as a route.
- Referenced names form one set for the whole suite, so a name that matches another module's (e.g. `verify`) counts.

Proven: six untested public functions in a scratch module passed. The real tree does not currently rely on any of these forms.

**Repair direction:** resolve references per module (import source plus attribute), walk `If`/`Try` bodies and module-level assignments, and match routes by the actual router object.

### FP-19 — `io_budget --assert` accepts declarations that declare nothing

**WARNING; Saboteur.** Location: `scripts/io_budget.py:43`, `:48` and `:69`.

It passes in all of these cases:
- a router in `reports/__init__.py` (`__init__.py` files are skipped);
- `IO_BUDGET: int` with no value;
- `IO_BUDGET = float("inf")`;
- `IO_BUDGET = None`;
- routes moved outside `caos/api/`, where "no request paths yet; nothing to budget" exits 0.

All of these were proven.

**Repair direction:** include `__init__.py`, require a non-negative int, and fail when `caos/api` is missing.

### FP-20 — The document register checks paths as strings

**WARNING; Security Auditor.** Location: `scripts/document_register.py:109` and `:157`.

`relative_to(root.parent)` does not normalise `..`, and the containment test is a `startswith("qualification/")` string check. `qualification/set-a/../../../../../../../../../../etc/hosts` marked `in_hand` is emitted as a register row with its size and digest, and the script exits 0. Proven.

**Repair direction:** `resolve()` the path, require `is_relative_to(repo / "qualification")`, and refuse symlinks.

### FP-21 — Two security tests always skip in CI

**WARNING; Saboteur (CI environment).** Location: `tests/test_frontend_modes.py:44-48`.

CI's backend job installs no Node, and the frontend job runs no pytest. These two tests therefore never run anywhere, and the run passes:
- `test_the_dev_proxy_strips_client_identity_and_injects_the_local_actor` (invariant 3);
- `test_production_build_contains_no_fixture_or_demo_route`.

Proven: `SKIPPED [2] tests/test_frontend_modes.py:48`.

**Repair direction:** run them in the frontend job, or fail on skips when `CI=1`.

### FP-22 — The forecast refuses negative EBITDA, negative CFO and tax refunds

**WARNING; Saboteur.** Location: `caos/calculators/cash_flow.py:50` (`_SIGNED`) and `:272-274`.

Every movement except `acquisitions_disposals` and `fx_perimeter` must be non-negative. A driver with `ebitda`, `cfo` or `cash_taxes` of `"-5"` refuses the whole request with `METHODOLOGY_INPUT_INVALID`. So any borrower with negative EBITDA or cash burn cannot be forecast, although CP-CF is an opt-in extension on any route that carries CP-1, CP-2G and CP-4, the distressed-restructuring pathways included. This fails closed, but the refusal tells the user their input is invalid when it is a supported credit profile. Proven by probe.

**Repair direction:** sign `ebitda`, `cfo` and `cash_taxes` (the ratios already return null on a non-positive denominator). If the refusal is deliberate, give it a named reason and record it in `decisions.md`.

### FP-23 — The new tolerance cap is absolute, not relative to the balances

**Base NOTE → WARNING; Saboteur + Security Auditor.** Location: `caos/calculators/cash_flow.py:34-36` (`MAX_TOLERANCE`, F62) and `_tolerance`.

`validate_driver_mapping` requires `scale = millions`, so a tolerance of `1000` means 1bn. With the current tree, a debt residual of 999m on a 1,000m balance passes with `outcome: PASS` and `status: complete`. Proven by probe.

This is mitigated because the tolerance must be an evidence-anchored CP-2G quote (`validate_forecast_bindings`). The cap is still wide enough to switch the one arithmetic check off for most borrowers.

**Repair direction:** bound the tolerance relative to the opening balances, or to a fixed amount per scale, and test the limit.

## Notes

| ID | Location | Issue | Repair direction |
| --- | --- | --- | --- |
| FP-24 | `harness.py:326-343` | Recorded producers are never compared with the prepared model, so a run whose calls used another model builds a `complete` snapshot. `record_verdict`'s `_models_recorded` refuses it at signing. | Check `call_outcomes.model` before building the matrix, so the snapshot is not recorded as complete. |
| FP-25 | `matrix.py:323-352` | The set digest appends optional fields untagged and by position, so a subject and an `expects_ready` list encode identically. Proven collision; blocked in practice by `valid_subject` and `_consumers`. | Tag each optional entry. |
| FP-26 | `harness.py:740-741` | `_answerable` checks that a citation's document digest is a member, but not that its `matched_text` occurs in that document, so an impossible key is paid for and then reads as a model miss. | Check each `matched_text` against the admitted text before any spend. |
| FP-27 | `on_disk.py:246` | A symlinked document is recorded under its target's filename, not the declared path's last segment. Proven. | Use `Path(declared).name` after the containment check, or refuse symlinks. |
| FP-28 | `release_pack.py:173-181`, `:212-215` | `except Refusal: continue` swallows `VERDICT_BINDING_INVALID`, contradicting the docstring. A malformed `prepared` item raises a raw `KeyError`/`ValueError`. | Skip only `VERDICT_EXPIRED`; refuse with a typed code otherwise. |
| FP-29 | `qualify.py:216`, `:273`; `qualification/ba-fy2025-covenant-refinancing/` | `--attempts 0` or a negative number means 1. A missing `CAOS_MODEL_PRICE` is a `KeyError` traceback. The set has tracked documents but no `qualification.json`, so it refuses `QUALIFICATION_SET_FILE_INVALID`; the other 18 sets reproduce their `RESULT.md` digests. | Validate the arguments; add or remove the set. |
| FP-30 | `matrix.py:29`, `:168`, `:960`, `:1001-1009`; `harness.py:106`; `proof.py:289`; `store.py:219`, `:245` | The docstrings say "seven" projection fields, but there are eight. `_LABEL_LIMIT` is defined three times. The guard at `matrix.py:960` cannot fire. The per-node artifact query is written four times. `proof.py:289`'s pragma comment claims a lock that is not taken. `asdict(...).values()` and `Evidence(*row)` depend on field order matching the SQL columns. | Tidy while fixing FP-01/FP-07; use named columns. |
| FP-31 | `render.py:189-193` | On a CP-CF route, the other sections print "None performed by the host on this route." while the CP-CF section says the host performed a projection. | Say "for this module". |
| FP-32 | `deliverable/canonical.py:197-207` and three other places | `selection=("LITE_CREDIT_22", "LITE_FULL_CREDIT_SCREEN")` is repeated four times without explanation. The deliverable proof re-checks owner restrictions for CP-5 only, never CP-CF. | One named table next to `verify_owner_restrictions`. |
| FP-33 | `filing.py:65-85` | The narrative's `saved_by` is never compared with the signers, so an approver can write and sign the same opinion; the test harness does exactly that. | Decide; if unintended, refuse with `APPROVER_NOT_INDEPENDENT`. |
| FP-34 | `receipts.py:83-100` | `read_filed_receipt` checks only `DELIVERABLE_FILED`. The sign and freeze event checks live in the one caller, `_publication`. | Move them in, or state the required order in its contract. |
| FP-35 | `deliverable/*.py` docstrings | Rationale cites `docs/DECISIONS.md` and `SYSTEM_SPEC.md` sections; neither file exists in this repo. | Point at `docs/rebuild/decisions.md` entries. |
| FP-36 | `cash_flow.py:32`, `:195`, `:311-316` | Two guards cannot fire. `MAX_WORK = 100_000` is unreachable: the ceilings allow at most 40 × 6 × 41 = 9,840. `_check_chain` compares a closing with its own six-decimal serialisation of add/subtract results. Tests reach them only by monkeypatching `MAX_WORK` to 1 or calling `_check_chain` directly. | Delete, or set `MAX_WORK` to a bound that binds; say what `_check_chain` guards. |
| FP-37 | `cash_flow.py:222`, `:83-97` | `opening.as_of_period_id` is validated and then ignored, and period order within a case is the caller's. Reordered periods chain in the given order, and only the residual check catches them. | Check that `as_of` precedes each case's first period and that fiscal years ascend. |
| FP-38 | `cash_flow.py:288-296` | The duplicate key includes the amount, so two equal instalments (e.g. two quarterly 10s in one annual period) refuse, while 9 + 11 sums. Now documented as the legacy rule; fails closed. | Key by `(pair, facility, instalment_id)`, or require one aggregated row per facility. |
| FP-39 | `cash_flow.py:351` | `fcf = cfo − capex − cash_interest − cash_taxes` treats `cfo` as pre-interest and pre-tax, and nothing documents that. A reported US GAAP CFO double-counts both; the residual catches it only if stated closes are independent. | Name the definition in SKILL.md and the calculator docstring. |
| FP-40 | `ci.yml:146`, `:148` | `${{ github.base_ref }}` is interpolated into `run:` scripts. Exploiting it needs the right to create branches in the base repository. | Pass it through `env:`. |
| FP-41 | `check_vocabulary.py:76`, `:121`; `check_gate_config.py` `_bundle_problems`; `.pre-commit-config.yaml`; `tests/test_icm.py:110-112`; `tests/test_gate_scripts.py:533`; `tests/test_ci_hygiene.py:22-27` | Vocabulary misses acronym prefixes (`PDFChunk`, `LLMWorkflow`) and directory names. The bundle-sync check parses YAML with a regex. pre-commit hooks are pinned by mutable tags. `test_icm.py:110-112` compares output with itself. The io-budget guard test runs without `--assert`. `test_ci_hygiene` refers to a Dockerfile and a Makefile that do not exist. | Fix in passing. |

## Closed or narrowed during the pass

The concurrent session landed these while the review ran; they are not counted:
- F62 capped the tolerance (FP-23 is the remaining gap).
- F64 made `_answered` a conjunct (FP-03 covers snapshots already stored).
- F65 fixed the renderer hash truncated after escaping.
- F70 made `freeze_in` check every signature.
- F58 widened the suppression regexes to `NOQA`, `skipif` and `pytest.skip(...)`.
- `check_tested` now counts only names that are read.
- `on_disk.py` dropped its duplicate `MAX_MANIFEST_BYTES`.

For a while during the pass, `render.py` changed without the renderer-hash constant in `verify_package.py`, and 12 package tests failed; the constant has since been updated.

What held up:
- A 40,000-case fuzz of `render._markdown` produced no crash and no unclosed tag.
- HTML escaping and the ZIP limits (size, ratio and overlap) held.
- At the stated ceilings, the calculator cannot overflow its 38-digit context: the largest debt is about 2e20 and the largest ratio about 4e26.
- The calculator uses Decimal only and normalises negative zero.

## Summary of the focused pass

Fix FP-01 first. It is the only finding that is CRITICAL at base severity, and `qualify.py`'s retry loop makes it routine: a case can be signed QUALIFIED over a run that concluded, never finished, or blocked for another reason.

Next, make every reader of a verdict re-derive it from the stored document and the runs (FP-02, FP-03). Then settle the filing contract: re-prove at filing (FP-04) and serve filed records from their own bytes (FP-05).

On the gate side, FP-10 and FP-11 share one root cause: take gate definitions and baselines from the base branch and route their changes to a CODEOWNER.

---


</details>
