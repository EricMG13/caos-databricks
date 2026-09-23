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
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from canonical_fixtures import BUNDLE, CATALOG, research_brief

from caos.boundary_text import BoundaryText
from caos.evidence.citations import _match_at, _Token
from caos.evidence.extract import DEFAULT_LIMITS, dispatch_by_content
from caos.evidence.ingest import Document
from caos.graph.route import resolve_route
from caos.qualification.matrix import (
    ExpectedCitation,
    ExpectedForecast,
    ExpectedProjection,
    ExpectedRegister,
    ForecastValue,
    QualificationCase,
    QualificationSet,
    assert_measurable,
    assert_unambiguous,
    qualification_set_digest,
    unlocatable_register_keys,
)
from caos.qualification.on_disk import MANIFEST, load_qualification_set
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
COMMITTED_SET_DIGESTS = {
    "ba-fy2025": ("a30533b3530ed1e609ce33df67e50b4ce5e4f80167be4efc29f398b4c24a7bba"),
    "ccl-fy2025": "f5555753cf7b39868fa4885d95a0b80847c61204a4b3ebe5fffe8345587c327e",
    "ccl-fy2025-covenant-refinancing": (
        "726e28dad1498a56ed6692d09819834c9727ebbd23ec8bac619f31e61ba4ab8a"
    ),
    "ccl-fy2025-earnings-update": (
        "7f3619434a2697f10f5ea78d64a2e3e87c67691272037034235289a87507e275"
    ),
    "ccl-fy2025-liquidity": (
        "117dcda7edad142dc3ae4a33fc06376690f990eefc87f53fc2804d194d65a8c8"
    ),
    "ccl-fy2025-portfolio": (
        "7dcfa84602ff94a38fcc2627d15b7922acb08c23a871f7280e16bfe4a92d6a6c"
    ),
    "ccl-fy2025-full-relative-value": (
        "c834105e7c6e12d6e11996c3744eb414715aef07b549df11bbc9f7ba741977f2"
    ),
    "ccl-fy2025-relative-value": (
        "a8df0ccf6d8fd735886c584951f7ca82e460f483a4f235a5ad31143fd3f60ac8"
    ),
    "ccl-fy2025-lite-covenant-refinancing": (
        "4bc8aceaa622a76e930fa8aa419a349ffedd8ca681360571f5c8f2ee38c3aa9e"
    ),
    "ccl-fy2025-lite-full-credit-screen": (
        "a033b1f59bec2d61c887ab018fac8ef7ca22f048cf52c0c0d0f873d0bd53f13e"
    ),
    "ccl-fy2025-market-dislocation": (
        "502ca79ca3cda068f4621698f45f979e34e78945261b284c2ee232b2f57e11fe"
    ),
    "save-2024-distressed-restructuring": (
        "befe19de18cbf6374305882e7a812abeb2ec153038a1dff2a0e80e5674312166"
    ),
    "save-2024-lite-distressed-restructuring": (
        "f53523a15053a2d4f191408cddc600c1667837cbacade354468e0f58fb03c391"
    ),
    "f-fy2025": ("f7659a750e559db22b97ee3175aa5660819a65fef2d6735fae172126782a2fc2"),
    "vmo2-fy2025": "27b7df72963c877f707750adfb9e21d2bd42fbcdc1d8ac726cd5c2b53b4e4b07",
    "vmo2-fy2025-deep-research": (
        "09807efb1a3d5d40680d1a9d0e054333537781d7bb4013ecd7670323f817fd9b"
    ),
    "vmo2-fy2025-full-deep-research": (
        "1f15f91b746ee2bc58a9719ff5b5f0cb6a4328c827642bb384f8040ba8cfe3c2"
    ),
    "vmo2-fy2025-portfolio": (
        "a46a1b4f597885e8f6937b47f9da7eba5ec266f4a43818d5f9fa1d42337b87ea"
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


def test_every_committed_answer_key_names_its_route_and_exact_source() -> None:
    """No key can name an off-route module or an unreadable source quote."""
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
                document = documents[expected.document_sha256]
                if expected.document_sha256 not in extracted:
                    pages: dict[int, list[_Token]] = {}
                    for token in dispatch_by_content(document.data).extract(
                        document.data
                    ):
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
                    extracted[expected.document_sha256] = pages
                words = expected.matched_text.split()
                hits = sum(
                    bool(_match_at(tokens, start, words, normalised=False))
                    for tokens in extracted[expected.document_sha256].values()
                    for start in range(len(tokens))
                )
                assert hits == 1, expected


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
