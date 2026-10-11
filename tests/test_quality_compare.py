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
    assert record["citations"] == {"count": 1, "anchored": 1, "unverified": 0}
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
    # Distinct figures are reported on every comparison, the total and the
    # count in the registers the module still requires (F482); nothing else moved.
    [line] = compared["changes"]
    figures = baseline["distinct_figures"]
    assert line.startswith(f"distinct figures {figures} (baseline {figures}); ")
    assert "in required registers" in line
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


def test_distinct_figures_count_facts_not_their_copies() -> None:
    """5d-2 review, M2: a removed table that only repeats figures held elsewhere
    leaves the count; a lost fact lowers it. Magnitude, so (335), -335 and 335
    are one figure; a locator, a date or a word is none."""
    table = (
        "| Line Item | Q2 2026 | Note |\n| --- | ---: | --- |\n"
        "| Revenue | 2,993 | 10-Q p. 2 |\n| Capex | (335) | 2026-06-30 |\n"
    )
    copy = "| Metric | Value |\n|---|---|\n| revenue | 2993 |\n| capex | -335 |\n"
    margin = "| KPI | Q2 2026 |\n|---|---|\n| Margin | 30.7% |\n"
    assert quality_compare.distinct_figures(table) == 2
    assert quality_compare.distinct_figures(table + "\n" + copy) == 2
    assert quality_compare.distinct_figures(table + "\n" + margin) == 3
    assert quality_compare.distinct_figures("| Revenue | 2,993 |\n") == 0


def test_compare_records_flags_a_fall_in_distinct_figures() -> None:
    baseline = {**_answer("Passed", "Draft Only", 80, 8), "distinct_figures": 100}
    lost = {**baseline, "distinct_figures": 79}
    [compared] = quality_compare.compare_records([baseline], [lost])
    assert compared["large"] == ["distinct figures 79 below 80% of baseline low 100"]
    kept = {**baseline, "distinct_figures": 96}
    [quiet] = quality_compare.compare_records([baseline], [kept])
    assert quiet["large"] == []
    assert quiet["changes"] == ["distinct figures 96 (baseline 100)"]
    unmeasured = dict(baseline)
    del unmeasured["distinct_figures"]
    [old] = quality_compare.compare_records([unmeasured], [kept])
    assert old["changes"] == ["distinct figures 96 (baseline unmeasured)"]


def test_a_fall_of_fewer_than_five_figures_is_never_large() -> None:
    """5d-2 review, round 2: CP-0's baselines hold 4 to 10 figures, where one
    year or page cell is 10-25%; a fall must also be at least five figures."""
    baseline = {**_answer("Passed", "Draft Only", 80, 8), "distinct_figures": 6}
    for now, large in ((4, False), (2, False), (1, True), (0, True)):
        [compared] = quality_compare.compare_records(
            [baseline], [{**baseline, "distinct_figures": now}]
        )
        assert bool(compared["large"]) is large, now
        assert f"distinct figures {now} (baseline 6)" in compared["changes"]
    big = {**baseline, "distinct_figures": 20}
    [compared] = quality_compare.compare_records(
        [big], [{**big, "distinct_figures": 15}]
    )
    assert compared["large"] == ["distinct figures 15 below 80% of baseline low 20"]


def _by_table(
    total: int,
    by_table: dict[str, list[str]],
    required: tuple[str, ...] = ("T1",),
    located: tuple[str, ...] = ("T1",),
) -> dict[str, Any]:
    return {
        **_answer("Passed", "Draft Only", 80, 8),
        "distinct_figures": total,
        "required_registers": list(required),
        "registers": dict.fromkeys(located, 1),
        "figures_by_table": by_table,
    }


def test_figures_leave_out_only_what_a_retired_register_alone_held() -> None:
    """F482: 5d-4 retired CP-0's P4, whose triage scores were most of a
    baseline answer's figures, so the whole-table count flagged each later
    answer LARGE. A figure found only in a register the new answer's module no
    longer requires leaves both sides; one also held elsewhere stays."""
    kept = [f"t{n}" for n in range(6)]
    scores = [f"p{n}" for n in range(10)]
    baseline = _by_table(
        17,
        {"P4": [*scores, "t0"], "T1": kept, "": ["front"]},
        required=("P4", "T1"),
        located=("P4", "T1"),
    )
    later = _by_table(7, {"T1": kept, "": ["front"]})
    [compared] = quality_compare.compare_records([baseline], [later])
    assert compared["large"] == []
    assert compared["changes"] == [
        "register P4 dropped",
        "distinct figures 7 (baseline 7); in required registers 6 (baseline 6)",
    ]
    # The whole-table count would have flagged it: 7 is below 80% of 17.
    whole = {k: v for k, v in later.items() if k != "figures_by_table"}
    [before] = quality_compare.compare_records([baseline], [whole])
    assert before["large"] == ["distinct figures 7 below 80% of baseline low 17"]
    # An ID no record's contract names (CP-1B's "#### T4.18 Debt (from CP-1)")
    # is not a retired register: its figures count.
    foreign = _by_table(7, {"T1": kept, "T4.18": ["front"]})
    [quiet] = quality_compare.compare_records([foreign], [later])
    assert quiet["changes"] == [
        "distinct figures 7 (baseline 7); in required registers 6 (baseline 6)"
    ]


def test_figures_outside_any_register_still_count() -> None:
    """F482 fix round (5d-5 review): counting only required registers was blind
    to a front table and a tagged interface table under no register heading;
    in N2's CP-1, dropping the "Reported Q2 changes" table and the operating
    KPI schedule's body took the total from 170 to 152. The total keeps every
    table, so the loss shows; it is LARGE once it passes the existing margin."""
    registers = [f"r{n}" for n in range(152)]
    front = [f"f{n}" for n in range(18)]
    baseline = _by_table(170, {"T1": registers, "": front})
    dropped = _by_table(152, {"T1": registers})
    [compared] = quality_compare.compare_records([baseline], [dropped])
    assert compared["changes"] == [
        "distinct figures 152 (baseline 170); in required registers 152 (baseline 152)"
    ]
    assert compared["large"] == []  # 152 is 89% of 170: reported, not LARGE
    small = _by_table(20, {"T1": registers[:4], "": front[:16]})
    [flagged] = quality_compare.compare_records(
        [small], [_by_table(4, {"T1": registers[:4]})]
    )
    assert flagged["large"] == ["distinct figures 4 below 80% of baseline low 20"]


def test_extract_record_keeps_each_table_s_figures_by_its_heading(
    tmp_path: Path,
) -> None:
    """F482: each table's figures under the register ID its heading leads with,
    read from the headings and not the contract, so a retired register keeps
    its label; "" for a table under no such heading. Truncated hashes, not
    printed (a small number is recoverable by trying every candidate)."""
    record = _extracted(_set(tmp_path), quotes=(CITED,))
    assert set(record["figures_by_table"]) >= set(record["registers"])
    markdown = (
        "**Reported** (USD m):\n\n| Measure | Q2 |\n|---|---|\n| Revenue | 2,993 |\n\n"
        "#### P4 — Triage register\n\n| Source | Score |\n|---|---|\n| 10-Q | 11 |\n\n"
        "### **T4.7** Normalized\n\n| Item | Value |\n|---|---|\n| Debt | (1,240) |"
        "\n| Cash | 1240 |\n"
    )
    digest = {n: sha256(n.encode()).hexdigest()[:16] for n in ("2993", "11", "1240")}
    assert quality_compare.table_figures(markdown) == {
        "": [digest["2993"]],
        "P4": [digest["11"]],
        "T4.7": [digest["1240"]],
    }
    assert "1240" not in json.dumps(quality_compare.table_figures(markdown))
    assert quality_compare.distinct_figures(markdown) == 3


def test_compare_says_answer_keys_unmeasured_without_a_record(
    tmp_path: Path,
) -> None:
    """F482 (5d-0 review): without the host record the citation, readiness and
    projection keys are unchecked, and the report says so by kind, not only
    "citations unmeasured"."""
    root = _set(tmp_path)
    baseline = _extracted(root, quotes=(CITED,))
    markdown = handoff_markdown(identity("CP-0"), readiness={"CP-5": "READY"})
    alone = quality_compare.extract_record(markdown, root, bundle=BUNDLE)
    [compared] = quality_compare.compare_records([baseline], [alone])
    assert "citations unmeasured (no record given)" in compared["changes"]
    assert (
        "answer keys unmeasured: 3 (no record given): expects 2, expects_ready 1"
        in compared["changes"]
    )
    assert compared["large"] == []
    [measured] = quality_compare.compare_records([baseline], [baseline])
    assert not any("unmeasured" in line for line in measured["changes"])
