# Current audit findings — Astra max — 2026-09-23

**Verdict: BLOCK under the requested Adversarial Reviewer rubric.** The current list contains **22 findings: 13 promoted CRITICAL and 9 WARNING, plus 3 notes**. Every promoted finding has base severity WARNING; the promotion records two reviewer personas identifying the same issue. It does not mean 13 security breaches or production outages were demonstrated. The reopened-run workflow in MAX-18 has a separate P1 priority from the skills review.

**Scope and revision:** API edge and identity; store and graph; model seam, methodology and evidence; deployment and platform stand-ins; deliverables, qualification, calculators and gate scripts. Reviewed HEAD 653dc9ce91a73137360c43b81f14284d324de58f plus the working tree. This is a system review across callers, rather than a diff-only review.

**Method:** both requested passes were rerun as ten scoped assignments using gpt-6-astra at max, under standard safeguards. The first five used sequential Saboteur, New Hire and Security Auditor perspectives; the second five applied the relevant audit, design, specialist and Databricks skills. At most three child agents ran concurrently, four agents including the coordinator, within the user's maximum of five. Some completed agents were reused for a different scope. Duplicate findings were consolidated and unsupported leads excluded.

**Replacement and changes:** MAX identifiers replace this reviewer's prior AR-01–25 and R2 findings. The separate historical FP review written by another session is preserved below and is not included in current counts. This audit changes only this findings document. Application code, tests, configuration and vendor files were not edited by the reviewers.

## Critical findings under persona promotion

### MAX-01 — A typed store refusal changes the retry key after an ambiguous commit

**Base WARNING → CRITICAL; Saboteur + New Hire.** [controls.tsx:142](/Users/ericguei/Documents/caos-databricks/frontend/src/sections/run/controls.tsx:142), [store transaction:224](/Users/ericguei/Documents/caos-databricks/caos/store/__init__.py:224).

The browser retains an unchanged command's key for offline/invalid-response outcomes, but rotates it after a typed STORE_UNAVAILABLE. That refusal can follow a successful commit whose acknowledgement was lost. A disposable PostgreSQL probe injected failure after the real commit: the case and receipt existed, the same-key retry replayed them, and a fresh key created another case. A separate mounted production-hook probe confirmed that this typed 503 produces that fresh key. These are complementary database and React probes, not an end-to-end network fault test.

**Repair direction:** retain the command intent through commit-ambiguous refusals until its receipt is resolved. The previous unreadable-response defect is fixed; this typed-refusal variant remains.

### MAX-02 — Health recovery forgets probes that are still running

**Base WARNING → CRITICAL; Saboteur + New Hire.** [health.py:323](/Users/ericguei/Documents/caos-databricks/caos/api/health.py:323), completion accounting at [health.py:285](/Users/ericguei/Documents/caos-databricks/caos/api/health.py:285).

After the inflight ceiling expires, recovery clears the counter although old threads may still run. Their later completion decrements the replacement round's counter. The ceiling is 10 seconds, below supported SDK HTTP/retry durations; the async deadline cannot cancel a running thread. A bounded event-controlled, simulated-clock probe started a second probe while the first remained active; the old completion then allowed a third without another ceiling interval. Three calls ran, with peak overlap two.

**Repair direction:** track actual jobs or generations through completion and distinguish a never-started cancellation from a running probe. The historical permanent stall is repaired; this demonstrates overlapping work, not measured pool exhaustion or an outage.

### MAX-03 — API and health reconnects retain a rejected Lakebase credential

**Base WARNING → CRITICAL; Saboteur + Security Auditor.** [deps.py:78](/Users/ericguei/Documents/caos-databricks/caos/api/deps.py:78), [health.py:113](/Users/ericguei/Documents/caos-databricks/caos/api/health.py:113), [shared connect:202](/Users/ericguei/Documents/caos-databricks/caos/store/__init__.py:202).

Worker and checkpoint connections now invalidate rejected cached credentials, but API and health connections do not. Two real API connections and a health probe against a disposable database rejected an intentionally invalid cached password while retaining it and making zero mint calls. Explicit invalidation then allowed SELECT 1 using one mint. A rejected credential can therefore persist until the local refresh point, up to about 14 minutes, unless another caller refreshes it first. Existing sessions can remain active and need not trigger that recovery. [Lakebase authentication](https://docs.databricks.com/aws/en/oltp/projects/authentication).

**Repair direction:** apply bounded invalidation/remint consistently at the shared connection boundary. This is an availability defect; actual cloud token revocation and an authorization bypass were not demonstrated.

### MAX-04 — Cancellation during a refused call leaves the run nonterminal

**Base WARNING → CRITICAL; Saboteur + New Hire.** [worker.py:258](/Users/ericguei/Documents/caos-databricks/caos/graph/worker.py:258), [work.py:195](/Users/ericguei/Documents/caos-databricks/caos/store/work.py:195).

A Cancel accepted during a provider call remains pending if the answer then fails ordinary validation. The refusal path parks the queue without settling cancellation. A real worker/runtime/database probe produced CITATION_NOT_LOCATED, run RUNNING, queue STOPPED and cancellation requested. Subsequent claim returned nothing, Retry was disabled, and no terminal event existed. The outcome and charge remained durable, with no further model spend. A second Cancel completed cancellation; the UI permits that manual recovery.

**Repair direction:** honor a pending cancellation under the existing fence when settling an ordinary refusal. The successful-final-call cancellation fix does not cover this branch.

### MAX-05 — SDK normalization hides malformed token usage before validation

**Base WARNING → CRITICAL; Saboteur + New Hire.** [models.py:170](/Users/ericguei/Documents/caos-databricks/caos/models.py:170), [charge validation:204](/Users/ericguei/Documents/caos-databricks/caos/models.py:204).

The installed adapter defaults absent/null usage counts to zero, and its message model coerces other types before the application's integer checks. The real ChatDatabricks/OpenAI stack over an in-memory HTTP transport accepted usage={} and null counts as a known zero charge; booleans, numeric strings and integral floats also became accepted counts. Entire usage=null and negative counts correctly refused. Thus malformed upstream accounting can become a trusted charge and continue to artifact validation.

**Repair direction:** validate original usage presence and types before lossy SDK normalization, or preserve sufficient raw metadata. Conservative reservations still hold; no released-budget or overspending bypass was demonstrated. Both model reviews independently reproduced this seam.

### MAX-06 — Ambiguous citation matching retains every matching token slice

**Base WARNING → CRITICAL; Saboteur + Security Auditor.** [citations.py:207](/Users/ericguei/Documents/caos-databricks/caos/evidence/citations.py:207), [candidate collection:426](/Users/ericguei/Documents/caos-databricks/caos/evidence/citations.py:426).

Matching allocates quote-sized token slices and retains every successful match before refusing ambiguity. With only 24 repeated tokens and an eight-token quote, the bounded probe retained 17 slices/136 token references before CITATION_AMBIGUOUS. Current limits allow a 500,000-token page and a 6,000-token quote: source arithmetic implies 2,964,006,000 retained references, about 23.7 GB of pointers alone. That large workload was not executed. The second review checked that page tokenization survives block splitting and that a bounded CP-0 request fits the request limit; anchoring searches the whole page before delivered-block validation.

**Repair direction:** stop at the second match, avoid per-position slice allocation, and bound long near-match searches. This work runs in the application process, outside PDF child limits.

### MAX-07 — The documented standalone preflight command fails on import

**Base WARNING → CRITICAL; Saboteur + New Hire.** [preflight.py:125](/Users/ericguei/Documents/caos-databricks/scripts/preflight.py:125), [deployment instructions:22](/Users/ericguei/Documents/caos-databricks/docs/DEPLOYMENT.md:22).

The documented uv run python scripts/preflight.py command, with a valid --price and without an ambient PYTHONPATH, raises ModuleNotFoundError for caos before performing its checks. The project is not installed as a package and direct script execution does not place the repository root on the import path. Imported tests conceal this entry-point failure. The enterprise wrapper explicitly sets up the root, so its one-command path works.

**Repair direction:** make the documented direct entry point resolve its package consistently, or document an entry point that does. The endpoint/price mismatch check itself is now correct when imports succeed.

### MAX-08 — Deployment E9 accepts two buffered frames from a closed stream

**Base WARNING → CRITICAL; Saboteur + New Hire.** [enterprise_deploy.py:401](/Users/ericguei/Documents/caos-databricks/scripts/enterprise_deploy.py:401), timing setup at [enterprise_deploy.py:374](/Users/ericguei/Documents/caos-databricks/scripts/enterprise_deploy.py:374).

E9 validates frame shape but accepts the second frame without establishing the requested liveness interval. A real loopback HTTP server returned two SSE frames with Content-Length and Connection: close, then closed. E9 exited successfully in approximately 0.002–0.005 seconds despite LIVE_SECONDS=2. Both frames were already buffered. Closed HTML, single-frame EOF and inappropriate case-create responses are now rejected; those fixes do not establish continued streaming.

**Repair direction:** require observed stream liveness over the declared interval before recording verification. This is a false-positive deployment proof; real Databricks proxy buffering was not tested.

### MAX-09 — The deployment path cannot select Lakebase Autoscaling

**Base WARNING → CRITICAL; Saboteur + New Hire.** [databricks.yml:25](/Users/ericguei/Documents/caos-databricks/databricks.yml:25), [database resource:92](/Users/ericguei/Documents/caos-databricks/databricks.yml:92), [enterprise_deploy.py:295](/Users/ericguei/Documents/caos-databricks/scripts/enterprise_deploy.py:295).

The runtime supports an Autoscaling endpoint, but deployment requires a Provisioned instance, binds that resource, and uses its API in preflight/E8. CAOS_LAKEBASE_INSTANCE also takes precedence over the Autoscaling setting. The real installed SDK could fetch and mint for an Autoscaling endpoint against the loopback stand-in; passing the same endpoint through the deployment instance path failed. Existing Provisioned resources remain supported, while creation of new ones is unavailable after March 12, 2026. [Official Lakebase Apps resource documentation](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/lakebase).

**Repair direction:** carry the selected resource type consistently through bundle, credentials, preflight and verification. Preserve existing Provisioned bindings and role identity. No live deployment was attempted.

### MAX-10 — A final matrix refusal loses the performed qualification snapshot

**Base WARNING → CRITICAL; Saboteur + New Hire.** [harness.py:373](/Users/ericguei/Documents/caos-databricks/caos/qualification/harness.py:373), [matrix.py:475](/Users/ericguei/Documents/caos-databricks/caos/qualification/matrix.py:475).

Matrix construction runs before the harness persists its performed result. If the local methodology manifest changes after execution but before the final authority check, the refusal escapes that persistence boundary. In a scratch vendor copy, appending one space after the final record yielded AUTHORITY_BYTES_MISMATCH after three real harness calls with scripted responses: the run was COMPLETE, three call outcomes remained, and zero performed snapshots were added.

**Repair direction:** preserve a non-signable performed result when post-execution matrix construction refuses, while keeping the authority check. This requires privileged/concurrent local file mutation. The paid-call ledger and blobs survive; no false qualification or remote mutation capability was shown.

### MAX-11 — Multi-case qualification capture exports only the first run's attempts

**Base WARNING → CRITICAL; Saboteur + New Hire.** [qualify.py:129](/Users/ericguei/Documents/caos-databricks/scripts/qualify.py:129), [first-run argument:400](/Users/ericguei/Documents/caos-databricks/scripts/qualify.py:400).

The CLI now admits multi-case sets, but its attempt query still receives only prepared[0].input.run_id. A two-case LITE run completed six scripted calls. The durable ledger contained six attempts and total charge 0.0000246; the capture reported complete=true and two results, but only three attempts and charge 0.0000123. All second-run attempt identities and diagnostics were omitted. The database's performed snapshot correctly contained both cases.

**Repair direction:** collect attempts for every prepared/performed run and preserve case/run association, including cases without a proof. This is incomplete exported evidence, not lost ledger entries or a budget bypass.

### MAX-12 — The Markdown release pack omits qualification identity

**Base WARNING → CRITICAL; New Hire + Security Auditor.** [release_pack.py:466](/Users/ericguei/Documents/caos-databricks/scripts/release_pack.py:466); compare the repaired [JSON projection:333](/Users/ericguei/Documents/caos-databricks/scripts/release_pack.py:333).

The Markdown renderer shows QUALIFIED with a shortened evidence digest and expiry, but omits provider, model, reviewer and set. A real signed fixture preserved all four fields in JSON and none in Markdown. A reader sharing only the human artifact cannot tell which execution identity its qualification covers, particularly when it came from a test/OpenRouter provider. The underlying verdict binding and optional identity filter remain correct.

**Repair direction:** display the qualification's execution identity and relevant signer/set bindings beside its status, or explicitly scope the entire artifact. The previous blanket claim about both JSON and Markdown is withdrawn.

### MAX-13 — The gate-integrity checker accepts effective gate weakening

**Base WARNING → CRITICAL; Saboteur + Security Auditor.** [check_gate_config.py:126](/Users/ericguei/Documents/caos-databricks/scripts/check_gate_config.py:126).

The checker inspects positive rule selections and option substrings without resolving overriding configuration. Three isolated mutations each returned no problems: ignoring F821 made installed Ruff stop reporting an undefined name; appending --cov-fail-under=0 made installed pytest's effective coverage threshold zero; restricting coverage source to caos.boundary_text narrowed the measured package. These were scratch configurations. The current repository was not changed to disable its gates, and the current gate checks pass.

**Repair direction:** validate effective rules, conflicting options, exclusions and the intended coverage source. The coordinator reproduced the tool behavior and the deliverable security perspective corroborated the guard failure. Generic scanner scores were not used as evidence.

## Warnings

### MAX-14 — EventSource reconnection leaves a disconnected view marked live

**WARNING; Saboteur.** [sse.ts:75](/Users/ericguei/Documents/caos-databricks/frontend/src/app/sse.ts:75), [Workspace.tsx:195](/Users/ericguei/Documents/caos-databricks/frontend/src/app/Workspace.tsx:195).

The error handler returns while EventSource is CONNECTING, before marking the view not live. A transport stand-in transitioned OPEN → CONNECTING and emitted an error; live changes remained [true]. During native reconnect attempts, stale content therefore retains its live indication. A later successful open resynchronizes it, and CLOSED handling already retries correctly.

**Repair direction:** mark loss of the open connection immediately while allowing the existing reconnection/resync path to restore freshness. This is separate from selecting the wrong stream in MAX-19.

### MAX-15 — Autoscaling credential expiry uses the wrong SDK field

**WARNING; Saboteur.** [lakebase.py:188](/Users/ericguei/Documents/caos-databricks/caos/store/lakebase.py:188), fallback at [lakebase.py:202](/Users/ericguei/Documents/caos-databricks/caos/store/lakebase.py:202).

The Autoscaling API returns expire_time as a Timestamp, but the common path reads the Provisioned field expiration_time. A real installed SDK object with one hour remaining therefore retained only the synthetic 840-second deadline; its Provisioned equivalent retained 3,540 seconds. With refresh failing at simulated second 841, the real credential cache refused although the server token was still valid. Successful routine refreshes hide this availability gap. [Documented SDK credential fields](https://databricks-sdk-py.readthedocs.io/en/stable/dbdataclasses/postgres.html#databricks.sdk.service.postgres.DatabaseCredential).

**Repair direction:** normalize the two response shapes and Timestamp representation before entering the common cache. No live endpoint or expired-token acceptance was tested.

### MAX-16 — NaN Retry-After escapes the typed provider interface

**WARNING; Saboteur.** [models.py:233](/Users/ericguei/Documents/caos-databricks/caos/models.py:233), [retry handler:156](/Users/ericguei/Documents/caos-databricks/caos/models.py:156).

A gateway 429 with Retry-After: NaN survives float parsing and clamping. Sleeping raises ValueError inside the exception handler, outside its sibling catch clauses. The real SDK over an in-memory transport raised after exactly one call. The traced worker path then parks the run as INTERNAL_FAULT before a typed outcome is recorded. Ordinary numeric, invalid-text and infinite headers were counterchecked and remained bounded.

**Repair direction:** require a finite interval and use the existing invalid-header fallback. This requires a malformed upstream header; a case uploader cannot directly supply it. Other runs remain serviceable.

### MAX-17 — Truncated HTTP bodies escape deployment evidence recording

**WARNING; Saboteur.** [enterprise_deploy.py:249](/Users/ericguei/Documents/caos-databricks/scripts/enterprise_deploy.py:249), [E9 reads:343](/Users/ericguei/Documents/caos-databricks/scripts/enterprise_deploy.py:343).

The response-body catches omit http.client.IncompleteRead. A loopback response declaring 100 bytes and sending 10 raised it from the E6 health read and produced no evidence row. The same uncovered body-read boundary exists in E9. The command fails closed, so this is missing diagnostics/retry handling rather than false readiness.

**Repair direction:** map incomplete HTTP responses into the normal failed-attempt evidence and bounded polling behavior.

### MAX-18 — Reopening an approved run leaves Start and Retry unusable

**WARNING; skills review priority P1.** [controls.tsx:539](/Users/ericguei/Documents/caos-databricks/frontend/src/sections/run/controls.tsx:539), [RunSection.tsx:45](/Users/ericguei/Documents/caos-databricks/frontend/src/sections/run/RunSection.tsx:45).

The component's fingerprint starts null, ordinary Run reads omit it, and a successful gate preview deliberately does not retain it. If input is already pinned and both gates are RELEASED, the user cannot Pin again or use an Approve button to recover it. Mounted production components reproduced both Start and Retry remaining disabled with COMMAND_EXPECTATION_STALE after two valid previews returned the fingerprint; zero command POSTs occurred. Same-session pin/approval still works.

**Repair direction:** make the server-verified fingerprint recoverable after reload without discarding the reviewed preview. Preserve server checks and binding. This blocks normal authorized UI use; it is not a server authorization failure.

### MAX-19 — Case-only navigation displays a run but subscribes only to case audit events

**WARNING; skills review priority P2.** [Workspace.tsx:180](/Users/ericguei/Documents/caos-databricks/frontend/src/app/Workspace.tsx:180), [stream.py:278](/Users/ericguei/Documents/caos-databricks/caos/api/stream.py:278).

Directory navigation omits the run query. Reads resolve the latest run, but Workspace opens its stream with the raw null selection. That server stream intentionally excludes run events. Mounted Run/Analysis views retained this URL after showing a run; a real database comparison yielded no run_progress event for the case-only tail and one for the named-run tail. A frontend test currently injects an event that this real URL cannot deliver.

**Repair direction:** scope events to the displayed run while retaining case events and the explicit-reload identity policy. Under healthy networking, the server's 300-second stream expiry/reopen limits the stale interval to about five minutes plus reconnect delay; manual refresh or relevant audit events can shorten it.

### MAX-20 — A transient startup failure permanently disables the in-process worker

**WARNING; skills review priority P2.** [worker.py:490](/Users/ericguei/Documents/caos-databricks/caos/graph/worker.py:490), [serve.py:65](/Users/ericguei/Documents/caos-databricks/caos/serve.py:65).

start_in_process is called once and returns None on transient configuration/database failures. The API then starts separately, with no worker-start retry. A probe followed the real serve ordering, injected one failed initial worker connection, then used real successful database connections and the API lifespan. Health returned ready/store OK/workers ABSENT while work stayed QUEUED. A subsequent manual worker configuration succeeded, establishing a temporary dependency failure. Reconnect logic inside an already-running worker cannot help when no thread was created.

**Repair direction:** retry transient startup failures with bounded shutdown handling, or fail required-worker startup so the platform restarts it. API readiness remaining separate from worker health is an accepted design and is not itself the finding.

### MAX-21 — The provider retry sequence can outlast the lease and duplicate billing

**WARNING; skills review priority P2.** [models.py:148](/Users/ericguei/Documents/caos-databricks/caos/models.py:148), [600-second lease:27](/Users/ericguei/Documents/caos-databricks/caos/store/work.py:27), [240-second call timeout:30](/Users/ericguei/Documents/caos-databricks/caos/provider.py:30).

Three calls and two waits of up to 20 seconds can exceed the 600-second lease without renewal. A logical-time probe used two 230-second 429 responses plus waits, followed by a third call ending at second 730. A replacement worker claimed at simulated second 601 through real database/runtime code. Both CP-0 attempts were billed; only the replacement's artifact was accepted. Each call fit its individual timeout. No long wall-clock wait or paid invocation occurred.

**Repair direction:** bound the whole retry operation against the lease with settlement margin, or renew/revalidate ownership throughout it. This needs late 429s and overlapping workers. Exactly-once acceptance and conservative reservation accounting held; no budget bypass was shown.

### MAX-22 — Deployment prerequisites omit the store schema's CREATE privilege

**WARNING; conditional skills review priority P2.** [DEPLOYMENT.md:12](/Users/ericguei/Documents/caos-databricks/docs/DEPLOYMENT.md:12), [store bookkeeping:173](/Users/ericguei/Documents/caos-databricks/caos/store/__init__.py:173), [platform fixture:79](/Users/ericguei/Documents/caos-databricks/tests/platform_app.py:79).

Database CONNECT/CREATE does not grant CREATE within an existing public schema. If the app role has only the documented database grants and no writable default schema, startup's unqualified store table creation fails. A restricted temporary PostgreSQL 17 role reproduced SQLSTATE 42501; adding CREATE on public allowed all 27 migrations. The ordinary boot fixture uses an administrator and misses this condition. Current Apps docs describe database grants; the Autoscaling tutorial separately grants schema privileges. [Apps resource grants](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/lakebase), [custom-app schema setup](https://docs.databricks.com/aws/en/oltp/projects/tutorial-databricks-apps-autoscaling).

**Repair direction:** arrange/document the writable store schema and check startup with the declared app-role privileges. Live Lakebase ACL defaults were not inspected; already-writable deployments are unaffected.

## Notes

### MAX-N01 — The UUID-parser guard scans a nonexistent directory

**NOTE; New Hire.** [test_api_routes.py:1306](/Users/ericguei/Documents/caos-databricks/tests/test_api_routes.py:1306) searches server/api rather than caos/api. The scan visits zero files and passes vacuously. Point it at the current package and assert a nonempty scan. No current UUID authorization/parser bypass was established.

### MAX-N02 — The manual bundle-run example omits required variable values

**NOTE; New Hire.** [DEPLOYMENT.md:55](/Users/ericguei/Documents/caos-databricks/docs/DEPLOYMENT.md:55). Values supplied with --var during deployment are not persisted as defaults for the subsequent CLI invocation. The documented standalone bundle run lacks required values unless the operator separately supplies them through the environment or an override file. The enterprise wrapper works. State the manual command's variable prerequisites.

### MAX-N03 — Provider charge precision differs from validated price precision

**NOTE; skills model review.** [models.py:71](/Users/ericguei/Documents/caos-databricks/caos/models.py:71), [pricing.py:75](/Users/ericguei/Documents/caos-databricks/caos/pricing.py:75).

Price validation permits precision up to 1,000 digits with inexact arithmetic trapped, while charge multiplication uses precision 60 without that trap. An accepted one-token input price of 1 + 10^-70 produced charge 1, losing 10^-70 units. This is a contrived 71-significant-digit input, not material rounding for ordinary configured prices or a demonstrated budget bypass. Align the supported precision contract or reject excess precision.

## Skills and verification

The adversarial pass used [Adversarial Reviewer](/Users/ericguei/.codex/skills/adversarial-reviewer/SKILL.md). The second pass applied [Codebase Design](/Users/ericguei/.codex/skills/codebase-design/SKILL.md), [Code Reviewer](/Users/ericguei/.codex/skills/code-reviewer/SKILL.md) and its applicable Python/TypeScript guidance, with [Senior Fullstack](/Users/ericguei/.codex/skills/senior-fullstack/SKILL.md), [Senior Backend](/Users/ericguei/.codex/skills/senior-backend/SKILL.md), [Senior ML Engineer](/Users/ericguei/.codex/skills/senior-ml-engineer/SKILL.md), [Senior DevOps](/Users/ericguei/.codex/skills/senior-devops/SKILL.md), and [Dimensional Analysis](/Users/ericguei/.codex/skills/dimensional-analysis/SKILL.md) where relevant.

Databricks review used the repository's [Core](/Users/ericguei/Documents/caos-databricks/.claude/skills/databricks-core/SKILL.md), [Apps Python](/Users/ericguei/Documents/caos-databricks/.claude/skills/databricks-apps-python/SKILL.md), [Lakebase](/Users/ericguei/Documents/caos-databricks/.claude/skills/databricks-lakebase/SKILL.md), [Python SDK](/Users/ericguei/Documents/caos-databricks/.claude/skills/databricks-python-sdk/SKILL.md), [Model Serving](/Users/ericguei/Documents/caos-databricks/.claude/skills/databricks-model-serving/SKILL.md) and [DABs](/Users/ericguei/Documents/caos-databricks/.claude/skills/databricks-dabs/SKILL.md) skills and relevant references. Current official documentation and installed SDK shapes took precedence over stale examples. Python 3.13 with uv.lock, bundle app config.env, and support for existing Provisioned resources were counterchecked and excluded as findings. [Apps dependencies](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/dependencies), [bundle resources](https://docs.databricks.com/aws/en/dev-tools/bundles/resources).

| Scoped assignment | Verification result |
| --- | --- |
| [Adversarial API/identity](/private/var/folders/81/bwblpst93lb6wb3lwrk8k6800000gn/T/caos-api-audit-max-kb3pcmcu/first-pass-api-report.md) | 54 existing cases completed successfully; 2 Python and 2 mounted frontend counterexamples passed. |
| [Adversarial store/graph](/tmp/caos-store-audit-03tuWT/report.md) | 52 passed, 1 live-provider case deselected; bounded credential, cancellation and SDK-expiry probes. |
| [Adversarial model/methodology/evidence](/tmp/caos-audit-model-3plulse7/report.md) | 72 passed; 1 explicitly excluded direct SDK-construction test after a stalled discovery attempt; bounded transport/citation probes. |
| [Adversarial deployment/stand-ins](/var/folders/81/bwblpst93lb6wb3lwrk8k6800000gn/T/caos-deploy-astra-audit-bp_z3qfc/report.md) | 18 passed; real CLI 1.17.0 validate/deploy/run succeeded for both dev and prod against loopback. Each uploaded 572 files including 28 frontend distribution files; both shipping checks passed. |
| [Adversarial deliverables/qualification/calculators/gates](/var/folders/81/bwblpst93lb6wb3lwrk8k6800000gn/T/caos-max-adversarial-deliverable-xl05s9gz/REPORT.md) | 243 pure/package/loader checks and 25 selected database cases passed; nine scripted harness calls in disposable-database counterexamples. |
| [Skills API/identity/fullstack](/tmp/caos-api-skills-audit-VQqIe1/report.md) | 154 existing checks passed; 4 mounted workflow and 1 database stream counterexamples passed. |
| [Skills store/graph](/tmp/caos-max-skills-store/report.md) | 49 passed, 1 deselected; real startup/retry-lease probes with simulated transport/time. |
| [Skills model/methodology/evidence](/tmp/caos-max-skills-model/report.md) | 116 passed, 5 database-dependent skips, 1 explicit direct SDK-construction exclusion; independently corroborated all three model findings. |
| [Skills deployment/stand-ins](/var/folders/81/bwblpst93lb6wb3lwrk8k6800000gn/T/caos-skills-deploy-audit-dsa0g1_u/report.md) | 21 passed; restricted-role schema probe failed then succeeded as described in MAX-22; temporary role/database cleanup verified. |
| [Skills deliverables/qualification/calculators/gates](/tmp/caos-max-skills-deliverable/report.md) | 349 passed, zero failures/skips/deselections; four calculator scale transformations with 276 monetary comparisons passed, ratios unchanged and Decimal context isolated. No new finding beyond corroborating MAX-10/11/12. |
| Coordinator | Ruff lint passed; formatting check passed for 341 files; mypy passed for 340 source files. Five read-only gate scripts passed. Focused gate tests: 75 passed, 39 database-dependent skips. |

Key installed versions used for the reproductions: Databricks SDK 0.140.0, databricks-langchain 0.20.0, OpenAI client 3.18.0, langchain-core 1.6.4, Databricks CLI 1.17.0 and PostgreSQL 17.11.

Counts overlap across assignments and must not be added as unique coverage. Counterexample checks pass when they reproduce a defect. The five coordinator scripts were check_gate_config, check_tested, io_budget --assert, check_vocabulary and check_icm. Python checks used no coverage output, no pytest cache and no bytecode writes; database tests used disposable UUID databases on the existing local test server. CLI state and all probe files stayed outside the repository.

This was not a full CI or coverage run, a live workspace deployment, paid provider qualification, live grant/token-revocation test, or memory-exhaustion test. The direct SDK-construction discovery stall was not reported as a product failure or a passing check. Actual Apps proxy behavior, enterprise ACLs and live model quality remain unverified. Heuristic scanner alerts were investigated as leads; fixture credentials, parameterized SQL matches, scores and estimated coverage were not promoted to findings.

The tree changed in another session during review. The second model pass checked the current 52 KiB invocation contract and credited its fail-closed tradeoff. Finding-bearing source was hash-checked by each scope. The coordinator rechecked all 33 linked repository files against the initial snapshot on 2026-09-23 at 11:38 UTC: none changed. The current invocation implementation and its tests also match the second model reviewer's recorded hashes. Concurrent OpenRouter qualification work was not treated as a completed live qualification or fully certified here.

## Reconciliation with this reviewer's previous list

Only the reported scenarios and inspected callers are classified below; a repaired historical scenario does not certify all neighboring behavior.

| Previous identifiers | Current disposition |
| --- | --- |
| AR-01, AR-03 | Broken-connection rollback/recovery and retry exponent overflow are repaired in current worker paths and regressions. MAX-20 concerns the separate pre-thread startup phase. |
| AR-02 | Worker/checkpoint invalidation repaired; API/health omission remains as MAX-03. |
| AR-04, AR-12 | Negative identity cache bounds and malformed SCIM group parsing repaired and tested. |
| AR-05 | HTML/single-frame false success repaired; two already-buffered closed frames still pass as MAX-08. |
| AR-06, AR-17 | Endpoint/price consistency and JSON smoke parsing repaired. MAX-07 concerns the standalone import path. |
| AR-07 | Effective gate override gap revalidated as MAX-13. |
| AR-08 | Renderer-numbering change explicitly declined in current decisions/parity contract; no production renderer caller found. Excluded from current open findings. |
| AR-09, AR-23, AR-25 | Loader materialization/type bounds and contradictory scalar-key preflight checks repaired in reviewed paths. |
| AR-10 | Current code recovers the winning receipt after a duplicate-verdict rollback. The historical two-connection race was not independently repeated by the coordinator. |
| AR-11 | Never-started probe permanent stall repaired; MAX-02 covers the replacement generation's accounting. |
| AR-13 | Successful final-call cancellation repaired; ordinary validation refusal remains MAX-04. |
| AR-14 | Negative usage rejected; raw usage normalized before validation remains MAX-05. |
| AR-15, AR-16 | Unsupported reasoning setting rejected; non-finite PDF deadline normalized. |
| AR-18 | Multi-case ceilings/admission repaired; resulting capture still omits later attempts, MAX-11. |
| AR-19 | Offline/unreadable-response key retention repaired; typed ambiguous-commit refusal remains MAX-01. |
| AR-20 | Checkpoint setup serialization repaired; concurrent setup checks passed. |
| AR-21 | Autoscaling deployment gap remains MAX-09. |
| AR-22 | JSON identity repaired; Markdown residual remains MAX-12. |
| AR-24 | Original single-call freshness threshold repaired; aggregate retry duration is part of MAX-21 rather than a duplicate finding. |
| R2-E1 | Qualification/package shipping omission repaired; both real-CLI loopback uploaded trees passed current shipping checks. |
| R2-N1 | Vacuous UUID test remains MAX-N01. |
| R2-N2 | Register comparison fields now included through dataclass projection; distinct multi-run capture issue is MAX-11. |

The first deliverable pass also counterchecked the repaired refusal scoring, release coverage, signed evidence re-derivation, filing proof, frozen receipt, subject binding and portable figure-verification paths. Latest-signer receipt semantics and legacy negative-CFO refusal are documented accepted choices and were not reopened. The final calculator review found no additional confirmed arithmetic or unit-scaling defect: annual/quarterly money values scaled consistently between millions, thousands and units, ratios stayed unchanged, and caller Decimal settings did not change canonical output. Dimensional Analysis was applied as a bounded manual audit with external probes; its repository-annotation pipeline was not run.

The most direct normal-use blocker is reopening an already approved run (MAX-18). Worker startup recovery, aggregate retry/lease timing, citation-search bounds and the qualification/deployment evidence gaps warrant repair or explicit acceptance before release. This report records findings and repair directions; it applies no fixes.


---

## Preserved independent historical review

The following FP section was written by another session against an older tree. It is retained verbatim to preserve that independent work, including its historical counts and conclusions. It is not the current findings list or an assertion that all FP items remain open. The MAX list and reconciliation above state this rerun's verified results.

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
