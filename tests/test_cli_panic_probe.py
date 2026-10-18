"""The DF-13 panic probe (N234): it deploys twice over the state the first
deploy left, to a new loopback stub each time, with a rotated price, and tells
a CLI that panics from one that does not. The CLI here is a script on PATH that
records what it was given; the stand-in workspace is the real one."""

from __future__ import annotations

import json
from pathlib import Path

import cli_panic_probe
import pytest
from cli_panic_probe import PRICES, Deploy, main, panicked, probe
from workspace_stub import BEARER, LOOPBACK

STATE = ".databricks/bundle/dev/sync-snapshots/files.json"
OWN_HOST = "https://adb-1.azuredatabricks.net"


def _cli(directory: Path, calls: Path, *, panics_over_state: bool) -> Path:
    """A `databricks` that records its call and leaves state naming its stub,
    as the real CLI does; over state a deploy left it panics when asked to."""
    directory.mkdir()
    script = (
        "#!/usr/bin/env bash\n"
        "set -e\n"
        'printf "%s|%s|%s|%s|%s|%s\\n" "$DATABRICKS_HOST" "$DATABRICKS_TOKEN" '
        '"$BUNDLE_VAR_model_price" "${DATABRICKS_CONFIG_PROFILE-unset}" '
        '"$(wc -c < "$DATABRICKS_CONFIG_FILE" | tr -d " ")" '
        f'"$([ -e {STATE} ] && echo state || echo none)" >> "{calls}"\n'
    )
    if panics_over_state:
        script += (
            f"if [ -e {STATE} ]; then echo 'panic: OverrideChangeDesc' >&2;"
            " exit 2; fi\n"
        )
    script += (
        f"mkdir -p {Path(STATE).parent}\n"
        f'printf \'{{"host": "%s"}}\' "$DATABRICKS_HOST" > {STATE}\n'
        "echo Deployment complete\n"
    )
    (directory / "databricks").write_text(script, encoding="utf-8")
    (directory / "databricks").chmod(0o755)
    return directory


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    here = tmp_path / "repo"
    here.mkdir()
    (here / "databricks.yml").write_text("bundle:\n  name: probe\n", encoding="utf-8")
    monkeypatch.chdir(here)
    monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "real")
    monkeypatch.setenv("DATABRICKS_TOKEN", "a-real-token")
    return here


def test_a_panic_is_told_from_a_deploy_without_one() -> None:
    assert panicked("panic: runtime error: OverrideChangeDesc")
    assert panicked("goroutine 1\nPANIC in plan")
    assert panicked("x OverrideChangeDesc y")
    assert not panicked("Deployment complete")
    assert not panicked("")


def test_a_cli_that_panics_over_the_first_deploy_s_state_is_reported(
    root: Path, tmp_path: Path
) -> None:
    calls = tmp_path / "calls"
    cli = _cli(tmp_path / "bin", calls, panics_over_state=True)
    result = probe(root, "dev", cli)
    assert isinstance(result, list)
    assert [d.panicked for d in result] == [False, True]
    assert result[1] == Deploy(2, True, "panic: OverrideChangeDesc")
    first, second = (line.split("|") for line in calls.read_text().splitlines())
    # Each deploy: a new stub on loopback, the stub's token and no inherited
    # profile or token, an empty private config, and its own price; the second
    # over the state the first left (nothing cleared between).
    assert first[0] != second[0]
    assert first[0].startswith(LOOPBACK) and second[0].startswith(LOOPBACK)
    assert [first[1], second[1]] == [BEARER, BEARER]
    assert (first[2], second[2]) == PRICES
    assert [first[3], second[3]] == ["unset", "unset"]
    assert [first[4], second[4]] == ["0", "0"]
    assert (first[5], second[5]) == ("none", "state")
    assert not (root / STATE).exists(), "the stand-in's state is cleared after"


def test_a_cli_that_does_not_panic_passes_the_probe(root: Path, tmp_path: Path) -> None:
    cli = _cli(tmp_path / "bin", tmp_path / "calls", panics_over_state=False)
    result = probe(root, "dev", cli)
    assert isinstance(result, list)
    assert [d.panicked for d in result] == [False, False]


def test_main_exits_one_on_a_panic_and_zero_without(
    root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli_panic_probe, "REPO", root)
    bad = _cli(tmp_path / "bad", tmp_path / "calls", panics_over_state=True)
    assert main(["--cli-dir", str(bad)]) == 1
    assert "deploy 2: exit 2, panic" in capsys.readouterr().out
    good = _cli(tmp_path / "good", tmp_path / "calls", panics_over_state=False)
    assert main(["--cli-dir", str(good)]) == 0
    assert "deploy 2: exit 0, no panic" in capsys.readouterr().out


def test_a_real_workspace_s_state_is_not_touched_and_nothing_runs(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshots = root / ".databricks/bundle/prod/sync-snapshots"
    snapshots.mkdir(parents=True)
    kept = snapshots / "files.json"
    kept.write_text(json.dumps({"host": OWN_HOST}))
    calls = tmp_path / "calls"
    cli = _cli(tmp_path / "bin", calls, panics_over_state=False)
    result = probe(root, "dev", cli)
    assert isinstance(result, str) and "real workspace's state" in result
    assert kept.is_file() and not calls.exists()
    monkeypatch.setattr(cli_panic_probe, "REPO", root)
    assert main(["--cli-dir", str(cli)]) == 2


def test_a_bundle_naming_its_own_workspace_is_refused(
    root: Path, tmp_path: Path
) -> None:
    (root / "databricks.yml").write_text(
        f"bundle:\n  name: probe\nworkspace:\n  host: {OWN_HOST}\n", encoding="utf-8"
    )
    calls = tmp_path / "calls"
    cli = _cli(tmp_path / "bin", calls, panics_over_state=False)
    result = probe(root, "dev", cli)
    assert isinstance(result, str) and result.startswith("stub:")
    assert not calls.exists()


def test_no_cli_on_path_runs_nothing(
    root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert probe(root, "dev") == "probe: no databricks CLI on PATH"


def test_a_deploy_that_fails_without_a_panic_is_not_a_pass(
    root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The probe says nothing of a panic from a deploy that never got far
    enough to meet the state (a missing `frontend/dist`, say)."""
    cli = tmp_path / "bin"
    cli.mkdir()
    (cli / "databricks").write_text("#!/bin/sh\necho 'Error: no dist' >&2\nexit 1\n")
    (cli / "databricks").chmod(0o755)
    monkeypatch.setattr(cli_panic_probe, "REPO", root)
    assert main(["--cli-dir", str(cli)]) == 1
    out = capsys.readouterr().out
    assert "deploy 1: exit 1, no panic" in out and "Error: no dist" in out
