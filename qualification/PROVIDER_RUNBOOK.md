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
