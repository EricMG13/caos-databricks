#!/usr/bin/env bash
# gitleaks over the working tree as git would commit it: tracked files plus
# untracked files that are not ignored (F466).
#
# `gitleaks dir` walks the disk and knows nothing of .gitignore, so it also
# scanned git-ignored local state (other worktrees, retained audit runs, the
# live-editing session logs) that can never reach a commit. .gitignore already
# answers "is this ours" (scripts/tracked.py); this copies exactly that set
# into a scratch directory and scans it from `.`, where .gitleaks.toml is read
# and its `^`-anchored path allowlist matches repo-relative paths. A tracked
# file that is deleted on disk has nothing to scan and is skipped.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT

git ls-files -z --cached --others --exclude-standard |
  while IFS= read -r -d '' path; do
    if [ -e "$path" ]; then printf '%s\0' "$path"; fi
  done |
  tar --null -T - -cf - |
  tar -xf - -C "$scratch"

cd "$scratch"
gitleaks dir --no-banner --redact -v .
