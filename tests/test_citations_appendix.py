"""D107's deliverable (F506; owner, 4 October 2026: "The deliverable lists
citations compactly in an appendix rather than inline full lines"): the
analysis keeps its `[C<n>]` markers as text; each module ends with a compact
Citations appendix, one line per citation in the answer's list order --
marker, document, page, the excerpt clamped, verified or labelled
unverified; a narrative figure is its excerpt and a reference to its
module's citation; no source line and no `<mark>` anywhere on the page.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any

import pytest
from test_deliverable_package import IDENTITY
from test_unverified_citations_shown import (
    DOCUMENT,
    LINE,
    SOURCE,
    _anchored,
    _payload,
    _unverified,
)

from caos.deliverable.render import (
    EXCERPT_CHARS,
    RenderRefused,
    clamped,
    located,
    render,
)

OPEN, CLOSE = "\N{LEFT DOUBLE QUOTATION MARK}", "\N{RIGHT DOUBLE QUOTATION MARK}"


def _rows(page: str) -> list[str]:
    appendix = page.split('<h3>Citations</h3>\n<ul class="cite">\n')[1]
    return re.findall(r"<li>(.*?)</li>", appendix.split("</ul>")[0])


def _marked() -> dict[str, Any]:
    """A record since D107: [C1] and [C3] located, [C2] not."""
    return _payload(
        [_anchored(marker=1), _anchored(marker=3, linked=False, page=2)],
        [_unverified(marker=2)],
    )


def test_the_appendix_lists_each_citation_in_the_answers_order() -> None:
    page = render(_marked()).decode()
    module = page.split("<h2>", 2)[1]
    analysis = module.index("<h3>Analysis (model-authored, not host-verified)</h3>")
    calculation = module.index("<h3>Deterministic calculations</h3>")
    appendix = module.index("<h3>Citations</h3>")
    assert analysis < calculation < appendix
    excerpt = f"{OPEN}believe the Borrower will breach the leverage covenant{CLOSE}"
    assert _rows(page) == [
        f"[C1] · 6fc4a221c5d5 · page 1 · {excerpt} · verified",
        f"[C2] · unverified \N{EN DASH} page 4 · source {SOURCE} · the model's quote"
        f" {OPEN}Net leverage is 3.2x{CLOSE} · claim lineage: Untraced · not located",
        f"[C3] · 6fc4a221c5d5 · page 2 · {excerpt} · verified"
        " · not linked to a statement in the answer",
    ]
    # The whole line is the source's to show, at the page given.
    assert "We do not" not in page and LINE not in page
    assert "<mark" not in page and "<blockquote" not in page


def test_the_analysis_keeps_its_markers_as_text() -> None:
    payload = _marked()
    artifact = payload["artifacts"][0]
    markdown = "Leverage holds [C1]; headroom [C2, C3] and \\[C1\\].\n"
    _rebind(artifact, markdown)
    page = render(payload).decode()
    assert "<p>Leverage holds [C1]; headroom [C2, C3] and \\[C1\\].</p>" in page


def _rebind(artifact: dict[str, Any], markdown: str) -> None:
    """`artifact` with `markdown` in place, its two digests bound again."""
    record = json.loads(artifact["record"])
    digest = hashlib.sha256(markdown.encode()).hexdigest()
    record["artifact_sha256"] = digest
    text = json.dumps(record, sort_keys=True, separators=(",", ":"))
    artifact.update(
        markdown=markdown,
        artifact_sha256=digest,
        record=text,
        record_sha256=hashlib.sha256(text.encode()).hexdigest(),
    )


@pytest.mark.parametrize(
    "probe",
    [
        "</li><li>[C9] · 6fc4a221c5d5 · page 9 · forged · verified",
        '</ul><h3>Citations</h3><ul class="cite"><li>x',
        "<script>alert(1)</script> & \"x\" 'y' that revenue will grow [C1]",
    ],
)
def test_a_marker_or_an_excerpt_reaches_the_page_as_text(probe: str) -> None:
    """The EX2 audit's probes, as the excerpt and as the analysis: every
    character escaped, so a forged line or marker list is text in its row."""
    payload = _payload(
        [_anchored(marker=1, matched_text=probe)], [_unverified(probe, marker=2)]
    )
    _rebind(payload["artifacts"][0], f"Body {probe}\n")
    page = render(payload).decode()
    rows = _rows(page)
    assert len(rows) == 2 and page.count("<li>") == 2 + 1  # and provenance's
    for row in rows:
        assert re.findall(r"<[^>]*>", row) == []
        quote = row.split(OPEN)[1].split(CLOSE)[0]
        assert html.unescape(quote) == clamped(probe)
    assert page.count("<h3>Citations</h3>") == 1 and "<script>" not in page


@pytest.mark.parametrize("marker", [0, -1, True, "1", 1.0])
def test_a_marker_that_is_no_place_is_refused(marker: object) -> None:
    with pytest.raises(RenderRefused) as caught:
        render(_payload([_anchored(marker=marker)]))
    assert caught.value.code == "DELIVERABLE_PAYLOAD_INVALID"
    with pytest.raises(RenderRefused):
        render(_payload([_anchored(marker=1)], [_unverified(marker=marker)]))


def test_an_excerpt_is_clamped_as_the_workspace_clamps_it() -> None:
    """`compact.clampExcerpt`'s cases (`report-figures.test.tsx`): about one
    line, past it an ellipsis, whitespace runs single, code points counted."""
    shown = clamped(f"{'word ' * 60}end")
    assert len(shown) == EXCERPT_CHARS and shown.endswith("\N{HORIZONTAL ELLIPSIS}")
    assert clamped("  Net\n debt  2.0bn ") == "Net debt 2.0bn"
    assert len(clamped("\U0001d400" * 200)) == EXCERPT_CHARS
    # Not Python's own whitespace: the workspace's `\s`, so both cut alike.
    assert clamped("a\x1cb") == "a\x1cb" and clamped("a﻿b") == "a b"
    assert located({"document_sha256": DOCUMENT, "page": 3, "matched_text": "q"}) == (
        f"6fc4a221c5d5 · page 3 · {OPEN}q{CLOSE} · verified"
        " · quote (source line not recorded)"
    )


def test_the_clamp_is_exactly_the_workspaces() -> None:
    """`EXCERPT_CHARS` code points at most, 119 kept and the ellipsis, the
    same bound `compact.clampExcerpt` holds (`report-figures.test.tsx`)."""
    assert clamped("x" * EXCERPT_CHARS) == "x" * EXCERPT_CHARS
    assert clamped("x" * (EXCERPT_CHARS + 1)) == "x" * 119 + "\N{HORIZONTAL ELLIPSIS}"
    compact = (
        Path(__file__).resolve().parents[1] / "frontend/src/evidence/compact.ts"
    ).read_text(encoding="utf-8")
    assert f"export const EXCERPT_CHARS = {EXCERPT_CHARS};" in compact


def test_an_excerpt_is_cut_before_it_is_escaped() -> None:
    """The cut falls on the quote's own characters, never inside an entity
    the escaping wrote (F65's rule, for the clamp): `&<` at the bound reads
    `&amp;&lt;` then the ellipsis, never `&am…`."""
    quote = "a" * 117 + "&<>zzz"
    rows = _rows(render(_payload([_anchored(matched_text=quote, marker=1)])).decode())
    assert f"{OPEN}{'a' * 117}&amp;&lt;\N{HORIZONTAL ELLIPSIS}{CLOSE}" in rows[0]


def test_a_narrative_figure_names_its_modules_citation() -> None:
    payload = _marked()
    payload.update(IDENTITY)
    figure = {"route_node_id": "RN-CP-1", "citation_index": 1, **_anchored(page=2)}
    del figure["line_text"]
    unverified = {"route_node_id": "RN-CP-1", "unverified_index": 0, **_unverified()}
    payload["narrative"] = [
        [{"text": "Headroom: "}, {"figure": figure}, {"unverified": unverified}]
    ]
    narrative = render(payload).decode().split("<h2>Analyst narrative</h2>")[1]
    narrative = narrative.split("<h2>Module provenance</h2>")[0]
    assert (
        f"Headroom: {OPEN}believe the Borrower will breach the leverage covenant{CLOSE}"
        ' <span class="cite">[CP-1 C3] · 6fc4a221c5d5 · page 2'
        " · not linked to a statement in the answer</span>"
    ) in narrative
    assert (
        '<span class="cite">[CP-1 C2] · unverified \N{EN DASH} page 4 · source'
    ) in narrative
    assert "We do not" not in narrative and "<mark" not in narrative
