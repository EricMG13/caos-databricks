# Blockers

Entries record a missing external resource with the exact command and error. A failing test or gate is never a blocker.

## Spec-author run, 2026-09-22

- B1 — Databricks CLI not installed. `command -v databricks` → `databricks: MISSING` (`(eval):1: command not found: databricks`). Consequence: `databricks aitools list` was replaced by enumerating the skills repo at commit `e77e37e8a4dabbe2662b680c180bb72a05eca48d`; `DEPLOY_ACCESS=no` in the launcher; acceptance A30–A31 will be blocked until fixed. Fix (user): `brew tap databricks/tap && brew install databricks`, then `databricks auth login --profile <DBX_PROFILE>`.
- B2 — Databricks workspace facts unknown: host, CLI profile, Unity Catalog schema, Lakebase instance, AI Gateway endpoint names. `grep -rIl databricks` over `/Users/ericguei/Documents/caos-v2` and `caos-workbench` → 0 files; a host-pattern grep over `/Users/ericguei/Documents` → no matches; reading `~/.databrickscfg` was refused by the auto-mode classifier ("Credential Exploration"). Consequence: the spec names environment variables (`DATABRICKS_CONFIG_PROFILE`, `CAOS_UC_SCHEMA`, `CAOS_LAKEBASE_INSTANCE`, `CAOS_MODEL_ENDPOINT`) and a default endpoint; `launch.sh` keeps `CHANGE_ME` for `DBX_HOST`, `DBX_PROFILE`, `UC_SCHEMA`, `LAKEBASE_INSTANCE`, `GATEWAY_ENDPOINTS`.
- B3 — Claude Code version. `claude --version` → `2.1.246 (Claude Code)`; the launcher preflight requires ≥ 2.1.259 (`--permission-prompts none`). `/goal` itself exists since 2.1.139. Fix (user): `claude update`.
- B4 — Legacy OpenRouter key file. `[ -f /Users/ericguei/Documents/caos-v2/.env ]` → absent; absent in `CAOS-Final` and `caos test`; `/Users/ericguei/Documents/caos-workbench/.env` exists but `grep -cE '^(export )?OPENROUTER_API_KEY=' …` → `0`; `OPENROUTER_API_KEY` is not set in this session. Consequence: `LEGACY_ENV_FILE` stays `CHANGE_ME`; the OpenRouter-backed tests cannot run until the launcher exports the key. Never write the key into any file.
- B5 — Lakebase PostgreSQL major version not stated on https://docs.databricks.com/aws/en/oltp/ (fetched 2026-09-22). Consequence: local tests keep `postgres:17-alpine`; the builder records `SELECT version()` from Lakebase on first deploy (D17).
- B6 — Databricks Apps user-identity headers other than `x-forwarded-access-token` are not on the auth docs page fetched (https://docs.databricks.com/aws/en/dev-tools/databricks-apps/auth). Consequence: identity is resolved through SCIM `Me` with the forwarded token (D10), which needs no other header.
- B7 — `.python-version` handling by Databricks Apps is undocumented (https://docs.databricks.com/aws/en/dev-tools/databricks-apps/dependencies). Consequence: `requires-python` is the binding pin; `.python-version` is kept for uv locally.

## Build run

(the builder appends here; each entry quotes the command and the exact error)
