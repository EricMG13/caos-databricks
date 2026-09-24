# CAOS v2 → Databricks App — build spec (2026-09-22)

This is the contract the builder reads first. Everything below is binding; the decision log (`docs/rebuild/decisions.md`, entries D1–D22) records why. Paths are relative to the target repo unless absolute.

Inputs:

| Input | Value |
|---|---|
| Legacy snapshot (read-only) | `$LEGACY_RO/repo` = clone of `https://github.com/EricMG13/caos-v2.git` at `b5a3932f0e36d464d857040d98dbd90558b02a12` |
| Deploy V bundle | `$LEGACY_RO/repo/vendor/deploy-v` (integrity build `78c24be4…`, never edited) |
| External corpus | `$LEGACY_RO/skills/1-DEPLOY_B_COWORK_SKILLS` (dropped, see §9) |
| Target repo / branch | `/Users/ericguei/Documents/caos-databricks`, `rebuild/databricks` |
| Databricks | profile `$DATABRICKS_CONFIG_PROFILE`, UC schema `$CAOS_UC_SCHEMA` (`catalog.schema`), Lakebase instance `$CAOS_LAKEBASE_INSTANCE`, gateway endpoint `$CAOS_MODEL_ENDPOINT` (default `databricks-claude-opus-5`); unknown at spec time (`blockers.md` B1–B2) |
| Deploy access | `no` unless the launcher says `yes` and `databricks current-user me` succeeds |
| Test-only model | `OPENROUTER_API_KEY` from the environment; model `anthropic/claude-opus-5-20260723` |

## 1. Operating mode for the builder

You are operating autonomously. The user is not watching in real time and cannot answer questions mid-task, so asking "Want me to…?" or "Shall I…?" will block the work. Never ask, never wait, never end a turn with a plan, a question, or a promise of future work. End your turn only when the task is complete or you are blocked on input only the user can provide. Do not stop because the context or session is long.

- **Deliverable = scope.** Build every KEEP and CHANGE row in §8–§9. Do not narrow, widen or swap the scope. If one part is blocked, finish every other part in full and say exactly what was left out and why.
- **Apply your own findings.** Any finding from a gate, test, parity check, security scan, research or your own review that bears on the spec, gates, ledgers, security or maintainability is fixed in place and logged in `docs/rebuild/decisions.md` as `Fn — finding; action; evidence (command + output line)`.
- **Convergence.** A feature or requirement beyond the ledgers is logged in `docs/rebuild/next.md`, not built. Do not fix nearby code the task did not touch. Do not promote scratch checks into permanent test files.
- **Blockers.** When a step needs a credential, permission, host or CLI you do not have, complete everything else, record the blocker in `docs/rebuild/blockers.md` with the exact command and error text, and continue. Never get around a blocker by weakening a gate, faking output, stubbing the gateway, or mocking the thing a criterion exists to test. A failing test or gate is never a blocker.
- **Evidence.** Before reporting progress or completion, audit each claim against a tool result from this session. If a command fails, say so with its output. The final message copies command, exit code and summary from tool output produced in that same final turn.
- **Hard limits.** Never modify `$LEGACY_RO` (it is read-only; do not `chmod` it). Never `git push`. Never print, log or persist an API key, token or connection string with a password (print names or lengths only). Never delete workspace resources you did not create. Never write `requirements.txt` at the repo root (it would switch Databricks Apps to pip and Python 3.11).
- **Working style.** Prefer targeted edits to whole-file rewrites. First privately list what you need next; then request every item that doesn't depend on another's result in the same response. Stdlib first, then an already-pinned dependency, then new code; no new dependency without a `Dn` entry naming the version. Commit to `rebuild/databricks` at each stable checkpoint (`git add -A && git commit -m …`); the pre-commit hooks must pass, never `--no-verify`.
- **Long output.** The `rtk` user hook truncates long tool output. Print summaries (tail lines, counts) and write full logs under `docs/rebuild/runs/` (git-ignored).
- **Ledger discipline.** A KEEP or CHANGE row may be marked `dropped` only when a `blockers.md` entry names that row; any other drop voids the result. Dropped tests are listed by name with the row they belonged to in an `Fn` entry.
- **Machine facts.** Present on this machine and therefore never a blocker: Docker 29.6, Node 24.16 / npm 11.13, gitleaks 8.30.1, trivy, uv 0.12.5, uv-managed CPython 3.13.15 and 3.14.6, gh. Absent: the `databricks` CLI (B1).
- **Closing recap.** The last message must stand alone: what was built, the EVIDENCE table (§11), both ledgers with row status, `blockers.md` verbatim.

## 2. Objective

CAOS turns governed source documents (10-Ks, credit agreements, earnings releases) into committee-ready leveraged-finance credit conclusions: documents are admitted into an immutable source set, a pinned methodology route of CP-* modules runs each module against delivered evidence with budgets that fail closed, every number is anchored to a rectangle on a page, and a frozen deliverable is signed, frozen and filed under an audit chain. The rebuild moves the host from a self-managed Docker/OpenRouter stack to a Databricks App: LangGraph executes the pinned route with Lakebase Postgres checkpoints, models are reached only through Databricks AI Gateway, blobs live in a Unity Catalog volume, and the workspace UI is served from the same app. Nothing in the credit methodology changes; the parity suite proves it.

## 3. Fixed requirements

1. Python `>=3.13,<3.14` in `pyproject.toml` `requires-python`, `.python-version` = `3.13`, `uv.lock` committed, `[tool.uv] no-build = true` (wheels only). Every tool runs through `uv run`. The running app's `GET /api/health` reports `python_version` (from `sys.version`) and `build_id`. No `requirements.txt` at the root.
2. LangGraph (`langgraph>=1.1`) for runtime orchestration; Lakebase Postgres for the LangGraph checkpointer (`databricks_langchain.CheckpointSaver`, schema `caos_graph`) and for all durable domain state (the legacy schema and migrations, `psycopg` 3 hand-written SQL, unchanged table set).
3. Production model calls go only through Databricks AI Gateway via `databricks_langchain.ChatDatabricks(endpoint=…)` behind one factory `caos/models.py::chat_model(...)`. No other model client anywhere in `caos/`, `icm/`, `.claude/skills/`, `databricks.yml`, `app.yaml`.
4. OpenRouter is permitted for tests only: `tests/openrouter_adapter.py` builds a LangChain `ChatOpenAI` with `base_url="https://openrouter.ai/api/v1"`, `api_key` read from `OPENROUTER_API_KEY` at call time (never stored), `model="anthropic/claude-opus-5-20260723"`; a `conftest.py` fixture injects it through the factory (`monkeypatch.setattr("caos.models.chat_model", ...)`). `langchain-openai` is in the `dev` dependency group only. Only synthetic or public fixtures (the `qualification/*/documents` public filings, `tests/*_fixtures.py`) go through OpenRouter. OpenRouter tests never count as gateway coverage.
5. ICM architecture (D4–D5): LangGraph owns execution, state, interrupts, persistence. ICM owns agent definitions: `icm/CONTEXT.md` (Layer 1: module index, route-is-order rule, loading rule), `icm/stages/<deploy-v-folder-slug>/` for each of the 25 physical modules plus `cp-parse` (CP-0 authority under its own node) and `cp-cf` (host extension), each with `CONTEXT.md` (`## Inputs` table with columns Source | File | Section | Why, `## Process`, `## Outputs`), `prompt.md` (the host prompt template whose rendering equals the legacy `invocation.py` bytes, see §10), and `references/` only where the host owns the file (CP-CF's `SKILL.md` and calculator contract). Bundle files are referenced by path into `vendor/deploy-v/` and loaded through the verified `Bundle` seam; they are never copied. Root `CLAUDE.md` is Layer 0. `caos/icm.py` is the single loader: it parses a stage `CONTEXT.md`, resolves every Inputs row to bytes (bundle rows via `Bundle`, host rows via `verified_host_bytes`), and renders `prompt.md`.
6. A new `CLAUDE.md`, written from scratch, under 120 lines: repo map, commands, gate commands, the conventions in §12. Nothing stale from legacy.
7. Repo layout: `caos/` (app package; legacy `server/` ported with the same subpackages: `api`, `store`, `evidence`, `methodology`, `calculators`, `deliverable`, `qualification`, plus `graph/` replacing `engine/`, `models.py`, `blobs.py`, `icm.py`), `icm/`, `vendor/deploy-v/` (byte-identical copy of the legacy bundle), `frontend/` (copied), `scripts/`, `tests/` (incl. `tests/parity/`, `tests/graph/`), `qualification/` (copied, public documents only), `databricks.yml`, `app.yaml`, `pyproject.toml`, `uv.lock`, `.python-version`, `CLAUDE.md`, `CONTEXT.md`, `.pre-commit-config.yaml`, `.gitleaks.toml`, `.github/workflows/ci.yml`, `compose.yaml` (local test Postgres only), `docs/rebuild/`.

## 4. Architecture

- **Graph.** `caos/graph/build.py::build_graph(route: ResolvedRoute) -> CompiledStateGraph` builds a `StateGraph` from the pinned route: one node per route node, edges from the typed edge set (CONDITIONAL predicates are already frozen at the plan gate, so they compile to plain edges or to the BLOCKED sink), QA_GATE and human gates compile to `interrupt()` whose resume value is the digest-bound approval (invariant 5) (corrected: F26 -- no node calls `interrupt()`; a run whose gate approval is missing is refused by `execution_input` before it is ever claimed, so there is nothing mid-graph to interrupt, and the checkpointer keeps thread position only, D6). State is `RunState` (TypedDict: `run_id`, `route_digest`, `accepted: dict[node_id, sha256]`, `blocked: str | None`) (corrected: D6, F6 -- `caos.graph.build.RunState` is a frozen dataclass of `run_id: str`, `passes: dict[str, str]` and `ended: str`; every node's successor is a conditional edge read from `RunState.ended`). Thread id = run id. Nodes run one at a time (N1 records parallelism as future work).
- **Node body** `caos/graph/node.py::run_module` (corrected: D6 -- as built, `caos/graph/runtime.py::node_pass`) keeps the legacy order exactly: check the context → start the attempt → reserve → call → accept, using the ported store functions. Truth is the accepted-attempt ledger (D6): on entry the node re-derives `node_states` from the store and returns immediately if it is already COMPLETE.
- **Persistence.** `caos/store/connect.py` (corrected: F30 -- as built, `connect()` is `caos/store/__init__.py::connect`; there is no separate `connect.py`) yields psycopg connections from one pool: locally from `CAOS_DATABASE_URL`; on Databricks from `PGHOST/PGPORT/PGDATABASE/PGUSER/PGSSLMODE` with a password minted per connection via `WorkspaceClient().database.generate_database_credential(...)` (provisioned instance) or `.postgres.generate_database_credential(endpoint=...)` (autoscaling), following `databricks_ai_bridge.lakebase` (tokens expire after 60 min; recycle at 14 min). The checkpointer uses `CheckpointSaver(instance_name=$CAOS_LAKEBASE_INSTANCE, schema="caos_graph")` (or `autoscaling_endpoint=` when the launcher's instance is an autoscaling endpoint path) and `setup()` once at startup (corrected: F30 -- the vendor `CheckpointSaver` fixed `port=5432 sslmode=require` and its own connection class, so it could reach neither the platform's `PGPORT`/`PGSSLMODE` nor any stand-in database; `caos/graph/checkpoint.py` runs `PostgresSaver` over a small `psycopg_pool` whose `MintedConnection` builds its URL from `caos/store/lakebase.py::store_url()` on open, the same values and the same minted credential the store uses, refreshed the same way).
- **Model factory.** `chat_model(*, endpoint: str | None = None, effort: str | None = None) -> BaseChatModel` (corrected: F95 -- as built, `chat_model(*, endpoint: str | None = None) -> BaseChatModel` takes no effort; a reasoning effort is carried on `ChatCompletions.reasoning_effort` for the qualification identity only, and setting `CAOS_REASONING_EFFORT` refuses `PROVIDER_NOT_CONFIGURED` because it is never sent to the endpoint, next.md N2); production returns `ChatDatabricks(endpoint=endpoint or os.environ.get("CAOS_MODEL_ENDPOINT", "databricks-claude-opus-5"), max_tokens=65_536)`. The node calls `.invoke([SystemMessage(authority), HumanMessage(handoff)])` (corrected: as built -- `caos.models.ChatCompletions.complete` sends `chat.invoke([HumanMessage(content=prompt)])`; the authority and the handoff are assembled into one prompt string by `caos.methodology.invocation` before the call, never sent as two messages -- no single decisions.md entry records this choice), reads `content`, `id` (generation id) and `usage_metadata` (input/output tokens); charge = tokens × the dated `CAOS_MODEL_PRICE` (Decimal, D8). Request/response byte ceilings, refusal table (`PROVIDER_OUTPUT_TRUNCATED`, `PROVIDER_REFUSED`, transient vs never-retried) and "nothing quotes the response" stay as in legacy `provider.py`. Qualification identity: `databricks/<endpoint>/<effort-or-none>/65536`.
- **Blobs.** `caos/blobs.py` keeps the CAS contract (sha256 key, verify on read); backend `VolumeBlobStore` uses `WorkspaceClient().files.upload/download` under `/Volumes/<catalog>/<schema>/caos_blobs/<sha[:2]>/<sha>`; `FileBlobStore` (legacy) for tests and local dev, selected by `CAOS_BLOB_ROOT` (`volume://…` vs a path).
- **Identity.** D10: `caos/api/identity.py` reads `x-forwarded-access-token`, calls SCIM `Me` (cached 5 min per token hash), maps groups → ADMIN/ANALYST via `CAOS_GROUP_ADMIN`/`CAOS_GROUP_ANALYST`, READER floor; subject UUID = `uuid5(NAMESPACE_CAOS, f"{workspace_id}:{scim_id}")`. Unknown and unauthorized both answer 404. Dev mode unchanged (`CAOS_TRUST_ROLE_HEADER=1`, `CAOS_DEV_USER`, `CAOS_DEV_ROLE`). The HMAC edge assertion is removed; security headers stay.
- **Worker.** In-process background task (`caos/graph/worker.py`) started in the FastAPI lifespan: poll `run_work`, claim with lease, build the graph from the pinned route, `graph.invoke(...)` with `configurable={"thread_id": run_id}`, map outcome, heartbeat; SIGTERM stops between nodes. One run at a time.
- **API and UI.** FastAPI app (`caos/api/app.py`) with the legacy wire models, section reads, commands, SSE stream and `/api/health` (add `python_version`, `build_id`); `caos/api/site.py` serves `frontend/dist` from `CAOS_SITE_ROOT`, one origin. `app.yaml`: `command: ["uv", "run", "caos-serve"]` where `caos-serve` (`[project.scripts]`) runs uvicorn on `0.0.0.0:$DATABRICKS_APP_PORT` (corrected: F3 -- the project is virtual (`package = false`; nothing here is built or installed, so there is no `[project.scripts]` entry point), and `databricks.yml`'s `config.command` runs `["uv", "run", "--locked", "--no-dev", "python", "-m", "caos.serve"]`).
- **Bundle.** `databricks.yml` declares `resources.apps.caos` with `source_code_path: ./`, `config.command`, `config.env` (`CAOS_MODEL_ENDPOINT`, `CAOS_UC_SCHEMA`, `CAOS_BLOB_ROOT=volume://…`, `CAOS_GROUP_*`, `CAOS_MODEL_PRICE`), and resources `serving_endpoint` (name `${var.model_endpoint}`, `CAN_QUERY`), `database` or `postgres` (`CAN_CONNECT_AND_CREATE`), `uc_securable` (the `caos_blobs` volume); `sync.include: ["frontend/dist/**"]` because `dist/` is git-ignored but must ship. Targets `dev` (default) and `prod`.

## 5. Gates (hard constraints)

No lowered threshold. No new `noqa`, `type: ignore`, `nosec`, `pragma: no cover`, `pytest.mark.skip`, or per-file ignore beyond the committed baseline. No excluding paths to make a gate pass; the only exclusions are the inherited ones stated here (`.venv*`, `vendor/`, `.claude/worktrees`, `frontend/node_modules`). Code under `tests/` (including the OpenRouter adapter) and scripts under `.claude/skills/` (none vendored) pass every gate. Tool versions are pinned in `pyproject.toml`/`uv.lock` and `frontend/package-lock.json`.

| # | Dimension | Tool (pin) | Threshold / ruleset | Command (repo root) |
|---|---|---|---|---|
| G1 | Lint | ruff `==0.14.0` | select `E,F,W,I,UP,B,ANN,BLE,TRY,C901,PLR0912,PLR0913,PLR0915,RUF`; mccabe 10; line 88; `target-version = "py313"`; `extend-exclude = [".venv", "vendor", ".claude/worktrees"]` | `uv run ruff check .` |
| G2 | Format | ruff | no diffs | `uv run ruff format --check .` |
| G3 | Typing | mypy `==1.18.2` | `strict = true` over `caos scripts tests icm` (loader code) | `uv run mypy caos scripts tests` |
| G4 | Tests + coverage | pytest `==9.0.3`, pytest-cov `==7.0.0`, pytest-xdist `==3.8.0` | `addopts = "-q --strict-markers --cov --cov-branch --cov-report=xml --cov-report=term:skip-covered --cov-fail-under=80"`; markers `live_provider` (OpenRouter-backed, deselected here, selected by A26); `[tool.coverage.run] source=["."] omit=["tests/*","vendor/*",".venv*/*"]`; Postgres required; graph mechanics are unit-tested with `langchain_core.language_models.fake_chat_models.GenericFakeChatModel` injected through the factory, so coverage does not depend on live calls | `CAOS_REQUIRE_POSTGRES=1 uv run pytest -n auto -m "not live_provider"` |
| G5 | Coverage floor | `scripts/scan_floors.py` (legacy) | report measured ≥1 file | `uv run python scripts/scan_floors.py coverage.xml --cobertura` |
| G6 | Postgres races | pytest | two-connection race suite, no skips | `CAOS_REQUIRE_POSTGRES=1 uv run pytest --no-cov tests/test_postgres_races.py` |
| G7 | Vocabulary | `scripts/check_vocabulary.py` (legacy) | no synonym identifiers vs `CONTEXT.md` | `uv run python scripts/check_vocabulary.py` |
| G8 | Tested definitions | `scripts/check_tested.py` (legacy) | every public definition named by a test | `uv run python scripts/check_tested.py` |
| G9 | I/O budget | `scripts/io_budget.py` (legacy) | every module under `caos/api/` declares `IO_BUDGET` | `uv run python scripts/io_budget.py --assert` |
| G10 | SAST | bandit `>=1.8.6` + floor | zero findings; report parsed every file under `caos scripts icm`; `tests` listed unscanned | `uv run bandit -r caos scripts icm -f json -o bandit.json \|\| true && uv run python scripts/scan_floors.py bandit.json --no-parse-errors --cover caos scripts icm --unscanned tests && uv run bandit -r caos scripts icm` |
| G11 | Dependency audit | pip-audit `==2.9.0` | no known vulnerabilities across all groups, hashes required | `uv sync --locked --all-groups && uv run pip-audit --strict` (the lock's hashes are verified by the sync; the audit covers exactly the environment that runs, F17) |
| G12 | Secrets | gitleaks (system `8.30.1`; pre-commit `v8.21.2`) | default rules, allowlist only `^finish_reason=(?:stop\|length)$` | `gitleaks git --no-banner` |
| G13 | Lock integrity | uv `0.12.5` | lock current, wheels only | `uv lock --check && uv sync --locked --all-groups` |
| G14 | Cognitive complexity | complexipy (pinned in `dev`) | ≤15 per function for every function not in the committed baseline `complexipy-snapshot.json` (the 26 legacy functions above 15, which may not grow: Sonar's new-code rule, D27); the baseline count may only fall (G16) | `uv run complexipy caos scripts icm --max-complexity-allowed 15` |
| G15 | Duplication | jscpd (pinned in `frontend/package.json` devDependencies) | ≤3% duplicated lines, min 10 lines, over `caos scripts icm frontend/src` | `npx --prefix frontend --no-install jscpd --threshold 3 --min-lines 10 --ignore "**/node_modules/**,**/dist/**,**/dist-demo/**" caos scripts icm frontend/src` |
| G16 | Gate integrity | `scripts/check_gate_config.py` (new, D15) | ruff select ⊇ G1 set, mccabe 10, mypy strict, `--cov-fail-under=80` present, coverage omit equal to G4, `requires-python == ">=3.13,<3.14"`, no root `requirements.txt`, pre-commit hook ids equal to G18, the eleven parity golden manifests (§10) present with ≥1 case each, suppression counts (`noqa`, `type: ignore`, `nosec`, `pragma: no cover`, `pytest.mark.skip`, `xfail`) ≤ `tests/gate_baseline.json`; the script and `check_icm.py` each have a test proving they exit nonzero on a tampered input | `uv run python scripts/check_gate_config.py` |
| G17 | ICM integrity | `scripts/check_icm.py` (new) | every `icm/stages/*/CONTEXT.md` has Inputs/Process/Outputs; every Inputs path exists; every file under `icm/**/references/` is named by ≥1 contract; every skill in §9 with destination `.claude/skills/` exists with a provenance line | `uv run python scripts/check_icm.py` |
| G18 | Pre-commit | pre-commit `==4.6.2` | ruff, ruff-format, gitleaks, check-added-large-files (legacy exclusions), check-merge-conflict, end-of-file-fixer, trailing-whitespace, vocabulary, tested, io-budget | `uv run pre-commit run --all-files` |
| G19 | Frontend lint | eslint, prettier (locked) | `--max-warnings=0`, prettier clean, `check-vocabulary.mjs`, `check-tested.mjs` | `npm --prefix frontend run lint` |
| G20 | Frontend types | tsc | `--noEmit` clean | `npm --prefix frontend run typecheck` |
| G21 | Frontend unit | vitest | all pass | `npm --prefix frontend test` |
| G22 | Frontend build | vite + export | build succeeds; `frontend/dist/<s>/index.html` exists for `directory upload analysis book run model report committee admin` | `npm --prefix frontend run build && for s in directory upload analysis book run model report committee admin; do test -f frontend/dist/$s/index.html; done` |
| G23 | Demo build | vite | succeeds | `npm --prefix frontend run build:demo` |
| G24 | Accessibility | axe via Playwright | 0 violations across the matrix | `npm --prefix frontend run a11y` |
| G25 | Workbench | Playwright (3 engines) | all pass | `npm --prefix frontend run test:workbench` |
| G26 | PR size (CI only) | `scripts/check_pr_size.py` | ≤800 changed lines per PR, legacy exclusions | CI job on `pull_request`; not an acceptance command |
| G27 | Bundle validity | Databricks CLI | schema-valid | `databricks bundle validate` |

Dropped gates and why: SonarCloud (excluded by the meta-prompt; dimensions replaced by G4, G14, G15 and G1/G10 per D12); Trivy image scan and `smoke-production` (no image, D14); the bandit 3.12 side environment (D13). `bandit.json`, `coverage.xml` and `docs/rebuild/runs/` are git-ignored.

## 6. Build order

Work in this order; commit after each step passes the gates that exist by then.

0. Scaffold: `pyproject.toml` (deps: `fastapi`, `uvicorn`, `python-multipart`, `psycopg[binary,pool]`, `pdfminer.six`, `langgraph`, `databricks-langchain[memory]`, `databricks-sdk`; dev group: ruff, mypy, pytest, pytest-cov, pytest-xdist, pre-commit, httpx, bandit, pip-audit, complexipy, `langchain-openai`), `.python-version`, `uv lock`, `.gitignore`, `.pre-commit-config.yaml`, `.gitleaks.toml`, `CONTEXT.md` (copy), `scripts/` (copy the six legacy gate scripts + `tracked.py`, port paths `server`→`caos`), `frontend/` (copy), `vendor/deploy-v/` (copy, then `uv run python -B vendor/deploy-v/verify_package.py` must exit 0), `qualification/` (copy), `npm --prefix frontend ci --ignore-scripts && ./frontend/node_modules/.bin/playwright install`, `docker compose up -d --wait`. Register the `live_provider` marker. Generate `tests/gate_baseline.json` from the copied files and commit it.
1. Pure core + parity: port `boundary_text`, `refusals`, `digest`, `calculators`, `pricing`, `store/budget.py` pure functions, `methodology/forecast.py`, `engine/route.py` → `caos/graph/route.py`, `evidence/extract.py`, `evidence/citations.py` (pure part), `deliverable/render.py`, `methodology/invocation.py` prompt assembly. Generate goldens (§10) from the legacy snapshot and make `uv run pytest tests/parity` pass.
2. Store: schema + migrations unchanged, `connect.py` (corrected: F30 -- `connect()` in `caos/store/__init__.py`, Lakebase credentials in `caos/store/lakebase.py`) with both backends, all store modules, `compose.yaml` for the local test database, `tests/test_postgres_races.py` green with `CAOS_REQUIRE_POSTGRES=1`.
3. Methodology + ICM: `Bundle`, vendor validators, handoff, canonical executor, `caos/icm.py`, the 27 stage folders, `scripts/check_icm.py`, prompt-bytes parity.
4. Graph + models: `caos/models.py`, `tests/openrouter_adapter.py`, `caos/graph/{build,node,worker}.py` (corrected: D6 -- as built, `caos/graph/{build,runtime,worker}.py`), budget/attempt/accept flow, `tests/graph/` (OpenRouter-backed, synthetic fixtures: one LITE route end to end, one interrupt/resume, one blocked route, one crash-then-resume proving one charge and one artifact).
5. API + UI: wire models, reads, commands, SSE, health, site, identity (D10), blobs (D9); regenerate `frontend/src/wire/v1/schema.json` and pass the frontend gates.
6. Databricks: `app.yaml`, `databricks.yml`, `scripts/gateway_smoke.py` (imports `caos.models.chat_model` — the production path, never a direct client — prints `type(model).__name__`, endpoint name, response id and `usage_metadata`, and exits nonzero unless the class is `ChatDatabricks`), `.github/workflows/ci.yml` (lint, types, test, postgres, security, size, frontend); `databricks bundle validate`; if deploy access, deploy and run A31.
7. `CLAUDE.md` from scratch; full gate run; evidence.

## 7. Rules that hold throughout

- The eleven legacy invariants (`$LEGACY_RO/repo/CLAUDE.md` lines 48–84) hold unchanged except invariant 6's "no checkpointer" clause, which D6 refines. Restate them in the new `CLAUDE.md`.
- Wire strictness (`extra="forbid"` both ways), transactional pairing, `BoundaryText` at every boundary, "persona is not authority", Decimal never float on money paths.
- Never edit a file under `vendor/deploy-v/`; host additions live in `icm/` and `caos/`.
- Never log document-derived text; log typed codes.
- Tests are there to verify correctness, not to define the solution. It is unacceptable to remove, weaken or skip a test to pass a gate; if a test is wrong, fix it and log `Fn` with the reason.
- A scanner that scanned nothing is a failure (G5, G10).
- No `requirements.txt`; no Python below 3.13 anywhere (`requires-python`, `.python-version`, `uv.lock`, CI, `app.yaml`).

## 8. Capability ledger

Legacy rows (paths under `$LEGACY_RO/repo/server` unless noted). Status: KEEP (port unchanged), CHANGE (port with the stated change), DROP (not built, reason). The builder marks each row `implemented` or `dropped: <reason>` in the final message.

| # | Capability | Legacy location | Status | Reason / change |
|---|---|---|---|---|
| C1 | Pack admission, all-or-nothing | `evidence/ingest.py` | KEEP | only door for bytes |
| C2 | Plain-text extractor | `evidence/extract.py` | KEEP | parity golden |
| C3 | PDF extractor (pdfminer) | `evidence/pdf.py` | KEEP | dependency carried |
| C4 | `read_evidence` fail-closed boundary | `evidence/read.py` | KEEP | invariant 2 |
| C5 | Citation anchoring | `evidence/citations.py` | KEEP | invariant 11, parity golden |
| C6 | Evidence page read | `evidence/page.py` | KEEP | drawer |
| C7 | Extraction integrity v1 | `store/extraction_integrity.py` | KEEP | frozen format |
| C8 | Schema + ordered migrations | `store/__init__.py`, `store/*.sql` | KEEP | same DDL on Lakebase; record `SELECT version()` (D17) |
| C9 | Cases/runs/transitions | `store/runs.py`, `store/cases.py` | KEEP | state and event commit in one transaction; no platform coupling |
| C10 | Run events | `store/events.py` | KEEP | exactly-once |
| C11 | Budget reservations/ledger | `store/budget.py` | KEEP | parity on pure functions |
| C12 | Call outcomes / attempt refusals | `store/outcomes.py` | CHANGE | charge from tokens × dated price (D8) |
| C13 | Governed writes + audit chain | `store/audit.py`, `store/members.py` | KEEP | hash chain is host logic; no platform coupling |
| C14 | Idempotent commands | `store/commands.py` | KEEP | receipt semantics unchanged |
| C15 | Route pin | `store/routes.py` | KEEP | invariant 10 |
| C16 | Run input pin | `store/run_inputs.py` | KEEP | pin fingerprint unchanged |
| C17 | Source sets | `store/source_sets.py` | KEEP | immutable set semantics unchanged |
| C18 | Human gates (digest-bound) | `store/gates.py` | CHANGE | resumed through LangGraph `interrupt()`; approval semantics unchanged |
| C19 | Work queue (claim/lease) | `store/work.py` | KEEP | drives the in-process worker |
| C20 | Blob store (CAS) | `blobs.py` | CHANGE | UC volume backend + filesystem backend (D9) |
| C21 | Primitives (`BoundaryText`, refusals, digest) | `boundary_text.py`, `refusals.py`, `digest.py` | KEEP | parity golden |
| C22 | Bundle authority | `methodology/bundle.py` | KEEP | invariant 4 |
| C23 | Vendor validators | `methodology/vendor.py` | KEEP | loaded from verified bundle bytes; unchanged |
| C24 | Canonical handoff | `methodology/handoff.py` | KEEP | Markdown conformance is provider-independent |
| C25 | Invocation / prompt assembly | `methodology/invocation.py` | CHANGE | template moves to `icm/stages/*/prompt.md`; rendered bytes identical (parity) |
| C26 | Canonical executor | `methodology/canonical.py` | CHANGE | calls the model factory; refusal table kept |
| C27 | Evidence delivery/selection | `methodology/executor.py`, `selection.py` | KEEP | pure over pinned inputs |
| C28 | Accepted-artifact verification | `methodology/verification.py` | KEEP | the ten checks are host logic |
| C29 | CP-CF host extension | `methodology/host.py`, `host_pin.py`, `methodology/skills/cp-cf` | CHANGE | files move to `icm/stages/cp-cf/references/`; manifest pin regenerated by `scripts/host_manifest.py` |
| C30 | Forecast binding | `methodology/forecast.py` | KEEP | parity golden |
| C31 | Runner (`ModuleProvider`) | `methodology/runner.py` | CHANGE | becomes the graph node body |
| C32 | Provider client | `provider.py` | CHANGE | replaced by `caos/models.py` + `ChatDatabricks`; byte ceilings and refusals kept; OpenRouter encoding removed |
| C33 | Pricing | `pricing.py` | KEEP | parity golden |
| C34 | `cash_flow_forecast` | `calculators/cash_flow.py` | KEEP | parity golden, decision §54 |
| C35 | Route resolution | `engine/route.py` | KEEP | moved to `caos/graph/route.py`; parity on 18 pathways |
| C36 | Frontier loop | `engine/runtime.py` | CHANGE | LangGraph graph built from the pinned route (D5–D6) |
| C37 | Worker | `engine/worker.py` | CHANGE | in-process background task (D11) |
| C38 | App + wire contract | `api/app.py`, `api/wire.py` | KEEP | schema export regenerated |
| C39 | Edge guard + identity | `api/edge.py`, `api/identity.py`, `api/deps.py` | CHANGE | Databricks identity (D10); HMAC edge removed; headers kept |
| C40 | Health | `api/health.py` | CHANGE | adds `python_version`, `build_id` |
| C41 | Site ASGI (static export) | `api/site.py` | KEEP | same one-origin static serving on Databricks Apps |
| C42 | Case SSE stream | `api/stream.py`, `api/events.py` | KEEP | verify streaming through the Apps proxy on deploy; if it buffers, log `Fn` and add polling fallback |
| C43 | Section reads (11 routes) | `api/reads/*.py` | KEEP | wire contract binds the frontend |
| C44 | Case commands | `api/commands/cases.py`, `members.py` | KEEP | governed writes unchanged |
| C45 | Run commands | `api/commands/runs.py`, `execution.py` | KEEP | enqueue only |
| C46 | Deliverable commands | `api/commands/deliverable.py` | KEEP | same filing chain |
| C47 | Verdict command | `api/commands/qualification.py` | KEEP | same qualification store |
| C48 | Action availability | `api/commands/availability.py` | KEEP | pure over read facts |
| C49 | Canonical deliverable payload | `deliverable/canonical.py` | KEEP | re-anchoring is host logic |
| C50 | Render (HTML) | `deliverable/render.py` | KEEP | parity golden |
| C51 | Revisions | `deliverable/revisions.py` | KEEP | immutable revisions unchanged |
| C52 | Filing chain + receipts | `deliverable/filing.py`, `receipts.py` | KEEP | three-actor chain unchanged |
| C53 | Audit package + verifier | `deliverable/package.py`, `verify_package.py` | KEEP | stdlib verifier; render parity covers the payload |
| C54 | ORCHESTRATION_PROOF | `qualification/proof.py` | KEEP | proof re-derives from the store |
| C55 | Qualification harness | `qualification/harness.py` | CHANGE | provider identity string per D8 |
| C56 | Matrix + set digest | `qualification/matrix.py` | KEEP | deterministic comparison |
| C57 | On-disk qualification sets | `qualification/on_disk.py`, `qualification/*` | KEEP | public documents only |
| C58 | Qualification store + verdict | `qualification/store.py`, `verdict.py` | KEEP | schema unchanged; identity string per D8 |
| C59 | Document register | `qualification/documents.json`, `scripts/document_register.py` | KEEP | demand and sha256 gate unchanged |
| C60 | Workspace shell (9 sections) | `frontend/src/app/*` | KEEP | copied (D3) |
| C61 | Chrome bands | `frontend/src/chrome/*` | KEEP | copied with the workspace (D3) |
| C62 | Region states | `frontend/src/states/*`, `ds/*` | KEEP | copied (D3) |
| C63 | Evidence surface | `frontend/src/evidence/*` | KEEP | copied (D3) |
| C64 | Sections | `frontend/src/sections/*` | KEEP | copied (D3) |
| C65 | Client transport / SSE / commands | `frontend/src/app/*.ts`, `wire/v1` | KEEP | copied (D3); SSE verified on deploy (C42) |
| C66 | Demo/fixture mode | `frontend/vite.config.ts`, `fixtures/*` | KEEP | copied (D3); the workbench gate depends on it |
| C67 | Frontend tests (unit, a11y, workbench, journey spec) | `frontend/tests/*`, `scripts/a11y-axe.mjs` | CHANGE | journey config kept but not run (needs the compose stack, D14) |
| C68 | Repo gate scripts | `scripts/{check_vocabulary,check_tested,io_budget,scan_floors,check_pr_size,tracked}.py` | KEEP | paths `server`→`caos` |
| C69 | Dev tooling | `scripts/dev_doctor.py`, `check_postgres.py`, `dev-init.sql`, `Makefile`, `compose.yaml` | CHANGE | Makefile targets become `uv run` commands; `compose.yaml` keeps only the two Postgres services; `measure_admission.py` KEEP |
| C70 | Live qualification driver | `scripts/qualify.py` | CHANGE | gateway identity; OpenRouter flags removed |
| C71 | Release pack | `scripts/release_pack.py` | KEEP | reads store and tree; identity string per D8 |
| C72 | Image / compose smoke / Trivy | `Dockerfile`, `compose.smoke.yaml`, `scripts/install_trivy.sh` | DROP | no image on Databricks Apps (D14) |
| C73 | CI workflow | `.github/workflows/ci.yml` | CHANGE | jobs lint, types, test, postgres, security, size, frontend; sonarqube/image/smoke/provider removed; a `gateway` dispatch-only job is logged in `next.md`, not built |
| C74 | Backend test suite | `tests/*` | KEEP | ported; OpenRouter-marked tests use the adapter |
| C75 | Probes + journey runner | `tests/probes/*`, `tests/journey/run.py` | CHANGE | probes KEEP; `journey/run.py` DROP (compose/TLS edge) |
| C76 | Claude hooks (guard/format) | `scripts/claude_hook.py`, `.claude/settings.json` | DROP | rules restated in §1; formatter would fight targeted edits (D22) |
| C77 | GitNexus skills + phase reviewer agents | `.claude/skills/gitnexus/*`, `.claude/agents/*` | DROP | external CLI, not a gate; review cadence replaced by §1 evidence rules |

Deploy V components (all under `vendor/deploy-v/`):

| # | Component | Status | Reason |
|---|---|---|---|
| V1 | 25 physical skills `skills/cp-*` (CP-0, 1, 1A, 1B, 1C, 1D, 2, 2A, 2D, 2E, 2G, 2H, 3, 3C, 3D, 4, 4C, 5, 6, 8, DR, L10, MEMO, MODEL, OS) with their `references/` and stdlib `scripts/` | KEEP | methodology authority, byte-verified at use; one ICM stage contract per skill names its files |
| V2 | Alias table (CP-PARSE, 2B, 2C, 2F, 3A, 3B, 4A, 4B, 4D, 5A, 6A, L20–L40) | KEEP | resolved through the retrieval index as legacy |
| V3 | `CANON_SHARED.md` | KEEP | shared canon, referenced by every stage contract |
| V4 | `CP_DEPLOY_V_RETRIEVAL_INDEX_v1.json`, `DEPLOY_V_MANIFEST.json`, `DEPLOY_V_BASELINE.json`, `DEPLOY_V_INTEGRITY_v1.json` | KEEP | routing + integrity authority |
| V5 | `CP_DEPLOY_V_EXECUTION_PROFILES_v1.json` (FULL_CREDIT_32, LITE_CREDIT_22) | KEEP | route catalog |
| V6 | `CP_DEPLOY_V_CHILD_SCHEMA_REGISTRY_v1.json`, payload base schemas | KEEP | validator inputs |
| V7 | `verify_package.py`, `tests/*.py` | KEEP | acceptance A29 |
| V8 | `DEPLOY_V_COPILOT_MEMORY_PROMPT*.md` | KEEP (inert) | part of the integrity manifest; never loaded by a stage |
| V9 | CP-MEMO exporter (`python-docx`, `pypdf`, `soffice`) and CP-MODEL exporter (`openpyxl`) scripts | KEEP (inert) | legacy decision §14: the host places no model build and no publication module; files stay for integrity, no dependency added |
| V10 | CP-CF host extension (`methodology/skills/cp-cf`) | CHANGE | moves to `icm/stages/cp-cf/references/` (C29) |

## 9. Skills ledger

`name | source + version/SHA | status | consumer | destination | reason | conflicts`

| Name | Source | Status | Consumer | Destination | Reason | Conflicts |
|---|---|---|---|---|---|---|
| databricks-core | databricks/databricks-agent-skills@e77e37e8 v0.2.20 | KEEP | builder | `.claude/skills/databricks-core/` (vendored) | CLI auth/profiles for A30–A31; parent of the others | none |
| databricks-apps-python | same | KEEP | builder | `.claude/skills/databricks-apps-python/` | App runtime, `app.yaml`, resources, Lakebase from an app | its default "reach for AppKit first" is overridden by fixed requirement (Python app) |
| databricks-lakebase | same | KEEP | builder | `.claude/skills/databricks-lakebase/` | connectivity, credentials, autoscaling vs provisioned | none |
| databricks-model-serving | same | KEEP | builder | `.claude/skills/databricks-model-serving/` | endpoint querying, AI Gateway | none |
| databricks-dabs | same | KEEP | builder | `.claude/skills/databricks-dabs/` | bundle structure, validate/deploy/run, app resource permissions | none |
| databricks-python-sdk | same | KEEP | builder | `.claude/skills/databricks-python-sdk/` | `WorkspaceClient`, Files API, SCIM | none |
| databricks-setup-local, -docs, -mlflow-evaluation, -agent-bricks, -ai-functions, -aibi-dashboards, -app-design, -apps (AppKit), -data-discovery, -dbsql, -execution-compute, -genie-agents, -iceberg, -jobs, -lakeflow-connect, -metric-views, -ml-training, -pipelines, -serverless-migration, -spark-structured-streaming, -synthetic-data-gen, -unity-catalog, -unstructured-pdf-generation, -vector-search, -zerobus-ingest | same | DROP | — | — | no requirement, gate or ledger row needs them | — |
| databricks-ai-runtime, spark-python-data-source (experimental) | same, `experimental/` | DROP | — | — | experimental; nothing needs them | — |
| gitnexus-cli, -debugging, -exploring, -guide, -impact-analysis, -refactoring | legacy `.claude/skills/gitnexus/` | DROP | — | — | depend on an external CLI; not a gate | — |
| final-phases-reviewer, phase-adversarial-auditor, phase-confidence-reviewer, task-acceptance-reviewer | legacy `.claude/agents/` | DROP | — | — | phase-review cadence replaced by §1 evidence rules; reference OpenRouter env | reference OpenRouter |
| Deploy V 25 skills (V1) | legacy `vendor/deploy-v@78c24be4` | ADAPT | runtime (graph nodes) | referenced from `icm/stages/<slug>/CONTEXT.md`; bytes stay in `vendor/deploy-v/` | methodology content kept whole (D4); Claude/Copilot launcher text is not loaded | Copilot memory prompts (inert) |
| cp-cf (host extension) | legacy `methodology/skills/cp-cf` | ADAPT | runtime | `icm/stages/cp-cf/references/` | host-owned calculator contract | none |
| DEPLOY_B_COWORK_SKILLS (32 skills + 5 tools) | `/Users/ericguei/Documents/Co-Pilot Agents/DEPLOY_B_COWORK_SKILLS` | DROP | — | — | superseded by the pinned Deploy V build; its `COWORK_MIGRATION_MANIFEST.json` marks it `historical_non_runtime`; Cowork-platform mechanics | overlaps every Deploy V module |
| Conventions (one term per concept, Decimal on money, typed refusals, no document text in logs, `uv run` everything) | legacy `CLAUDE.md`, `CONTEXT.md` | MERGE | every session | `CLAUDE.md` §Conventions | short rules every turn needs | none |

Hooks active during the build: see D22. No project-level hooks are configured; no autofix hook rewrites files.

## 10. Parity

Every KEEP/CHANGE row that computes financial values or a deterministic pin gets golden-output tests against the legacy snapshot. Generate goldens once with `tests/parity/generate_goldens.py`, run under the legacy interpreter:

```bash
LEGACY="$LEGACY_RO/repo"; TMP="$(mktemp -d)"
uv venv --python 3.14 "$TMP/venv"
uv pip install --python "$TMP/venv" --require-hashes --only-binary :all: -r "$LEGACY/requirements.txt"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$LEGACY" "$TMP/venv/bin/python" tests/parity/generate_goldens.py --legacy "$LEGACY" --out tests/parity/golden
```

Golden groups (directory names under `tests/parity/golden/`, each with a `manifest.json` naming inputs and sha256 of outputs; the tests in `tests/parity/test_<group>.py` recompute with `caos` and compare exactly):

| Group | Legacy function(s) | Inputs |
|---|---|---|
| `cash_flow` | `calculators.cash_flow.cash_flow_forecast`, `forecast_bytes` | every request in `tests/test_cash_flow_forecast.py` and `tests/forecast_fixtures.py` |
| `pricing` | `pricing.priced_request`, `worst_case` | grid of byte sizes × three dated prices |
| `budget` | `store.budget.validate_spend`, `remaining`, `ceiling_of` | legacy `tests/test_budget.py` cases (pure parts) |
| `forecast` | `methodology.forecast.forecast_projection`, `validate_forecast_bindings`, `validate_driver_mapping` | `tests/forecast_fixtures.py` |
| `routes` | `engine.route.resolve_route` → digest, node order, edges, predicates | all 18 `(profile, selection)` pairs from `ADAPTER_ROUTES`, with and without research/model extensions |
| `digest` | `digest` canonical JSON | fixture objects incl. nested Decimal/None/unicode |
| `boundary_text` | `BoundaryText` | accept/refuse table incl. NFC, bidi, controls |
| `extraction` | `evidence.extract` (plain text) | three public documents from `qualification/*/documents/*.txt` |
| `citations` | `evidence.citations` anchoring | answer-key quotes from the matching `qualification.json` files against the extraction tokens |
| `render` | `deliverable.render` | one frozen canonical payload fixture |
| `prompt` | `methodology.invocation` rendered prompt bytes | one assignment per stage folder from route fixtures |

LLM-dependent behaviour (module output, verdicts) gets contract tests on structure and required fields (`tests/graph/`), never exact output. The charge path (D8) gets contract tests, not parity.

## 11. Acceptance criteria and evidence

Run every command from the repo root in the final turn and print an EVIDENCE table (`# | command | exit | summary`) in the final message, copied from the tool output of that turn. "Summary" is one line: the pytest summary line, the last line of a linter, the count of matches, the health JSON.

| # | Command | Expected |
|---|---|---|
| A1–A25 | gate commands G1–G25 in §5, one row each, run exactly as written (G10 and G13 are compound rows; G26 is CI-only and has no acceptance row) | exit 0; A4 prints `N passed, 0 failed, 0 skipped, 0 xfailed` with N ≥ 1,786 (legacy has 2,073 test functions in 172 files; 88 of them sit in the five files tied to dropped rows C32/C72/C75/C76; the floor is 90% of the remainder, and every test below that remainder is named in an `Fn` entry) and `TOTAL … ≥ 80%` |
| A26 | `CAOS_REQUIRE_PROVIDER=1 CAOS_REQUIRE_POSTGRES=1 uv run pytest --no-cov tests/parity tests/graph` | exit 0; prints passed count and the eleven golden group directories present (`ls tests/parity/golden`) |
| A27 | `uv run python -B vendor/deploy-v/verify_package.py` | exit 0 |
| A28 | `grep -rniI openrouter caos icm .claude/skills databricks.yml app.yaml; echo "exit=$?"` | no output, `exit=1` |
| A29 | `uv run python -c "import sys; print(sys.version)"` and `grep -n requires-python pyproject.toml && cat .python-version` | `3.13.x`; `>=3.13,<3.14`; `3.13` |
| A30 | `databricks bundle validate` (G27) | exit 0, or blocker B1/B2 quoted |
| A31 | deploy access `yes`: `databricks bundle deploy -t dev && databricks bundle run caos && databricks apps get caos` (state `RUNNING`), `curl -fsS "$APP_URL/api/health"` (200, `python_version` starts `3.13`), `uv run python scripts/gateway_smoke.py` (prints endpoint name, response id, input/output tokens from one real `ChatDatabricks` call; exit 0). Deploy access `no`: `blockers.md` contains the line `gateway path unverified` with the command and error | as stated |
| A32 | `ls .claude/skills` | the six vendored skills listed |
| A33 | `git status --short && git rev-parse HEAD` | clean; commit hash printed |

Then print: the capability ledger (C1–C77) and Deploy V ledger (V1–V10) with each row `implemented` or `dropped: <reason>`; the skills ledger with each row's status; `docs/rebuild/blockers.md` verbatim.

## 12. Conventions for the new `CLAUDE.md`

Repo map (one line per top-level dir); commands (`uv sync --locked --all-groups`, `uv run caos-serve` (corrected: F3 -- `uv run python -m caos.serve`; the project is virtual and has no `[project.scripts]` entry), `docker compose up -d --wait`, `npm --prefix frontend ci --ignore-scripts`); the gate commands G1–G25 verbatim; the eleven invariants (one line each, invariant 6 as refined by D6); conventions: one term per concept (`CONTEXT.md`), Decimal never float on money, typed refusals and no `str(exc)` on the wire, never log document text, every module under `caos/api/` declares `IO_BUDGET`, every public definition is named by a test, no new dependency without a `Dn` entry, stdlib before new code, targeted edits, `uv run` for everything, OpenRouter only under `tests/`, never edit `vendor/deploy-v/`. Under 120 lines.

## 13. Verified platform facts (do not re-derive; re-verify only if a call fails)

- Apps use uv + `requires-python` only when `requirements.txt` is absent and `uv.lock` is present (R8); default otherwise is pip + Python 3.11.
- `app.yaml`: `command:` list (no shell), `env:` list of `{name, value|valueFrom}`; auto env `DATABRICKS_HOST`, `DATABRICKS_APP_PORT`, `DATABRICKS_CLIENT_ID/SECRET`, `DATABRICKS_APP_NAME`, `DATABRICKS_WORKSPACE_ID`; app listens on `0.0.0.0:$DATABRICKS_APP_PORT`.
- Bundle `apps` resource: `source_code_path`, `config.command`, `config.env[].value_from`, `resources[]` with `serving_endpoint{name, permission: CAN_QUERY}`, `database{instance_name, database_name, permission: CAN_CONNECT_AND_CREATE}` or `postgres{branch, database, permission}`, `uc_securable`, `secret`; `databricks bundle validate|deploy|run|summary`; `databricks apps get|deploy|logs`.
- `from databricks_langchain import ChatDatabricks, CheckpointSaver, AsyncCheckpointSaver, DatabricksStore`; `ChatDatabricks(endpoint=..., max_tokens=..., extra_params=...)`; `CheckpointSaver(instance_name=..., schema=...)` / `(autoscaling_endpoint=..., project=..., branch=...)`, `.setup()`.
- Lakebase app env: `PGHOST PGPORT PGDATABASE PGUSER PGSSLMODE PGAPPNAME`; credentials via `WorkspaceClient().database.generate_database_credential(request_id=..., instance_names=[...])` or `.postgres.generate_database_credential(endpoint=...)`; 60-minute token life.
- Apps forward `x-forwarded-access-token`; default user scopes include `iam.current-user:read`; SDK Files API `w.files.upload(path, contents, overwrite=True)`, `w.files.download(path).contents`, paths `/Volumes/<catalog>/<schema>/<volume>/...`.
- Claude endpoints (FMAPI, pay-per-token): `databricks-claude-opus-5`, `databricks-claude-sonnet-5`, `databricks-claude-fable-5-1`.
- OpenRouter test model `anthropic/claude-opus-5-20260723` (1M context, 128K completion, $5/$25 per MTok); example `CAOS_MODEL_PRICE=anthropic/claude-opus-5-20260723,0.000005,0.000025,2026-09-22`.
- `/goal`: evaluator reads only the transcript; background subagents defer evaluation, so run acceptance commands in the main session.
