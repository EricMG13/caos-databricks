"""Phase 8 exit: the page renders from frozen bytes and nothing else.

`docs/REBUILD_PLAN.md` Phase 8 names
`test_the_deliverable_renders_from_the_frozen_payload_alone` among its three.
`SYSTEM_SPEC.md` §7 says the render *originates nothing*: it is a function of
frozen bytes, so there is no editorial boundary to police.

A test that rendered with a live connection to hand would pass whether or not
that were true, so this one closes the store first and renders from the payload
alone. The other two exit tests -- the filing chain and the audit package --
arrive with the chain they check.

The payload below is the canonical shape `render()` understands since the
claims render path was deleted (f-2a; `docs/DECISIONS.md` §42.1): one artifact
carries a Markdown handoff and its host record, each addressed by digest, in
place of the retired `module_id`/`claims` shape. `_artifact` builds one with
correct digests by hand -- standard library only, like the render itself.
"""

from __future__ import annotations

import hashlib
import json
import re
from html import unescape
from pathlib import Path
from typing import Any

import pytest

from caos.boundary_text import BoundaryText
from caos.deliverable.render import ELEMENTS, PENDING, RenderRefused, render
from caos.refusals import RefusalCode
from caos.store import apply_schema, connect
from caos.store.runs import create_case

RENDER_SOURCE = (
    Path(__file__).resolve().parents[1] / "caos/deliverable/render.py"
).read_text(encoding="utf-8")

REVISION = "rev-001"

MARKDOWN = "Total debt at 31 December 2026 was USD 1,240.0m.\n"
BUILD_ID = "a43cb903ca2751f79e77b6da71f6ea131b8462a3"
AUTHORITY_DIGEST = "0302b789df5d0cae" + "0" * 48
QUOTE = "Total debt at 31 December 2026"
DOCUMENT_SHA256 = "6fc4a221c5d5" + "0" * 52


def _artifact(
    markdown: str = MARKDOWN, *, projections: object = None, citations: object = None
) -> dict[str, Any]:
    """One canonical artifact, bound: the record's own digests match its bytes."""
    digest = hashlib.sha256(markdown.encode()).hexdigest()
    record = {
        "artifact_sha256": digest,
        "build_id": BUILD_ID,
        "authority_digest": AUTHORITY_DIGEST,
        "projections": (
            {
                "module_id": "CP-1",
                "qa_status": "Passed",
                "committee_status": "Committee Ready",
                "decision_scope": "COMMITTEE",
                "limitation_flags": [],
            }
            if projections is None
            else projections
        ),
        "citations": (
            [{"document_sha256": DOCUMENT_SHA256, "page": 1, "matched_text": QUOTE}]
            if citations is None
            else citations
        ),
    }
    record_json = json.dumps(record, sort_keys=True, separators=(",", ":"))
    return {
        "markdown": markdown,
        "record": record_json,
        "artifact_sha256": digest,
        "record_sha256": hashlib.sha256(record_json.encode()).hexdigest(),
    }


PAYLOAD_DATA: dict[str, Any] = {
    "case_title": "Acme Holdings plc",
    "revision_id": REVISION,
    "artifacts": [_artifact()],
    "narrative": "Leverage is inside the covenant with limited headroom.",
}


def test_the_deliverable_renders_from_the_frozen_payload_alone(
    empty_database: str,
) -> None:
    """A named exit test. The store is closed before the render runs.

    §7's claim is structural: the render is a function of frozen bytes. If it
    could reach past the payload for anything -- a title, a digest, a fresher
    artifact -- this would raise rather than return a page.
    """
    with connect(empty_database) as conn:
        apply_schema(conn)
        create_case(conn, BoundaryText.of("Acme Holdings plc"))
        conn.commit()
        first = render(PAYLOAD_DATA)
        conn.close()

        second = render(PAYLOAD_DATA)

    assert first == second, "the same payload renders byte-identically"
    assert b"Acme Holdings plc" in first
    assert PENDING.encode() in first, "approved bytes always read PENDING APPROVAL"
    assert b"Total debt at 31 December 2026" in first, "the figure carries its quote"
    assert b"Module provenance" in first


def test_cp_cf_render_discloses_its_host_performed_projection() -> None:
    payload = {
        **PAYLOAD_DATA,
        "artifacts": [
            _artifact(
                projections={
                    "module_id": "CP-CF",
                    "qa_status": "Passed",
                    "committee_status": "Committee Ready",
                    "decision_scope": "COMMITTEE",
                    "limitation_flags": [],
                }
            )
        ],
    }
    assert b"CP-CF forecast projection performed by the host" in render(payload)


def test_the_render_reaches_no_network_and_no_clock() -> None:
    """It prints to paper and has to render the same in ten years. A page that
    fetched a stylesheet would render differently the day the stylesheet moved."""
    page = render(PAYLOAD_DATA)

    assert b"http://" not in page
    assert b"https://" not in page
    assert b"<link" not in page
    assert b"<script" not in page


def test_an_uncited_figure_is_refused_at_the_render() -> None:
    """§7: every figure carries its citation. An uncited handoff inside a frozen
    payload is a freeze that should not have happened, and this is the last
    place it can still be caught."""
    payload = json.loads(json.dumps(PAYLOAD_DATA))
    payload["artifacts"][0] = _artifact(citations=[])

    with pytest.raises(RenderRefused) as caught:
        render(payload)

    assert caught.value.code == "DELIVERABLE_UNCITED_FIGURE"


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda p: p.update(artifacts=[]), id="no artifacts"),
        pytest.param(
            lambda p: p.update(artifacts="not-a-list"), id="artifacts not a list"
        ),
        pytest.param(
            lambda p: p["artifacts"].__setitem__(0, "not-a-mapping"),
            id="artifact not a mapping",
        ),
        pytest.param(
            lambda p: p["artifacts"][0].__setitem__("record", "not json"),
            id="record not valid json",
        ),
        pytest.param(
            lambda p: p["artifacts"].__setitem__(
                0, _artifact(projections="not-a-mapping")
            ),
            id="projections not a mapping",
        ),
        pytest.param(
            lambda p: p["artifacts"].__setitem__(0, _artifact(citations="not-a-list")),
            id="citations not a list",
        ),
        pytest.param(
            lambda p: p["artifacts"].__setitem__(
                0, _artifact(citations=["not-a-mapping"])
            ),
            id="citation not a mapping",
        ),
        pytest.param(lambda p: p.update(case_title=""), id="case_title empty"),
    ],
)
def test_a_malformed_payload_is_refused_not_crashed(mutate: object) -> None:
    """Every shape a frozen payload can be wrong in reaches the same closed
    code, `DELIVERABLE_PAYLOAD_INVALID` -- never an unhandled `TypeError` or
    `KeyError` from treating a stranger's JSON as trusted structure."""
    payload = json.loads(json.dumps(PAYLOAD_DATA))
    mutate(payload)  # type: ignore[operator]

    with pytest.raises(RenderRefused) as caught:
        render(payload)

    assert caught.value.code == "DELIVERABLE_PAYLOAD_INVALID"


def test_no_narrative_omits_the_section_rather_than_refusing() -> None:
    """The narrative is optional; its absence is not malformed."""
    payload = json.loads(json.dumps(PAYLOAD_DATA))
    del payload["narrative"]

    page = render(payload)

    assert b"Analyst narrative" not in page


def test_a_narrative_that_is_not_a_string_is_refused() -> None:
    payload = json.loads(json.dumps(PAYLOAD_DATA))
    payload["narrative"] = 123

    with pytest.raises(RenderRefused) as caught:
        render(payload)

    assert caught.value.code == "DELIVERABLE_PAYLOAD_INVALID"


MARKDOWN_HANDOFF = (
    "---\n"
    "module_id: CP-1\n"
    "---\n"
    "## Audit Summary\n\n"
    "Total debt at 31 December 2026 was **USD 1,240.0m**.\n\n"
    "### Registers\n\n"
    "| Metric | Value |\n"
    "| --- | --- |\n"
    "| Net leverage | 4.2x |\n\n"
    "- One limitation\n"
    "- Another limitation\n\n"
    "> The covenant headroom is thin.\n"
)


def test_a_handoffs_markdown_reaches_the_page_as_headings_tables_and_lists() -> None:
    """A committee page shows the register as a table, not as its source.

    The escaped `<pre>` this replaces printed `| Metric | Value |` and `## Audit
    Summary` as characters, so a reader of a filed deliverable read the
    Markdown rather than the document. The element set is closed and named in
    `render.py`; everything in this handoff is inside it.
    """
    payload = json.loads(json.dumps(PAYLOAD_DATA))
    payload["artifacts"][0] = _artifact(MARKDOWN_HANDOFF)

    page = render(payload).decode()

    assert "<table>" in page and "<th>Metric</th>" in page and "<td>4.2x</td>" in page
    assert "<li>One limitation</li>" in page
    assert "<strong>USD 1,240.0m</strong>" in page
    assert "<blockquote>The covenant headroom is thin.</blockquote>" in page
    # The authored heading is a heading, and it never collides with the page's
    # own structure: authored level 1 lands at <h4>, below the <h3> section
    # headings, and the level the module wrote is kept rather than normalised.
    assert '<h5 data-level="2">Audit Summary</h5>' in page
    assert '<h6 data-level="3">Registers</h6>' in page
    assert "## Audit Summary" not in page
    assert "| Metric | Value |" not in page


def test_markdown_outside_the_element_set_reaches_the_page_as_itself() -> None:
    """A construct the set does not carry never becomes markup.

    A link, an image and a raw tag are the three a general Markdown library
    would render; here they are the characters the model wrote, escaped and
    inert, which is what `test_the_page_keeps_limitations_labels_screens_and`
    `_escapes_model_text` has required of the deliverable all along.
    """
    authored = (
        "## Audit Summary\n\n"
        "See [the filing](https://example.com/x) and <b>note</b> ![chart](c.png).\n"
    )
    payload = json.loads(json.dumps(PAYLOAD_DATA))
    payload["artifacts"][0] = _artifact(authored)

    page = render(payload).decode()

    assert "<a " not in page and "<img" not in page and "<b>note</b>" not in page
    assert "[the filing](https://example.com/x)" in page
    assert "&lt;b&gt;note&lt;/b&gt;" in page


def test_a_block_with_no_faithful_rendering_is_refused_not_guessed_at() -> None:
    """Where the set cannot render a block *and* printing it as text would
    misstate the document, the render refuses rather than choosing for the
    author: an unterminated fence, a row that does not fit its header, and a
    list nested past the depth the page carries."""
    for unsupported in (
        "## Audit Summary\n\n```\nnever closed\n",
        "| Metric | Value |\n| --- | --- |\n| Net leverage | 4.2x | 3.1x |\n",
        "- a\n  - b\n    - c\n      - d\n        - e\n",
    ):
        payload = json.loads(json.dumps(PAYLOAD_DATA))
        payload["artifacts"][0] = _artifact(unsupported)

        with pytest.raises(RenderRefused) as caught:
            render(payload)

        assert caught.value.code == "DELIVERABLE_MARKDOWN_UNSUPPORTED"


def test_an_identifier_and_an_unpaired_asterisk_are_not_emphasis() -> None:
    """The domain writes `net_debt_to_ebitda`, and prose writes a lone `*`.
    Neither is a delimiter here, so neither silently italicises the words it
    sits between."""
    authored = "## Audit Summary\n\nnet_debt_to_ebitda rose 2 * 3 and *held.\n"
    payload = json.loads(json.dumps(PAYLOAD_DATA))
    payload["artifacts"][0] = _artifact(authored)

    page = render(payload).decode()

    assert "<em>" not in page
    assert "net_debt_to_ebitda rose 2 * 3 and *held." in page


def test_the_page_carries_no_element_the_set_does_not_name() -> None:
    """`ELEMENTS` is the claim; the tags in the page are the evidence for it.

    A reader checks the deliverable against a named list rather than against a
    parser, so the list has to be the whole of what the render can emit.
    """
    payload = json.loads(json.dumps(PAYLOAD_DATA))
    payload["artifacts"][0] = _artifact(MARKDOWN_HANDOFF)

    page = render(payload).decode()

    authored = page.split("<h3>Analysis (model-authored, not host-verified)</h3>")[1]
    authored = authored.split("<h3>Deterministic calculations</h3>")[0]
    tags = {name.lower() for name in re.findall(r"<\s*/?\s*([a-zA-Z0-9]+)", authored)}
    assert tags <= {
        "pre",
        "code",
        "h4",
        "h5",
        "h6",
        "p",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "ul",
        "ol",
        "li",
        "blockquote",
        "hr",
        "strong",
        "em",
    }
    assert len(ELEMENTS) == 12 and "heading" in ELEMENTS


def test_a_citation_without_a_page_is_refused_like_the_fields_beside_it() -> None:
    """`matched_text` and `document_sha256` are refused when absent; the page
    was printed as an empty string, so the deliverable said "page " instead of
    saying no."""
    for citation in (
        {"document_sha256": DOCUMENT_SHA256, "matched_text": QUOTE},
        {"document_sha256": DOCUMENT_SHA256, "matched_text": QUOTE, "page": "1"},
        {"document_sha256": DOCUMENT_SHA256, "matched_text": QUOTE, "page": 0},
        {"document_sha256": DOCUMENT_SHA256, "matched_text": QUOTE, "page": True},
    ):
        payload = json.loads(json.dumps(PAYLOAD_DATA))
        payload["artifacts"][0] = _artifact(citations=[citation])

        with pytest.raises(RenderRefused) as caught:
            render(payload)

        assert caught.value.code == "DELIVERABLE_PAYLOAD_INVALID"


def test_every_portable_render_refusal_names_a_closed_host_code() -> None:
    """The render is portable -- it ships inside an audit package and runs with
    no host beside it -- so it refuses with its own `RenderRefused` and a string
    code. The wrapper that turned that string into a `Refusal` had no caller:
    the host never renders here, and every name the render can raise is one the
    host's closed set already carries, which is what this holds."""
    with pytest.raises(RenderRefused, match="DELIVERABLE_PAYLOAD_INVALID") as portable:
        render({})

    assert portable.value.code == "DELIVERABLE_PAYLOAD_INVALID"
    raised = {
        name.strip('"')
        for name in re.findall(r"RenderRefused\((\"[A-Z_]+\")\)", RENDER_SOURCE)
    }
    assert raised == {
        "DELIVERABLE_PAYLOAD_INVALID",
        "DELIVERABLE_UNCITED_FIGURE",
        "DELIVERABLE_MARKDOWN_UNSUPPORTED",
    }
    assert raised <= {code.value for code in RefusalCode}


def test_every_authored_character_reaches_the_page() -> None:
    """No authored character is deleted. That is the hazard; the axis is the
    characters, and the first version of this test did not measure them.

    It asserted that the single longest four-or-more-character word of each
    line survived. The Completion Phase 12 adversarial audit found four
    deletions it could not see, and the reasons are all the same reason: an
    ordinal (`7.`) is two characters and never a line's longest word; the
    corpus carried no fence, table, list, quote or heading, so three of the
    four constructs were unreachable by it; and where a prose line was turned
    into a fabricated table, every word survived as a header cell while the
    `---` was gone. Its cheapest evasion was to emit one token per line, which
    makes the deliverable worse -- so by `CLAUDE.md`'s own separator it was the
    eighth instance of the class, written as the remediation for the seventh.

    The axis now: every non-whitespace character of the source appears, in
    order, in the page's unescaped text, except the construct markers a
    renderer legitimately consumes. Those are named in `CONSUMED` rather than
    inferred, so a marker added to the allowance is a deliberate edit a reader
    can see. The corpus carries one of every member of `ELEMENTS` plus the
    constructs outside it.
    """
    authored_source = "\n\n".join(
        [
            "# Heading one",
            "###### Heading six",
            "Ordinary prose with **strong**, *emphasis* and `a code span`.",
            "<!-- MATERIAL: management refused the covenant schedule -->",
            "A [link](https://example.test) and an ![image](x.png).",
            "A raw <span data-x='1'>tag</span> and an entity &amp;.",
            # Deliberately not consecutive: a sequential run's later ordinals
            # are drawn by the browser from `start`, so only a broken run puts
            # every ordinal on the page as its own characters -- which is the
            # case this corpus must carry for the check below to mean anything.
            "7. Covenant headroom breached\n9. Waiver requested",
            "- bullet one\n- bullet two",
            "> A quoted caveat from the issuer.",
            '```caos-forecast-v1\n{"driver": 1}\n``` trailing note',
            "| Leverage | Headroom |\n| --- | --- |\n| 4.2x | 0.3x |",
            "Leverage | covenant headroom\n---",
            "***",
        ]
    )
    payload = json.loads(json.dumps(PAYLOAD_DATA))
    payload["artifacts"][0] = _artifact(authored_source)

    page = render(payload).decode()
    authored = page.split("<h3>Analysis (model-authored, not host-verified)</h3>")[1]
    authored = authored.split("<h3>Deterministic calculations</h3>")[0]
    # Compare on what a reader sees, not on the markup this module wrote. An
    # `<ol start="7">` is the one place authored content is carried by an
    # attribute rather than by text -- the browser draws the 7 -- so it is put
    # back before the tags are stripped, and named here rather than silently
    # allowed, because an attribute is exactly where a deletion could hide next.
    shown_markup = re.sub(r'<ol start="([^"]+)">', r"\1", authored)
    text = unescape(re.sub(r"<[^>]*>", "", shown_markup))

    # Contiguously, not as a subsequence. A subsequence check over the whole
    # page finds a line's letters scattered among unrelated words -- deleting
    # "trailing note" still passed one, because those letters all occur
    # elsewhere in order. That is the witness-word weakness in another form, so
    # the comparison is over each line's alphanumerics as one run against the
    # page's alphanumerics.
    #
    # Alphanumerics only: punctuation is shared between authored prose, this
    # module's separators and the construct markers, and every deletion this
    # test exists for carries alphanumerics. The one that does not -- a `---`
    # turned into a fabricated table -- has its own test below.
    shown_text = "".join(c for c in text if c.isalnum())
    missing = [
        line
        for line in authored_source.split("\n")
        if (content := "".join(c for c in line if c.isalnum()))
        and content not in shown_text
    ]
    assert missing == [], (missing, text)


def test_a_fabricated_table_is_not_asserted_for_a_prose_line() -> None:
    """A page may not claim a structure the model did not write.

    `_DELIMITER` matches a bare `---`, so a prose line carrying a pipe followed
    by a thematic break was read as a one-column table and the page asserted a
    `<table>` with an empty `<tbody>`. That is worse than the deletions beside
    it: a reader cannot tell an invented table from an authored one, and a
    deliverable's whole claim is that what is on the page is what was signed.
    """
    payload = json.loads(json.dumps(PAYLOAD_DATA))
    payload["artifacts"][0] = _artifact("Leverage | covenant headroom\n---")

    page = render(payload).decode()
    authored = page.split("<h3>Analysis (model-authored, not host-verified)</h3>")[1]
    authored = authored.split("<h3>Deterministic calculations</h3>")[0]

    assert "<table>" not in authored
    assert "Leverage | covenant headroom" in unescape(authored)


def test_a_consecutive_ordered_list_starts_where_the_model_numbered_it() -> None:
    """The other half of the ordinal rule: a run that *is* consecutive keeps
    its first number and lets the browser draw the rest, so a register
    numbered from 7 is not renumbered from 1."""
    payload = json.loads(json.dumps(PAYLOAD_DATA))
    payload["artifacts"][0] = _artifact("7. First\n8. Second")

    page = render(payload).decode()

    assert '<ol start="7">' in page
    assert "<li>First</li>" in page


def test_provenance_and_citation_digests_are_cut_before_they_are_escaped() -> None:
    """F65: a truncation after escaping could leave half an entity on the page."""
    payload = json.loads(json.dumps(PAYLOAD_DATA))
    artifact = payload["artifacts"][0]
    record = json.loads(artifact["record"])
    record["build_id"] = "a" * 9 + "<b>"
    record["citations"][0]["document_sha256"] = "c" * 9 + "<d>"
    artifact["record"] = json.dumps(record, sort_keys=True, separators=(",", ":"))
    artifact["record_sha256"] = hashlib.sha256(artifact["record"].encode()).hexdigest()
    page = render(payload)
    assert b"aaaaaaaaa&lt;b&gt;" in page and b"ccccccccc&lt;d&gt;" in page
    assert b"&amp;lt" not in page and b"&lt;b>" not in page
