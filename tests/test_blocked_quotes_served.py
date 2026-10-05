"""The owner's ruling on a Blocked answer: "Show its quotes (Recommended)".

Run and Analysis serve a Blocked verdict with the answer's quotes as the
host judged them (`blocked_by_view`, from the blob migration 0044 keeps
beside the verdict): each located one with the line it is an excerpt of,
each unverified one as the model's own, labelled by its code. A verdict
recorded before 0044 has none, and says so. The quotes are the model's, so
the EX2 injection probes cross the wire as the exact text they are -- the
workspace renders them as text (`frontend/tests/unit/blocked.test.tsx`).
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from test_deliverable_canonical import LITE

from caos.api.reads.analysis import blocked_by_view
from caos.api.wire import BlockedByView
from caos.blobs import BlobStore
from caos.evidence.citations import AnchoredCitation, Rect
from caos.methodology.handoff import UnverifiedCitation, blocked_citations_bytes
from caos.refusals import Refusal, RefusalCode

LINE = (
    "We do not believe <script>alert(1)</script> & \"x\" 'y' that revenue will"
    " grow by more than 5% next year."
)
EXCERPT = "<script>alert(1)</script> & \"x\" 'y' that revenue will grow"
UNVERIFIED = "</q><mark>INJECT</mark> | `code` | **bold** | [l](http://e)"


def _verdict(blobs: BlobStore, sha: str | None) -> BlockedByView:
    node = LITE.nodes[1]
    return blocked_by_view(LITE, (uuid4(), node.route_node_id), sha, blobs)


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
    assert not view.quotes_recorded
    assert (view.verified, view.unverified) == ([], [])


def test_quotes_that_are_not_the_hosts_bytes_are_refused(tmp_path: Path) -> None:
    blobs = BlobStore(tmp_path / "blobs")
    sha = blobs.put(b'{"format":1}')
    with pytest.raises(Refusal) as caught:
        _verdict(blobs, sha)
    assert caught.value.code == RefusalCode.ARTIFACT_RECORD_MISMATCH
