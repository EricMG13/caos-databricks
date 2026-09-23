"""The release pack: emitted from the suite, the tree and the store, never typed.

`docs/COMPLETION_PLAN.md` Phase 13's exit check asks for two things of it, and
each has a test here. "The release pack reproduces without editing a checksum"
is byte equality between two emissions over one tree, one of them from a fresh
interpreter so that nothing an in-process cache or a hash seed decides can
leak into the bytes. "Every advertised pathway has a current verdict or is
disabled and says so" is the pathway table, and the half of it that matters
most is the negative one: no pathway reads QUALIFIED unless a signed
`qualification_verdicts` row, current at the moment the caller names and bound
to this build, stands behind it.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import release_pack
from qualification_fixtures import qualification_performed, record_runs

from caos.api.deps import VENDORED_BUNDLE
from caos.graph.route import ResolvedRoute, resolve_route, route_digest
from caos.methodology import CANONICAL_ADAPTER_VERSION
from caos.methodology.bundle import Bundle
from caos.methodology.handoff import ADAPTER_ROUTES
from caos.methodology.vendor import catalog
from caos.qualification.store import (
    PerformedEvidence,
    performed_evidence,
    record_performed,
    record_verdict,
)
from caos.qualification.verdict import read_verdict
from caos.refusals import Refusal
from caos.store import StoreConnection, apply_schema, connect
from caos.store.routes import _canonical

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 18, tzinfo=UTC)
# `qualification_fixtures` pins every run of its snapshot to this build.
FIXTURE_BUILD = "b" * 64


def _catalog_pathways() -> set[tuple[str, str]]:
    loaded = catalog(Bundle(VENDORED_BUNDLE))
    return {
        (profile_id, selection_id)
        for profile_id, profile in loaded["profiles"].items()
        for selection_id in profile["pathways"]
    }


def test_two_packs_over_one_tree_are_byte_identical(tmp_path: Path) -> None:
    """The exit check's first half: reproduce without editing a checksum.

    One emission in-process and one from a fresh interpreter under a different
    hash seed. Equal bytes across the two is what "reproduces" means; equal
    output from one process twice would pass a pack that iterated a set.
    """
    here, there = tmp_path / "here", tmp_path / "there"
    assert release_pack.main(["--out", str(here)]) == 0
    completed = subprocess.run(
        [sys.executable, str(REPO / "scripts/release_pack.py"), "--out", str(there)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONHASHSEED": "12345"},
    )
    assert completed.returncode == 0, completed.stderr
    for name in (release_pack.JSON_NAME, release_pack.MARKDOWN_NAME):
        assert (here / name).read_bytes() == (there / name).read_bytes(), name


def test_every_catalog_pathway_is_enabled_or_disabled_and_says_so() -> None:
    """The exit check's second half, for a pack that read no store."""
    pack = release_pack.build_pack(REPO, bundle=Bundle(VENDORED_BUNDLE))
    rows = {(row["profile_id"], row["selection_id"]): row for row in pack["pathways"]}
    assert set(rows) == _catalog_pathways()
    for key, row in rows.items():
        if key in ADAPTER_ROUTES:
            assert row["enabled"] is True
            assert row["status"] == release_pack.UNVERIFIED
        else:
            assert row["enabled"] is False
            assert row["status"] == release_pack.DISABLED
            assert "HANDOFF_MODULE_UNSUPPORTED" in row["reason"]
        assert row["verdicts"] == []
    assert pack["store"] is None


def test_the_pack_names_the_build_the_locks_and_the_migration_head() -> None:
    bundle = Bundle(VENDORED_BUNDLE)
    pack = release_pack.build_pack(REPO, bundle=bundle)
    assert pack["bundle"] == {
        "build_id": bundle.build_id,
        "manifest_sha256": bundle.manifest_sha256,
    }
    assert set(pack["locks"]) == set(release_pack.LOCK_FILES)
    assert all(len(digest) == 64 for digest in pack["locks"].values())
    assert pack["migrations"] == release_pack.migration_head()


def test_the_migration_head_is_the_digest_a_migrated_store_records(
    empty_database: str,
) -> None:
    """The pack's head is the store's own `applied_digest`, not a second
    reading of the migration list that could drift from it."""
    with connect(empty_database) as conn:
        apply_schema(conn)
        applied = conn.execute("SELECT applied_digest FROM store_schema").fetchone()
    head = release_pack.migration_head()
    assert applied == (head["history_sha256"],)
    assert head["count"] == len(head["names"])


def test_the_inventory_is_read_from_both_suites() -> None:
    """The live answer that replaces the dated feature-status record."""
    inventory = release_pack.suite_inventory(REPO)
    assert (
        "tests/test_release_pack.py::test_the_inventory_is_read_from_both_suites"
        in inventory["python"]
    )
    assert inventory["python"] == sorted(inventory["python"])
    assert inventory["frontend"] == sorted(inventory["frontend"])
    assert any(
        title.startswith("frontend/tests/unit/") for title in inventory["frontend"]
    )


def test_an_empty_suite_is_a_failure_not_an_empty_pack(tmp_path: Path) -> None:
    """A scanner that scanned nothing is a failure (`CLAUDE.md`)."""
    (tmp_path / "tests").mkdir()
    with pytest.raises(release_pack.EmptyScan):
        release_pack.suite_inventory(tmp_path)


def test_a_store_read_needs_the_moment_it_is_judged_at(tmp_path: Path) -> None:
    """A verdict's currency is judged at a moment the caller names, never the
    clock's, or two emissions a second apart could differ."""
    assert release_pack.main(["--out", str(tmp_path), "--store"]) == 2


def _pin(
    conn: StoreConnection,
    profile_id: str,
    selection_id: str,
    performed: PerformedEvidence | None = None,
    *,
    accepted_nothing: str | None = None,
) -> PerformedEvidence:
    """The route pin behind the fixture snapshot's one run, written for real.

    `run_routes` used to be written here with `resolved='{}'` -- a row
    `route_pin` refuses `ROUTE_IDENTITY_INVALID` -- and the pack read the row
    directly and named a pathway from it (FP-02). The pin goes through
    `pin_route` now, and the snapshot carries the digest that route actually
    has, because that join is what ties a verdict to a pathway.
    """
    route = resolve_route(catalog(Bundle(VENDORED_BUNDLE)), profile_id, selection_id)
    performed = _on_route(route, performed)
    record_performed(conn, performed)
    record_runs(conn, performed, accepted_nothing=accepted_nothing)
    # `pin_route_in`'s own row, written without its lock: the fixture's runs are
    # rows, not runs a worker drove, so they are not RUNNING.
    for case in performed.prepared:
        conn.execute(
            "INSERT INTO run_routes (run_id,profile_id,selection_id,route_digest,"
            "resolved) VALUES (%s,%s,%s,%s,%s)",
            (
                case.input.run_id,
                route.profile_id,
                route.selection_id,
                route_digest(route),
                _canonical(route),
            ),
        )
    return performed


def _on_route(
    route: ResolvedRoute, performed: PerformedEvidence | None = None
) -> PerformedEvidence:
    """The snapshot, with every prepared case pinned to this route's digest."""
    digest = route_digest(route)
    original = qualification_performed() if performed is None else performed
    return performed_evidence(
        prepared=tuple(
            replace(case, input=replace(case.input, route_digest=digest))
            for case in original.prepared
        ),
        performed=original.performed,
    )


def _sign(
    conn: StoreConnection,
    *,
    days: int = 30,
    performed: PerformedEvidence | None = None,
) -> None:
    evidence = (qualification_performed() if performed is None else performed).evidence
    record_verdict(
        conn,
        evidence=evidence,
        reviewer_id=uuid4(),
        verdict=read_verdict(
            {
                "provider": evidence.provider + ":" + evidence.model,
                "qualification_set_sha256": evidence.qualification_set_sha256,
                "build_id": evidence.build_id,
                "decided_at": NOW.isoformat(),
                "expires_at": (NOW + timedelta(days=days)).isoformat(),
                "reviewer": "Reviewer",
            },
            now=NOW,
        ),
    )


def test_no_pathway_is_qualified_without_a_signed_verdict_row(
    empty_database: str,
) -> None:
    """A performed, complete snapshot on a pinned pathway is not a verdict."""
    profile_id, selection_id = sorted(ADAPTER_ROUTES)[0]
    with connect(empty_database) as conn:
        apply_schema(conn)
        performed = _pin(conn, profile_id, selection_id)
        assert (
            release_pack.qualified_pathways(
                conn, build_id=FIXTURE_BUILD, as_of=NOW + timedelta(days=1)
            )
            == {}
        )
        _sign(conn, performed=performed)
        found = release_pack.qualified_pathways(
            conn, build_id=FIXTURE_BUILD, as_of=NOW + timedelta(days=1)
        )
    assert list(found) == [(profile_id, selection_id)]
    (verdict,) = found[(profile_id, selection_id)]
    assert verdict["reviewer"] == "Reviewer"
    assert verdict["expires_at"] == (NOW + timedelta(days=30)).isoformat()


@pytest.mark.parametrize(
    ("build_id", "as_of"),
    [
        pytest.param("c" * 64, NOW + timedelta(days=1), id="another-build"),
        pytest.param(FIXTURE_BUILD, NOW + timedelta(days=31), id="expired"),
        pytest.param(FIXTURE_BUILD, NOW - timedelta(days=1), id="not-yet-decided"),
    ],
)
def test_a_verdict_that_is_not_current_for_this_build_qualifies_nothing(
    empty_database: str, build_id: str, as_of: datetime
) -> None:
    profile_id, selection_id = sorted(ADAPTER_ROUTES)[0]
    with connect(empty_database) as conn:
        apply_schema(conn)
        performed = _pin(conn, profile_id, selection_id)
        _sign(conn, performed=performed)
        assert (
            release_pack.qualified_pathways(conn, build_id=build_id, as_of=as_of) == {}
        )


def test_a_verdict_from_an_old_adapter_revision_qualifies_nothing(
    empty_database: str,
) -> None:
    profile_id, selection_id = sorted(ADAPTER_ROUTES)[0]
    current = qualification_performed()
    [prepared] = current.prepared
    old_adapter = performed_evidence(
        prepared=(
            replace(
                prepared,
                input=replace(
                    prepared.input,
                    adapter_version=CANONICAL_ADAPTER_VERSION + "-old",
                ),
            ),
        ),
        performed=current.performed,
    )
    with connect(empty_database) as conn:
        apply_schema(conn)
        pinned = _pin(conn, profile_id, selection_id, old_adapter)
        _sign(conn, performed=pinned)
        assert (
            release_pack.qualified_pathways(
                conn, build_id=FIXTURE_BUILD, as_of=NOW + timedelta(days=1)
            )
            == {}
        )


def test_a_store_read_reports_enabled_pathways_qualified_or_not(
    empty_database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Driven through `main`, as `make release-pack STORE=1` drives it."""
    monkeypatch.setenv("CAOS_DATABASE_URL", empty_database)
    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()
    code = release_pack.main(
        ["--out", str(tmp_path), "--store", "--as-of", NOW.isoformat()]
    )
    assert code == 0
    pack = json.loads((tmp_path / release_pack.JSON_NAME).read_text(encoding="utf-8"))
    assert pack["store"] == {"as_of": NOW.isoformat()}
    statuses = {row["status"] for row in pack["pathways"] if row["enabled"] is True}
    assert statuses == {release_pack.NOT_QUALIFIED}
    markdown = (tmp_path / release_pack.MARKDOWN_NAME).read_text(encoding="utf-8")
    assert f"store read as of {NOW.isoformat()}" in markdown


def test_a_store_its_migrations_do_not_describe_refuses_the_pack(
    empty_database: str,
) -> None:
    """Verdicts read from a store this build cannot vouch for would be relayed
    from rows whose meaning the build does not know."""
    with connect(empty_database) as conn:
        with pytest.raises(Refusal, match=r"^STORE_SCHEMA_DRIFT$"):
            release_pack.read_store(conn, bundle=Bundle(VENDORED_BUNDLE), as_of=NOW)


def test_a_lock_digest_is_the_digest_of_the_bytes_on_disk() -> None:
    digests = release_pack.lock_digests(REPO)
    for name, digest in digests.items():
        assert digest == hashlib.sha256((REPO / name).read_bytes()).hexdigest()


def test_the_written_pack_reads_back_as_the_pack_and_the_reader_copy_names_every_row(
    tmp_path: Path,
) -> None:
    pack = release_pack.build_pack(REPO, bundle=Bundle(VENDORED_BUNDLE))
    release_pack.write_pack(pack, tmp_path)
    written = (tmp_path / release_pack.JSON_NAME).read_text(encoding="utf-8")
    assert json.loads(written) == pack
    markdown = release_pack.render_markdown(pack)
    assert (tmp_path / release_pack.MARKDOWN_NAME).read_text(
        encoding="utf-8"
    ) == markdown
    for row in pack["pathways"]:
        assert (
            f"| `{row['profile_id']}` | `{row['selection_id']}` | {row['status']} |"
            in markdown
        )
    assert "no pathway is claimed qualified" in markdown


def test_a_pathway_is_qualified_only_through_a_run_that_produced_output(
    empty_database: str,
) -> None:
    """FP-02: a verdict covered every pathway any run in its snapshot was pinned
    to.

    A case that met the refusal it declared -- signable, and deliberately so --
    made its own pathway QUALIFIED although no run on it produced an artifact.
    """
    profile_id, selection_id = sorted(ADAPTER_ROUTES)[0]
    refused = qualification_performed(blocked_label="blocked")
    with connect(empty_database) as conn:
        apply_schema(conn)
        performed = _pin(
            conn, profile_id, selection_id, refused, accepted_nothing="blocked"
        )
        _sign(conn, performed=performed)
        found = release_pack.qualified_pathways(
            conn, build_id=FIXTURE_BUILD, as_of=NOW + timedelta(days=1)
        )
        # Both cases are pinned to the one pathway; only the one that finished
        # and answered its keys is what the verdict covers.
        assert list(found) == [(profile_id, selection_id)]
        assert release_pack._snapshot_pins(performed.document) == [
            (
                performed.prepared[0].input.run_id,
                performed.prepared[0].input.route_digest,
            )
        ]


def test_a_verdict_entry_names_the_signer_the_identity_and_the_set(
    empty_database: str,
) -> None:
    """FP-14 and AR-22: the entry carried free text an ADMIN typed and dates.

    Production's model is set by environment (D7), so a pack's QUALIFIED said
    nothing about which execution identity it covered, and `--provider/--model`
    is how a deployment asks for its own.
    """
    profile_id, selection_id = sorted(ADAPTER_ROUTES)[0]
    with connect(empty_database) as conn:
        apply_schema(conn)
        performed = _pin(conn, profile_id, selection_id)
        _sign(conn, performed=performed)
        evidence = performed.evidence
        as_of = NOW + timedelta(days=1)
        (verdict,) = release_pack.qualified_pathways(
            conn, build_id=FIXTURE_BUILD, as_of=as_of
        )[(profile_id, selection_id)]
        assert verdict["provider"] == evidence.provider
        assert verdict["model"] == evidence.model
        assert verdict["qualification_set_sha256"] == evidence.qualification_set_sha256
        assert UUID(verdict["reviewer_id"])
        assert (
            release_pack.qualified_pathways(
                conn,
                build_id=FIXTURE_BUILD,
                as_of=as_of,
                identity=(evidence.provider, evidence.model),
            )
            != {}
        )
        assert (
            release_pack.qualified_pathways(
                conn,
                build_id=FIXTURE_BUILD,
                as_of=as_of,
                identity=(evidence.provider, "another/model"),
            )
            == {}
        )


def test_a_pin_the_store_cannot_read_names_no_pathway(empty_database: str) -> None:
    """FP-02: `run_routes` was read by `(run_id, route_digest)` and never
    validated, so a row whose `resolved` is `{}` named a pathway although
    `route_pin` refuses it `ROUTE_IDENTITY_INVALID`."""
    profile_id, selection_id = sorted(ADAPTER_ROUTES)[0]
    performed = qualification_performed()
    with connect(empty_database) as conn:
        apply_schema(conn)
        record_performed(conn, performed)
        record_runs(conn, performed)
        [case] = performed.prepared
        conn.execute(
            "INSERT INTO run_routes (run_id,profile_id,selection_id,route_digest,"
            "resolved) VALUES (%s,%s,%s,%s,'{}')",
            (case.input.run_id, profile_id, selection_id, case.input.route_digest),
        )
        _sign(conn, performed=performed)
        assert (
            release_pack.qualified_pathways(
                conn, build_id=FIXTURE_BUILD, as_of=NOW + timedelta(days=1)
            )
            == {}
        )
