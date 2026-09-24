#!/usr/bin/env bash
# From workspace values to a verified deployment, in one command (F31).
#
#   scripts/enterprise_deploy.sh [--provisioned] <profile> <catalog> <schema> <lakebase> \
#       [endpoint] [price] [run_ceiling]
#
# <lakebase> is the Lakebase Autoscaling project id, the default kind (targets
# dev and prod). With --provisioned it is an existing Lakebase Provisioned
# instance's name instead, and the target is TARGET's Provisioned pair
# (dev-provisioned, prod-provisioned); R24-14.
#
# Optional, by environment: TARGET (prod: dev or prod, never a -provisioned
# name, which the flag chooses), for Autoscaling LAKEBASE_BRANCH (production),
# LAKEBASE_ENDPOINT (primary) and LAKEBASE_DATABASE_ID (databricks-postgres),
# for Provisioned LAKEBASE_DATABASE (databricks_postgres), GROUP_ADMIN
# (caos-admins), GROUP_ANALYST (caos-analysts), PG_PORT (5432), PG_SSLMODE
# (require), EVIDENCE (docs/rebuild/runs/<today>/enterprise/<time>),
# BUNDLE_STATE (.databricks/bundle/<target>).
# An empty profile means the SDK's ambient auth (DATABRICKS_HOST and a token).
#
# Steps E1..E10 are described in scripts/enterprise_deploy.py; the three
# `databricks bundle` commands run here and are recorded as E2, E3 and E4.
# The script stops at the first step that fails. Nothing secret is printed.
set -euo pipefail
cd "$(dirname "$0")/.."
# The engine every stand-in run used; the other one needs a Terraform download.
export DATABRICKS_BUNDLE_ENGINE=direct

KIND=autoscaling
case "${1:-}" in
  --provisioned) KIND=provisioned; shift ;;
  --*) echo "unknown flag ${1}: the one flag is --provisioned" >&2; exit 2 ;;
esac
PROFILE="${1?profile (may be empty: '')}"
CATALOG="${2:?catalog}"
SCHEMA="${3:?schema}"
LAKEBASE="${4:?lakebase project (or, with --provisioned, the instance)}"
# One source (N23): databricks.yml's own variable defaults, read back
# rather than repeated here. `: "${NAME:=...}"` only fills a name this
# shell does not already have, so an inherited GROUP_ADMIN etc. still wins.
eval "$(uv run python scripts/bundle_defaults.py --shell)"
ENDPOINT="${5:-$MODEL_ENDPOINT}"
PRICE="${6:-$MODEL_PRICE}"
CEILING="${7:-$RUN_CEILING}"
TARGET="${TARGET:-prod}"
case "$TARGET" in
  *-provisioned) echo "TARGET names dev or prod; --provisioned chooses its Provisioned pair" >&2; exit 2 ;;
esac
# GROUP_ADMIN, GROUP_ANALYST and the LAKEBASE_* defaults are already set by
# the eval above (their own bundle default, or an inherited value it left
# alone). The target binds the kind (databricks.yml); each kind takes its own.
if [ "$KIND" = provisioned ]; then
  TARGET="$TARGET-provisioned"
  LAKEBASE_VALUES=(--lakebase-instance "$LAKEBASE" --lakebase-database "$LAKEBASE_DATABASE")
  LAKEBASE_VARS=(--var "lakebase_instance=$LAKEBASE" --var "lakebase_database=$LAKEBASE_DATABASE")
else
  LAKEBASE_VALUES=(--lakebase-project "$LAKEBASE" --lakebase-branch "$LAKEBASE_BRANCH"
    --lakebase-endpoint "$LAKEBASE_ENDPOINT" --lakebase-database-id "$LAKEBASE_DATABASE_ID")
  LAKEBASE_VARS=(--var "lakebase_project=$LAKEBASE" --var "lakebase_branch=$LAKEBASE_BRANCH"
    --var "lakebase_endpoint=$LAKEBASE_ENDPOINT" --var "lakebase_database_id=$LAKEBASE_DATABASE_ID")
fi
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
  "${LAKEBASE_VALUES[@]}"
  --endpoint "$ENDPOINT" --price "$PRICE" --run-ceiling "$CEILING"
  --group-admin "$GROUP_ADMIN" --group-analyst "$GROUP_ANALYST"
  --pg-port "$PG_PORT" --pg-sslmode "$PG_SSLMODE")
# The price holds commas, and the CLI splits a `--var` value on commas (C1);
# the environment form carries it whole.
export BUNDLE_VAR_model_price="$PRICE"
VARS=(--var "model_endpoint=$ENDPOINT" --var "run_ceiling=$CEILING"
  --var "uc_catalog=$CATALOG" --var "uc_schema=$SCHEMA" "${LAKEBASE_VARS[@]}"
  --var "group_admin=$GROUP_ADMIN"
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
