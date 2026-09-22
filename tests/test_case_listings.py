"""The store reads behind the Directory and Upload sections (Task 4.1, slice 4.1c).

`cases_for_member` lists a user's live-standing cases in one query, whatever
their number; `case_sources` lists a case's sources with the set versions each
belongs to, and says when it stopped at its limit.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.ingest import Document, admit_pack
from caos.store import StoreConnection
from caos.store.members import (
    CaseListing,
    RunListing,
    Standing,
    cases_for_member,
    grant,
)
from caos.store.runs import create_case, start_run
from caos.store.source_sets import (
    CaseSetVersion,
    CaseSource,
    CaseSources,
    case_sources,
    snapshot_source_set,
)


class _CountingConnection:
    """Counts store round trips."""

    def __init__(self, conn: StoreConnection) -> None:
        self._conn = conn
        self.executed = 0

    def execute(self, *args: object, **kwargs: object) -> object:
        self.executed += 1
        return self._conn.execute(*args, **kwargs)  # type: ignore[arg-type]


def _admit(
    conn: StoreConnection, case_id: UUID, blobs: Path, *names: str
) -> list[UUID]:
    return admit_pack(
        conn,
        BlobStore(blobs),
        case_id=case_id,
        documents=[
            Document(BoundaryText.of(name), f"text of {name}".encode())
            for name in names
        ],
    )


def test_case_sources_truncates_past_its_limit(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    conn, case_id = case
    _admit(conn, case_id, tmp_path / "b", "a.txt", "b.txt", "c.txt")
    conn.commit()
    snapshot_source_set(conn, case_id)

    listed = case_sources(conn, case_id=case_id, limit=2)

    assert len(listed.sources) == 2
    assert listed.truncated is True
    assert case_sources(conn, case_id=case_id, limit=3).truncated is False


def test_cases_for_member_costs_one_query_whatever_the_case_count(
    case: tuple[StoreConnection, UUID],
) -> None:
    conn, _case_id = case
    user = uuid4()
    for index in range(5):
        created = create_case(conn, BoundaryText.of(f"Case {index}"))
        grant(conn, case_id=created, user_id=user, standing=Standing.READER)
        start_run(conn, created)
    conn.commit()
    counter = _CountingConnection(conn)

    listed = cases_for_member(counter, user_id=user, limit=10)  # type: ignore[arg-type]

    assert len(listed) == 5
    assert all(row.latest_run is not None for row in listed)
    assert counter.executed == 1


def test_store_listings_are_typed_rows(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    """`CaseListing` carries a `RunListing`; `CaseSources` carries `CaseSource`
    and `CaseSetVersion` rows."""
    conn, case_id = case
    user = uuid4()
    grant(conn, case_id=case_id, user_id=user, standing=Standing.READER)
    run_id = start_run(conn, case_id)
    _admit(conn, case_id, tmp_path / "b", "a.txt")
    conn.commit()
    snapshot_source_set(conn, case_id)

    [listing] = cases_for_member(conn, user_id=user, limit=1)
    listed = case_sources(conn, case_id=case_id, limit=10)

    assert isinstance(listing, CaseListing)
    assert isinstance(listing.latest_run, RunListing)
    assert (listing.latest_run.run_id, listing.latest_run.status) == (
        run_id,
        "RUNNING",
    )
    assert (listing.latest_run.profile_id, listing.latest_run.selection_id) == (
        None,
        None,
    )
    assert isinstance(listed, CaseSources)
    assert all(isinstance(source, CaseSource) for source in listed.sources)
    assert [type(v) for v in listed.set_versions] == [CaseSetVersion]
    assert listed.sources[0].set_versions == (1,)


def test_a_listing_that_asks_for_no_members_serves_none_not_empty(
    case: tuple[StoreConnection, UUID],
) -> None:
    """The Book lists without `members_limit`: an ADMIN row then says "not
    served" (`None`), never "no members" (an empty tuple), which is the
    distinction `CaseRow.members` carries on the wire."""
    conn, case_id = case
    user = uuid4()
    grant(conn, case_id=case_id, user_id=user, standing=Standing.ADMIN)
    conn.commit()

    [unasked] = cases_for_member(conn, user_id=user, limit=1)
    [asked] = cases_for_member(conn, user_id=user, limit=1, members_limit=5)

    assert unasked.members is None
    assert asked.members == ((user, Standing.ADMIN),)
