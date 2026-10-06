# Copilot SDK Adapter (with a Copilot CLI fallback) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **The owner said "Do not use agents" on 2026-09-24: ask before dispatching any subagent; without a yes, execute inline with superpowers:executing-plans.**

**Goal:** Let a module of a governed run be answered by GitHub Copilot, behind the existing single model factory, on the machine the worker runs on (including an analyst's Windows PC). The Copilot SDK is the main transport and the Copilot CLI is a fallback, and every invariant the AI Gateway path holds stays unchanged.

**Architecture:** A model named `copilot:<model>[@<effort>]` or `copilot-cli:<model>[@<effort>]` makes `caos.models.chat_model` return `ChatCopilot`, a LangChain chat model. Each call runs one isolated Copilot session: no tools, no memory, no compaction. Both transports deliver the runtime's session events in the same wire form, and one mapping turns them into the `AIMessage` that `ChatCompletions` already prices, bounds and refuses. CAOS stays the orchestrator (LangGraph, the attempt ledger, the run's model pin), and Copilot is only the model. Lakebase keeps the queue, the ledger and the checkpoints, and the UC volume keeps the bytes. Only the worker process moves to the PC, where the Copilot seat is.

**Tech Stack:** Python 3.13 · `github-copilot-sdk==1.0.16` (new, D77) · the IT-installed `copilot` CLI (fallback, D78) · LangChain core · psycopg on Lakebase · Databricks SDK (unchanged).

**Spec:** the **Design** section below, which extends spec §3 (`docs/rebuild/2026-09-22-caos-databricks-spec.md`: the one model factory, D7, D8) and D75 (a run is pinned to its model and price, `docs/rebuild/decisions.md`).

**Base:** `origin/rebuild/databricks`, where this plan merged as `dfd64ad` and the documentation was then brought in line with it (D77, B12, and the goal reissued as D76's addendum). The owner's local `rebuild/databricks` was 27 commits behind on 2026-10-01, so fetch first. Work happens in worktree branches, and the owner merges. The goal file `docs/rebuild/2026-09-22-goal.txt` runs this plan.

---

## Why this shape

- **What the workspace allows.** AI Gateway is disabled in the enterprise workspace; Lakebase, UC volumes and compute are enabled. GitHub Copilot is the AI layer the firm already approves, while RAI (the firm's gateway) needs use-case onboarding first.
- **What was rejected.** The proposed alternative was Copilot CLI as orchestrator, with one skill per module and Delta over ODBC. It would turn run order, exactly-once execution, the canonical envelope and anchored citations from code into instructions. This plan keeps CAOS in charge and swaps only the model transport, behind the seam that already exists: `CompletionProvider` → `ChatCompletions` → a LangChain `BaseChatModel`.
- **The worker can already move.** `python -m caos.graph.worker` runs as its own process: it polls Lakebase, claims runs by lease and writes under the lease. The API serves without it (with `CAOS_WORKER_IN_PROCESS` unset it reports `WORKERS_ABSENT` until a worker beats). The store (an SDK-minted Lakebase token) and the blobs (the SDK Files API) both work from a PC.
- **Why a CLI fallback.** The SDK pip package, or the runtime it downloads, may not be approved on a managed PC. The `copilot` binary IT already installed has a documented prompt mode that prints the same session events as JSON lines (`--output-format json`, added 2026; official changelog). The fallback is a transport chosen by name, not an automatic retry, for the reason in Design 10.

## Design (the spec this plan implements)

> Amended by **Re-spec of 2026-10-06** at the end of this file: it supersedes Design 3 (the session posture), 4 (the reply mapping), 5 (the charge, now in AI units), 6 (errors against the schema), 7 (auth and readiness) and 10 (the CLI's flags and environment), adds the D116 context declaration for Copilot models and R7 (the runtime's stderr), and restates Tasks 2–7. Revision 2 closed an adversarial review's findings. Read it before building.

1. **Name grammar.** A Copilot model is `<platform>:<model>[@<effort>]`:
   - `<platform>` is `copilot` (the SDK) or `copilot-cli` (the CLI fallback);
   - `<model>` is the runtime's own id, matching `[a-z0-9][a-z0-9.-]{0,127}`;
   - `<effort>` is one of `low|medium|high|xhigh|max`.

   The effort is part of the name for a specific reason: when none is sent, the runtime silently applies the model's default effort, and no identity may name an effort the model did not receive (AR-15). A name that claims a Copilot platform and does not parse is refused `PROVIDER_NOT_CONFIGURED`; it is never read as an endpoint. The name flows unchanged through `CAOS_MODEL_ENDPOINT`, `CAOS_MODEL_PRICE`, `CAOS_MODEL_CHOICES`, the run pin (`runs.price_model`, migration 0043), the wire (`Id`, a length bound only) and `producer_identifier`, which allows `:`, `.`, `@` and `-`.
2. **Dispatch and identity.**
   - `chat_model(endpoint=name)` returns `ChatCopilot(model=name)` for a Copilot name, and `ChatDatabricks` otherwise.
   - `identity_of` returns `<platform>/<model>/<effort|none>/65536`, so a model served through Copilot qualifies separately from the same model on a gateway, and the CLI separately from the SDK (D8).
3. **SDK session posture.** Each call gets one `CopilotClient(mode="empty", base_directory=<fresh private temp dir>, log_level="none")` with one session, and the client, session and directory are all removed when the call ends. Empty mode turns off custom instructions, skills, memory, the session store, plugins, telemetry and environment context. The session sets:
   - `available_tools=[]`: no built-in, MCP or custom tool, so no shell, file or web access (invariant 1);
   - `system_message={"mode": "replace", "content": ""}`: the prompt is the whole request, as on the gateway;
   - `infinite_sessions={"enabled": False}`: otherwise on by default, and it would compact evidence;
   - `context_tier="long_context"`: the 1M-token tier, because CP-0 sends whole filings and the default tier is about 200K (D29);
   - `model_capabilities.limits.max_output_tokens = MAX_COMPLETION_TOKENS`;
   - `streaming=False`.

   `response_format` is not sent: the canonical executor validates the envelope it asked for (invariant 9), and the request is still priced as though it carried it.
4. **One reply mapping for both transports.** A call's events (`{"type": ..., "data": {...}}`, camelCase fields, the runtime's own schema) become one `AIMessage`. A finish reason is stated only when the call was exactly the one asked for:
   - exactly one `assistant.usage` and one `assistant.message`;
   - the usage names the pinned model and the pinned effort;
   - it is not auto-routed, not BYOK, and offers no tools;
   - the message has no tool request and no server tool (a server tool can mean a second "advisor" model);
   - no truncation or compaction event occurred.

   Otherwise no finish reason is stated, and `ChatCompletions` bills the call and refuses it `PROVIDER_RESPONSE_INVALID` (F34). Finish reasons are read into the one vocabulary `provider.finish_refusal` knows: `end_turn` and `stop_sequence` become `stop`, `max_tokens` becomes `length`, and `refusal` becomes `content_filter`. Any other value passes through and is refused there.
5. **Charge.**
   - Usage tokens are input + cache read + cache write, all at the dated **input** rate, plus output at the **output** rate. The owner prices a Copilot model at `max(input, cache write)` per token. Summing may overstate cached reads, but the charge is never below GitHub's bill (1 AI credit = $0.01; GitHub publishes per-model dollar rates per 1M tokens).
   - A `copilot-cli:` request is priced and bounded with `CLI_OVERHEAD_BYTES` (64 KiB) added, because the CLI wraps the prompt in a system prompt of its own.
   - The bound `ChatCompletions._charge` applies stays: prompt tokens no more than request bytes, and output no more than `MAX_COMPLETION_TOKENS`.
6. **Errors.**
   - A `session.error` is raised as `CopilotStatusError(OpenAIError)` carrying only its status, so `ChatCompletions` maps it the way it maps a gateway status: `NEVER_RETRIED` gives `PROVIDER_CALL_INVALID`, a 429 is re-sent under the same reservation, and anything else gives `PROVIDER_UNAVAILABLE`.
   - A timeout aborts the session or kills the CLI and raises `TimeoutError`. That, a missing CLI, and a CLI exiting non-zero with no event are all indeterminate.
   - No error text travels. The CLI's stderr is never read.
7. **Readiness.** At start, the worker refuses `PROVIDER_NOT_CONFIGURED` (exit 2, before claiming any run) unless the following hold:
   - every `copilot:` model is offered to the GitHub identity signed in on this machine, is enabled by its organisation's policy, and is pinned at an effort it takes (or at none only if it takes none);
   - for any `copilot-cli:` model, a `copilot` executable is on `PATH`.

   The worker prints each SDK model's `max_prompt_tokens`. No runtime starts when no approved model is Copilot's.
8. **Where things run.** The worker runs on the PC, signed in to Copilot, with a Databricks CLI profile that reaches Lakebase and the volume. The API and UI stay wherever the hosting decision puts them (pending). The API and the worker must approve the same models, so that runs are pinned to Copilot models.
9. **Dependency.** `github-copilot-sdk==1.0.16` (MIT, released 2026-09-30). It brings `python-dateutil`, `pydantic>=2.11` and `httpx>=0.24`, all already locked. Its runtime comes from GitHub Releases, checked against the release's checksums. On the PC the runtime is provisioned once (`python -m copilot download-runtime`), and `COPILOT_SKIP_CLI_DOWNLOAD=1` stops any download at run time. `caos/copilot.py` imports the SDK only inside the SDK transport and readiness, so a PC that cannot install the package runs `uv sync --locked --no-install-package github-copilot-sdk` and uses `copilot-cli:` models.
10. **The CLI fallback (D78).**
    - **Invocation.** A `copilot-cli:` call runs the `copilot` executable found on `PATH` in prompt mode:
      - the prompt on **stdin**, because a module's prompt runs to megabytes, far past a Windows command line's 32,767 characters;
      - `--output-format json`, which prints the session events as JSON lines that the Design 4 mapping reads;
      - `--available-tools=` (no tool), `--no-custom-instructions`, `--no-auto-update`, `--stream off`, `--context long_context`, `--model` and `--reasoning-effort`.
    - **Isolation.** It runs with a private `COPILOT_HOME` that doubles as its working directory and is removed afterwards, so none of the analyst's extensions, skills, plugins, MCP configuration, memory or trusted folders reaches the call. The `GITHUB_COPILOT_PROMPT_MODE_*` opt-ins are never passed on.
    - **Chosen by name only.** It is never an automatic fallback, for two reasons. No CLI flag replaces Copilot's own system prompt, so its answers are a different execution profile. And a run pinned to one transport never switches (F468).
    - **Process start.** The CLI is started with `asyncio.create_subprocess_exec`. Bandit's subprocess checks do not cover asyncio's process API (verified on 2026-10-01: zero findings for that call). The call therefore carries no finding and needs no suppression. To make up for the scanner's blind spot, its arguments are fixed flags plus a model id matched against `[a-z0-9.-]` (never the prompt), it uses no shell, and Task 4 requires an adversarial review.
    - **Known gap.** The CLI caps output at the model's own limit, not `MAX_COMPLETION_TOKENS`. An answer past 65,536 tokens is billed as unknown and refused, as it would be on the gateway.

## Gating risks (Task 1 measures them before any code)

> Task 1 ran on 2026-10-06 and stopped at three of these (auth in isolation, usage semantics, CLI JSON lines). The re-spec below replaces the mapping and charge rules they rested on, and section R6 is the checklist for the firm-seat spike (N177).

| Risk | Why it matters | Stop rule |
|---|---|---|
| Prompt limit | D29 sized requests for a 1M-token model; CP-0 sends whole filings (a 1.92 MB 10-K went in one request). Copilot's default tier is about 200K, and its 1M tier is selected per session. | Record each candidate's `max_prompt_tokens` under `long_context`. If a candidate rejects the tier, record it; the owner decides. |
| Auth in isolation | Empty mode does not fall back to `~/.copilot`, and the CLI runs under a fresh `COPILOT_HOME`. A signed-in user may not be visible to either. | If neither the signed-in user nor `COPILOT_GITHUB_TOKEN` authenticates a transport, stop and report. |
| Empty replaced system message (SDK) | GitHub warns that replace "removes guardrails", and firm policy may forbid it. | If refused, stop and report (owner decides). |
| Usage semantics | The charge assumes reasoning tokens are inside `outputTokens`. | Any `reasoningTokens > outputTokens`: stop. |
| Hidden prompt overhead | Prompt tokens may not exceed request bytes. | SDK smoke `inputTokens` > 160: stop. CLI smoke `inputTokens` > 32,768 (half the 64 KiB allowance): stop. |
| One call per prompt | The mapping refuses two `assistant.usage` events, and prompt mode may make auxiliary calls (for example, titles). | More than one `assistant.usage` on a plain smoke, on either transport: stop and report. |
| CLI JSON lines | The fallback reads `assistant.usage` from stdout. | If stdout lacks `assistant.usage` with `inputTokens` and `outputTokens`: stop. |
| CLI flags | `_CLI_FLAGS` uses spellings from the changelog. | Record `copilot --help`; correct `_CLI_FLAGS` to its spelling in Task 4. If no spelling offers no tools (`availableToolCount` 0), stop. |

## Global Constraints

- Python `>=3.13,<3.14`. Use `uv run` for every tool. No `requirements.txt`.
- All gates exit 0 and none is loosened (project `CLAUDE.md`).
  - Per task: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy caos scripts tests`, and the task's tests.
  - Before each PR: the full gate list in `CLAUDE.md`, including:
    - `CAOS_REQUIRE_POSTGRES=1 uv run pytest -n auto -m "not live_provider"` (coverage ≥ 80%);
    - `scripts/check_tested.py`, `scripts/check_vocabulary.py`, `scripts/check_gate_config.py`;
    - complexipy ≤ 15, `jscpd --threshold 3`, `pip-audit --strict`, bandit with the floor, `uv lock --check`.
- Ruff selects `ANN` (no bare `Any` on arguments: use `object` for `**kwargs`), `BLE` (no blind `except`), `TRY`, `C901` ≤ 10 and `PLR0913` ≤ 5 arguments. mypy is strict.
- Add no new suppression (`noqa`, `type: ignore`, `nosec`, `pragma`): `tests/gate_baseline.json` may only fall. Bandit fails on any finding (`scripts/scan_floors.py`).
- Every module-level public function and class is named by a test that imports it from its own module (`scripts/check_tested.py`).
- One term per concept (`CONTEXT.md`). Never use `pipeline`, `workflow`, `chunk`, `fragment`, `passage`, `corpus`, `deal`, `benchmark`, `golden_set` or `ready_set` in identifiers.
- Typed refusals only. Never `str(exc)`. Never print or log a prompt, an answer, an error message, the CLI's stderr, a path under a user's home, or a credential. A model name, a count and a status code are host facts.
- Money is `Decimal`, never `float` (invariant 7). No model call without a reservation (invariant 8).
- A new dependency needs a `Dn` entry in `docs/rebuild/decisions.md` (D77 here).
- IDs: **D77** (the direction) and **B12** (the gateway disabled) were recorded when the build was initialised on 2026-10-01; Task 2 adds "D77, addendum". Still free: **D78, D79, N121–N125, B13**. Another session may take some meanwhile, so re-read the tail of each log before writing.
- PRs stay ≤ 800 changed lines (`docs/**`, `vendor/**` and lockfiles excluded; check with `uv run python scripts/check_pr_size.py <base>`). Ship three stacked PRs:
  - **Copilot 1/3**, the SDK transport (Tasks 2–3);
  - **Copilot 2/3**, the CLI fallback (Task 4);
  - **Copilot 3/3**, the worker on the PC (Tasks 5–7).
- Task 4's review is adversarial and security-focused: the `adversarial-reviewer` skill inline, or `mx-adversary` if the owner allows agents. The reason is that bandit does not scan its process start.
- Make paid calls (Task 1, Task 7) only within an amount the owner authorises for that task, in chat or in the goal's VALUES line (`docs/rebuild/2026-09-22-goal.txt`, default none). Copilot bills AI credits at $0.01 each.
- End every commit message with the session's attribution trailer.

## File structure

| File | Responsibility | Task |
|---|---|---|
| `caos/copilot.py` (create) | The Copilot transports: name grammar, the shared reply mapping, `ChatCopilot`, the SDK call, the CLI call, readiness | 2, 3, 4, 5 |
| `caos/models.py` (modify) | `identity_of`, `chat_model` dispatch, `ChatCompletions.request_bytes` allowance, docstring | 3, 4 |
| `caos/provider.py` (modify) | Docstring names both transports | 3 |
| `pyproject.toml`, `uv.lock` (modify) | `github-copilot-sdk==1.0.16` | 2 |
| `caos/graph/worker.py` (modify) | Readiness at start; console stop signals | 5, 6 |
| `scripts/gateway_smoke.py` (modify) | Accepts `ChatCopilot` on a real transport only | 5 |
| `scripts/qualify.py` (modify) | Docstring: the Copilot identity examples | 5 |
| `caos/evidence/pdf.py` (modify) | No `resource` module on Windows | 6 |
| `.gitattributes` (modify) | Byte-verified trees never converted | 6 |
| `tests/test_copilot.py` (create) | Grammar, mapping, `ChatCopilot` through `ChatCompletions`, both transports, dispatch, readiness, smoke | 2, 3, 4, 5 |
| `tests/test_pc_worker.py` (create) | Stop signals, the `resource` guard, byte pins | 6 |
| `docs/COPILOT_WORKER.md` (create) | The analyst-PC runbook, the CLI fallback included | 7 |
| `docs/rebuild/decisions.md`, `next.md`, `ENTERPRISE_HANDOFF.md`, `CLAUDE.md`, `docs/DEPLOYMENT.md` (modify) | D77–D79, N121–N125, pointers | 2, 4, 6, 7 |

---

### Task 1: Measure the Copilot runtime and CLI (spike; no repository code)

**Files:**
- Create (git-ignored): `docs/rebuild/runs/copilot-spike-<YYYY-MM-DD>/copilot_spike.py`, `facts.jsonl`, `help.txt`, `SUMMARY.md`

**Interfaces:**
- Consumes: nothing.
- Produces: `SUMMARY.md`, which D77 and D78 cite. It records the exact model ids, the auth method that works for each transport, each model's prompt limit and prices, the CLI flag spellings and the CLI overhead tokens.

Run it on the machine the worker will run on (the analyst PC), because model policy and auth are the firm's. Any machine with a Copilot seat can pre-check the mechanics. **Spend:** about 15 small calls plus two 200 KB prompts on the cheapest listed model. Ask the owner for **$1.00** of Copilot credits before Step 3.

- [ ] **Step 1: Write the spike script**

```python
"""Copilot SDK and CLI facts for the CAOS adapter (plan Task 1). Prints counts,
ids and flags; never a prompt, an answer or an error message."""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from copilot import CopilotClient, ModelCapabilitiesOverride, ModelLimitsOverride

SMOKE = "Reply with the single word OK."
USAGE_KEYS = (
    "model", "inputTokens", "cacheReadTokens", "cacheWriteTokens", "outputTokens",
    "reasoningTokens", "finishReason", "maxOutputTokens", "maxPromptTokens",
    "reasoningEffort", "isAuto", "isByok", "availableToolCount",
)


def emit(fact: dict) -> None:
    print(json.dumps(fact, default=str), flush=True)


def summarise(wire: list[dict], label: str, prompt: str, started: float) -> None:
    for event in wire:
        kind, data = event.get("type"), event.get("data") or {}
        if kind == "assistant.usage":
            emit({label: "usage", **{key: data.get(key) for key in USAGE_KEYS},
                  "providerCallId": bool(data.get("providerCallId")),
                  "apiCallId": bool(data.get("apiCallId"))})
        elif kind == "assistant.message":
            emit({label: "message", "answer_bytes": len(str(data.get("content", "")).encode()),
                  "toolRequests": bool(data.get("toolRequests")),
                  "serverTools": data.get("serverTools") is not None})
        elif kind == "session.error":
            emit({label: "error", "errorType": data.get("errorType"),
                  "statusCode": data.get("statusCode")})
    emit({label: "call", "prompt_bytes": len(prompt.encode()),
          "seconds": round(time.monotonic() - started, 1),
          "types": sorted({str(event.get("type")) for event in wire})})


async def listed() -> None:
    with tempfile.TemporaryDirectory(prefix="caos-spike-") as home:
        async with CopilotClient(mode="empty", base_directory=home, log_level="none") as client:
            status = await client.get_auth_status()
            emit({"auth": status.isAuthenticated, "auth_type": status.authType})
            for info in await client.list_models():
                prices = info.billing.token_prices if info.billing else None
                emit({
                    "id": info.id,
                    "policy": info.policy.state if info.policy else None,
                    "efforts": info.supported_reasoning_efforts,
                    "default_effort": info.default_reasoning_effort,
                    "max_prompt_tokens": info.capabilities.limits.max_prompt_tokens,
                    "max_context_window_tokens": info.capabilities.limits.max_context_window_tokens,
                    "batch_size": prices.batch_size if prices else None,
                    "input_price": prices.input_price if prices else None,
                    "cache_write_price": prices.cache_write_price if prices else None,
                    "output_price": prices.output_price if prices else None,
                    "long_context_prices": bool(prices and prices.long_context),
                })


async def sdk_call(model: str, effort: str | None, prompt: str) -> None:
    wire: list[dict] = []
    ended = asyncio.Event()

    def heard(event) -> None:
        wire.append(event.to_dict())
        if wire[-1].get("type") in ("session.idle", "session.error"):
            ended.set()

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="caos-spike-") as home:
        async with CopilotClient(mode="empty", base_directory=home, log_level="none") as client:
            async with await client.create_session(
                model=model,
                reasoning_effort=effort,
                available_tools=[],
                system_message={"mode": "replace", "content": ""},
                infinite_sessions={"enabled": False},
                context_tier="long_context",
                model_capabilities=ModelCapabilitiesOverride(
                    limits=ModelLimitsOverride(max_output_tokens=65536)
                ),
                working_directory=home,
                streaming=False,
            ) as session:
                session.on(heard)
                await session.send(prompt)
                await asyncio.wait_for(ended.wait(), timeout=240)
    summarise(wire, "sdk", prompt, started)


def cli_call(model: str, effort: str | None, prompt: str, flags: list[str]) -> None:
    executable = shutil.which("copilot")
    arguments = [executable, "--model", model, *flags]
    if effort:
        arguments += ["--reasoning-effort", effort]
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="caos-spike-") as home:
        done = subprocess.run(
            arguments, input=prompt.encode(), capture_output=True, cwd=home,
            env={**os.environ, "COPILOT_HOME": home}, timeout=240,
        )
    wire = [json.loads(line) for line in done.stdout.decode("utf-8", "replace").splitlines()
            if line.lstrip().startswith("{")]
    emit({"cli": "exit", "code": done.returncode, "stderr_bytes": len(done.stderr)})
    summarise(wire, "cli", prompt, started)


def filler(size: int) -> str:
    """Neutral text of about `size` bytes; never a document."""
    line = "The quick brown fox jumps over the lazy dog, line {n}.\n"
    return "".join(line.format(n=n) for n in range(size // 50 + 1))[:size] + "\n" + SMOKE


if __name__ == "__main__":
    match sys.argv[1:]:
        case ["list"]:
            asyncio.run(listed())
        case ["sdk", model, *effort]:
            asyncio.run(sdk_call(model, effort[0] if effort else None, SMOKE))
        case ["sdk-fill", model, size]:
            asyncio.run(sdk_call(model, None, filler(int(size))))
        case ["cli", model, effort, "--", *flags]:
            cli_call(model, None if effort == "none" else effort, SMOKE, flags)
        case _:
            sys.exit("usage: list | sdk <model> [effort] | sdk-fill <model> <bytes>"
                     " | cli <model> <effort|none> -- <flags...>")
```

- [ ] **Step 2: List what this identity is offered, and the CLI's flags (free)**

Sign in first by running the IT-installed CLI once (`copilot`, then `/login`). Then run, with `S=docs/rebuild/runs/copilot-spike-<date>`:

```bash
uv run python $S/copilot_spike.py list | tee -a $S/facts.jsonl
copilot --version > $S/help.txt && copilot --help >> $S/help.txt
```

- Expected output: `{"auth": true, ...}` followed by one line per model.
- If `auth` is false, set `COPILOT_GITHUB_TOKEN` (a fine-grained token with the "Copilot Requests" permission) in this shell and run again. Record which method worked; Task 7's runbook keeps only that one.
- In `help.txt`, find the spellings for:
  - the JSON output format;
  - offering no tools (`--available-tools=` or similar);
  - `--no-custom-instructions`, `--no-auto-update`, `--stream` and `--reasoning-effort`;
  - the context tier (`--context` and its values).

  Write them into `SUMMARY.md`.

- [ ] **Step 3: One smoke call per candidate, per transport (owner-authorised spend)**

The candidates are the cheapest listed GPT-6 Luna id, Claude Sonnet 5.5, and Claude Opus 5.5 at the effort the owner wants, using the exact ids from Step 2. Replace the CLI flags below with Step 2's spellings:

```bash
uv run python $S/copilot_spike.py sdk <luna-id> | tee -a $S/facts.jsonl
uv run python $S/copilot_spike.py sdk <opus-id> high | tee -a $S/facts.jsonl
uv run python $S/copilot_spike.py cli <luna-id> none -- \
  --output-format json --available-tools= --no-custom-instructions --no-auto-update \
  --stream off --context long_context | tee -a $S/facts.jsonl
uv run python $S/copilot_spike.py cli <opus-id> high -- \
  --output-format json --available-tools= --no-custom-instructions --no-auto-update \
  --stream off --context long_context | tee -a $S/facts.jsonl
```

Expected for every call:
- exactly one `usage` line, whose `model` equals the id asked for;
- `isAuto` false or null, and `reasoningEffort` equal to the effort sent;
- `availableToolCount` 0 or null;
- `reasoningTokens` null or ≤ `outputTokens`;
- `toolRequests` and `serverTools` false.

Per transport:
- SDK: `inputTokens` ≤ 160, and `maxOutputTokens` 65536 (or the model's own lower cap, recorded).
- CLI: exit 0; record `inputTokens`, which is the CLI's own overhead.

Apply the stop rules in **Gating risks**. If the CLI's `assistant.usage` is missing from stdout, stop: the fallback has nothing to bill from.

- [ ] **Step 4: Cache semantics and the over-limit behaviour (cheapest model, SDK)**

```bash
uv run python $S/copilot_spike.py sdk-fill <luna-id> 200000 | tee -a $S/facts.jsonl
uv run python $S/copilot_spike.py sdk-fill <luna-id> 200000 | tee -a $S/facts.jsonl
uv run python $S/copilot_spike.py sdk-fill <luna-id> <5 × its max_prompt_tokens> | tee -a $S/facts.jsonl
```

Record:
- whether the second call reports `cacheReadTokens > 0`, and whether `inputTokens` already includes them (the D77 sum rule is conservative either way);
- whether the over-limit prompt gets an `error` with `statusCode` 400 or 413 (not billed), or a truncation event (billed). The adapter refuses both; the runbook states which happens.

- [ ] **Step 5: Summarise**

In `SUMMARY.md`, add:
- one line per gating risk (the value measured and the verdict);
- the auth method that works per transport;
- each candidate's id, `max_prompt_tokens` under `long_context`, efforts and per-token prices;
- the CLI flag spellings;
- the CLI overhead tokens.

Nothing is committed, because the folder is git-ignored.

---

### Task 2: The names and the shared reply mapping

**Files:**
- Create: `caos/copilot.py`, `tests/test_copilot.py`
- Modify: `pyproject.toml` (dependencies), `uv.lock`, `docs/rebuild/decisions.md` (D77)

**Interfaces:**
- Consumes: `caos.provider.TIMEOUT_SECONDS`; `caos.refusals.Refusal`, `RefusalCode`. No SDK import.
- Produces (later tasks rely on these exact names):
  - `PLATFORM = "copilot"`;
  - `Event = Mapping[str, Any]`, one session event in wire form;
  - `@dataclass(frozen=True, slots=True) class CopilotModel: platform: str; name: str; reasoning_effort: str | None`;
  - `def parsed(model: str) -> CopilotModel | None`, which raises `Refusal(PROVIDER_NOT_CONFIGURED)` on a malformed Copilot name;
  - `class CopilotStatusError(OpenAIError)` with `.status_code: int | None`;
  - `Ask = Callable[[str, CopilotModel, float], Sequence[Event]]`;
  - `class ChatCopilot(BaseChatModel)` with `model: str`, `timeout: float = TIMEOUT_SECONDS` and `ask: Any = None`;
  - `def reply_message(seen: Sequence[Event], target: CopilotModel) -> AIMessage`;
  - `def _data(seen: Sequence[Event], kind: str) -> list[Mapping[str, Any]]` (private; Task 4 uses it);
  - `def ask_copilot(prompt: str, target: CopilotModel, seconds: float) -> list[Event]`, a stub raising `NotImplementedError` that Task 3 implements in the same PR.

- [ ] **Step 1: Check the dependency (already locked)**

`github-copilot-sdk==1.0.16` was added to `pyproject.toml` and `uv.lock` when the build was initialised (D77, addendum: dependency), with the documentation, so the build starts from a lock `pip-audit` has cleared (F474). Do not edit either file.

Run: `uv run python -c "import copilot; print('sdk ok')"`

Expected: `sdk ok`.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_copilot.py`:

```python
"""GitHub Copilot as the model behind the one factory (D77): the names, the
shared reply mapping, the transports and `ChatCopilot` through
`ChatCompletions`."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
from decimal import Decimal

import pytest
from langchain_core.messages import HumanMessage

from caos import models
from caos.copilot import (
    ChatCopilot,
    CopilotModel,
    CopilotStatusError,
    Event,
    parsed,
    reply_message,
)
from caos.models import ChatCompletions, completions
from caos.pricing import ModelPrice
from caos.refusals import Refusal, RefusalCode

MODEL = "copilot:claude-opus-5.5@high"
TARGET = CopilotModel("copilot", "claude-opus-5.5", "high")
# Opus 5.5 on Copilot per token: its cache-write rate as the input rate, and
# its output rate (D77's derivation).
PRICE = ModelPrice(MODEL, Decimal("0.000005"), Decimal("0.00002"), date(2026, 10, 1))
# Long enough that its request carries the fixtures' 1,000 prompt tokens: no
# request holds more tokens than bytes (ST-11).
PROMPT = "q" * 1000


def event(kind: str, **data: object) -> Event:
    """One session event in the runtime's wire form."""
    return {"type": kind, "data": data}


def usage(**changed: object) -> Event:
    """One exact call's usage: 900 + 80 cache-read + 20 cache-written prompt
    tokens and 40 output tokens, on the pinned model at the pinned effort."""
    data: dict[str, object] = {
        "model": "claude-opus-5.5",
        "inputTokens": 900,
        "cacheReadTokens": 80,
        "cacheWriteTokens": 20,
        "outputTokens": 40,
        "finishReason": "end_turn",
        "reasoningEffort": "high",
        "providerCallId": "call-1",
    }
    data.update(changed)
    return event("assistant.usage", **data)


def answer(content: str = "answer", **changed: object) -> Event:
    return event("assistant.message", content=content, messageId="message-1", **changed)


IDLE = event("session.idle")


def replying(*seen: Event) -> Callable[[str, CopilotModel, float], list[Event]]:
    """An `ask` that answers every prompt with these events, then idles."""

    def ask(prompt: str, target: CopilotModel, seconds: float) -> list[Event]:
        return [*seen, IDLE]

    return ask


def provider(
    ask: Callable[[str, CopilotModel, float], Sequence[Event]],
) -> ChatCompletions:
    """The production provider over `ChatCopilot` with a scripted transport."""
    return completions(PRICE, chat=ChatCopilot(model=MODEL, ask=ask), endpoint=MODEL)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (MODEL, TARGET),
        ("copilot:gpt-6-luna", CopilotModel("copilot", "gpt-6-luna", None)),
        ("claude-opus-5-5", None),
        ("databricks-claude-opus-5", None),
        ("other:thing", None),
    ],
)
def test_a_copilot_name_is_its_platform_model_and_effort_and_any_other_is_an_endpoint(
    name: str, expected: CopilotModel | None
) -> None:
    assert parsed(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "copilot:",
        "copilot:Claude-Opus",
        "copilot:gpt-6@turbo",
        "copilot:gpt-6@high@low",
        "copilot:gpt 6",
        "copilot:-gpt",
    ],
)
def test_a_name_that_claims_copilot_and_does_not_parse_is_refused(name: str) -> None:
    with pytest.raises(Refusal) as refused:
        parsed(name)
    assert refused.value.code is RefusalCode.PROVIDER_NOT_CONFIGURED


def test_one_exact_call_is_an_answer_billed_on_every_prompt_token() -> None:
    message = reply_message([usage(), answer(), IDLE], TARGET)
    assert message.content == "answer"
    assert message.response_metadata == {"id": "call-1", "finish_reason": "stop"}
    assert message.usage_metadata == {
        "input_tokens": 1000,
        "output_tokens": 40,
        "total_tokens": 1040,
    }


@pytest.mark.parametrize(
    "seen",
    [
        [usage(model="claude-sonnet-5.5"), answer()],
        [usage(isAuto=True), answer()],
        [usage(isByok=True), answer()],
        [usage(availableToolCount=3), answer()],
        [usage(reasoningEffort="low"), answer()],
        [usage(), usage(), answer()],
        [usage(), answer(), answer()],
        [usage(), answer(toolRequests=[{"name": "bash", "toolCallId": "tool-1"}])],
        [usage(), answer(serverTools={"provider": "x"})],
        [usage(), event("session.truncation", tokenLimit=10), answer()],
        [usage(), event("session.compaction_start"), answer()],
        [usage()],
    ],
    ids=[
        "other-model",
        "auto",
        "byok",
        "tools-offered",
        "other-effort",
        "two-calls",
        "two-answers",
        "tool-request",
        "server-tool",
        "truncated",
        "compacted",
        "no-answer",
    ],
)
def test_anything_but_the_call_asked_for_states_no_finish_reason_and_keeps_its_bill(
    seen: list[Event],
) -> None:
    message = reply_message(seen, TARGET)
    assert "finish_reason" not in message.response_metadata
    assert message.usage_metadata is not None


@pytest.mark.parametrize(
    "changed",
    [
        {"inputTokens": None},
        {"outputTokens": None},
        {"inputTokens": "900"},
        {"cacheReadTokens": -1},
        {"outputTokens": True},
    ],
)
def test_a_count_not_stated_as_a_whole_number_is_no_usage(
    changed: dict[str, object],
) -> None:
    assert reply_message([usage(**changed), answer()], TARGET).usage_metadata is None


def test_a_usage_event_whose_data_is_not_an_object_is_no_usage() -> None:
    seen: list[Event] = [{"type": "assistant.usage", "data": "x"}, answer()]
    assert reply_message(seen, TARGET).usage_metadata is None


@pytest.mark.parametrize(
    ("reported", "read"),
    [
        ("stop", "stop"),
        ("end_turn", "stop"),
        ("stop_sequence", "stop"),
        ("max_tokens", "length"),
        ("length", "length"),
        ("refusal", "content_filter"),
        ("tool_use", "tool_use"),
    ],
)
def test_a_finish_reason_is_read_in_the_provider_vocabulary(
    reported: str, read: str
) -> None:
    message = reply_message([usage(finishReason=reported), answer()], TARGET)
    assert message.response_metadata["finish_reason"] == read


def test_chat_copilot_asks_once_with_the_prompt_its_pinned_model_and_deadline() -> None:
    asked: list[tuple[str, CopilotModel, float]] = []

    def ask(prompt: str, target: CopilotModel, seconds: float) -> list[Event]:
        asked.append((prompt, target, seconds))
        return [usage(), answer()]

    message = ChatCopilot(model=MODEL, ask=ask).invoke([HumanMessage(content=PROMPT)])
    assert message.content == "answer"
    assert asked == [(PROMPT, TARGET, models.TIMEOUT_SECONDS)]


def test_a_session_error_raises_its_status_and_never_its_text() -> None:
    failed = event("session.error", errorType="quota", message="private", statusCode=402)
    chat = ChatCopilot(model=MODEL, ask=replying(failed))
    with pytest.raises(CopilotStatusError) as raised:
        chat.invoke([HumanMessage(content=PROMPT)])
    assert raised.value.status_code == 402
    assert "private" not in str(raised.value)


def test_through_the_factory_the_charge_is_every_prompt_token_at_the_dated_price() -> (
    None
):
    completion = provider(replying(usage(), answer())).complete(PROMPT, json_object=True)
    assert completion.refusal is None
    assert completion.content == "answer"
    # 1,000 x 0.000005 + 40 x 0.00002, exactly (invariant 7).
    assert completion.charge == Decimal("0.0058")
    assert completion.generation_id == "call-1"


def test_a_call_that_was_not_the_one_asked_for_is_billed_and_refused() -> None:
    seen = (usage(model="claude-sonnet-5.5"), answer())
    completion = provider(replying(*seen)).complete(PROMPT)
    assert completion.content is None
    assert completion.charge == Decimal("0.0058")
    assert completion.refusal is RefusalCode.PROVIDER_RESPONSE_INVALID


def test_a_rate_limit_is_asked_again_under_the_same_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(models, "_sleep", lambda _seconds: None)
    limited = event("session.error", errorType="rate", message="private", statusCode=429)
    answers = iter([[limited], [usage(), answer()]])
    calls: list[str] = []

    def ask(prompt: str, target: CopilotModel, seconds: float) -> list[Event]:
        calls.append(prompt)
        return next(answers)

    completion = provider(ask).complete(PROMPT)
    assert completion.refusal is None
    assert calls == [PROMPT, PROMPT]


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, RefusalCode.PROVIDER_CALL_INVALID),
        (500, RefusalCode.PROVIDER_UNAVAILABLE),
        (None, RefusalCode.PROVIDER_UNAVAILABLE),
    ],
)
def test_a_runtime_error_maps_to_its_status_class_and_carries_no_text(
    status: int | None, code: RefusalCode
) -> None:
    failed = event("session.error", errorType="x", message="private", statusCode=status)
    completion = provider(replying(failed)).complete(PROMPT)
    assert (completion.content, completion.charge, completion.refusal) == (
        None,
        None,
        code,
    )
    assert "private" not in repr(completion)


def test_a_call_that_does_not_end_in_time_is_indeterminate() -> None:
    def ask(prompt: str, target: CopilotModel, seconds: float) -> list[Event]:
        raise TimeoutError

    completion = provider(ask).complete(PROMPT)
    assert completion.refusal is RefusalCode.PROVIDER_UNAVAILABLE
    assert completion.charge is None
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest --no-cov -p no:xdist tests/test_copilot.py -q`
Expected: a collection error, `ModuleNotFoundError: No module named 'caos.copilot'`.

- [ ] **Step 4: Write the module**

Create `caos/copilot.py`:

```python
"""GitHub Copilot as the model behind the one factory (D77).

AI Gateway is disabled in the enterprise workspace, so a model named
`copilot:<model>[@<effort>]` is answered by the GitHub Copilot runtime through
the Copilot SDK, on the machine the worker runs on and under the GitHub
identity signed in there; no credential is read by this code. The runtime is
used as a model and as nothing else.

Whatever transport carries a call, its answer arrives as the runtime's session
events in their wire form, `{"type": ..., "data": {...}}`, and is shaped here
into the `AIMessage` `models.ChatCompletions` already prices, bounds and
refuses, so every rule the gateway path is held to holds unchanged: the charge
is tokens x the run's dated price (invariant 7), a finish reason other than
`stop` is a refusal carrying its bill, one deadline bounds the call, and no
text of an error travels. A finish reason is stated only when the call was
exactly the one asked for; any other call is billed and refused as an invalid
response (F34).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGeneration, ChatResult
from openai import OpenAIError

from caos.provider import TIMEOUT_SECONDS
from caos.refusals import Refusal, RefusalCode

PLATFORM = "copilot"
_PLATFORMS = frozenset({PLATFORM})
# `<platform>:<model>[@<effort>]`: the transport, the runtime's own model id,
# and the effort it is sent at, one of the runtime's levels. The effort is part
# of the name because the runtime applies a model's default effort when none
# is sent, and no identity may name an effort the model did not receive (AR-15).
_NAME = re.compile(
    r"(copilot):([a-z0-9][a-z0-9.-]{0,127})(?:@(low|medium|high|xhigh|max))?"
)
# The finish reasons model families report, read in the one vocabulary
# `provider.finish_refusal` knows. Any other passes through unchanged and is
# refused there as an invalid response.
_FINISH = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "refusal": "content_filter",
}
# Events that say the prompt the model saw is not the prompt that was sent.
_RESHAPED = frozenset(
    {"session.truncation", "session.compaction_start", "session.compaction_complete"}
)

# One session event as the runtime writes it: `{"type": ..., "data": {...}}`.
Event = Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CopilotModel:
    """One Copilot model: the transport that carries it, the runtime's id, and
    the effort it is sent at."""

    platform: str
    name: str
    reasoning_effort: str | None


def parsed(model: str) -> CopilotModel | None:
    """The Copilot model `model` names; None for any other name (a gateway
    endpoint). A name that claims a Copilot platform and does not parse is
    refused, never read as an endpoint."""
    platform, colon, _rest = model.partition(":")
    if not colon or platform not in _PLATFORMS:
        return None
    matched = _NAME.fullmatch(model)
    if matched is None:
        raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED)
    return CopilotModel(matched.group(1), matched.group(2), matched.group(3))


class CopilotStatusError(OpenAIError):
    """A runtime error by its status alone, so `ChatCompletions` maps it as it
    maps a gateway status (`NEVER_RETRIED`, the 429 re-send under the same
    reservation). Its message never travels."""

    def __init__(self, status_code: int | None) -> None:
        super().__init__(PLATFORM)
        self.status_code = status_code


Ask = Callable[[str, CopilotModel, float], Sequence[Event]]


class ChatCopilot(BaseChatModel):
    """The chat model a Copilot name is answered by: one prompt, one reply."""

    model: str
    timeout: float = TIMEOUT_SECONDS
    # The test seam, as `completions(chat=...)` is the gateway's: a suite
    # passes its own and no runtime is started. Production passes nothing.
    ask: Any = None

    @property
    def _llm_type(self) -> str:
        return PLATFORM

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        # `response_format` is not sent (D77): the canonical executor validates
        # the envelope it asked for (invariant 9), and the request is still
        # priced as though it carried it.
        target = parsed(self.model)
        if target is None:
            raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED)
        content = messages[-1].content
        prompt = content if isinstance(content, str) else str(content)
        asked: Ask = self.ask or ask_copilot
        seen = asked(prompt, target, self.timeout)
        failed = _data(seen, "session.error")
        if failed:
            status = failed[0].get("statusCode")
            raise CopilotStatusError(status if type(status) is int else None)
        message = reply_message(seen, target)
        return ChatResult(generations=[ChatGeneration(message=message)])


def reply_message(seen: Sequence[Event], target: CopilotModel) -> AIMessage:
    """One call's events as the `AIMessage` `ChatCompletions` reads a gateway
    answer as: the answer, every call's tokens and the provider's call id,
    with a finish reason only when the call was exactly the one asked for."""
    usages = _data(seen, "assistant.usage")
    answers = _data(seen, "assistant.message")
    metadata: dict[str, Any] = {}
    if usages:
        last = usages[-1]
        claimed = last.get("providerCallId") or last.get("apiCallId")
        if isinstance(claimed, str) and claimed:
            metadata["id"] = claimed
        reason = last.get("finishReason")
        if isinstance(reason, str) and reason and _exact(seen, usages, answers, target):
            metadata["finish_reason"] = _FINISH.get(reason, reason)
    content = answers[-1].get("content") if answers else None
    return AIMessage(
        content=content if isinstance(content, str) else "",
        response_metadata=metadata,
        usage_metadata=_usage(usages),
    )


def _data(seen: Sequence[Event], kind: str) -> list[Mapping[str, Any]]:
    """The data of every event of one type, in order; a malformed one is empty,
    so a usage it carried is unknown rather than skipped."""
    return [
        event["data"] if isinstance(event.get("data"), Mapping) else {}
        for event in seen
        if event.get("type") == kind
    ]


def _exact(
    seen: Sequence[Event],
    usages: Sequence[Mapping[str, Any]],
    answers: Sequence[Mapping[str, Any]],
    target: CopilotModel,
) -> bool:
    """One model call on the pinned model at the pinned effort, offered no tool,
    answered once with no tool and no second model, nothing truncated or
    compacted."""
    if len(usages) != 1 or len(answers) != 1:
        return False
    usage, answer = usages[0], answers[0]
    reshaped = any(event.get("type") in _RESHAPED for event in seen)
    return (
        usage.get("model") == target.name
        and not usage.get("isAuto")
        and not usage.get("isByok")
        and not usage.get("availableToolCount")
        and _effort(usage.get("reasoningEffort")) == target.reasoning_effort
        and not answer.get("toolRequests")
        and answer.get("serverTools") is None
        and not reshaped
    )


def _effort(reported: object) -> str | None:
    return reported if isinstance(reported, str) and reported not in ("", "none") else None


def _usage(usages: Sequence[Mapping[str, Any]]) -> UsageMetadata | None:
    """Every call's tokens, or None when a call did not state its input or
    output as a whole count. Prompt tokens read from or written to a cache are
    counted at the input rate (D77): never less than the bill."""
    if not usages:
        return None
    prompt = output = 0
    try:
        for usage in usages:
            prompt += (
                _whole(usage.get("inputTokens"))
                + _whole(usage.get("cacheReadTokens") or 0)
                + _whole(usage.get("cacheWriteTokens") or 0)
            )
            output += _whole(usage.get("outputTokens"))
    except ValueError:
        return None
    return UsageMetadata(
        input_tokens=prompt, output_tokens=output, total_tokens=prompt + output
    )


def _whole(count: object) -> int:
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError
    return count


def ask_copilot(prompt: str, target: CopilotModel, seconds: float) -> list[Event]:
    """One call through the SDK (Task 3)."""
    raise NotImplementedError
```

The `ask_copilot` stub only exists so that `ChatCopilot` type-checks. Task 3 replaces it in the same PR, and `chat_model` does not dispatch until Task 3.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest --no-cov -p no:xdist tests/test_copilot.py -q`
Expected: all pass.

Run: `uv run ruff check caos/copilot.py tests/test_copilot.py && uv run ruff format --check caos/copilot.py tests/test_copilot.py && uv run mypy caos scripts tests`
Expected: clean. If `ruff format` would reflow, run `uv run ruff format` on the two files and re-run.

- [ ] **Step 6: Record D77's addendum**

D77 (the direction) was recorded when the build was initialised. Re-read the tail of `docs/rebuild/decisions.md`, then append this under D77's section `## GitHub Copilot as the model, 2026-10-01`:

```markdown
- D77, addendum (<YYYY-MM-DD>) — The SDK transport as built. A model named `copilot:<model>[@<effort>]` (`caos/copilot.py`) is answered by the Copilot runtime through `github-copilot-sdk` 1.0.16 on the machine the worker runs on: `caos.models.chat_model` returns `ChatCopilot` for such a name, and `ChatCompletions` prices, bounds and refuses its answer exactly as a gateway answer, so CAOS stays the orchestrator and Copilot is only the model. Each call is one empty-mode client, session and private directory, all removed afterwards: no tool (`available_tools=[]`, invariant 1); no custom instruction, skill or memory; the system message replaced by nothing; infinite sessions off (nothing compacted); the long-context tier (CP-0 sends whole filings, D29); output capped at `MAX_COMPLETION_TOKENS`; `response_format` not sent (the executor validates the envelope, invariant 9). Answers are read from the runtime's session events in wire form, so any transport that delivers them shares one mapping: a finish reason is stated only for exactly one model call on the pinned model at the pinned effort, offered no tool, with no tool request, no server tool and nothing truncated or compacted; anything else is billed and refused as an invalid response (F34). The charge is every prompt token (input, cache read, cache write) at the dated input rate plus output at the output rate; the owner prices a Copilot model at max(input, cache write) per token, so the charge is never below GitHub's bill (1 AI credit = $0.01). The effort is part of the name because the runtime applies a model's default effort when none is sent (AR-15). The identity is `copilot/<model>/<effort|none>/65536`, so a Copilot-served model qualifies separately from the same model on a gateway. Alternatives: Copilot CLI as the orchestrator with one skill per module and Delta over ODBC (run order, the ledger, the envelope and citations would rest on instructions, not code; rejected); a `CompletionProvider` of its own (duplicates the deadline, charge and refusal logic `ChatCompletions` already proves); RAI (needs use-case onboarding; a later provider behind the same factory). Measured first: `docs/rebuild/runs/copilot-spike-<date>/SUMMARY.md` (git-ignored). Evidence: `tests/test_copilot.py`.
```

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock caos/copilot.py tests/test_copilot.py docs/rebuild/decisions.md
git commit -m "Copilot 1/3: the copilot: names and the shared reply mapping (D77)"
```

---

### Task 3: The SDK transport and the factory dispatch

**Files:**
- Modify: `caos/copilot.py` (replace the `ask_copilot` stub; add `session_options`, `_client`, `_asked`)
- Modify: `caos/models.py:1-17` (docstring), `caos/models.py:80-110` (`identity_of`, `chat_model`)
- Modify: `caos/provider.py:1-14` (docstring)
- Test: `tests/test_copilot.py` (append)

**Interfaces:**
- Consumes: Task 2's names; `caos.provider.MAX_COMPLETION_TOKENS`; the SDK's `CopilotClient`, `ModelCapabilitiesOverride`, `ModelLimitsOverride` and `SessionEvent`, imported only inside the functions that use them.
- Produces:
  - `def session_options(target: CopilotModel, home: str) -> dict[str, Any]`;
  - `def ask_copilot(prompt: str, target: CopilotModel, seconds: float) -> list[Event]` (real);
  - `async def _client() -> AsyncIterator[tuple[CopilotClient, str]]` (private; Task 5 reuses it);
  - `caos.models.identity_of(model, reasoning_effort=None) -> str`, now aware of the platform;
  - `caos.models.chat_model(*, endpoint=None) -> BaseChatModel`, now `ChatCopilot` for a Copilot name.

- [ ] **Step 1: Write the failing tests**

Merge these imports into `tests/test_copilot.py`'s import block, in `ruff` order:

```python
from pathlib import Path
from typing import Any, ClassVar

from copilot import ModelCapabilitiesOverride, ModelLimitsOverride

from caos.copilot import ask_copilot, session_options
```

Then append:

```python
class Wire:
    """A session event as the SDK hands it to a handler."""

    def __init__(self, wire: Event) -> None:
        self.wire = wire

    def to_dict(self) -> Event:
        return self.wire


class FakeSession:
    """Stands in for `copilot.CopilotSession`: delivers its events on `send`."""

    def __init__(self, seen: Sequence[Event], *, ends: bool = True) -> None:
        self.seen = seen
        self.ends = ends
        self.handlers: list[Callable[[Any], None]] = []
        self.sent: list[str] = []
        self.aborted = False

    def on(self, handler: Callable[[Any], None]) -> Callable[[], None]:
        self.handlers.append(handler)
        return lambda: None

    async def send(self, prompt: str) -> str:
        self.sent.append(prompt)
        if self.ends:
            for wire in self.seen:
                for handler in self.handlers:
                    handler(Wire(wire))
        return "message-1"

    async def abort(self) -> None:
        self.aborted = True

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class FakeRuntime:
    """Stands in for `copilot.CopilotClient`: one per call, each recorded."""

    made: ClassVar[list[FakeRuntime]] = []
    session: ClassVar[FakeSession] = FakeSession([])
    signed_in: ClassVar[bool] = True
    offered: ClassVar[list[object]] = []

    def __init__(self, **options: object) -> None:
        self.options = options
        self.home = Path(str(options["base_directory"]))
        self.home_existed = self.home.is_dir()
        self.created: dict[str, object] = {}
        type(self).made.append(self)

    async def __aenter__(self) -> FakeRuntime:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def create_session(self, **options: object) -> FakeSession:
        self.created = options
        return type(self).session

    async def get_auth_status(self) -> object:
        return type("Status", (), {"isAuthenticated": type(self).signed_in})()

    async def list_models(self) -> list[object]:
        return type(self).offered


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> type[FakeRuntime]:
    class Runtime(FakeRuntime):
        made: ClassVar[list[FakeRuntime]] = []

    monkeypatch.setattr("copilot.CopilotClient", Runtime)
    return Runtime


def test_a_session_has_no_tool_no_compaction_no_system_text_and_the_cap() -> None:
    assert session_options(TARGET, "home") == {
        "model": "claude-opus-5.5",
        "reasoning_effort": "high",
        "available_tools": [],
        "system_message": {"mode": "replace", "content": ""},
        "infinite_sessions": {"enabled": False},
        "context_tier": "long_context",
        "model_capabilities": ModelCapabilitiesOverride(
            limits=ModelLimitsOverride(max_output_tokens=65536)
        ),
        "working_directory": "home",
        "streaming": False,
    }


def test_one_call_is_one_fresh_runtime_and_session_and_leaves_nothing_on_disk(
    runtime: type[FakeRuntime],
) -> None:
    runtime.session = FakeSession([usage(), answer(), IDLE])
    assert ask_copilot(PROMPT, TARGET, 5.0) == [usage(), answer(), IDLE]
    [made] = runtime.made
    assert made.options == {
        "mode": "empty",
        "base_directory": str(made.home),
        "log_level": "none",
    }
    assert made.home_existed
    assert not made.home.exists()
    assert made.created == session_options(TARGET, str(made.home))
    assert runtime.session.sent == [PROMPT]


def test_a_call_that_does_not_end_in_time_is_aborted_and_raises(
    runtime: type[FakeRuntime],
) -> None:
    runtime.session = FakeSession([], ends=False)
    with pytest.raises(TimeoutError):
        ask_copilot(PROMPT, TARGET, 0.01)
    assert runtime.session.aborted


def test_a_session_error_ends_the_wait_and_is_returned_as_data(
    runtime: type[FakeRuntime],
) -> None:
    failed = event("session.error", errorType="quota", message="private", statusCode=402)
    runtime.session = FakeSession([failed])
    assert ask_copilot(PROMPT, TARGET, 5.0) == [failed]


def test_a_copilot_model_is_answered_by_chat_copilot_never_the_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import databricks_langchain

    def gateway(**_given: object) -> None:
        raise AssertionError("a copilot: model reached the gateway")

    monkeypatch.setattr(databricks_langchain, "ChatDatabricks", gateway)
    chat = models.chat_model(endpoint=MODEL)
    assert isinstance(chat, ChatCopilot)
    assert (chat.model, chat.ask, chat.timeout) == (MODEL, None, models.TIMEOUT_SECONDS)
    monkeypatch.setenv(models.ENDPOINT_ENV, "copilot:gpt-6-luna")
    assert isinstance(models.chat_model(), ChatCopilot)


def test_a_copilot_identity_names_its_platform_model_and_effort() -> None:
    assert models.identity_of(MODEL) == "copilot/claude-opus-5.5/high/65536"
    assert models.identity_of("copilot:gpt-6-luna") == "copilot/gpt-6-luna/none/65536"
    assert models.identity_of("claude-opus-5-5") == "databricks/claude-opus-5-5/none/65536"
    assert provider(replying()).qualification_identity == (
        "copilot/claude-opus-5.5/high/65536"
    )


def test_a_malformed_copilot_name_is_refused_before_any_client() -> None:
    with pytest.raises(Refusal) as refused:
        models.chat_model(endpoint="copilot:Opus")
    assert refused.value.code is RefusalCode.PROVIDER_NOT_CONFIGURED
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest --no-cov -p no:xdist tests/test_copilot.py -q`
Expected: an `ImportError` for `session_options`. After a stub of it exists, the failures are the `NotImplementedError`, `ChatDatabricks` being reached for a Copilot name, and the identity mismatch.

- [ ] **Step 3: Implement the SDK transport**

In `caos/copilot.py`, merge into the imports:

```python
import asyncio
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from caos.provider import MAX_COMPLETION_TOKENS

if TYPE_CHECKING:
    from copilot import CopilotClient, SessionEvent
```

(`MAX_COMPLETION_TOKENS` joins the existing `caos.provider` import line.) Replace the `ask_copilot` stub with:

```python
# The events that end a call: the session went idle, or it failed.
_ENDS = frozenset({"session.idle", "session.error"})


def session_options(target: CopilotModel, home: str) -> dict[str, Any]:
    """What one session is created with: the pinned model at its pinned effort,
    and nothing else the runtime offers (D77)."""
    from copilot import ModelCapabilitiesOverride, ModelLimitsOverride

    return {
        "model": target.name,
        "reasoning_effort": target.reasoning_effort,
        # A model, not an agent: no tool of any source -- built-in, MCP or
        # custom -- so no file, shell or web page is reachable (invariant 1).
        "available_tools": [],
        # The prompt is the whole request, as it is on the gateway.
        "system_message": {"mode": "replace", "content": ""},
        # Never compacted to fit: evidence is sent whole or refused.
        "infinite_sessions": {"enabled": False},
        # The 1M-token tier: CP-0 sends whole filings (D29).
        "context_tier": "long_context",
        # The completion cap every reservation is priced on.
        "model_capabilities": ModelCapabilitiesOverride(
            limits=ModelLimitsOverride(max_output_tokens=MAX_COMPLETION_TOKENS)
        ),
        "working_directory": home,
        "streaming": False,
    }


@asynccontextmanager
async def _client() -> AsyncIterator[tuple[CopilotClient, str]]:
    """One runtime in a private directory removed with it, so a prompt -- which
    carries document text -- is not left on the disk after its call (D77)."""
    from copilot import CopilotClient

    with tempfile.TemporaryDirectory(
        prefix="caos-copilot-", ignore_cleanup_errors=True
    ) as home:
        async with CopilotClient(
            mode="empty", base_directory=home, log_level="none"
        ) as client:
            yield client, home


def ask_copilot(prompt: str, target: CopilotModel, seconds: float) -> list[Event]:
    """One call through the SDK: every event, in its wire form and order.

    Raises `TimeoutError` past `seconds`, having asked the runtime to stop;
    whatever else the SDK raises propagates, and `ChatCompletions` reads it as
    indeterminate. A session error ends the wait and is returned as data, so
    its message is never raised.
    """
    return asyncio.run(_asked(prompt, target, seconds))


async def _asked(prompt: str, target: CopilotModel, seconds: float) -> list[Event]:
    seen: list[Event] = []
    ended = asyncio.Event()

    def heard(event: SessionEvent) -> None:
        wire = event.to_dict()
        seen.append(wire)
        if wire.get("type") in _ENDS and wire.get("agentId") is None:
            ended.set()

    async with _client() as (client, home):
        options = session_options(target, home)
        async with await client.create_session(**options) as session:
            session.on(heard)
            await session.send(prompt)
            try:
                await asyncio.wait_for(ended.wait(), timeout=seconds)
            except TimeoutError:
                await session.abort()
                raise
    return seen
```

`asyncio.run` gives each call its own event loop, on the thread `ChatCompletions._invoked` runs it on. That thread is abandoned at the call's deadline (ST-9), the same way the gateway's socket is.

- [ ] **Step 4: Dispatch in the factory**

In `caos/models.py`, add `from caos import copilot` after `from caos.pricing import ...`, then replace `identity_of`:

```python
def identity_of(model: str, reasoning_effort: str | None = None) -> str:
    """The execution profile a verdict binds (D8), from the names alone, so a
    caller can refuse an unexpected one before any client is built. A Copilot
    model names its own platform and effort (D77)."""
    target = copilot.parsed(model)
    if target is None:
        parts = (PLATFORM, model, reasoning_effort or "none")
    else:
        parts = (target.platform, target.name, target.reasoning_effort or "none")
    return "/".join((*parts, str(MAX_COMPLETION_TOKENS)))
```

In `chat_model`, dispatch before the `databricks_langchain` import, and pass `name` on:

```python
def chat_model(*, endpoint: str | None = None) -> BaseChatModel:
    """The production chat model: `ChatDatabricks` on the configured endpoint,
    or `ChatCopilot` for a Copilot model (D77).

    Imported here rather than at module load so the seam's tests, which inject
    their own model, never touch the Databricks SDK. Authentication is the
    SDK's unified chain -- the app's service-principal variables on Databricks
    Apps, a CLI profile locally -- and no credential is read by this code.
    """
    name = endpoint or configured_endpoint()
    if copilot.parsed(name) is not None:
        return copilot.ChatCopilot(model=name)
    from databricks_langchain import ChatDatabricks

    from caos.workspace import workspace_client

    # A read deadline no longer than the whole call's (brief D5, F40, ST-9),
    # and no retry below the seam: a retry is the caller's reservation. The client
    # is the process's bounded one (CR-6): the default the library would
    # build carries the SDK's five-minute discovery budget.
    return ChatDatabricks(
        endpoint=name,
        max_tokens=MAX_COMPLETION_TOKENS,
        timeout=TIMEOUT_SECONDS,
        max_retries=0,
        workspace_client=workspace_client(),
    )
```

Make three docstring edits:
- In `caos/models.py`, change the first line to `"""The one model factory: every production call goes through AI Gateway or Copilot.`
- In the same docstring, change the first paragraph's description of `chat_model` to "`ChatDatabricks` against the configured serving endpoint, or `ChatCopilot` for a Copilot model (D77, `caos/copilot.py`)".
- In `caos/provider.py`'s docstring, change "(Databricks AI Gateway through the one model factory)" to "(Databricks AI Gateway, or GitHub Copilot for a Copilot model, through the one model factory)".

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest --no-cov -p no:xdist tests/test_copilot.py tests/test_models.py tests/test_model_choice.py -q`
Expected: all pass, `test_the_production_model_is_chat_databricks_on_the_endpoint` unchanged.

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy caos scripts tests && uv run complexipy caos scripts icm --max-complexity-allowed 15 && uv run python scripts/check_tested.py && uv run python scripts/check_vocabulary.py`
Expected: all exit 0.

- [ ] **Step 6: The PR gates (end of Copilot 1/3)**

Run the full gate list in `CLAUDE.md`, with Postgres up (`docker compose up -d --wait`). Expected: all exit 0. That includes the suite under `CAOS_REQUIRE_POSTGRES=1` with coverage ≥ 80%, `uv run python scripts/check_gate_config.py`, and `uv run python scripts/check_pr_size.py origin/rebuild/databricks` (≤ 800).

- [ ] **Step 7: Commit, then open Copilot 1/3 when the owner asks**

```bash
git add caos/copilot.py caos/models.py caos/provider.py tests/test_copilot.py
git commit -m "Copilot 1/3: a copilot: model is answered through the Copilot SDK (D77)"
```

---

### Task 4: The Copilot CLI fallback

**Files:**
- Modify: `caos/copilot.py` (the `copilot-cli` platform, `overhead_bytes`, `cli_arguments`, `printed_events`, `ask_copilot_cli`, `_cli_asked`; dispatch in `ChatCopilot._generate`)
- Modify: `caos/models.py` (`ChatCompletions.request_bytes`)
- Modify: `docs/rebuild/decisions.md` (D78)
- Test: `tests/test_copilot.py` (append)

**Interfaces:**
- Consumes: `_data`, `reply_message`, `Event`, `CopilotModel` and `parsed` (Task 2); the factory dispatch (Task 3).
- Produces:
  - `CLI_PLATFORM = "copilot-cli"`, `CLI = "copilot"`, `CLI_OVERHEAD_BYTES = 65_536`;
  - `def overhead_bytes(model: str) -> int`;
  - `def cli_arguments(target: CopilotModel) -> list[str]`;
  - `def printed_events(printed: bytes) -> list[Event]`;
  - `def ask_copilot_cli(prompt: str, target: CopilotModel, seconds: float) -> list[Event]`.

Before Step 3, put Task 1's spellings from `help.txt` into `_CLI_FLAGS` wherever they differ from the defaults below.

- [ ] **Step 1: Write the failing tests**

Merge these imports into `tests/test_copilot.py`:

```python
import json
import sys

from caos.copilot import (
    CLI_OVERHEAD_BYTES,
    ask_copilot_cli,
    cli_arguments,
    overhead_bytes,
    printed_events,
)
from caos.provider import encode_request
```

Then append:

```python
CLI_MODEL = "copilot-cli:claude-opus-5.5@high"
CLI_TARGET = CopilotModel("copilot-cli", "claude-opus-5.5", "high")
CLI_PRICE = ModelPrice(
    CLI_MODEL, Decimal("0.000005"), Decimal("0.00002"), date(2026, 10, 1)
)
# Stands in for the `copilot` executable: reads the prompt on stdin, prints a
# banner that is not an event, then one usage and one answer naming what it saw.
FAKE_CLI = r"""
import json, os, sys
prompt = sys.stdin.buffer.read()
home = os.environ.get("COPILOT_HOME", "")
seen = {
    "home": home,
    "cwd_is_home": bool(home) and os.path.samefile(os.getcwd(), home),
    "opt_in": "GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS" in os.environ,
    "prompt_bytes": len(prompt),
}
print("Copilot CLI banner, not an event")
print(json.dumps({"type": "assistant.usage", "data": {
    "model": "claude-opus-5.5", "inputTokens": 900, "outputTokens": 40,
    "finishReason": "stop", "reasoningEffort": "high"}}))
print(json.dumps({"type": "assistant.message", "data": {"content": json.dumps(seen)}}))
"""


def faked(monkeypatch: pytest.MonkeyPatch, script: str) -> None:
    """Run `script` under this interpreter wherever the CLI would run."""
    monkeypatch.setattr("caos.copilot.shutil.which", lambda _name: sys.executable)
    monkeypatch.setattr("caos.copilot.cli_arguments", lambda _target: ["-c", script])


def test_a_cli_name_is_its_own_platform_and_identity() -> None:
    assert parsed(CLI_MODEL) == CLI_TARGET
    assert models.identity_of(CLI_MODEL) == "copilot-cli/claude-opus-5.5/high/65536"
    with pytest.raises(Refusal):
        parsed("copilot-cli:")


def test_the_cli_is_given_fixed_flags_and_the_pinned_model_only() -> None:
    arguments = cli_arguments(CLI_TARGET)
    assert arguments[:4] == ["--model", "claude-opus-5.5", "--reasoning-effort", "high"]
    assert "--output-format" in arguments
    assert "--no-custom-instructions" in arguments
    assert cli_arguments(CopilotModel("copilot-cli", "gpt-6-luna", None))[:2] == [
        "--model",
        "gpt-6-luna",
    ]


def test_printed_events_keeps_event_lines_and_refuses_a_broken_one() -> None:
    printed = b'banner\n\n{"type": "assistant.usage", "data": {}}\n'
    assert printed_events(printed) == [{"type": "assistant.usage", "data": {}}]
    with pytest.raises(ValueError):
        printed_events(b'{"type": ')
    with pytest.raises(ValueError):
        printed_events(b'{"data": {}}')


def test_a_cli_request_carries_the_allowance_for_its_own_system_prompt() -> None:
    assert overhead_bytes(CLI_MODEL) == CLI_OVERHEAD_BYTES
    assert overhead_bytes(MODEL) == overhead_bytes("claude-opus-5-5") == 0
    cli = completions(CLI_PRICE, chat=ChatCopilot(model=CLI_MODEL), endpoint=CLI_MODEL)
    assert len(cli.request_bytes(PROMPT)) == (
        len(encode_request(CLI_MODEL, PROMPT)) + CLI_OVERHEAD_BYTES
    )


def test_one_cli_call_is_isolated_and_reads_the_events_it_printed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    faked(monkeypatch, FAKE_CLI)
    monkeypatch.setenv("GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS", "true")
    seen = ask_copilot_cli(PROMPT, CLI_TARGET, 30.0)
    assert [wire["type"] for wire in seen] == ["assistant.usage", "assistant.message"]
    facts = json.loads(seen[1]["data"]["content"])
    assert facts["cwd_is_home"] is True
    assert facts["opt_in"] is False
    assert facts["prompt_bytes"] == len(PROMPT)
    assert not Path(facts["home"]).exists()


def test_a_cli_that_does_not_end_in_time_is_killed_and_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    faked(monkeypatch, "import time; time.sleep(30)")
    with pytest.raises(TimeoutError):
        ask_copilot_cli(PROMPT, CLI_TARGET, 0.5)


def test_a_cli_that_fails_says_so_only_through_its_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    faked(monkeypatch, "import sys; sys.exit(3)")
    with pytest.raises(ChildProcessError):
        ask_copilot_cli(PROMPT, CLI_TARGET, 30.0)
    failed = json.dumps(
        {"type": "session.error", "data": {"errorType": "x", "statusCode": 401}}
    )
    faked(monkeypatch, f"import sys; print({failed!r}); sys.exit(1)")
    assert printed_events(failed.encode()) == ask_copilot_cli(PROMPT, CLI_TARGET, 30.0)


def test_a_missing_cli_is_indeterminate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("caos.copilot.shutil.which", lambda _name: None)
    with pytest.raises(FileNotFoundError):
        ask_copilot_cli(PROMPT, CLI_TARGET, 30.0)


def test_a_cli_model_takes_the_cli_and_never_the_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def sdk(prompt: str, target: CopilotModel, seconds: float) -> list[Event]:
        raise AssertionError("a copilot-cli: model reached the SDK")

    cli_usage = usage(cacheReadTokens=0, cacheWriteTokens=0, inputTokens=1000)
    monkeypatch.setattr("caos.copilot.ask_copilot", sdk)
    monkeypatch.setattr("caos.copilot.ask_copilot_cli", replying(cli_usage, answer()))
    completion = completions(CLI_PRICE, endpoint=CLI_MODEL).complete(PROMPT)
    assert completion.refusal is None
    assert completion.charge == Decimal("0.0058")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest --no-cov -p no:xdist tests/test_copilot.py -q`
Expected: an `ImportError` for `CLI_OVERHEAD_BYTES`.

- [ ] **Step 3: Implement the CLI transport**

In `caos/copilot.py`:
- in the module docstrings of `caos/copilot.py` and `tests/test_copilot.py`, and in `caos/models.py`'s docstring, change `(D77` to `(D77, D78`;
- add `import json`, `import os`, `import shutil` to the imports;
- set `_PLATFORMS = frozenset({PLATFORM, CLI_PLATFORM})`, defining `CLI_PLATFORM` above it;
- widen `_NAME`'s first group to `(copilot|copilot-cli)`;
- in `ChatCopilot._generate`, replace `asked: Ask = self.ask or ask_copilot` with:

```python
        transport = ask_copilot_cli if target.platform == CLI_PLATFORM else ask_copilot
        asked: Ask = self.ask or transport
```

Then append:

```python
CLI_PLATFORM = "copilot-cli"
# The executable the fallback runs, found on PATH as IT installed it (D78).
CLI = "copilot"
# Prompt mode as a model: JSON event lines, no tool, no custom instruction,
# no self-update mid-run, no token streaming, the long-context tier (Task 1
# recorded these spellings from `copilot --help`).
_CLI_FLAGS = (
    "--output-format",
    "json",
    "--available-tools=",
    "--no-custom-instructions",
    "--no-auto-update",
    "--stream",
    "off",
    "--context",
    "long_context",
)
# Prompt-mode opt-ins that load a folder's hooks, MCP servers or extensions;
# never passed on to the CLI.
_CLI_OPT_INS = frozenset(
    {
        "GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS",
        "GITHUB_COPILOT_PROMPT_MODE_WORKSPACE_MCP",
        "GITHUB_COPILOT_PROMPT_MODE_EXTENSIONS",
    }
)
# The CLI wraps every prompt in a system prompt of its own that no flag
# replaces: this many bytes are added to what its request is priced and bounded
# on (D78). Task 1 measured its tokens at well under half of it.
CLI_OVERHEAD_BYTES = 65_536


def overhead_bytes(model: str) -> int:
    """What a transport adds to the prompt it is given, as request bytes: the
    CLI's own system prompt; nothing for the SDK or a gateway endpoint."""
    target = parsed(model)
    if target is not None and target.platform == CLI_PLATFORM:
        return CLI_OVERHEAD_BYTES
    return 0


def cli_arguments(target: CopilotModel) -> list[str]:
    """The CLI's arguments: fixed flags and the pinned model and effort, which
    `parsed` matched against `[a-z0-9.-]` and the effort levels. Never the
    prompt, which goes on stdin."""
    effort = target.reasoning_effort
    pinned = ["--reasoning-effort", effort] if effort is not None else []
    return ["--model", target.name, *pinned, *_CLI_FLAGS]


def printed_events(printed: bytes) -> list[Event]:
    """The event lines the CLI printed, in order. A line that is not JSON at
    all is not an event; a line that starts as one and does not parse, or
    names no type, raises: a lost usage line would under-bill."""
    seen: list[Event] = []
    for line in printed.decode("utf-8", "replace").splitlines():
        if not line.lstrip().startswith("{"):
            continue
        wire = json.loads(line)
        if not isinstance(wire, dict) or not isinstance(wire.get("type"), str):
            raise ValueError
        seen.append(wire)
    return seen


def ask_copilot_cli(prompt: str, target: CopilotModel, seconds: float) -> list[Event]:
    """One call through the Copilot CLI in prompt mode (D78): every event it
    printed, in order.

    Raises `TimeoutError` past `seconds` (the process is killed), and raises
    when the CLI cannot be found or exits non-zero with no session error;
    `ChatCompletions` reads each as indeterminate. Its error output is never
    read.
    """
    executable = shutil.which(CLI)
    if executable is None:
        raise FileNotFoundError(CLI)
    return asyncio.run(_cli_asked(executable, prompt, target, seconds))


async def _cli_asked(
    executable: str, prompt: str, target: CopilotModel, seconds: float
) -> list[Event]:
    with tempfile.TemporaryDirectory(
        prefix="caos-copilot-", ignore_cleanup_errors=True
    ) as home:
        environment = {
            name: value
            for name, value in os.environ.items()
            if name not in _CLI_OPT_INS
        }
        # A private home that is also the working folder: no extension, skill,
        # plugin, MCP configuration, memory or trusted folder of the analyst's
        # own reaches the call, and nothing of it outlives the call.
        environment["COPILOT_HOME"] = home
        # Arguments only, no shell: `cli_arguments` is fixed flags and a
        # matched model id. bandit does not scan asyncio's process API, so this
        # call had an adversarial review instead (D78).
        process = await asyncio.create_subprocess_exec(
            executable,
            *cli_arguments(target),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=home,
            env=environment,
        )
        try:
            printed, _ = await asyncio.wait_for(
                process.communicate(prompt.encode("utf-8")), timeout=seconds
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise
    seen = printed_events(printed)
    if process.returncode != 0 and not _data(seen, "session.error"):
        raise ChildProcessError(process.returncode)
    return seen
```

In `caos/models.py`, replace `ChatCompletions.request_bytes`:

```python
    def request_bytes(self, prompt: str, *, json_object: bool = False) -> bytes:
        """The request the call is priced on: model, prompt, ceiling, format --
        and, for a transport that wraps the prompt in a system prompt of its
        own, an allowance for it (D78). Only its length is read."""
        encoded = encode_request(self.model, prompt, json_object=json_object)
        return encoded + bytes(copilot.overhead_bytes(self.model))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest --no-cov -p no:xdist tests/test_copilot.py tests/test_models.py -q`
Expected: all pass.

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy caos scripts tests && uv run complexipy caos scripts icm --max-complexity-allowed 15 && uv run python scripts/check_tested.py && uv run bandit -r caos scripts icm -f json -o bandit.json; uv run python scripts/scan_floors.py bandit.json --no-parse-errors --cover caos scripts icm --unscanned tests`
Expected: all exit 0, and bandit reports no finding.

- [ ] **Step 5: Adversarial review of the process start**

Run the `adversarial-reviewer` skill inline (or dispatch `mx-adversary` if the owner allows agents) on `_cli_asked`, `cli_arguments`, `printed_events` and `ask_copilot_cli`. The review covers:
- argument injection: the model id, the effort, a Windows `.cmd` shim;
- the prompt never reaching the command line;
- inherited environment and credentials;
- that `COPILOT_HOME` isolates extensions, skills, plugins and MCP;
- stdout parsing that could under-bill;
- a process left behind after a timeout (Windows included);
- stderr never read.

Fix what it confirms, recording each fix as an `Fn` in `decisions.md`.

- [ ] **Step 6: Record D78**

Append to `docs/rebuild/decisions.md`, using the next free D:

```markdown
- D78 (<YYYY-MM-DD>) — The Copilot CLI as a fallback transport, for a PC where the Copilot SDK or the runtime it provisions is not approved or not working (D77). A model named `copilot-cli:<model>[@<effort>]` is answered by the IT-installed `copilot` executable in prompt mode: the prompt on stdin (a module's prompt is far past a command line's limit, 32,767 characters on Windows); `--output-format json`, whose JSON lines are the runtime's session events in the same wire form the SDK delivers, read by the same `reply_message`; no tool (`--available-tools=`), `--no-custom-instructions`, `--no-auto-update`, `--stream off`, the long-context tier, `--model` and `--reasoning-effort`; a private `COPILOT_HOME` that is also the working folder and is removed after the call, so no extension, skill, plugin, MCP configuration, memory or trusted folder of the analyst's own reaches it; the `GITHUB_COPILOT_PROMPT_MODE_*` opt-ins never passed on; error output never read. It is chosen by name, never an automatic fallback: no flag replaces the CLI's own system prompt, so its answers are a different execution profile (`copilot-cli/<model>/<effort|none>/65536`) that qualifies separately, and a run pinned to one transport never switches (F468). Its request is priced and bounded with `CLI_OVERHEAD_BYTES` (64 KiB) added for that system prompt (Task 1 measured <n> tokens). The CLI caps output at the model's own limit, not `MAX_COMPLETION_TOKENS`: an answer past 65,536 tokens is billed unknown and refused, as on the gateway. The process starts through `asyncio.create_subprocess_exec`; bandit's subprocess checks do not cover asyncio's process API (checked: no finding), so the call carries neither a finding nor a suppression, and in the scanner's place it is shell-free, takes fixed flags and a matched model id only, and had an adversarial review (<reviewer>, <date>). A PC that may not install the SDK package syncs with `uv sync --locked --no-install-package github-copilot-sdk`: `caos/copilot.py` imports the SDK only inside the SDK transport and readiness. Alternatives: an automatic fallback from the SDK (two execution profiles in one run, against D8 and F468); the SDK over the IT-installed executable through `COPILOT_CLI_PATH` (still needs the SDK package and a protocol-compatible executable; recorded in the runbook as a configuration); `subprocess` with `nosec` (raises the suppression baseline, which may only fall). Evidence: `tests/test_copilot.py` (the `copilot-cli` tests).
```

- [ ] **Step 7: Commit; Copilot 2/3**

```bash
git add caos/copilot.py caos/models.py tests/test_copilot.py docs/rebuild/decisions.md
git commit -m "Copilot 2/3: the Copilot CLI as a fallback transport (D78)"
```

Run the PR gates as in Task 3 Step 6, against Copilot 1/3's branch. Open **Copilot 2/3**, stacked on 1/3, only when the owner asks.

---

### Task 5: Readiness at worker start and the production smoke

**Files:**
- Modify: `caos/copilot.py` (add `require_ready`, `usable`, `_offered`)
- Modify: `caos/graph/worker.py:597-611` (`_configured`)
- Modify: `scripts/gateway_smoke.py:30-41` (production check)
- Modify: `scripts/qualify.py:23-30` (docstring examples)
- Test: `tests/test_copilot.py` (append)

**Interfaces:**
- Consumes: `_client()`, `parsed`, `CopilotModel`, `CLI_PLATFORM`, `CLI` (Tasks 2–4); `copilot.ModelInfo` (for typing only).
- Produces:
  - `def require_ready(models: Iterable[str]) -> None`, which prints `copilot <model> max_prompt_tokens=<n>` to stderr for each SDK model and raises `Refusal(PROVIDER_NOT_CONFIGURED)` when not ready;
  - `def usable(info: ModelInfo, target: CopilotModel) -> bool`.

- [ ] **Step 1: Write the failing tests**

Merge these imports into `tests/test_copilot.py`:

```python
import gateway_smoke
from copilot import ModelInfo

from caos.copilot import require_ready, usable
from caos.graph import worker
```

Then append:

```python
def listed(
    model_id: str = "claude-opus-5.5",
    *,
    state: str | None = "enabled",
    efforts: list[str] | None = None,
    limit: int = 1_000_000,
) -> ModelInfo:
    """A model as `list_models` describes it."""
    taken = ["low", "medium", "high"] if efforts is None else efforts
    info: dict[str, object] = {
        "id": model_id,
        "name": model_id,
        "capabilities": {
            "supports": {"reasoningEffort": bool(taken)},
            "limits": {"max_prompt_tokens": limit},
        },
        "supportedReasoningEfforts": taken,
    }
    if state is not None:
        info["policy"] = {"state": state, "terms": ""}
    return ModelInfo.from_dict(info)


def test_no_copilot_model_starts_no_runtime(runtime: type[FakeRuntime]) -> None:
    require_ready(["claude-opus-5-5", "databricks-claude-opus-5"])
    assert runtime.made == []


def test_a_ready_copilot_model_prints_its_prompt_limit(
    runtime: type[FakeRuntime], capsys: pytest.CaptureFixture[str]
) -> None:
    runtime.offered = [listed()]
    require_ready([MODEL, "claude-opus-5-5"])
    assert capsys.readouterr().err == (
        "copilot claude-opus-5.5 max_prompt_tokens=1000000\n"
    )
    [made] = runtime.made
    assert not made.home.exists()


@pytest.mark.parametrize(
    ("signed_in", "offered", "name"),
    [
        (False, [listed()], MODEL),
        (True, [], MODEL),
        (True, [listed(state="disabled")], MODEL),
        (True, [listed(state="unconfigured")], MODEL),
        (True, [listed(efforts=["low"])], MODEL),
        (True, [listed()], "copilot:claude-opus-5.5"),
        (True, [listed(efforts=[])], MODEL),
    ],
    ids=[
        "not-signed-in",
        "not-offered",
        "policy-disabled",
        "policy-unconfigured",
        "effort-not-taken",
        "effort-taken-none-pinned",
        "effort-pinned-none-taken",
    ],
)
def test_a_model_this_machine_cannot_answer_on_refuses_the_worker(
    runtime: type[FakeRuntime], signed_in: bool, offered: list[object], name: str
) -> None:
    runtime.signed_in = signed_in
    runtime.offered = offered
    with pytest.raises(Refusal) as refused:
        require_ready([name])
    assert refused.value.code is RefusalCode.PROVIDER_NOT_CONFIGURED


def test_a_cli_model_needs_the_cli_on_path_and_starts_no_runtime(
    runtime: type[FakeRuntime], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("caos.copilot.shutil.which", lambda _name: None)
    with pytest.raises(Refusal):
        require_ready([CLI_MODEL])
    monkeypatch.setattr("caos.copilot.shutil.which", lambda _name: sys.executable)
    require_ready([CLI_MODEL])
    assert runtime.made == []


def test_an_sdk_model_without_the_sdk_installed_refuses_the_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "copilot", None)
    with pytest.raises(Refusal) as refused:
        require_ready([MODEL])
    assert refused.value.code is RefusalCode.PROVIDER_NOT_CONFIGURED


def test_usable_reads_the_policy_and_the_effort() -> None:
    assert usable(listed(), TARGET)
    assert usable(listed(state=None), TARGET)
    assert usable(listed(efforts=[]), CopilotModel("copilot", "gpt-6-luna", None))
    assert not usable(listed(), CopilotModel("copilot", "claude-opus-5.5", None))


def test_a_worker_whose_copilot_model_is_not_ready_refuses_before_the_store(
    runtime: type[FakeRuntime],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(models.ENDPOINT_ENV, MODEL)
    monkeypatch.setenv(models.MODEL_PRICE_ENV, f"{MODEL},0.000005,0.00002,2026-10-01")
    monkeypatch.delenv("CAOS_MODEL_CHOICES", raising=False)
    runtime.signed_in = False
    assert worker.main() == 2
    assert capsys.readouterr().err.strip() == "PROVIDER_NOT_CONFIGURED"


def test_the_production_smoke_takes_copilot_only_on_a_real_transport(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def ask(prompt: str, target: CopilotModel, seconds: float) -> list[Event]:
        text = '{"ok": true}' if "JSON" in prompt else "OK"
        counted = usage(inputTokens=10, cacheReadTokens=0, cacheWriteTokens=0)
        return [counted, answer(text)]

    scripted = completions(PRICE, chat=ChatCopilot(model=MODEL, ask=ask), endpoint=MODEL)
    monkeypatch.setattr(models, "from_environment", lambda: scripted)
    assert gateway_smoke.main() == 2
    monkeypatch.setattr("caos.copilot.ask_copilot", ask)
    real = completions(PRICE, chat=ChatCopilot(model=MODEL), endpoint=MODEL)
    monkeypatch.setattr(models, "from_environment", lambda: real)
    assert gateway_smoke.main() == 0
    assert "model=ChatCopilot" in capsys.readouterr().out
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest --no-cov -p no:xdist tests/test_copilot.py -q`
Expected: an `ImportError` for `require_ready`, then (after a stub) failures for the worker's missing check and the smoke refusing `ChatCopilot`.

- [ ] **Step 3: Implement readiness**

In `caos/copilot.py`:
- add `import sys` and `Iterable` (from `collections.abc`) to the imports;
- add `ModelInfo` to the `TYPE_CHECKING` import from `copilot`;
- append:

```python
def require_ready(models: Iterable[str]) -> None:
    """The Copilot models in `models` can be answered on this machine, or
    `PROVIDER_NOT_CONFIGURED` before any run is claimed (D77, D78): each
    `copilot:` model offered to the GitHub identity signed in here, enabled by
    its organisation's policy and pinned at an effort it takes, and a `copilot`
    executable on PATH for any `copilot-cli:` model. Each SDK model's prompt
    limit is printed: the host fact a model is chosen by. No runtime starts
    when no model is the SDK's, and no prompt is sent."""
    targets = [target for target in map(parsed, models) if target is not None]
    if any(t.platform == CLI_PLATFORM for t in targets) and shutil.which(CLI) is None:
        raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED)
    runtime = [target for target in targets if target.platform == PLATFORM]
    if not runtime:
        return
    try:
        signed_in, offered = asyncio.run(_offered())
    except ImportError:
        # The SDK is not installed here (D78): only `copilot-cli:` models run.
        raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED) from None
    by_id = {info.id: info for info in offered}
    for target in runtime:
        info = by_id.get(target.name)
        if not signed_in or info is None or not usable(info, target):
            raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED)
        limit = info.capabilities.limits.max_prompt_tokens
        print(f"copilot {target.name} max_prompt_tokens={limit}", file=sys.stderr)


def usable(info: ModelInfo, target: CopilotModel) -> bool:
    """Enabled by policy, and sent at an effort it takes -- or at none only
    when it takes none, because the runtime would apply its default (AR-15)."""
    enabled = info.policy is None or info.policy.state == "enabled"
    efforts = info.supported_reasoning_efforts or []
    if target.reasoning_effort is None:
        return enabled and not efforts
    return enabled and target.reasoning_effort in efforts


async def _offered() -> tuple[bool, list[ModelInfo]]:
    async with _client() as (client, _home):
        status = await client.get_auth_status()
        if not status.isAuthenticated:
            return False, []
        return True, await client.list_models()
```

- [ ] **Step 4: Wire it into the worker**

In `caos/graph/worker.py`, add `from caos.copilot import require_ready`. In `_configured()`, directly after `choices = model_choices()`, add:

```python
    # The Copilot models among them answer on this machine (D77, D78): ready
    # here, or refused before the store is touched or a run claimed.
    require_ready(choices)
```

- [ ] **Step 5: Accept Copilot in the production smoke**

In `scripts/gateway_smoke.py`:
- change the first docstring line to `"""One real call through the production model path (A31): AI Gateway or Copilot.`;
- add the docstring sentence "For a Copilot model the chat model is `ChatCopilot` on its real transport (D77, D78), never a scripted one.";
- replace the class check in `main()` with:

```python
    from caos.copilot import ChatCopilot
    from caos.models import from_environment

    provider = from_environment()
    chat = provider.chat
    kind = type(chat).__name__
    # The production model only: `ChatDatabricks` on an endpoint, or
    # `ChatCopilot` on a real transport for a Copilot model, never a scripted one.
    production = kind == "ChatDatabricks" or (
        isinstance(chat, ChatCopilot) and chat.ask is None
    )
    if not production:
        print(f"gateway_smoke: refused, chat model is {kind}", file=sys.stderr)
        return 2
```

In `scripts/qualify.py`'s docstring, after the existing example, add:

```text
    # The same set through GitHub Copilot on this machine (D77), or through
    # the CLI fallback (D78) with `copilot-cli:` in place of `copilot:`:
    CAOS_MODEL_ENDPOINT=copilot:gpt-6-luna \
    CAOS_MODEL_PRICE=copilot:gpt-6-luna,<in>,<out>,<YYYY-MM-DD> \
    scripts/qualify.py qualification/ccl-fy2025-market-dislocation \
        --expect-identity copilot/gpt-6-luna/none/65536 --ceiling 5.00
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest --no-cov -p no:xdist tests/test_copilot.py tests/test_workspace_stub.py -q`
Expected: all pass, with `test_the_gateway_smoke_passes_over_http_with_chat_databricks` unchanged.

Run: `CAOS_TEST_POSTGRES_URL=postgresql://postgres:local-test-admin-only@127.0.0.1:55437/postgres CAOS_REQUIRE_POSTGRES=1 uv run pytest --no-cov -n auto tests/test_worker.py tests/test_worker_in_process.py tests/test_health.py -q`
Expected: all pass, since non-Copilot choices start no runtime.

- [ ] **Step 7: Commit**

```bash
git add caos/copilot.py caos/graph/worker.py scripts/gateway_smoke.py scripts/qualify.py tests/test_copilot.py
git commit -m "Copilot 3/3: the worker refuses a Copilot model this machine cannot answer on"
```

---

### Task 6: The worker on a Windows PC

**Files:**
- Modify: `caos/graph/worker.py:547-549` (`install_stop_handler`; add `STOP_SIGNALS`)
- Modify: `caos/evidence/pdf.py:786` (`_limit_address_space`)
- Modify: `.gitattributes`
- Create: `tests/test_pc_worker.py`
- Modify: `docs/rebuild/decisions.md` (D79)

**Interfaces:**
- Consumes: nothing new.
- Produces: `caos.graph.worker.STOP_SIGNALS: tuple[signal.Signals, ...]`, used by `install_stop_handler(stopping: Event) -> None` (signature unchanged).

Three facts this task fixes, found on 2026-10-01:
- `install_stop_handler` handles only SIGTERM, which a Windows console never sends. Ctrl+C therefore raises `KeyboardInterrupt` mid-module instead of draining.
- `_limit_address_space` imports the POSIX-only `resource` module unguarded, so PDF extraction in the child process fails with `ImportError` on Windows.
- `vendor/deploy-v/**` and `icm/**` are `text: unspecified` (per `git check-attr`). Git for Windows converts their line endings by default, so `Bundle.verify_manifest()` and the host-integrity digests refuse on an analyst's clone.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pc_worker.py`:

```python
"""The worker on an analyst's PC (D79): console stop signals, a platform with
no `resource` module, and the byte-verified trees checked out unconverted."""

from __future__ import annotations

import signal
import subprocess
import sys
from threading import Event

import pytest

from caos.evidence import pdf
from caos.graph.worker import STOP_SIGNALS, install_stop_handler


def test_ctrl_c_only_asks_the_worker_to_stop() -> None:
    stopping = Event()
    previous = {stop: signal.getsignal(stop) for stop in STOP_SIGNALS}
    install_stop_handler(stopping)
    try:
        signal.raise_signal(signal.SIGINT)
        assert stopping.is_set()
    finally:
        for stop, handler in previous.items():
            signal.signal(stop, handler)


def test_every_stop_signal_the_platform_has_is_handled() -> None:
    assert signal.SIGTERM in STOP_SIGNALS
    assert signal.SIGINT in STOP_SIGNALS
    if sys.platform == "win32":
        assert signal.SIGBREAK in STOP_SIGNALS


def test_a_platform_with_no_resource_module_still_extracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "resource", None)
    pdf._limit_address_space(pdf._Inflater(1024))


@pytest.mark.parametrize(
    "path", ["vendor/deploy-v/CANON_SHARED.md", "icm/HOST_INTEGRITY_v1.json"]
)
def test_the_byte_verified_trees_are_never_converted(path: str) -> None:
    attributes = subprocess.run(
        ["git", "check-attr", "text", "--", path],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert attributes.strip() == f"{path}: text: unset"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest --no-cov -p no:xdist tests/test_pc_worker.py -q`
Expected: `ImportError: cannot import name 'STOP_SIGNALS'`. Once that is stubbed, the `resource` test fails with `ImportError` and the byte-pin test fails with `text: unspecified`.

- [ ] **Step 3: Implement**

In `caos/graph/worker.py`, replace `install_stop_handler`:

```python
# What stops a worker: SIGTERM from a platform, and Ctrl+C (SIGINT) or, on
# Windows, Ctrl+Break (SIGBREAK) from the console an analyst runs it in (D79).
STOP_SIGNALS: tuple[signal.Signals, ...] = tuple(
    getattr(signal, name)
    for name in ("SIGTERM", "SIGINT", "SIGBREAK")
    if hasattr(signal, name)
)


def install_stop_handler(stopping: Event) -> None:
    """A stop signal only sets `stopping`; the loop decides when that is safe."""
    for stop in STOP_SIGNALS:
        signal.signal(stop, lambda _signum, _frame: stopping.set())
```

In `caos/evidence/pdf.py`, inside `_limit_address_space`, replace `    import resource` with:

```python
    try:
        import resource
    except ImportError:
        # Windows has no `resource` (D79): the child is still bounded by its
        # deadline and the decoded-bytes budget, as it is on macOS.
        return
```

Append to `.gitattributes`:

```text
# Byte-verified where they are used (invariant 4; icm/HOST_INTEGRITY_v1.json):
# a checkout that converts line endings -- Git for Windows does by default --
# must still hold these bytes, or the worker refuses to start (D79).
vendor/deploy-v/** -text
icm/** -text
```

Then check that nothing in the index changes: `git add --renormalize . && git status --short`. Expected: only the files this task edited.

Do not add a Windows CI job. `scripts/check_gate_config.py` pins every job to `RUNS_ON = "ubuntu-latest"`, and widening that is a gate change only the owner can make (N125). The tests above run on Linux. Task 7's start of the worker on the analyst's PC is the Windows proof, because `_configured()` verifies the bundle manifest and the host prompts on that clone.

- [ ] **Step 4: Run the tests and the gate checks**

Run: `uv run pytest --no-cov -p no:xdist tests/test_pc_worker.py -q`
Expected: all pass.

Run: `CAOS_TEST_POSTGRES_URL=postgresql://postgres:local-test-admin-only@127.0.0.1:55437/postgres CAOS_REQUIRE_POSTGRES=1 uv run pytest --no-cov -n auto tests/test_worker.py tests/test_pdf_extraction.py -q && uv run python scripts/check_gate_config.py && uv run pre-commit run --all-files`
Expected: all exit 0.

- [ ] **Step 5: Record D79**

Append to `docs/rebuild/decisions.md`, using the next free D:

```markdown
- D79 (<YYYY-MM-DD>) — The worker on an analyst's Windows PC, where the Copilot seat is (D77, D78). Three facts stopped it: `install_stop_handler` handled SIGTERM only, which a console never sends, so Ctrl+C raised `KeyboardInterrupt` mid-module (it now handles SIGTERM, SIGINT and, on Windows, SIGBREAK, and only sets `stopping`); `caos/evidence/pdf.py` imported the POSIX-only `resource` module unguarded in the extraction child (it now returns, as on macOS, and the child stays bounded by its deadline and decoded-bytes budget); and `vendor/deploy-v/**` and `icm/**` were `text: unspecified`, so Git for Windows' default `core.autocrlf=true` changed the bytes the bundle manifest and `HOST_INTEGRITY_v1.json` verify (both are now `-text`). There is no Windows CI job: `scripts/check_gate_config.py` pins every job to `ubuntu-latest`, and widening it is the owner's call (N125). The worker's first start on the analyst's PC, which verifies the bundle and the host prompts on a Windows clone, is the Windows proof. Alternatives: WSL (one more install for IT to approve, and blocked on many managed PCs); a clone-time instruction alone (forgotten once, the worker refuses with an opaque bytes mismatch). Evidence: `tests/test_pc_worker.py`, and the PC run in the plan's Task 7.
```

- [ ] **Step 6: Commit**

```bash
git add caos/graph/worker.py caos/evidence/pdf.py .gitattributes tests/test_pc_worker.py docs/rebuild/decisions.md
git commit -m "Copilot 3/3: the worker runs on an analyst's Windows PC (D79)"
```

---

### Task 7: The runbook, the records and the live run

**Files:**
- Create: `docs/COPILOT_WORKER.md`
- Modify: `docs/rebuild/next.md` (N121–N125), `docs/rebuild/ENTERPRISE_HANDOFF.md` (§1), `docs/DEPLOYMENT.md` (section 1), `CLAUDE.md` (Layer 0 sentence, repo map)
- Modify (only if Step 4 hits a missing external resource): `docs/rebuild/blockers.md` (B13)

**Interfaces:**
- Consumes: Task 1's `SUMMARY.md` (auth methods, model ids, prompt limits, prices, CLI flags, over-limit behaviour).
- Produces: the runbook the analyst follows. No code.

- [ ] **Step 1: Write `docs/COPILOT_WORKER.md`**

Wherever the content below says **[Task 1 result]**, use the corresponding fact from Task 1's `SUMMARY.md`. Content:

````markdown
# The worker on an analyst's PC (GitHub Copilot)

AI Gateway is disabled in the enterprise workspace, so module calls go to GitHub Copilot (D77) from the one place a Copilot seat lives: the analyst's PC. Only the worker runs there. Lakebase keeps the queue, the attempt ledger and the checkpoints; the Unity Catalog volume keeps every byte; the API and UI run wherever the hosting decision puts them. A run advances only while a worker runs.

| Part | Where |
|---|---|
| Worker (`python -m caos.graph.worker`) and the Copilot runtime | The analyst's PC |
| Store, ledger, checkpoints | Lakebase (unchanged) |
| Sources and artifacts by digest | UC volume `caos_blobs` (unchanged) |
| API and UI | Unchanged by this page; they must approve the same models as the worker |

## 1. Decisions and grants first (owner and administrators)

- **Data:** Compliance confirms that issuer documents may be sent to the Copilot models chosen. Every prompt carries document text.
- **Seat and policy:** the analyst holds a Copilot Business or Enterprise seat, and the organisation's policy enables Copilot CLI (both transports run its runtime) and each chosen model.
- **Spend:** a Business seat includes 1,900 AI credits ($19) a month and an Enterprise seat 3,900 ($39), and one LITE run on Claude Opus can use more. The owner sets a GitHub budget for overage. Each run's CAOS ceiling still applies.
- **Network from the PC:** HTTPS to the workspace, TLS Postgres to the Lakebase endpoint's host on port 5432, and HTTPS to GitHub's Copilot endpoints.
- **Lakebase:** the analyst's Databricks identity needs a Postgres role on the project. If the app's service principal created `caos_store` and `caos_graph`, it (or a Lakebase administrator) grants:
  ```sql
  GRANT USAGE ON SCHEMA caos_store, caos_graph TO "<analyst's Databricks user name>";
  GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA caos_store, caos_graph TO "<analyst's Databricks user name>";
  GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA caos_store, caos_graph TO "<analyst's Databricks user name>";
  ```
  With no app deployed, the analyst's role creates both schemas on the worker's first start, and no grant is needed.
- **Volume:** `READ VOLUME` and `WRITE VOLUME` on `<catalog>.<schema>.caos_blobs` for the analyst.

## 2. Install (once)

1. Install Git, `uv`, the Databricks CLI and the GitHub Copilot CLI from IT's approved sources.
2. Run `git clone <the enterprise repository>`, then `uv sync --locked --no-dev` in the clone; `uv` brings Python 3.13. If the SDK package may not be installed here, use `uv sync --locked --no-dev --no-install-package github-copilot-sdk` instead and follow section 6.
3. Run `databricks auth login --profile caos --host <workspace URL>`.
4. Provision the SDK's runtime once: `uv run python -m copilot download-runtime`. Then set `COPILOT_SKIP_CLI_DOWNLOAD=1` permanently, so nothing is downloaded at run time.
5. Sign in to Copilot. **[Task 1 result: keep exactly the one of these two lines that worked]**
   - Run `copilot login`; both transports use that sign-in.
   - Set `COPILOT_GITHUB_TOKEN` in the worker's environment to a fine-grained token with the "Copilot Requests" permission.

## 3. Price each model

GitHub publishes each model's dollar rates per million tokens (docs.github.com, "Models and pricing for GitHub Copilot"). `list_models` reports the same rates in AI credits, at 1 credit = $0.01.

- **Per token:** input is `max(input, cache write) / 1,000,000` and output is `output / 1,000,000`. Where a model's rates rise above a context length, use the higher tier, because the worker asks for the long-context tier.
- **Example:** Claude Opus 5.5 on 2026-10-01 cost $4.00 input, $5.00 cache write and $20.00 output per million, which gives `copilot:<opus id>@high,0.000005,0.00002,2026-10-01`.
- **Ceiling:** one worst-case call at that price is 4 MiB × 0.000005 + 65,536 × 0.00002 = 22.28224, and the run ceiling must cover it.

Choose models by prompt limit. The worker prints each SDK model's `max_prompt_tokens` at start. **[Task 1 result: the candidates' limits under `long_context`.]** A module whose prompt exceeds the limit is **[Task 1 result: refused 400/413 before billing | billed and refused]**, and the run parks. CP-0 sends whole filings, so a large 10-K needs the 1M tier.

## 4. Run the worker

PowerShell, in the clone:

```powershell
$env:DATABRICKS_CONFIG_PROFILE = "caos"
$env:CAOS_LAKEBASE_ENDPOINT = "projects/<project>/branches/production/endpoints/primary"
$env:PGHOST = "<the endpoint's host>"
$env:PGPORT = "5432"
$env:PGDATABASE = "databricks_postgres"
$env:PGUSER = "<your Databricks user name>"
$env:CAOS_BLOB_ROOT = "volume:///Volumes/<catalog>/<schema>/caos_blobs"
$env:CAOS_MODEL_ENDPOINT = "copilot:<model>[@<effort>]"
$env:CAOS_MODEL_PRICE = "copilot:<model>[@<effort>],<in>,<out>,<YYYY-MM-DD>"
$env:CAOS_RUN_CEILING = "100.00"
$env:COPILOT_SKIP_CLI_DOWNLOAD = "1"
uv run --no-sync python scripts/gateway_smoke.py
uv run --no-sync python -m caos.graph.worker
```

- **Smoke:** one paid call of a few tokens. It must print `model=ChatCopilot ... json_mode=accepted`.
- **Start:** the worker prints `copilot <model> max_prompt_tokens=<n>` for each SDK model. It exits 2 with `PROVIDER_NOT_CONFIGURED` when Copilot is not ready (not signed in, model not enabled, effort not taken, CLI missing for a `copilot-cli:` model, SDK missing for a `copilot:` model), or with `STORE_UNAVAILABLE` when Lakebase is unreachable or the role is missing.
- **Stop:** Ctrl+C stops it after the module in flight. Closing the window kills it; the run's lease then expires after 900 s (D117) and the next worker resumes it, with no attempt run twice.

## 5. What this does not do

- No run advances while no worker runs, and one worker spends one Copilot seat.
- There is no in-app chat (Query) until RAI is onboarded.
- Hosting the API and UI with Copilot models is a separate step (N124).

## 6. Fallback: the Copilot CLI (D78)

Use this when the SDK package or its runtime may not be installed or will not start. Name each model `copilot-cli:<model>[@<effort>]` in `CAOS_MODEL_ENDPOINT`, `CAOS_MODEL_PRICE` and the API's approved models, priced exactly as in section 3. The worker then runs the `copilot` executable on `PATH` once per module call:
- the prompt goes on stdin;
- the events come back as JSON lines;
- no tools are offered, and no custom instructions or self-update are used;
- each call runs under a private `COPILOT_HOME` that is removed afterwards.

How it differs from the SDK:
- **System prompt:** Copilot's own system prompt wraps every call, because no flag replaces it. A `copilot-cli:` model is therefore a different execution profile (`copilot-cli/<model>/<effort|none>/65536`) and must be qualified on its own (`scripts/qualify.py --expect-identity copilot-cli/...`).
- **Pricing allowance:** each request is priced with 64 KiB added for that system prompt.
- **Output cap:** output is capped at the model's own limit, not 65,536 tokens. An answer past 65,536 is billed as unknown and refused.
- **Not automatic:** CAOS never switches a run between transports. A run started on `copilot:` stays on `copilot:`.

If the SDK package is installed but its runtime is not approved, a third option is to point the SDK at the IT-installed executable with `COPILOT_CLI_PATH=<path to copilot>` instead of step 2.4. This works only if that executable speaks the SDK's protocol version: run the smoke to check.
````

- [ ] **Step 2: Records**

Append to `docs/rebuild/next.md`, re-reading it first for the next free N (ids as of `25b4ca2`):

```markdown
- N121 (<date>; D77) — An in-memory session filesystem (`session_fs`) if no prompt may touch the PC's disk even for the length of its call (today a private temp directory, removed after the call; a crash can leave it).
- N122 (<date>; D77) — One long-lived Copilot client per worker if the runtime's start-up (Task 1: seconds per call) shows in node latency.
- N123 (<date>; D77) — Reconcile each call's charge against GitHub's own figure (`copilotUsage.totalNanoAiu` on `assistant.usage`), stored per attempt.
- N124 (<date>; D77) — Hosting with Copilot models: the bundle's `model_endpoint` serving-endpoint resource and `CAN_QUERY` grant, `scripts/preflight.py`'s endpoint checks and `scripts/enterprise_deploy.sh` rows E1/E10 assume a gateway endpoint; an App whose approved models are Copilot's needs them made conditional. Pending the hosting answer.
- N125 (<date>; D79) — A Windows CI runner for the PC worker's tests: `scripts/check_gate_config.py` pins every job to `ubuntu-latest` (`RUNS_ON`), so a `windows-latest` job is a gate change for the owner to approve. Until then, the worker's start on the analyst's PC is the Windows proof (D79).
```

Then update the pointers:
The 2026-10-01 initialisation already wrote status notes and the "No other provider" bullet that say Copilot is *being built*. Now say it is built:
- In `docs/rebuild/ENTERPRISE_HANDOFF.md`, replace the 2026-10-01 status note with: "AI Gateway is disabled in the enterprise workspace (B12). Model calls go to GitHub Copilot from a worker on the analyst's PC: follow `docs/COPILOT_WORKER.md` in place of the steps here that need a serving endpoint (D77–D79)." In "No other provider", replace "once D77 is built, " with nothing. Append "A Copilot model's effort is part of its name (D77)." to "No reasoning-effort setting".
- In `docs/DEPLOYMENT.md`, replace the status note's last two sentences with a pointer to `docs/COPILOT_WORKER.md` (D77–D79), and add a row to section 1 after the endpoint rows: "Workspace without AI Gateway | — | Module calls go to GitHub Copilot from a worker on the analyst's PC: `docs/COPILOT_WORKER.md` (D77–D79)."
- In `CLAUDE.md`, change Layer 0's "so the factory is gaining GitHub Copilot as the model, answered on the worker's machine (D77); that build is `docs/superpowers/plans/2026-10-01-copilot-sdk-adapter.md`" to "so GitHub Copilot is the model there, answered on the worker's machine (D77–D79, `docs/COPILOT_WORKER.md`)". In the repo map, after `models.py` (the model factory), add `copilot.py` (the Copilot transports).

- [ ] **Step 3: Gates and Copilot 3/3**

Run the full gate list in `CLAUDE.md`, then `uv run python scripts/check_pr_size.py <Copilot 2/3's branch>`. Expected: all exit 0.

```bash
git add docs/COPILOT_WORKER.md docs/rebuild/next.md docs/rebuild/ENTERPRISE_HANDOFF.md docs/DEPLOYMENT.md CLAUDE.md
git commit -m "Copilot 3/3: the analyst-PC runbook and the records (D77-D79)"
```

Open **Copilot 3/3**, stacked on 2/3, only when the owner asks.

- [ ] **Step 4: Live verification (owner-authorised spend, on the PC)**

Ask the owner for an amount first: pennies for the smokes, plus a ceiling for one qualification run on the cheapest model whose limit fits. **$5.00** is proposed.

1. Follow `docs/COPILOT_WORKER.md` §2–§4 on the PC. Expected:
   - the smoke prints `model=ChatCopilot`, a known charge and `json_mode=accepted`;
   - the worker prints `copilot <model> max_prompt_tokens=<n>` and runs. Its start verifies the bundle and the host prompts on this Windows clone, which is D79's Windows proof;
   - `/api/health` reports workers OK wherever the API runs.
2. Repeat the smoke with `CAOS_MODEL_ENDPOINT` and `CAOS_MODEL_PRICE` naming `copilot-cli:<the same model>`. Expected: the same three facts.
3. On a machine with Docker Postgres and the same Copilot sign-in, run:

   ```bash
   CAOS_QUALIFY_POSTGRES_URL=<persistent server> \
   CAOS_QUALIFY_BLOB_ROOT=<kept directory> \
   CAOS_MODEL_ENDPOINT=copilot:<luna id> \
   CAOS_MODEL_PRICE=copilot:<luna id>,<in>,<out>,<date> \
   uv run python scripts/qualify.py qualification/ccl-fy2025-market-dislocation \
     --expect-identity copilot/<luna id>/none/65536 --ceiling 5.00
   ```

   Record the outcome in `qualification/PROVIDER_RUNBOOK.md`: per node, the code, the charge, and the largest prompt's tokens against the model's limit.
4. If an external resource is missing (port 5432 blocked, Lakebase role absent, Copilot CLI policy off), add **B13** to `docs/rebuild/blockers.md` with the exact command and error. Correct the runbook to the commands that actually ran, then commit:

```bash
git add docs/COPILOT_WORKER.md qualification/PROVIDER_RUNBOOK.md docs/rebuild/blockers.md
git commit -m "Copilot 3/3: the runbook as it ran on the analyst's PC"
```

---

## Out of scope (named so nothing is silently dropped)

- **Hosting** the API and UI as a Databricks App with Copilot models (N124), pending the hosting answer. Until then the API runs wherever it does today, approving the same models as the worker.
- **The in-app Query chat**: it needs a server-side model, which means RAI after onboarding (a later provider behind the same factory).
- **Copilot as orchestrator** (skills per module, Delta over ODBC): rejected in D77.
- **An automatic SDK-to-CLI fallback**: rejected in D78 (two execution profiles in one run).
- **Two analysts' workers at once**: this already works through leases, but each worker spends its own seat. No change is needed.

## Spec coverage (self-review)

| Design point | Task |
|---|---|
| 1 Name grammar | 2 (`copilot:`), 4 (`copilot-cli:`) |
| 2 Dispatch and identity | 3, 4 |
| 3 SDK session posture | 3 (`session_options`, `_client`) |
| 4 One reply mapping | 2 (`reply_message`, `_exact`, `_data`) |
| 5 Charge | 2 (`_usage`), 3 (through `ChatCompletions`), 4 (CLI allowance), 7 (price derivation) |
| 6 Errors | 2 (`CopilotStatusError`), 3 (SDK timeout and error), 4 (CLI timeout, exit, missing) |
| 7 Readiness | 5 |
| 8 Where things run | 6, 7 |
| 9 Dependency | 2, 5 (SDK absent), 7 (`--no-install-package`) |
| 10 CLI fallback | 4 (code, review, D78), 7 (runbook §6) |
| Gating risks | 1 |
| Re-spec R1–R7 (2026-10-06, revision 2) | 2–7, and the firm-seat spike (N177) |

---

## Re-spec of 2026-10-06 (owner: re-spec now, build with fakes)

**Why.** Task 1 ran on the owner's personal seat on 2026-10-06 (`docs/rebuild/runs/copilot-spike-2026-10-06/SUMMARY.md`, git-ignored) and stopped at its gating risks: the SDK in empty mode authenticated with the GitHub CLI's token (`authType` `gh-cli`) and listed no model; the seat offers one model (`mai-code-1.1-flash`, routed `auto_v2` when no `--model` is given); the CLI's JSON lines carry no `assistant.usage`, and billing arrives as AI units on `session.usage_checkpoint` (`totalNanoAiu` 251,164,000 and `totalPremiumRequests` 1 for one tiny prompt); and every `assistant.message` carries `serverTools: {"provider": "openai-responses"}`, which Design 4 would have refused. The owner decided on 2026-10-06 that Copilot replaces the AI Gateway as the production model transport, that the adapter is re-specified now against the SDK's own types, and that it is built against fakes generated from those types, with the firm-seat measurements deferred (N177, section R6). This section supersedes what it changes in Design 3–7 and 10 and Tasks 2–7. Everything it does not name stands: Design 1–2, 8–9, the Global Constraints, the invariants, the three stacked PRs, and Task 1's script.

**Revision 2 (2026-10-06, after an adversarial review of revision 1).** Seven findings are closed in the rules below and marked where they land: (1) the CLI transport's auth cage and proof (R3); (2) spend on a failed call is billed, never a re-attempted drop, and a runtime-recovered answer is not re-paid (R2.10); (3) the reservation's bound prices every cache-write tier, the CLI's output cap and the pinned price are checked at readiness, `max_ai_credits` is named a non-bound, and the nano-AIU conversion is an assumption (R2.1, R2.5, R2.7, R6); (4) a park after `BUDGET_CHARGE_OVER_RESERVATION` is terminal for its pin, the credit price is stored on the reservation, and zero AI units on an answered call is an unknown charge (R2.2, R2.3, R2.6); (5) the model proof adds the CAPI witness, refuses `isByok` unknown and any fusion attribution, is an allow-list of event types, and refuses `serverTools` and `session.auto_mode_resolved` outright (R1); (6) both transports run under one environment allow-list and a tool-free session posture, with a restricted `PATH` (R3, R7); (7) the SDK's logger is silenced so the runtime's stderr never reaches the worker's (R7). Two low findings: R3 is based on the runtime the SDK runs (1.0.90) beside the CLI the spike captured (1.0.92), and `totalPremiumRequests` is a `Decimal`.

**Authority for the schema.** `github-copilot-sdk==1.0.16` as locked (D77, addendum: dependency): `copilot.generated.session_events` (`SessionEventType` and the `*Data` classes), `copilot.generated.rpc` (`ModelBilling`, `ModelBillingTokenPrices`, `ModelBillingTokenPricesLongContext`, `ModelCapabilitiesLimits`, `ModelPolicy`, `AuthInfoType`) and `copilot.client` (`ModelInfo`, `GetAuthStatusResponse`, the runtime start). The SDK runs the runtime it downloads, `copilot._cli_version.CLI_VERSION` = `1.0.90` (GitHub release, checksum-verified), while the IT-installed CLI the spike captured is 1.0.92; both are pinned here, and where their help differs the runtime's own capture governs the SDK transport (R6 re-captures both). Wire field names are the camelCase keys `to_dict()` writes, and a fake is valid only when the SDK's own `from_dict` accepts it. The envelope `SessionEvent.to_dict()` writes is `{"type", "data", "id" (a UUID string), "timestamp", "parentId", "agentId"?, "ephemeral"?}`. The CLI's `--output-format json` prints the same objects one per line beside lines that are not session events (the spike saw a `result` line).

### R1. Reply mapping (Design 4), against the schema

One call's events become one `AIMessage`. A finish reason is stated only when all of the following hold (the call was exactly the one asked for); otherwise none is stated, the call keeps its bill (R2) and `ChatCompletions` refuses it `PROVIDER_RESPONSE_INVALID` (F34), as before.

0. **An allow-list of event types.** The mapping reads only these types, and any other type present refuses the finish reason and keeps the bill: `session.start`, `session.idle`, `session.shutdown`, `session.info`, `session.warning`, `session.title_changed`, `session.usage_info`, `session.usage_checkpoint`, `session.model_change` (only when `newModel == target.name`), `session.tools_updated` (only with an empty tool list), `session.mcp_servers_loaded` and `session.mcp_server_status_changed` (only with no server), `session.skills_loaded`, `session.extensions_loaded` and `session.custom_agents_updated` (only empty), `session.managed_settings_resolved`, `session.managed_settings_enforced`, `user.message`, `assistant.turn_start`, `assistant.turn_end`, `assistant.turn_retry`, `assistant.idle`, `assistant.reasoning`, `assistant.message`, `assistant.usage`, `model.call_start`, `model.call_finished`, `model.call_final_result`, `model.call_failure`, `session.error`, `prompt_cache_break`. Named as refusing, so a build cannot admit them by mistake: `session.auto_mode_resolved`, `session.model_deselected`, `auto_mode_switch.*`, `session.auto_tier_*`, `session.fusion_*`, `assistant.fusion_*`, `assistant.server_tool_progress`, `tool.*`, `tool_search.activated`, `skill.*`, `hook.*`, `sampling.*`, `external_tool.*`, `workflow.run_*`, `subagent.*`, `permission.*`, `user_input.*`, `elicitation.*`, `mcp.*`, `session.truncation`, `session.compaction_*`, `session.context_cleared`, `session.handoff`, `session_limits_exhausted.*`, `session.completion_receipt`, `session.binary_asset`, `command.*`, `unknown`. The CLI's `result` line is not a session event and is ignored by `printed_events` (a line with a `type` of `result`), never read. The firm-seat spike (R6) records every type a plain smoke emits; the owner extends the allow-list on that evidence only.
1. **Exactly one answer, naming the pin.** Exactly one `assistant.message` (`AssistantMessageData`) whose `data.model` (`str | None`) equals `target.name`, with no `data.fusion` (`FusionAttribution`, a synthetic multi-model turn). An absent `model` is no proof: no finish reason.
2. **Exactly one settled model operation, naming the pin.** Exactly one `model.call_final_result` (`ModelCallFinalResultData`, "one logical model operation after all orchestrator-owned retries settle") with `data.model == target.name`, `data.result == "success"` and `data.isByok` exactly `False` (`None` is unknown, and unknown refuses). Two such events are two operations. Every `model.call_finished.data.outcome` present must be `success`, and no `model.call_start` or `model.call_failure` may carry `data.fusion`.
   The proof that the pinned model answered is therefore the conjunction of `assistant.message.model` **and** `model.call_final_result.model`, each equal to the pin, **and**, whenever a usage event is present, its two names in 3. `assistant.usage.model` is never the only witness.
3. **`assistant.usage`, when present, agrees.** The SDK transport may deliver `assistant.usage` (`AssistantUsageData`); the CLI 1.0.92 did not. When present: at most one; `data.model == target.name`; `data.copilotUsage.model`, the CAPI-sourced witness (`AssistantUsageCopilotUsage.model`, `str | None`), equal to `target.name` when `copilotUsage` is present; `isAuto` falsy; `isByok` exactly `False`; `availableToolCount` falsy; no `fusion`; `reasoningEffort` read by `_effort` equals `target.reasoning_effort` (AR-15); `contentFilterTriggered` not true. Its token counts fill `usage_metadata` as Design 5 wrote them (input + `cacheReadTokens` + `cacheWriteTokens`; output), and its `finishReason` is read as before: `end_turn` and `stop_sequence` become `stop`, `max_tokens` becomes `length`, `refusal` becomes `content_filter`, anything else passes through to be refused.
4. **Not auto-routed.** `session.auto_mode_resolved` (`SessionAutoModeResolvedData`, "the concrete model the session settled on for the first prompt of an auto-mode session") present at all means the pin was not applied: refused, whatever `chosenModel` says. A `session.model_change` whose `newModel != target.name`, and every event 0 names as refusing, refuses.
5. **`serverTools` refuses.** `AssistantMessageServerTools` is typed as a "neutral provider-tagged server-side tool-use payload (tool search, advisor)" with `provider: str` required and `advisorModel`, `functionCallNamespaces`, `items`, `rawContentBlocks` optional; the value the spike saw, `openai-responses`, appears nowhere in the SDK. Any `serverTools` present refuses the finish reason, as does a non-empty `toolRequests`. If the firm-seat spike (R6) shows a bare `{"provider": <wire api>}` on every answer of a model family with `items`, `rawContentBlocks`, `functionCallNamespaces` and `advisorModel` always absent, the owner may admit exactly that shape for exactly those families; until then it is a refusal, and a build that admits it is wrong.
6. **One prompt, one logical operation.** A `session.truncation`, `session.compaction_*`, `session.context_cleared`, `session.handoff`, `session_limits_exhausted.*` or `subagent.*` event refuses (0). `assistant.turn_retry` ("an additional model inference attempt within an existing assistant turn") and a `model.call_failure` **followed by** the one `model.call_final_result` with `result == "success"` are the runtime's own recovery inside one logical operation (the SDK's `ModelCallFinishedData` doc: "a logical dispatch may include internal reconnect or fallback work"); they do not refuse while 1–3 hold, the model witnesses rule out a fallback model, and the one checkpoint bills the whole operation (R2). R6 measures how often they occur.
7. **Finish reason without `assistant.usage` (the CLI).** When no `assistant.usage` is present, `stop` is stated when 0–6 hold and the session ended with an `assistant.turn_end` and a `session.idle` whose `aborted` is not true. `length` is stated instead when `assistant.message.data.outputTokens` (`int | None`) is present and at least the output cap of R2.5. Nothing else is derived; the executor still validates the envelope (invariant 9).
8. **The call id.** `response_metadata["id"]` is `assistant.usage.providerCallId` or `apiCallId` when a usage is present, else `assistant.message.data.apiCallId`, `requestId` or `serviceRequestId`, the first that is a non-empty string; none means a host-minted id (`HOST_MINTED`).

**Errors (Design 6), against the schema.** These apply only to a call with no spend and no answer (R2.10 decides which):

- `session.error` (`SessionErrorData`: `errorType: str`, `message: str`, `statusCode: int | None`, `errorCode`, `providerCallId`) raises `CopilotStatusError(status_code)`; `message`, `stack` and `url` never travel.
- `model.call_failure` (`ModelCallFailureData`: `failureKind` `api | transport`, `statusCode: int | None`, `badRequestKind` `bodyless | structured_error` on a 400, `errorMessage`) with no `session.error` after it and no `model.call_final_result` `success` after it ends the call: `failureKind == "api"` with a status raises `CopilotStatusError(status_code)`; `failureKind == "transport"`, or no status, raises `CopilotStatusError(None)`, undeclared.
- A `model.call_final_result.data.result` other than `success`, with no status from either event, supplies one: `http_400` is 400, `http_413` is 413, `http_429` is 429 (re-sent under the same reservation), `http_4xx` and `http_5xx` are declared with no status, `transport_error` and `other_error` are undeclared.
- D110 (and D118 where it has merged) decide the re-attempt from `DropKind`. `CopilotStatusError(status_code, *, declared)` therefore carries `status_code` and, for a declared failure with no status, a non-text `body` mapping `{"error": {"result": "<the enum value>"}}` that `models._declared` reads as declared; an undeclared one carries neither. `NEVER_RETRIED` and the 429 re-send apply unchanged. `errorType` and `errorCode` reach the F513 stderr line only through `_name` and `_status` (an identifier or digits, else `?`).
- A `session.idle` with `aborted: true`, or a session that ends with none of `session.idle`, `session.error` or `model.call_failure` inside the deadline, is indeterminate (`TimeoutError`), as before.

### R2. Charge (Design 5) when billing is in AI units

**Facts from the types.** `SessionUsageCheckpointData.totalNanoAiu: float` ("durable session usage checkpoint for reconstructing aggregate accounting on resume") and `totalPremiumRequests: float | None`; `AssistantUsageCopilotUsage.totalNanoAiu` per request ("from the CAPI copilot_usage response field") with `model` and `tokenDetails[]` of `{batchSize, costPerBatch, tokenCount, tokenType, model}`; `AssistantUsageData.inputTokens`, `cacheReadTokens`, `cacheWriteTokens`, `outputTokens`, `reasoningTokens` and `cost: float | None`; `SessionLimitsExhaustedRequestedData.usedAiCredits` and `maxAiCredits`. The unit: `AutopilotObjectiveCreditLimit` documents `creditsUsed` as "fractional AI credits" beside `creditsUsedNanoAiu`, "exact window consumption in non-negative integer nano-AIU", so one AI credit is read as 1,000,000,000 nano-AIU. **That ratio is an assumption until R6 measures it** against a call whose credits the seat's own `/usage` display states; the per-token prices in `ModelBillingTokenPrices` (`inputPrice`, `cacheReadPrice`, `cacheWritePrice`, `cacheWrite1HPrice`, `outputPrice`, `batchSize`, `contextMax`, `maxPromptTokens`, and the same under `longContext`) are read as credits per `batchSize` tokens, also an assumption R6 measures. The SDK's session cap, `create_session(session_limits={"max_ai_credits": ...})` (the CLI's `--max-ai-credits`), has a 30-credit floor and is documented as "a soft cap: usage is known only after a model response returns": **it is not a bound** and nothing here relies on it. The dollar value of a credit is not in the types; GitHub's published $0.01 (Design 5) becomes the operator's dated pin (2).

1. **The reservation bounds the bill, as today.** Before the call the attempt reserves `priced_request(price, request_bytes, output_tokens=copilot.output_cap(model))` at the operator's pinned per-token `ModelPrice` (with `CLI_OVERHEAD_BYTES` added for `copilot-cli:`), so D29's admission, `worst_case` and the ceiling work unchanged. The operator prices a Copilot model so that the per-token reservation is never below the AI-unit bill: per input token the greatest of `inputPrice`, `cacheReadPrice`, `cacheWritePrice` and `cacheWrite1HPrice` across both the base and the `longContext` tier, and per output token the greater of the two tiers' `outputPrice`, each times `billing.multiplier` (1 when absent), with `discountPercent` and `promo` ignored because a discount can end mid-run. **Readiness checks the pin:** for each offered approved model it derives those two figures from the listing, `price_per_batch / batchSize x credit_price x multiplier`, in `Decimal`, and refuses `PROVIDER_NOT_CONFIGURED` when the pinned `input_per_token` or `output_per_token` is below its figure, printing both on the model's line. A `copilot-cli:` model, which never lists, is checked the same way when the SDK is installed and is otherwise the operator's word (printed `price_check=-`).
2. **The credit price is a pin, stored with the reservation.** `CAOS_COPILOT_CREDIT_PRICE=<usd per AI credit>,<YYYY-MM-DD>` is read once at worker start by `caos.copilot.credit_price()` as a `Decimal` validated by `validate_spend` and a date, and refused `PROVIDER_NOT_CONFIGURED` when any approved model is a Copilot model and it is absent or malformed. Migration `0047_reservation_credit_price` adds `credit_price numeric` and `credit_as_of date` to `budget_reservations` (both or none), which `reserve` writes from the process's pin for a Copilot model and `reserved_for` reads back as `Reservation.credit`; the settled charge (3) and the over-reservation check (6) use the reservation's credit price, never the environment's, so a redeploy cannot change a live run's charge (F468's rule for the per-token price, 0043, applied to the credit). A reservation with no credit price cannot settle a Copilot call: the charge is unknown and the call is refused.
3. **The settled charge is the call's AI units.** `charge = nano_aiu x credit_price / 1,000,000,000`, computed in `exact_context()` from `Decimal(nano_aiu)` and passed through `reported_charge`. `nano_aiu` is the last `session.usage_checkpoint.data.totalNanoAiu` of the session (it is cumulative, so the last one), accepted only as a whole number (an `int`, or a float for which `is_integer()` holds, below 2**53) that is **greater than zero on an answered call**: zero, as `_charge` reads a zero count, is a figure the runtime never stated. Anything else is an unknown charge, so the call is billed unknown and refused `PROVIDER_RESPONSE_INVALID` with its reservation kept (`_completion`, unchanged). No checkpoint, no charge. When per-request `assistant.usage.copilotUsage.totalNanoAiu` figures exist their sum must not exceed the checkpoint's total; an excess is a request the checkpoint missed, and the charge is unknown. `totalPremiumRequests`, when present, is read as `Decimal(str(value))` (it can be fractional) onto the bill line, never money: a seat on the legacy premium-request platform bills by the seat, the ledger still records the AI-unit figure, and N123 reconciles.
4. **Where it lands.** `reply_message` puts `nano_aiu` (int) and `premium_requests` (a decimal string or None) into `response_metadata`. `ChatCompletions._completion` takes the charge from `copilot.settled_charge(message, reservation.credit)` when the model is a Copilot name and the metadata carries `nano_aiu`, and from `_charge` as today otherwise; a Copilot message with no `nano_aiu` is an unknown charge even when it carries token counts, because the tokens are not the bill.
5. **The bound, and the CLI's output.** Token counts exist in the types (`AssistantUsageData`, `AssistantMessageData.outputTokens`), so when an `assistant.usage` is present `_charge`'s bound still applies to them as a validity check: prompt tokens no more than request bytes, output no more than `copilot.output_cap(model)`, else the usage is unknown and the call is refused. `output_cap` is `MAX_COMPLETION_TOKENS` for an SDK model (the session sets `model_capabilities.limits.max_output_tokens`) and, for a `copilot-cli:` model, which the CLI caps at the model's own limit (Design 10), the pinned `caos.copilot.CLI_OUTPUT_TOKENS[<model id>]`, the listed `capabilities.limits.maxOutputTokens` the operator copies in; a `copilot-cli:` name with no entry refuses `PROVIDER_NOT_CONFIGURED` at readiness, so its reservation prices the output the CLI can actually return (Design 5's "bound stays" holds with that cap in place of 65,536, and `identity_of` keeps `65536` only for `copilot:`; a `copilot-cli:` identity ends in its cap). With no token counts the bound used is the reservation itself (6).
6. **Above the reservation: typed, never silent, terminal for the pin.** After the call, in the executor beside `_within_reservation` (a new `_settled_within(conn, taken, completion)` ahead of `_billed_once`), a known `completion.charge` greater than `taken.amount` is recorded in full in `budget_ledger` (the money was spent: "a ceiling checked afterwards is an invoice"), and the attempt is then refused `BUDGET_CHARGE_OVER_RESERVATION` (a new `RefusalCode`): the answer is not accepted, one stderr line reads `BUDGET_CHARGE_OVER_RESERVATION reserved=<d> charged=<d> nano_aiu=<n>`, and the run parks. The pinned per-token price no longer bounds the AI-unit bill, and because the run's price is pinned (F468) a requeue would reserve the same way and overshoot the same way: **the park is terminal for the pin.** `requeue` refuses `BUDGET_CHARGE_OVER_RESERVATION` for a run parked by it; the operator re-prices the model (1), restarts the worker (readiness now checks the pin), and starts a successor run (`supersedes_run_id`) on the re-priced model. `remaining` already counts `greatest(reserved, charged)`.
7. **The SDK-side cap is a guard, not a bound.** `session_options` sets `session_limits={"max_ai_credits": credits}` and `cli_arguments` adds `--max-ai-credits <credits>`, with `credits = max(30, ceil(reserved / credit_price))` read from `caos.provider.reserved_amount`, a `ContextVar` the executor sets around `complete` through `reserving(amount)` (the `resend_checked` pattern); a call with no reservation in scope sends none. It limits a runaway session after the fact and nothing in R2 depends on it; the reservation (1) and the settled check (6) are the bound.
8. **Cross-check against per-token prices (diagnostic).** When an `assistant.usage` with token counts is present and readiness listed the model's prices, `expected_nano = sum(tokens x price) / batchSize x 10**9 x multiplier` is printed beside `nano_aiu` on the bill line as `AIU_CROSSCHECK model=<id> nano_aiu=<n> expected_nano_aiu=<n> tokens=<in>/<cr>/<cw>/<out>`. It changes no outcome until the firm-seat spike (R6) has measured the unit `costPerBatch` is stated in; it becomes a refusal bound when it has.
9. **Decimal throughout.** Every figure above is a `Decimal` under `exact_context()` (invariant 7). A float from the wire is converted only after the whole-number check in 3 and is never multiplied as a float.
10. **Spend on a failed call is billed, never a re-attempted drop (invariants 6 and 8; D110, D118; migration 0046).** A failed session can carry spend: the runtime's internal retries, or a `model.call_failure` whose operation is later recovered. The rule, applied in `ChatCopilot._generate` before any error is raised: when the session's events carry a checkpoint with `nano_aiu > 0`, or any `assistant.message`, the call is **not a drop**. It is returned as a message (never raised), and `ChatCompletions` bills it from the checkpoint (3; an absent or zero checkpoint beside an `assistant.message` is an unknown charge) and refuses it `PROVIDER_RESPONSE_INVALID` unless R1 states a finish reason, with `drop_kind` `None`: `call_outcomes` holds the charge (`charged_attempt_id` set) and no `drop_kind`, which is exactly what 0046's `call_outcomes_drop_unanswered` CHECK allows, and D110's `drop_reattempt_due`, which reads `drop_kind`, never re-attempts it. A runtime-recovered answer (a 503, then the one `model.call_final_result` `success` and one `assistant.message`) is therefore an ordinary answered call under R1.6, billed once from its checkpoint and never raised or re-paid. Only a session with no answer and no spend reaches the Errors rules of R1 and the `DropKind` path; a declared one earns D110's single re-attempt, as before.

### R3. Auth and isolation (Design 3, 7 and 10)

**Precedence, from the SDK source and the runtime's own help.** `CopilotClient(github_token=...)` "takes priority over other auth methods" (`client.py`): the runtime is started with `--auth-token-env COPILOT_SDK_AUTH_TOKEN` and that variable set. `use_logged_in_user` defaults to `not bool(github_token)`, and when it is false the runtime is started with `--no-auto-login`. `base_directory` becomes the runtime's `COPILOT_HOME`, and mode `empty` sets `COPILOT_DISABLE_KEYTAR=1` ("disable the runtime's system keychain probe"). Inside the runtime (`copilot help environment`, CLI 1.0.92; the review's capture of runtime 1.0.90 says the same): `COPILOT_GITHUB_TOKEN`, `GH_TOKEN` and `GITHUB_TOKEN`, in that order, "take precedence over previously stored credentials"; the stored credential is the `copilot login` sign-in, in the keychain or under `COPILOT_HOME`; last comes auto-login, which took the GitHub CLI's token (`AuthInfoType.GH_CLI`, `gh-cli`) by running `gh`. The spike's empty-mode client, with a private `COPILOT_HOME` and the keychain probe off, could see no stored credential and fell to `gh-cli`, whose token has no Copilot entitlement, so `list_models` was empty. The spike's CLI call did the same under a private `COPILOT_HOME` with no token variable, and authenticated anyway: the CLI transport needs the same cage.

**One environment for both transports: an allow-list.** `caos.copilot.child_environment(home)` builds the child's whole environment; nothing else is inherited. It carries exactly: `COPILOT_HOME=<home>`; `COPILOT_GITHUB_TOKEN` copied from the worker's environment when set (its value is never read, logged or compared by CAOS code); `COPILOT_DISABLE_KEYTAR=1`; `COPILOT_AUTO_UPDATE=false`; `NO_COLOR=1`; `PATH` set to the directory of the executable being started and nothing else (and the directory of `node` when the SDK's runtime entry is a `.js`), so `gh` is not findable and auto-login has nothing to run; the platform's process needs, `HOME`, `TMPDIR`, `LANG` on POSIX and `SYSTEMROOT`, `SYSTEMDRIVE`, `USERPROFILE`, `TEMP`, `TMP`, `LOCALAPPDATA` on Windows; and the firm's proxy, `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, `SSL_CERT_FILE` and `NODE_EXTRA_CA_CERTS`, copied when set. What the allow-list excludes, each named here so the exclusion is a tested fact and not a hope: `GH_TOKEN`, `GITHUB_TOKEN` (the GitHub CLI's and Actions' tokens: the runtime would rank them above nothing but below `COPILOT_GITHUB_TOKEN`, and with the Copilot token absent they would authenticate a seat with no entitlement); `GITHUB_ASKPASS`, `GIT_ASKPASS`, `SSH_ASKPASS` and `COPILOT_HMAC_*` (an askpass program is a credential path the runtime can spawn: the strings "HMAC askpass command" are in runtime 1.0.90); `COPILOT_PROVIDER_BASE_URL`, `COPILOT_PROVIDER_API_KEY`, `COPILOT_PROVIDER_API_KEY_COMMAND`, `COPILOT_PROVIDER_BEARER_TOKEN` and every `COPILOT_PROVIDER_*` (BYOK: the runtime would route the prompt to another provider, run a shell command for a key, and the R1 `isByok` witness would be the only tell); `COPILOT_ALLOW_ALL` (auto-approves tools and, when exactly `true`, trusts the working directory's skills, plugins, MCP servers and hooks); `COPILOT_OTEL_*`, `OTEL_*` and `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` (telemetry export of the prompt and the answer to an endpoint the environment names); `GH_HOST` and `COPILOT_GH_HOST` (a redirected GitHub host); `COPILOT_CLI_PATH` (the SDK resolves "explicit CLI > `COPILOT_CLI_PATH` > downloaded runtime" against the `env` it is given, so with it absent the SDK runs the runtime it verified; an IT-provisioned runtime is named instead by `CAOS_COPILOT_RUNTIME=<path>`, a path CAOS reads and passes as the explicit entry); `COPILOT_MODEL`, `COPILOT_AUTO_TIER`, `COPILOT_CUSTOM_INSTRUCTIONS_DIRS`, `COPILOT_OFFLINE`, the `GITHUB_COPILOT_PROMPT_MODE_*` opt-ins, `USE_TGREP*`, `BASH_ENV` and every other name. `_client()` passes this mapping as `env=` (the SDK's child inherits only it) and `_cli_asked` as the process environment; the SDK adds its own `COPILOT_SDK_AUTH_TOKEN`, `COPILOT_CONNECTION_TOKEN` and `COPILOT_HOME` on top, as `client.py` shows.

**The SDK transport.** `_client()` starts `CopilotClient(mode="empty", base_directory=home, log_level="none", use_logged_in_user=False, env=child_environment(home))`, so the runtime is started with `--no-auto-login`, never consults the keychain, sees no stored credential, cannot find `gh`, and reads `COPILOT_GITHUB_TOKEN` itself. Readiness requires `get_auth_status()` to report `isAuthenticated` true, `authType == "env"` (`AuthInfoType.ENV`) and `host` equal to `CAOS_COPILOT_HOST` (default `github.com`; the firm's data-residency host is a pin, never an inherited `GH_HOST`); `gh-cli`, `token`, `api-key`, `hmac`, `copilot-api-token`, none, or another host refuses `PROVIDER_NOT_CONFIGURED`. `login` is printed as a host identifier (`[A-Za-z0-9-]{1,39}`, else `-`), never the token.

**The CLI transport's cage and proof.** `cli_arguments` adds `--no-auto-login` (accepted by CLI 1.0.92; an unknown flag exits with "unexpected argument", which the review probed) beside the flags of Design 10, and the process runs under `child_environment(home)`, so `COPILOT_DISABLE_KEYTAR=1`, no stored credential, no `gh` on `PATH`, no askpass, no `GH_TOKEN`: the only credential the runtime can hold is `COPILOT_GITHUB_TOKEN`. The CLI prints no `authType`, so the proof is a readiness probe pair, free of spend, run once per worker start for a `copilot-cli:` model: (a) the **negative probe**, the CLI started exactly as a call is but with `COPILOT_GITHUB_TOKEN` left out of the environment and the prompt `Reply with the single word OK.` on stdin, must end with no `assistant.message`, no `model.call_final_result`, no checkpoint with `nano_aiu > 0`, and a non-zero exit or a `session.error` (nothing authenticated, so nothing was called or billed); a negative probe that answers proves another credential path is open, and readiness refuses `PROVIDER_NOT_CONFIGURED`; (b) the **positive probe** is the production smoke (`scripts/gateway_smoke.py`, one paid call) the runbook already requires before the worker starts. The negative probe's exact ending on each platform is unmeasured (R6); the rule stands on its stated facts.

**Readiness refuses when the seat offers none of the approved models.** `require_ready(choices)` lists the models once and refuses `PROVIDER_NOT_CONFIGURED` (exit 2, before any run is claimed) when no approved `copilot:` model is offered with `policy` `None` or `state == "enabled"` and `usable` (the effort rules unchanged), when any offered approved model's pinned price fails R2.1's check, or when a `copilot-cli:` model has no `CLI_OUTPUT_TOKENS` entry (R2.5). An approved model the seat does not offer is printed `offered=n`, and a run pinned to it parks `PROVIDER_NOT_CONFIGURED` before any attempt (F468's path), so one worker serves the models its seat has. Printed per approved model: `copilot <model> offered=<y|n> policy=<state|-> max_prompt_tokens=<n|-> max_context_window_tokens=<n|-> max_output_tokens=<n|-> efforts=<a,b|-> price_check=<ok|-> credit_price=<usd>@<date>`, and once per start `copilot runtime=<version> host=<host> login=<login>` (the version from `session.start.copilotVersion` or the SDK's pin).

### R4. Context (D116)

A Copilot model's context window is declared from the listing and pinned once per process (invariant 10):

- source, in order, each `int | None`: `ModelInfo.billing.tokenPrices.longContext.maxPromptTokens` (the session asks for `context_tier="long_context"`), else `billing.tokenPrices.maxPromptTokens`, else `capabilities.limits.maxPromptTokens`, else `capabilities.limits.maxContextWindowTokens`;
- `require_ready` records the value for each offered approved model in `caos.copilot.CONTEXT_LISTED`, a mapping set once and then frozen, keyed by the runtime's model id. `caos.provider.request_ceiling(model)` consults `copilot.context_tokens(model)` for a Copilot name, which answers from `CONTEXT_LISTED` by `parsed(model).name`, else from the pinned table `caos.provider.CONTEXT_TOKENS` under the full model name (the only source for a `copilot-cli:` name, which never lists), else None: the transport ceiling and the `CONTEXT_NOT_DECLARED` notice (D116, D119);
- when both a listing and a pinned entry exist, the pinned entry must not exceed the listing's value, else `PROVIDER_NOT_CONFIGURED` at start;
- the ceiling is D116's with the output cap of R2.5: `min(MAX_REQUEST_BYTES, (tokens - output_cap(model)) x BYTES_PER_TOKEN_FLOOR)`. A prompt limit already excludes the output, so subtracting the cap from one is conservative and stays.

### R5. Tasks 2–7: what the re-spec changes

**Fakes.** Every fake event is built through the SDK's own types, in a helper `wire(kind, **data)` in `tests/test_copilot.py`: `copilot.SessionEvent.from_dict({"type": kind, "data": data, "id": str(uuid4()), "timestamp": "2026-10-06T00:00:00Z"}).to_dict()`, so a field the SDK does not know, or a value it cannot parse, fails the fake and not the adapter. The named fake builders: `started(model, version)` (`session.start` with `selectedModel`, `reasoningEffort`, `contextTier`, `copilotVersion`); `turn_start()`; `call_start(model)`; `answer(content, model, **changed)` (`assistant.message` with `messageId`, `model`, `apiCallId`, and **no** `serverTools` by default); `call_finished(outcome)`; `final_result(model, result, isByok=False)`; `usage(**changed)` (`assistant.usage` with `copilotUsage={"totalNanoAiu": n, "model": model}`, optional on the happy path); `turn_end()`; `checkpoint(nano_aiu, premium_requests)` (`session.usage_checkpoint`); `idle(aborted)`; `auto_resolved(chosen, available, routing, fallback)`; `error(status, error_type)`; `failure(kind, status, bad_request_kind)` (`model.call_failure`); `truncation()`; `compaction_start()`; `limits_exhausted(used, maximum)`; `turn_retry(reason)`; `model_change(new, previous)`; `server_tool_progress()`; `tools_updated(tools)`; `mcp_loaded(servers)`; `permission_requested()`; `fusion(event, **attribution)` (adds a `fusion` block to any event); `unknown_event(kind)`; `result_line()` (the CLI's non-event line). The happy path on both transports is `HAPPY = [started, turn_start, call_start, answer, call_finished("success"), final_result("success"), turn_end, checkpoint(251_164_000, 1), idle]`; the SDK's happy path adds `usage()` after `call_finished`; `RECOVERED = [started, turn_start, call_start, failure("api", 503), turn_retry("provider_error"), call_start, answer, call_finished("success"), final_result("success"), turn_end, checkpoint(300_000_000, 1), idle]`; `SPENT_FAILURE = [started, turn_start, call_start, failure("api", 500), checkpoint(100_000_000, 1), error(500), ]`.

- **Task 2 (the names and the mapping).** `reply_message` implements R1 and R2.4: `_witnessed` replaces `_exact`, over an `_ALLOWED` and `_REFUSING` event-type set; `_ai_units`, `_derived_finish` and `_spent` (R2.10) are new; `CopilotStatusError(status_code, *, declared)` carries the body mapping of R1. Tests replaced or added: `test_one_exact_call_is_witnessed_by_its_message_its_final_result_and_the_capi_usage`; `test_a_finish_reason_is_derived_without_a_usage_event` (the CLI shape); the refusal parametrization becomes `other-model-in-message`, `other-model-in-final-result`, `other-model-in-copilot-usage`, `two-final-results`, `byok-unknown`, `byok-true`, `fusion-on-message`, `fusion-on-usage`, `auto-resolved-even-naming-the-pin`, `model-change-other`, `server-tools-bare-provider`, `server-tools-advisor`, `tool-request`, `tools-updated-non-empty`, `mcp-server-loaded`, `permission-requested`, `unknown-event-type`, `sampling-requested`, `hook-start`, `skill-invoked`, `tool-search-activated`, `external-tool-requested`, `workflow-run-started`, `truncated`, `compacted`, `limits-exhausted`, `idle-aborted`, `no-answer`, `usage-other-effort`, `usage-tools-offered`; `test_a_runtime_recovered_answer_is_one_billed_call_never_raised` (`RECOVERED`); `test_a_failed_call_with_spend_is_billed_and_refused_never_a_drop` (`SPENT_FAILURE`: a message with `nano_aiu`, no `CopilotStatusError`, `PROVIDER_RESPONSE_INVALID`, `drop_kind` None through `ChatCompletions`); `test_a_failed_call_with_no_spend_and_no_answer_is_a_drop_by_its_status`; `test_the_charge_is_the_checkpoints_ai_units_at_the_reservations_credit_price` (251,164,000 nano-AIU at 0.01 a credit is exactly `Decimal("0.00251164")`); `test_zero_ai_units_on_an_answered_call_is_an_unknown_charge`; `test_a_checkpoint_that_is_not_a_whole_number_is_an_unknown_charge`; `test_no_checkpoint_is_an_unknown_charge_even_with_token_counts`; `test_per_request_ai_units_above_the_checkpoint_are_unknown`; `test_premium_requests_are_read_as_a_decimal`; `test_a_failure_event_maps_to_its_status_class_and_declaration`. The grammar, error-text and 429 tests stand. `credit_price()`, `CREDIT_PRICE_ENV`, `child_environment()`, `output_cap()`, `CLI_OUTPUT_TOKENS` and `RefusalCode.BUDGET_CHARGE_OVER_RESERVATION` are added, with `test_the_credit_price_is_a_dated_decimal_or_not_configured` and `test_the_child_environment_is_exactly_the_allow_list` (every excluded name of R3 set in the parent and asserted absent; `PATH` equal to the executable's directory). D77, addendum 2 is recorded with this re-spec (`docs/rebuild/decisions.md`), so Task 2's Step 6 is done.
- **Task 3 (the SDK transport and the dispatch).** `_client()` passes `use_logged_in_user=False` and `env=child_environment(home)`, names the explicit runtime from `CAOS_COPILOT_RUNTIME` when set, and silences the SDK's logger (R7) before the client starts (`FakeRuntime.options` asserts all: `test_the_runtime_never_auto_logs_in_and_sees_only_the_allow_listed_environment`, `test_the_sdk_logger_reaches_no_handler`). `session_options` adds `session_limits` from `reserved_amount` (`test_a_session_is_capped_at_its_reservation_in_credits_never_below_thirty`), `disabled_mcp_servers=["github-mcp-server", "githubiq"]`, `mcp_servers={}`, `enable_skills=False`, `skip_custom_instructions=True`, `enable_file_hooks=False`, `plugin_directories=[]`, `skill_directories=[]`, `custom_agents=[]`, `tools=[]`, `enable_session_telemetry=False`, and `on_permission_request` set to a handler that denies everything and records that it was asked (a call during which it was asked is refused: `test_a_permission_request_during_a_call_is_denied_and_refuses_the_call`). `caos.provider.reserved_amount` and `reserving(amount)` are new, set by the executor around `complete` (`tests/test_canonical_execution.py::test_the_call_runs_inside_its_reservation_scope`). `priced_request` gains `output_tokens` (default `MAX_COMPLETION_TOKENS`; `tests/test_pricing.py::test_a_cli_copilot_request_is_priced_at_its_own_output_cap`). `ChatCompletions._completion` dispatches the charge as R2.4 with the reservation's credit price (`tests/test_models.py::test_a_copilot_message_is_billed_in_ai_units_at_the_reservations_credit_price`, `::test_a_copilot_message_with_no_ai_units_is_an_unknown_charge`). Migration `0047_reservation_credit_price` and `reserve`/`reserved_for` (`tests/test_budget.py::test_a_copilot_reservation_stores_its_credit_price_and_reads_it_back`, `::test_a_reservation_with_no_credit_price_cannot_settle_a_copilot_call`). The executor gains `_settled_within` (R2.6; `tests/test_canonical_execution.py::test_a_charge_above_the_reservation_is_recorded_in_full_and_refused_typed`, asserting the ledger row, the code and the stderr line) and `requeue` the terminal rule (`tests/test_commands.py::test_a_run_parked_over_its_reservation_cannot_be_requeued_on_its_pin`). `request_ceiling` consults `copilot.context_tokens` and `output_cap` (R4; `tests/test_context_bound.py::test_a_listed_copilot_model_is_bounded_by_its_listing`, `::test_a_pinned_copilot_entry_above_the_listing_refuses_at_start`, `::test_a_cli_copilot_model_uses_its_pinned_entry_and_its_own_output_cap`). The dispatch and identity tests stand, with a `copilot-cli:` identity ending in its cap.
- **Task 4 (the CLI).** `_CLI_FLAGS` adds `--no-auto-login`, `--disable-builtin-mcps` (the spike saw `session.mcp_servers_loaded` and `session.mcp_server_status_changed` even with `--available-tools=`: the built-in GitHub MCP servers load unless disabled), `--no-ask-user`, `--disallow-temp-dir`, and the deny rules `--deny-tool shell --deny-tool write --deny-tool url` (denials precede every allow, per `copilot help permissions`; `--allow-all-tools` is never passed, so a tool that still reached the model would wait on a prompt no TTY answers); `cli_arguments` appends `--max-ai-credits <n>` when a reservation is in scope (R2.7); `_cli_asked` runs under `child_environment(home)` with `PATH` restricted to the executable's directory (R3). `FAKE_CLI` prints the `HAPPY` lines, a `result` line and the banner, and no `assistant.usage`; `printed_events` still raises on a JSON line with no `type`. Tests: `test_the_cli_is_given_no_auto_login_no_builtin_mcp_no_ask_user_the_deny_rules_and_its_credit_cap`, `test_a_cli_call_is_billed_from_its_checkpoint_with_no_usage_event`, `test_the_cli_sees_only_the_allow_listed_environment_and_cannot_find_gh` (a fake `gh` on the parent's `PATH` is not on the child's), `test_the_negative_probe_refuses_readiness_when_it_answers`; the adversarial review adds the allow-list, the `PATH`, the deny rules and the credit-cap argument to its list. `CLI_OVERHEAD_BYTES` stays as the reservation allowance; the firm-seat spike measures it with `--usage-output-file` (R6). Whether a tool can run before the CLI prints the event that reveals it is unprovable from outside the process; R6 measures the event order on a prompt that asks for a tool.
- **Task 5 (readiness).** `_offered()` returns `(status, models)`; `require_ready` implements R3 and R4 (`CONTEXT_LISTED`, the per-model and per-start lines, `credit_price()`, R2.1's price check, R2.5's cap check, the host check, the CLI's negative probe); `usable` is unchanged. The `listed()` fake gains `billing: {"tokenPrices": {..., "cacheWrite1HPrice": ..., "longContext": {...}}, "multiplier": 1}` and `capabilities.limits.maxContextWindowTokens` and `maxOutputTokens`, built by `ModelInfo.from_dict`, and `FakeRuntime` gains `auth_type` and `host`. Tests: `test_readiness_requires_the_env_token_and_refuses_the_github_cli_token` (`gh-cli` refused; `env` ready), `test_readiness_refuses_a_host_other_than_the_pinned_one`, `test_readiness_refuses_when_the_seat_offers_none_of_the_approved_models`, `test_an_approved_model_the_seat_lacks_is_printed_not_offered_and_its_run_parks`, `test_readiness_refuses_a_pinned_price_below_the_listed_price_times_the_multiplier` (each of the five input rates and both output rates, both tiers), `test_readiness_declares_each_listed_models_context_once`, `test_readiness_needs_a_credit_price_for_any_copilot_model`, `test_a_cli_model_needs_its_output_cap_and_a_clean_negative_probe`; the effort and policy cases stand with the auth fake set to `env`. `scripts/gateway_smoke.py` prints `charge=<d> nano_aiu=<n>`.
- **Task 6** is unchanged.
- **Task 7 (the runbook and the records).** Section 2 step 5 keeps only `COPILOT_GITHUB_TOKEN` (R3), and names `CAOS_COPILOT_RUNTIME` for an IT-provisioned runtime and `CAOS_COPILOT_HOST` for a data-residency host. Section 3 prices in AI credits: `CAOS_COPILOT_CREDIT_PRICE=0.01,<date>` at GitHub's published rate on that date, the per-token pin derived as R2.1 (every cache-write tier), `CLI_OUTPUT_TOKENS` for each `copilot-cli:` model, the ceiling arithmetic unchanged. Section 4 adds the variables and the start lines' new fields, and says that a run parked `BUDGET_CHARGE_OVER_RESERVATION` is restarted as a successor run after re-pricing. Section 6 adds `--no-auto-login`, `--disable-builtin-mcps`, `--no-ask-user`, `--disallow-temp-dir`, the deny rules and `--max-ai-credits`, and the negative probe. The N ids the task names (N121–N125) are taken: use the next free after N177 when writing. Step 4's live verification runs the firm-seat spike (R6) first, then the smokes.

### R6. Gating risks: what to measure on the firm's seat (N177)

A checklist, each item one line in a new `SUMMARY.md` under `docs/rebuild/runs/copilot-spike-<date>/`, run with `COPILOT_GITHUB_TOKEN` set, Task 1's script and its `list` step first (free):

1. `get_auth_status().authType` is `env`, `host` is the firm's, and `list_models()` names each candidate with `policy.state`, `supportedReasoningEfforts`, `defaultReasoningEffort`, `capabilities.limits.*` (`maxOutputTokens` included), `billing.tokenPrices.*` (`cacheWrite1HPrice`, `batchSize`, `longContext.*`) and `multiplier`.
2. `copilot help environment`, `help billing`, `help limits` and `help permissions` captured from **both** the SDK's runtime 1.0.90 (`<cache>/github-copilot-sdk/.../copilot --help` and the help topics) and the IT-installed CLI; any difference in auth precedence or flags recorded, and R3 re-read against it.
3. One SDK smoke per candidate with `model=` pinned: exactly one `assistant.message` and one `model.call_final_result`, both naming the pin, `isByok` stated `false`; whether `assistant.usage` is delivered on the SDK and what its `apiEndpoint`, `transport`, `isAuto`, `availableToolCount`, `reasoningEffort` and `copilotUsage.model` say; **the whole set of event types a plain smoke emits** (R1.0's allow-list is extended only from this list); whether `session.auto_mode_resolved` is emitted at all when the model is pinned; the `serverTools` shape per model family (R1.5 admits a bare provider tag only on this evidence, per family).
4. The same per candidate on the CLI with `--model`, `--no-auto-login`, `--disable-builtin-mcps`, `--no-ask-user`, `--disallow-temp-dir`, the deny rules and `--max-ai-credits 30`: exit 0, no `assistant.usage`, the checkpoint present, `--usage-output-file` read for token counts (the CLI's overhead tokens against `CLI_OVERHEAD_BYTES`), and the event types emitted.
5. The negative probe (R3): the CLI started as a call but with no `COPILOT_GITHUB_TOKEN`, under the allow-listed environment and restricted `PATH`, on macOS and on Windows: its exit code, its events, that nothing was billed, and that it never opened a browser or waited on input.
6. The nano-AIU ratio: two calls of different sizes, `totalNanoAiu` on the checkpoint against the credits the seat's `/usage` display and GitHub's usage page state, so R2's 10**9 is measured; the unit `copilotUsage.tokenDetails[].costPerBatch` and the listing's `batchSize` prices are stated in (R2.1's readiness check and R2.8's cross-check rest on it); whether the checkpoint's total equals the sum of the per-request figures.
7. The seat's billing platform: `totalPremiumRequests` present (legacy) or not, and which figure the firm's invoice follows.
8. `session_limits.max_ai_credits` accepted by `create_session` (experimental), and the events when it is exceeded.
9. Task 1 Step 4's 200 KB and over-limit fills: `max_prompt_tokens` under `long_context`, the over-limit answer (`session.error` 400 or 413, `model.call_failure` with its `badRequestKind`, or a truncation), the cache semantics, and whether a failed call carries a checkpoint with `nano_aiu > 0` (R2.10).
10. How often `assistant.turn_retry` and a `model.call_failure`-then-success occur on plain smokes (R1.6 admits them; the bill they carry).
11. A prompt that asks the model to run a shell command or read a file, on both transports: that no `tool.*` or `permission.*` event appears and no command ran (a canary file in `COPILOT_HOME`); the order in which the CLI prints `session.tools_updated` relative to any tool event.
12. The replaced-empty system message: whether the firm's policy allows it (the risk is unchanged).
13. The `--reasoning-effort` values the candidates take (`minimal` and `none` exist on the CLI; the grammar admits `low|medium|high|xhigh|max`, the SDK's `ReasoningEffort`).
14. The SDK's logger: that with R7's `NullHandler` nothing the runtime wrote to stderr reaches the worker's stderr on a smoke that makes the runtime complain (a bad flag through `CAOS_COPILOT_RUNTIME`).

Stop rules: a candidate not listed, `authType` not `env` or a host other than the pin, two `model.call_final_result` on a smoke, a checkpoint absent on either transport, a negative probe that answers, a tool event on item 11, or a `costPerBatch` or nano-AIU unit that cannot be reconciled: stop and report, and the owner decides.

### R7. The runtime's stderr and the SDK's logger

`copilot._jsonrpc` reads the runtime's stderr on a thread and logs every line at WARNING (`logger.warning("[CLI] %s", line)`, `_jsonrpc.py:157`) under the logger `copilot._jsonrpc`, and keeps it for `get_stderr_output()`; Python's last-resort handler prints a WARNING with no configured handler, so a runtime complaint, which can quote a prompt, would reach the worker's stderr (Global Constraints: never the CLI's stderr). Rule: before the first client starts, `caos.copilot._silenced()` sets `logging.getLogger("copilot")` to `propagate = False` with a single `logging.NullHandler()` and level `CRITICAL`, once per process; `get_stderr_output()` is never called; the runtime is started with `log_level="none"`; and the CLI transport keeps `stderr=DEVNULL`. Test: `test_the_sdk_logger_reaches_no_handler` (a WARNING logged on `copilot._jsonrpc` during a fake call leaves `capsys` empty and no record on the root logger).
