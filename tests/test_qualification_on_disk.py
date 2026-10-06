"""A qualification set as a declared form on disk, and the loader that reads it.

`CLAUDE.md`'s Phase 10 ledger: a set lived in memory and was digested, not
stored -- "enough for the binding to be checkable and not enough for two people
to be sure they hold the same set without comparing digests by hand". Once a
case carried its documents as bytes it got worse: a set of any size became a
Python literal nobody would write.

The property that makes the form worth having is one line long: **a set read
from disk digests identically to the same set built in memory**. Without it the
file would be a convenience that quietly changes what a verdict binds. With it,
a reviewer can be handed a directory, and the digest in the verdict is a
statement about the bytes in their hands.

What the loader refuses is the other half. The file is authored by someone --
possibly not by this repository, possibly years later -- so it is read the way
`read_verdict` reads a verdict: a closed shape, refusals apart by remedy, and
nothing taken on trust. A document path that leaves the set's directory is the
one refusal that is about safety rather than shape.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from canonical_fixtures import BUNDLE, CATALOG, research_brief

from caos.boundary_text import BoundaryText
from caos.evidence.citations import AnchoredCitation, _Token
from caos.evidence.extract import DEFAULT_LIMITS, dispatch_by_content
from caos.evidence.ingest import Document, token_groups
from caos.graph.route import resolve_route
from caos.qualification.matrix import (
    AlternativeLine,
    ExpectedCitation,
    ExpectedForecast,
    ExpectedProjection,
    ExpectedRegister,
    ForecastValue,
    QualificationCase,
    QualificationSet,
    _matches,
    assert_measurable,
    assert_unambiguous,
    key_lines,
    qualification_set_digest,
    unlocatable_register_keys,
)
from caos.qualification.on_disk import MANIFEST, load_qualification_set
from caos.qualification.proof import cited_line
from caos.refusals import Refusal, RefusalCode
from caos.store.run_inputs import RunSubject, research_text

REPORT = b"""Acme Holdings plc annual report 2026
Total debt at 31 December 2026 was USD 1,240.0m
"""
OTHER = b"""Borealis Industries plc annual report 2026
Total debt at 31 December 2026 was USD 880.0m
"""
QUOTE = "Total debt at 31 December 2026"


def _in_memory() -> QualificationSet:
    """The set the fixture below writes out, built the way Python callers do."""
    return QualificationSet(
        cases=(
            QualificationCase(
                label="acme-2026",
                documents=(
                    Document(filename=BoundaryText.of("report.txt"), data=REPORT),
                ),
                profile_id="FULL_CREDIT_32",
                selection_id="DEEP_RESEARCH",
                expects=(
                    ExpectedCitation(
                        module_id="CP-0",
                        document_sha256=sha256(REPORT).hexdigest(),
                        matched_text=QUOTE,
                    ),
                ),
            ),
            QualificationCase(
                label="borealis-2026",
                documents=(
                    Document(filename=BoundaryText.of("report.txt"), data=OTHER),
                ),
                profile_id="FULL_CREDIT_32",
                selection_id="DEEP_RESEARCH",
                expects=(
                    ExpectedCitation(
                        module_id="CP-0",
                        document_sha256=sha256(OTHER).hexdigest(),
                        matched_text=QUOTE,
                    ),
                ),
            ),
        )
    )


def _manifest() -> dict[str, object]:
    return {
        "cases": [
            {
                "label": "acme-2026",
                "profile_id": "FULL_CREDIT_32",
                "selection_id": "DEEP_RESEARCH",
                "documents": ["documents/acme-2026/report.txt"],
                "expects": [
                    {
                        "module_id": "CP-0",
                        "document_sha256": sha256(REPORT).hexdigest(),
                        "matched_text": QUOTE,
                    }
                ],
            },
            {
                "label": "borealis-2026",
                "profile_id": "FULL_CREDIT_32",
                "selection_id": "DEEP_RESEARCH",
                "documents": ["documents/borealis-2026/report.txt"],
                "expects": [
                    {
                        "module_id": "CP-0",
                        "document_sha256": sha256(OTHER).hexdigest(),
                        "matched_text": QUOTE,
                    }
                ],
            },
        ]
    }


@pytest.fixture
def on_disk(tmp_path: Path) -> Path:
    """The set above, written out in the declared form."""
    return _write(tmp_path, _manifest())


def _write(root: Path, manifest: object) -> Path:
    for case, data in (("acme-2026", REPORT), ("borealis-2026", OTHER)):
        document = root / "documents" / case / "report.txt"
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_bytes(data)
    (root / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    return root


def test_a_set_read_from_disk_digests_identically_to_one_built_in_memory(
    on_disk: Path,
) -> None:
    """The property the whole form rests on.

    A verdict binds `qualification_set_sha256`. If loading changed the digest,
    the file would be a second way of saying something slightly different, and
    a signature given over the directory would not name the set a caller ran.
    """
    loaded = load_qualification_set(on_disk)

    assert qualification_set_digest(loaded) == qualification_set_digest(_in_memory())
    assert [case.label for case in loaded.cases] == ["acme-2026", "borealis-2026"]
    assert loaded.cases[0].documents[0].data == REPORT
    assert loaded.cases[0].documents[0].filename.value == "report.txt"


def test_the_bytes_on_disk_are_what_the_case_carries(on_disk: Path) -> None:
    """Edit a document and the digest moves, because the digest covers content.

    This is what stops a set being edited underneath a verdict that binds it:
    the file is not a name for a set, it is the set.
    """
    before = qualification_set_digest(load_qualification_set(on_disk))
    (on_disk / "documents" / "acme-2026" / "report.txt").write_bytes(b"something else")

    assert qualification_set_digest(load_qualification_set(on_disk)) != before


def test_a_disk_set_binds_a_forecast_key_and_host_extension(tmp_path: Path) -> None:
    manifest = _manifest()
    first = manifest["cases"][0]  # type: ignore[index]
    first.update(
        {
            "forecast": {
                "scenario": "BASE",
                "period_id": "FY2026",
                "values": [{"name": "cash.closing", "value": "145.000000"}],
                "currency": "USD",
                "scale": "millions",
                "perimeter": "Consolidated",
                "qa_status": "Passed",
                "limitation_flags": [],
                "readiness": [["CP-1", "READY"]],
            },
            "expected_refusal": "HANDOFF_BLOCKED",
            "model_extension": True,
        }
    )
    [case] = load_qualification_set(_write(tmp_path, manifest)).cases[:1]
    assert case.model_extension is True
    assert case.expected_refusal is RefusalCode.HANDOFF_BLOCKED
    assert case.forecast == ExpectedForecast(
        scenario="BASE",
        period_id="FY2026",
        values=(ForecastValue(name="cash.closing", value="145.000000"),),
        currency="USD",
        scale="millions",
        perimeter="Consolidated",
        qa_status="Passed",
        limitation_flags=(),
        readiness=(("CP-1", "READY"),),
    )


def test_a_disk_set_binds_a_readiness_key(tmp_path: Path) -> None:
    manifest = _manifest()
    first = manifest["cases"][0]  # type: ignore[index]
    first["expects_ready"] = ["CP-1", "CP-2"]

    [case] = load_qualification_set(_write(tmp_path, manifest)).cases[:1]
    assert case.expects_ready == ("CP-1", "CP-2")


def test_a_disk_set_binds_a_readiness_refusal_key(tmp_path: Path) -> None:
    """§99: `expects_blocked` reaches the case as declared and moves the digest;
    absent, it is the empty tuple every set loaded before it carried."""
    plain = load_qualification_set(_write(tmp_path / "plain", _manifest()))
    assert all(case.expects_blocked == () for case in plain.cases)

    manifest = _manifest()
    manifest["cases"][0]["expects_blocked"] = ["CP-L10", "CP-5"]  # type: ignore[index]
    keyed = load_qualification_set(_write(tmp_path / "keyed", manifest))

    assert keyed.cases[0].expects_blocked == ("CP-L10", "CP-5")
    assert qualification_set_digest(keyed) != qualification_set_digest(plain)


def test_a_module_expected_both_ready_and_blocked_is_refused(tmp_path: Path) -> None:
    """No run can clear and refuse one module, so the manifest is refused."""
    manifest = _manifest()
    manifest["cases"][0]["expects_ready"] = ["CP-L10"]  # type: ignore[index]
    manifest["cases"][0]["expects_blocked"] = ["CP-L10"]  # type: ignore[index]

    with pytest.raises(Refusal) as refused:
        load_qualification_set(_write(tmp_path, manifest))

    assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID


# The digest each committed set binds. A set's digest moves only when its own
# manifest or documents move; a change to the loader or the digest that moved
# one of these would silently orphan every verdict and snapshot bound to it.
#
# N8/FP-25: every optional field a case can carry is now tagged in `_digested`
# with its own name before its value, closing a real ambiguity -- a set naming
# a subject and a set naming, say, an equal-shaped `expects_ready` list could
# digest identically. Every one of these moved because every committed set
# carries at least one of the fields that used to go in untagged.
COMMITTED_SET_DIGESTS = {
    "ba-fy2025": ("300a680d0c3f8e4d5e207ce4e80d1d46390d7e28b6d88eadb4f70cb9ca19ec61"),
    "ccl-fy2025": "85d50a252f3158fe8a4bd8e4cd0747409f1b559460c16bdc1761b8745d381eb5",
    "ccl-fy2025-covenant-refinancing": (
        "813a9182f25b51814e97ab9b5ce924b21c313471e6557d2486f2599f175806df"
    ),
    "ccl-fy2025-earnings-update": (
        "36aafade247e6c98811e23be6a5c9ccb6bd17c975b77075b6a7d58a62012be61"
    ),
    "ccl-fy2025-liquidity": (
        "f98bf8cc077e7fca0e347a34ef8f29adc9dbd4a2a9e51e985fc7118d645335e1"
    ),
    "ccl-fy2025-portfolio": (
        "504fcb0641cb445d6413b0824b2482013f862b739594b0b80fdb3dfa82ae7532"
    ),
    "ccl-fy2025-full-relative-value": (
        "f4205e4e3606ef68aece138696ea630c7632d2e184a067edce13eebf88e22e79"
    ),
    "ccl-fy2025-relative-value": (
        "fb20188605c957ec7b91079bd98f0002a627d15f633586eb39f7349e1f4bbf4b"
    ),
    "ccl-fy2025-lite-covenant-refinancing": (
        "85fd43d537432db2a5a805ab5855ca2dda28d4b8b8b4e04fe91e0b78421fc2a9"
    ),
    "ccl-fy2025-lite-full-credit-screen": (
        "f1647d3b593d4a3ec66a001969346f9411da30091b618383a1076b4cefda9608"
    ),
    "ccl-fy2025-market-dislocation": (
        "c01b06c9c09b1ced76c297e0d7bf81ad07ace9e03f3e3322da81b3f85840db35"
    ),
    "czr-2026q2": ("927d45cf483827717ed2f322c7ff7b5a81dd7c8ab9d3e7d06c2f8d2414127c68"),
    "czr-2026q2-earnings-update": (
        "03b43aad16b19c0c3ce2d66b3b949a5b21f2708831b1e293ad0efe94c2677d75"
    ),
    "czr-2026q2-liquidity": (
        "e85741cb049525fb7d16ed4ea00166eb9f730b0f7575c1dadae174e17fe5f2a0"
    ),
    "czr-2026q2-covenant-refinancing": (
        "c4bd9867b774d1b23d69d563f9519c98f22cb2d8fcf43de215e65c495be1a0b5"
    ),
    "czr-2026q2-lite-covenant-refinancing": (
        "309f8ef9531fd9e65d1fb5d777eb9aa9263c930a9f402977b5a27f62623f877e"
    ),
    "czr-2026q2-lite-relative-value": (
        "99a498e0085d5cd725547129b2d30bbd808f7c43fec6fb44c1d7ac295b37db78"
    ),
    "czr-2026q2-relative-value": (
        "a645d01e13330854836b371a4096cf4637b527bf06784151005ef9f5d0745c91"
    ),
    "czr-2026q2-lite-full-credit-screen": (
        "e63265aaf3004c4bc9ce7b755cda587786240647b50e70a26567beaa3741bb39"
    ),
    "czr-2026q2-lite-portfolio": (
        "60d8bef15b29bfca43cc572741c5f1b6c0b808e0f54e50374eb5de3de96c0285"
    ),
    "czr-2026q2-portfolio": (
        "c847fbfa3b7621d2cccba4f42830bd73274b5826277c2ef2dedc427f4512f066"
    ),
    "czr-2026q2-full-credit-assessment": (
        "5e0a1f7d45f61cf66ab435da206caa4f9acabc3589ed51ff880e7a019c9670e5"
    ),
    "save-2024-distressed-restructuring": (
        "5a6fb829e945143cf3b6593231dbb2b6d181b7feaca2b60906f3222faf313f6b"
    ),
    "save-2024-lite-distressed-restructuring": (
        "3dcc0176be623c26b6da7d734c6a1a9ea2f1244beab0ca69de29e8228a05903c"
    ),
    "f-fy2025": ("645e5829dcee868d58e4c8997014a6d9351e7245fe64727d9c01f04ba9e2206f"),
    "vmo2-fy2025": "ff9dc7ecc2229ae0d7a114bb8f50e8c30ac9fdd05d62191447c63c8a4dee6b41",
    "vmo2-fy2025-deep-research": (
        "1881fcf6818e623322b52679268906a624d9ad4b4026c759f74bdcf9435e9bdd"
    ),
    "vmo2-fy2025-full-deep-research": (
        "6e617e8ced5f874ecef59f30bd813f9be06de8c6a2674a2f9c461f2346964f23"
    ),
    "vmo2-fy2025-portfolio": (
        "7215b7c7c41697cc6464adc9cf2f3fe57fa520faf3d2a83c5ea800160f3f1ae2"
    ),
}

PENDING_SET_DOCUMENTS: dict[str, frozenset[str]] = {}


def test_every_committed_set_binds_its_recorded_digest() -> None:
    """Every complete set digests as recorded; pending sets name exact gaps."""
    root = Path(__file__).resolve().parents[1] / "qualification"
    found = {}
    pending = {}
    for path in root.glob(f"*/{MANIFEST}"):
        name = path.parent.name
        if name in PENDING_SET_DOCUMENTS:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            pending[name] = frozenset(
                document
                for case in manifest["cases"]
                for document in case["documents"]
                if not (path.parent / document).is_file()
            )
        else:
            found[name] = qualification_set_digest(load_qualification_set(path.parent))

    assert found == COMMITTED_SET_DIGESTS
    assert pending == PENDING_SET_DOCUMENTS


def _evidence_lines(tokens: list[_Token]) -> list[str]:
    """A page's evidence lines as admission writes them: each token line cut
    into its `PACKING_BY_TOKEN` blocks (`token_groups`), each block a string."""
    lines: dict[int, list[str]] = {}
    for token in tokens:
        lines.setdefault(token.line_id, []).append(token.text)
    return [block for words in lines.values() for block in token_groups(words)]


def test_every_committed_answer_key_names_its_route_and_exact_source() -> None:
    """No key can name an off-route module or an unreadable source quote, and
    every key is exactly one whole evidence line of its document (F475), NFC
    as a shown line is: a citation meets a key by the line it anchored in,
    compared by exact equality (D105), so a fragment or a quote that runs onto
    the next line is a key no run can meet. A whole line whose words also run
    inside a longer line is still one line (K2, F502): the 10-Q's `Adjusted
    EBITDA` row recurs inside its `Total Adjusted EBITDA` row and is a key."""
    root = Path(__file__).resolve().parents[1] / "qualification"
    extracted: dict[str, dict[int, list[_Token]]] = {}

    for name in COMMITTED_SET_DIGESTS:
        qualification = load_qualification_set(root / name)
        assert not unlocatable_register_keys(BUNDLE, qualification)
        for case in qualification.cases:
            route_modules = {
                node.module_id
                for node in resolve_route(
                    CATALOG, case.profile_id, case.selection_id
                ).nodes
            }
            keyed_modules = (
                {key.module_id for key in case.expects}
                | set(case.expects_ready)
                | set(case.expects_blocked)
                | {key.module_id for key in case.expects_projection}
                | {key.module_id for key in case.expects_register}
            )
            assert keyed_modules <= route_modules

            documents = {
                sha256(document.data).hexdigest(): document
                for document in case.documents
            }
            for expected in case.expects:
                # A key's alternatives (D101) are held to its own line's rule.
                for document_sha256, matched_text in key_lines(expected):
                    if document_sha256 not in extracted:
                        extracted[document_sha256] = _pages(
                            documents[document_sha256].data
                        )
                    whole = _whole_lines(extracted[document_sha256], matched_text)
                    assert unicodedata.normalize("NFC", matched_text) == matched_text
                    assert whole == 1, (
                        f"{matched_text!r} is not exactly one evidence line"
                        f" of its document (found {whole}): {expected}"
                    )


def _pages(data: bytes) -> dict[int, list[_Token]]:
    """A document's tokens by page, as admission extracts them."""
    pages: dict[int, list[_Token]] = {}
    for token in dispatch_by_content(data).extract(data):
        pages.setdefault(token.page, []).append(
            _Token(
                token.text,
                token.region_id,
                token.line_id,
                token.x0,
                token.y0,
                token.x1,
                token.y1,
            )
        )
    return pages


def _whole_lines(pages: dict[int, list[_Token]], matched_text: str) -> int:
    """How often `matched_text` is one whole evidence line (F475): a key or
    alternative must be exactly 1. How often its words run inside other lines
    is no longer asked (K2): a key is met by the line a citation anchored in,
    never by a run of the page."""
    return sum(
        block == matched_text
        for tokens in pages.values()
        for block in _evidence_lines(tokens)
    )


def test_ccl_liquidity_set_is_a_complete_offline_copy_with_pinned_keys() -> None:
    root = Path(__file__).resolve().parents[1]
    set_root = root / "qualification" / "ccl-fy2025-liquidity"
    source = root / "qualification" / "ccl-fy2025" / "documents" / "CCL_FY2025_10K.txt"
    document = set_root / "documents" / "CCL_FY2025_10K.txt"

    inventory = {
        path.relative_to(set_root).as_posix()
        for path in set_root.rglob("*")
        if path.is_file()
    }
    assert inventory == {
        "qualification.json",
        "RESULT.md",
        "documents/CCL_FY2025_10K.txt",
    }
    assert document.read_bytes() == source.read_bytes()
    assert sha256(document.read_bytes()).hexdigest() == (
        "8fa7fceda34be50b3b9b5406e0c9269b5269870d1cd8c2bdafb682755a1c88e6"
    )

    qualification = load_qualification_set(set_root)
    assert_measurable(qualification)
    assert_unambiguous(qualification)
    [case] = qualification.cases
    assert (case.profile_id, case.selection_id) == (
        "FULL_CREDIT_32",
        "LIQUIDITY_REVIEW",
    )
    assert case.expects_ready == ("CP-1", "CP-2", "CP-2D")
    projections = {
        (key.module_id, key.field, key.value) for key in case.expects_projection
    }
    assert projections == {
        ("CP-2D", "decision_scope", "FULL"),
    }
    document_sha256 = "8fa7fceda34be50b3b9b5406e0c9269b5269870d1cd8c2bdafb682755a1c88e6"
    anchors = {
        "Cash and cash equivalents | $ | 1,928 | $ | 1,210 |",
        "Customer deposits | 6,831 | 6,425 |",
        "Net cash provided by operating activities | 6,218 | 5,923 | 4,281 |",
        "Purchases of property and equipment | ( 3,611 ) | ( 4,626 ) | ( 3,284 ) |",
    }
    cash_and_deposits = {
        "Cash and cash equivalents | $ | 1,928 | $ | 1,210 |",
        "Customer deposits | 6,831 | 6,425 |",
    }
    citations = {
        (citation.module_id, citation.document_sha256, citation.matched_text)
        for citation in case.expects
    }
    assert citations == (
        {("CP-1", document_sha256, anchor) for anchor in cash_and_deposits}
        | {("CP-2", document_sha256, anchor) for anchor in anchors - cash_and_deposits}
        | {("CP-2D", document_sha256, anchor) for anchor in anchors}
    )
    evidence = document.read_text(encoding="utf-8")
    assert all(evidence.count(anchor) == 1 for anchor in anchors)


def test_a_document_path_that_leaves_the_set_is_refused(tmp_path: Path) -> None:
    """The one refusal here that is about safety rather than shape.

    A manifest is authored, possibly not by this repository. A path escaping the
    set's own directory would let a file anywhere the process can read be
    admitted into a case and digested as part of it.
    """
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"not part of the set")
    root = tmp_path / "set"
    root.mkdir()
    manifest = _manifest()
    manifest["cases"][0]["documents"] = ["../outside.txt"]  # type: ignore[index]

    with pytest.raises(Refusal) as refused:
        load_qualification_set(_write(root, manifest))

    assert refused.value.code is RefusalCode.QUALIFICATION_SET_PATH_ESCAPES


def test_an_absolute_document_path_is_refused(tmp_path: Path) -> None:
    """Absolute is the same escape by a shorter route, and `Path.joinpath`
    silently discards the root it was joined to when handed one."""
    root = tmp_path / "set"
    root.mkdir()
    manifest = _manifest()
    manifest["cases"][0]["documents"] = ["/etc/hostname"]  # type: ignore[index]

    with pytest.raises(Refusal) as refused:
        load_qualification_set(_write(root, manifest))

    assert refused.value.code is RefusalCode.QUALIFICATION_SET_PATH_ESCAPES


def test_a_manifest_that_is_not_the_declared_shape_is_refused(
    tmp_path: Path,
) -> None:
    """Every way the file can fail to be a qualification set, one code.

    Apart from the escape above, a malformed manifest has one remedy -- fix the
    file -- so it gets one refusal rather than a taxonomy nobody acts on
    differently.
    """
    root = tmp_path / "set"
    root.mkdir()
    malformed: list[object] = [
        {"cases": "not a list"},
        {"cases": [{"label": "a"}]},
        {"cases": [{**_manifest()["cases"][0], "documents": "not a list"}]},  # type: ignore[index]
        {"cases": [{**_manifest()["cases"][0], "expects": [{"module_id": "CP-0"}]}]},  # type: ignore[index]
        {"cases": [{**_manifest()["cases"][0], "label": ""}]},  # type: ignore[index]
        {"cases": [{**_manifest()["cases"][0], "undeclared": 1}]},  # type: ignore[index]
        {"cases": [{**_manifest()["cases"][0], "expects_ready": []}]},  # type: ignore[index]
        {"cases": [{**_manifest()["cases"][0], "expects_ready": "CP-0"}]},  # type: ignore[index]
        {"cases": [{**_manifest()["cases"][0], "expects_ready": [""]}]},  # type: ignore[index]
        {"cases": [{**_manifest()["cases"][0], "expects_ready": [1]}]},  # type: ignore[index]
        {"cases": [{**_manifest()["cases"][0], "expects_ready": ["CP-0", "CP-0"]}]},  # type: ignore[index]
        {"cases": [{**_manifest()["cases"][0], "expects_blocked": []}]},  # type: ignore[index]
        {"cases": [{**_manifest()["cases"][0], "expects_blocked": "CP-L10"}]},  # type: ignore[index]
        {"cases": [{**_manifest()["cases"][0], "expects_blocked": [" "]}]},  # type: ignore[index]
        {"cases": [{**_manifest()["cases"][0], "expects_blocked": [1]}]},  # type: ignore[index]
        {"cases": [{**_manifest()["cases"][0], "expects_blocked": ["CP-5", "CP-5"]}]},  # type: ignore[index]
        ["not a mapping"],
    ]

    for manifest in malformed:
        with pytest.raises(Refusal) as refused:
            load_qualification_set(_write(root, manifest))
        assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID, (
            manifest
        )


def test_a_projection_key_naming_a_field_the_host_does_not_project_is_refused(
    tmp_path: Path,
) -> None:
    """A mistyped field must refuse at load, not read as a failed conclusion.

    Compared at match time it would return False, and the matrix would report
    that the module concluded the wrong thing when the truth is that the key
    asked about nothing. That is the one failure a key must never have.
    """
    root = tmp_path / "set"
    root.mkdir()
    manifest = _manifest()
    cases = manifest["cases"]
    assert isinstance(cases, list)
    cases[0]["expects_projection"] = [
        {"module_id": "CP-L10", "field": "qa_stat", "value": "Restricted"}
    ]

    with pytest.raises(Refusal) as refused:
        load_qualification_set(_write(root, manifest))

    assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID


def test_a_projection_key_is_read_as_declared(tmp_path: Path) -> None:
    """The declared conclusions reach the case, and move the set's digest."""
    root = tmp_path / "set"
    root.mkdir()
    plain = load_qualification_set(_write(root, _manifest()))

    keyed_root = tmp_path / "keyed"
    keyed_root.mkdir()
    manifest = _manifest()
    cases = manifest["cases"]
    assert isinstance(cases, list)
    cases[0]["expects_projection"] = [
        {"module_id": "CP-L10", "field": "qa_status", "value": "Restricted"},
        {"module_id": "CP-L10", "field": "decision_scope", "value": "SCREENING_ONLY"},
    ]
    keyed = load_qualification_set(_write(keyed_root, manifest))

    [expect, scope] = keyed.cases[0].expects_projection
    assert isinstance(expect, ExpectedProjection)
    assert (expect.module_id, expect.field, expect.value) == (
        "CP-L10",
        "qa_status",
        "Restricted",
    )
    assert scope.field == "decision_scope"
    assert qualification_set_digest(keyed) != qualification_set_digest(plain)


def test_a_document_that_is_not_a_regular_file_is_refused(tmp_path: Path) -> None:
    """A FIFO at a declared path would block the loader until someone wrote.

    `read_bytes` answers "what is at this path" only for files; on a FIFO it
    waits, and a set that hangs its loader is a set nobody can time out. The
    same check refuses a directory and a socket.
    """
    import os

    root = tmp_path / "set"
    root.mkdir()
    written = _write(root, _manifest())
    document = written / "documents" / "acme-2026" / "report.txt"
    document.unlink()
    os.mkfifo(document)

    with pytest.raises(Refusal) as refused:
        load_qualification_set(written)

    assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID


def test_a_document_larger_than_admission_would_take_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refused at load, before its bytes are read into memory.

    `admit_pack` bounds a document at 20 MiB, but it never saw one this large:
    the loader read the whole file first and handed it over. The ceiling here is
    admission's own, so a set that could not be admitted is not read either.
    """
    root = tmp_path / "set"
    root.mkdir()
    written = _write(root, _manifest())
    monkeypatch.setattr(
        "caos.qualification.on_disk.DEFAULT_LIMITS",
        replace(DEFAULT_LIMITS, max_document_bytes=8),
    )

    with pytest.raises(Refusal) as refused:
        load_qualification_set(written)

    assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID


def test_an_undeclared_key_at_the_top_of_the_manifest_is_refused(
    tmp_path: Path,
) -> None:
    """Closed at the outer shape too, not only per case.

    A key this loader ignores is a statement its author believed they had made
    -- a `tolerance` or a `provider` at the top of the file would be read by a
    person and by nothing else.
    """
    root = tmp_path / "set"
    root.mkdir()
    manifest = {**_manifest(), "notes": "for the reviewer"}

    with pytest.raises(Refusal) as refused:
        load_qualification_set(_write(root, manifest))

    assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID


def test_a_document_that_is_not_a_path_string_is_refused(tmp_path: Path) -> None:
    """`documents` is a list of paths; an object or a number in it is a manifest
    written against a different format than this one."""
    root = tmp_path / "set"
    root.mkdir()
    manifest = _manifest()
    manifest["cases"][0]["documents"] = [{"path": "documents/a.txt"}]  # type: ignore[index]

    with pytest.raises(Refusal) as refused:
        load_qualification_set(_write(root, manifest))

    assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID


def test_a_filename_the_boundary_refuses_is_a_malformed_manifest(
    tmp_path: Path,
) -> None:
    """A filename is digested and admitted, so it crosses `BoundaryText`.

    Retyped on the way out: a bidi override in a document's name is a defect in
    the file being read, and `BOUNDARY_TEXT_INVALID` would send a reader looking
    at the loader rather than at the manifest that named it.
    """
    root = tmp_path / "set"
    root.mkdir()
    hostile = root / "documents" / "acme-2026"
    hostile.mkdir(parents=True, exist_ok=True)
    # U+202E, one of the nine controls `BoundaryText` refuses.
    (hostile / "re\u202eport.txt").write_bytes(REPORT)
    manifest = _manifest()
    manifest["cases"][0]["documents"] = [  # type: ignore[index]
        "documents/acme-2026/re\u202eport.txt"
    ]

    with pytest.raises(Refusal) as refused:
        load_qualification_set(_write(root, manifest))

    assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID


def test_a_missing_manifest_or_document_is_refused(tmp_path: Path) -> None:
    """A set is its bytes. One named document absent is not a smaller set."""
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(Refusal) as refused:
        load_qualification_set(empty)
    assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID

    root = _write(tmp_path / "set", _manifest())
    (root / "documents" / "acme-2026" / "report.txt").unlink()
    with pytest.raises(Refusal) as gone:
        load_qualification_set(root)
    assert gone.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID


def test_a_manifest_that_is_not_json_is_refused(tmp_path: Path) -> None:
    """Bytes that will not parse say nothing about a set."""
    root = _write(tmp_path / "set", _manifest())
    (root / MANIFEST).write_text("{ not json", encoding="utf-8")

    with pytest.raises(Refusal) as refused:
        load_qualification_set(root)

    assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID


def test_a_manifest_larger_than_its_bound_is_refused_before_reading(
    tmp_path: Path,
) -> None:
    """A manifest names cases; it never needs to carry a document's worth of bytes.

    Refused by size, before `json.loads` ever sees the bytes -- the same
    fail-closed shape `admit_pack` gives a document, applied to the file that
    names them.
    """
    from caos.qualification.on_disk import MAX_MANIFEST_BYTES

    root = _write(tmp_path / "set", _manifest())
    oversized = "{" + " " * MAX_MANIFEST_BYTES + "}"
    (root / MANIFEST).write_text(oversized, encoding="utf-8")

    with pytest.raises(Refusal) as refused:
        load_qualification_set(root)

    assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID


def test_a_document_larger_than_admit_packs_own_limit_is_refused(
    tmp_path: Path,
) -> None:
    """A document too large for `admit_pack` is refused at load, not read first.

    `_document` shares the exact ceiling `admit_pack` applies at admission, so a
    set that would be refused there does not pay to read an oversized file into
    memory here only to have it refused a moment later.
    """
    from caos.evidence.extract import DEFAULT_LIMITS

    root = _write(tmp_path / "set", _manifest())
    big_document = root / "documents" / "acme-2026" / "report.txt"
    with big_document.open("wb") as handle:
        handle.seek(DEFAULT_LIMITS.max_document_bytes)
        handle.write(b"\0")

    with pytest.raises(Refusal) as refused:
        load_qualification_set(root)

    assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID


def test_a_document_path_naming_a_directory_is_refused(tmp_path: Path) -> None:
    """A declared document that is not a regular file reads no bytes at all.

    A directory is not a FIFO, but it is the one non-regular case this suite
    can create without an actual named pipe -- both fail `Path.is_file()` the
    same way, before `read_bytes` would ever block or fail differently.
    """
    root = _write(tmp_path / "set", _manifest())
    document = root / "documents" / "acme-2026" / "report.txt"
    document.unlink()
    document.mkdir()

    with pytest.raises(Refusal) as refused:
        load_qualification_set(root)

    assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID


# `_in_memory()`'s digest before a case could carry a subject. A set whose cases
# carry none must keep binding exactly this, or every earlier verdict is orphaned.
GOLDEN = "64bc178c0010b0fe104e01f4f7fac2bce35d1dc09f21fea86ff996aa99233373"
SUBJECT = {
    "issuer_id": "ACME",
    "issuer_name": "Acme Holdings plc",
    "reporting_period": "FY2026",
    "analysis_date": "2026-09-13",
}


def test_a_set_without_subjects_keeps_its_golden_digest(on_disk: Path) -> None:
    assert qualification_set_digest(_in_memory()) == GOLDEN
    loaded = load_qualification_set(on_disk)
    assert all(case.subject is None for case in loaded.cases)
    assert qualification_set_digest(loaded) == GOLDEN


def test_a_declared_subject_round_trips_and_is_digested(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["cases"][0]["subject"] = dict(SUBJECT)  # type: ignore[index]
    loaded = load_qualification_set(_write(tmp_path, manifest))

    subject = RunSubject(**SUBJECT)
    assert loaded.cases[0].subject == subject
    assert loaded.cases[1].subject is None
    with_subject = qualification_set_digest(loaded)
    assert with_subject != GOLDEN
    first, second = _in_memory().cases
    built = QualificationSet((replace(first, subject=subject), second))
    assert qualification_set_digest(built) == with_subject
    for key, value in SUBJECT.items():
        moved = replace(subject, **{key: value + "X"})
        changed = QualificationSet((replace(first, subject=moved), second))
        assert qualification_set_digest(changed) not in {with_subject, GOLDEN}, key


@pytest.mark.parametrize(
    "declared",
    [
        {k: v for k, v in SUBJECT.items() if k != "analysis_date"},
        {**SUBJECT, "cos_run_id": "COS-1"},
        {**SUBJECT, "issuer_id": 7},
        {**SUBJECT, "issuer_name": ""},
        {**SUBJECT, "issuer_name": " padded"},
        {**SUBJECT, "analysis_date": "2026-02-30"},
        [SUBJECT["issuer_id"]],
        None,
    ],
)
def test_a_subject_that_is_not_the_closed_shape_is_refused(
    tmp_path: Path, declared: object
) -> None:
    manifest = _manifest()
    manifest["cases"][0]["subject"] = declared  # type: ignore[index]

    with pytest.raises(Refusal) as refused:
        load_qualification_set(_write(tmp_path, manifest))

    assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID


# --- Register keys (Completion Phase 8 Task 8.1) -----------------------------

REGISTER_KEY = {
    "module_id": "CP-L10",
    "register_id": "TL10.2",
    "row_key": {"topic_id": "LIQUIDITY_MATURITIES"},
    "column": "evidence_status",
    "expected": "PARTIAL",
}


def _with_register(key: object) -> dict[str, object]:
    manifest = _manifest()
    cases = manifest["cases"]
    assert isinstance(cases, list)
    cases[0]["expects_register"] = key
    return manifest


def test_expects_register_loads_from_a_manifest(tmp_path: Path) -> None:
    """The declared register keys reach the case, and move the set's digest."""
    plain = load_qualification_set(_write(tmp_path / "plain", _manifest()))
    keyed = load_qualification_set(
        _write(tmp_path / "keyed", _with_register([dict(REGISTER_KEY)]))
    )

    [expect] = keyed.cases[0].expects_register
    assert expect == ExpectedRegister(
        module_id="CP-L10",
        register_id="TL10.2",
        row_key=(("topic_id", "LIQUIDITY_MATURITIES"),),
        column="evidence_status",
        expected="PARTIAL",
    )
    assert keyed.cases[1].expects_register == ()
    assert qualification_set_digest(keyed) != qualification_set_digest(plain)


def test_an_empty_row_key_refuses_at_load(tmp_path: Path) -> None:
    """A row key that names no cell names every row, which is not one answer.

    Its own code: the file is well formed and the key is not answerable, so
    "correct the set manifest" would send the author looking at the shape rather
    than at the row they meant to name.
    """
    with pytest.raises(Refusal) as refused:
        load_qualification_set(
            _write(tmp_path, _with_register([{**REGISTER_KEY, "row_key": {}}]))
        )

    assert refused.value.code is RefusalCode.QUALIFICATION_KEY_AMBIGUOUS


def test_two_spellings_of_one_row_key_column_refuse_at_load(tmp_path: Path) -> None:
    """Bounded to one column name, so the key names the row twice."""
    with pytest.raises(Refusal) as refused:
        load_qualification_set(
            _write(
                tmp_path,
                _with_register(
                    [
                        {
                            **REGISTER_KEY,
                            "row_key": {
                                "topic_id": "LIQUIDITY_MATURITIES",
                                "topic_id ": "CASH_CONVERSION",
                            },
                        }
                    ]
                ),
            )
        )

    assert refused.value.code is RefusalCode.QUALIFICATION_KEY_AMBIGUOUS


@pytest.mark.parametrize(
    "declared",
    [
        [{**REGISTER_KEY, "undeclared": "x"}],
        [{k: v for k, v in REGISTER_KEY.items() if k != "column"}],
        [{**REGISTER_KEY, "row_key": [["topic_id", "LIQUIDITY_MATURITIES"]]}],
        [{**REGISTER_KEY, "row_key": {"topic_id": 7}}],
        [{**REGISTER_KEY, "expected": ""}],
        [dict(REGISTER_KEY), dict(REGISTER_KEY)],
        [],
        "TL10.2",
    ],
)
def test_an_undeclared_register_key_field_refuses(
    tmp_path: Path, declared: object
) -> None:
    """Closed both ways, like every other declared object here.

    A key this loader ignored -- a `row` beside `row_key`, a second identical
    key, a list where an object belongs -- would be a statement its author
    believed they had made.
    """
    with pytest.raises(Refusal) as refused:
        load_qualification_set(_write(tmp_path, _with_register(declared)))

    assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID


def test_a_register_key_carrying_a_bidi_control_is_refused_at_the_boundary(
    tmp_path: Path,
) -> None:
    """A key is pinned state, so it crosses `BoundaryText` like a case label,
    and what the boundary refuses reads as a malformed manifest (FP-08): the
    loader is the one place that can name the file, so the code is its own,
    never a boundary failure raised from nowhere."""
    # U+202E, one of the nine controls `BoundaryText` refuses.
    hostile = {**REGISTER_KEY, "column": "evidence\u202estatus"}
    with pytest.raises(Refusal) as refused:
        load_qualification_set(_write(tmp_path, _with_register([hostile])))

    assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID


def test_the_vmo2_set_still_loads_with_its_register_key(tmp_path: Path) -> None:
    """The set in the tree is read by the loader that now has one more key.

    Authored from the two admitted earnings releases: each release states
    undrawn commitments and covenant leverage and neither carries a maturity
    profile of the group's debt, so the topic's evidence is `PARTIAL` -- not
    `SUFFICIENT` and not `MISSING`. The key is not taken from any run.
    """
    root = Path(__file__).resolve().parents[1] / "qualification" / "vmo2-fy2025"
    [case] = load_qualification_set(root).cases

    [expect] = case.expects_register
    assert (expect.module_id, expect.register_id) == ("CP-L10", "TL10.2")
    assert expect.row_key == (("topic_id", "LIQUIDITY_MATURITIES"),)
    assert (expect.column, expect.expected) == ("evidence_status", "PARTIAL")
    assert len(qualification_set_digest(QualificationSet(cases=(case,)))) == 64


def test_a_case_carries_its_research_brief_as_the_pins_canonical_text(
    tmp_path: Path,
) -> None:
    """§96: a CP-DR case declares its brief as an object; the loader carries it
    as the canonical text a pin stores, the digest moves with it, and a brief
    that is not an object, or that no pin could store, refuses the file."""
    manifest = _manifest()
    cases = manifest["cases"]
    assert isinstance(cases, list)
    cases[0]["research_brief"] = research_brief()
    loaded = load_qualification_set(_write(tmp_path, manifest))
    assert loaded.cases[0].research_brief == research_text(research_brief())
    assert loaded.cases[1].research_brief is None
    assert qualification_set_digest(loaded) != qualification_set_digest(_in_memory())
    changed = research_brief(decision_context="Another premise")
    cases[0]["research_brief"] = changed
    assert qualification_set_digest(
        load_qualification_set(_write(tmp_path, manifest))
    ) != qualification_set_digest(loaded)
    for bad in (["not", "an", "object"], {"x": float("nan")}, "text"):
        cases[0]["research_brief"] = bad
        with pytest.raises(Refusal) as refused:
            load_qualification_set(_write(tmp_path, manifest))
        assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID


def test_a_case_states_its_command_and_an_unknown_qualifier_refuses_the_file(
    tmp_path: Path,
) -> None:
    """D109: a case's `qualifiers` and `objective` are read by the pin's own
    closed rule, carried as the pin takes them, and covered by the digest."""
    manifest = _manifest()
    first = _first(manifest)
    first["qualifiers"] = {"CP-2G": {"cases": "base/upside/downside"}}
    first["objective"] = "Refinancing decision"
    loaded = load_qualification_set(_write(tmp_path, manifest))
    assert loaded.cases[0].qualifiers == (("CP-2G", "cases", "base/upside/downside"),)
    assert loaded.cases[0].objective == "Refinancing decision"
    assert (loaded.cases[1].qualifiers, loaded.cases[1].objective) == ((), None)
    assert qualification_set_digest(loaded) != qualification_set_digest(_in_memory())
    first["objective"] = "Another decision"
    assert qualification_set_digest(
        load_qualification_set(_write(tmp_path, manifest))
    ) != qualification_set_digest(loaded)
    for key, bad in (
        ("qualifiers", {"CP-2G": {"horizon": "FY27"}}),
        ("qualifiers", {"CP-9": {"cases": "base"}}),
        ("qualifiers", ["CP-2G"]),
        ("objective", 7),
        ("objective", "two\nlines"),
    ):
        amended = _manifest()
        _first(amended)[key] = bad
        with pytest.raises(Refusal) as refused:
            load_qualification_set(_write(tmp_path, amended))
        assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID


def _first(manifest: dict[str, object]) -> dict[str, Any]:
    """The manifest's first case, typed, so a test can amend one field of it."""
    cases = manifest["cases"]
    assert isinstance(cases, list)
    case = cases[0]
    assert isinstance(case, dict)
    return case


def test_a_forecast_value_that_is_not_two_strings_is_refused(tmp_path: Path) -> None:
    """FP-08 and AR-25: `ForecastValue(**_closed(...))` took whatever JSON carried.

    A float loaded as a float, so a key no host value could ever equal was paid
    for and then read as a model miss; `NaN` made the digest raise an untyped
    `ValueError`; and a list name reached the first ambiguity check unhashable.
    The annotations say two strings, and the loader is where that becomes true.
    """
    malformed: tuple[dict[str, Any], ...] = (
        {"name": "revenue.total", "value": 1240.0},
        {"name": "revenue.total", "value": float("nan")},
        {"name": [], "value": {}},
        {"name": "revenue.total", "value": ""},
    )
    for value in malformed:
        manifest = _manifest()
        case = _first(manifest)
        case["model_extension"] = True
        case["forecast"] = {
            "scenario": "BASE",
            "period_id": "FY2027",
            "values": [value],
            "currency": "GBP",
            "scale": "millions",
            "perimeter": "GROUP",
            "qa_status": "Passed",
            "limitation_flags": [],
            "readiness": [],
        }
        with pytest.raises(Refusal) as refused:
            load_qualification_set(_write(tmp_path, manifest))
        assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID


def test_a_quote_carrying_a_nul_is_refused_before_anything_is_spent(
    tmp_path: Path,
) -> None:
    """FP-08: `matched_text` was unbounded and could carry a NUL.

    The key passed `prepare`, the whole route was paid for, and then
    `record_performed` failed with psycopg's `UntranslatableCharacter` --
    surfacing as `STORE_UNAVAILABLE`, with the snapshot lost and no capture
    written.
    """
    manifest = _manifest()
    _first(manifest)["expects"][0]["matched_text"] = "Total debt\x00here"
    with pytest.raises(Refusal) as refused:
        load_qualification_set(_write(tmp_path, manifest))
    assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID


def test_only_a_methodology_refusal_may_be_declared(tmp_path: Path) -> None:
    """FP-01: the loader accepted any `RefusalCode` at all.

    A set could declare `STORE_UNAVAILABLE` as its expected result and be signed
    when one happened, which is qualifying an outage rather than a reading.
    """
    manifest = _manifest()
    _first(manifest)["expected_refusal"] = "STORE_UNAVAILABLE"
    with pytest.raises(Refusal) as refused:
        load_qualification_set(_write(tmp_path, manifest))
    assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID

    _first(manifest)["expected_refusal"] = "HANDOFF_BLOCKED"
    [case, _other] = load_qualification_set(_write(tmp_path, manifest)).cases
    assert case.expected_refusal is RefusalCode.HANDOFF_BLOCKED


def test_the_set_is_bounded_before_its_documents_are_read(tmp_path: Path) -> None:
    """AR-09: `_case` read and retained every listed document eagerly.

    Each read was bounded on its own; the count and the total were not, so a
    manifest listing one allowed file fifty-one times loaded fifty-one copies of
    it before `admit_pack`'s ceiling refused the fifty-first.
    """
    from caos.evidence.extract import DEFAULT_LIMITS
    from caos.qualification.on_disk import MAX_SET_BYTES, MAX_SET_DOCUMENTS

    assert MAX_SET_DOCUMENTS >= DEFAULT_LIMITS.max_documents
    assert MAX_SET_BYTES == DEFAULT_LIMITS.max_pack_bytes
    manifest = _manifest()
    _first(manifest)["documents"] = ["documents/acme-2026/report.txt"] * (
        DEFAULT_LIMITS.max_documents + 1
    )
    with pytest.raises(Refusal) as refused:
        load_qualification_set(_write(tmp_path, manifest))
    assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID


def test_a_symlinked_document_is_recorded_under_its_declared_name(
    tmp_path: Path,
) -> None:
    """FP-27: the filename came from the resolved target, and the digest covers
    the filename -- so a set naming `report.txt` digested `other.txt`."""
    root = _write(tmp_path, _manifest())
    target = root / "documents" / "acme-2026" / "other.txt"
    target.write_bytes(REPORT)
    linked = root / "documents" / "acme-2026" / "report.txt"
    linked.unlink()
    linked.symlink_to(target)

    [case, _other] = load_qualification_set(root).cases
    assert case.documents[0].filename.value == "report.txt"


@pytest.mark.parametrize("key", ["expects_ready", "expects_blocked"])
def test_an_over_long_readiness_id_is_a_malformed_manifest(
    tmp_path: Path, key: str
) -> None:
    """DQ-14: `_ready` called `BoundaryText.of` outside the retyping `_bounded`
    applies, so a 200-character module id leaked `BOUNDARY_TEXT_TOO_LONG` where
    every other string the loader bounds is the manifest's own refusal."""
    manifest = _manifest()
    _first(manifest)[key] = ["C" * 200]
    with pytest.raises(Refusal) as refused:
        load_qualification_set(_write(tmp_path, manifest))
    assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID


def test_a_refusal_no_run_ends_in_is_refused_at_load(tmp_path: Path) -> None:
    """DQ-2: a node refusal leaves its run RUNNING, so a declared
    CITATION_NOT_LOCATED could never be met however the run went, and the set
    was paid for anyway. The loader refuses it with the file's own code."""
    manifest = _manifest()
    _first(manifest)["expected_refusal"] = "CITATION_NOT_LOCATED"
    with pytest.raises(Refusal) as refused:
        load_qualification_set(_write(tmp_path, manifest))
    assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID


# D101: a figure key may name the other whole lines that state its figures.
# REPORT's title line stands in for one: the mechanism is what is tested, not
# whether the line states the figure (the committed sets are judged by hand).
_KEY_LINE = "Total debt at 31 December 2026 was USD 1,240.0m"
_ALTERNATIVE = "Acme Holdings plc annual report 2026"


def _keyed(*alternatives: str, module_id: str = "CP-1B") -> ExpectedCitation:
    return ExpectedCitation(
        module_id=module_id,
        document_sha256=sha256(REPORT).hexdigest(),
        matched_text=_KEY_LINE,
        alternatives=tuple(
            AlternativeLine(sha256(REPORT).hexdigest(), text) for text in alternatives
        ),
    )


def _alternative_manifest(alternatives: object) -> dict[str, object]:
    """`_manifest()` with its first key's line made whole and `alternatives`
    set on it."""
    manifest = _manifest()
    cases = manifest["cases"]
    assert isinstance(cases, list)
    first = dict(cases[0])
    first["expects"] = [
        {
            "module_id": "CP-0",
            "document_sha256": sha256(REPORT).hexdigest(),
            "matched_text": _KEY_LINE,
            "alternatives": alternatives,
        }
    ]
    return {"cases": [first, cases[1]]}


def test_an_alternative_line_meets_its_key_under_its_own_module() -> None:
    """R3's CP-1B cited the 10-Q's net revenues row for the release's: the same
    figures, another line. Named as an alternative, that citation meets the
    key, compared as the exact string it is."""
    expect = _keyed(_ALTERNATIVE)
    document = sha256(REPORT).hexdigest()

    assert key_lines(expect) == ((document, _KEY_LINE), (document, _ALTERNATIVE))
    assert _matches(expect, {("CP-1B", document, _ALTERNATIVE)})
    assert _matches(expect, {("CP-1B", document, _KEY_LINE)})
    assert not _matches(expect, {("CP-1B", document, _ALTERNATIVE + ".")})
    assert not _matches(expect, {("CP-1B", "c" * 64, _ALTERNATIVE)})


def test_another_modules_citation_of_an_alternative_does_not_meet_the_key() -> None:
    """Keys stay module-bound: the right line under the wrong module answers a
    different question, for an alternative as for the key's own line."""
    document = sha256(REPORT).hexdigest()

    assert not _matches(_keyed(_ALTERNATIVE), {("CP-1", document, _ALTERNATIVE)})


def _cited(matched_text: str, line_text: str | None) -> AnchoredCitation:
    return AnchoredCitation(
        document_sha256=sha256(REPORT).hexdigest(),
        page=1,
        matched_text=matched_text,
        bboxes=(),
        line_text=line_text,
    )


def test_an_excerpt_meets_the_key_its_line_is_under_the_keys_module() -> None:
    """D105: a citation is any excerpt of one line, and a key is met by the
    line it anchored in (`cited_line`), never by the quote -- for the key's own
    line and for an alternative. The same line under another module does not
    meet it, and an excerpt of another line does not either."""
    document = sha256(REPORT).hexdigest()
    excerpt = _cited("Total debt at 31 December 2026 was USD", _KEY_LINE)
    other = _cited("annual report 2026 of Acme Holdings plc here", _ALTERNATIVE)
    elsewhere = _cited("Total debt at 31 December 2026 was USD", "Total debt at 31")

    assert cited_line(excerpt) == _KEY_LINE
    assert _matches(_keyed(), {("CP-1B", document, cited_line(excerpt))})
    assert _matches(_keyed(_ALTERNATIVE), {("CP-1B", document, cited_line(other))})
    assert not _matches(_keyed(), {("CP-1", document, cited_line(excerpt))})
    assert not _matches(_keyed(), {("CP-1B", document, cited_line(elsewhere))})


def test_a_record_from_before_excerpts_is_scored_by_its_quote() -> None:
    """A record accepted under an earlier rule keeps no line (EX1), and its
    quote is what it was scored by: its whole line meets the key, and a run
    inside the line -- which `ANY_RUN` accepted -- still does not."""
    document = sha256(REPORT).hexdigest()
    whole = _cited(_KEY_LINE, None)
    partial = _cited("Total debt at 31 December 2026 was USD", None)

    assert cited_line(whole) == _KEY_LINE
    assert _matches(_keyed(), {("CP-1B", document, cited_line(whole))})
    assert not _matches(_keyed(), {("CP-1B", document, cited_line(partial))})


def test_a_key_without_alternatives_is_met_only_by_its_own_line() -> None:
    """A statement key carries no alternative and is the exact key it was, and
    a set of such keys binds the digest it bound before D101."""
    expect = _keyed()
    document = sha256(REPORT).hexdigest()

    assert expect.alternatives == ()
    assert key_lines(expect) == ((document, _KEY_LINE),)
    assert not _matches(expect, {("CP-1B", document, _ALTERNATIVE)})
    assert qualification_set_digest(_in_memory()) == (
        "64bc178c0010b0fe104e01f4f7fac2bce35d1dc09f21fea86ff996aa99233373"
    )


def test_a_manifest_without_alternatives_loads_as_before(on_disk: Path) -> None:
    """Absent is no alternative: every manifest written before D101 loads."""
    loaded = load_qualification_set(on_disk)

    assert all(
        expect.alternatives == () for case in loaded.cases for expect in case.expects
    )


def test_a_manifest_alternative_is_read_and_bound_by_the_digest(
    tmp_path: Path,
) -> None:
    """An alternative is part of the answer key, so adding one moves the
    digest; the order an author lists them in does not."""
    other = "Borealis Industries plc annual report 2026"
    document = sha256(REPORT).hexdigest()
    one = load_qualification_set(
        _write(
            tmp_path / "one",
            _alternative_manifest(
                [{"document_sha256": document, "matched_text": _ALTERNATIVE}]
            ),
        )
    )
    both = [
        {"document_sha256": document, "matched_text": _ALTERNATIVE},
        {"document_sha256": sha256(OTHER).hexdigest(), "matched_text": other},
    ]
    forward = load_qualification_set(
        _write(tmp_path / "forward", _alternative_manifest(both))
    )
    backward = load_qualification_set(
        _write(tmp_path / "backward", _alternative_manifest(both[::-1]))
    )
    bare = load_qualification_set(_write(tmp_path / "bare", _manifest()))

    assert one.cases[0].expects[0].alternatives == (
        AlternativeLine(document, _ALTERNATIVE),
    )
    digests = {qualification_set_digest(item) for item in (one, forward, bare)}
    assert len(digests) == 3
    assert qualification_set_digest(forward) == qualification_set_digest(backward)


@pytest.mark.parametrize(
    "alternatives",
    [
        [],
        "not a list",
        [{"document_sha256": "a" * 64}],
        [{"document_sha256": "a" * 64, "matched_text": "x", "page": 1}],
        [{"document_sha256": "a" * 64, "matched_text": " "}],
        [{"document_sha256": "", "matched_text": _ALTERNATIVE}],
        [{"document_sha256": "a" * 64, "matched_text": "x\u202ey"}],
        [
            {"document_sha256": "a" * 64, "matched_text": _ALTERNATIVE},
            {"document_sha256": "a" * 64, "matched_text": _ALTERNATIVE},
        ],
        [{"document_sha256": sha256(REPORT).hexdigest(), "matched_text": _KEY_LINE}],
    ],
)
def test_a_malformed_alternative_is_refused_at_load(
    tmp_path: Path, alternatives: object
) -> None:
    """Closed when present, as every declared object is: a blank, unbounded or
    repeated line, or the key's own line restated, is not a second answer."""
    with pytest.raises(Refusal) as refused:
        load_qualification_set(_write(tmp_path, _alternative_manifest(alternatives)))

    assert refused.value.code is RefusalCode.QUALIFICATION_SET_FILE_INVALID


def test_a_partial_alternative_is_not_one_whole_evidence_line() -> None:
    """The committed-set check holds every alternative to F475, as it holds a
    key: a run of words inside a line is found once and is no whole line, so a
    committed set naming it fails as a set naming a partial key does."""
    pages = _pages(REPORT)

    assert _whole_lines(pages, _KEY_LINE) == 1
    assert _whole_lines(pages, "Total debt at 31 December 2026") == 0


def test_an_alternative_answering_another_key_of_its_module_is_ambiguous() -> None:
    """One citation must not meet two keys of one module: an alternative that is
    another key's line there is refused before anything is scored. Under a
    different module the same line is an ordinary second question."""
    document = sha256(REPORT).hexdigest()
    title = ExpectedCitation("CP-1B", document, _ALTERNATIVE)

    def keyed(*expects: ExpectedCitation) -> QualificationSet:
        case = _in_memory().cases[0]
        return QualificationSet(cases=(replace(case, expects=expects),))

    with pytest.raises(Refusal) as refused:
        assert_unambiguous(keyed(_keyed(_ALTERNATIVE), title))
    assert refused.value.code is RefusalCode.QUALIFICATION_SET_AMBIGUOUS
    shared = ExpectedCitation(
        "CP-1B",
        document,
        "Borealis Industries plc annual report 2026",
        alternatives=(AlternativeLine(document, _ALTERNATIVE),),
    )
    with pytest.raises(Refusal) as twice:
        assert_unambiguous(keyed(_keyed(_ALTERNATIVE), shared))
    assert twice.value.code is RefusalCode.QUALIFICATION_SET_AMBIGUOUS
    assert_unambiguous(keyed(_keyed(_ALTERNATIVE), replace(title, module_id="CP-1")))
