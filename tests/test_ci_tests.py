"""Exhaustive CI partitions and fail-closed coverage inputs."""

from __future__ import annotations

from pathlib import Path

import ci_tests
import pytest
from test_check_gate_config import _git


def test_shard_files_partition_every_pytest_file_once(tmp_path: Path) -> None:
    names = [f"tests/test_case_{i}.py" for i in range(80)]
    names += ["tests/nested/example_test.py", "tests/a space/test_file.py"]
    for name in [*names, "tests/fixture.py", "test_outside.py"]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    parts = [ci_tests.shard_files(i, tmp_path) for i in range(4)]
    actual = [name for part in parts for name in part]
    assert set(actual) == set(names)
    assert len(actual) == len(set(actual))
    for i, part in enumerate(parts):
        assert part == sorted(part) == ci_tests.shard_files(i, tmp_path)
    with pytest.raises(ValueError, match="shard index"):
        ci_tests.shard_files(4, tmp_path)


def test_shard_files_rejects_an_empty_partition(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    with pytest.raises(ValueError, match="empty test shard"):
        ci_tests.shard_files(0, tmp_path)


def test_coverage_files_requires_all_four_distinct_data_files(tmp_path: Path) -> None:
    for i in range(4):
        path = tmp_path / f"coverage-{i}" / f".coverage.shard-{i}"
        path.parent.mkdir()
        path.write_bytes(b"data")
    files = ci_tests.coverage_files(tmp_path)
    assert len(files) == 4
    assert all(Path(name).is_absolute() for name in files)
    last = Path(files[-1])
    last.unlink()
    with pytest.raises(ValueError, match="exactly one"):
        ci_tests.coverage_files(tmp_path)
    last.write_bytes(b"data")
    extra = tmp_path / ".coverage.shard-0"
    extra.write_bytes(b"duplicate")
    with pytest.raises(ValueError, match="exactly one"):
        ci_tests.coverage_files(tmp_path)


def test_main_emits_null_delimited_paths_and_refuses_bad_inputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for i in range(4):
        (tmp_path / f".coverage.shard-{i}").write_bytes(b"data")
    assert ci_tests.main(["coverage", str(tmp_path)]) == 0
    output = capsys.readouterr()
    assert output.out.endswith("\0")
    assert output.out.count("\0") == 4
    (tmp_path / ".coverage.shard-2").unlink()
    assert ci_tests.main(["coverage", str(tmp_path)]) == 1
    assert "exactly one" in capsys.readouterr().err
    assert ci_tests.main(["shard", "0"]) == 0
    assert "tests/" in capsys.readouterr().out
