"""The deliverable: one HTML file, and a render that originates nothing.

The host renders from the frozen snapshot -- the accepted artifacts in route
order, every figure carrying its citation, then the analyst's narrative and
the module provenance index.

The structural claim is the one worth protecting: *the render is a function of
frozen bytes*. It takes a payload and returns a page. It has no store, no
connection and no clock, so there is no editorial boundary to police -- nothing
here can reach past the payload to fetch something newer, prettier or different.
That is what `test_the_deliverable_renders_from_the_frozen_payload_alone`
enforces by rendering with the store closed.

The consequence is deliberate: both sides of an unresolved conflict, `Restricted`
and `SCREENING_ONLY` qualifications reach the page exactly as the artifacts carry
them. A render that tidied them would be originating an opinion.

It prints to paper. No PDF, deck, dashboard or workbook, and no network: a page
that fetched a stylesheet would render differently the day the stylesheet moved,
and this file has to render the same in ten years.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from html import escape
from typing import Any

# Every approved copy says so on its face. The bytes that carry an opinion are
# not the bytes that carry a filing.
PENDING = "PENDING APPROVAL"
# A pathway scope that is a screen, never committee clearance (`handoff.py`).
SCREENING_ONLY = "SCREENING_ONLY"


class RenderRefused(ValueError):
    """A portable render refusal; the host maps its code at its boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def render(payload: Mapping[str, Any]) -> bytes:
    """The frozen payload as one self-contained HTML file.

    Pure: no I/O, no clock, no randomness. The same payload renders
    byte-identically, which is what makes the audit package's re-render a check
    rather than a second opinion.
    """
    case = _text(payload, "case_title")
    revision = _text(payload, "revision_id")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise RenderRefused("DELIVERABLE_PAYLOAD_INVALID")

    # A canonical artifact's page facts come from its record (§41).
    views = [_canonical(artifact) for artifact in artifacts]
    body = "\n".join(_handoff(view) for view in views)
    narrative = _narrative(payload.get("narrative"))
    provenance = _provenance([view.provenance for view in views])

    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{escape(case)} — {escape(revision)}</title>\n"
        # Inline, and print-first. A page that fetched a stylesheet would render
        # differently the day that stylesheet moved.
        "<style>\n"
        "body{font:11pt/1.45 Georgia,serif;max-width:44em;margin:2em auto;color:#111}\n"
        "h1,h2{font-weight:600;line-height:1.2}\n"
        ".status{border:1px solid #111;padding:.4em .8em;display:inline-block}\n"
        "blockquote{border-left:3px solid #999;margin:.6em 0;\n"
        "padding:.2em 1em;color:#333}\n"
        ".cite{font-size:9pt;color:#555}\n"
        "pre{white-space:pre-wrap;font:9pt/1.35 Menlo,monospace}\n"
        "table{border-collapse:collapse;width:100%;font-size:9.5pt}\n"
        "th,td{border:1px solid #bbb;padding:.25em .5em;text-align:left;\n"
        "vertical-align:top}\n"
        "h4,h5,h6{font-weight:600;line-height:1.25;margin:1em 0 .3em}\n"
        "@media print{body{margin:0;max-width:none}}\n"
        "</style>\n</head>\n<body>\n"
        f"<h1>{escape(case)}</h1>\n"
        f'<p class="status">{escape(PENDING)}</p>\n'
        f"<p>Revision {escape(revision)}</p>\n"
        f"{body}\n"
        f"{narrative}"
        f"{provenance}"
        "</body>\n</html>\n"
    ).encode()


class _Handoff:
    """One canonical artifact as the page shows it, read from its record."""

    __slots__ = ("citations", "markdown", "projections", "provenance")

    def __init__(self, markdown: str, record: Mapping[str, Any]) -> None:
        self.markdown = markdown
        projections = record.get("projections")
        citations = record.get("citations")
        if not isinstance(projections, Mapping) or not isinstance(citations, list):
            raise RenderRefused("DELIVERABLE_PAYLOAD_INVALID")
        self.projections = projections
        self.citations = citations
        self.provenance = {
            "module_id": _text(projections, "module_id"),
            "build_id": _text(record, "build_id"),
            "authority_digest": _text(record, "authority_digest"),
        }


def canonical_bound(artifact: Mapping[str, Any]) -> bool:
    """Whether the Markdown and record text hash to the pair the payload binds,
    and the record names that Markdown. Standard library only, like the package.
    """
    if not isinstance(artifact, Mapping):
        return False
    markdown, record = artifact.get("markdown"), artifact.get("record")
    if not isinstance(markdown, str) or not isinstance(record, str):
        return False
    try:
        document = json.loads(record)
    except ValueError:
        return False
    digest = artifact.get("artifact_sha256")
    return (
        hashlib.sha256(markdown.encode("utf-8")).hexdigest() == digest
        and hashlib.sha256(record.encode("utf-8")).hexdigest()
        == artifact.get("record_sha256")
        and isinstance(document, dict)
        and document.get("artifact_sha256") == digest
    )


def _canonical(artifact: Mapping[str, Any]) -> _Handoff:
    if not canonical_bound(artifact):
        raise RenderRefused("DELIVERABLE_PAYLOAD_INVALID")
    return _Handoff(str(artifact["markdown"]), json.loads(str(artifact["record"])))


def _handoff(view: _Handoff) -> str:
    """The Markdown as text, never markup, beside what qualifies it.

    A `Restricted` handoff keeps its limitations on the page, and a
    `SCREENING_ONLY` scope is labelled a screen whatever committee status the
    module wrote: the vendor maps no status to that scope, so the page must.
    """
    facts = view.projections
    qa = escape(_text(facts, "qa_status"))
    committee = escape(_text(facts, "committee_status"))
    scope = _text(facts, "decision_scope")
    flags = facts.get("limitation_flags")
    if not isinstance(flags, list) or not all(isinstance(f, str) for f in flags):
        raise RenderRefused("DELIVERABLE_PAYLOAD_INVALID")
    if not view.citations:
        raise RenderRefused("DELIVERABLE_UNCITED_FIGURE")
    screen = (
        '<p class="status">SCREENING ONLY: a screen, not committee clearance</p>\n'
        if scope == SCREENING_ONLY
        else ""
    )
    limitations = (
        "<h3>Limitations</h3>\n<ul>\n"
        + "\n".join(f"<li>{escape(flag)}</li>" for flag in flags)
        + "\n</ul>\n"
        if flags
        else ""
    )
    return (
        f"<h2>{escape(view.provenance['module_id'])}</h2>\n"
        f'<p class="status">QA status: {qa}</p>\n'
        f"<p>Committee status as written: {committee} · "
        f"decision scope {escape(scope)}</p>\n"
        f"{screen}{limitations}"
        # §45.6: what the host verified, what the model wrote, what the host
        # computed -- in that order, never mixed.
        "<h3>Source facts (host-verified citations)</h3>\n"
        + "\n".join(_citation(citation) for citation in view.citations)
        + "\n<h3>Analysis (model-authored, not host-verified)</h3>\n"
        # The elements of `ELEMENTS`, every authored character escaped inside
        # them: committee layout, with nothing the model wrote reaching the
        # page as markup this file did not write.
        f"{_markdown(view.markdown)}"
        "<h3>Deterministic calculations</h3>\n"
        + (
            "<p>CP-CF forecast projection performed by the host.</p>\n"
            if _text(facts, "module_id") == "CP-CF"
            else "<p>None performed by the host on this route.</p>\n"
        )
    )


# The closed element set the handoff Markdown is rendered as. Nothing else
# becomes markup: a construct outside this list either reaches the page as the
# characters the model wrote -- which is what the `<pre>` before it did for the
# whole document, and what `test_the_page_keeps_limitations_labels_screens_and`
# `_escapes_model_text` has always required of raw HTML -- or, where the block
# is structurally incomplete and no faithful rendering of it exists, refuses.
# Named here so a reader checks the page against a list rather than a parser.
ELEMENTS = (
    "front matter",
    "heading",
    "paragraph",
    "table",
    "unordered list",
    "ordered list",
    "blockquote",
    "code block",
    "thematic break",
    "strong",
    "emphasis",
    "code span",
)
# Authored headings sit under the page's own <h3> section headings, so authored
# level 1 lands at <h4>; HTML stops at 6, and the level the module wrote is
# kept as an attribute rather than normalised away.
_HEADING_BASE = 3
_MAX_HEADING = 6
# ponytail: lists nest four deep. Deeper than that is refused rather than
# flattened, because a flattened list states a structure the module did not.
_MAX_NESTING = 4
# Possessive `\s++`: the trailing `(.*)$` can match anything up to the same
# newline-free end `\s+` would also match, so backtracking into the leading
# run is never needed for a real match -- only for the VM to search it, which
# is what made these super-linear on crafted whitespace. `++` closes that off.
_HEADING = re.compile(r"^(#{1,6})\s++(.*)$")
_UNORDERED = re.compile(r"^([-*+])\s++(.*)$")
_ORDERED = re.compile(r"^([0-9]{1,3}[.)])\s++(.*)$")
# A table's delimiter row. `_block` also requires it to contain a `|`, because
# this pattern matches a bare `---` -- so a prose line carrying a pipe followed
# by a thematic break used to be read as a one-column table, and the page then
# asserted a table with an empty body that the module never wrote. Fabrication
# is worse than the deletions beside it: a reader cannot tell it from a table
# the model authored.
_DELIMITER = re.compile(r"^\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?$")
# `*` and backticks only. `_` is left alone because identifiers carry it --
# `net_debt_to_ebitda` is a word in this domain, not two emphasis runs.
_INLINE = re.compile(r"(\*\*|\*|`)")


def _markdown(text: str) -> str:
    """The handoff Markdown as the elements named in `ELEMENTS`.

    Not a Markdown implementation: a closed reader for the constrained document
    the methodology bundle's own validators accept. Every authored character it
    emits is escaped, so no model-authored byte reaches the page as markup this
    file did not write.
    """
    lines = text.split("\n")
    out: list[str] = []
    index = 0
    if lines and lines[0].rstrip() == "---":
        index = _front_matter(lines, out)
    while index < len(lines):
        index = _block(lines, index, out)
    return "".join(out)


def _front_matter(lines: list[str], out: list[str]) -> int:
    """The host-owned front matter, shown as the data it is.

    It is not prose, and the page projects its fields above it; printed whole
    and unchanged it stays checkable against the record.
    """
    for end in range(1, len(lines)):
        if lines[end].rstrip() == "---":
            block = "\n".join(lines[1:end])
            out.append(f'<pre class="front">{escape(block)}</pre>\n')
            return end + 1
    raise RenderRefused("DELIVERABLE_MARKDOWN_UNSUPPORTED")


def _block(lines: list[str], index: int, out: list[str]) -> int:
    """One block from `index`, appended to `out`; returns the next index."""
    line = lines[index]
    if not line.strip():
        return index + 1
    if line.lstrip().startswith("<!--"):
        return _comment(lines, index, out)
    if line.startswith("```"):
        return _code(lines, index, out)
    if line.rstrip() in {"---", "***", "___"}:
        out.append("<hr>\n")
        return index + 1
    heading = _HEADING.match(line)
    if heading is not None:
        level = len(heading.group(1))
        tag = f"h{min(level + _HEADING_BASE, _MAX_HEADING)}"
        out.append(f'<{tag} data-level="{level}">{_inline(heading.group(2))}</{tag}>\n')
        return index + 1
    if line.lstrip().startswith(">"):
        return _quote(lines, index, out)
    if _item(line) is not None:
        return _list(lines, index, out)
    if (
        "|" in line
        and index + 1 < len(lines)
        and "|" in lines[index + 1]
        and _DELIMITER.match(lines[index + 1])
    ):
        return _table(lines, index, out)
    return _paragraph(lines, index, out)


def _comment(lines: list[str], index: int, out: list[str]) -> int:
    """An HTML comment reaches the page as the characters the model wrote.

    It used to be consumed and emit nothing, on the reasoning that a comment is
    "invisible in any reading of it". That is true of a Markdown renderer and
    false here. A signer's `payload_sha256` binds the record's bytes, and this
    is the only rendering of them a committee reads, so a construct that
    vanished took model-authored text out of the document the signature covers
    -- a MATERIAL caveat written as a comment would have been bound and unseen.
    Every other construct outside `ELEMENTS` reaches the page escaped; this one
    now does too, which is the rule this file already states.
    """
    for end in range(index, len(lines)):
        if "-->" in lines[end]:
            block = "\n".join(lines[index : end + 1])
            out.append(f"<pre>{escape(block)}</pre>\n")
            return end + 1
    raise RenderRefused("DELIVERABLE_MARKDOWN_UNSUPPORTED")


def _code(lines: list[str], index: int, out: list[str]) -> int:
    """A fenced block, with both fence lines' own text kept.

    The info string was discarded, and `caos-forecast-v1` is *the* label of the
    CP-CF forecast block -- so the first deliverable carrying one showed a
    committee an unlabelled JSON blob. Text after the closing fence was
    discarded too. Both are authored characters, and this module's contract is
    that authored characters reach the page or the block refuses.
    """
    info = lines[index][3:].strip()
    for end in range(index + 1, len(lines)):
        if lines[end].startswith("```"):
            block = "\n".join(lines[index + 1 : end])
            tail = lines[end][3:].strip()
            label = f'<p class="cite">{escape(info)}</p>\n' if info else ""
            after = f'<p class="cite">{escape(tail)}</p>\n' if tail else ""
            out.append(f"{label}<pre><code>{escape(block)}</code></pre>\n{after}")
            return end + 1
    raise RenderRefused("DELIVERABLE_MARKDOWN_UNSUPPORTED")


def _quote(lines: list[str], index: int, out: list[str]) -> int:
    quoted: list[str] = []
    while index < len(lines) and lines[index].lstrip().startswith(">"):
        quoted.append(lines[index].lstrip()[1:].strip())
        index += 1
    out.append(f"<blockquote>{_inline(' '.join(quoted))}</blockquote>\n")
    return index


def _item(line: str) -> tuple[int, bool, str, str] | None:
    """One list item as (indent, ordered, marker, text), or None otherwise.

    The marker is carried because an ordinal is a fact the model wrote: a
    register numbered 7, 8, 9 renumbered itself to 1, 2, 3 on the page, which
    is the deletion class §77.3 forbids, arrived at through a default rather
    than through a discard.
    """
    stripped = line.lstrip(" ")
    indent = len(line) - len(stripped)
    ordered = _ORDERED.match(stripped)
    if ordered is not None:
        return indent, True, ordered.group(1), ordered.group(2)
    unordered = _UNORDERED.match(stripped)
    if unordered is not None:
        return indent, False, unordered.group(1), unordered.group(2)
    return None


def _list(lines: list[str], index: int, out: list[str]) -> int:
    """A list, nested by indentation. Each level opens and closes in order, so
    the page never carries an element this function did not close."""
    levels: list[tuple[int, str]] = []
    # Per indent level, the marker a consecutive run would use next.
    expected: dict[int, str] = {}
    while index < len(lines):
        item = _item(lines[index])
        if item is None or not lines[index].strip():
            break
        indent, ordered, marker, text = item
        tag = "ol" if ordered else "ul"
        while levels and indent < levels[-1][0]:
            out.append(f"</{levels.pop()[1]}>\n")
        if not levels or indent > levels[-1][0]:
            if len(levels) == _MAX_NESTING:
                raise RenderRefused("DELIVERABLE_MARKDOWN_UNSUPPORTED")
            levels.append((indent, tag))
            start = ""
            if ordered:
                first = marker[:-1]
                start = f' start="{escape(first)}"' if first != "1" else ""
                expected[indent] = marker
            out.append(f"<{tag}{start}>\n")
        # An `<ol start="N">` numbers sequentially from N, so it draws the
        # ordinals the model wrote only while they *are* sequential. A register
        # numbered 7, 9 would be drawn 7, 8 -- a number on the page that nobody
        # authored, which is the fabrication class. Where the run is not
        # consecutive each marker is written as its own characters instead.
        prefix = ""
        if ordered and marker != expected.get(levels[-1][0]):
            prefix = f"{escape(marker)} "
        if ordered:
            head = marker[:-1]
            expected[levels[-1][0]] = (
                f"{int(head) + 1}{marker[-1]}" if head.isdigit() else ""
            )
        out.append(f"<li>{prefix}{_inline(text)}</li>\n")
        index += 1
    while levels:
        out.append(f"</{levels.pop()[1]}>\n")
    return index


def _table(lines: list[str], index: int, out: list[str]) -> int:
    header = _cells(lines[index])
    index += 2
    rows: list[str] = []
    while index < len(lines) and "|" in lines[index] and lines[index].strip():
        cells = _cells(lines[index])
        if len(cells) != len(header):
            # A row that does not fit its header has no faithful rendering:
            # padding it would invent a cell and dropping one would lose a fact.
            raise RenderRefused("DELIVERABLE_MARKDOWN_UNSUPPORTED")
        rows.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
        index += 1
    head = "".join(f"<th>{_inline(c)}</th>" for c in header)
    out.append(
        "<table>\n<thead><tr>"
        + head
        + "</tr></thead>\n<tbody>\n"
        + "\n".join(rows)
        + "\n</tbody>\n</table>\n"
    )
    return index


def _cells(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _paragraph(lines: list[str], index: int, out: list[str]) -> int:
    held: list[str] = []
    while index < len(lines) and lines[index].strip():
        line = lines[index]
        if held and (_HEADING.match(line) or _item(line) is not None):
            break
        if line.startswith("```") or line.lstrip().startswith("<!--"):
            break
        held.append(line.strip())
        index += 1
    out.append(f"<p>{_inline(' '.join(held))}</p>\n")
    return index


def _inline(text: str) -> str:
    """Strong, emphasis and code spans; every other character as itself.

    Nothing here builds an element from an attribute or a URL, so a link, an
    image or a tag in model-authored prose reaches the page escaped -- visible
    as what the model wrote, and inert. A delimiter is a delimiter only where
    Markdown's own flanking rule says so (`2 * 3` is arithmetic), and a run
    that never pairs makes the whole text literal rather than half-rendered.

    Two rules this function used to get wrong, found by the Completion Phase 12
    confidence review. **A code span's contents are literal**: `` `a*b*c` ``
    rendered as `<code>a<em>b</em>c</code>`, which dropped the two asterisks the
    model wrote from the page -- the same defect as deleting a comment, inside
    a construct `ELEMENTS` names and Markdown defines as literal. And
    **delimiters close in the order they opened**: `*a **b* c**` produced
    `<em>a <strong>b</em> c</strong>`, which is not well-formed. A delimiter
    that would close out of order is not a delimiter, which leaves its opener
    unpaired and makes the whole text literal -- the fallback this function
    already had.
    """
    pieces = _INLINE.split(text)
    marks: list[str] = []
    spans: list[str] = []
    for position, piece in enumerate(pieces):
        if position % 2 == 0:  # `re.split` alternates text and delimiter
            spans.append(escape(piece))
            continue
        if marks and marks[-1] == "`" and piece != "`":
            # Inside a code span nothing is a delimiter.
            spans.append(escape(piece))
            continue
        spans.append(_delimiter(piece, pieces, position, marks))
    return escape(text) if marks else "".join(spans)


def _delimiter(piece: str, pieces: list[str], position: int, marks: list[str]) -> str:
    """One delimiter as a tag or as itself, by what sits either side of it.

    A run closes only the innermost open delimiter (`marks[-1]`); one that
    matches an outer opener is written as itself, which leaves that opener
    unpaired and sends `_inline` to its literal fallback rather than emitting
    mis-nested tags.
    """
    tag = {"**": "strong", "*": "em", "`": "code"}[piece]
    before, after = pieces[position - 1], pieces[position + 1]
    if piece in marks:
        if marks[-1] != piece:
            return escape(piece)
        if tag == "code" or (before and not before[-1].isspace()):
            marks.pop()
            return f"</{tag}>"
        return escape(piece)
    if tag == "code" or (after and not after[0].isspace()):
        marks.append(piece)
        return f"<{tag}>"
    return escape(piece)


def _citation(citation: object) -> str:
    if not isinstance(citation, Mapping):
        raise RenderRefused("DELIVERABLE_PAYLOAD_INVALID")
    quote = escape(_text(citation, "matched_text"))
    document = escape(_text(citation, "document_sha256")[:12])  # cut, then escape
    page = _page(citation)
    return (
        f"<blockquote>{quote}</blockquote>\n"
        f'<p class="cite">{document} · page {page}</p>'
    )


def _page(citation: Mapping[str, Any]) -> str:
    """A citation's page, refused when absent -- as `matched_text` and
    `document_sha256` beside it already were. Printed as `page ` with nothing
    after it, an absent page read as a page the reader could go and check."""
    value = citation.get("page")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RenderRefused("DELIVERABLE_PAYLOAD_INVALID")
    return str(value)


def _narrative(narrative: object) -> str:
    if narrative is None or narrative == []:
        return ""
    # Historical payloads remain renderable; the save boundary accepts only spans.
    if isinstance(narrative, str):
        return f"<h2>Analyst narrative</h2>\n<p>{escape(narrative)}</p>\n"
    if not isinstance(narrative, list) or len(narrative) > 64:
        raise RenderRefused("DELIVERABLE_PAYLOAD_INVALID")
    paragraphs = []
    for paragraph in narrative:
        if not isinstance(paragraph, list) or not 1 <= len(paragraph) <= 64:
            raise RenderRefused("DELIVERABLE_PAYLOAD_INVALID")
        paragraphs.append(
            "<div>" + "".join(_span(span) for span in paragraph) + "</div>\n"
        )
    return "<h2>Analyst narrative</h2>\n" + "".join(paragraphs)


def _span(span: object) -> str:
    if isinstance(span, Mapping):
        if set(span) == {"text"} and isinstance(span["text"], str):
            return escape(span["text"])
        if set(span) == {"figure"}:
            return _citation(span["figure"])
    raise RenderRefused("DELIVERABLE_PAYLOAD_INVALID")


def _provenance(artifacts: Sequence[object]) -> str:
    """Which module produced what, under which build and authority.

    Not decoration: it is how a reader checks that the page in front of them came
    from the methodology the run was pinned to.
    """
    rows = "\n".join(
        f"<li>{escape(_text(artifact, 'module_id'))} · "
        f"build {escape(_text(artifact, 'build_id')[:12])} · "
        f"authority {escape(_text(artifact, 'authority_digest')[:12])}</li>"
        for artifact in artifacts
        if isinstance(artifact, Mapping)
    )
    return f"<h2>Module provenance</h2>\n<ul>\n{rows}\n</ul>\n"


def _text(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise RenderRefused("DELIVERABLE_PAYLOAD_INVALID")
    return value
