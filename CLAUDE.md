# CAOS on Databricks — Layer 0

Governed source documents to committee-ready credit conclusions, as one Databricks App: FastAPI serves the nine-section workspace and the API, LangGraph runs each pinned methodology route one node at a time, Lakebase Postgres holds the store and the graph checkpoints, a Unity Catalog volume holds every byte by digest, and every model call goes through Databricks AI Gateway behind one factory. The build contract is `docs/rebuild/2026-09-22-caos-databricks-spec.md`; decisions are `docs/rebuild/decisions.md`.

## Repo map

- `caos/` — the app package. `api/` (edge, identity, wire models, section reads, commands, health, site), `store/` (psycopg SQL, ordered migrations, `lakebase.py`), `evidence/`, `methodology/` (bundle authority, canonical executor, invocation), `graph/` (`route.py` resolution, `build.py` LangGraph graph, `runtime.py` node passes, `worker.py`), `calculators/`, `deliverable/`, `qualification/`, `models.py` (the model factory), `blobs.py`, `icm.py`, `serve.py` (the process entry).
- `icm/` — agent definitions: `CONTEXT.md` (Layer 1), `stages/<slug>/` contracts and prompt declarations, `shared/prompt/` the host prompt blocks, `HOST_INTEGRITY_v1.json`.
- `vendor/deploy-v/` — the methodology bundle, read-only and byte-verified at use. Never edit it.
- `frontend/` — the React workspace, built to `frontend/dist` and served by the app.
- `scripts/` — gates and tooling; `tests/` — the suite, `tests/parity/` goldens against the legacy host, `tests/graph/` the graph.
- `app.yaml`, `databricks.yml` — the App and its bundle; `docs/DEPLOYMENT.md` — the enterprise runbook; `scripts/enterprise_deploy.sh` — the one deployment command (F31); `tests/workspace_stub.py` and `tests/platform_app.py` — the workspace and the platform boot, stood in locally (D28).

## Commands

```bash
uv sync --locked --all-groups && docker compose up -d --wait
npm --prefix frontend ci --ignore-scripts && npm --prefix frontend run build
CAOS_TEST_POSTGRES_URL=postgresql://postgres:local-test-admin-only@127.0.0.1:55437/postgres CAOS_REQUIRE_POSTGRES=1 uv run pytest -n auto -m "not live_provider"
uv run python -m caos.serve            # local API on 127.0.0.1:8000 (dev mode needs .env from .env.example)
```

## Gates (all must exit 0; none may be loosened)

`uv run ruff check .` · `uv run ruff format --check .` · `uv run mypy caos scripts tests` · `CAOS_REQUIRE_POSTGRES=1 uv run pytest -n auto -m "not live_provider"` (coverage ≥ 80%) · `uv run python scripts/scan_floors.py coverage.xml --cobertura` · `CAOS_REQUIRE_POSTGRES=1 uv run pytest --no-cov tests/test_postgres_races.py` · `uv run python scripts/check_vocabulary.py` · `uv run python scripts/check_tested.py` · `uv run python scripts/io_budget.py --assert` · bandit with the floor (`scripts/scan_floors.py bandit.json --no-parse-errors --cover caos scripts icm --unscanned tests`) · `uv run pip-audit --strict` (after `uv sync --locked`) · `gitleaks git --no-banner` · `uv lock --check && uv sync --locked --all-groups` · `uv run complexipy caos scripts icm --max-complexity-allowed 15` (new code; `complexipy-snapshot.json` baselines the 25 legacy functions above 15) · `npx --prefix frontend --no-install jscpd --threshold 3 --min-lines 10 --ignore "**/node_modules/**,**/dist/**,**/dist-demo/**" caos scripts icm frontend/src` · `uv run python scripts/check_gate_config.py` (suppression counts equal `tests/gate_baseline.json`) and `--against <an earlier commit's tests/gate_baseline.json>` (no budget rose; CI holds a push to the tip it replaced and a pull request to its base) · `uv run python scripts/check_icm.py` · `uv run pre-commit run --all-files` · `npm --prefix frontend run lint|typecheck|test|build|build:demo|a11y|test:workbench` · `databricks bundle validate` (with a profile) and, until one exists, `uv run python tests/workspace_stub.py -- databricks bundle validate -t dev --var uc_catalog=main --var uc_schema=caos --var lakebase_instance=caos-lb` (D28), plus `bundle deploy` and `bundle run caos` the same way (A35, A36), a non-default price as `BUNDLE_VAR_model_price=<endpoint,in,out,date>` (the CLI splits a `--var` on commas, C1), and the `prod` target's validate, deploy and run under one stub via `sh -c "... && ... && ..."` (A37), each deploy followed by `uv run python scripts/check_gate_config.py --shipped .databricks/bundle/<dev|prod>/deployment.json` with the export built first (every tracked file under the sync roots and every export file was synced; DF-4). The stub clears the bundle state an earlier stand-in run left and refuses a real workspace's (DF-13).

## Invariants (never weaken)

1. Pinned sources only; no web discovery. 2. Evidence reads fail closed with a typed code, no text on refusal. 3. The host owns identity; provider frontmatter never survives. 4. The bundle is the methodology authority, verified on the bytes at use; never edit an upstream file. 5. Human gates are digest-bound. 6. Execution is durable and exactly-once: the accepted-attempt ledger is the truth, the LangGraph checkpoint only remembers position (D6). 7. Calculation is pure and finite; Decimal, never float, on money. 8. Budgets fail closed; no model call without a reservation. 9. Module output is the strict canonical envelope. 10. The route is resolved once and pinned. 11. Citations are coordinate-anchored or refused.

## Conventions

- One term per concept (`CONTEXT.md`); `scripts/check_vocabulary.py` enforces it on identifiers.
- Typed refusals only; never `str(exc)` on the wire or in a log; never log document text.
- Every module under `caos/api/` declares `IO_BUDGET`; every public definition is named by a test.
- No new dependency without a `Dn` entry in `docs/rebuild/decisions.md`; stdlib, then an already-pinned dependency, then new code.
- Targeted edits over whole-file rewrites; `uv run` for every tool; Python is `>=3.13,<3.14`; no `requirements.txt` at the root.
- OpenRouter exists only under `tests/` (the adapter); production calls go through `caos.models.chat_model`.
- Suppressions (`noqa`, `type: ignore`, `nosec`, `pragma`, skips) may only fall: `tests/gate_baseline.json`.
- Findings you fix go in `decisions.md` as `Fn`; new scope goes in `docs/rebuild/next.md`; missing external resources go in `docs/rebuild/blockers.md` with the exact command and error.
