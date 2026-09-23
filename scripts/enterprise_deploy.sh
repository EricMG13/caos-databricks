#!/usr/bin/env bash
# From workspace values to a verified deployment, in one command (F31).
#
#   scripts/enterprise_deploy.sh <profile> <catalog> <schema> <lakebase_instance> \
#       [endpoint] [price] [run_ceiling]
#
# Optional, by environment: TARGET (prod), LAKEBASE_DATABASE (databricks_postgres),
# GROUP_ADMIN (caos-admins), GROUP_ANALYST (caos-analysts), PG_PORT (5432),
# PG_SSLMODE (require), EVIDENCE (docs/rebuild/runs/<today>/enterprise/<time>).
# An empty profile means the SDK's ambient auth (DATABRICKS_HOST and a token).
#
# Steps E1..E9 are described in scripts/enterprise_deploy.py; the three
# `databricks bundle` commands run here and are recorded as E2, E3 and E4.
# The script stops at the first step that fails. Nothing secret is printed.
set -euo pipefail
cd "$(dirname "$0")/.."
# The engine every stand-in run used; the other one needs a Terraform download.
export DATABRICKS_BUNDLE_ENGINE=direct

PROFILE="${1?profile (may be empty: '')}"
CATALOG="${2:?catalog}"
SCHEMA="${3:?schema}"
INSTANCE="${4:?lakebase instance}"
ENDPOINT="${5:-databricks-claude-opus-5}"
PRICE="${6:-databricks-claude-opus-5,0.000005,0.000025,2026-09-22}"
CEILING="${7:-100.00}"
TARGET="${TARGET:-prod}"
LAKEBASE_DATABASE="${LAKEBASE_DATABASE:-databricks_postgres}"
GROUP_ADMIN="${GROUP_ADMIN:-caos-admins}"
GROUP_ANALYST="${GROUP_ANALYST:-caos-analysts}"
PG_PORT="${PG_PORT:-5432}"
PG_SSLMODE="${PG_SSLMODE:-require}"
# One directory per run (N2): a rerun after an unverified row never
# interleaves its rows with the first run's.
EVIDENCE="${EVIDENCE:-docs/rebuild/runs/$(date -u +%F)/enterprise/$(date -u +%H%M%S)}"
mkdir -p "$EVIDENCE"

VALUES=(--evidence "$EVIDENCE" --profile "$PROFILE" --target "$TARGET"
  --catalog "$CATALOG" --schema "$SCHEMA"
  --lakebase-instance "$INSTANCE" --lakebase-database "$LAKEBASE_DATABASE"
  --endpoint "$ENDPOINT" --price "$PRICE" --run-ceiling "$CEILING"
  --group-admin "$GROUP_ADMIN" --group-analyst "$GROUP_ANALYST"
  --pg-port "$PG_PORT" --pg-sslmode "$PG_SSLMODE")
# The price holds commas, and the CLI splits a `--var` value on commas (C1);
# the environment form carries it whole.
export BUNDLE_VAR_model_price="$PRICE"
VARS=(--var "model_endpoint=$ENDPOINT" --var "run_ceiling=$CEILING"
  --var "uc_catalog=$CATALOG" --var "uc_schema=$SCHEMA" --var "lakebase_instance=$INSTANCE"
  --var "lakebase_database=$LAKEBASE_DATABASE" --var "group_admin=$GROUP_ADMIN"
  --var "group_analyst=$GROUP_ANALYST")
PROFILE_FLAG=()
if [ -n "$PROFILE" ]; then PROFILE_FLAG=(-p "$PROFILE"); fi

uv run python scripts/enterprise_deploy.py --stage before "${VALUES[@]}"

bundle() {  # id, verb...
  local id="$1"; shift
  local log="$EVIDENCE/$id.log" code=0
  databricks bundle "$@" -t "$TARGET" ${PROFILE_FLAG[@]+"${PROFILE_FLAG[@]}"} "${VARS[@]}" > "$log" 2>&1 || code=$?
  uv run python scripts/enterprise_deploy.py --stage record --evidence "$EVIDENCE" \
    --step "$id" --command "databricks bundle $* -t $TARGET" --code "$code" --log "$log"
  return "$code"
}
bundle E2 validate
bundle E3 deploy
bundle E4 run caos

uv run python scripts/enterprise_deploy.py --stage after "${VALUES[@]}"
