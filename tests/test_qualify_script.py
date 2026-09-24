"""The live qualification driver, checked where it decides not to spend --
and, separately, driven through its whole happy path against a real database.

The run this drives costs real money and is authorized one at a time, so what
is worth testing offline is the refusal before the spend: a profile the caller
did not expect must stop the driver before it creates a database, let alone
calls a provider. Everything after that point is "the harness's own, and has
its own suite" -- true of the behaviour, but SonarCloud's coverage gate is
per file, not per behaviour, and it does not credit this file for exercising
someone else's. So the happy path is driven here too, end to end, through
`qualify.main` exactly as an operator runs it: a real local PostgreSQL that
`qualify.py` creates and drops a database on (the same admin-connection
pattern `tests/conftest.py`'s `empty_database` uses), and a fake completion
provider standing in for the gateway so the run costs nothing and touches no
network.

The happy-path scenario below calls `qualify.main` with no `--attempts`, so
it exercises the single-`perform` path regardless of whether this revision's
`qualify.py` also carries `_perform_until`'s retry loop -- the default is one
attempt either way, and the retry loop has no suite of its own to lean on.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from canonical_fixtures import LITE_PROFILE, LITE_SELECTION, QUOTE, CanonicalCompletions

from caos.provider import Completion, encode_request
from caos.qualification.on_disk import MANIFEST
from caos.refusals import Refusal, RefusalCode
from caos.store import connect

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import qualify


def test_main_refuses_a_profile_the_caller_did_not_expect(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A verdict binds its execution profile, so a surprise one spends nothing."""
    monkeypatch.setenv("CAOS_MODEL_ENDPOINT", "openai/gpt-5.6-terra")
    # A provider that answers, so the refusal is the profile's and not the
    # workspace's: the real one refuses first when no workspace is configured.
    monkeypatch.setattr(qualify, "from_environment", _FakeProvider.from_environment)
    # No database is reachable under this name: reaching one would be the bug.
    monkeypatch.setenv("CAOS_TEST_POSTGRES_URL", "postgresql://nobody@127.0.0.1:1/none")
    monkeypatch.setenv(
        "CAOS_MODEL_PRICE", "openai/gpt-5.6-terra,0.000002,0.000012,2026-09-16"
    )

    code = qualify.main(
        [
            str(Path(__file__).resolve().parents[1] / "qualification/vmo2-fy2025"),
            "--expect-identity",
            "openrouter/google-ai-studio/high/65536",
            "--ceiling",
            "22.00",
        ]
    )

    assert code == 2
    assert "nothing was spent" in capsys.readouterr().err


def test_main_is_the_driver_the_record_names() -> None:
    """The driver is in the tree, not in a temporary directory that can vanish."""
    assert (Path(__file__).resolve().parents[1] / "scripts/qualify.py").is_file()
    assert qualify.main.__module__ == "qualify"


# The report and quote `CanonicalCompletions` below cites into every handoff
# it writes -- the same pair `tests/test_qualification_harness.py` uses for
# the LITE route, so a run against it proves out the same way that suite's
# does, without this file re-deriving the fixture.
REPORT = b"""Acme Holdings plc annual report 2026
Total debt at 31 December 2026 was USD 1,240.0m
"""


def _write_lite_set(root: Path) -> Path:
    """An on-disk qualification set of one case, over the LITE earnings route.

    Built the way `tests/test_qualification_on_disk.py`'s `_write` builds one:
    a manifest naming its documents relative to the set's own directory, plus
    the bytes those paths point at. One case is enough to drive `qualify.main`
    through every stage of the happy path without the cost of a set sized for
    a real qualification run.
    """
    document = root / "documents" / "lite-acme" / "report.txt"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_bytes(REPORT)
    manifest = {
        "cases": [
            {
                "label": "lite-acme",
                "profile_id": LITE_PROFILE,
                "selection_id": LITE_SELECTION,
                "documents": ["documents/lite-acme/report.txt"],
                "subject": {
                    "issuer_id": "ACME",
                    "issuer_name": "Acme Holdings plc",
                    "reporting_period": "FY2026",
                    "analysis_date": "2026-09-13",
                },
                "expects": [
                    {
                        "module_id": "CP-0",
                        "document_sha256": hashlib.sha256(REPORT).hexdigest(),
                        "matched_text": QUOTE,
                    }
                ],
            }
        ]
    }
    (root / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    return root


@dataclass
class _FakeProvider:
    """A `CompletionProvider` double standing in for the gateway provider.

    Mirrors `_Completions` in `tests/test_qualification_harness.py`: it reads
    the prompt the host actually built and answers with a canonical handoff
    cited to the evidence the prompt names, so the run underneath is a real
    one against the harness rather than a rehearsal -- it is only the network
    call that is faked. `provider` and `qualification_identity` are the two
    facts `qualify.main` and `harness._provider_identity` need from something
    that is not the gateway provider itself (`_provider_identity` reads
    `qualification_identity` first, then `.provider`).
    """

    model: str = "a-model/for-the-test"
    provider: str = "test-fake"
    qualification_identity: str = "test-fake-identity"
    prompts: list[str] = field(default_factory=list)

    @classmethod
    def from_environment(cls) -> _FakeProvider:
        return cls()

    def request_bytes(self, prompt: str, *, json_object: bool = False) -> bytes:
        return encode_request(self.model, prompt, json_object=json_object)

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion:
        self.prompts.append(prompt)
        # The evidence section is last, so its source is the last one named --
        # the same read `_Completions.complete` makes in the harness suite.
        source_id = re.findall(r"^source_id: (\S+)$", prompt, re.MULTILINE)[-1]
        return CanonicalCompletions(
            UUID(source_id), generation_id="gen-qualify-test"
        ).complete(prompt, json_object=json_object)


def test_main_refuses_to_keep_a_paid_run_where_it_cannot_last(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A paid run's database is its evidence. The test server keeps its data
    in memory, so a restart erased every retained run of 18 September 2026;
    the driver now needs a server named for the purpose and spends nothing
    without one."""
    monkeypatch.setenv("CAOS_MODEL_ENDPOINT", "openai/gpt-5.6-terra")
    monkeypatch.delenv("CAOS_QUALIFY_POSTGRES_URL", raising=False)
    monkeypatch.setenv("CAOS_TEST_POSTGRES_URL", "postgresql://nobody@127.0.0.1:1/none")
    monkeypatch.setenv(
        "CAOS_MODEL_PRICE", "openai/gpt-5.6-terra,0.000002,0.000012,2026-09-16"
    )

    code = qualify.main(
        [
            str(Path(__file__).resolve().parents[1] / "qualification/vmo2-fy2025"),
            "--expect-identity",
            "databricks/openai/gpt-5.6-terra/none/65536",
            "--ceiling",
            "22.00",
        ]
    )

    assert code == 2
    assert "CAOS_QUALIFY_POSTGRES_URL" in capsys.readouterr().err


def _skip_without_postgres() -> None:
    """The same skip/fail split `tests/conftest.py`'s database fixtures use.

    `qualify.py` reads `CAOS_QUALIFY_POSTGRES_URL` itself, as an admin
    connection it creates a fresh database from, so there is no store fixture
    to depend on for this -- the check is repeated here rather than skipped
    silently.
    """
    if os.environ.get("CAOS_TEST_POSTGRES_URL") is not None:
        return
    reason = "CAOS_TEST_POSTGRES_URL is unset: no database to run qualify.py against"
    if os.environ.get("CAOS_REQUIRE_POSTGRES") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture
def created(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Every database `qualify.main` creates in the test, dropped after it.

    The happy paths each left a `caos_qualify_<hex>` database on the shared
    server, 25 of them during one review (DQ-12). The list is what a test
    asserts on when the point is that nothing was created at all.
    """
    made: list[tuple[str, str]] = []
    names: list[str] = []
    create = qualify._create_database

    def recorded(admin_url: str) -> tuple[str, str]:
        database, run_url = create(admin_url)
        made.append((admin_url, database))
        names.append(database)
        return database, run_url

    monkeypatch.setattr(qualify, "_create_database", recorded)
    try:
        yield names
    finally:
        for admin_url, database in made:
            with psycopg.connect(admin_url, autocommit=True) as admin:
                admin.execute(
                    psycopg.sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        psycopg.sql.Identifier(database)
                    )
                )


def test_main_performs_a_full_qualification_set_against_a_real_database(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    created: list[str],
) -> None:
    """The whole happy path: `prepare`, every gate approved, `perform`,
    `_capture`, and the final JSON printed and written to `--capture`.

    Against a real local PostgreSQL -- the database `qualify.py` itself
    creates and applies the schema to -- and a fake provider, so the run costs
    nothing and reaches no network, while everything from the database
    upward is the real store.
    """
    _skip_without_postgres()
    test_server = os.environ["CAOS_TEST_POSTGRES_URL"]
    monkeypatch.setenv("CAOS_QUALIFY_POSTGRES_URL", test_server)
    monkeypatch.setenv("CAOS_QUALIFY_BLOB_ROOT", str(tmp_path / "blobs"))
    monkeypatch.setattr(qualify, "from_environment", _FakeProvider.from_environment)
    monkeypatch.setenv(
        "CAOS_MODEL_PRICE", "a-model/for-the-test,0.0000000001,0.00001,2026-09-13"
    )
    set_root = _write_lite_set(tmp_path / "set")
    capture_path = tmp_path / "capture.json"

    code = qualify.main(
        [
            str(set_root),
            "--expect-identity",
            "test-fake-identity",
            "--ceiling",
            "5.00",
            "--capture",
            str(capture_path),
        ]
    )

    out = capsys.readouterr().out
    preamble_line, _, rest = out.partition("\n")
    preamble = json.loads(preamble_line)
    assert set(preamble) == {
        "database",
        "blob_root",
        "run_ceiling",
        "price_model",
        "price_input_per_token",
        "price_output_per_token",
        "price_as_of",
        "price_worst_case_per_call",
    }
    body = rest.strip("\n")
    document = json.loads(body)

    assert code == 0
    assert created == [preamble["database"]]
    assert document["complete"] is True
    assert document["provider"] == "test-fake-identity"
    assert document["model"] == "a-model/for-the-test"
    assert len(document["result"]) == 1
    assert document["result"][0]["case_label"] == "lite-acme"
    assert document["result"][0]["status"] == "COMPLETE"
    assert document["result"][0]["stopped"] is None
    assert document["result"][0]["refusal"] is None
    assert document["result"][0]["proof"] is not None
    assert document["attempts"], "every pinned node attempted at least once"
    matrix = document["matrix"]
    assert matrix is not None
    assert len(matrix) == 1
    assert matrix[0]["case_label"] == "lite-acme"
    assert matrix[0]["proven"] is True
    assert matrix[0]["missed"] == 0
    # The LITE case here declares no forecast or readiness-gate expectation,
    # so these three columns are present (this revision's `QualificationMatrixRow`
    # carries them) but unset for a case that never asked to be judged by them.
    assert matrix[0]["ready_met"] is None
    assert matrix[0]["blocked_met"] is None
    assert matrix[0]["forecast_met"] is None
    assert matrix[0]["expected_refusal_met"] is None

    # `--capture` writes exactly what was printed, plus the trailing newline
    # `qualify.main` adds -- the branch at scripts/qualify.py's `args.capture
    # is not None` check.
    assert capture_path.read_text(encoding="utf-8") == body + "\n"


def test_main_refuses_a_malformed_admin_url_without_the_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """CF-078: a DSN psycopg's own parser refuses -- bad percent-encoding in
    the password -- raises `ProgrammingError` quoting the whole connection
    string, password included, in its message. `main`'s unguarded
    `_create_database(admin_url)` let that string escape to stderr; it must
    print the typed code alone, before any database was created."""
    monkeypatch.setenv(
        "CAOS_QUALIFY_POSTGRES_URL",
        "postgresql://baduser:SuperSecretPw%2passwordZZZ@127.0.0.1:1/nodb",
    )
    monkeypatch.setenv("CAOS_QUALIFY_BLOB_ROOT", str(tmp_path / "blobs"))
    monkeypatch.setattr(qualify, "from_environment", _FakeProvider.from_environment)
    monkeypatch.setenv(
        "CAOS_MODEL_PRICE", "a-model/for-the-test,0.0000000001,0.00001,2026-09-13"
    )
    set_root = _write_lite_set(tmp_path / "set")

    code = qualify.main(
        [
            str(set_root),
            "--expect-identity",
            "test-fake-identity",
            "--ceiling",
            "5.00",
        ]
    )

    assert code == 2
    logged = capsys.readouterr().err
    assert logged.strip() == "STORE_UNAVAILABLE: the set was refused; nothing was spent"
    assert "SuperSecretPw" not in logged


def test_main_writes_no_capture_file_when_the_flag_is_omitted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    created: list[str],
) -> None:
    """The other side of the `args.capture is not None` branch.

    Without `--capture`, `qualify.main` still prints the same JSON document to
    stdout and returns 0 on a complete run; it just writes nothing to disk.
    """
    _skip_without_postgres()
    test_server = os.environ["CAOS_TEST_POSTGRES_URL"]
    monkeypatch.setenv("CAOS_QUALIFY_POSTGRES_URL", test_server)
    monkeypatch.setenv("CAOS_QUALIFY_BLOB_ROOT", str(tmp_path / "blobs"))
    monkeypatch.setattr(qualify, "from_environment", _FakeProvider.from_environment)
    monkeypatch.setenv(
        "CAOS_MODEL_PRICE", "a-model/for-the-test,0.0000000001,0.00001,2026-09-13"
    )
    set_root = _write_lite_set(tmp_path / "set")

    code = qualify.main(
        [
            str(set_root),
            "--expect-identity",
            "test-fake-identity",
            "--ceiling",
            "5.00",
        ]
    )

    out = capsys.readouterr().out
    _preamble_line, _, rest = out.partition("\n")
    document = json.loads(rest.strip("\n"))

    assert code == 0
    assert document["complete"] is True
    assert not any(tmp_path.glob("**/capture.json"))


def test_main_refuses_an_unnamed_blob_root(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """FP-16: the blobs went to `$TMPDIR`, which macOS purges.

    `assert_orchestration_proof` re-reads them, so the evidence a paid run
    bought could not be re-proven once the purge ran. Named explicitly, exactly
    as the persistent server the database is kept on already is.
    """
    _skip_without_postgres()
    monkeypatch.setenv(
        "CAOS_QUALIFY_POSTGRES_URL", os.environ["CAOS_TEST_POSTGRES_URL"]
    )
    monkeypatch.delenv("CAOS_QUALIFY_BLOB_ROOT", raising=False)
    monkeypatch.setattr(qualify, "from_environment", _FakeProvider.from_environment)
    monkeypatch.setenv(
        "CAOS_MODEL_PRICE", "a-model/for-the-test,0.0000000001,0.00001,2026-09-13"
    )
    set_root = _write_lite_set(tmp_path / "set")

    code = qualify.main(
        [str(set_root), "--expect-identity", "test-fake-identity", "--ceiling", "5.00"]
    )

    assert code == 2
    assert "CAOS_QUALIFY_BLOB_ROOT" in capsys.readouterr().err


def test_main_refuses_a_missing_price_and_a_non_positive_attempt_count(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """FP-29: a missing `CAOS_MODEL_PRICE` was a `KeyError` traceback, and
    `--attempts 0` or a negative number silently meant one."""
    _skip_without_postgres()
    monkeypatch.setenv(
        "CAOS_QUALIFY_POSTGRES_URL", os.environ["CAOS_TEST_POSTGRES_URL"]
    )
    monkeypatch.setenv("CAOS_QUALIFY_BLOB_ROOT", str(tmp_path / "blobs"))
    monkeypatch.setattr(qualify, "from_environment", _FakeProvider.from_environment)
    monkeypatch.delenv("CAOS_MODEL_PRICE", raising=False)
    set_root = _write_lite_set(tmp_path / "set")
    common = [str(set_root), "--expect-identity", "test-fake-identity"]

    assert qualify.main([*common, "--ceiling", "5.00", "--attempts", "0"]) == 2
    assert "--attempts" in capsys.readouterr().err
    assert qualify.main([*common, "--ceiling", "5.00"]) == 2
    assert "CAOS_MODEL_PRICE" in capsys.readouterr().err


def _two_cases(root: Path) -> Path:
    """The one-case LITE set with a second case under another label."""
    _write_lite_set(root)
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    second = dict(manifest["cases"][0])
    second["label"] = "lite-borealis"
    manifest["cases"].append(second)
    (root / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    return root


def test_a_set_of_more_than_one_case_can_be_admitted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    created: list[str],
) -> None:
    """AR-18: the CLI set the whole-set ceiling and each run's to one number.

    `harness._affordable` requires `run_ceiling x cases <= ceiling`, so every
    positive-budget invocation with more than one case was impossible to admit
    and raising the shared value could not fix the inequality. The per-run
    ceiling is derived from the set's when it is not named, and printed with the
    database and the blob root so an operator can see what each run may spend.
    """
    _skip_without_postgres()
    monkeypatch.setenv(
        "CAOS_QUALIFY_POSTGRES_URL", os.environ["CAOS_TEST_POSTGRES_URL"]
    )
    monkeypatch.setenv("CAOS_QUALIFY_BLOB_ROOT", str(tmp_path / "blobs"))
    monkeypatch.setattr(qualify, "from_environment", _FakeProvider.from_environment)
    monkeypatch.setenv(
        "CAOS_MODEL_PRICE", "a-model/for-the-test,0.0000000001,0.00001,2026-09-13"
    )
    root = _two_cases(tmp_path / "set")

    code = qualify.main(
        [str(root), "--expect-identity", "test-fake-identity", "--ceiling", "10.00"]
    )

    preamble_line, _, rest = capsys.readouterr().out.partition("\n")
    preamble = json.loads(preamble_line)
    assert preamble["run_ceiling"] == "5.000000"
    assert code == 0
    assert created == [preamble["database"]]
    # DQ-6 (MAX-11): the capture read the first case's run alone, so the second
    # run's three charged calls were missing from what reconciles the bill.
    document = json.loads(rest.strip("\n"))
    runs = [item["run_id"] for item in document["result"]]
    assert document["run_ids"] == runs and len(set(runs)) == 2
    with connect(
        _database_url(os.environ["CAOS_TEST_POSTGRES_URL"], preamble["database"])
    ) as conn:
        stored = conn.execute(
            "SELECT t.run_id::text, t.route_node_id, t.ordinal FROM run_attempts t"
        ).fetchall()
    captured = [
        (item["run_id"], item["route_node_id"], item["ordinal"])
        for item in document["attempts"]
    ]
    assert sorted(captured) == sorted(stored)
    assert {run_id for run_id, _, _ in captured} == set(runs)


def _database_url(admin_url: str, database: str) -> str:
    """The admin URL pointed at `database`, as `qualify.py` builds its own."""
    from urllib.parse import urlsplit, urlunsplit

    return urlunsplit(urlsplit(admin_url)._replace(path=f"/{database}"))


def _refused_before_the_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, provider: _FakeProvider
) -> None:
    """The environment a spend would need, with nothing else in the way."""
    _skip_without_postgres()
    monkeypatch.setenv(
        "CAOS_QUALIFY_POSTGRES_URL", os.environ["CAOS_TEST_POSTGRES_URL"]
    )
    monkeypatch.setenv("CAOS_QUALIFY_BLOB_ROOT", str(tmp_path / "blobs"))
    monkeypatch.setenv(
        "CAOS_MODEL_PRICE", "a-model/for-the-test,0.0000000001,0.00001,2026-09-13"
    )
    monkeypatch.setattr(qualify, "from_environment", lambda: provider)


def test_a_run_ceiling_of_zero_is_the_operators_and_spends_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    created: list[str],
) -> None:
    """DQ-7: `args.run_ceiling or ceiling / cases` replaced a named zero -- falsy
    -- with the derived share, so a run capped at nothing made three paid
    calls. A named ceiling goes to the harness as given, which refuses a run
    that cannot afford one call, before the database exists."""
    provider = _FakeProvider()
    _refused_before_the_database(monkeypatch, tmp_path, provider)
    root = _write_lite_set(tmp_path / "set")

    code = qualify.main(
        [
            str(root),
            "--expect-identity",
            "test-fake-identity",
            "--ceiling",
            "5.00",
            "--run-ceiling",
            "0",
        ]
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "QUALIFICATION_SET_OVER_CEILING" in err and "nothing was spent" in err
    assert created == [] and provider.prompts == []


@pytest.mark.parametrize(
    "refused",
    [
        (0, "5.00", "QUALIFICATION_SET_EMPTY"),
        (1, "Infinity", "MONEY_INVALID"),
        (1, "sNaN", "MONEY_INVALID"),
    ],
)
def test_the_derived_run_ceiling_is_computed_only_from_what_admission_accepts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    created: list[str],
    refused: tuple[int, str, str],
) -> None:
    """R24-N03: with no `--run-ceiling`, the set ceiling was divided by the
    case count and quantized before either was checked, so an empty set raised
    `DivisionByZero` and `--ceiling Infinity` `InvalidOperation`: a traceback
    and exit 1 where every pre-spend refusal is a typed code and exit 2."""
    cases, ceiling, code = refused
    provider = _FakeProvider()
    _refused_before_the_database(monkeypatch, tmp_path, provider)
    root = _write_lite_set(tmp_path / "set")
    if not cases:
        manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
        (root / MANIFEST).write_text(json.dumps({**manifest, "cases": []}))

    argv = [str(root), "--expect-identity", "test-fake-identity", "--ceiling", ceiling]
    assert qualify.main(argv) == 2
    err = capsys.readouterr().err
    assert f"{code}: the set was refused; nothing was spent" in err
    assert created == [] and provider.prompts == []


def test_a_set_prepare_would_refuse_creates_no_database(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    created: list[str],
) -> None:
    """DQ-12: `CREATE DATABASE` ran before `prepare`, the first place a set's
    ceilings were checked, so `--ceiling 10 --run-ceiling 9` over two cases left
    an empty database on the operator's server and exited through a traceback.
    The checks run first and a refusal exits 2, as every pre-spend one does."""
    provider = _FakeProvider()
    _refused_before_the_database(monkeypatch, tmp_path, provider)
    root = _two_cases(tmp_path / "set")

    code = qualify.main(
        [
            str(root),
            "--expect-identity",
            "test-fake-identity",
            "--ceiling",
            "10.00",
            "--run-ceiling",
            "9.00",
        ]
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "QUALIFICATION_SET_OVER_CEILING" in err and "nothing was spent" in err
    assert created == [] and provider.prompts == []


def test_a_refusal_after_the_database_exists_names_the_database(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    created: list[str],
) -> None:
    """DQ-5 at the driver: a set that stops on a refusal after its database
    exists -- the matrix's own last check, say -- exits 2 naming the database
    that keeps what it performed, never claiming that nothing was spent."""
    provider = _FakeProvider()
    _refused_before_the_database(monkeypatch, tmp_path, provider)
    root = _write_lite_set(tmp_path / "set")

    def refused(*_: object, **__: object) -> object:
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)

    monkeypatch.setattr(qualify, "_perform_until", refused)
    code = qualify.main(
        [str(root), "--expect-identity", "test-fake-identity", "--ceiling", "5.00"]
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "AUTHORITY_BYTES_MISMATCH" in err and created and created[0] in err
    assert "nothing was spent" not in err
