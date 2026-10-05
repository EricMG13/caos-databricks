"""The owner's ruling on a Blocked answer: "Show its quotes (Recommended)".

Run and Analysis serve a Blocked verdict with the answer's quotes as the
host judged them (`blocked_by_view`, from the blob migration 0044 keeps
beside the verdict): each located one with the line it is an excerpt of,
each unverified one as the model's own, labelled by its code. A verdict
recorded before 0044 has none, and says so. The quotes are the model's, so
the EX2 injection probes cross the wire as the exact text they are -- the
workspace renders them as text (`frontend/tests/unit/unverified.test.tsx`).
"""

from __future__ import annotations

from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from test_deliverable_canonical import LITE

from caos.api.reads import analysis as analysis_read
from caos.api.reads.analysis import blocked_by_view
from caos.api.wire import BlockedByView
from caos.blobs import BlobStore
from caos.evidence.citations import AnchoredCitation, Rect
from caos.methodology.handoff import UnverifiedCitation, blocked_citations_bytes
from caos.refusals import RefusalCode
from caos.store import StoreConnection
from caos.store.source_sets import cited_source_ids

# The stand-in above answers for the store; nothing else may reach it.
_NO_STORE = cast(StoreConnection, None)
LINE = (
    "We do not believe <script>alert(1)</script> & \"x\" 'y' that revenue will"
    " grow by more than 5% next year."
)
EXCERPT = "<script>alert(1)</script> & \"x\" 'y' that revenue will grow"
UNVERIFIED = "</q><mark>INJECT</mark> | `code` | **bold** | [l](http://e)"


SOURCE = uuid4()


def _verdict(blobs: BlobStore, sha: str | None) -> BlockedByView:
    """The view, its located quotes' documents resolved by a stand-in for
    the run's pinned members (`cited_source_ids`, one query in the reads)."""
    node = LITE.nodes[1]
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            analysis_read,
            cited_source_ids.__name__,
            lambda _conn, _run, documents: {d: (SOURCE, None) for d in documents},
        )
        return blocked_by_view(
            LITE, (uuid4(), node.route_node_id), sha, (_NO_STORE, blobs, uuid4())
        )


def test_a_blocked_view_lists_the_answers_quotes_verified_and_unverified(
    tmp_path: Path,
) -> None:
    blobs = BlobStore(tmp_path / "blobs")
    anchored = AnchoredCitation(
        "a" * 64, 3, EXCERPT, (Rect(3, 0.0, 0.0, 1.0, 1.0),), line_text=LINE
    )
    unverified = UnverifiedCitation(
        uuid4(), 9, UNVERIFIED, RefusalCode.CITATION_AMBIGUOUS, linked=False
    )
    sha = blobs.put(blocked_citations_bytes((anchored,), (unverified,)))

    view = _verdict(blobs, sha)

    assert view.quotes_recorded and view.module_id == LITE.nodes[1].module_id
    [verified] = view.verified
    assert verified.matched_text == EXCERPT and verified.page == 3
    assert (verified.source_id, verified.withdrawn_at) == (SOURCE, None)
    assert (verified.line.before, verified.line.excerpt, verified.line.after) == (
        "We do not believe ",
        EXCERPT,
        " by more than 5% next year.",
    )
    [model] = view.unverified
    assert (model.matched_text, model.page, model.code, model.linked) == (
        UNVERIFIED,
        9,
        "CITATION_AMBIGUOUS",
        False,
    )


def test_a_verdict_from_before_its_quotes_were_kept_says_so(tmp_path: Path) -> None:
    view = _verdict(BlobStore(tmp_path / "blobs"), None)
    assert not view.quotes_recorded and view.quotes_refusal is None
    assert (view.verified, view.unverified) == ([], [])


def test_quotes_unreadable_are_a_contained_typed_notice(tmp_path: Path) -> None:
    """Bytes not this host's, or a kept blob since missing: the refusal is
    the view's own field, never the run page's."""
    blobs = BlobStore(tmp_path / "blobs")
    for sha in (blobs.put(b'{"format":1}'), "f" * 64):
        view = _verdict(blobs, sha)
        assert view.quotes_recorded
        assert view.quotes_refusal is not None
        assert view.quotes_refusal.code == RefusalCode.ARTIFACT_RECORD_MISMATCH
        assert (view.verified, view.unverified) == ([], [])
