#!/usr/bin/env bash
# From workspace values to a verified deployment, in one command (F31).
#
#   scripts/enterprise_deploy.sh <profile> <catalog> <schema> <lakebase_instance> \
#       [endpoint] [price] [run_ceiling]
#
# Optional, by environment: TARGET (prod), LAKEBASE_DATABASE (databricks_postgres),
# GROUP_ADMIN (caos-admins), GROUP_ANALYST (caos-analysts), PG_PORT (5432),
# PG_SSLMODE (require), EVIDENCE (docs/rebuild/runs/<today>/enterprise/<time>),
# BUNDLE_STATE (.databricks/bundle/<target>).
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
# Where the CLI keeps the target's state, its deployment record among it.
BUNDLE_STATE="${BUNDLE_STATE:-.databricks/bundle/$TARGET}"
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

record() {  # id, command, exit code, log, [record flags...]
  uv run python scripts/enterprise_deploy.py --stage record "${VALUES[@]}" \
    --step "$1" --command "$2" --code "$3" --log "$4" "${@:5}"
}
bundle() {  # id, verb... [:: record flags...]
  local id="$1"; shift
  local verb=()
  while [ "$#" -gt 0 ] && [ "$1" != "::" ]; do verb+=("$1"); shift; done
  if [ "$#" -gt 0 ]; then shift; fi
  local log="$EVIDENCE/$id.log" code=0
  databricks bundle "${verb[@]}" -t "$TARGET" ${PROFILE_FLAG[@]+"${PROFILE_FLAG[@]}"} "${VARS[@]}" > "$log" 2>&1 || code=$?
  record "$id" "databricks bundle ${verb[*]} -t $TARGET" "$code" "$log" "$@"
}
# E2 is validate in its JSON form: what the CLI resolved must be the endpoint,
# price and run ceiling given (a misspelt BUNDLE_VAR validates on the default,
# DF-4), and it names the app E5 reads (DF-5). Its diagnostics are the log.
RESOLVED="$EVIDENCE/bundle.json"
code=0
databricks bundle validate -o json -t "$TARGET" ${PROFILE_FLAG[@]+"${PROFILE_FLAG[@]}"} \
  "${VARS[@]}" > "$RESOLVED" 2> "$EVIDENCE/E2.log" || code=$?
record E2 "databricks bundle validate -o json -t $TARGET" "$code" "$EVIDENCE/E2.log" \
  --bundle "$RESOLVED"
# E3 is held to the CLI's own record of what it synced: every tracked file
# under the sync roots and every file of the built export (F48, DF-4).
bundle E3 deploy :: --shipped "$BUNDLE_STATE/deployment.json"
bundle E4 run caos

uv run python scripts/enterprise_deploy.py --stage after "${VALUES[@]}" --bundle "$RESOLVED"
