# The worker on an analyst's PC (GitHub Copilot, SDK transport)

AI Gateway is disabled in the enterprise workspace (`docs/rebuild/blockers.md` B12), so module calls go to GitHub Copilot (D77) from the one place a Copilot seat lives: the analyst's PC. Only the worker runs there. Lakebase keeps the queue, the attempt ledger and the checkpoints; the Unity Catalog volume keeps every byte by digest; the API and UI run wherever the hosting decision puts them and must approve the same models as the worker. A run advances only while a worker runs.

Status: the SDK transport (`copilot:` models) is built and tested against fakes. It has not yet run against a real seat: section 8 is what to measure first (N185, N177, N184). The `copilot-cli:` transport is designed and deferred (D78, N188); a `copilot-cli:` name is refused at readiness. Nothing on this page has been run on the firm's seat, so treat each command as the intended one and correct it to what actually ran (N187).

| Part | Where |
|---|---|
| Worker (`python -m caos.graph.worker`) and the Copilot runtime | The analyst's PC |
| Store, ledger, checkpoints | Lakebase (unchanged) |
| Sources and artifacts by digest | UC volume `caos_blobs` (unchanged) |
| API and UI | Unchanged by this page |

## 1. Decisions and grants first (owner and administrators)

- **Data:** Compliance confirms that issuer documents may be sent to the Copilot models chosen. Every prompt carries document text.
- **Seat and policy:** the analyst holds a Copilot Business or Enterprise seat, and the organisation's policy enables Copilot CLI (the SDK runs its runtime) and each chosen model.
- **Spend:** Copilot bills AI credits (GitHub lists $0.01 each). The owner sets a GitHub budget for overage. Each run's CAOS ceiling (`CAOS_RUN_CEILING`) still applies.
- **Network from the PC:** HTTPS to the workspace, TLS Postgres to the Lakebase endpoint's host on port 5432, and HTTPS to GitHub's Copilot endpoints.
- **Lakebase:** the analyst's Databricks identity needs a Postgres role on the project. If the app's service principal created `caos_store` and `caos_graph`, it (or a Lakebase administrator) grants:
  ```sql
  GRANT USAGE ON SCHEMA caos_store, caos_graph TO "<analyst's Databricks user name>";
  GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA caos_store, caos_graph TO "<analyst's Databricks user name>";
  GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA caos_store, caos_graph TO "<analyst's Databricks user name>";
  ```
  With no app deployed, the analyst's role creates both schemas on the worker's first start and no grant is needed.
- **Volume:** `READ VOLUME` and `WRITE VOLUME` on `<catalog>.<schema>.caos_blobs` for the analyst.

## 2. Install the worker (once)

1. Install Git, `uv` and the Databricks CLI from IT's approved sources.
2. `git clone <the enterprise repository>`, then `uv sync --locked --no-dev` in the clone; `uv` brings Python 3.13. The SDK package `github-copilot-sdk` is locked with the repository (D77, dependency addendum). On a Windows clone keep Git's `core.autocrlf` as it is: `.gitattributes` marks `vendor/deploy-v/**`, `icm/**`, the goldens and fixtures, and the three source files whose own bytes are pinned (`caos/calculators/cash_flow.py`, `caos/deliverable/render.py`, `caos/deliverable/verify_package.py`) as `-text` (D79), so the verified bytes survive the checkout.
3. `databricks auth login --profile caos --host <workspace URL>` (section 6).

## 3. Provision the Copilot runtime (once)

The worker never lets the SDK find or download a runtime. It starts only a runtime you name and pin, and each call starts its own verified copy of that directory (F591, F596).

1. Download it once, on a machine that may reach GitHub's release site, or have IT do so:
   ```
   uv run python -m copilot download-runtime
   ```
   It prints `Runtime cached at: <path>`. That path (the `copilot-runtime` or `copilot-runtime.exe` wrapper) is the entry. The cache is under `~/Library/Caches/github-copilot-sdk/cli/<version>/prebuilds/<platform>/` on macOS, `~/.cache/...` on Linux and `%LOCALAPPDATA%\github-copilot-sdk\cli\<version>\prebuilds\<platform>\` on Windows.
2. Set `COPILOT_SKIP_CLI_DOWNLOAD=1` permanently, so nothing is downloaded at run time.
3. Copy the entry's whole directory to a place only the analyst and IT can write, if the cache is not that. The runtime loads a native library and assets beside the entry, so the digest covers the directory, not the one file.
4. Set `CAOS_COPILOT_RUNTIME` to the entry's absolute path. It must be a native executable (a `.js`, `.bat`, `.cmd` or `.ps1` entry is refused: it would run an interpreter no digest covers), not a link, and nothing under its directory may be a link or a non-regular file.
5. Compute the pin and set `CAOS_COPILOT_RUNTIME_SHA256` to it.

### The digest

The algorithm (`caos.copilot.runtime_digest`): take every regular file under the entry's directory, recursively; for each, form the line `<path relative to that directory, with / separators>\0<SHA-256 of the file, lower-case hex>\n` (a NUL byte between the two); sort the lines as strings; the digest is the SHA-256, lower-case hex, of the lines joined with no separator. The check at start recomputes it over the copy it made, so the same pin works on every OS, and any change to any file refuses the worker.

The command, using the code's own function (in the clone):

```
uv run --no-sync python -c "import sys; from caos.copilot import runtime_digest; print(runtime_digest(sys.argv[1]))" "<the entry's absolute path>"
```

A machine with no clone can compute the same value with Python 3 alone (this version does not refuse a link, which the worker will; check there are none):

```python
import hashlib, pathlib, sys
root = pathlib.Path(sys.argv[1]).parent
lines = sorted(
    f"{p.relative_to(root).as_posix()}\0{hashlib.sha256(p.read_bytes()).hexdigest()}\n"
    for p in root.rglob("*") if p.is_file()
)
print(hashlib.sha256("".join(lines).encode()).hexdigest())
```

Both were run on a three-file sample directory and printed the same digest (`6183748e...a874c`). Re-compute after any runtime update, and compare against what IT approved.

## 4. The seat, the host and the prices

**Token.** The seat signs in only through `COPILOT_GITHUB_TOKEN`: a fine-grained personal access token with the "Copilot Requests" permission, which the operator creates in their own GitHub settings and sets in the worker's environment only. Readiness refuses any other sign-in (`gh` CLI, a stored login, `GH_TOKEN`). Never paste a token into a document, a ticket, a chat or a shell history; set it from a secret store or the process's environment. The runtime's child process receives only an allow-listed environment, with this token the one credential.

**Host.** `CAOS_COPILOT_HOST` pins the GitHub host the seat must be signed in on (default `github.com`; a data-residency firm sets its own host name, lower case, no scheme). Readiness refuses a seat on any other host. Whether the runtime reports a non-`github.com` host in a form readiness accepts (`<host>` or `https://<host>`) is unmeasured (N184).

**Credit price.** `CAOS_COPILOT_CREDIT_PRICE=<usd>,<YYYY-MM-DD>`: the dollar price of one AI credit and the day you read it, e.g. `0.01,2026-10-07` at GitHub's published rate (docs.github.com, "Models and pricing for GitHub Copilot"). Above zero, not dated in the future. A call's charge is its AI units divided by 10^9 (an assumption N185 measures) times this price.

**Per-token price pin.** Budgets reserve on a per-token price you pin in `CAOS_MODEL_PRICE` as `copilot:<model>[@<effort>],<input per token>,<output per token>,<YYYY-MM-DD>` (dollars per token). Readiness refuses a pin below the listing's own rate:
- the listing's rates are per `batchSize` tokens, in credits: floor per token = `rate / batchSize x credit price x multiplier`;
- the input floor is the highest of the input, cache-read, cache-write (5-minute and 1-hour) and legacy cache rates, in both the default and the long-context tier, because every session asks for the long-context tier; the output floor is the output rate's higher tier;
- the worker prints each model's floors (`price_floor=<input>,<output>`, rounded up, in dollars per token) at start, so pin at or above them;
- a listing that does not state a positive `batchSize`, both tiers each with an `inputPrice` and an `outputPrice`, and a positive finite multiplier is `price_check=unpriced`, and the worker refuses.

The run ceiling must cover one worst-case call: 4 MiB of input at the input pin plus 65,536 output tokens at the output pin (the Copilot output cap). For example at $0.000005 in and $0.00002 out that is 4,194,304 x 0.000005 + 65,536 x 0.00002 = 22.28; set `CAOS_RUN_CEILING` above it.

## 5. Choose the models

Name each model `copilot:<model id>[@<effort>]`, the effort one of `low`, `medium`, `high`, `xhigh`, `max`. The effort is part of the name because the runtime applies a model's default effort when none is sent, and no identity may name an effort the model did not get. A model that takes efforts must be named with one it lists; a model that takes none must be named with none.

- `CAOS_MODEL_ENDPOINT` is the model a run gets when it names none; `CAOS_MODEL_PRICE` prices it (section 4).
- `CAOS_MODEL_CHOICES` is the approved list a run may be pinned to, each entry a dated price in `CAOS_MODEL_PRICE`'s form, joined by `;` (D75, at most 16). Approve only models the firm's policy enables and Compliance cleared. The API must approve the same list.
- Every `copilot:` model is declared at 1,000,000 tokens of context (owner, 2026-10-06; `COPILOT_CONTEXT_TOKENS`), at the long-context tier each session asks for, and its requests are fitted to that, the same in every worker process. The worker prints the seat's long-context `maxPromptTokens` as `context=` and refuses to start when it is below the declared figure or not listed (`context_check=low|unlisted`). A prompt past the seat's real limit is refused after the call (what it bills is unmeasured: N185).
- Every approved model must be offered to the seat, enabled by policy, usable at its pinned effort and priced at or above its listing, or the whole worker refuses (including any gateway model in the same list).
- Never mix: CAOS does not switch a run between transports or models. A run stays on the model it was pinned to.

## 6. Databricks CLI profile, Lakebase and the volume

`databricks auth login --profile caos --host <workspace URL>`, then in the worker's shell (PowerShell shown):

```powershell
$env:DATABRICKS_CONFIG_PROFILE = "caos"
$env:CAOS_LAKEBASE_ENDPOINT = "projects/<project>/branches/production/endpoints/primary"
$env:PGHOST = "<the endpoint's host>"
$env:PGPORT = "5432"
$env:PGDATABASE = "databricks_postgres"
$env:PGUSER = "<your Databricks user name>"
$env:CAOS_BLOB_ROOT = "volume:///Volumes/<catalog>/<schema>/caos_blobs"
```

The worker mints its Lakebase credential from the profile. `STORE_UNAVAILABLE` at start means Lakebase is unreachable (port 5432, profile expired: log in again) or the role lacks the grants in section 1.

## 7. Start and stop

```powershell
$env:COPILOT_SKIP_CLI_DOWNLOAD = "1"
$env:COPILOT_GITHUB_TOKEN = "<set from your secret store; never written here>"
$env:CAOS_COPILOT_RUNTIME = "<absolute path of the entry>"
$env:CAOS_COPILOT_RUNTIME_SHA256 = "<section 3's digest>"
$env:CAOS_COPILOT_HOST = "github.com"
$env:CAOS_COPILOT_CREDIT_PRICE = "0.01,<YYYY-MM-DD>"
$env:CAOS_MODEL_ENDPOINT = "copilot:<model>[@<effort>]"
$env:CAOS_MODEL_PRICE = "copilot:<model>[@<effort>],<in>,<out>,<YYYY-MM-DD>"
$env:CAOS_MODEL_CHOICES = "<more priced entries joined by ;>"   # optional
$env:CAOS_RUN_CEILING = "<above one worst-case call>"
uv run --no-sync python scripts/gateway_smoke.py     # one paid call of a few tokens
uv run --no-sync python -m caos.graph.worker
```

The smoke must print `model=ChatCopilot` and `json_mode=accepted` with the plain call's AI units and charge. Run it once per approved model you rely on.

At start the worker prints on stderr one runtime line, `copilot runtime=<version> host=<host> login=<login>`, then one line per approved model: `copilot <name> offered=y|n policy=<state> usable=y|n efforts=<list> max_prompt_tokens=<n> max_context_window_tokens=<n> context=<n> context_check=ok|low|unlisted price_check=ok|low|unpriced price_floor=<in>,<out> credit_price=<usd>@<date>`. A field it cannot state safely prints `-`. It exits 2 with `PROVIDER_NOT_CONFIGURED` before claiming any run when readiness fails; the stderr line before it says why:

| What you see | What it means and what to do |
|---|---|
| `PROVIDER_NOT_CONFIGURED`, no other line | `CAOS_COPILOT_CREDIT_PRICE` missing, malformed, zero or future-dated; `CAOS_COPILOT_HOST` malformed; `CAOS_COPILOT_RUNTIME` not an absolute path to a file (or a link) or `CAOS_COPILOT_RUNTIME_SHA256` not 64 lower-case hex; the runtime's directory digest differs from the pin (re-compute, section 3); a link or special file under the runtime directory; a `copilot-cli:` name; or the seat is not signed in through `COPILOT_GITHUB_TOKEN`, is signed in on another host, or the token was rejected (no runtime line is printed) |
| `reason=runtime_not_native` | The entry is a script or not this machine's executable format (Mach-O, ELF or PE of this CPU). Use the native wrapper `download-runtime` printed |
| `reason=sdk_not_installed` | `github-copilot-sdk` is not installed here: `uv sync --locked --no-dev` |
| `reason=runtime_unready class=<Name>` | The runtime would not start, timed out (60 s) or answered something the SDK could not parse. The class names what failed; the runtime's own text is never printed. Check the token, the network to GitHub and the policy enabling Copilot CLI |
| model line `offered=n` | The seat does not offer that model id: correct the name or have the organisation enable it. An unoffered approved model refuses the whole worker (N184 asks the owner whether that stays) |
| `usable=n` | The model is disabled by policy, or the effort in its name is not one it takes (`efforts=` lists what it takes; `-` takes none, so name it without `@effort`) |
| `context_check=low` or `unlisted` | The seat lists a long-context prompt budget below the declared 1,000,000 tokens, or none: that model cannot carry the requests CAOS fits to it. Remove it from the approved list or report it (N185) |
| `price_check=low` | The pin is below the listing's floor: raise `CAOS_MODEL_PRICE` to at least `price_floor` (and re-check the run ceiling) |
| `price_check=unpriced` | The listing lacks a batch size, a tier or a rate, so no pin can be checked: report it (N185); do not guess a pin |
| `STORE_UNAVAILABLE` | Lakebase unreachable or the role lacks the grants (section 6) |

Other typed codes arrive on a run, not at start: a call over its reservation parks the run (below); a spent failure bills its charge and is never re-sent.

**Stop.** Ctrl+C (SIGINT; on Windows also Ctrl+Break) stops it after the module in flight. Closing the window is the same orderly stop: the worker has up to 4 s to release its lease before Windows ends it. A lease not released in time expires after 900 s (D117) and the next worker resumes the run with no attempt run twice.

### A run parked for over-reservation

If a call's charge exceeds what the run reserved, the run parks `BUDGET_CHARGE_OVER_RESERVATION`. The park is terminal for that pin: a retry would reserve at the same price and overshoot the same way, so RETRY_RUN is refused (HTTP 500 for that code, N183). To continue:
1. Re-price: raise the model's per-token pin in `CAOS_MODEL_PRICE` (and the API's approved entry) to at least its listing and observed rate, and keep `CAOS_RUN_CEILING` above one worst-case call. Update the credit price too if GitHub's rate moved.
2. Restart the worker so readiness re-checks the pins.
3. Start a successor run of the same case (`supersedes_run_id` names the parked run). It reserves at the new price; the parked run stays as the record. How the Run section offers this is not exercised against a real seat (N185).

## 8. What this does not do

- No run advances while no worker runs, and one worker spends one Copilot seat. Two analysts' workers may run at once (leases); each spends its own seat.
- No in-app chat (Query) until RAI is onboarded.
- Hosting the API and UI with Copilot models is a separate step (N124).
- No `copilot-cli:` models (D78, N188).

## 9. Measure on the firm's seat first (N177, N184, N185)

Nothing below has been measured; every rule in sections 4 and 7 rests on the SDK's types and fakes until it is. Run these with `COPILOT_GITHUB_TOKEN` set, free listing steps first, one line per result in a new `docs/rebuild/runs/copilot-spike-<date>/SUMMARY.md`. Stop and report, rather than work around it, if a candidate is not listed, `authType` is not `env`, the host is not the pin, two `model.call_final_result` events arrive for one smoke, or a unit cannot be reconciled.

1. `get_auth_status`: `authType` is `env`; the exact `host` value (readiness accepts only `<pin>` or `https://<pin>`).
2. `list_models` for each candidate: `policy.state`, `supportedReasoningEfforts`, `defaultReasoningEffort`, `capabilities.limits` (`max_prompt_tokens` under the long-context tier; `max_output_tokens` comes from the typed `client.rpc.models.list`, not `ModelInfo`), `billing.tokenPrices` with `batchSize`, both tiers, `cacheWrite1HPrice`, and `multiplier`. Whether readiness prints `price_check=ok` for the pin you derived.
3. One SDK smoke per candidate with the model pinned: exactly one `assistant.message` and one `model.call_final_result`, both naming the pin, `isByok` false; whether `assistant.usage` arrives and its fields; the whole set of event types a plain smoke emits (the mapping's allow-list is extended only from this); whether `session.auto_mode_resolved` is emitted when pinned; the `serverTools` shape per model family (any answer carrying it is billed and refused until this is decided).
4. The nano-AIU ratio: two calls of different sizes, `totalNanoAiu` on the checkpoint against the credits the seat's usage display and GitHub's usage page state, so 10^9 per credit is measured; the unit of `costPerBatch` and of the listing's batch-size prices; whether `billing.multiplier` applies to token prices; whether the checkpoint's total equals the per-request sum.
5. The seat's billing platform: `totalPremiumRequests` present or not, and which figure the invoice follows.
6. `session_limits.max_ai_credits` accepted by `create_session` (experimental) and the events when exceeded.
7. A 200 KB fill and an over-limit fill: `max_prompt_tokens` under long context, the over-limit answer (`session.error` 400 or 413, `model.call_failure`, or a truncation), whether a failed call carries a checkpoint with `nano_aiu > 0`.
8. How often `assistant.turn_retry` and a `model.call_failure`-then-success occur, and what they bill.
9. A prompt that asks the model to run a shell command or read a file: no `tool.*` or `permission.*` event, no command run, no file read.
10. Whether the firm's policy allows the replaced-empty system message.
11. The effort values each candidate takes.
12. That a runtime complaint (a bad flag through `CAOS_COPILOT_RUNTIME`) reaches nothing on the worker's stderr.
13. Whether the runtime honours the client's `working_directory`, and that the SDK's `ensure_runtime_wrapper` (private, pinned with the SDK at 1.0.16) still behaves as `download-runtime` needs after any SDK update.
14. Then the live proof (N186): the smoke per model, the worker's start on the Windows clone (D79's Windows proof: it verifies the bundle and host prompts there), `/api/health` workers OK, and one qualification run on the cheapest model whose limit fits, within the amount the owner authorises:
    ```
    CAOS_QUALIFY_POSTGRES_URL=<persistent server> CAOS_QUALIFY_BLOB_ROOT=<kept directory> \
    CAOS_MODEL_ENDPOINT=copilot:<model> CAOS_MODEL_PRICE=copilot:<model>,<in>,<out>,<date> \
    uv run python scripts/qualify.py qualification/ccl-fy2025-market-dislocation \
      --expect-identity copilot/<model>/none/65536 --ceiling <authorised amount>
    ```
    (the identity's effort segment is the pinned effort, `none` when the name has none). Record per node the code, the charge and the largest prompt's tokens against the model's limit in `qualification/PROVIDER_RUNBOOK.md`.

If an external resource is missing (port 5432 blocked, Lakebase role absent, Copilot CLI policy off), add B13 to `docs/rebuild/blockers.md` with the exact command and error, and correct this runbook to the commands that actually ran.
