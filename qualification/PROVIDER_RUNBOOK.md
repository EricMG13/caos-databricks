# The deployment fork (D31) replayed on every stored real answer — 23 September 2026, night

Status: **no spend; live runs blocked (the OpenRouter account has $0.48 of credit left,
`docs/rebuild/blockers.md`).** Every stored answer from the day's runs (80, five models)
was put through the vendor's checks as the host runs them (validator, completeness,
CP-0's T8 parser) twice: under the original bundle (`78c24be4`) and under the fork
(`99ed0dc3`).

| Module | Answers | Vendor-clean, original | Vendor-clean, fork |
|---|---|---|---|
| CP-0 | 65 | 26 | 32 |
| CP-1 | 6 | 0 | 1 |
| CP-1A | 3 | 0 | 1 |
| CP-3D | 4 | 1 | 2 |
| CP-5 | 2 | 1 | 1 |

The fork cleared 8 validator refusals (6 MATERIAL, 2 CRITICAL, each a Severity table outside
QA Validation) and cut completeness violations from 221 to 114. Of the 9 answers it newly
clears, all 9 also pass the host's own checks, which no bundle changes: every quote carried
verbatim, every citation anchored (checked against the run's whole evidence, not each node's
delivered subset). They are both Claude Opus 5.5 CP-0 answers, CP-0 answers from GPT-5.6 luna
(2), Gemini 2.5 Flash and GPT-6 Luna Pro, and GPT-6 Luna Pro's CP-1, CP-1A and CP-3D: the first
CP-1 and CP-1A answers any model has produced that the contract accepts. Not re-run here:
the host's identity check and CP-0's T8 module-set check, which a replay under a new build
cannot reproduce (the runs pinned the old bundle). The largest refusal left is the model's own:
`qa_status: Restricted` above the score cap of 59 (18 answers), which the second attempt names.

# Downstream modules, and N52 measured — 23 September 2026, late

Status: **one set qualifies end to end: `ccl-fy2025-market-dislocation` on GPT-6 Luna Pro with
N52 (D2: every key, projection, readiness and proof check met). No other set completes; the
stops are the gate's readiness verdicts and the models' misses of the vendor's register
contract, none the host's. NOT_QUALIFIED overall.**

Same $8.00 authorisation. Spend on the key: **$12.08** after, $4.44 of the $8.00 in all.
`openai/gpt-5.6-luna` ($0.20/$1.20) for E1-E2 at `cp0/investigation`; `openai/gpt-6-luna-pro`
($0.10/$0.50, reasoning mode pro, about $0.05 and three minutes a call) for G1
at `cp0/investigation` and D1-D6 at branch `d30/widen` (N52). Evidence (git-ignored):
`docs/rebuild/runs/live-2026-09-23/{E,G,D}*.{json,log}`.

| Run | Set | Attempts (refusal, or OK) | End |
|---|---|---|---|
| E1 | earnings-update | CP-0 ×5: `Restricted` above the 59 cap ×4, MATERIAL under `Passed` ×1 | stopped, CP-0 |
| E2 | earnings-update | CP-0 ×13: the cap ×11 (a second T8 table ×7), MATERIAL under `Passed` ×1, quotes ×2 | stopped, CP-0 |
| G1 | earnings-update | CP-0 unanchored, **OK**; CP-1 ×6 incomplete/malformed | stopped, CP-1 |
| D1 | earnings-update | CP-0 **OK**; CP-5 incomplete, then (N52) a valid `Blocked` | BLOCKED |
| D2 | market-dislocation | CP-0 malformed, **OK**; CP-3D incomplete, then (N52) **OK** | **COMPLETE, qualified** |
| D3 | relative-value | CP-0 **OK** | BLOCKED at the gate |
| D4 | vmo2-fy2025 (PDF) | CP-0 unanchored, then (N52) **OK** | BLOCKED at the gate |
| D5 | lite-full-credit-screen | CP-0 unanchored ×2, **OK**; CP-1A ×3 incomplete/malformed | stopped, CP-1A |
| D6 | liquidity | CP-0 ×4: T8 readiness in backticks, unanchored, not the transport, unanchored | stopped, CP-0 |

What it shows.

- **N52 works where D30 alone did not.** Six nodes refused incomplete or unanchored got the
  N52 second attempt; three answered it validly: D2's CP-3D (placeholder critical cells fixed,
  accepted, and the set qualified), D1's CP-5 (a validated `Blocked`) and D4's CP-0 (the named
  citation fixed, accepted). The other three missed again: D5's and D6's CP-0 fixed what they
  were told and broke a different rule; D5's CP-1A fixed its placeholder cells but not the
  eleven register IDs its message does not name (N55). Under D30 alone, G1's CP-1 second attempt fixed every
  T4 column it was told of, the literal `Period 1…N` included, then broke an interface table;
  its four unaided retries never fixed the headers.
- **The gate is the commonest stop.** GPT-6 Luna Pro's CP-0 marks a consumer `CONDITIONAL`
  for any source it lacks, as the vendor lets it: CP-L10 on every pack (for a "complete
  debt-document set", although CP-L10's own skill runs with missing documents as
  `COMPLETE_WITH_GAPS`), CP-1/CP-1B/CP-2 without the FY2026 10-Q (D1), and every consumer on a
  PDF pack whose extraction the host's block does not attest (D4; N53). Two keys expect a
  clearance the pack cannot support (N54).
- **The modules' own contracts are the other stop.** CP-1 and CP-1A are refused for register
  shape the vendor's checker matches literally: `Period 1…N` headers, register IDs in the
  heading, one bad interface table voiding all seven (N55).
- **GPT-5.6 luna does not clear CP-0 on this set**: 0 of 18 attempts in E1-E2, 15 of them the
  `Restricted` score cap it is told of in `SKILL.md` and, on its second attempt, by the
  validator.
- Every refusal was replayed through the host's verdict (`canonical._replayed_answer`) and
  traced to its rule; one host fault was found and fixed on `d30/widen`: the second attempt's
  anchoring line said "not on its cited page" for a quote that is on the page across two
  wrapped PDF lines; it now names the rule broken, "not one evidence line of its cited page".

# CP-0 investigation — 23 September 2026, evening

Status: **a real model's CP-0 answer accepted live (GPT-5.6 luna, anchored); two host
defects fixed (F148, F149); NOT_QUALIFIED (no set has finished).**

Method. Every stored CP-0 answer with a body in the blob root (29, from six models) was
replayed read-only through the host's full post-call verdict (`canonical._replayed_answer`),
and each refusal traced to the check and the cause behind it, by rule, page and shape only.
Then three live sets on `openai/gpt-5.6-luna` ($0.20/$1.20 per million, `--ceiling 1.00`) at
the `cp0/investigation` commits, under the same $8.00 authorisation as below. Spend on the
key: **$9.21** after, $1.57 of the $8.00 in all. Evidence (git-ignored):
`docs/rebuild/runs/live-2026-09-23/L1..L3-luna-market-dislocation.*`.

Host defects. F148: sentence punctuation and brackets beside a quote made its edge word a
different word (12 quotes; all nine of the Opus 5.5 answer's). F149: Markdown's backslash
escape did the same (`\"...\"`; all eight of the Sonnet 5 answer's).

What each stored answer gets from the fixed host:

| Model | Answers | Refused now for |
|---|---|---|
| Claude Opus 5.5 | 2 | the vendor severity rule alone (a MATERIAL finding under `qa_status: Passed`), the rule D30's second attempt names; every quote carried |
| Claude Opus 5 | 1 | the same |
| Claude Sonnet 5 | 1 | one citation of ten naming page 17 for a line its prompt shows under page 18 (`CITATION_NOT_LOCATED`); quotes, validator and completeness pass |
| Claude Haiku 4.5 | 5 | quotes absent or paraphrased; the severity rule; the confidence cap; in one answer two quotes glued by an ellipsis with no space (`Ba1...Carnival`), read as one different word, beside a quote absent from the body |
| Gemini 2.5 Flash | 12 | quotes not verbatim; answers not JSON; one two-word quote on its page twice (`CITATION_AMBIGUOUS`); one incomplete |
| GPT-5.6 luna | 8 | the live runs below; one accepted |

GPT-5.6 terra and sol (18–19 September, the only earlier accepted CP-0s) have no body in this
blob root and were not replayed.

| Run | CP-0 attempts | Stop |
|---|---|---|
| L1 | 1: transport, quotes and validator clean; a fixture marker in `validation_warnings` and a second T8 table | `HANDOFF_INCOMPLETE` (no second attempt on it, OD-1) |
| L2 (`--attempts 3`) | 1: `Restricted` caps `confidence_score` at 59. 2 (D30): **that rule met**; one citation absent from the body. 3 (operator re-entry): **accepted**, its citation anchored | CP-3D refused twice, then `BUDGET_CEILING_REACHED` at 1.00 |
| L3 (`--attempts 3`) | 1: page 11 cited with page 18's spacing (`CITATION_NOT_LOCATED`). 2: a paraphrased quote. 3 (D30): **quote fixed**; the confidence cap. 4 (re-entry): a re-cased quote and an absent one | `HANDOFF_MALFORMED`, attempts spent |

What it shows. After F148 and F149, every refusal is traceable to a rule the authority or
the final check states and the answer broke; none remains that the host caused (the glued
ellipsis is kept as the model's: a letter follows the marks, and that answer fails anyway). The fed-back
check is acted on each time it is given (L2 #2, L3 #3), and a clean answer is accepted and
anchored (L2 #3). What stands between a model and CP-0 is per-attempt reliability: the second
attempt is due only on `HANDOFF_MALFORMED`, so three of luna's eight attempts stopped their
node on a code that gets none. N52 is the owner's option. A live Claude run was not made:
D29's admission needs a 9.05 (Sonnet 5 at $2/$10) or 22.61 (Opus at $5/$25) ceiling,
beyond the $6.43 left.

# Second attempt (D30) and whole 10-Ks (D29) — 23 September 2026, afternoon

Status: **D30 and D29 measured live; no CP-0 accepted yet; NOT_QUALIFIED.**

A second owner authorisation: cheaper models only, **$8.00** for all combined testing.
Seven sets were run at `c37733e` plus the D29/D30 commits (`6e99ec4`, `029c13b`) through
the test-only adapter, `--attempts 1` (so every second attempt below is the host's own, D30),
`--ceiling 2.00` for Gemini and `5.00` for Haiku, which D29 requires to cover one 4 MiB
worst-case call (1.42 and 4.52). A run started only if the key's spend so far plus its
ceiling fitted the $8.00. The key was read from the owner's file at call time and is not
recorded. Spend on the key: **$1.13** ($7.64 before, $8.77 after); the host billed $1.29 at
list prices. Evidence (git-ignored): `docs/rebuild/runs/live-2026-09-23/`.

The checks each answer failed, as the second attempt's block reports them (rules only):

| Run | Model | Set | CP-0 attempt 1 | CP-0 attempt 2 (carrying attempt 1's checks) | Stop |
|---|---|---|---|---|---|
| A | `google/gemini-2.5-flash` | `ccl-fy2025-market-dislocation` | vendor-clean; 1 of 4 citations not verbatim | not a JSON object (a raw newline inside a string) | `HANDOFF_MALFORMED` |
| A2 | same | same | not a JSON object | vendor-clean; 2 of 2 citations not verbatim | `HANDOFF_MALFORMED` |
| A3 | same | same | 6 of 6 not verbatim; H2 headings out of order | no body, no usage | `PROVIDER_RESPONSE_INVALID` |
| H1 | `anthropic/claude-haiku-4.5` | same | 12 of 12 not verbatim; **MATERIAL finding under `qa_status: Passed`** | **severity rule met**; 3 of 9 not verbatim; `Restricted` caps `confidence_score` at 59 | `HANDOFF_MALFORMED` |
| H2 | same | same | 10 of 10 not verbatim; MATERIAL under Passed; H2 headings out of order | **headings fixed**; 8 of 10 not verbatim; MATERIAL under Passed | `HANDOFF_MALFORMED` |
| B1 | `google/gemini-2.5-flash` | `ba-fy2025` (Boeing 10-K, 1.18 MB, whole) | 3 of 8 not verbatim; front matter YAML malformed | 1 of 1 not verbatim; no front-matter boundary | `HANDOFF_MALFORMED` |
| F1 | same | `f-fy2025` (Ford 10-K, 1.92 MB, whole) | not a JSON object | transport and vendor clean | `HANDOFF_INCOMPLETE` |

What it shows. D30 works as built: every refused CP-0 got exactly one second attempt,
reserved and billed like any other, carrying the checks; a second refusal stopped the run and
nothing was called downstream. The fed-back check is acted on: Haiku met the exact rule it was
told it broke (H1: the severity rule; H2: the heading order) and quoted more verbatim, but broke
an adjacent rule or kept another, so no CP-0 has been accepted from any model. D29 works end to
end: both 10-Ks went to the gate whole in one request each, admitted by the host and answered by
the provider at about $0.08–0.12 a call, where the legacy 1 MiB ceiling had forced page mode.
The two misses left are the model's: quotes that are not verbatim (every run) and, on Gemini,
answers that are not strict JSON (3 of its 10). N50 and N51 are the host-side options.

# Qualification provider and spend pin — 23 September 2026 (rebuilt host)

Status: **FIRST LIVE RUNS ON CLAUDE OPUS 5 — one LITE set launched once; CP-0 refused by the vendor's severity rule; NOT_QUALIFIED.**

The owner supplied an OpenRouter key and a total budget of $14.00 for the day.
The rebuilt host was driven through the test-only adapter (`tests/qualify_openrouter.py`
over `tests/openrouter_adapter.py`), identity `openrouter/anthropic/claude-opus-5/none/65536`,
price `anthropic/claude-opus-5,0.000005,0.000025,2026-09-23`, `--attempts 1`, a 14.00
ceiling per set, the run database on the persistent dev server and the blobs under
`.dev-data/qualification-blobs`. The key was read from the owner's file at call time and is
not recorded anywhere.

| Run | Set | Route | Outcome | Spend on the key after it |
|---|---|---|---|---|
| live smoke, `tests/test_live_run.py` | two synthetic documents | LITE_EARNINGS_UPDATE | CP-0 accepted (36,544-byte handoff); CP-L10 refused `UPSTREAM_SECTION_OVER_CEILING` at the legacy 32 KiB bound (F110) | $1.01 |
| live smoke, bound lifted | same | same | CP-0 `Restricted`, `READY_WITH_LIMITATIONS`; route ended BLOCKED on a source-limited pack, the methodology's verdict | $2.09 |
| `ccl-fy2025-market-dislocation`, Opus 5, database `caos_qualify_7e7bf95604d146e49078b0521d789a32` | Carnival FY2025, two documents | MARKET_DISLOCATION (CP-0, CP-3D) | The driver was stopped while CP-0's call was on the wire, to diagnose the run above before spending more; the endpoint billed the call, nothing was recorded (an abandoned attempt, reservation held), no artifact. | $4.02 |
| `ccl-fy2025-market-dislocation`, **Opus 5.5**, run `76fcf302-0445-4c8f-b865-272efe22bea5`, database `caos_qualify_594429739df54eab99ce599b09146a4d` | same | same | CP-0 answered 28,785 bytes with 22 citations, 9 of them not quoting its own body verbatim; the vendor validator refused "a MATERIAL finding requires qa_status Restricted" against `qa_status: Passed`. `HANDOFF_MALFORMED`, no artifact, no CP-3D call. | see below |
| `ccl-fy2025-liquidity`, **Opus 5.5**, run `1b1ec13d-09cd-43f4-9034-32cfc30daea1`, database `caos_qualify_203781a43b5c45fc8c0185d8ae54087c` | Carnival FY2025, one document | LIQUIDITY_REVIEW (CP-0, CP-1, CP-2, CP-2D) | CP-0 answered 32,154 bytes with 23 citations, all quoted; refused by the same rule against `qa_status: Passed`. `HANDOFF_MALFORMED`, no artifact, no CP-1 call. | $5.23 |
| `ccl-fy2025`, run `65ae2607-fe24-42a6-8a23-4b9cad628baa`, database `caos_qualify_c1bc22c03b504716a44945815b8c11d7` | Carnival FY2025 10-K, one document | LITE_EARNINGS_UPDATE | CP-0 answered a well-formed 44,736-byte envelope with 18 citations, all quoted; the vendor validator refused it: "a MATERIAL finding requires qa_status Restricted" while the answer declared `qa_status: Passed`. Attempt refused `HANDOFF_MALFORMED`, no artifact accepted, no CP-L10 call, proof `ORCHESTRATION_NOTHING_TO_PROVE`, matrix incomplete, no verdict. | see the next row |

The host held on every step that is the host's: transport, the text bounds, citation
quoting, the typed refusal, the reservation and the record. The miss is the same
model-contract miss the 19 September runs recorded for the OpenAI models: the module
grades its own severity and then writes a `qa_status` the vendor's rule forbids for that
severity. Nothing in the host may restate the vendor's rule in the prompt (invariant 4,
prompt parity), so the next launch changes the model, not the host.

The rule is in the authority every CP-0 call receives: `CANON_SHARED.md` line 373, "any
MATERIAL, no CRITICAL → score ≤ 59, qa_status = Restricted", delivered whole beside the
module's `SKILL.md`. Three model generations (OpenAI on 19 September, Claude Opus 5 and
Claude Opus 5.5 today) each tagged a finding MATERIAL in their own body and still wrote
`Passed`. That is the agent's contract miss, reproduced, and the reason no pathway has an
accepted CP-0 artifact from a real model yet. Cheaper models are measured on the same
two-call set below.

## Cheaper models on the two-call set (`ccl-fy2025-market-dislocation`, `--attempts 1`)

| Model (OpenRouter id) | Price in/out per million | CP-0 outcome | Measured cost |
|---|---|---|---|
| `anthropic/claude-sonnet-5` | $2 / $10 | Vendor contract met (`qa_status: Restricted`, no vendor error); refused by the host's quote rule: 8 of 10 citations' `matched_text` do not appear verbatim in the body although the final-check block asks for exactly that. `HANDOFF_MALFORMED`. | $1.36 |
| `anthropic/claude-haiku-4.5` | $1 / $5 | Vendor error: `committee_status 'Committee Ready' is not permitted under decision_scope SCREENING_ONLY`; also 3 of 13 citations not quoted in the body. `HANDOFF_MALFORMED`. | $0.73 |
| `google/gemini-2.5-flash` | $0.30 / $2.50 | Vendor contract met (no vendor error); refused by the host's quote rule: none of its 8 citations appears verbatim in the body. `HANDOFF_MALFORMED`. | $0.17 |
| `deepseek/deepseek-v3.2` | $0.27 / $0.40 | The provider answered a 4xx before inference on both attempts (`PROVIDER_CALL_INVALID`, the message is not kept; the 164k-token context or the JSON response format are the likely causes). Nothing billed. | $0.05 over two runs |

Two distinct misses, then. The Claude Opus generations grade a MATERIAL finding and write
`Passed` (the vendor's rule); Sonnet 5 and Gemini 2.5 Flash meet the vendor's rules and
break the host's, by citing evidence lines they did not reproduce verbatim in their own
Evidence Trace, which the final-check block requires. The host refuses both typed, before
any downstream call, and the reservation is retained as designed. Spend on the key after
the four: $7.50.

Retry on the cheapest model that met the vendor contract, `google/gemini-2.5-flash`, with
`--attempts 2` (run database `caos_qualify_4d130dab70144e4a810bb200941e3fe2` was the first
launch, abandoned on the wire; see below): two CP-0 attempts, both `HANDOFF_MALFORMED`.
The first answered 12,439 bytes with 7 citations, vendor-clean, one citation not quoted in
the body; the second was not a JSON object at all, so the transport refused it. Cost $0.05.
Spend on the key at the close of the day: **$7.59 of the $14.00 authorised**.

One host-side defect surfaced on the way and was fixed (F112): the test-only adapter built
its client on the library's defaults, a 600 s timeout with two retries, so one hung call held
the first Gemini retry launch on the wire for over half an hour before it was stopped; the
adapter now carries the production deadline (240 s) and no retry below the seam.

# Qualification provider and spend pin — 19 September 2026

Status: **PAID BOUNDED RETRY COMPLETE — Sol/xhigh smoke sets ran once; Phase 4 remains stopped.**

## Phase 4 xhigh retry record

The owner explicitly authorized one configuration-only retry of the same two
unchanged smoke sets under the same official model and `openai` endpoint, with
reasoning effort `xhigh`, identity `openrouter/openai/xhigh/65536`, the
unchanged conservative price below, `--attempts 1`, a ceiling of `$12.451840`
per set, and an aggregate maximum of `$24.903680`. The CCL set was launched
first and reconciled before VMO2 was launched. Each driver was launched once;
neither set was re-entered or rerun.

The CCL driver made one CP-0 call. It retained `$3.381505` of reservation and
charged `$0.4907785`. The closed transport passed and all six citations quoted
by the answer anchored uniquely on their declared pages, but the vendor
validator rejected a model-authored `qa_status: Passed` because the answer also
carried a MATERIAL finding that requires `Restricted`. No artifact was
accepted, no CP-L10 call occurred, and no matrix or verdict exists. This is a
model-contract miss, not a host, parser, provider, source-delivery or key
defect.

The VMO2 driver made one accepted CP-0 call and one accepted CP-L10 call. It
retained `$4.983815` of reservations and charged `$0.8599520`. The route reached
`COMPLETE`; its proof covers two artifacts and eleven re-anchored citations,
and the readiness, projection and register keys passed. The one pre-run CP-L10
citation key was missed, so the matrix reads `met: 0`, `missed: 1`, the
performed snapshot is incomplete, and no verdict exists. The key is unchanged.

Across both launches, three calls retained `$8.365320` of reservations and
charged **`$1.3507305`**, within the `$24.903680` aggregate maximum. The bounded
retry does not justify continuing to wider sets: CCL still fails the vendor
contract and VMO2 still misses its valid pre-run key. Both pathways remain
`NOT_QUALIFIED`, and Phase 4 stops here pending a new explicit owner decision.

The retained stores and files are:

| Set | Run | Database | Blob root | Capture / driver log |
|---|---|---|---|---|
| `ccl-fy2025-portfolio` | `0e4198da-abb8-4188-8f1e-c5547f3d0dec` | `caos_qualify_0fea5b169d6e4eccb59cd4815302eab5` | `.dev-data/qualification-blobs/caos-qualify-mpp_b9qh` | `run-2026-09-19-b-capture.json` / `run-2026-09-19-b-driver.log` |
| `vmo2-fy2025-portfolio` | `802ae485-54a8-4f4c-96c8-2f1cd9f80d2d` | `caos_qualify_cc7b22d0e73745f3918abf44cbb9ed6e` | `.dev-data/qualification-blobs/caos-qualify-tob16vnx` | `run-2026-09-19-b-capture.json` / `run-2026-09-19-b-driver.log` |

## Phase 4 early-stop record

On 19 September 2026 the two smallest portfolio smoke sets were each launched
once under the pinned `openrouter/openai/high/65536` profile. Four CP-0 calls
charged `1.4463290` in total and retained `11.287080` of reservations. No CP-0
artifact was accepted, no downstream CP-L10 call occurred, no matrix was built,
and no human verdict exists.

The retained diagnostics reproduce as model-contract misses: three answers
contradict the vendor's explicit severity-to-`qa_status` rules, one citation
alters source text and cannot anchor, and another declares the wrong page. The
host transport, parser, source delivery and validator were not defective. The
second set was a deliberate diagnostic exception to the default stop after an
unexpected refusal; after it reproduced the failure, the remaining sixteen
sets were not launched. Both smoke results remain `NOT_QUALIFIED`.

No further Sol/high run is justified. The smallest controlled replacement was
the same official model and `openai` endpoint at reasoning effort `xhigh`,
identity `openrouter/openai/xhigh/65536`, with the unchanged dated `0.000005` /
`0.000015` price. That proposal was subsequently authorized and executed only
for the two unchanged smoke sets, as recorded above. The earlier Sol/high
authorization did not itself authorize that changed identity or spend.

## Observed configuration

The active environment was inspected without printing credentials or complete
database URLs:

| Setting | Observed value |
|---|---|
| provider | OpenRouter |
| model | `openai/gpt-4o-mini` |
| base URL | unset, so CAOS resolves its built-in `https://openrouter.ai/api/v1` |
| endpoint tag | unset |
| reasoning effort | unset |
| API key | present; value not read or recorded |
| `CAOS_MODEL_PRICE` | unset |
| `CAOS_QUALIFY_POSTGRES_URL` | unset |
| `CAOS_BLOB_ROOT` | unset |

The resulting CAOS identity is `openrouter`. That identity is not usable for
qualification: `server/qualification/harness.py` refuses an OpenRouter profile
without an upstream endpoint pin. The qualification configuration below
replaces this observed candidate; it does not mutate or expose the current
credential.

The official OpenRouter catalog confirms the exact model slug
[`openai/gpt-4o-mini`](https://openrouter.ai/openai/gpt-4o-mini), and its
[endpoint catalog](https://openrouter.ai/api/v1/models/openai/gpt-4o-mini/endpoints)
lists the first-party endpoint tag `openai`. Both were accessed on
19 September 2026. The endpoint caps output at 16,384 tokens, below CAOS's
65,536-token request. It is not the qualification model.

## Selected qualification configuration

Use the official OpenRouter slug
[`openai/gpt-5.6-sol`](https://openrouter.ai/openai/gpt-5.6-sol), endpoint tag
`openai`, and reasoning effort `high`. OpenRouter's current
[endpoint catalog](https://openrouter.ai/api/v1/models/openai/gpt-5.6-sol/endpoints)
reports that endpoint healthy, with a 128,000-token completion limit and
support for reasoning effort and response format. The model catalog lists
`high` among its supported reasoning efforts. Both sources were accessed on
19 September 2026.

This is the smallest configuration-only choice that matches CAOS's existing
65,536-token cap and closed JSON transport. It also follows the programme's
model matrix: Sol/high owns money, provider identity and qualification evidence.

The exact configuration and identity are:

```text
OPENROUTER_MODEL=openai/gpt-5.6-sol
OPENROUTER_PROVIDER=openai
OPENROUTER_REASONING_EFFORT=high
--expect-identity openrouter/openai/high/65536
```

`OPENROUTER_BASE_URL` remains unset, selecting CAOS's built-in OpenRouter API
base. Before any authorized run, the environment must resolve to that exact
identity; `scripts/qualify.py` otherwise refuses before spend.

The identity string intentionally names the upstream endpoint, reasoning effort
and output cap rather than the model. The command below pins the model itself,
and `price_from_environment` refuses before execution unless the dated price's
model equals that configured model. The base URL has no equivalent stored
binding, so the command actively removes `OPENROUTER_BASE_URL` instead of merely
assuming it stayed unset.

## Dated conservative price

OpenRouter's model page lists the first-party endpoint at `$2.00` per million
input tokens and `$10.00` per million output tokens. Its official endpoint API
also lists the long-context rate, starting at 272,000 prompt tokens, as `$4.00`
input and `$15.00` output per million, and a `$5.00` long-context cache-write
rate. OpenRouter's
[prompt-caching guide](https://openrouter.ai/docs/guides/best-practices/prompt-caching)
states that GPT-5.6 and later use automatic caching whose writes cost `1.25×`
input. CAOS conservatively treats every request byte as an input token, so the
1,048,576-byte host maximum can cross both the 272,000-token price threshold
and the automatic cache-write threshold. The correct flat price for a
fail-closed CAOS reservation therefore uses the highest applicable input rate:

```text
CAOS_MODEL_PRICE=openai/gpt-5.6-sol,0.000005,0.000015,2026-09-19
```

This deliberately overprices shorter requests rather than risking a reservation
at the wrong tier. Recheck both official pages and replace the dated value if
pricing or endpoint support changes before execution.

## Persistent stores and capture locations

The tracked Compose configuration provides two distinct local services:

- persistent qualification server: `dev-postgres`, database `caos_dev`, host
  `127.0.0.1:55436`, backed by volume `caos-workbench-dev-postgres`;
- isolated test server: `test-postgres`, database `postgres`, host
  `127.0.0.1:55437`, backed by `tmpfs`.

Both services were healthy on 19 September 2026. `make doctor` passed with the
tracked synthetic development configuration, and `make check-postgres` passed
when its probe variable was temporarily pointed at the persistent qualification
URL. No database was created or deleted.

For any later authorized run:

- `CAOS_QUALIFY_POSTGRES_URL` must name the persistent server, never the test
  server. The generated database is `caos_qualify_<uuid>`; record that name in
  the set's `RESULT.md` without recording credentials.
- Set `TMPDIR=$PWD/.dev-data/qualification-blobs` after creating that ignored,
  project-local directory. `scripts/qualify.py` then creates its
  `caos-qualify-*` blob root there; record the resulting absolute path in the
  same `RESULT.md`. The launch wrapper checks `tempfile.gettempdir()` inside
  the process that imports the driver, so Python cannot silently fall back to
  `/tmp` when the governed root is unusable.
- Write the capture beside the result as
  `qualification/<set>/run-YYYY-MM-DD[-suffix]-capture.json`, and record that
  relative filename in `RESULT.md`.
- Preserve the driver's first JSON line, which names the database, blob root,
  dated price, and worst-case call price. These identifiers contain no API key
  or database password. The command below tees all driver output to a sibling
  `run-YYYY-MM-DD[-suffix]-driver.log`; `pipefail` preserves the driver's exit
  status if the process stops after printing that locator but before writing its
  final capture.

## Derived ceilings

With the dated conservative price above, the existing host calculation is:

```text
worst case per call
= 1,048,576 request bytes × 0.000005
  + 65,536 completion tokens × 0.000015
= 6.225920
```

Every proposed run uses `--attempts 2`. The first entry performs the route;
the one permitted re-entry retries only the stopped node because accepted nodes
are reused. The maximum priced calls are therefore `route nodes + 1`, not twice
the route size. Each ceiling below is exactly
`6.225920 × (route nodes + 1)`:

| Qualification set | Nodes | Maximum calls | `--ceiling` |
|---|---:|---:|---:|
| `ba-fy2025` | 3 | 4 | `24.903680` |
| `ccl-fy2025` | 3 | 4 | `24.903680` |
| `ccl-fy2025-covenant-refinancing` | 7 | 8 | `49.807360` |
| `ccl-fy2025-earnings-update` | 5 | 6 | `37.355520` |
| `ccl-fy2025-full-relative-value` | 9 | 10 | `62.259200` |
| `ccl-fy2025-liquidity` | 4 | 5 | `31.129600` |
| `ccl-fy2025-lite-covenant-refinancing` | 4 | 5 | `31.129600` |
| `ccl-fy2025-lite-full-credit-screen` | 9 | 10 | `62.259200` |
| `ccl-fy2025-market-dislocation` | 2 | 3 | `18.677760` |
| `ccl-fy2025-portfolio` | 2 | 3 | `18.677760` |
| `ccl-fy2025-relative-value` | 3 | 4 | `24.903680` |
| `f-fy2025` | 3 | 4 | `24.903680` |
| `save-2024-distressed-restructuring` | 13 | 14 | `87.162880` |
| `save-2024-lite-distressed-restructuring` | 5 | 6 | `37.355520` |
| `vmo2-fy2025` | 3 | 4 | `24.903680` |
| `vmo2-fy2025-deep-research` | 2 | 3 | `18.677760` |
| `vmo2-fy2025-full-deep-research` | 2 | 3 | `18.677760` |
| `vmo2-fy2025-portfolio` | 2 | 3 | `18.677760` |

The aggregate envelope is `616.366080`. The owner authorized applying this
recommendation to all sets on 19 September 2026. That is a maximum bound, not a
spend target or a reason to batch runs: execute sets sequentially, stop on an
unexpected refusal or configuration drift, and never exceed an individual
ceiling. It authorizes one driver launch per set. If a launch is interrupted or
fails after creating its database, reconcile that retained run and its
reservations before deciding how to resume it; never start the set again with a
fresh full ceiling. Each set must retain the `OFFLINE`, `UNVERIFIED`, or
`NOT QUALIFIED` state recorded in its `RESULT.md` until a performed snapshot
and authenticated verdict exist.

The Phase 4 command shape is:

```sh
set -e
set -o pipefail
set_name=replace-with-set-name
run_stamp=2026-09-19-a
ceiling=replace-with-exact-ceiling-from-table
capture="qualification/$set_name/run-$run_stamp-capture.json"
driver_log="qualification/$set_name/run-$run_stamp-driver.log"
test ! -e "$capture" && test ! -e "$driver_log" || {
  echo "capture or driver log already exists; refusing a second launch" >&2
  exit 1
}
blob_parent="$PWD/.dev-data/qualification-blobs"
mkdir -p "$blob_parent"
test -d "$blob_parent" && test -w "$blob_parent"
( set -o noclobber; : > "$driver_log" ) || {
  echo "cannot reserve the driver log; refusing to launch" >&2
  exit 1
}
export CAOS_QUALIFY_POSTGRES_URL=postgresql://caos_dev_admin:local-dev-admin-only@127.0.0.1:55436/caos_dev
env -u OPENROUTER_BASE_URL \
  OPENROUTER_MODEL=openai/gpt-5.6-sol \
  OPENROUTER_PROVIDER=openai \
  OPENROUTER_REASONING_EFFORT=high \
  CAOS_MODEL_PRICE=openai/gpt-5.6-sol,0.000005,0.000015,2026-09-19 \
  TMPDIR="$blob_parent" \
  .venv/bin/python -c \
  'import os, sys, tempfile
expected = os.path.realpath(os.environ["TMPDIR"])
if os.path.realpath(tempfile.gettempdir()) != expected:
    raise SystemExit("governed TMPDIR unavailable; refusing to launch")
from scripts.qualify import main
raise SystemExit(main(sys.argv[1:]))' \
  "qualification/$set_name" \
  --expect-identity openrouter/openai/high/65536 \
  --ceiling "$ceiling" \
  --attempts 2 \
  --capture "$capture" \
  2>&1 | tee -a "$driver_log"
```

## Live loop, 3 to 5 October 2026 (`openai/gpt-6-luna`)

The first live loop on the CZR sets, one set at a time, stopping at the first node that exhausted its guided retries. Every run file is git-ignored under `docs/rebuild/runs/live-2026-10-03/`; each set's own `RESULT.md` carries its table. No set is qualified.

**Model and configuration.** `openai/gpt-6-luna`, reasoning effort `high`, provider pinned to `openai` (identity `openrouter/openai/gpt-6-luna@openai/high/65536`), price `$0.20` in and `$1.00` out per million tokens (`0.0000002,0.000001`, dated 2026-10-02). The test-only OpenRouter adapter sends the effort and pins the provider (F479). Three probes (`P1-luna-high`, `P2-lunapro-flex`, `P3-deepseek-low`) preceded the loop.

**Spend.** Key `caos-qualification`: usage 35.05 of the $50 budget at the end (ledger: 35.053 after FCA2). Every run was started under a ceiling and a stop line on the key's usage.

**Runs, one line each** (modules accepted of the route; keys met of scored; ledger key-usage change):

- R1 earnings-update: complete, keys 2/9 (JSON only; no ledger line).
- R1b: stopped at CP-1B, CITATION_NOT_LOCATED, +$0.29.
- R2: stopped at CP-0, CITATION_NOT_LOCATED (character slips in whole-paragraph quotes), +$0.04.
- R3: complete, keys 2/9, +$0.23.
- R4: stopped at CP-1 (checker false positive, D103), about +$0.12.
- R5: complete, keys 6/9, +$0.30.
- R6: stopped, STORE_UNAVAILABLE (Docker VM disk full).
- R7: complete, keys 5/9, +$0.24.
- L1 liquidity: complete, keys 8/9, +$0.56. LIQ1: complete, keys 5/9, +$0.66.
- C1 covenant-refinancing: stopped at CP-1, +$0.52. C2: stopped at CP-4, HANDOFF_MALFORMED, +$0.84. C3: stopped, EVIDENCE_DEMAND_UNRESOLVED, +$0.83. C4: stopped at CP-4, +$1.28. C5: blocked (CP-0 judged CP-4 DO NOT RUN), keys 7/20, +$1.17. C6: complete, keys 6/20, +$1.49.
- E1 LITE earnings: complete, keys 2/5 (3/5 after K2), +$0.17. E2: complete, keys 1/5, +$0.14.
- LRV1 LITE relative-value: blocked after CP-0 (no TRACE prints), +$0.19. LRV2: complete, keys 5/8, +$0.49.
- LCR1 LITE covenant-refinancing: blocked after CP-0 (CP-L10 DO NOT RUN, incomplete legal chain; F508). LCR2: PROVIDER_UNAVAILABLE at ~195 s. LCR3: PROVIDER_UNAVAILABLE at ~299 s, +$0.30. LCR4: stopped at CP-3C, +$1.01. LCR5: complete, keys 2/7, +$0.67.
- LFCS1 LITE full-credit-screen: stopped at CP-5, +$1.96. LFCS2: PROVIDER_UNAVAILABLE at ~294 s, +$0.46.
- LP1 LITE portfolio: blocked at CP-0 (synthetic mandate), 0/6 keys. `czr-2026q2-portfolio` was never run.
- RV1 FULL relative-value: complete, keys 7/16, +$1.38.
- FCA1 FULL credit assessment: PROVIDER_UNAVAILABLE at CP-1B, +$0.76. FCA2: 11 of 19 accepted, CP-2G Blocked (forecast scope), 7 not run, keys 8/35, +$1.79.

**Host changes that moved results** (decisions in `docs/rebuild/decisions.md`):

- F493 (L2): a near-miss quote is told which line to copy; R3 was the first completed run.
- D101: a figure key is met by an equivalent line (owner, 4 October: a quarter pair suffices). D102: the final check asks for a citation behind each material figure; CP-0 went from 4 to 25 citations (R4).
- D103: vendor fork r12, a register's own heading beats a prose mention (R4's CP-1 false positive). D104: a retry repairs the refused answer; R5 completed with 115 citations, keys 6/9.
- F495 (L3) names a wrong source_id and dropped cells; F496 (L4) asks for the whole answer back and names a quote that runs past its line; F497 (L5) checks CP-0's T8 demand cells at acceptance; F498 splits the legal instruments by clause; F499 (L6) names the line and the code point.
- D105 (excerpts, F500 to F503), D106 (a citation fault refuses the citation, not the answer, F503, F504) and D107 (body markers `[C<n>]`, F505, F506): run C5 onward, with unverified citations counted instead of refusing.
- F507: TRACE prints added to the LITE relative-value set (LRV2 cleared CP-0). F508: the conformed credit agreement and supplements (CP-0 cleared CP-4 and CP-L10 from C6 and LCR3 on).
- F509 (L7) names a register row a cell short or long; F510 (L8) names the owner restrictions CP-5 dropped (LCR5 completed; LFCS was not re-run after F510).

**Provider limit.** PROVIDER_UNAVAILABLE after about 195 to 299 s on large non-streamed calls, in four runs (LCR2, LCR3, LFCS2, FCA1), never billed. This fits a gateway or idle cut near 300 s, not the 420 s call timeout. L9 (F511: stream in the test adapter, `aef7d41`) is unmerged: its first live smoke call was refused PROVIDER_RESPONSE_INVALID (usage missing) and the diagnostic call was not made. Owner, 5 October: "Run without streaming", re-running a dropped module once.

**Open items.** L9 streaming (N145); the portfolio sets' self-declared synthetic mandate labels (owner, 5 October: leave them, record the stop); the CP-2G forecast horizon and base period, an owner input (N144); N129 (a third guided retry: it would likely have accepted C1's CP-1); N133 to N143 (review residue).

## Root-cause pass, 5 October 2026

The 5 October pass on the stops of the live loop above. Branches `claude/rca-prov`, `-case`, `-ops`, `-cp3c` and `-pages`, merged on `claude/rca`; the decisions are F511 to F513 and F520 to F522 in `docs/rebuild/decisions.md` and N144 to N158 in `docs/rebuild/next.md`. Spend figures are OpenRouter `GET /api/v1/generation` `total_cost` summed per run ("billed"); "host" is the run's recorded charges.

**(a) The eleven non-model stops.**

| run | stop | established root cause | fix or note | status |
|---|---|---|---|---|
| LCR2 | PROVIDER_UNAVAILABLE, CP-L10, ~195 s | undecided (see b) | F513 names the class on stderr | open |
| LCR3 | PROVIDER_UNAVAILABLE, CP-3C, ~299 s | undecided (see b) | F513 | open |
| LFCS2 | PROVIDER_UNAVAILABLE, CP-1A, ~295 s | undecided (see b) | F513 | open |
| FCA1 | PROVIDER_UNAVAILABLE, CP-1B, 138 s (attempt 3) | undecided (see b) | F513 | open |
| C5 | BLOCKED after CP-0 (CP-4 DO NOT RUN) | corpus: no conformed credit agreement, only the 4th and 5th amendments | F508 (corpus) | fixed; C6 and later cleared |
| LCR1 | BLOCKED after CP-0 (CP-L10 DO NOT RUN) | the same corpus gap | F508 | fixed |
| LRV1 | BLOCKED after CP-0 (no TRACE prints) | corpus: the LITE relative-value set carried no TRACE prints | F507 | fixed; LRV2 cleared CP-0 |
| LP1 | BLOCKED after CP-0 (CP-L10 DO NOT RUN) | CP-0 reads the allocation use case as needing a real mandate and holdings; the delivered mandate is synthetic (D80) and cannot substitute (vendor hard rule 6 and the source hierarchy) | owner ruled 5 October: leave the labels; real fund mandate and a stated objective channel are N146 and N147 | open, owner |
| FCA2 | CP-2G Blocked (forecast scope) | host gap: the vendor resolves forecast horizon and base period from a command qualifier, bundle declares no default, no upstream module owns them, and the host has no channel to deliver a qualifier; RV1's CP-2G passed only by choosing Restricted with no forecast | none landed; N146 (qualifier channel), N144 | open, owner |
| R4 | CP-1 refused (checker) | the vendor checker bound a register to a prose mention over its own heading (the D103 class) | D103 (fork r12); host-side sibling F520 (`_absent_ids_line` matched `T4.1` inside `T4.10`); three remaining bindings V1 to V3 are N151 | partly fixed; N151 needs owner authorisation |
| R6 | STORE_UNAVAILABLE, CP-2 evidence read | the Docker VM disk reached zero free bytes (`No space left on device` writing about 3 MB of query temp); the store failed closed before CP-2 had an attempt or reservation | F521; no preflight (N150) | fixed in tooling; owner reclaim pending |

**(b) The provider drops.** The four drops are not a fixed 300 s cut: they came at 138, 195, 295 and 300 s, and calls of 334 to 358 s completed in the same runs. The host deadline and client timeout (420 s) are ruled out. The stored evidence cannot name the cause: each dropped attempt has no diagnostic and the captures carry no error class. The leading candidate is an HTTP 200 whose body holds only an error object (OpenRouter commits 200 at provider accept, so a later provider failure arrives that way), then a reset mid-body or a truncated body; none is confirmed. F513 now prints one stderr line for every unanswered call (`call=vendor|raised|deadline`, the class, causes, status, provider error code and type, elapsed seconds; no message, body or prompt). The loop's captures kept stdout only, so run `tests/qualify_openrouter.py ... 2> <label>.err` to catch the next drop. Streaming was validated live in LCR6: the first streamed call (L9) had been refused PROVIDER_RESPONSE_INVALID with usage missing, because OpenRouter repeats `role` on every delta and repeats `finish_reason` in the usage frame, which the library's accumulator concatenates (F512); a live sample (`tests/fixtures/openrouter_sse_sample.txt`) confirmed both. LCR6 then completed 7 streamed calls with no drop, the longest 327 s on 544k prompt tokens. Production does not stream, so it shares the exposure if the cause is a provider failure after a committed 200; how the AI Gateway behaves is unknown (B12). A drop remains a run stop by design: `PROVIDER_UNAVAILABLE` is not a second-attempt code and its reservation is kept (N148 proposes one ledger-gated re-attempt for a drop the provider declared).

**(c) Pricing.** On prompts of 272,000 tokens or more OpenRouter bills a long-context tier. From the keyless `GET /api/v1/models/openai/gpt-6-luna/endpoints` (tag `openai`), Luna's override is $0.20 input, $0.75 output and $0.25 cache write per million tokens, and `gpt-6-sol`'s is $2/$10, with $4/$15 and cache writes at $5 at 272k tokens or more. Measured on 231 of 234 generations: on all 102 calls at 272k tokens or more, host divided by billed was 0.83 to 0.925, because the input is billed at the cache-write rate above the $0.20 pin (worked example, C4: 595,470 prompt tokens at $0.25 plus 11,891 completion tokens at $0.75 is $0.1578, the billed figure, against $0.1310 recorded); on the other 129 it was 1.0 to 1.8. 230 of 231 calls carry a cache-write charge and one read the cache. The reservation still caps the bill (it prices a byte as a token), but the settled ledger can read low by up to about 1.2 times, so stop lines are measured on `/generation`, not on host spend or the wrapper's lagging key-usage delta. Pin rule: the input pin must cover the highest input rate the prompts reach, including cache writes: Luna $0.25 per million (`PRICE_IN=0.00000025`; LCR7 used it). N152 records the finding and N153 the option of prompt caching (a stable shared prefix, which needs a prompt reorder and re-pinned goldens).

**(d) Disk and the compose hazard.** `scripts/qualify.py` makes one database per set and never drops one (DQ-12), and nothing else reclaims them: 28 harness databases held 2.29 GB on a 39.1 GB VM disk with 1.3 GB free, beside 14.1 GB of unused images, 7.5 GB of anonymous volumes and 2.7 GB of unused named volumes. F521 adds `scripts/qualify_reclaim.py`: it lists harness databases and prints `DROP DATABASE` only for one whose every run id a capture names; it never drops. Read-only on the dev server it offered 27 of 28 (2,257,315,041 bytes). The owner reclaim list, none run: `docker volume prune` (about 7.5 GB); `docker volume rm caos-linux-venv caos-linux-uvcache` (about 1.8 GB); `docker builder prune -a` (about 0.97 GB); `docker image prune -a` (up to 14.1 GB, forces rebuilds) or `docker image rm` of named unused tags; the 27 database drops (about 2.26 GB; the proof can no longer be re-run on them); or `colima stop && colima start --disk 80`. A stopped set cannot resume in its own database (N150). Compose hazard: a first LCR7 attempt died STORE_UNAVAILABLE with $0 spent because a gate agent's `docker compose up` from a new worktree re-created the dev Postgres container (the project path had changed). Never run compose while a live run uses the dev store.

**(e) CP-3C (F522).** LCR6's CP-3C was refused three times HANDOFF_INCOMPLETE on T3D.2 row 7 (11 cells under a 12-cell header; the model merged two cells) and a fourth time MALFORMED on a dangling marker. The demand is satisfiable (the columns agree across SKILL.md and the references, and LCR5 passed CP-3C on the same set) and the host's count was right. The F509 line was correct but not actionable: it gave a row number and a cell count, and the model rewrote the row's text three times without fixing its width. F522 names the row by its first cell and quotes how its last three columns read. The vendor's own message names only the padded cell (N154). A live retry has not yet shown that F522 repairs a short row.

**(f) The LCR7 coverage slip and the probes.** LCR7's CP-0 said the conformed credit agreement showed pages 1 to 59 ending at Section 8.16 and marked CP-L10 DO NOT RUN, while the host had delivered all 67 pages (3,981 lines; Section 9.27 included). Rebuilt offline, the prompt equals attempt 1's priced request to the byte (2,416,625). Three direct probes on the 525,849-token prompt (the agreement in its original position twice, moved last once, about $0.13 each) all found 67 pages, Sections 9.23 to 9.27 on page 66, and 9.27 present, so there is no position or context limit at that size and the claim was a slip under the full CP-0 task. Page claims are unreliable elsewhere too (FCA2 said 1 to 65 and LCR6 1 to 67 for a 60-page indenture). Options, nothing built: N156 (state each WHOLE source's pages and lines in the prompt, or hold the answer's page claim to the delivered extent), N157 (a pack-level gate bound, declared through the existing page-map path; the per-source `GATE_SOURCE_BYTES` degrades to a page map and refuses only when not even one line per page fits), N158 (evidence is ordered by a random `source_id`, so the same set is laid out differently each run; a stable order would also serve N153).

**(g) Sol vs Luna.** One sample each on `czr-2026q2` (see its `RESULT.md`): Sol (xhigh, $3/$15 pin) completed with no retries, 0 unverified citations and 148 citations against Luna's 71 with one unverified and one retry, but with fewer distinct figures (CP-0 2 against 7) and fewer keys (2/5 against 3/5; it lost the CP-L10 Adjusted EBITDA key). Billed $2.1923 against $0.1434, about 15 times. Sol calls took 250 to 288 s against 104 to 249 s. Sol at a $3/$15 pin is safe only under the long-context tier; above 272k tokens the billed input is $4 ($5 for cache writes), so only the recorded ledger reads low, the ceiling still holds, and the safe flat pin of $5/$15 does not fit the $14 ceiling. A wrapper key-usage delta read +$1.44 for S1 against $2.1923 billed: usage settles seconds after a run, so measure from `/generation`. Key usage at the end of the pass: 39.08 of the $50 budget.

**(h) Open owner decisions.**
- N146: a qualifier and objective channel in the run-input pin; it blocks FCA's CP-2G and every FULL route through CP-2G.
- N147: the corpus downloads (the full Merger Agreement and commitment letters, the VICI and GLPI leases) and the documents in hand that close CP-0 gaps; LP1's public fund mandate download (the real mandate stays `to_source`).
- N148: one automatic re-attempt of a provider-declared drop.
- N150: a free-space preflight and a resumable stopped set. N151: the vendor checker bindings V1 to V3 and the fixture-substring refusal (vendor edit needs authorisation).
- N153: prompt caching. N154: a vendor width message for short register rows. N155: residue in the F513 trace.
- N156, N157, N158: CP-0 source extent, a pack-level bound, and a stable evidence order.
- The reclaim approval (the list in (d)).
- Whether streaming (F511, F512, validated in LCR6) replaces the 5 October "run without streaming" ruling.

## Owner decisions, 6 October 2026

The 6 October pass: the owner approved the controller's recommendation on every outstanding decision, with the two rulings quoted below. Branch `claude/dec` (decisions D109 to D117, findings F523 to F550 in `docs/rebuild/decisions.md`, residue N159 to N172 in `docs/rebuild/next.md`). Spend figures are the runs' recorded charges at the pinned price (Luna, $0.25 input and $1 output per million tokens); the key's usage after these runs read 43.45. The owner raised the budget cap to $75 on 6 October; the key's own limit stays $50.

**(a) The decisions and what each changed.**

| decision | what it changed | live evidence |
|---|---|---|
| D109 (F523 to F526; N144, N146) | A run pins a command: an optional closed per-module `qualifiers` map and a CP-0 `objective`, in run-input format 3 and its fingerprint. Owner ruling: CP-2G's horizon is derived from the latest reporting period (Q1 to Q3 of year Y: FY(Y) to FY(Y+2); Q4 or FY of Y: FY(Y+1) to FY(Y+3)); the base period is the LTM to the latest quarter (the controller's reading of the vendor card's example). A stated value wins; wire break: `PinRunInput` now requires `qualifiers` and `objective` | FCA4 CP-2G accepted on attempt 3, Restricted: FY2026 to FY2028 and a Q2 2026 LTM base. FCA2's Blocked stop is resolved (N144) |
| D110 (F527 to F530; N148) | A drop the provider declared (a status or an error object, nothing generated) is re-attempted once, a fresh attempt and reservation, gated on the ledger. Never a `deadline`, a client-raised failure, a reset, or a stream failed after content began | not exercised by a declared drop. LCR10's cut after content is the excluded kind (see c) |
| D118 (F551 to F553, F559; N174; amends D110) | A provider's error after content began is a declared drop too when its error object states a 5xx, a 429 or a transient `error_type`, and gets D110's one re-attempt under the same gates. A plain reset or truncation, a 4xx (also a 4xx error object before content, F559) and the `deadline` are still never re-attempted. The ledger records it `declared_after_content` with the stream's generation id (0047), and the qualification capture lists each attempt's drop kind and reservation | LCR10's 502 at CP-L10 is the shape; not yet rerun |
| D111 (F531 to F533; N151, N154) | Vendor fork r13, owner-authorised for these changes: a line opening with a register's ID beats one that only mentions it (V1 to V3), a fixture marker counts only in front matter or alone on a line (V4), and a critical cell a short row left empty is named with the row's width. Build `d8a307a9`, manifest `812ba297` | every run below ran on `d8a307a9`; FCA4's CP-5 retries carried the width message ("the row has 8 cells under a 9-cell header") |
| D112 (F535, F536; N156) | CP-0's P5 page-coverage claims are held to the pages the host delivered: a WHOLE source claimed shorter than delivered is refused `HANDOFF_MALFORMED` with a `host coverage check:` line | no run has stopped on it; not exercised |
| D113 (F538 to F540, F545; N153, N158) | Evidence is ordered by filename then digest and opens every prompt under a run-wide tag, so a run's calls share a prefix | probes, 9 calls: automatic caching wrote the whole prompt each call and read 0; explicit mode with a breakpoint read 0; explicit mode with no breakpoint was 20% cheaper on input ($0.0202 against $0.0251). No saving measured on this provider; the test adapter sends caching off (F545) |
| D115 (F541 to F543; N167, N168) | Three sec.gov files downloaded (the Merger Agreement, the fund's N-PORT schedule, its prospectus and SAI); the fund's files replace the synthetic mandate in the portfolio sets | LP2 COMPLETE on the real fund (c); FCA3's request was 4,033,648 bytes before D116 |
| D116 (F546 to F548; N157, N167, N170, N171) | Every node's request is bounded by its model's context (`CONTEXT_TOKENS`, 1,050,000 for Luna, Luna Pro and Sol; 3 request bytes a token floor), and a node past it shows its largest sources as page maps | FCA3: HTTP 400 on CP-0, nothing billed. N157's fitted CP-0 request (2,866,967 bytes) returned 200 live; FCA4 ran 34 attempts on it |
| D117 (F549, F550; N172) | The model-call deadline 420 to 720 s, the lease 600 to 900 s; store sessions stop idling out; E10 reopens a closed event tail | LCR9 stopped at `call=deadline elapsed=420.0` on CP-3C. Not yet rerun under 720 s |
| D114 | never allocated | none |

**(b) The runs** (scored by `q9/classify.py` against each run's database; run files under `docs/rebuild/runs/live-2026-10-03/`; all on `openai/gpt-6-luna`, effort high, provider pinned to `openai`; recorded charges total $5.3334 over six runs).

| run | set | result | keys | recorded charge |
|---|---|---|---|---|
| FCA3-dec | full-credit-assessment | refused HTTP 400 at CP-0 (context), nothing billed | not scored | $0.00 |
| LP2-dec | lite-portfolio | COMPLETE, 3 attempts, 44 citations | 3/6 | $0.3693 |
| LCR8-dec | lite-covenant-refinancing | BUDGET_CEILING_REACHED at CP-3C (a $3 ceiling, controller error) | 0/7 | $0.5060 |
| LCR9-dec | lite-covenant-refinancing | PROVIDER_UNAVAILABLE at CP-3C, `deadline elapsed=420.0` | 2/7 | $0.5320 |
| LCR10-dec | lite-covenant-refinancing | PROVIDER_UNAVAILABLE at CP-L10, 502 after content | 0/7 | $0.1777 |
| FCA4-dec | full-credit-assessment | 17 of 19 modules, 34 attempts, 454 citations (8 unverified); stopped at CP-5 | 19/35 | $3.7485 |

The set tables are in each set's `RESULT.md`. No set is qualified. FCA4 is the first FULL_CREDIT_ASSESSMENT run past CP-2G.

**(c) What the runs showed.**
- LP2: the portfolio set clears CP-0 over the real fund documents (before D115 the synthetic mandate blocked it). Met keys: Adjusted EBITDA, the N-PORT `6.500%, 2/15/2032` line and the TRACE last trade; missed: the revolver availability line, net assets and the 80% policy sentence (N168).
- LCR10 is the first captured cause of a provider drop: F513's line read `PROVIDER_UNAVAILABLE call=raised class=CutAfterContentError cause=APIError status=- error_code=502 error_type=provider_unavailable elapsed=96.0`, an upstream 502 after content began, 96 s into CP-L10. This is the kind D110 excludes by design (the provider had begun to answer), so the run stopped; the earlier candidate of an error-only `200` (5 October, b) is not what this drop was.
- LCR9: CP-3C ran to the 420 s host deadline; D117 followed. LCR6's CP-3C had taken 327 s.
- CP-5 in FCA4 (4 attempts, HANDOFF_INCOMPLETE x3, HANDOFF_MALFORMED x1), replayed offline through the host's own checks on the four stored answers (`caos_qualify_8b79e0c9…`, read-only; the refusal text is not stored, so the retry lines are the host's current output for each stored answer). **Cause: the model.** Attempt 1 left one cell out of three T5B.3 rows (8 cells under a 9-cell header, rows 3 to 5; the last column read empty). Attempt 2 answered something other than the single JSON object (`HANDOFF_MALFORMED`, the host's transport check). Attempt 3 fixed T5B.3 and shifted two T5B.5 rows (rows 2 and 3, 8 cells under 9) and left citation 17 outside the evidence. Attempt 4 dropped the T5.2 register, wrote a T5B.6 row one cell long and changed citation 17's `source_id` to one that is not a source of the request. Each hint named the row by its first cell, its width against the header's and the columns as read, and the vendor line named the empty critical column with the same widths (F522, F533); no owner-restriction gap was reported (F510 not involved); the host's lines were accurate and actionable, so this is neither a host hint nor a contract defect, and no Nn is added for it. Each retry repaired the tables it was told about and broke another (the F522 pattern, LCR6 CP-3C).

**(d) Open items.**
- N148's cut-after-content exclusion, now seen live (LCR10): a stream the provider fails after it has begun is not re-attempted, so such a drop stops the run. Whether to re-attempt it is the owner's call; the evidence is one drop. **Decided (6 October):** D118 re-attempts it once when the provider declared it (a 5xx, a 429 or a transient `error_type`).
- N167: covered by D116 (a node past its model's bound shows page maps); the effect on CP-0's judgement over withheld lines is unmeasured (N171). N170: declare the contexts of the workspace's ten approved endpoints, the repo default and each `copilot:<model>`; until then each runs with a `CONTEXT_NOT_DECLARED` line, and the 3-bytes-a-token floor is measured, not guaranteed (the N-PORT schedule is 2.54). N172: the 720 s deadline is measured only through the streaming test adapter; production does not stream, so whether the workspace endpoint, the AI Gateway or Copilot cuts an idle request before 720 s is unmeasured, and E10 cannot measure it; `idle_session_timeout=0` on Lakebase is unmeasured too.
- FCA CP-5: the model's register widths; the three guided retries did not repair them. Options for the owner: a further guided retry (N129's class), or a first-attempt instruction to count each register row's cells against its header (N154).
- Key limit: usage read 43.45 after these runs; the owner's cap is $75 as of 6 October, but the key's own limit stays $50, so about $6.55 of key headroom remains until the key is raised.
