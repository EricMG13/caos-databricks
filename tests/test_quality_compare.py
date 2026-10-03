"""`scripts/quality_compare.py`: one handoff's quality record, and the comparison
that flags a large fall against the pre-5d baseline."""

from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from canonical_fixtures import (
    BUNDLE,
    LITE_PROFILE,
    LITE_SELECTION,
    handoff_markdown,
    identity,
)

from caos.evidence.citations import AnchoredCitation, Rect
from caos.methodology.handoff import CanonicalRecord, Projections, record_bytes
from caos.qualification.on_disk import MANIFEST

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import quality_compare

REPORT = b"Total debt at 31 December 2026 was USD 1,240.0m.\nLeverage fell.\n"
CITED = "Total debt at 31 December 2026 was USD 1,240.0m."
NOT_CITED = "Leverage fell."


def _set(root: Path) -> Path:
    document = root / "documents" / "report.txt"
    document.parent.mkdir(parents=True)
    document.write_bytes(REPORT)
    digest = sha256(REPORT).hexdigest()
    case = {
        "label": "example-lite",
        "profile_id": LITE_PROFILE,
        "selection_id": LITE_SELECTION,
        "documents": ["documents/report.txt"],
        "expects": [
            {"module_id": "CP-0", "document_sha256": digest, "matched_text": quote}
            for quote in (CITED, NOT_CITED)
        ],
        "expects_ready": ["CP-5"],
    }
    (root / MANIFEST).write_text(json.dumps({"cases": [case]}), encoding="utf-8")
    return root


def _record(markdown: bytes, quotes: tuple[str, ...]) -> bytes:
    gate = identity("CP-0")
    box = Rect(page=1, x0=0.0, y0=0.0, x1=1.0, y1=1.0)
    return record_bytes(
        CanonicalRecord(
            artifact_sha256=sha256(markdown).hexdigest(),
            adapter_version="canonical-markdown-v3",
            build_id=BUNDLE.build_id,
            manifest_sha256="b" * 64,
            authority_bundle_sha256=gate.authority_bundle_sha256,
            authority_digest="d" * 64,
            delivered_authority_digest="e" * 64,
            identity=gate,
            lineage=(),
            projections=Projections(
                module_id="CP-0",
                qa_status="Passed",
                committee_status="Draft Only",
                confidence_score=90,
                confidence_band="High",
                limitation_flags=(),
                validation_warnings=(),
                downstream_consumers=(),
                readiness=(("CP-5", "READY"),),
                blockers=(),
                decision_scope="SCREENING_ONLY",
            ),
            citations=tuple(
                AnchoredCitation(
                    document_sha256=sha256(REPORT).hexdigest(),
                    page=1,
                    matched_text=quote,
                    bboxes=(box,),
                )
                for quote in quotes
            ),
        )
    )


def _extracted(
    root: Path, *, omit_register: str | None = None, quotes: tuple[str, ...]
) -> dict[str, Any]:
    markdown = handoff_markdown(
        identity("CP-0"), readiness={"CP-5": "READY"}, omit_register=omit_register
    )
    return quality_compare.extract_record(
        markdown, root, record=_record(markdown, quotes), bundle=BUNDLE
    )


def test_extract_record_reads_a_fixture_handoff_and_scores_its_answer_keys(
    tmp_path: Path,
) -> None:
    record = _extracted(_set(tmp_path), quotes=(CITED,))

    assert record["module_id"] == "CP-0"
    assert record["case_label"] == "example-lite"
    assert record["front_matter"]["qa_status"] == "Passed"
    assert record["front_matter"]["confidence_score"] == 90
    assert "Analysis" in record["h2"]
    assert set(record["registers"]) == set(record["required_registers"])
    assert "T8" in record["registers"]
    assert record["citations"] == {"count": 1, "anchored": 1}
    met = {
        (key["kind"], json.dumps(key["key"])): key["met"]
        for key in record["answer_keys"]
    }
    digest = sha256(REPORT).hexdigest()
    assert met[("expects", json.dumps(["CP-0", digest, CITED]))] is True
    assert met[("expects", json.dumps(["CP-0", digest, NOT_CITED]))] is False
    assert met[("expects_ready", json.dumps(["CP-5"]))] is True
    # A count, never the quote: the only quoted text is the key's own.
    assert CITED not in json.dumps(
        {k: v for k, v in record.items() if k != "answer_keys"}
    )


def test_compare_records_flags_a_dropped_register_and_a_lost_answer_key(
    tmp_path: Path,
) -> None:
    root = _set(tmp_path)
    baseline = _extracted(root, quotes=(CITED,))
    later = _extracted(root, omit_register="T3", quotes=(NOT_CITED,))

    [compared] = quality_compare.compare_records([baseline], [later])

    assert "register T3 dropped (still required)" in compared["large"]
    lost = json.dumps(["expects", ["CP-0", sha256(REPORT).hexdigest(), CITED]])
    assert f"answer key lost: {lost}" in compared["large"]
    gained = json.dumps(["expects", ["CP-0", sha256(REPORT).hexdigest(), NOT_CITED]])
    assert f"answer key gained: {gained}" in compared["changes"]
    report = quality_compare.render_report([compared])
    assert (
        report.index("LARGE")
        < report.index("register T3 dropped")
        < report.index("Changes")
    )


def test_compare_records_holds_a_baseline_answer_against_itself_quiet(
    tmp_path: Path,
) -> None:
    baseline = _extracted(_set(tmp_path), quotes=(CITED,))

    [compared] = quality_compare.compare_records([baseline], [baseline])

    assert compared["large"] == []
    assert compared["changes"] == []
    assert "LARGE\n  none" in quality_compare.render_report([compared])


def _answer(qa: str, committee: str, score: int, anchored: int) -> dict[str, Any]:
    front = {"qa_status": qa, "committee_status": committee, "confidence_score": score}
    return {
        **{"module_id": "CP-0", "set": "s", "artifact_sha256": "a" * 64, "bytes": 1},
        **{"registers": {}, "required_registers": [], "answer_keys": []},
        "front_matter": front,
        "citations": {"count": anchored, "anchored": anchored},
    }


def test_compare_records_flags_status_confidence_and_anchoring_falls() -> None:
    baseline = _answer("Passed", "Draft Only", 80, 8)
    later = _answer("Restricted", "Requires More Work", 70, 4)

    [compared] = quality_compare.compare_records([baseline], [later])

    assert [line.split()[0] for line in compared["large"]] == [
        "qa_status",
        "committee_status",
        "confidence_score",
        "anchored",
    ]
    # Inside the margins: reported, not LARGE.
    near = _answer("Passed", "Draft Only", 71, 5)
    [quiet] = quality_compare.compare_records([baseline], [near])
    assert quiet["large"] == []
    assert quiet["changes"]


def test_extract_record_unmeasured_without_a_record_refused_with_anothers(
    tmp_path: Path,
) -> None:
    markdown = handoff_markdown(identity("CP-0"), readiness={"CP-5": "READY"})
    root = _set(tmp_path)
    alone = quality_compare.extract_record(markdown, root, bundle=BUNDLE)
    assert alone["citations"] is None
    assert {key["met"] for key in alone["answer_keys"]} == {None}
    other = _record(markdown + b"\n", (CITED,))
    with pytest.raises(quality_compare.UsageError) as usage:
        quality_compare.extract_record(markdown, root, record=other, bundle=BUNDLE)
    assert str(usage.value) == quality_compare.RECORD_OTHER_ARTIFACT


def test_main_exits_two_on_a_usage_error_and_zero_on_a_comparison(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = _extracted(_set(tmp_path / "set"), quotes=(CITED,))
    path = tmp_path / "record.json"
    path.write_text(json.dumps({"artifacts": [record]}), encoding="utf-8")

    assert quality_compare.main(["compare", str(path), str(path)]) == 0
    assert "LARGE" in capsys.readouterr().out
    assert (
        quality_compare.main(["compare", str(tmp_path / "absent.json"), str(path)]) == 2
    )
