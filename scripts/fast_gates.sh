#!/usr/bin/env bash
# Local CI lint/type/configuration commands plus repository guard tests.
# Full coverage, security, browser and bundle jobs remain CI gates.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
base="${1:-HEAD^}"
if [ "$#" -gt 0 ]; then shift; fi
uv lock --check
uv sync --locked --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy caos scripts tests
for gate in check_vocabulary check_tested check_gate_config check_icm document_register; do
  uv run python "scripts/$gate.py"
done
uv run python scripts/io_budget.py --assert
uv run python scripts/check_gate_config.py --against "$base"
uv run python scripts/check_pr_size.py "$base"
uv run complexipy caos scripts icm --max-complexity-allowed 15
# Match the existing repository guard set, including the suppression budget.
guards=()
for file in tests/test*.py; do
  case "$file" in
    *budget*|*gate*|*baseline*|*vocab*|*register*|*wire_contract*|*api_routes*|*tested*|*icm*|*io_*|*schema*|*store*)
      guards+=("$file") ;;
  esac
done
export CAOS_REQUIRE_POSTGRES=1
uv run pytest --no-cov -n "${CAOS_TEST_WORKERS:-0}" "${guards[@]}" "$@"
