"""The closed provider transport and the host record beside the Markdown
(Phase 3 Task 3.1 c-1).

The Markdown is the authority; the record is a host-written attachment bound to
it by digest. Neither the transport nor the record tolerates a key, a type or a
byte the host did not declare, and every refusal carries only its code.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import (
    BUNDLE,
    CATALOG,
    CONTRACT,
    PINNED,
    VENDORED,
    skill,
    wire,
)
from canonical_fixtures import handoff_markdown as _markdown
from canonical_fixtures import identity as _identity

from caos.blobs import BlobStore
from caos.digest import canonical_json
from caos.evidence.citations import (
    ANY_RUN,
    EXCERPT,
    REANCHORING_RULES,
    WHOLE_LINE,
    WHOLE_LINE_AS_STORED,
    AnchoredCitation,
    Citation,
    Rect,
)
from caos.methodology import bundle as bundle_module
from caos.methodology.bundle import (
    MANIFEST_NAME,
    SKILLS_DIR,
    Bundle,
    assemble_authority,
    authority_digest,
    delivered_authority,
    delivered_authority_digest,
)
from caos.methodology.handoff import (
    MAX_CITATIONS,
    RECORD_FORMAT,
    CanonicalRecord,
    LineageRef,
    UpstreamRef,
    parse_response,
    read_record,
    record_bytes,
    stored_lineage,
    strict_json,
    validate_markdown,
)
from caos.methodology.invocation import record_authority_matches
from caos.refusals import Refusal, RefusalCode

SECRET = "Confidential covenant headroom 7.3x"
# Fixed, not uuid4(): it reaches parametrize ids, which pytest-xdist workers
# must collect identically.
SOURCE = UUID("6da212c6-65a1-46b3-9e5c-7ed56acccd18")
CP0 = _identity("CP-0")
CP0_MD = _markdown(CP0, body_note="Recorded source p1 [C1]. " + SECRET)
QUOTE = "Recorded source p1"
CITED = json.dumps({"source_id": str(SOURCE), "page": 1, "matched_text": QUOTE})


def _citation(**changes: object) -> dict[str, object]:
    return {"source_id": str(SOURCE), "page": 1, "matched_text": QUOTE, **changes}


def _refused(call: Callable[[], object]) -> Refusal:
    with pytest.raises(Refusal) as refused:
        call()
    refusal = refused.value
    assert refusal.__cause__ is None and refusal.__context__ is None
    assert SECRET not in repr(refusal) and SECRET not in str(refusal)
    return refusal


def _parse_refused(body: str) -> RefusalCode:
    return _refused(lambda: parse_response(body)).code


def _linked(body: str) -> tuple[bool, ...]:
    """Whether a marker in the body names each citation (D107: one no marker
    names is flagged, not linked to a statement, never the answer's
    refusal)."""
    return parse_response(body)[2]


def test_a_closed_transport_yields_the_exact_markdown_and_its_citations() -> None:
    markdown, citations, linked = parse_response(wire(CP0_MD, [_citation()]))
    assert markdown == CP0_MD
    assert citations == (Citation(source_id=SOURCE, page=1, matched_text=QUOTE),)
    assert linked == (True,)


def test_claims_only_json_is_not_a_canonical_handoff() -> None:
    body = json.dumps({"claims": [{"statement": SECRET, "citations": [_citation()]}]})
    assert _parse_refused(body) is RefusalCode.HANDOFF_MALFORMED


@pytest.mark.parametrize(
    "body",
    [
        "not json " + SECRET,
        json.dumps([SECRET]),
        '{"canonical_markdown": "Recorded source p1", "canonical_markdown": "b",'
        f' "citations": [{CITED}]}}',
        json.dumps({"canonical_markdown": 7, "citations": [_citation()]}),
        json.dumps({"canonical_markdown": SECRET}),
        json.dumps(
            {"canonical_markdown": SECRET, "citations": [_citation()], "extra": 1}
        ),
        json.dumps({"canonical_markdown": SECRET, "citations": {}}),
        wire(CP0_MD, []),
        wire(CP0_MD, [_citation(page=True)]),
        wire(CP0_MD, [_citation(page=0)]),
        wire(CP0_MD, [_citation(page=1.0)]),
        wire(CP0_MD, [_citation(source_id="not-a-uuid")]),
        wire(CP0_MD, [_citation(source_id=7)]),
        wire(CP0_MD, [_citation(matched_text="")]),
        wire(CP0_MD, [_citation(matched_text="   ")]),
        wire(CP0_MD, [_citation(bbox=[0, 0, 1, 1])]),
        wire(CP0_MD, ["Recorded source p1"]),  # type: ignore[list-item]
        '{"canonical_markdown": "Recorded source p1", "citations": [{"source_id":'
        f' "{SOURCE}", "page": 1, "page": 2, "matched_text": "{QUOTE}"}}]}}',
        '{"canonical_markdown": "\\ud800 Recorded source p1",'
        f' "citations": [{CITED}]}}',
        '{"canonical_markdown": "Recorded source p1", "citations": [{"source_id":'
        f' "{SOURCE}", "page": NaN, "matched_text": "{QUOTE}"}}]}}',
    ],
)
def test_a_malformed_transport_refuses(body: str) -> None:
    assert _parse_refused(body) is RefusalCode.HANDOFF_MALFORMED


def test_a_citation_of_undelivered_evidence_is_left_to_anchoring() -> None:
    """D106: the transport no longer refuses a source the node was not
    given; anchoring keeps that citation as unverified."""
    other = uuid4()
    _markdown, citations, linked = parse_response(
        wire(CP0_MD, [_citation(source_id=str(other))])
    )
    assert citations[0].source_id == other and linked == (True,)


def test_a_citation_no_marker_names_is_not_linked() -> None:
    """D107: a citation no `[C<n>]` marker names is flagged, not linked to a
    statement, and never refuses the handoff."""
    body = wire(CP0_MD, [_citation(), _citation(matched_text="headroom 9.9x")])
    assert _linked(body) == (True, False)


def _record(**changes: object) -> CanonicalRecord:
    projections = validate_markdown(
        CONTRACT, CATALOG, skill("CP-0"), CP0_MD, identity=CP0, gate_expects=PINNED
    )
    values: dict[str, object] = {
        "artifact_sha256": hashlib.sha256(CP0_MD).hexdigest(),
        "adapter_version": "canonical-markdown-v3",
        "build_id": "build-1",
        "manifest_sha256": "a" * 64,
        "authority_bundle_sha256": CP0.authority_bundle_sha256,
        "authority_digest": "b" * 64,
        "delivered_authority_digest": "f" * 64,
        "identity": CP0,
        "lineage": (),
        "projections": projections,
        "citations": (
            AnchoredCitation(
                document_sha256="c" * 64,
                page=1,
                matched_text=QUOTE,
                bboxes=(Rect(page=1, x0=1.0, y0=2.5, x1=30.0, y1=12.25),),
            ),
        ),
    }
    values.update(changes)
    return CanonicalRecord(**values)  # type: ignore[arg-type]


def _stored(tmp_path: Path, record: CanonicalRecord) -> tuple[BlobStore, str, str]:
    blobs = BlobStore(tmp_path / "blobs")
    artifact = blobs.put(CP0_MD)
    return blobs, artifact, blobs.put(record_bytes(record))


@pytest.mark.parametrize(
    "field",
    [
        None,
        "adapter_version",
        "build_id",
        "manifest_sha256",
        "authority_digest",
        "delivered_authority_digest",
    ],
)
def test_record_authority_matches_only_this_build_and_pinned_module(
    field: str | None,
) -> None:
    """Invariant 4: the one check the executor, the runtime, the proof and the
    deliverable share. The module is the caller's (the pin's), never the
    record's."""
    this_build: dict[str, object] = {
        "build_id": BUNDLE.build_id,
        "manifest_sha256": BUNDLE.manifest_sha256,
        "authority_digest": authority_digest(assemble_authority(BUNDLE, "CP-0")),
        "delivered_authority_digest": delivered_authority_digest(
            delivered_authority(BUNDLE, "CP-0")
        ),
    }
    if field is not None:
        this_build[field] = "0" * 64
    record = _record(**this_build)
    matches = record_authority_matches(record, bundle=BUNDLE, module_id="CP-0")
    assert matches is (field is None)
    assert not record_authority_matches(record, bundle=BUNDLE, module_id="CP-L10")


def test_a_record_round_trips_exactly(tmp_path: Path) -> None:
    link = LineageRef("RN-01-CP-0", "CP-0", "d" * 64, "e" * 64)
    record = _record(lineage=(link,))
    blobs, artifact, sha = _stored(tmp_path, record)
    read = read_record(blobs, artifact_sha256=artifact, record_sha256=sha, expected=CP0)
    assert read == record
    assert record_bytes(read) == record_bytes(record)
    decoded = json.loads(record_bytes(record))
    assert decoded["format"] == RECORD_FORMAT
    assert record_bytes(record) == json.dumps(
        decoded, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def test_a_record_names_the_rule_its_citations_were_accepted_under(
    tmp_path: Path,
) -> None:
    """N28: a record accepted before the whole-line rule carries no rule and
    reads back as `ANY_RUN`, byte for byte as it was stored; one accepted
    under its first reading names `whole-line` (`WHOLE_LINE_AS_STORED`), and
    one accepted since `whole-line-as-shown` (`WHOLE_LINE`, W6). A record
    naming any other rule, or `ANY_RUN` aloud, is not one this host wrote."""
    old = _record()
    assert old.citation_rule == ANY_RUN
    assert "citation_rule" not in json.loads(record_bytes(old))
    first = _record(citation_rule=WHOLE_LINE_AS_STORED)
    assert json.loads(record_bytes(first))["citation_rule"] == "whole-line"
    new = _record(citation_rule=WHOLE_LINE)
    assert json.loads(record_bytes(new))["citation_rule"] == "whole-line-as-shown"
    for record in (old, first, new):
        blobs, artifact, sha = _stored(tmp_path, record)
        read = read_record(
            blobs, artifact_sha256=artifact, record_sha256=sha, expected=CP0
        )
        assert read == record
    for rule in (ANY_RUN, "prefix", 1):
        document = json.loads(record_bytes(new))
        document["citation_rule"] = rule
        sha = blobs.put(canonical_json(document).encode("utf-8"))
        _mismatch(blobs, artifact, sha, CP0)


def test_a_record_keeps_the_page_a_reanchored_citation_was_cited_on(
    tmp_path: Path,
) -> None:
    """D94: a citation the host re-anchored at its true page carries the page
    the module named as `cited_page`; one found where it was cited carries
    none, so every record written before reads back byte for byte. A stored
    `cited_page` that is null, not a page, or the page itself is not one this
    host wrote."""
    [found] = _record().citations
    assert "cited_page" not in json.loads(record_bytes(_record()))["citations"][0]
    moved = _record(
        citation_rule=WHOLE_LINE,
        citations=(dataclasses.replace(found, page=2, cited_page=7),),
    )
    [stored] = json.loads(record_bytes(moved))["citations"]
    assert (stored["page"], stored["cited_page"]) == (2, 7)
    blobs, artifact, sha = _stored(tmp_path, moved)
    read = read_record(blobs, artifact_sha256=artifact, record_sha256=sha, expected=CP0)
    assert read == moved and read.citations[0].cited_page == 7
    for value in (None, 2, 0, "7", 7.0, True):
        document = json.loads(record_bytes(moved))
        document["citations"][0]["cited_page"] = value
        sha = blobs.put(canonical_json(document).encode("utf-8"))
        _mismatch(blobs, artifact, sha, CP0)
    # Only the whole-line rule re-anchors: under any other a `cited_page` is
    # not this host's (M2).
    for rule in (ANY_RUN, WHOLE_LINE_AS_STORED):
        other = dataclasses.replace(moved, citation_rule=rule)
        _mismatch(blobs, artifact, blobs.put(record_bytes(other)), CP0)


def test_an_excerpt_record_keeps_the_line_of_each_citation(tmp_path: Path) -> None:
    """D105: a record accepted under `EXCERPT` names `excerpt-of-shown-line`
    and writes every citation's `line_text`, the whole line it anchored in,
    and reads back as written; a record under any earlier rule writes none,
    so every record stored before it is the same bytes, and holds None. A
    line missing from an excerpt record, empty, not a string, or held under
    another rule is not one this host wrote; an excerpt record re-anchors at
    its true page as a whole-line one does (D94)."""
    [found] = _record().citations
    line = f"{QUOTE} and the rest of its line"
    part = " ".join(line.split()[1:])
    excerpt = _record(
        citation_rule=EXCERPT,
        citations=(
            dataclasses.replace(found, matched_text=part, line_text=line, cited_page=7),
        ),
    )
    document = json.loads(record_bytes(excerpt))
    assert document["citation_rule"] == "excerpt-of-shown-line"
    assert document["citations"][0]["line_text"] == line
    for rule in (ANY_RUN, WHOLE_LINE_AS_STORED, WHOLE_LINE):
        older = json.loads(record_bytes(_record(citation_rule=rule)))
        assert "line_text" not in older["citations"][0]
    assert REANCHORING_RULES == {WHOLE_LINE, EXCERPT}
    blobs, artifact, sha = _stored(tmp_path, excerpt)
    read = read_record(blobs, artifact_sha256=artifact, record_sha256=sha, expected=CP0)
    assert read == excerpt and read.citations[0].line_text == line
    whole = dataclasses.replace(found, line_text=QUOTE)
    exact = _record(citation_rule=EXCERPT, citations=(whole,))
    assert json.loads(record_bytes(exact))["citations"][0]["line_text"] == QUOTE
    # Never written without its lines, nor with a line its quote cannot be
    # in (fix round 1): `record_bytes` fails closed.
    for odd in (
        _record(citation_rule=WHOLE_LINE, citations=(whole,)),
        _record(citation_rule=EXCERPT),
        _record(
            citation_rule=EXCERPT,
            citations=(dataclasses.replace(found, line_text="Unrelated text"),),
        ),
    ):
        with pytest.raises(ValueError):
            record_bytes(odd)
    for value in (None, "", 5, "Unrelated text"):
        document = json.loads(record_bytes(excerpt))
        document["citations"][0]["line_text"] = value
        _mismatch(blobs, artifact, blobs.put(canonical_json(document).encode()), CP0)
    document = json.loads(record_bytes(excerpt))
    del document["citations"][0]["line_text"]
    _mismatch(blobs, artifact, blobs.put(canonical_json(document).encode()), CP0)
    for rule in ("whole-line-as-shown", "whole-line"):
        document = json.loads(record_bytes(excerpt))
        document["citation_rule"] = rule
        del document["citations"][0]["cited_page"]
        _mismatch(blobs, artifact, blobs.put(canonical_json(document).encode()), CP0)


def _mismatch(blobs: BlobStore, artifact: str, sha: str, expected: object) -> None:
    refusal = _refused(
        lambda: read_record(
            blobs,
            artifact_sha256=artifact,
            record_sha256=sha,
            expected=expected,  # type: ignore[arg-type]
        )
    )
    assert refusal.code is RefusalCode.ARTIFACT_RECORD_MISMATCH


def test_a_changed_markdown_byte_breaks_the_record(tmp_path: Path) -> None:
    blobs, artifact, sha = _stored(tmp_path, _record())
    # A record naming other Markdown is not this artifact's record.
    other = blobs.put(CP0_MD + b"\n")
    _mismatch(blobs, other, sha, CP0)
    # The Markdown blob changed under its digest.
    blobs.path_of(artifact).write_bytes(CP0_MD.replace(b"p1", b"p2", 1))
    _mismatch(blobs, artifact, sha, CP0)


def test_a_changed_record_byte_breaks_the_record(tmp_path: Path) -> None:
    blobs, artifact, sha = _stored(tmp_path, _record())
    blobs.path_of(sha).write_bytes(record_bytes(_record(build_id="build-2")))
    _mismatch(blobs, artifact, sha, CP0)
    _mismatch(blobs, artifact, "d" * 64, CP0)


def test_a_record_naming_another_identity_refuses(tmp_path: Path) -> None:
    blobs, artifact, sha = _stored(tmp_path, _record())
    _mismatch(blobs, artifact, sha, dataclasses.replace(CP0, ordinal=2))
    _mismatch(blobs, artifact, sha, dataclasses.replace(CP0, issuer_name="Other"))


def _rewritten(edit: Callable[[dict[str, Any]], object]) -> bytes:
    decoded = json.loads(record_bytes(_record()))
    edit(decoded)
    # Canonical form, so the strict parser rather than the byte comparison is
    # what each variant meets.
    return json.dumps(
        decoded, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _set(path: tuple[str | int, ...], value: object) -> Callable[[Any], None]:
    def edit(decoded: Any) -> None:  # noqa: ANN401 -- a JSON tree
        target = decoded
        for step in path[:-1]:
            target = target[step]
        target[path[-1]] = value

    return edit


@pytest.mark.parametrize(
    "data",
    [
        b"not json",
        _rewritten(_set(("format",), "canonical-record-v0")),
        _rewritten(_set(("extra",), 1)),
        _rewritten(lambda d: d.pop("build_id")),
        _rewritten(_set(("identity", "ordinal"), True)),
        _rewritten(_set(("identity", "ordinal"), "1")),
        _rewritten(_set(("identity", "extra"), None)),
        _rewritten(_set(("projections", "confidence_score"), 90.0)),
        _rewritten(_set(("projections", "readiness"), [["CP-5"]])),
        _rewritten(_set(("citations",), [])),
        _rewritten(_set(("lineage",), [{"route_node_id": "RN-1"}])),
        _rewritten(_set(("lineage",), None)),
        _rewritten(_set(("citations", 0, "page"), False)),
        _rewritten(_set(("citations", 0, "bboxes", 0, "x0"), 1)),
        _rewritten(_set(("citations", 0, "bboxes", 0, "extra"), 1.0)),
        record_bytes(_record()).replace(
            b'{"adapter_version"', b'{"build_id":"x","adapter_version"', 1
        ),
    ],
)
def test_a_malformed_record_refuses(tmp_path: Path, data: bytes) -> None:
    blobs = BlobStore(tmp_path / "blobs")
    artifact = blobs.put(CP0_MD)
    _mismatch(blobs, artifact, blobs.put(data), CP0)


def test_the_record_carries_no_model_authored_claims() -> None:
    decoded = json.loads(record_bytes(_record()))
    assert set(decoded) == {
        "format",
        "artifact_sha256",
        "adapter_version",
        "build_id",
        "manifest_sha256",
        "authority_bundle_sha256",
        "authority_digest",
        "delivered_authority_digest",
        "identity",
        "lineage",
        "projections",
        "citations",
    }


@pytest.mark.parametrize(
    "citations",
    [[_citation(page=2**31)], [_citation(), _citation()]],
)
def test_an_unbounded_page_or_a_repeated_citation_refuses(
    citations: list[dict[str, object]],
) -> None:
    assert _parse_refused(wire(CP0_MD, citations)) is RefusalCode.HANDOFF_MALFORMED


def test_an_oversized_transport_refuses_before_parsing() -> None:
    body = " " * (2 * 26_214_400 + 1)
    assert _parse_refused(body) is RefusalCode.HANDOFF_MALFORMED


def test_more_citations_than_a_handoff_may_carry_refuse() -> None:
    """AI-5: nothing bounded the count, and each one was checked against the
    body by a scan of the whole body. A few thousand of them spent about a
    minute of worker time, on the attempt and again on every replay of it."""
    quotes = [_citation(matched_text=f"word{n}") for n in range(MAX_CITATIONS + 1)]
    assert _parse_refused(wire(CP0_MD, quotes)) is RefusalCode.HANDOFF_MALFORMED


def test_occurrences_finds_every_run_overlapping_or_not() -> None:
    """`occurrences`, the one-pass search the evidence's own excerpt search
    uses (D105): every start of the pattern, overlapping runs included."""
    from caos.evidence.citations import occurrences

    assert list(occurrences(["a", "a", "b", "a", "a"], ["a", "a"])) == [0, 3]
    assert list(occurrences(["a", "a", "a"], ["a", "a"])) == [0, 1]
    assert list(occurrences(["a", "b"], ["c"])) == []


def test_a_record_contradicting_its_own_identity_refuses(tmp_path: Path) -> None:
    blobs, artifact, sha = _stored(tmp_path, _record(authority_bundle_sha256="e" * 64))
    _mismatch(blobs, artifact, sha, CP0)


def test_a_v1_record_refuses_without_backfill(tmp_path: Path) -> None:
    """§45.4: a pre-release v1 record -- no delivered digest, no lineage -- is
    not read as a v2 record with defaults."""
    assert RECORD_FORMAT == "caos-canonical-record-v2"

    def v1(decoded: dict[str, Any]) -> None:
        decoded["format"] = "caos-canonical-record-v1"
        del decoded["delivered_authority_digest"], decoded["lineage"]

    blobs = BlobStore(tmp_path / "blobs")
    _mismatch(blobs, blobs.put(CP0_MD), blobs.put(_rewritten(v1)), CP0)


def test_a_record_not_in_canonical_form_refuses(tmp_path: Path) -> None:
    blobs, artifact, _ = _stored(tmp_path, _record())
    spaced = record_bytes(_record()).replace(b'":', b'": ', 1)
    _mismatch(blobs, artifact, blobs.put(spaced), CP0)


def test_stored_lineage_reads_the_chain_from_the_stored_records(
    tmp_path: Path,
) -> None:
    """§45.4: a direct ref's pair plus every ancestor its stored record names,
    each still the accepted pair; anything else refuses with no text."""
    blobs = BlobStore(tmp_path / "blobs")
    gate = LineageRef("RN-01-CP-0", "CP-0", "d" * 64, "e" * 64)
    screen_md = blobs.put(CP0_MD)
    screen_sha = blobs.put(record_bytes(_record(lineage=(gate,))))
    ref = UpstreamRef("RN-02-CP-L10", "CP-L10", "COS-1", "FY2025", screen_md)
    screen = LineageRef(ref.route_node_id, "CP-L10", screen_md, screen_sha)
    accepted: dict[str, tuple[str, str | None]] = {
        gate.route_node_id: (gate.artifact_sha256, gate.record_sha256),
        ref.route_node_id: (screen_md, screen_sha),
    }
    assert stored_lineage(blobs, (ref,), accepted) == (gate, screen)
    assert stored_lineage(blobs, (), accepted) == ()
    moved: list[dict[str, tuple[str, str | None]]] = [
        {**accepted, gate.route_node_id: (gate.artifact_sha256, "0" * 64)},
        {**accepted, ref.route_node_id: (screen_md, None)},
        {ref.route_node_id: (screen_md, screen_sha)},
        {**accepted, ref.route_node_id: ("0" * 64, screen_sha)},
    ]
    for rows in moved:
        refusal = _refused(partial(stored_lineage, blobs, (ref,), rows))
        assert refusal.code is RefusalCode.ARTIFACT_RECORD_MISMATCH


def test_stored_lineage_follows_a_three_deep_chain_past_non_direct_ancestors(
    tmp_path: Path,
) -> None:
    """§45.4 over stored rows built directly: the consumer's one direct input
    names two ancestors that are not its inputs, and the grand-ancestor's pair
    still binds -- moved or missing, it refuses through a record the consumer
    never reads as an input."""
    blobs = BlobStore(tmp_path / "blobs")

    def stored(route_node_id: str, module_id: str, *lineage: LineageRef) -> LineageRef:
        artifact = blobs.put(CP0_MD + route_node_id.encode())
        record = _record(artifact_sha256=artifact, lineage=lineage)
        return LineageRef(
            route_node_id, module_id, artifact, blobs.put(record_bytes(record))
        )

    gate = stored("RN-01-CP-0", "CP-0")
    screen = stored("RN-02-CP-L10", "CP-L10", gate)
    trace = stored("RN-03-CP-5", "CP-5", gate, screen)
    ref = UpstreamRef(
        trace.route_node_id, "CP-5", "COS-1", "FY2025", trace.artifact_sha256
    )
    accepted: dict[str, tuple[str, str | None]] = {
        link.route_node_id: (link.artifact_sha256, link.record_sha256)
        for link in (gate, screen, trace)
    }
    assert stored_lineage(blobs, (ref,), accepted) == (gate, screen, trace)
    grand = {**accepted, gate.route_node_id: (gate.artifact_sha256, "0" * 64)}
    missing = {k: v for k, v in accepted.items() if k != screen.route_node_id}
    for rows in (grand, missing):
        refusal = _refused(partial(stored_lineage, blobs, (ref,), rows))
        assert refusal.code is RefusalCode.ARTIFACT_RECORD_MISMATCH


def test_a_verified_record_is_not_read_again_for_its_lineage(tmp_path: Path) -> None:
    """The executor hands `stored_lineage` the records its pre-call unit already
    verified; that copy answers, and must still bind the accepted artifact."""
    blobs = BlobStore(tmp_path / "blobs")
    artifact = blobs.put(CP0_MD)
    record = _record(artifact_sha256=artifact)
    sha = blobs.put(record_bytes(record))
    ref = UpstreamRef("RN-01-CP-0", "CP-0", "COS-1", "FY2025", artifact)
    accepted: dict[str, tuple[str, str | None]] = {ref.route_node_id: (artifact, sha)}
    blobs.path_of(sha).unlink()  # only the verified copy can answer now
    link = LineageRef(ref.route_node_id, "CP-0", artifact, sha)
    assert stored_lineage(blobs, (ref,), accepted, verified={sha: record}) == (link,)
    other = dataclasses.replace(record, artifact_sha256="0" * 64)
    for verified in ({}, {sha: other}):
        refusal = _refused(
            partial(stored_lineage, blobs, (ref,), accepted, verified=verified)
        )
        assert refusal.code is RefusalCode.ARTIFACT_RECORD_MISMATCH


def _resign(root: Path, module_id: str, name: str, data: bytes) -> None:
    """Rewrite one module file and its manifest hash, keeping the build id."""
    manifest = root / MANIFEST_NAME
    document = json.loads(manifest.read_bytes())
    [entry] = [e for e in document["skills"] if e["module_id"] == module_id]
    (root / SKILLS_DIR / entry["folder_slug"] / name).write_bytes(data)
    entry["relative_file_hashes"][name] = {
        **entry["relative_file_hashes"][name],
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    manifest.write_text(json.dumps(document))


def test_authority_digests_are_hashed_once_per_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every reader compares a record's authority with the bundle's; the files
    are hashed once per (root, manifest, build, module), and a manifest that
    moved -- same build, one reference re-signed -- is never answered from the
    earlier reading."""
    root = tmp_path / "deploy-v"
    shutil.copytree(VENDORED, root)
    bundle = Bundle(root)
    record = _record(
        build_id=bundle.build_id,
        manifest_sha256=bundle.manifest_sha256,
        authority_digest=authority_digest(assemble_authority(bundle, "CP-0")),
        delivered_authority_digest=delivered_authority_digest(
            delivered_authority(bundle, "CP-0")
        ),
    )
    reads: list[Path] = []
    real = bundle_module._read_verified

    def counted(on: Bundle, path: Path, expected: dict[str, Any]) -> bytes:
        reads.append(path)
        return real(on, path, expected)

    monkeypatch.setattr(bundle_module, "_read_verified", counted)
    assert record_authority_matches(record, bundle=bundle, module_id="CP-0")
    first = len(reads)
    assert record_authority_matches(record, bundle=bundle, module_id="CP-0")
    assert len(reads) == first
    entry = bundle.skill_of("CP-0")
    name = min(n for n in entry["relative_file_hashes"] if n.startswith("references/"))
    path = root / SKILLS_DIR / entry["folder_slug"] / name
    _resign(root, "CP-0", name, path.read_bytes() + b"\n")
    moved = Bundle(root)
    assert moved.build_id == record.build_id
    assert not record_authority_matches(
        dataclasses.replace(record, manifest_sha256=moved.manifest_sha256),
        bundle=moved,
        module_id="CP-0",
    )
    assert len(reads) > first


def test_a_verifying_reader_refuses_a_file_tampered_after_a_cache_hit(
    tmp_path: Path,
) -> None:
    """The proof and deliverable path (`verify=True`) re-reads the bytes, so a
    reference edited on disk under an unchanged manifest refuses even though this
    process already cached the manifest's digests."""
    root = tmp_path / "deploy-v"
    shutil.copytree(VENDORED, root)
    bundle = Bundle(root)
    record = _record(
        build_id=bundle.build_id,
        manifest_sha256=bundle.manifest_sha256,
        authority_digest=authority_digest(assemble_authority(bundle, "CP-0")),
        delivered_authority_digest=delivered_authority_digest(
            delivered_authority(bundle, "CP-0")
        ),
    )
    assert record_authority_matches(record, bundle=bundle, module_id="CP-0")
    entry = bundle.skill_of("CP-0")
    name = min(n for n in entry["relative_file_hashes"] if n.startswith("references/"))
    path = root / SKILLS_DIR / entry["folder_slug"] / name
    path.write_bytes(path.read_bytes() + b"tampered")
    assert record_authority_matches(record, bundle=bundle, module_id="CP-0")
    with pytest.raises(Refusal) as refused:
        record_authority_matches(record, bundle=bundle, module_id="CP-0", verify=True)
    assert refused.value.code is RefusalCode.AUTHORITY_BYTES_MISMATCH


def test_an_empty_blocker_list_is_absent_from_the_record_and_read_back_as_empty(
    tmp_path: Path,
) -> None:
    """Task 10.3: `Projections.blockers` did not move the v2 record's bytes.

    A gate that cleared every module -- and every module but the gate, which
    projects no readiness at all -- writes no `blockers` key, which is the shape
    every record stored before the field existed has. Reading one back supplies
    the empty tuple, and re-serialising it gives those same bytes, so the
    `record_bytes(record) != data` check every reader makes still holds for a
    record this build did not write.
    """
    record = _record()
    assert record.projections.blockers == ()
    data = record_bytes(record)
    assert "blockers" not in json.loads(data)["projections"]

    blobs, artifact, sha = _stored(tmp_path, record)
    read = read_record(blobs, artifact_sha256=artifact, record_sha256=sha, expected=CP0)

    assert read.projections.blockers == ()
    assert record_bytes(read) == data


def test_a_research_brief_in_the_identity_round_trips(tmp_path: Path) -> None:
    brief = '{"schema":"CP_DR_RESEARCH_BRIEF_V1"}'
    identity = dataclasses.replace(CP0, module_id="CP-DR", research_brief=brief)
    record = _record(identity=identity)
    data = record_bytes(record)
    assert json.loads(data)["identity"]["research_brief"] == brief

    blobs, artifact, sha = _stored(tmp_path, record)
    read = read_record(
        blobs, artifact_sha256=artifact, record_sha256=sha, expected=identity
    )

    assert read.identity.research_brief == brief
    assert record_bytes(read) == data


def test_a_record_carrying_blockers_writes_them_and_reads_them_back(
    tmp_path: Path,
) -> None:
    """The other spelling: rows present are written, sorted, and round-trip."""
    asked = "The FY2025 audited consolidated statements are not in the pinned set."
    conditional = _markdown(
        CP0,
        readiness={"CP-5": "CONDITIONAL", "CP-L10": "READY"},
        blockers={"CP-5": asked},
    )
    projections = validate_markdown(
        CONTRACT, CATALOG, skill("CP-0"), conditional, identity=CP0, gate_expects=PINNED
    )
    record = _record(
        artifact_sha256=hashlib.sha256(conditional).hexdigest(),
        projections=projections,
    )
    data = record_bytes(record)
    assert json.loads(data)["projections"]["blockers"] == [["CP-5", asked]]

    blobs = BlobStore(tmp_path / "blobs")
    artifact = blobs.put(conditional)
    read = read_record(
        blobs, artifact_sha256=artifact, record_sha256=blobs.put(data), expected=CP0
    )

    assert read.projections.blockers == (("CP-5", asked),)
    assert record_bytes(read) == data


def test_an_explicitly_empty_blocker_list_is_not_the_canonical_form(
    tmp_path: Path,
) -> None:
    """`blockers: []` written out is a second spelling of one value, and the
    canonical form is the absent key: a record carrying it refuses rather than
    giving two byte strings for one record."""
    document = json.loads(record_bytes(_record()))
    document["projections"]["blockers"] = []
    data = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    blobs = BlobStore(tmp_path / "blobs")
    artifact = blobs.put(CP0_MD)

    _mismatch(blobs, artifact, blobs.put(data), CP0)


def test_strict_json_refuses_a_duplicate_key_and_a_json_constant() -> None:
    """The reader every handoff body goes through: one value per key, no NaN."""
    assert strict_json('{"a":1,"b":[2,3]}') == {"a": 1, "b": [2, 3]}
    for text in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'):
        with pytest.raises(ValueError):
            strict_json(text)
