"""A rollback is a redeploy only across no migration and no schema move (C1).

The runbook once said a rollback is always "check out the previous commit and
run the same one command": against the store a release had migrated, a
commit from before a migration refuses to start (`STORE_SCHEMA_DRIFT`), and
one from before DL-1 starts on an empty store in `public`. The check reads
both commits through git and names which of the two it would be.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import rollback_check

STORE_MODULE = """\
from pathlib import Path

SCHEMA = (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")
MIGRATIONS = (
    ("0001_legacy", SCHEMA),
    ("0002_extraction", Path(__file__).with_name("0002_extraction.sql").read_text()),
{extra})
{schema}
"""
ADDED = (
    '    ("0003_budget", Path(__file__).with_name("0003_budget.sql").read_text()),\n'
)
MOVED = 'STORE_SCHEMA = "caos_store"'


def _git(root: Path, *args: str) -> str:
    git = shutil.which("git")
    assert git is not None
    done = subprocess.run([git, *args], cwd=root, check=True, capture_output=True)
    return done.stdout.decode().strip()


def _commit(root: Path, files: dict[str, str], message: str) -> str:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", message)
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Rollback test")
    return root


HANDOFF = "caos/methodology/handoff.py"
# Every `WRITERS` entry the release must declare in a form the check reads.
WRITER_FILES = {
    "caos/evidence/pdf.py": 'ExtractorIdentity("caos.pdfminer", "6", {})\n',
    "caos/evidence/extract.py": 'ExtractorIdentity("caos.plain-text", "4", {})\n',
    "caos/evidence/page.py": 'PDF_CROP_VERSIONS = frozenset({"2"})\n',
    "caos/evidence/citations.py": 'NORMALISATION_VERSION = "2"\n',
    "caos/evidence/ingest.py": "PACKING_BY_WIDTH = 1\nPACKING_BY_TOKEN = 2\n",
    "caos/methodology/__init__.py": 'CANONICAL_ADAPTER_VERSION = "v3"\n',
    "caos/deliverable/verify_package.py": 'RENDERER_SHA256 = "aa"\n',
    HANDOFF: 'RECORD_FORMAT = "r"\nBLOCKED_FORMAT = "b"\nRECORD_CODEC_VERSION = 1\n',
}


def _store(extra: str = "", schema: str = MOVED) -> dict[str, str]:
    return {
        **WRITER_FILES,
        "caos/store/__init__.py": STORE_MODULE.format(extra=extra, schema=schema),
        "caos/store/schema.sql": "CREATE TABLE cases (case_id uuid);\n",
        "caos/store/0002_extraction.sql": "ALTER TABLE cases ADD COLUMN x int;\n",
    }


def test_a_redeploy_across_no_migration_is_a_rollback(repo: Path) -> None:
    older = _commit(repo, {**_store(), "caos/serve.py": "a = 1\n"}, "older")
    release = _commit(repo, {"caos/serve.py": "a = 2\n"}, "release")
    layout = rollback_check.store_layout(release, repo)
    assert layout.schema == "caos_store"
    assert [name for name, _ in layout.migrations] == ["0001_legacy", "0002_extraction"]
    assert rollback_check.rollback_problems(older, release, repo) == []


def test_a_release_that_added_a_migration_cannot_be_rolled_back_by_redeploy(
    repo: Path,
) -> None:
    older = _commit(repo, _store(), "older")
    release = _commit(
        repo,
        {**_store(ADDED), "caos/store/0003_budget.sql": "CREATE TABLE b (x int);\n"},
        "release adds a migration",
    )
    assert rollback_check.rollback_problems(older, release, repo) == [
        f"{release} applied 0003_budget, which {older} does not carry: its app "
        "refuses the store (STORE_SCHEMA_DRIFT)"
    ]


def test_a_migration_whose_bytes_moved_is_not_the_same_history(repo: Path) -> None:
    older = _commit(repo, _store(), "older")
    release = _commit(
        repo,
        {"caos/store/0002_extraction.sql": "ALTER TABLE cases ADD COLUMN y int;\n"},
        "release edits an applied migration",
    )
    [problem] = rollback_check.rollback_problems(older, release, repo)
    assert "in order and byte for byte" in problem


def test_code_from_before_the_schema_move_is_never_a_rollback(repo: Path) -> None:
    """F219 (DL-1): the same migrations, but read from `public`, is an app
    that starts green on an empty store beside the real one."""
    older = _commit(repo, _store(schema=""), "before DL-1")
    release = _commit(repo, _store(), "DL-1")
    assert rollback_check.rollback_problems(older, release, repo) == [
        f"{older} reads the public schema, not caos_store: it would start on an "
        "empty store beside the release's (F219, DL-1)"
    ]


def test_an_unreadable_commit_is_refused_not_passed(repo: Path) -> None:
    release = _commit(repo, _store(), "release")
    missing = "not-a-commit has no caos/store/__init__.py (or is not a commit)"
    assert rollback_check.store_layout("not-a-commit", repo) == (
        rollback_check.StoreLayout("", (), missing)
    )
    assert rollback_check.rollback_problems("not-a-commit", release, repo) == [missing]
    computed = _commit(
        repo,
        {"caos/store/__init__.py": "MIGRATIONS = tuple(load())\n"},
        "a computed list",
    )
    assert rollback_check.rollback_problems(computed, release, repo) == [
        f"{computed}'s MIGRATIONS cannot be read"
    ]


def test_the_reviewed_rollback_targets_are_refused() -> None:
    """The two targets review 4 booted against a store HEAD had migrated:
    the commit before 0040 refused the store, and 84eb06d, from before DL-1,
    started on a new store in `public`."""
    assert rollback_check.rollback_problems("HEAD", "HEAD") == []
    # Since D106 that commit also reads host records by no codec (M4); HEAD
    # writes them by codec 3 since D109 (2 since D107).
    drift, codec, *_ = rollback_check.rollback_problems("b1c1c83^", "HEAD")
    assert "0040_hidden_painted_over" in drift and "STORE_SCHEMA_DRIFT" in drift
    assert codec.startswith("b1c1c83^ reads host records by codec None, not 3")
    moved = rollback_check.rollback_problems("84eb06d", "HEAD")
    assert moved[0].startswith("84eb06d reads the public schema, not caos_store")
    assert rollback_check.main(["HEAD"]) == 0
    assert rollback_check.main(["84eb06d"]) == 1


def test_a_release_whose_record_codec_moved_cannot_be_rolled_back(
    repo: Path,
) -> None:
    """M4 (D106): the same migrations, but an older record codec, is an app
    that refuses every record the release wrote, so it is no rollback; the
    same codec on both sides is."""
    formats = 'RECORD_FORMAT = "r"\nBLOCKED_FORMAT = "b"\n'
    older = _commit(repo, {**_store(), HANDOFF: formats}, "older")
    release = _commit(
        repo, {HANDOFF: formats + "RECORD_CODEC_VERSION = 1\n"}, "release"
    )
    assert rollback_check.record_codec(older, repo) is None
    assert rollback_check.record_codec(release, repo) == 1
    assert rollback_check.rollback_problems(older, release, repo) == [
        f"{older} reads host records by codec None, not 1: it refuses the "
        f"records {release} wrote (D106)"
    ]
    same = _commit(repo, {"caos/serve.py": "a = 1\n"}, "same codec")
    assert rollback_check.rollback_problems(release, same, repo) == []


PDF = "caos/evidence/pdf.py"
PDF_SOURCE = """\
class {cls}:
    @property
    def identity(self):
        return ExtractorIdentity(
            "{name}",
            # a comment
            "{version}",
            {{"engine": "x"}},
        )
"""


def _extractor(version: str, name: str = "caos.pdfminer") -> str:
    return PDF_SOURCE.format(version=version, name=name, cls="PdfExtractor")


def test_a_release_whose_extractor_version_rose_cannot_be_rolled_back(
    repo: Path,
) -> None:
    """N111: equal migrations, schema and codec, but the release writes
    PdfExtractor v7 rows the older build refuses (SOURCE_IDENTITY_INVALID)."""
    older = _commit(repo, {**_store(), PDF: _extractor("6")}, "older")
    release = _commit(repo, {PDF: _extractor("7")}, "release")
    assert rollback_check.writer_versions(older, repo)["PdfExtractor version"] == "6"
    assert rollback_check.rollback_problems(older, release, repo) == [
        f"PdfExtractor version is 6 on {older} and 7 on {release}: {older} "
        f"refuses the rows {release} writes"
    ]
    same = _commit(repo, {"caos/serve.py": "a = 1\n"}, "same versions")
    assert rollback_check.rollback_problems(release, same, repo) == []


def test_every_declared_writer_version_is_read_and_each_move_is_named(
    repo: Path,
) -> None:
    files = {
        "caos/evidence/extract.py": _extractor("4", "caos.plain-text"),
        "caos/evidence/page.py": 'PDF_CROP_VERSIONS = frozenset({"2", "3"})\n',
        "caos/evidence/citations.py": 'NORMALISATION_VERSION = "2"\n',
        "caos/evidence/ingest.py": "PACKING_BY_WIDTH = 1\nPACKING_BY_TOKEN = 2\n",
        "caos/methodology/__init__.py": 'CANONICAL_ADAPTER_VERSION = "v3"\n',
        "caos/deliverable/verify_package.py": 'RENDERER_SHA256 = "aa"\n',
    }
    older = _commit(repo, {**_store(), **files}, "older")
    release = _commit(
        repo,
        {
            "caos/evidence/extract.py": _extractor("5", "caos.plain-text"),
            "caos/evidence/page.py": 'PDF_CROP_VERSIONS = frozenset({"2", "3", "4"})\n',
            "caos/evidence/citations.py": 'NORMALISATION_VERSION = "3"\n',
            "caos/evidence/ingest.py": "PACKING_BY_WIDTH = 1\nPACKING_BY_TOKEN = 3\n",
            "caos/methodology/__init__.py": 'CANONICAL_ADAPTER_VERSION = "v4"\n',
            "caos/deliverable/verify_package.py": 'RENDERER_SHA256 = "bb"\n',
        },
        "release",
    )
    named = [
        problem.split(" is ")[0]
        for problem in rollback_check.rollback_problems(older, release, repo)
    ]
    assert named == [
        "plain-text extractor version",
        "PDF crop versions",
        "citation normalisation version",
        "block packing (token)",
        "canonical adapter version",
        "renderer digest",
    ]


def test_a_release_with_an_unreadable_writer_is_refused_not_passed(
    repo: Path,
) -> None:
    """A writer the release declares in no form this reads is None on both
    sides when the older commit is the same, which compared equal and passed."""
    older = _commit(repo, {**_store(), HANDOFF: "RECORD_CODEC_VERSION = 1\n"}, "older")
    release = _commit(repo, {"caos/serve.py": "a = 1\n"}, "release")
    assert rollback_check.rollback_problems(older, release, repo) == [
        f"{label} is not declared in a form this check reads on {release}"
        for label in ("host record format", "blocked-citations format")
    ]


def test_every_writer_reads_a_value_at_head() -> None:
    versions = rollback_check.writer_versions("HEAD")
    assert [label for label, value in versions.items() if value is None] == []
    assert {"host record format", "blocked-citations format"} <= versions.keys()
