# Building inside the enterprise (GitHub-only downloads)

The enterprise PC may download files from GitHub only. Every tool the build needs has a GitHub release. Python packages are the exception: PyPI is unreachable, so they come from this repository's own release, a wheelhouse named after `uv.lock`'s digest. CI on GitHub (Linux, with full internet) runs the gates that need anything else. The build itself is `docs/superpowers/plans/2026-10-01-copilot-sdk-adapter.md`, run by the goal in `docs/rebuild/2026-09-22-goal.txt`.

## 1. Sources

| What | GitHub repository | Asset |
|---|---|---|
| uv 0.12.5 (the version CI pins) | `astral-sh/uv`, release `0.12.5` | `uv-x86_64-pc-windows-msvc.zip` |
| Python 3.13 | `astral-sh/python-build-standalone` | fetched by `uv venv` |
| Python packages | `EricMG13/caos-databricks`, release `wheelhouse-<lock>` (§3) | `caos-wheelhouse-win_amd64-cp313.zip` |
| PostgreSQL 17 (tests only) | `theseus-rs/postgresql-binaries`, release `17.11.0` | `postgresql-17.11.0-x86_64-pc-windows-msvc.zip` and its `.sha256` |
| Copilot CLI | `github/copilot-cli`, latest release | `copilot-win32-x64.zip` |
| Copilot SDK runtime | `github/copilot-cli` | fetched by `python -m copilot download-runtime` |
| GitHub CLI (to read CI) | `cli/cli`, latest release | `gh_<version>_windows_amd64.zip` |
| gitleaks (optional) | `gitleaks/gitleaks`, latest release | `gitleaks_<version>_windows_x64.zip` |

Git itself comes from IT. Unzip each tool under `$HOME\tools` and put its folder on `PATH`.

## 2. Clone without converting line endings

```powershell
git config --global core.autocrlf false
git clone https://github.com/EricMG13/caos-databricks.git
cd caos-databricks
git switch rebuild/databricks
```

`vendor/deploy-v` and `icm` are verified byte for byte (invariant 4), and the wheelhouse is named after `uv.lock`'s bytes. A clone that converts line endings breaks both. Once D79 lands, `.gitattributes` pins the two trees.

## 3. Python and the packages (offline from here on)

```powershell
$tools = "$HOME\tools"
$lock = (Get-FileHash uv.lock -Algorithm SHA256).Hash.Substring(0, 12).ToLower()
# Download caos-wheelhouse-win_amd64-cp313.zip from the release tagged wheelhouse-$lock, then:
Expand-Archive caos-wheelhouse-win_amd64-cp313.zip -DestinationPath "$tools\wheelhouse-$lock"
uv venv --python 3.13
uv pip sync --no-index --find-links "$tools\wheelhouse-$lock\wheels" --require-hashes "$tools\wheelhouse-$lock\requirements-win.txt"
[Environment]::SetEnvironmentVariable("UV_NO_SYNC", "1", "User"); $env:UV_NO_SYNC = "1"
[Environment]::SetEnvironmentVariable("UV_OFFLINE", "1", "User"); $env:UV_OFFLINE = "1"
uv run python -c "import caos.models, copilot; print('packages ok')"
```

- `uv pip sync` checks every wheel against the hash `uv.lock` records.
- `UV_NO_SYNC` and `UV_OFFLINE` make every `uv run …` in `CLAUDE.md` and the plan use this environment without contacting PyPI.
- If no release matches `$lock`, `uv.lock` changed after the wheelhouse was built. Rebuild it outside the enterprise (§8).

## 4. PostgreSQL for the tests

This replaces `docker compose up -d --wait`, because Docker Hub is unreachable. It serves the URL `CLAUDE.md` uses.

```powershell
# Check the zip against its .sha256, then unzip it under $tools.
$pg = (Get-ChildItem $tools -Recurse -Filter initdb.exe | Select-Object -First 1).DirectoryName
$data = "$HOME\caos-test-pg"
Set-Content -NoNewline "$tools\pgpass.txt" "local-test-admin-only"
& "$pg\initdb.exe" -D $data -U postgres --pwfile "$tools\pgpass.txt" -A scram-sha-256 -E UTF8
& "$pg\pg_ctl.exe" -D $data -o "-p 55437 -c listen_addresses=127.0.0.1" -l "$data\server.log" start
$env:CAOS_TEST_POSTGRES_URL = "postgresql://postgres:local-test-admin-only@127.0.0.1:55437/postgres"
$env:CAOS_REQUIRE_POSTGRES = "1"
```

The password is the test-only one in `CLAUDE.md`. Stop the server with `& "$pg\pg_ctl.exe" -D $data stop`.

## 5. Copilot: the model under test and the agent that builds

- **Copilot CLI.** Unzip `copilot-win32-x64.zip` under `$tools`, put it on `PATH`, then run `copilot login`.
- **SDK runtime.** Run `uv run python -m copilot download-runtime` once. Then set `COPILOT_SKIP_CLI_DOWNLOAD=1` (user environment), so nothing is downloaded at run time.
- **The agent that builds** is Copilot CLI, with the global settings from the work-PC install prompt. Every turn it takes spends Copilot AI credits. A seven-task build on Claude Opus 5.5 can exceed a Business seat's 1,900 monthly credits, so set a GitHub budget first, or run the implementation on Sonnet 5.5.

## 6. Which gates run where

| On the PC | Only in CI on GitHub (needs a download from outside GitHub) |
|---|---|
| `uv run ruff check .` · `uv run ruff format --check .` · `uv run mypy caos scripts tests` | `uv lock --check` (PyPI metadata) |
| The tests each plan task names, with `--no-cov` | `uv run pip-audit --strict` (advisory database) |
| `uv run bandit -r caos scripts icm -f json -o bandit.json`, then `uv run python scripts/scan_floors.py bandit.json --no-parse-errors --cover caos scripts icm --unscanned tests` | `uv run pre-commit run --all-files` (hook environments come from PyPI and Go) |
| `uv run python scripts/check_vocabulary.py` · `check_tested.py` · `io_budget.py --assert` · `check_gate_config.py` · `check_icm.py` · `document_register.py` | The frontend gates and `jscpd` (npm) |
| `uv run complexipy caos scripts icm --max-complexity-allowed 15` | `databricks bundle …` under the stand-in, and `tests/shipped_boot.py` (Terraform, a frontend build) |
| `uv run python -B vendor/deploy-v/verify_package.py` · `gitleaks git --no-banner` (if installed) | The whole suite with coverage ≥ 80% and `scan_floors.py coverage.xml`: CI on Linux is the authority |

A test can fail on Windows only because it relies on something POSIX-only that the code under test does not claim to support. That is a portability finding: record it as the next N, with the command and its output, and leave the verdict to CI on Linux. The plan's own tests are written to pass on both.

## 7. Pushing and reading CI

The owner pushes each branch, and CI runs every gate on Linux. From the PC, `gh auth login`, then `gh run list --branch <branch>` and `gh run view <id> --log-failed`. Fix any failure on the PC and push again.

## 8. Rebuilding the wheelhouse (outside the enterprise)

The wheelhouse holds exactly the `uv.lock` it is named after. A change to `pyproject.toml` or `uv.lock` needs a new one, built on a machine that can reach PyPI and published as release `wheelhouse-<lock>`:

```bash
uv export --frozen --all-groups --no-emit-project --format requirements-txt -o requirements-all.txt
uv run python - <<'EOF'
from pathlib import Path
from packaging.requirements import Requirement
env = {"implementation_name": "cpython", "os_name": "nt", "platform_machine": "AMD64",
       "platform_python_implementation": "CPython", "platform_system": "Windows",
       "python_full_version": "3.13.7", "python_version": "3.13", "sys_platform": "win32", "extra": ""}
keep, block = [], []
for line in Path("requirements-all.txt").read_text().splitlines() + ["#"]:
    if line and not line.startswith(" "):
        if block and (not block[0].split(";")[1:] or Requirement(block[0].rstrip(" \\")).marker.evaluate(env)):
            keep += block
        block = [] if line.startswith("#") else [line]
    elif line:
        block.append(line)
Path("requirements-win.txt").write_text("\n".join(keep) + "\n")
EOF
python -m pip download --no-deps --only-binary=:all: --platform win_amd64 --python-version 3.13 --implementation cp --abi cp313 --require-hashes -r requirements-win.txt -d wheels
zip -r caos-wheelhouse-win_amd64-cp313.zip wheels requirements-win.txt
gh release create "wheelhouse-$(shasum -a 256 uv.lock | cut -c1-12)" caos-wheelhouse-win_amd64-cp313.zip --title "Wheelhouse for uv.lock $(shasum -a 256 uv.lock | cut -c1-12)" --notes "Windows x64, CPython 3.13: every package in uv.lock, all groups (docs/ENTERPRISE_BUILD.md)."
```
