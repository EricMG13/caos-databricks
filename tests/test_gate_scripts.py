"""The two gates that guard against a control passing vacuously.

`scan_floors` refuses a scanner report that covered nothing; `io_budget` refuses
a server that declares no I/O budget. Excessive I/O is the largest single
multiple in the measurements behind docs/AI_CODE_QUALITY.md (~8x), and the
predecessor's `read_evidence` had exactly that defect.
"""

from __future__ import annotations

import json
import os
import re
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import check_tested
import io_budget
import pytest
import scan_floors
import tracked

REPO = Path(__file__).resolve().parents[1]


def _run_as_main(script: str, args: list[str], monkeypatch: pytest.MonkeyPatch) -> int:
    """Executes `script` with `__name__ == "__main__"`, in-process so coverage can
    see it. The `_run()` subprocess helper above cannot: coverage.py does not
    trace a subprocess, which is exactly why this line is otherwise dead in every
    report this suite writes."""
    monkeypatch.setattr(sys, "argv", [script, *args])
    with pytest.raises(SystemExit) as caught:
        runpy.run_path(str(REPO / "scripts" / script), run_name="__main__")
    assert isinstance(caught.value.code, int)
    return caught.value.code


def _run(script: str, *args: str, cwd: Path = REPO) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / script), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _report(tmp_path: Path, *, files: list[str], errors: list[str]) -> str:
    metrics: dict[str, dict[str, int]] = {name: {"loc": 1} for name in files}
    metrics["_totals"] = {"loc": len(files)}
    path = tmp_path / "bandit.json"
    path.write_text(
        json.dumps({"errors": errors, "metrics": metrics}), encoding="utf-8"
    )
    return str(path)


def test_scan_floor_refuses_a_report_that_covered_no_files(tmp_path: Path) -> None:
    report = _report(tmp_path, files=[], errors=[])
    result = _run("scan_floors.py", report, "--min-files", "1", cwd=tmp_path)
    assert result.returncode != 0
    assert "0 files" in result.stdout + result.stderr


def test_scan_floor_refuses_a_report_with_parse_errors(tmp_path: Path) -> None:
    report = _report(tmp_path, files=["caos/api.py"], errors=["syntax error"])
    result = _run(
        "scan_floors.py", report, "--min-files", "1", "--no-parse-errors", cwd=tmp_path
    )
    assert result.returncode != 0
    assert "parse error" in result.stdout + result.stderr


def test_scan_floor_accepts_a_report_that_covered_a_file(tmp_path: Path) -> None:
    report = _report(tmp_path, files=["caos/api.py"], errors=[])
    result = _run(
        "scan_floors.py", report, "--min-files", "1", "--no-parse-errors", cwd=tmp_path
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_scan_floor_refuses_a_cobertura_report_that_covered_no_files(
    tmp_path: Path,
) -> None:
    report = tmp_path / "coverage.xml"
    report.write_text("<coverage></coverage>", encoding="utf-8")
    result = _run("scan_floors.py", str(report), "--cobertura", cwd=tmp_path)
    assert result.returncode != 0
    assert "0 files" in result.stdout + result.stderr


def test_scan_floor_accepts_a_cobertura_report_that_covered_a_file(
    tmp_path: Path,
) -> None:
    report = tmp_path / "coverage.xml"
    report.write_text(
        "<coverage><packages><package><classes>"
        '<class filename="caos/api.py"></class>'
        "</classes></package></packages></coverage>",
        encoding="utf-8",
    )
    result = _run("scan_floors.py", str(report), "--cobertura", cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_scan_floor_refuses_a_report_outside_the_invocation_directory(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    report = _report(outside, files=["caos/api.py"], errors=[])
    inside = tmp_path / "inside"
    inside.mkdir()
    result = _run("scan_floors.py", report, "--min-files", "1", cwd=inside)
    assert result.returncode != 0
    assert "is outside" in result.stdout + result.stderr


def test_report_within_accepts_a_path_under_base(tmp_path: Path) -> None:
    report = tmp_path / "coverage.xml"
    report.write_text("x", encoding="utf-8")
    assert scan_floors.report_within(report, tmp_path) == report.resolve()


def test_report_within_refuses_a_path_outside_base(tmp_path: Path) -> None:
    outside = tmp_path / "outside" / "coverage.xml"
    outside.parent.mkdir()
    outside.write_text("x", encoding="utf-8")
    base = tmp_path / "inside"
    base.mkdir()
    with pytest.raises(ValueError, match="is outside"):
        scan_floors.report_within(outside, base)


def test_cobertura_metrics_reads_every_filename_attribute() -> None:
    report = (
        "<coverage><packages><package><classes>"
        '<class filename="a.py"></class><class filename="b.py"></class>'
        "</classes></package></packages></coverage>"
    )
    assert scan_floors.covered_files(scan_floors.cobertura_metrics(report)) == [
        "a.py",
        "b.py",
    ]


def test_io_budget_refuses_a_tree_with_no_route_directory(tmp_path: Path) -> None:
    """FP-19: `caos/api` missing exited 0 with "nothing to budget".

    The route directory is the floor this gate rests on, so a tree without one
    is a gate measuring nothing -- and every route moving out from under it was
    the one way past the check that needed no new declaration.
    """
    result = _run("io_budget.py", "--assert", "--root", str(tmp_path))
    assert result.returncode == 2, result.stdout + result.stderr
    assert "no route floor" in result.stdout + result.stderr


def test_io_budget_refuses_a_route_module_that_declares_no_budget(
    tmp_path: Path,
) -> None:
    api = tmp_path / "caos" / "api"
    api.mkdir(parents=True)
    (api / "routes.py").write_text("def list_cases() -> None: ...\n", encoding="utf-8")
    result = _run("io_budget.py", "--assert", "--root", str(tmp_path))
    assert result.returncode != 0
    assert "IO_BUDGET" in result.stdout + result.stderr


def test_io_budget_refuses_a_server_whose_routes_have_moved(tmp_path: Path) -> None:
    """A store beside no `caos/api` is not a tree with nothing to budget."""
    store = tmp_path / "caos" / "store"
    store.mkdir(parents=True)
    (store / "runs.py").write_text("def start_run() -> None: ...\n", encoding="utf-8")
    assert _run("io_budget.py", "--assert", "--root", str(tmp_path)).returncode == 2


def test_covered_files_excludes_the_totals_row() -> None:
    report: dict[str, object] = {"metrics": {"caos/api.py": {}, "_totals": {}}}
    assert scan_floors.covered_files(report) == ["caos/api.py"]


def test_covered_files_treats_a_missing_metrics_block_as_uncovered() -> None:
    assert scan_floors.covered_files({"errors": []}) == []


def test_main_accepts_a_report_covering_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # In-process, unlike the _run() tests above: coverage.py cannot trace a
    # subprocess, and main()'s own body -- argument parsing, the
    # report_within refusal path -- was otherwise measured nowhere.
    report = tmp_path / "bandit.json"
    report.write_text(
        json.dumps({"errors": [], "metrics": {"caos/api.py": {}}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    assert scan_floors.main([str(report), "--min-files", "1"]) == 0


def test_main_refuses_a_report_outside_the_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    report = outside / "bandit.json"
    report.write_text('{"metrics": {}}', encoding="utf-8")
    inside = tmp_path / "inside"
    inside.mkdir()
    monkeypatch.chdir(inside)
    with pytest.raises(SystemExit):
        scan_floors.main([str(report)])
    assert "is outside" in capsys.readouterr().err


def test_floor_failures_reports_each_floor_separately() -> None:
    report: dict[str, object] = {"metrics": {"_totals": {}}, "errors": ["boom"]}
    failures = scan_floors.floor_failures(report, min_files=1, no_parse_errors=True)
    assert len(failures) == 2


def test_scan_floor_refuses_a_file_under_cover_that_the_report_skipped() -> None:
    """The floor `--min-files 1` could not express. One scannable file satisfied
    it while bandit silently skipped the rest -- the failure mode of
    docs/AI_CODE_QUALITY.md section 4, with a green tick on it."""
    report: dict[str, object] = {"metrics": {"caos/blobs.py": {}, "_totals": {}}}
    claims = scan_floors.Claims(
        cover=("caos",),
        unscanned=("tests",),
        tracked=("caos/blobs.py", "caos/refusals.py"),
    )

    failures = scan_floors.floor_failures(report, claims=claims)

    assert len(failures) == 1
    assert "caos/refusals.py" in failures[0]


def test_scan_floor_refuses_a_tracked_file_no_list_claims() -> None:
    """Every tracked .py is either scanned or deliberately not. A third category
    is a file nobody decided about, which is how a new directory joins the tree
    and is scanned by nothing."""
    report: dict[str, object] = {"metrics": {"caos/blobs.py": {}, "_totals": {}}}
    claims = scan_floors.Claims(
        cover=("caos",),
        unscanned=("tests",),
        tracked=("caos/blobs.py", "engine/route.py"),
    )

    failures = scan_floors.floor_failures(report, claims=claims)

    assert len(failures) == 1
    assert "engine/route.py" in failures[0]


def test_scan_floor_accepts_a_report_that_covered_everything_it_claimed() -> None:
    report: dict[str, object] = {"metrics": {"caos/blobs.py": {}, "_totals": {}}}
    claims = scan_floors.Claims(
        cover=("caos",),
        unscanned=("tests",),
        tracked=("caos/blobs.py", "tests/test_blob_store.py"),
    )

    assert scan_floors.floor_failures(report, claims=claims) == []


def test_declares_budget_accepts_an_annotated_declaration() -> None:
    assert io_budget.declares_budget("IO_BUDGET: int = 3\n", "m.py")
    assert io_budget.declares_budget("IO_BUDGET = 3\n", "m.py")
    assert not io_budget.declares_budget("io_budget = 3\n", "m.py")


def test_a_declaration_that_declares_nothing_is_not_a_budget() -> None:
    """FP-19: the checker looked for the name being a target and nothing else,
    so three spellings satisfied it while stating no number of round trips."""
    for source in (
        "IO_BUDGET: int\n",
        "IO_BUDGET = None\n",
        'IO_BUDGET = float("inf")\n',
        "IO_BUDGET = -1\n",
        'IO_BUDGET = "many"\n',
        "IO_BUDGET = {}\n",
        "IO_BUDGET = 1\nIO_BUDGET = None\n",
    ):
        assert not io_budget.declares_budget(source, "m.py"), source
    # The module's own arithmetic over its own counts is left to it.
    for source in (
        "IO_BUDGET = 0\n",
        "IO_BUDGET = FIXED + NODES * PER\n",
        "IO_BUDGET = max(A, B)\n",
        'IO_BUDGET = {"report": 45, "committee": 59}\n',
    ):
        assert io_budget.declares_budget(source, "m.py"), source


def test_is_budget_reads_the_value_the_source_states() -> None:
    import ast

    def value(source: str) -> ast.expr:
        node = ast.parse(source).body[0]
        assert isinstance(node, ast.Assign) and node.value is not None
        return node.value

    assert io_budget.is_budget(value("x = 0"))
    assert not io_budget.is_budget(value("x = 1.5"))
    assert not io_budget.is_budget(value('x = float("inf")'))
    assert not io_budget.is_budget(value("x = True"))


def test_public_definitions_skips_private_names_and_entry_points() -> None:
    source = "def _helper(): ...\ndef main(): ...\nclass Ledger: ...\n"
    assert check_tested.public_definitions(source, "m.py") == [(3, "Ledger")]


def test_tracked_python_returns_what_git_tracks() -> None:
    found = tracked.tracked_python(REPO)
    assert REPO / "scripts" / "tracked.py" in found
    assert all(p.suffix == ".py" for p in found)


def test_untested_does_not_accept_a_name_buried_in_a_longer_word(
    tmp_path: Path,
) -> None:
    module = tmp_path / "m.py"
    module.write_text("def run() -> None: ...\n", encoding="utf-8")
    assert check_tested.untested(module, frozenset({"runner", "runs"}))


def test_a_name_that_appears_only_in_a_comment_references_nothing(
    tmp_path: Path,
) -> None:
    """The defect this gate shipped on 17 September 2026. A money-path guard
    passed with no test driving it because its name appeared in a comment, so
    a sentence *about* the code satisfied the check *for* the code."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_m.py").write_text(
        "# _within_reservation re-prices the request\n"
        '"""and this docstring names within_reservation too."""\n'
        'assert "a sentence naming within_reservation" == ""\n',
        encoding="utf-8",
    )

    assert "within_reservation" not in check_tested.referenced_names(tests_dir)


def test_a_dotted_path_in_a_string_is_a_reference_and_prose_is_not(
    tmp_path: Path,
) -> None:
    """`monkeypatch.setattr("caos.store.runs.append", ...)` is a real
    reference and Python gives it no other spelling, so a dotted identifier
    path is admitted. An English sentence is not a dotted path."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_m.py").write_text(
        'setattr("caos.store.runs.append", None)\n'
        'note = "we should really test the reconciler here"\n',
        encoding="utf-8",
    )

    referenced = check_tested.referenced_names(tests_dir)

    assert "caos.store.runs.append" in referenced
    assert not any(name.endswith("reconciler") for name in referenced)


def test_referenced_names_resolves_imports_and_the_chains_from_them(
    tmp_path: Path,
) -> None:
    """DQ-11: a reference is `module.name`, read through the test's imports. A
    bare name nothing imported, or an attribute of one, names no module."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_m.py").write_text(
        "from caos.store import reserve\nimport server.evidence.pdf as pdf\n"
        "import caos.graph.runtime\n"
        "widget.anchor_citation()\nfreeze\npdf.extract(reserve)\n"
        "caos.graph.runtime.finish()\nsetattr(pdf, 'walk_pages', None)\n",
        encoding="utf-8",
    )

    referenced = check_tested.referenced_names(tests_dir)

    assert {
        "caos.store.reserve",
        "server.evidence.pdf",
        "server.evidence.pdf.extract",
        "caos.graph.runtime.finish",
        "server.evidence.pdf.walk_pages",
    } <= referenced
    assert not any(
        name.rpartition(".")[2] in {"anchor_citation", "freeze"} for name in referenced
    )


def test_a_route_handler_is_covered_by_its_path_not_its_name() -> None:
    """A route is reached by an HTTP request, the way a React component is
    reached by rendering -- `frontend/scripts/check-tested.mjs` states the same
    rule. Demanding a test name it buys an import and no coverage."""
    source = (
        "router = APIRouter()\n"
        "@router.get('/api/v1/book')\ndef read_book(): ...\n"
        "@lru_cache\ndef cached_thing(): ...\n"
    )

    assert check_tested.public_definitions(source, "m.py") == [(5, "cached_thing")]


def test_a_suite_that_references_nothing_refuses_rather_than_clearing_everything(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty reference set would pass every definition in the tree. A reader
    that read nothing is a failure, which is this repository's standing rule
    for a scanner and is why the floor exists at all."""
    module = tmp_path / "m.py"
    module.write_text("def foo() -> None: ...\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_empty.py").write_text("", encoding="utf-8")

    assert check_tested.main([str(module), "--tests", str(tests_dir)]) == 2
    assert "read nothing is a failure" in capsys.readouterr().err


def test_tracked_python_keeps_a_path_containing_a_space(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "my file.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    assert tracked.tracked_python(tmp_path) == [tmp_path / "my file.py"]


def test_io_budget_reports_without_asserting(tmp_path: Path) -> None:
    api = tmp_path / "caos" / "api"
    api.mkdir(parents=True)
    (api / "routes.py").write_text("def list_cases() -> None: ...\n", encoding="utf-8")
    assert _run("io_budget.py", "--root", str(tmp_path)).returncode == 0
    assert _run("io_budget.py", "--assert", "--root", str(tmp_path)).returncode != 0


def test_tracked_python_skips_a_file_that_is_no_longer_on_disk(
    tmp_path: Path,
) -> None:
    # A tracked file can be absent mid-rebase, mid-checkout, or after a delete
    # that is not staged yet. A gate must not stack-trace on it.
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "gone.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "here.py").write_text("y = 2\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    (tmp_path / "gone.py").unlink()

    assert tracked.tracked_python(tmp_path) == [tmp_path / "here.py"]


def test_tracked_python_refuses_when_git_is_not_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="git is not on PATH"):
        tracked.tracked_python(tmp_path)


def test_check_tested_main_refuses_when_nothing_is_scanned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setattr(check_tested, "REPO", tmp_path)

    assert check_tested.main([]) == 2
    assert "scanned no files" in capsys.readouterr().err


def test_check_tested_main_reports_untested_symbols_and_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = tmp_path / "m.py"
    module.write_text("def foo() -> None: ...\n", encoding="utf-8")
    missing_tests_dir = tmp_path / "no_such_tests_dir"

    result = check_tested.main([str(module), "--tests", str(missing_tests_dir)])

    assert result == 1
    assert "'foo' has no test referencing it" in capsys.readouterr().out


def test_check_tested_main_passes_when_every_symbol_is_named(
    tmp_path: Path,
) -> None:
    module = tmp_path / "m.py"
    module.write_text("def foo() -> None: ...\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_m.py").write_text("from m import foo\n\nfoo()\n")

    assert check_tested.main([str(module), "--tests", str(tests_dir)]) == 0


def test_io_budget_main_refuses_a_missing_route_directory_in_process(
    tmp_path: Path,
) -> None:
    assert io_budget.main(["--assert", "--root", str(tmp_path)]) == 2


def test_io_budget_main_refuses_a_route_module_that_declares_no_budget_in_process(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api = tmp_path / "caos" / "api"
    api.mkdir(parents=True)
    (api / "routes.py").write_text("def list_cases() -> None: ...\n", encoding="utf-8")

    assert io_budget.main(["--assert", "--root", str(tmp_path)]) == 1
    assert "IO_BUDGET" in capsys.readouterr().err


def test_io_budget_main_reports_without_asserting_in_process(tmp_path: Path) -> None:
    api = tmp_path / "caos" / "api"
    api.mkdir(parents=True)
    (api / "routes.py").write_text("def list_cases() -> None: ...\n", encoding="utf-8")

    assert io_budget.main(["--root", str(tmp_path)]) == 0


def test_io_budget_main_passes_when_a_module_declares_the_budget(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api = tmp_path / "caos" / "api"
    api.mkdir(parents=True)
    (api / "routes.py").write_text("IO_BUDGET = 1\n", encoding="utf-8")

    assert io_budget.main(["--assert", "--root", str(tmp_path)]) == 0
    assert "all 1 route module(s) declare IO_BUDGET" in capsys.readouterr().out


def test_main_builds_claims_from_the_cover_and_unscanned_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI's `--cover`/`--unscanned` wiring, not `floor_failures` directly:
    passing `--cover` is what makes `main` build a `Claims` from the repo's
    tracked files in the first place."""
    repo = tmp_path / "repo"
    (repo / "caos").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "caos" / "api.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)

    report = repo / "bandit.json"
    report.write_text(
        json.dumps({"errors": [], "metrics": {"caos/api.py": {}}}), encoding="utf-8"
    )
    monkeypatch.chdir(repo)

    result = scan_floors.main(
        [
            str(report),
            "--cover",
            "caos",
            "--unscanned",
            "tests",
            "--repo",
            str(repo),
        ]
    )

    assert result == 0


def test_main_prints_a_failure_line_per_floor_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "bandit.json"
    report.write_text(json.dumps({"errors": [], "metrics": {}}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert scan_floors.main([str(report), "--min-files", "1"]) == 1
    assert "0 files" in capsys.readouterr().err


def test_main_refuses_a_bare_cover_flag_with_no_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """N46: `nargs="*"` let a bare `--cover` (no directory after it) leave
    `args.cover` empty, so `if args.cover:` in `main` took the false branch
    and skipped the claim check silently -- a scan claimed to cover nothing
    passed as though nothing needed claiming."""
    report = tmp_path / "bandit.json"
    report.write_text(json.dumps({"errors": [], "metrics": {}}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as caught:
        scan_floors.main([str(report), "--cover"])

    assert caught.value.code == 2
    assert "--cover" in capsys.readouterr().err


def test_check_tested_module_guard_exits_with_mains_return_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The whole repo's own tree: `make lint` already guarantees this passes.
    assert _run_as_main("check_tested.py", [], monkeypatch) == 0


def test_io_budget_module_guard_exits_with_mains_return_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Phase 0: no `caos/api` yet, so the real repo always takes this branch.
    assert _run_as_main("io_budget.py", [], monkeypatch) == 0


def test_scan_floors_module_guard_exits_with_mains_return_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = tmp_path / "bandit.json"
    report.write_text(
        json.dumps({"errors": [], "metrics": {"caos/api.py": {}}}), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    assert (
        _run_as_main("scan_floors.py", [str(report), "--min-files", "1"], monkeypatch)
        == 0
    )


def test_tracked_python_fails_closed_on_an_unreadable_path(tmp_path: Path) -> None:
    # Path.is_file() returns False for every OSError on 3.14, not only for a
    # missing path, so a permission error would drop a tracked file from the
    # scan silently. A gate that scanned less than it should is a failed gate.
    if os.geteuid() == 0:
        pytest.skip("root ignores the directory mode this test relies on")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "hidden.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    locked.chmod(0o000)
    try:
        with pytest.raises(PermissionError):
            tracked.tracked_python(tmp_path)
    finally:
        locked.chmod(0o755)


def test_the_image_floor_refuses_a_scan_that_examined_nothing(tmp_path: Path) -> None:
    """An image report with no Results is the same failure as a bandit report
    with no metrics: it ran, exited zero, and looked at nothing."""
    report = tmp_path / "trivy.json"
    report.write_text(json.dumps({"Results": []}), encoding="utf-8")

    result = _run("scan_floors.py", str(report), "--trivy", cwd=tmp_path)

    assert result.returncode != 0
    assert "scanned nothing" in result.stdout + result.stderr


def test_the_image_floor_accepts_a_scan_with_targets(tmp_path: Path) -> None:
    report = tmp_path / "trivy.json"
    report.write_text(
        json.dumps(
            {"Results": [{"Target": "caos:ci (debian 13)", "Vulnerabilities": []}]}
        ),
        encoding="utf-8",
    )

    result = _run("scan_floors.py", str(report), "--trivy", cwd=tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


def test_main_refuses_a_trivy_scan_that_examined_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # In-process, unlike the _run() tests above: coverage.py cannot trace a
    # subprocess, and the --trivy branch of main()'s body was otherwise
    # measured nowhere.
    report = tmp_path / "trivy.json"
    report.write_text(json.dumps({"Results": []}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert scan_floors.main([str(report), "--trivy"]) == 1
    assert "scanned nothing" in capsys.readouterr().err


def test_main_accepts_a_trivy_scan_with_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "trivy.json"
    report.write_text(
        json.dumps(
            {"Results": [{"Target": "caos:ci (debian 13)", "Vulnerabilities": []}]}
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert scan_floors.main([str(report), "--trivy"]) == 0
    assert "examined 1 target" in capsys.readouterr().out


def test_scanned_targets_ignores_a_result_with_no_target() -> None:
    report: dict[str, object] = {"Results": [{"Class": "lang-pkgs"}, {"Target": "app"}]}

    assert scan_floors.scanned_targets(report) == ["app"]


def test_io_budget_refuses_a_second_route_module_that_declares_no_budget(
    tmp_path: Path,
) -> None:
    """The floor was "some module declares one", so the second route to arrive
    was never asked.

    `CLAUDE.md`'s Phase 0 ledger called this out and pointed the upgrade at
    Phase 2. Excessive I/O is the largest measured multiple in
    `docs/AI_CODE_QUALITY.md`, and the predecessor's `read_evidence` is what it
    was measured on -- so a gate that stops asking after the first answer is a
    gate the next request path walks past.
    """
    api = tmp_path / "caos" / "api"
    api.mkdir(parents=True)
    (api / "runs.py").write_text("IO_BUDGET = 4\n", encoding="utf-8")
    (api / "cases.py").write_text("def list_cases() -> None: ...\n", encoding="utf-8")

    assert io_budget.main(["--assert", "--root", str(tmp_path)]) == 1


def test_io_budget_takes_zero_as_a_declared_cost(tmp_path: Path) -> None:
    """A module in the route directory that makes no round trip declares `0`.

    The rule is every module, not every module a heuristic recognises as
    serving a path: "it has no route decorator" and "it never names the store"
    are things a module can stop being true of without anyone noticing, and a
    gate resting on either is one a new request path can be written around.
    Zero is a cost, and stating it is cheaper than proving the exemption.
    """
    api = tmp_path / "caos" / "api"
    api.mkdir(parents=True)
    (api / "identity.py").write_text("IO_BUDGET = 0\n", encoding="utf-8")

    assert io_budget.main(["--assert", "--root", str(tmp_path)]) == 0


def test_io_budget_names_the_modules_that_did_not_declare_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A refusal a reader can act on names the files, not just the count."""
    api = tmp_path / "caos" / "api"
    api.mkdir(parents=True)
    (api / "cases.py").write_text("def list_cases() -> None: ...\n", encoding="utf-8")

    assert io_budget.main(["--assert", "--root", str(tmp_path)]) == 1
    assert "cases.py" in capsys.readouterr().err


def test_the_typescript_half_exempts_what_the_python_half_exempts() -> None:
    """One rule, two halves, read from the other's source.

    The TypeScript half's *behaviour* is asserted in the frontend suite, where
    the `typescript` it imports is installed; this job never runs `npm ci`, so
    driving it from here would test whether node_modules happens to be present.
    `test_ts_gate_enforces_the_same_tokens` keeps the vocabulary pair in step
    the same way and for the same reason.

    What has to agree across the two is the exemption: a name one half lets
    through and the other refuses is one rule wearing two answers.
    """
    gate = (REPO / "frontend" / "scripts" / "check-tested.mjs").read_text(
        encoding="utf-8"
    )
    literal = re.search(r"export const EXEMPT = new Set\(\[(.*?)\]\);", gate, re.DOTALL)
    assert literal, "the TypeScript gate no longer declares EXEMPT as a literal"
    exempt = set(re.findall(r'"([a-z]+)"', literal.group(1)))

    assert set(check_tested.EXEMPT) <= exempt, (
        "the Python half exempts a name the TypeScript half would refuse"
    )


def test_the_typescript_half_is_wired_into_the_workspace_lint() -> None:
    """A gate nothing runs is not a gate.

    It rides `npm run lint`, which the CI `frontend` job runs -- the one job
    that installs what it imports.
    """
    package = (REPO / "frontend" / "package.json").read_text(encoding="utf-8")

    assert "scripts/check-tested.mjs" in json.loads(package)["scripts"]["lint"]


def test_undeclared_names_the_module_a_refusal_must_be_acted_on(
    tmp_path: Path,
) -> None:
    """`io_budget --assert` prints a refusal; `undeclared` is the list behind
    it, named so an operator learns *which* module has no budget rather than
    that some module has none."""
    api = tmp_path / "caos" / "api"
    api.mkdir(parents=True)
    (api / "budgeted.py").write_text(
        "IO_BUDGET = 3\ndef read_one() -> None: ...\n", encoding="utf-8"
    )
    (api / "bare.py").write_text("def read_two() -> None: ...\n", encoding="utf-8")

    assert io_budget.undeclared(api) == [api / "bare.py"]


def test_a_name_a_test_only_binds_does_not_clear_a_public_definition(
    tmp_path: Path,
) -> None:
    """F63: a local, a parameter or a loop variable that shares a public name
    is a binding, not a use."""
    module = tmp_path / "pkg" / "m.py"
    module.parent.mkdir()
    module.write_text("def freeze_the_deliverable() -> int:\n    return 1\n")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    bound = tests_dir / "test_bound.py"
    bound.write_text(
        "import os\n\n"
        "def test_x(freeze_the_deliverable: int = 1) -> None:\n"
        "    del freeze_the_deliverable\n"
        "    for freeze_the_deliverable in ():\n"
        "        pass\n"
    )
    assert check_tested.main([str(module), "--tests", str(tests_dir)]) == 1
    bound.write_text(
        "from pkg.m import freeze_the_deliverable\n\n"
        "def test_x() -> None:\n"
        "    assert freeze_the_deliverable() == 1\n"
    )
    assert check_tested.main([str(module), "--tests", str(tests_dir)]) == 0


@pytest.mark.parametrize(
    "source",
    [
        "import math\nIO_BUDGET = math.inf\n",
        "IO_BUDGET = ~0\n",
        "IO_BUDGET = 10 ** 100\n",
        "FIXED = 3\nIO_BUDGET = FIXED - 4\n",
        'IO_BUDGET = {"report": 45, "frozen": 2.5}\n',
        "IO_BUDGET = 1 == 1\n",
    ],
    ids=["math-inf", "invert-zero", "googol", "negative", "float-in-map", "bool"],
)
def test_io_budget_refuses_a_value_that_is_not_a_bounded_count(
    tmp_path: Path, source: str
) -> None:
    """DQ-10: FP-19 closed the spelling `float("inf")` and nothing else, so
    `math.inf`, `~0` (which is -1) and `10 ** 100` each passed as a declared
    budget. The value is read as Python evaluates it and must be a whole
    number of round trips between 0 and `CEILING`."""
    api = tmp_path / "caos" / "api"
    api.mkdir(parents=True)
    (api / "routes.py").write_text(source, encoding="utf-8")
    assert io_budget.main(["--assert", "--root", str(tmp_path)]) == 1
    assert not io_budget.within(io_budget.declared_value(api / "routes.py", tmp_path))


def test_io_budget_reads_a_package_module_too(tmp_path: Path) -> None:
    """DQ-10, FP-19's first bullet: `__init__.py` was skipped, so a route
    declared in a package's own module was never read."""
    reads = tmp_path / "caos" / "api" / "reads"
    reads.mkdir(parents=True)
    (tmp_path / "caos" / "api" / "__init__.py").write_text(
        "IO_BUDGET = 0\n", encoding="utf-8"
    )
    (reads / "__init__.py").write_text(
        "from fastapi import APIRouter\nrouter = APIRouter()\n\n"
        "@router.get('/api/v1/unbudgeted')\ndef unbudgeted() -> None: ...\n",
        encoding="utf-8",
    )
    assert io_budget.main(["--assert", "--root", str(tmp_path)]) == 1
    (reads / "__init__.py").write_text("IO_BUDGET = 2\n", encoding="utf-8")
    assert io_budget.main(["--assert", "--root", str(tmp_path)]) == 0


def test_io_budget_evaluates_the_modules_own_arithmetic(tmp_path: Path) -> None:
    """Arithmetic over the module's counts, a `max`, a length and a map are all
    budgets once evaluated; the gate does not have to parse them, and the
    repository's own modules pass the same reading."""
    api = tmp_path / "caos" / "api"
    api.mkdir(parents=True)
    source = (
        "import enum\n"
        "class Gate(enum.Enum):\n    A = 1\n    B = 2\n"
        "FIXED, PER = 2, 3\n"
        "IO_BUDGET = max(FIXED + len(Gate) * PER, 1)\n"
    )
    (api / "routes.py").write_text(source, encoding="utf-8")
    assert io_budget.declared_value(api / "routes.py", tmp_path) == 8
    assert io_budget.within(8) and io_budget.within({"a": 0, "b": io_budget.CEILING})
    assert not io_budget.within({}) and not io_budget.within(io_budget.CEILING + 1)
    assert io_budget.main(["--assert", "--root", str(tmp_path)]) == 0
    assert io_budget.main(["--assert"]) == 0


def test_check_tested_sees_the_public_code_it_used_to_miss(tmp_path: Path) -> None:
    """DQ-11 (FP-18): a module holding a public lambda, a `def` under `if`, a
    function decorated `@cache.get(...)` and a `def verify` passed the gate with
    no test calling any of them. The first three were invisible, and `verify`
    was cleared by the suite's references to another module's `verify`."""
    module = tmp_path / "untested.py"
    module.write_text(
        "normalise = lambda value: value.strip()\n"
        "if True:\n    def guarded() -> int:\n        return 1\n"
        "try:\n    def attempted() -> int:\n        return 2\n"
        "except ImportError:\n    pass\n"
        "class _Cache:\n    def get(self, key):\n        return lambda f: f\n"
        "cache = _Cache()\n"
        "@cache.get('key')\ndef cached() -> int:\n    return 2\n"
        "def verify(archive: bytes) -> bool:\n    return True\n",
        encoding="utf-8",
    )
    names = [
        name
        for _, name in check_tested.public_definitions(module.read_text(), str(module))
    ]
    assert names == ["normalise", "guarded", "attempted", "cached", "verify"]
    referenced = check_tested.referenced_names(REPO / "tests")
    assert "caos.deliverable.verify_package.verify" in referenced
    found = check_tested.untested(module, referenced)
    assert len(found) == 5 and all(line.startswith(str(module)) for line in found)


def test_a_module_is_named_as_it_is_imported() -> None:
    """A package is its directory, and `scripts/` and `tests/` are on the
    import path themselves; a file outside the tree is its stem."""
    assert check_tested.module_name(REPO / "caos/store/runs.py", REPO) == (
        "caos.store.runs"
    )
    assert check_tested.module_name(REPO / "caos/api/__init__.py", REPO) == "caos.api"
    assert check_tested.module_name(REPO / "scripts/qualify.py", REPO) == "qualify"
    assert check_tested.module_name(REPO / "tests/conftest.py", REPO) == "conftest"
    assert check_tested.module_name(Path("/elsewhere/m.py"), REPO) == "m"


def test_a_reference_follows_the_imports_of_the_module_it_names(
    tmp_path: Path,
) -> None:
    """A test importing a name from the module that re-exports it references the
    definition, not the re-export -- and only that one."""
    import ast

    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("from pkg.core import run as run\n")
    (package / "core.py").write_text(
        "def run() -> None: ...\ndef idle() -> None: ...\n"
    )
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_pkg.py").write_text("from pkg import run\n\nrun()\n")

    bound = check_tested.bindings(
        ast.parse("import a.b as c\nfrom d import e as f\n").body
    )
    assert bound == {"c": "a.b", "f": "d.e"}
    reexports = {"pkg": {"run": "pkg.core.run"}}
    assert check_tested.canonical("pkg.run", reexports) == "pkg.core.run"
    assert check_tested.canonical("pkg.core.idle", reexports) == "pkg.core.idle"
    assert check_tested.main([str(package / "core.py"), "--tests", str(tests_dir)]) == 1
    (tests_dir / "test_pkg.py").write_text(
        "from pkg import run\nfrom pkg.core import idle\n\nrun()\nidle()\n"
    )
    assert check_tested.main([str(package / "core.py"), "--tests", str(tests_dir)]) == 0
