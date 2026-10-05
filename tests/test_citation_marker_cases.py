"""The page reads markers as the host does (F506, the MK2 audit): one set
of cases, `frontend/tests/unit/marker-cases.json`, held here to the host's
reader (`handoff.markers`) and in `markers.test.tsx` to the page's. Where
the page shows a block as written -- fenced code, a comment, front matter
the host does not take for it, a table it cannot format -- it draws no chip,
and the case says why; whether a citation is linked is the host's alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from caos.methodology.handoff import MARKER_DIGITS, markers

CASES = json.loads(
    (
        Path(__file__).resolve().parents[1] / "frontend/tests/unit/marker-cases.json"
    ).read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", CASES, ids=[repr(c["text"])[:40] for c in CASES])
def test_the_host_reads_each_shared_case_as_the_page_expects(
    case: dict[str, object],
) -> None:
    host, page = case["host"], case.get("page", case["host"])
    assert list(markers(str(case["text"]))) == host
    # A case where the page draws differently names its reason, and only
    # ever draws fewer chips than the host reads markers.
    assert isinstance(host, list) and isinstance(page, list)
    assert ("why" in case) == (page != host) and set(page) <= set(host)


def test_the_page_and_the_host_cut_a_marker_at_the_same_digits() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "frontend/src/ds/markdown.ts"
    ).read_text(encoding="utf-8")
    assert f"export const MARKER_DIGITS = {MARKER_DIGITS};" in source
