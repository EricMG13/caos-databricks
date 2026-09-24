# Virgin Media O2 FY2025 live qualification result

## Current tree status

The current set digest is
`ff9dc7ecc2229ae0d7a114bb8f50e8c30ac9fdd05d62191447c63c8a4dee6b41`.
It adds the CP-L10 `TL10.2` liquidity/maturities register key and has **not**
been run. Its status is **OFFLINE / UNVERIFIED / NOT QUALIFIED**. Every run and
snapshot below is retained historical evidence bound to an earlier set digest;
none is a performed result or verdict for the current set.

## Corpus and key

This case uses two existing public issuer documents:

- `Virgin-Media-O2-Q3-2025-Earnings-Release.pdf`, SHA-256
  `505bf1a0f4181c9cdffeeac7e6af3253d1883788e9cd1a81e65952e008aa17a1`
- `Virgin-Media-O2-Q4-2025-Earnings-Release.pdf`, SHA-256
  `66055bbb8d27721d07a5e8cb834c9b96a256ada45a0812ea4fb2e7202ee4f64d`

The initial answer key was fixed from those issuer documents before the provider run.
It tests a current borrowing-capacity statement under CP-0, the £1,021.7
million Q4 goodwill impairment under CP-L10, and the issuer's non-GAAP
liquidity limitation under CP-5. The qualification-set digest is
`ec84bf8bbb1b45fd715d52466b9142778b4346ab13b252951db0b589209d07d1`
for that initial historical set.

A first prepared pack also included the Q3 2025 quarterly bond report. Its
CP-0 request exceeded the host's 1 MiB request ceiling and refused as
`CONTEXT_OVER_CEILING` before an attempt, reservation, provider call or charge.
The detailed bond report was removed rather than weakening the resource gate;
the final two-document CP-0 request was 448,826 bytes.

## Run

- Route: `LITE_CREDIT_22 / LITE_EARNINGS_UPDATE` (`CP-0`, `CP-L10`, `CP-5`)
- Provider/model: `openrouter/ionstream/default / deepseek/deepseek-v4-pro-0813`
- Price configuration: `$0.96` input and `$2.88` output per million tokens,
  dated 2026-09-15
- Run ceiling: `$22.00`
- Local development run: `2abc6c57-bb8f-4840-970e-91830191d494`
- Source-set approval preview:
  `0bc48fd15025fe6a3a3ce51c389211c767d46cd7a7f2148c8aa5457489c196e4`
- Research-plan approval preview:
  `01760913dd364272c2ec0354e28a893793a955bd40fb3a3c6648e0a2baf00fa0`

## Result

The model is **not qualified**. CP-0 made three billed attempts and no
canonical handoff was accepted:

| Attempt | Charge | Host result | Deterministic diagnosis |
|---|---:|---|---|
| `92d8e655-cec3-46b8-ac88-9068fff2d9e2` | `$0.170135040` | `HANDOFF_MALFORMED` | Returned 94 citations; none of their exact quotes appeared in the Markdown body. |
| `28ef1818-9de3-47e7-85c1-a5756e50b675` | `$0.163118848` | `CITATION_NOT_DELIVERED` | Returned 61 citations, changed one pinned source UUID's final digit, and quoted none in the body. |
| `de292860-6163-4310-a523-9319eb60d36c` | `$0.154520128` | `HANDOFF_MALFORMED` | Used valid source IDs but quoted none of 14 citations and emitted `## Analysis` twice. |

Stored provider reconciliation identities:

- Attempt 1: generation `gen-1789467788-3tCVdQqEtUfF8VCYyhYf`, response digest
  `7e0fade839db3719855f64433f9caa9171b9e948c800abed35ce766a247900f9`
- Attempt 2: generation `gen-1789468111-xAuTdtAonxIKAKRnCubv`, response digest
  `873afcbac528a8379a6f6213896d493d0c33a234f9321338f5b951d75682dc71`
- Attempt 3: generation `gen-1789468381-JhS0gxgw8RWuDXWEI7A9`, response digest
  `503c8882bf480036399a338aeaa1895a66bac41f2fff373696d67e78af7f2119`

Total recorded charge was `$0.487774016`. CP-L10 and CP-5 were not called.
No artifact, orchestration proof, qualification matrix, evidence row or verdict
was produced. The exhausted run was closed as `FAILED` after the third attempt
so it cannot be resumed accidentally. It must not be represented as
`QUALIFIED`.

The adapter prompt was revised between these failed attempts to isolate the
observed copying defects. This cross-revision sequence is diagnostic only and
cannot support a positive qualification decision. Any future qualification
must start a fresh prepared run against one frozen adapter revision.

## Compatibility conclusion

OpenRouter returned well-formed closed JSON bodies, generation identifiers and
charges on all three attempts. The remaining incompatibility is therefore not
the provider transport. OpenRouter reconciliation subsequently established that
all three attempts were served by Ionstream with zero reasoning tokens. The
result therefore rejects only the `openrouter/ionstream/default` deployment
profile; it is not evidence that first-party or reasoning-enabled DeepSeek is
incapable of the contract.

Strict host validation remains unchanged. The shared prompt now distinguishes
eligible from required citations, forbids enumerating unquoted candidates,
names their required Markdown location, and repeats the exact delivered source
IDs at the generation point. Those clarifications improve the contract but do
not qualify this model. Use a separately qualified model for this route.

## Controlled profile follow-up — 2026-09-15

The runtime now sends an optional lowercase OpenRouter endpoint tag and
reasoning effort, and binds both into qualification identity. A fresh adapter
revision, `canonical-markdown-v2`, prevents the revised prompt from borrowing a
v1 verdict.

OpenRouter's public endpoint catalog reported the first-party endpoint live
under tag `deepseek`, with reasoning, reasoning-effort and JSON response-format
support. Nevertheless, harmless probes and a fresh prepared qualification run
all returned `404 No endpoints found for deepseek/deepseek-v4-pro-0813` before
generation. They produced no generation ID and no charge. Since the same model
remains available through Ionstream, this is an account/workspace routing or
data-policy restriction, not a demonstrated model or parameter failure.

An `openrouter/ionstream/xhigh` JSON probe succeeded as generation
`gen-1789472086-Xy5p8onbmebuRtteQRNK`: 15 prompt, 21 completion and 15 native
reasoning tokens, `finish_reason=stop`, charge `$0.00007488`. This proves that
the available deployment honors the requested reasoning profile.

The subsequently authorized full-corpus run
`62307d9b-f2d4-49f3-b015-82fea3b07298` bound
`openrouter/ionstream/xhigh`, adapter `canonical-markdown-v2`, and the unchanged
qualification-set digest. CP-0 generation
`gen-1789475926-OwNgVKf0G7QapLweplaL` used 153,892 prompt, 10,285 completion
and 6,286 native reasoning tokens, finished normally with `stop`, and charged
`$0.177133888`. The host rejected it as `CITATION_NOT_DELIVERED`; CP-L10 and
CP-5 were not called, and no artifact, proof, matrix, evidence row or verdict
was produced.

This rules out fallback routing, disabled reasoning and truncation as causes of
the observed contract failure. DeepSeek V4 Pro remains a capable general agent,
but this deployment is not compatible with the current one-shot canonical
handoff contract. Repeating the same frozen temperature-zero call would not add
a new controlled variable and was not purchased.

## Gemini 3.8 Flash follow-up — 2026-09-15

The replacement candidate used model `google/gemini-3.8-flash`, pinned
OpenRouter endpoint `google-ai-studio`, reasoning effort `high`, the same public
corpus and qualification-set digest, adapter `canonical-markdown-v2`, and the
same `$22.00` run ceiling. Current dated pricing was `$0.75` input and `$3.75`
output per million tokens. Google documents 1,048,576 input and 65,536 output
tokens for this model, but the unchanged CAOS provider ceiling remained 32,768
completion tokens.

Fresh run `7c9c8d60-7b42-4f38-9b42-bb4e1d1afb47` stopped at CP-0 as
`PROVIDER_OUTPUT_TRUNCATED`. Generation
`gen-1789477949-PdZ0oPgEZZGQjoUQbTE1` reconciled to Google AI Studio, 174,278
native prompt tokens, 32,761 native completion tokens, 29,454 native reasoning
tokens, `finish_reason=length`, and `$0.25356225` total cost. CP-L10 and CP-5
were not called, and no artifact, proof, matrix, evidence row or verdict was
produced.

This profile is not qualified at the shipped 32,768-token ceiling. A same-cap
retry changes no controlled variable and must not be purchased. A 65,536-token
experiment would be materially different, but requires an intentional runtime
change, fresh build identity and fresh authorization before spend.

## 65,536-token attempt — result collection indeterminate

After the authorized ceiling/profile change at `691637b`, the prepared attempt
used `openrouter/google-ai-studio/high/65536` with the same frozen corpus and
`$22.00` set/run ceilings. `perform()` returned to its temporary qualification
collector, but the collector then raised while JSON-encoding the proof's
`frozenset` of anchored citations. Its `finally` block dropped the disposable
database before it printed the run ID, generation IDs, charges, node status or
matrix.

The OpenRouter activity endpoint is aggregate-only and requires a management
key for this account; reconciliation therefore returned `403`. The number of
provider calls, their individual charges and the canonical outcome are
unrecoverable from the surviving record. No artifact, evidence row or verdict
may be claimed from this attempt. Future `perform()` calls persist the complete
or partial immutable snapshot and its bound evidence row before returning; the
collector serializes its digest and retains the disposable database/blob root
for external review. This is not permission to repeat the indeterminate paid
attempt.

## Recovered 65,536-token retry — Gemini protocol incompatibility confirmed

The recovery candidate at `40a13dd` persisted the complete immutable performed
snapshot and its bound evidence row before its collector returned. The fresh
run `1590edfc-a747-4c69-ae1a-06455edeb1a7` used the same frozen
qualification-set digest and profile
`openrouter/google-ai-studio/high/65536`. CP-0 generation
`gen-1789486082-I1BG57GiSspM6MntssMu` was served by Google AI Studio, finished
normally with `stop`, used 177,062 native prompt, 36,606 native completion and
28,952 native reasoning tokens, and cost `$0.270069`.

The retained diagnostic was a valid closed JSON transport with canonical
Markdown and four citations. Each citation named delivered evidence and
uniquely anchored in that evidence. The vendor Markdown validator also passed.
The host nevertheless correctly refused CP-0 as `HANDOFF_MALFORMED`: none of
the four evidence quotations occurred character-for-character in the Markdown
body. Safe replay found case-insensitive matches for three and punctuation-
normalized matches for all four, including an Evidence Trace section. Gemini
therefore rewrote the quotations while retaining their meaning, instead of
copying them verbatim as the pinned canonical protocol requires.

No artifact, orchestration proof, matrix, evidence row for a verdict, or
qualification verdict exists. The performed snapshot digest is
`713ba25de76d8edf3dcde577c1ac9cc0d3000fc0079ea009d8d98f04ba26933f` and its
bound evidence digest is
`0e5e64d3948bbc149ac313185d1d47343987d10d87e41f11a9c0b33eaedd192c`.
The retention failure is fixed; Gemini 3.8 Flash is not qualified for this
one-shot canonical handoff contract. Do not buy another Gemini retry without a
materially different, explicitly authorized protocol experiment.

## OpenAI Terra provenance diagnosis — 2026-09-15

The separately authorized Terra run used `openai/gpt-5.6-terra` through pinned
`openrouter/openai/flex/high/65536`, with the same two-document VMO2 set and a
`$22.00` maximum. CP-0 made one billed call: run
`650a2618-0fbd-48d3-ad12-27bbbd7edc10`, attempt
`9307791d-bdb5-456b-a8ea-36b82e8bbc99`, generation
`gen-1789491046-8S6zV4AASHeN1hdJmopq`, charge `$0.23236475`.

The response returned a controlled source-readiness block. Its diagnostic and
performed evidence are retained locally (diagnostic digest
`2c52bf3ac3ea29d1d1b2304087579a643b50fef374a12393c27c40cbdc07c1dd`,
performed digest
`17cd20b9a79fe742e37233ac1874e2fd342afec3ccc7447a8e7a067edb72b0cd`).
It correctly observed that CP-0 had received evidence excerpts but not the
host's immutable-original, source-root, extraction-manifest or managed-run
facts needed to author P1–P8. It also identified the genuine limitation that
the two earnings releases alone omit primary financial/legal material.

This is not a Terra or OpenRouter protocol failure. The v2 prompt omitted
metadata that the host already retained. `canonical-markdown-v3` now supplies
the verified CP-0 source-preparation context and rechecks original blobs at
acceptance/replay; it is a materially changed candidate. The v2 run produced no
accepted artifact or qualification verdict and cannot be reused. A fresh,
explicitly authorized live run is required after v3's local gates and, if the
source set changes, after a new frozen qualification key is prepared.

## OpenAI Terra v3 qualification run — 2026-09-16

The first run of this set to finish its route. `canonical-markdown-v3` through
the same pinned profile, the same frozen two-document corpus and the same
answer key; the model is **still not qualified**, but for a different and much
narrower reason than either run before it.

- Adapter: `canonical-markdown-v3`
- Provider/model: `openrouter/openai/flex/high/65536` / `openai/gpt-5.6-terra`
- Price configuration: `$0.000002` input and `$0.000012` output per token
  ($2.00 / $12.00 per million), dated 2026-09-16, read from OpenRouter's
  published model list on the day of the run
- Run ceiling: `$22.00`; reservation per call `$2.883584`
- Local development run: `e0e101b5-a908-4b9b-913d-45184a6f3a54`
- Qualification-set digest (unchanged):
  `ec84bf8bbb1b45fd715d52466b9142778b4346ab13b252951db0b589209d07d1`
- Evidence digest: `0a1b6faa43f5361b66f9acd391793a9ceeb56d54e8b05e676e8a41651d735476`
- Performed digest: `fd20bb5f19dbd16fd3fe6f3e78229a4c9057c33bb6c42ff6191ee0245084b170`
- Retained database `caos_test_d5b8c78452644d28be02943a6c3750c5`, blob root
  `/var/folders/81/bwblpst93lb6wb3lwrk8k6800000gn/T/caos-vmo2-v3-yn_c83lm`

### Run

The route ran to `COMPLETE`. Every module answered on its **first** attempt —
no retry, no refusal row, no replay:

| Module | Charge | Generation | Result |
|---|---:|---|---|
| CP-0 | `$0.2534435` | `gen-1789546489-g3Hv4o2ZMMQ5ASVL5nxI` | accepted |
| CP-L10 | `$0.28338425` | `gen-1789546572-n2msOOtl3OBd1ozbsiZx` | accepted |
| CP-5 | `$0.2856555` | `gen-1789546646-XaxBVRgUVG4KHpSobgxk` | accepted |

Total recorded charge `$0.82248325` against the `$22.00` ceiling. Three
artifacts, fourteen citations, and the host re-located **all fourteen** in its
own token index. The orchestration proof re-derived every record and every
citation. `attempt_refusals` is empty.

That settles what the two earlier runs could not. DeepSeek V4 Pro failed the
literal-quotation contract three times and Terra under v2 returned a controlled
readiness block; under v3 the same provider, corpus and key produce a completed
route whose every quote anchors. The missing CP-0 provenance context was the
cause, and supplying it was the fix.

### Verdict

**Not qualified.** The matrix row reads `proven=true, met=2, missed=1`:

- **CP-L10 — met.** The £1,021.7 million Q4 goodwill impairment, quoted exactly.
- **CP-5 — met.** The issuer's non-GAAP liquidity limitation, quoted exactly.
- **CP-0 — missed.** The key names the current borrowing-capacity statement
  ("When compliance reporting requirements have been completed and assuming no
  change from 31…"). CP-0 cited four blocks from the correct documents,
  including the consolidated third-party debt nominal amounts, but not that
  sentence.

This is a genuine evidence-selection miss, not a protocol failure: the module
answered, quoted the right documents, and every quote it gave anchored. It
simply did not select the block the key names.

`qualification_performed.complete` is **false** and no verdict was recorded.
That is the gate landed at `b456966` doing its job — before it, `complete` was
`matrix is not None`, and this snapshot, missing a key, would have been
signable as QUALIFIED. Nothing here may be represented as a qualified build.

An upgrade attempt must be a new, separately authorized run; the corpus and key
are unchanged, so it would not be a new qualification identity.

## OpenAI Terra v3 second run — 2026-09-16

Run `33ca320e-ef8e-4ca8-bdba-1e4d31355d1d`, same profile, corpus, key and
price, driven by `scripts/qualify.py` (the driver now lives in the tree). It
went **worse**, and what it failed on was the host's, not the model's.

- CP-0 accepted on its first attempt, `$0.23739675`, two citations — and again
  not the answer key's borrowing-capacity sentence. It cited the consolidated
  third-party debt nominal amounts and the preliminary results heading.
- CP-L10 answered in full, `$0.27101725`: 33 KB of Markdown, every required
  section, five citations whose quotes were all present in its own body. The
  host refused `HANDOFF_MALFORMED` and the run stopped `RUNNING` with no
  matrix. Total `$0.50841400`.

### What the refusal actually was

CP-L10 wrote its Evidence Trace the way prose writes a quotation:

    - **E-01 — Q4/FY2025 issuer release, p.6:** “The preliminary unaudited
      selected financial results are set forth below:”

`_quoted` compares whole whitespace tokens, so it read `“The` against `The`
and `below:”` against `below:` and concluded the module had not quoted what it
cited. Every one of the five citations failed the same way.

This is almost certainly what the three DeepSeek attempts were too — all three
were recorded as "returned N citations, quoted none of them in the body" —
which means the corpus has been blamed on three model attempts for a defect in
the host's reader. Fixed at `7a12c6d`: the two outer tokens of the window may
carry quotation marks, the quote's own words and internal punctuation still
must match exactly, and `verify_citations` is untouched, so nothing about what
may be *cited* moved. Verified against this stored answer, which now parses
with its five citations.

### What two runs say about the CP-0 key

Both runs completed CP-0 on the first attempt and neither cited the key's
sentence, though it was offered: it is rank 2 by length on its page and one of
the 93 blocks flagged `citation_candidate: true`. CP-0 cited scope and
boundary blocks both times — what the release covers, the entity perimeter, the
preliminary results, the debt nominal amounts.

That is what a module called `SourceReadiness` should cite. The key asks CP-0
for a current borrowing-capacity statement, which is a credit fact belonging to
CP-5's or CP-L10's reading. On this evidence the expectation is miscast rather
than unmet, and re-running the same key against the same module is not likely
to change it. Moving it is a change to a frozen answer key and therefore to the
set digest, so it is not made here.

Retained: database `caos_qualify_73f0718037d34d95a19417be505b77d2`, blob root
`/var/folders/81/bwblpst93lb6wb3lwrk8k6800000gn/T/caos-qualify-guifvx4y`,
capture beside this file.

## The answer key re-cast — 2026-09-16

The CP-0 expectation has been moved to CP-5. The set is now a different set:

| | |
|---|---|
| Digest before | `ec84bf8bbb1b45fd715d52466b9142778b4346ab13b252951db0b589209d07d1` |
| Digest after | `ae70850d27d1860155ec772ac27e95d7747dd2e9ab944f87034e0215dde407d8` |

**Why.** CP-0 is `SourceReadiness`: what the supplied sources are, what they
cover, and what they can support. The expectation asked it for the issuer's
current borrowing-capacity statement, which is a credit fact — CP-5's reading,
from the same document and the same kind of material as CP-5's existing
liquidity key. The expectation was miscast when it was fixed, and that is the
reason it moved; the two runs that missed it are corroboration, not the
argument. Both completed CP-0 on the first attempt and both cited scope and
perimeter blocks, which is what the module is for.

**What this costs.** Runs `e0e101b5…` and `33ca320e…` were measured against the
set that digests `ec84bf8b…`. They are not comparable to anything performed
after this change, and their records above say which set they were measured
against. That is what the digest is for.

**What is still owed.** CP-0 now carries no expectation, so the set measures
two modules by key and CP-0 only by proof — artifact accepted, host record
valid, every citation anchored. A replacement must be authored the way the
original was: read the Q4 release, decide from CP-0's own contract what a
readiness module must surface, and fix it before the next run. It must not be
chosen from what a previous run happened to cite — two runs' output is now on
the record, and a key picked from it would be measuring the model against
itself.

No run has been performed against this set.

## DeepSeek re-tried against the fixed reader — 2026-09-16

The v2 conclusion that DeepSeek V4 Pro is not qualified rested on three billed
CP-0 attempts recorded as "returned N citations; none of their exact quotes
appeared in the Markdown body", which reads like the reader defect fixed at
`7a12c6d`. The model was re-tried on that suspicion.

**That attribution was too broad, and is corrected below.** The surviving
record does not support it for at least two of the three: attempt 2 refused
`CITATION_NOT_DELIVERED` over a mutated source UUID, which `parse_response`
raises *before* the quote check, and attempt 3 emitted `## Analysis` twice,
which the vendor headings rule refuses whatever the quoting. Only attempt 1 is
consistent with the reader defect, and its generation id places it inside the
window between the candidate rule landing and the "do not enumerate candidates"
hardening — consistent with a model listing every eligible block. The runs are
gone, so this cannot be settled; what can be said is that the reader defect
explains at most one of the three, not all three.

- Set: `ae70850d27d1860155ec772ac27e95d7747dd2e9ab944f87034e0215dde407d8`
  (the re-cast key; CP-0 carries no expectation)
- Profile/model: `openrouter/ionstream/default/65536` /
  `deepseek/deepseek-v4-pro-0813`, the same profile the v2 run used
- Price: `$0.0000009834` input, `$0.0000029502` output per token, dated
  2026-09-16 from OpenRouter's published list; reservation `$1.2245139456` per
  call
- Run `ff71c457-70b8-44bd-b6ef-2099927b8936`, total `$0.33371808`

A first attempt, run `9bde894f-47fd-4424-bf8b-7713bef2d406`, refused
`PROVIDER_UNAVAILABLE` with **no charge and no generation**: Ionstream's shared
pool returned 429. Indeterminate rather than failed, so the attempt kept its
reservation and nothing was billed. Three probes at 8, 4,096 and 65,536
completion tokens all returned 200 minutes later, so it was transient and not
the host's fixed token ceiling.

### Result

| Module | Charge | Result |
|---|---:|---|
| CP-0 | `$0.15272064` | **accepted**, one artifact, one anchored citation |
| CP-L10 | `$0.18099744` | `HANDOFF_MALFORMED`; the run stopped `RUNNING` |

**CP-0 now passes.** Under v2 it failed three times in a row. That is the
reader fix and the v3 provenance context together, and it means the v2 record
overstated what was wrong with this model.

**CP-L10 fails on its own merits.** The refusal is not the quotation rule —
`parse_response` accepts the answer, and every cited quote is in the body. The
bundle's own validator returns the error:

    qa_status Restricted caps confidence_score at 59

The module declared `qa_status: Restricted` and then scored itself above the
cap the vendor contract sets for that status. Its register headings are also
paraphrased rather than reproduced — `TL20.1 — Source and Scope Guard` for
`Source and Scope Gate`, `TL40.3 —  decision screen`, `TL23.4 — Gaps` — where
the Terra runs reproduced them exactly.

**The verdict does not change: DeepSeek V4 Pro is not qualified.** The reason
does. This refusal is the model's, and precisely so: the cap lives in the same
vendor script that computes the score
(`cp-l10-financial-change-screen/scripts/confidence_score.py`), which applies
`min(score, 59)` whenever a MATERIAL finding exists. The module listed three
MATERIAL rows and scored itself 69. Terra satisfied the same rule four times
out of four, so the corpus does not force the contradiction — it forces
`Restricted`, which is a different thing.

Two corrections to what was said above about this run:

- The paraphrased register headings are **not** why it was refused. The
  vendor's `completeness_check` finds registers by ID and returns zero
  violations on this handoff; `validate_text` returns the cap error alone.
- DeepSeek's **accepted** CP-0 broke the same kind of rule in the other
  direction — `qa_status: Passed`, `committee_status: Committee Ready`,
  `confidence_score: 93`, over a self-declared `SOURCE_GAP | MATERIAL` row.
  The vendor validator checks only `Restricted → ≤59` and `Blocked → ≤39`, not
  "MATERIAL implies Restricted", and `completeness_check.load_contract` reads
  only cell disqualifiers, never the frontmatter ones. So the host accepted a
  CP-0 that contradicts the rule that later refused the same model's CP-L10.
  Ledgered in `CLAUDE.md`.

Retained: database `caos_qualify_cf7b0d99f8474825b7ce7264bb385e43` (the 429),
the second run's database and blob root are named in its capture beside this
file.

### Operator decision — 2026-09-16

`deepseek/deepseek-v4-pro-0813` is **unapproved for use**. That is the
operator's decision and it agrees with the evidence above: its only run against
this set stopped mid-route on a contract violation the model owns.

It is recorded here as a decision, not as a verdict. No `qualification_verdicts`
row exists for this model or any other, and the host has no representation of
"unapproved" — a model is simply not configured. The distinction matters: a
verdict is digest-bound to performed evidence and re-checkable; this is a
person's choice about what to configure.

## Terra against the corrected key — 2026-09-16, and what it exposed

Run `62698a60-c777-4153-9d21-d2dae189cf6c`, set
`746ee12d82703d9c04399708be8f1ef4996023cd9cb4dfa844a7687ed3428cc6` (the
borrowing key re-authored to the line that carries the fact). `$0.5161795`.

CP-0 accepted (`$0.2511`, `Restricted`, 59, `READY_WITH_LIMITATIONS`). CP-L10
accepted (`$0.2650795`, `Restricted`, 59, `Requires More Work`). Two artifacts,
four citations, all anchored. The run then ended **BLOCKED** and CP-5 was never
called, so all three keys are missed and `complete` is false.

### Why it blocked

**This section was wrong when first written, and is corrected here.** It said
CP-0 judged CP-5 unready for want of audited statements and executed debt
documents. That is not what CP-0 said. Its T8 row reads:

    | 2 | CP-5 | Run CP-5 | DO NOT RUN
    | …releases… | VMO2_CP-0_20260915.md plus completed CP-L10 handoff
    | CONDITIONAL
    | CP-L10 must first produce the selected-route analytical handoff for
      traceability review. |

The blocker is **sequencing**, not evidence. The gaps naming audited statements
and executed debt documents list CP-5 among the modules they affect, and the
first reading mistook that for the verdict's ground.

That distinction is the whole finding, because CP-0's own contract forbids the
verdict it gave. `cp-0-source-readiness/SKILL.md` line 359:

> Source readiness does not assert that upstream analytical handoffs already
> exist: navigation checks those separately.

Sequencing is the dependency plan's job — the catalog's edges, plus the rule
that a soft edge blocks while CP-0 has marked its source ready. CP-0 encoded
"CP-L10 has not run yet" as a source-readiness verdict, which is exactly what
that line tells it not to do. The host then honoured a structurally conformant
artifact, as invariant 4 requires of it.

So: not the corpus, not the host's reading, and not the `CP-L10 → CP-5`
ADVISORY edge, which behaved as designed — once CP-0 marked CP-L10 ready that
edge is blocking, which is how CP-5 is sequenced after the module it traces.

### What it actually exposes

Not a corpus that fails to support CP-5 — CP-5 needs no credit evidence; it
traces the analysts' findings. What varies between runs is whether CP-0 keeps
sequencing out of its readiness column. Run `e0e101b5…` did and the route
completed; run `62698a60…` did not and the route could not.

Behind the model's mistake is a gap in the bundle: `CONDITIONAL` is defined
only as "emit `DO NOT RUN`". Nothing says the condition must be a *source*
condition, and nothing discharges it within a run — the vendor's own
`prepare_invocation.py` and `handoffs.py` refuse a conditional module exactly
as the host does. A status that invites "conditional on an upstream handoff" is
therefore fatal to the route in vendor and host alike.

Three consequences:

- `--attempts` did not fire and should not have. A validated Blocked handoff is
  an answer, not a refusal: `Performed.stopped` is `None`, so the driver
  correctly did not retry. Retrying would have been paying for a different
  opinion.
- `complete` is reachable, and the earlier claim that it was not rested on the
  misreading above. What it needs is a CP-0 that does not put a sequencing
  condition in a readiness column.
- The remedies this section first proposed — drop CP-5 from the route, or
  change the corpus — were aimed at the wrong cause and are withdrawn. Neither
  would have helped: the same misuse recurs on any corpus.
- The set now measures this directly. `expects_ready: ["CP-L10", "CP-5"]` reads
  the host's own readiness projection, so a run where CP-0 gates CP-5 scores
  `ready_met=false` and says so, instead of reporting three missed citations by
  a module that was never asked to cite anything.

No further run was made. Spend on this set to date: `$2.18` across four Terra
runs and one DeepSeek run.

## Terra with CP-0's own rule restated — 2026-09-16

Run `729b0682-1076-4f7d-8371-2793bf43f3cd`, set
`a1a70f04ab0aa1b4f46940d6b17131a50909a14521b9a773210bd839695d2bbf`,
`$0.77497100`. The best run this set has had, and it isolates what is left.

- **Run status `COMPLETE`.** CP-0 did not gate CP-5. All three modules answered
  on the first attempt: CP-0 `$0.24055425`, CP-L10 `$0.26801425`, CP-5
  `$0.2664025`. Three artifacts, ten citations, every one re-located.
- **`ready_met: true`.** The readiness key passed — the first direct evidence
  that restating `SKILL.md` line 359 in CP-0's final check changes the verdict
  it writes. Run `62698a60…` put a sequencing condition in a readiness column
  and ended BLOCKED; this one did not.
- **`complete` is still false**: `met=1, missed=2`. CP-L10 cited the Adjusted
  Free Cash Flow limitation — an answer key — and not the goodwill impairment
  or the borrowing-capacity line.

### What is left is the citation key, and only that

CP-L10 returned five citations from the 93 the host offered: the guidance
metrics, the entity perimeter, the preliminary-results heading, the AFCF
limitation, and the £1,645.5 million Cellnex bridge. Sound, relevant evidence
for a financial-change screen — and a set of five drawn from ninety-three, which
has to contain three named lines for this set to pass.

Every other failure mode this set has produced is now closed: the reader defect
(`7a12c6d`), the diagnostic double-bill (`cf6905d`), the gate misuse
(`a40b2b4`), and the key that named a subordinate clause (`e258422`). What
remains is the instrument. A citation key measures whether a module's handful of
length-selected quotes happens to include particular lines; it does not measure
whether the screen was right, and this run's CP-L10 produced a defensible screen
while scoring `missed=2`.

The `expects_ready` key added in `1b9c060` is the shape that works, because it
reads a host projection rather than hoping for a quotation. The same is
available for `qa_status`, `committee_status`, `confidence_score`,
`limitation_flags` and CP-0's T8 readiness rows, and the bundle ships a register
parser for the rest. Until the citation keys are replaced with keys of that
kind, this set measures the draw rather than the analysis.

Spend on this set to date: `$2.96` across five Terra runs and one DeepSeek run.

## The first signable snapshot — 2026-09-16

Run `42e17048-8b50-48cc-94ff-833d894a68cb`, set
`0863964bb4dbad8dc8772654311d7b59dfc2810cd08cf6cfdeda6a940ed0db74`,
`$0.76978275`. **`qualification_performed.complete` is true.**

| | |
|---|---|
| Run status | `COMPLETE`, three modules, one attempt each |
| Proof | 3 artifacts, 8 citations, every one re-located |
| Citation key | `met=1, missed=0` — the goodwill impairment |
| `ready_met` | true — CP-0 gated nothing it should not have |
| `projections_met` | true — every module concluded what the set required |

Charges: CP-0 `$0.231761`, CP-L10 `$0.265523`, CP-5 `$0.27249875`. Database
`caos_qualify_eaa6ad1a8dc44ecb9171afec00325bc9`; one `qualification_evidence`
row, and **zero `qualification_verdicts`** — the host has produced a snapshot a
reviewer may sign, and nobody has signed it. That distinction is the point: a
verdict is a person's, and `complete` only says the question was answered.

### Verified rather than assumed

The capture written beside this file reports `projections_met: null`, which is
the capture under-reporting and not the key going unevaluated — `scripts/qualify.py`
was serialising `ready_met` and not the field added after it, now fixed.
`complete` treats an undeclared key as passed (`is not False`), so a key that
silently did nothing would have produced this same `true`. Re-deriving the
matrix from the store against the then-current set on disk gives `projections_met: True`,
`ready_met: True`, `proven: True`, `missed: 0`. The signable document stored in
the database carried the field correctly throughout.

### What made the difference, in order

1. `7a12c6d` — the reader refused typographic quotation marks and was blaming
   models for it.
2. `cf6905d` — a billed call whose body could not be stored was billed again.
3. `a40b2b4` — CP-0's own readiness rule restated in its final check; the gate
   stopped refusing CP-5 for a sequencing reason its contract forbids.
4. `e258422` — the borrowing key named a subordinate clause, not the fact.
5. `1b9c060`, `32bb47f` — keys that read the host's own projections instead of
   hoping a module's handful of quotes happened to include particular lines.

Four of those five were the host's or the record's, not the models'. The
citation-only instrument is what hid them: every one of them presented as a
model failing to find evidence.

Spend on this set to date: `$3.73` across six Terra runs and one DeepSeek run.

## Re-run against build `cdea0c9f` — 2026-09-16

Run `36d87283-ef92-49a2-a2b1-ef5928aaa5d2`, the first against the bundle build
produced by `docs/DECISIONS.md` §61. `$1.37845425`, the most any single run of
this set has cost, because `--attempts 3` bought CP-5 two more tries.

CP-0 accepted (`$0.24881325`), CP-L10 accepted (`$0.27359275`). **CP-5 refused
three times** — `$0.288437`, `$0.29529725`, `$0.272314` — and the run is
`RUNNING`, stopped `HANDOFF_INCOMPLETE`. `complete` is false.

### Not the bundle edit

`validate_handoff.validate_text` returns no errors on any of the three CP-5
bodies, so the severity rule added in §61 is not what refused them. The refusal
is `completeness_check`, which §61 deliberately did not touch. CP-0 and CP-L10
both passed the new rule, and CP-0 did not gate anything.

### What refused them

CP-5's own completeness contract (`cp-5-evidence-trace-validator/SKILL.md:101`)
lists `critical_cell_values_casefold` — cell values that disqualify a full run.
Among them: `insufficient information`, `not calculable from provided
materials`, `not assessable`, `unavailable`. T5B.5's Claim Status column is
critical and exempts none of them.

All three attempts wrote exactly those words:

    T5B.5 row 3: critical column 'Claim Status' holds a disqualifying
    placeholder 'Insufficient Information'
    T5B.5 row 2: critical column 'Status' holds a disqualifying placeholder
    'Not Calculable from Provided Materials'

CP-5 traces claims to sources. Handed two earnings releases, it reported that
some claims could not be calculated from what it was given — which is true, and
is the answer its own runbook asks for — and the completeness rule refused the
handoff for saying so. Three times, each one billed.

This is the same shape as everything else found today: the apparatus punishing
honest restraint. A validator that cannot say "this cannot be verified from the
provided materials" in a status column can only pass by overstating what the
evidence supports.

It is also not new. Run `42e17048…`'s CP-5 was accepted because it happened not
to use those words; the difference between that run and this one is phrasing,
not rigour. The set's `expects_projection` keys cannot see it either: a refused
CP-5 produces no artifact, so its conclusion is unreadable and the row reads as
a run that stopped.

*Upgrade:* `disqualifier_exempt_columns` already exists — T5B.6 exempts
`Evidence Status` — so the mechanism is there and the question is which of
CP-5's status columns should carry it. That is a bundle change and needs its own
authorisation, and it belongs with the `completeness_check.load_contract` half
that §61 left open.

Spend on this set to date: `$5.11`.

## Build `30222a49` — CP-5 completes, and the last key is a draw

Two runs against the build produced by `docs/DECISIONS.md` §63, which exempted
T5B.5's `Status` and `Claim Status` from the disqualifying-placeholder rule.

| | Run `c5da2040…` | Run `54ec3752…` |
|---|---|---|
| Route | COMPLETE | COMPLETE |
| Artifacts | 3 | 3 |
| Citations, all re-located | 4 | 9 |
| `ready_met` | true | true |
| `projections_met` | true | true |
| Citation key | missed | missed |
| Cost | `$1.04320025` | `$0.80026775` |

**CP-5 is fixed.** It completed in both — in the first on its retry, in the
second first time — where run `36d87283…` on the previous build was refused
three times for writing the honest answer. All three of those stored bodies were
replayed through the amended contract and produce no violation, so this is the
same defect, measured before and after.

**Every key now passes except one.** Readiness and all four declared conclusions
are met in both runs. What misses is the single citation key: CP-L10 did not
quote the `£1,021.7 million` Q4 goodwill impairment. Run `42e17048…` did quote
it. So across three runs where CP-L10 produced an accepted screen, the material
figure was surfaced once.

### What that means, and it is not an instrument defect

The earlier citation keys were replaced because they measured the draw. This one
is different in kind: the Q4 goodwill impairment is *the* material change in the
period, and a financial-change screen that does not surface it is a weaker
screen. The key is doing the job an evidence key is for.

So the honest reading of two misses is a finding about the model, not about the
apparatus: **Terra surfaces the period's material figure inconsistently**, and a
qualification bar that only passes when it does is the bar working. Lowering it
to make a run pass would be the exact failure `docs/REPAIR_PLAN.md`'s guardrails
name.

No `complete` snapshot exists on `30222a49`. The path to one is a run in which
CP-L10 cites the impairment; on the evidence so far that is roughly one run in
three, at about `$0.90` each.

Spend on this set to date: `$6.95`.

## A historical signable snapshot for the prior set — 2026-09-16

Run `62308d4e-70b5-4793-abb0-7be62d2ceba6`, build `30222a49`, set
`0863964b…`, `$0.79558075`. **`qualification_performed.complete` was true for
that prior set and build.** It does not bind the current `27b7df72…` set.

| | |
|---|---|
| Route | COMPLETE, three modules |
| Proof | 3 artifacts, 11 citations, every one re-located |
| Citation key | `met=1, missed=0` — CP-L10 quoted the £1,021.7m impairment |
| `ready_met` | true |
| `projections_met` | true |

Re-derived from the store against the then-current set on disk rather than read from the
capture: `proven=True, missed=0, ready_met=True, projections_met=True`. The
stored row binds set `0863964b…`, build `30222a49…`, provider
`openrouter/openai/flex/high/65536`, model `openai/gpt-5.6-terra`.

- Database `caos_qualify_5a47243d96774e088f1bfebb6271f2d1`
- Evidence digest `bb09d8d0bcec1524eabdc426142ef9eae60890be52a58bbf973f321644cd4621`
- Performed digest `d758a253dba3aed1f88cd325a46c8984d2e0da9189a3027e8f8b4734eb78a7bd`

It took three runs on this build for CP-L10 to surface the material figure,
which is the finding recorded above and is not changed by this one succeeding.
A model that quotes the period's largest single item one time in three is what
the record says; the bar was not moved to meet it.

`qualification_verdicts` is still empty. Nothing in `server/` or `scripts/`
calls `record_verdict`, so no reviewer can sign — the open half of F17 in
`docs/DECISIONS.md` §64. The snapshot is signable in the sense that `complete`
is true and every binding a verdict must match is recorded; what is missing is
the route by which a person asserts one.

Spend on this set to date: `$7.75` across eleven runs.
