#!/usr/bin/env bash
# CAOS v2 -> Databricks App: unattended two-stage rebuild.
#   Stage 1: spec author runs META_PROMPT.md and writes the spec + goal condition.
#            (Already executed interactively on 2026-09-22; set SKIP_STAGE1=1 to reuse
#            docs/rebuild/2026-09-22-goal.txt instead of re-running it.)
#   Stage 2: Claude Fable 5.1 builds under /goal until the condition holds.
#
# One-time setup (the only manual steps):
#   1. Fill in the CONFIG block below (remaining CHANGE_ME: see docs/rebuild/blockers.md B1-B4).
#   2. Authenticate the Databricks CLI profile: databricks auth login --profile <DBX_PROFILE>
#   3. Open `claude` once in TARGET_REPO and accept the workspace trust prompt
#      (/goal runs on the hooks system).
#   4. Check ~/.claude/settings.json for autofix hooks that could fight the gates.
#   Requires: Claude Code >= 2.1.259, uv, git, perl, databricks CLI.
set -euo pipefail

# ---------------- CONFIG ----------------
LEGACY_REPO="/Users/ericguei/Documents/caos-v2"              # legacy CAOS v2 repo (read, never written)
LEGACY_ENV_FILE="CHANGE_ME"          # file holding the legacy OpenRouter key (blockers.md B4: none found on disk)
LEGACY_KEY_VAR="OPENROUTER_API_KEY"  # variable name inside that file
DEPLOY_V_REL="vendor/deploy-v"       # Deploy V bundle path, relative to the legacy repo root
LEGACY_SKILL_DIRS=("/Users/ericguei/Documents/Co-Pilot Agents/DEPLOY_B_COWORK_SKILLS")  # skill dirs OUTSIDE the legacy repo
TARGET_REPO="/Users/ericguei/Documents/caos-databricks"
BUILD_BRANCH="rebuild/databricks"
DBX_HOST="CHANGE_ME"                 # blockers.md B2
DBX_PROFILE="CHANGE_ME"              # blockers.md B2
UC_SCHEMA="CHANGE_ME"                # catalog.schema (blockers.md B2)
LAKEBASE_INSTANCE="CHANGE_ME"        # blockers.md B2
GATEWAY_ENDPOINTS="CHANGE_ME"        # comma-separated; the spec defaults to databricks-claude-opus-5
DEPLOY_ACCESS="no"                   # yes | no  (no until the databricks CLI and profile exist, B1)
MODEL="claude-fable-5-1"
MAX_RESUMES=3
SKIP_STAGE1="${SKIP_STAGE1:-1}"      # 1: reuse the committed goal file; 0: re-run the spec author
# ----------------------------------------

die() { printf 'launch: %s\n' "$*" >&2; exit 1; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
META="$HERE/META_PROMPT.md"
TODAY="$(date +%F)"

# ---- preflight ----
grep -Eq '^[A-Z_]+="CHANGE_ME"' "${BASH_SOURCE[0]}" && die "fill in every CHANGE_ME in CONFIG"
[ -f "$META" ] || die "META_PROMPT.md not found next to this script"
for bin in claude git uv perl databricks; do
  command -v "$bin" >/dev/null || die "missing $bin"
done
ver="$(claude --version | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
[ "$(printf '%s\n' 2.1.259 "$ver" | sort -V | head -1)" = "2.1.259" ] \
  || die "Claude Code $ver is older than 2.1.259"
if [ "$DEPLOY_ACCESS" = "yes" ]; then
  databricks current-user me --profile "$DBX_PROFILE" >/dev/null 2>&1 \
    || die "Databricks profile '$DBX_PROFILE' is not authenticated"
fi

# ---- test-only OpenRouter key: loaded into the environment, never written ----
[ -f "$LEGACY_ENV_FILE" ] || die "legacy env file not found"
key="$(grep -E "^(export )?${LEGACY_KEY_VAR}=" "$LEGACY_ENV_FILE" | tail -1 \
        | cut -d= -f2- | sed -e "s/^[\"']//" -e "s/[\"']\$//")"
[ -n "$key" ] || die "$LEGACY_KEY_VAR not found in legacy env file"
export OPENROUTER_API_KEY="$key"
unset key

# ---- read-only legacy snapshot (committed HEAD only, so no .env or local junk) ----
LEGACY_RO="$(mktemp -d "${TMPDIR:-/tmp}/caos-legacy-ro.XXXXXX")"
trap 'chmod -R u+w "$LEGACY_RO" 2>/dev/null; rm -rf "$LEGACY_RO"' EXIT
git clone --quiet "$LEGACY_REPO" "$LEGACY_RO/repo"
mkdir -p "$LEGACY_RO/skills"
i=0
for d in "${LEGACY_SKILL_DIRS[@]+"${LEGACY_SKILL_DIRS[@]}"}"; do
  [ -d "$d" ] || die "skills dir not found: $d"
  i=$((i + 1))
  cp -R "$d" "$LEGACY_RO/skills/$i-$(basename "$d")"
done
chmod -R a-w "$LEGACY_RO"

# ---- target repo, branch, permissions ----
mkdir -p "$TARGET_REPO"
cd "$TARGET_REPO"
[ -d .git ] || git init --quiet
git switch -q "$BUILD_BRANCH" 2>/dev/null || git switch -q -c "$BUILD_BRANCH"
RUN_DIR="docs/rebuild/runs/$TODAY"
mkdir -p .claude "$RUN_DIR"
grep -qxF 'docs/rebuild/runs/' .gitignore 2>/dev/null || echo 'docs/rebuild/runs/' >> .gitignore

# Allow rules for the commands the build needs, so auto mode's classifier isn't
# consulted for them (headless auto mode exits after repeated denials).
if [ ! -f .claude/settings.json ]; then
  cat > .claude/settings.json <<'JSON'
{
  "permissions": {
    "allow": [
      "Bash(uv *)",
      "Bash(git status *)", "Bash(git diff *)", "Bash(git log *)", "Bash(git show *)",
      "Bash(git add *)", "Bash(git commit *)", "Bash(git switch *)", "Bash(git clone *)",
      "Bash(databricks bundle validate *)", "Bash(databricks bundle deploy *)",
      "Bash(databricks bundle run *)", "Bash(databricks bundle summary *)",
      "Bash(databricks apps get *)", "Bash(databricks apps deploy *)",
      "Bash(databricks aitools list *)", "Bash(databricks current-user *)",
      "Bash(grep *)", "Bash(wc *)", "Bash(ls *)", "Bash(find *)"
    ],
    "deny": [
      "Bash(git push *)",
      "Bash(databricks bundle destroy *)",
      "Bash(databricks apps delete *)"
    ]
  }
}
JSON
else
  echo "launch: .claude/settings.json exists; left unchanged (check it covers the build commands)"
fi

# ---- fill META_PROMPT placeholders ----
export LEGACY_RO TARGET_REPO BUILD_BRANCH DBX_HOST DBX_PROFILE UC_SCHEMA \
       LAKEBASE_INSTANCE GATEWAY_ENDPOINTS DEPLOY_ACCESS TODAY
export DEPLOY_V_PATH="$LEGACY_RO/repo/$DEPLOY_V_REL"
# The build session reads these names (spec section 3 / blockers B2).
export DATABRICKS_CONFIG_PROFILE="$DBX_PROFILE" CAOS_UC_SCHEMA="$UC_SCHEMA" \
       CAOS_LAKEBASE_INSTANCE="$LAKEBASE_INSTANCE" CAOS_MODEL_ENDPOINT="${GATEWAY_ENDPOINTS%%,*}"
prompt="$(perl -pe 's/\{\{(\w+)\}\}/exists $ENV{$1} ? $ENV{$1} : "{{$1}}"/ge' "$META")"
if grep -Eq '\{\{[A-Z_]+\}\}' <<<"$prompt"; then
  die "unfilled placeholder in META_PROMPT.md"
fi

# Don't drop long-running background subagents in -p mode (default: 10 min idle cap).
export CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0

# No --bare: it skips hooks, skills, and CLAUDE.md, and /goal is a hook.
FLAGS=(--model "$MODEL" --permission-mode auto --permission-prompts none
       --add-dir "$LEGACY_RO" --output-format stream-json --verbose)

# ---- stage 1: spec author (one retry) ----
GOAL_FILE="docs/rebuild/${TODAY}-goal.txt"
if [ "$SKIP_STAGE1" = "1" ]; then
  # Reuse the newest committed goal file; the spec author already ran.
  GOAL_FILE="$(ls docs/rebuild/*-goal.txt 2>/dev/null | sort | tail -1)"
  [ -n "$GOAL_FILE" ] || die "SKIP_STAGE1=1 but no docs/rebuild/*-goal.txt exists"
  echo "launch: stage 1 skipped; using $GOAL_FILE"
else
  echo "launch: stage 1 (spec author) -> $RUN_DIR/stage1.jsonl"
  if ! claude -p "$prompt" "${FLAGS[@]}" > "$RUN_DIR/stage1.jsonl"; then
    echo "launch: stage 1 exited early; resuming once"
    claude -p "Continue the spec-author task from where you stopped." --continue "${FLAGS[@]}" \
      > "$RUN_DIR/stage1-resume.jsonl" || die "stage 1 failed; see $RUN_DIR"
  fi
fi

[ -f "$GOAL_FILE" ] || die "stage 1 did not write $GOAL_FILE"
chars="$(wc -m < "$GOAL_FILE" | tr -d ' ')"
[ "$chars" -le 4000 ] || die "goal condition is $chars chars; limit is 4000"

# ---- stage 2: build under /goal (resume loop keeps the goal active) ----
echo "launch: stage 2 (build, /goal) -> $RUN_DIR/stage2-*.jsonl"
attempt=0
if claude -p "/goal $(cat "$GOAL_FILE")" "${FLAGS[@]}" > "$RUN_DIR/stage2-0.jsonl"; then ok=1; else ok=0; fi
while [ "$ok" -eq 0 ] && [ "$attempt" -lt "$MAX_RESUMES" ]; do
  attempt=$((attempt + 1))
  echo "launch: stage 2 exited early; resuming ($attempt/$MAX_RESUMES)"
  if claude -p "Resume the active goal from where you stopped." --continue "${FLAGS[@]}" \
       > "$RUN_DIR/stage2-$attempt.jsonl"; then ok=1; else ok=0; fi
done

echo "launch: finished (clean exit: $ok). Review, in order:"
echo "  docs/rebuild/blockers.md   docs/rebuild/decisions.md   docs/rebuild/next.md"
echo "  logs: $TARGET_REPO/$RUN_DIR/"
[ "$ok" -eq 1 ] || exit 1
