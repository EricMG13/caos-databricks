#!/usr/bin/env python3
"""A quality record of one accepted handoff, and a comparison against a baseline.

`extract <artifact> --set <set-dir> [--record <record>]` prints one handoff's
JSON record: front matter, H2 headings, the registers its module's contract
requires and the rows of each found, tagged interface tables, citations and how
many anchor, which of the set's answer keys it meets, and how many distinct
figures its tables hold. `compare <baseline> <records>` reports per module what
moved, LARGE differences under their own heading (the rules are in
`docs/rebuild/quality/2026-10-03-baseline.md`). It informs; it exits non-zero
only on a usage error.

Read by the host's own readers, never restated: `matrix.module_registers`,
`tables.handoff_tables`, the vendor's `parse_restricted_frontmatter`, and four
private names called from here -- `matrix._matches`, `matrix._matches_projection`
and `matrix._matches_register` (the matrix's key predicates) and
`handoff._decoded_record` (the host record: anchored citations, projections,
CP-0's readiness). No document text is written beyond the quotes the set's own
answer keys carry; a citation is counted, never copied.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from caos.graph.route import READY
from caos.methodology.bundle import Bundle, verified_bytes
from caos.methodology.handoff import GATE_MODULE, CanonicalRecord, _decoded_record
from caos.methodology.tables import handoff_tables
from caos.methodology.vendor import VendorContract, load_vendor_contract
from caos.qualification.matrix import (
    QualificationCase,
    _matches,
    _matches_projection,
    _matches_register,
    module_registers,
)
from caos.qualification.on_disk import load_qualification_set
from caos.refusals import Refusal

BUNDLE = Path(__file__).resolve().parents[1] / "vendor" / "deploy-v"

# Worst last. The vendor's vocabularies (`validate_handoff.QA_STATUSES`,
# `COMMITTEE_STATUSES`) are sets; this is the order a reader ranks them in.
QA_ORDER = ("Passed", "Restricted", "Blocked")
COMMITTEE_ORDER = (
    "Committee Ready",
    "Draft Only",
    "Requires More Work",
    "Insufficient Information",
    "Restricted",
    "Blocked",
)
CONFIDENCE_DROP = 10
ANCHORED_FALL = 0.5
# A later answer whose distinct figures fall below this share of the baseline's
# lowest, and by at least `FIGURES_FLOOR`, has lost facts, not duplicates (5d-2
# review, M2). The floor keeps one year or page cell from flagging an answer
# with few figures (CP-0's baseline holds 4 to 10).
FIGURES_FALL = 0.8
FIGURES_FLOOR = 5
# A table cell that is one figure: `2,993`, `(573)`, `-335`, `$1,240.0`, `30.7%`.
_FIGURE = re.compile(r"\(?\s*[-\u2212]?\s*\$?\s*\d[\d,]*(?:\.\d+)?\s*%?\s*\)?")
_CELL_SPLIT = re.compile(r"(?<!\\)\|")
_SEPARATOR_CELL = re.compile(r":?-+:?")

_H2 = re.compile(r"^## +(.+?)\s*$", re.MULTILINE)
_FRONT_MATTER = (
    "qa_status",
    "confidence_score",
    "confidence_band",
    "committee_status",
    "limitation_flags",
)


# Why a command cannot be answered. Fixed words, so nothing read from a file
# reaches the terminal.
ARTIFACT_UNREADABLE = "the artifact is not a handoff"
RECORD_OTHER_MODULE = "the record names another module"
RECORD_UNREADABLE = "the record does not parse"
RECORD_OTHER_ARTIFACT = "the record is bound to another artifact"
SET_NO_CASE = "the set has no single case for this handoff's route"
JSON_NOT_RECORDS = "a JSON file holds neither a record nor an artifacts list"
FILE_UNREADABLE = "a file does not read"


class UsageError(Exception):
    """A command the tool cannot answer: a wrong file, or another's record."""


def extract_record(
    artifact: bytes,
    set_dir: Path,
    *,
    record: bytes | None = None,
    bundle: Bundle | None = None,
) -> dict[str, Any]:
    """One accepted handoff's quality record, as `extract` prints it."""
    bundle = bundle if bundle is not None else Bundle(BUNDLE)
    contract = load_vendor_contract(bundle)
    try:
        text = artifact.decode("utf-8")
        fields, body = contract.validate_handoff.parse_restricted_frontmatter(text)
    except (UnicodeDecodeError, ValueError) as unreadable:
        raise UsageError(ARTIFACT_UNREADABLE) from unreadable
    module_id = str(fields.get("module_id", ""))
    stored = _record(artifact, record)
    if stored is not None and stored.identity.module_id != module_id:
        raise UsageError(RECORD_OTHER_MODULE)
    case = _case(set_dir, fields)
    required, found = _registers(contract, bundle, module_id, text)
    tables = handoff_tables(contract, text)
    return {
        "set": set_dir.name,
        "case_label": case.label,
        "module_id": module_id,
        "build": fields.get("credit_os_authority_bundle_sha256"),
        "reader_build": bundle.build_id,
        "artifact_sha256": sha256(artifact).hexdigest(),
        "bytes": len(artifact),
        "front_matter": {name: fields.get(name) for name in _FRONT_MATTER},
        "h2": _H2.findall(contract.validate_handoff.unfenced_markdown(body)),
        "required_registers": required,
        "registers": None
        if found is None
        else {
            register: len(rows) for register, (_header, rows) in sorted(found.items())
        },
        "tables": {table.table_id: len(table.rows) for table in tables.tables},
        "tables_unavailable": tables.unavailable_reason,
        "distinct_figures": distinct_figures(
            contract.validate_handoff.unfenced_markdown(body)
        ),
        "citations": _citations(stored),
        "answer_keys": _answer_keys(case, module_id, stored, registers_found=found),
    }


def distinct_figures(markdown: str) -> int:
    """How many different figures the handoff's tables hold.

    Every body cell of every pipe table that is a single figure counts once by
    its magnitude, so `(335)`, `-335` and `335` are one figure and a table that
    only repeats figures held elsewhere adds none: removing a duplicate never
    lowers the count, losing a fact found nowhere else does.
    """
    figures: set[str] = set()
    header = True
    for line in markdown.splitlines():
        row = line.strip()
        if not row.startswith("|"):
            header = True
            continue
        cells = [cell.strip() for cell in _CELL_SPLIT.split(row.strip("|"))]
        if header or all(_SEPARATOR_CELL.fullmatch(cell) for cell in cells):
            header = False
            continue
        figures.update(filter(None, map(_figure, cells)))
    return len(figures)


def _figure(cell: str) -> str | None:
    if not _FIGURE.fullmatch(cell):
        return None
    digits = re.sub(r"[^\d.]", "", cell)
    try:
        return format(Decimal(digits).normalize(), "f")
    except InvalidOperation:
        return None


def _record(artifact: bytes, record: bytes | None) -> CanonicalRecord | None:
    """The host record beside the artifact, bound to it, or None if not given."""
    if record is None:
        return None
    try:
        stored = _decoded_record(record)
    except (ValueError, TypeError, UnicodeDecodeError) as unreadable:
        raise UsageError(RECORD_UNREADABLE) from unreadable
    if stored.artifact_sha256 != sha256(artifact).hexdigest():
        raise UsageError(RECORD_OTHER_ARTIFACT)
    return stored


def _case(set_dir: Path, fields: Mapping[str, Any]) -> QualificationCase:
    """The one case of the set run on this handoff's profile and selection."""
    try:
        cases = load_qualification_set(set_dir).cases
    except Refusal as refused:
        raise UsageError(refused.code.value) from None
    matching = [
        case
        for case in cases
        if case.profile_id == fields.get("credit_os_profile_id")
        and case.selection_id == fields.get("credit_os_selection_id")
    ]
    if len(matching) != 1:
        raise UsageError(SET_NO_CASE)
    return matching[0]


def _registers(
    contract: VendorContract, bundle: Bundle, module_id: str, text: str
) -> tuple[list[str], dict[str, Any] | None]:
    """The registers the module's contract requires, and what the reader found.

    None for what it found when the module declares no register contract or the
    reader refused the handoff: unmeasured, never "no registers".
    """
    try:
        skill = verified_bytes(bundle, module_id, "SKILL.md").decode("utf-8")
        declared = contract.completeness_check.load_contract(skill, module_id)
        found = module_registers(contract, bundle, module_id, text)
    except (Refusal, ValueError, TypeError, UnicodeDecodeError):
        return [], None
    return sorted(declared["registers"]), found


def _citations(stored: CanonicalRecord | None) -> dict[str, int] | None:
    if stored is None:
        return None
    return {
        "count": len(stored.citations),
        "anchored": sum(1 for citation in stored.citations if citation.bboxes),
    }


def _answer_keys(
    case: QualificationCase,
    module_id: str,
    stored: CanonicalRecord | None,
    *,
    registers_found: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Every answer key of the case aimed at this module, and whether it is met.

    `met` is None where this artifact cannot answer the key: no record beside
    it, or registers the reader could not locate. Readiness keys are CP-0's,
    read from its record as `route.readiness_from` reads them.
    """
    return (
        _citation_keys(case, module_id, stored)
        + _ready_keys(case, module_id, stored)
        + _projection_keys(case, module_id, stored)
        + _register_keys(case, module_id, registers_found)
    )


def _citation_keys(
    case: QualificationCase, module_id: str, stored: CanonicalRecord | None
) -> list[dict[str, Any]]:
    cited = (
        None
        if stored is None
        else {(module_id, c.document_sha256, c.matched_text) for c in stored.citations}
    )
    return [
        _key(
            "expects",
            [expect.module_id, expect.document_sha256, expect.matched_text],
            None if cited is None else _matches(expect, cited),
        )
        for expect in case.expects
        if expect.module_id == module_id
    ]


def _ready_keys(
    case: QualificationCase, module_id: str, stored: CanonicalRecord | None
) -> list[dict[str, Any]]:
    if module_id != GATE_MODULE:
        return []
    readiness = None if stored is None else dict(stored.projections.readiness)
    return [
        _key(
            "expects_ready",
            [ready],
            None if readiness is None else readiness.get(ready) in READY,
        )
        for ready in case.expects_ready
    ]


def _projection_keys(
    case: QualificationCase, module_id: str, stored: CanonicalRecord | None
) -> list[dict[str, Any]]:
    return [
        _key(
            "expects_projection",
            [projection.module_id, projection.field, projection.value],
            None
            if stored is None
            else _matches_projection(stored.projections, projection),
        )
        for projection in case.expects_projection
        if projection.module_id == module_id
    ]


def _register_keys(
    case: QualificationCase, module_id: str, found: dict[str, Any] | None
) -> list[dict[str, Any]]:
    return [
        _key(
            "expects_register",
            [
                register.module_id,
                register.register_id,
                [list(pair) for pair in register.row_key],
                register.column,
                register.expected,
            ],
            None if found is None else _matches_register(found, register),
        )
        for register in case.expects_register
        if register.module_id == module_id
    ]


def _key(kind: str, key: list[Any], met: bool | None) -> dict[str, Any]:
    return {"kind": kind, "key": key, "met": met}


def compare_records(
    baseline: Sequence[Mapping[str, Any]], records: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Each record against the baseline answers for its module and set.

    One entry per record: `changes` (every line a reader would want) and
    `large` (the subset LARGE flags). A record with no baseline answer for its
    module and set has a single change saying so.
    """
    return [_compared(record, _references(baseline, record)) for record in records]


def _references(
    baseline: Sequence[Mapping[str, Any]], record: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    return [
        item
        for item in baseline
        if item.get("module_id") == record.get("module_id")
        and item.get("set") == record.get("set")
    ]


def _compared(
    record: Mapping[str, Any], references: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    head = {
        "module_id": record.get("module_id"),
        "set": record.get("set"),
        "artifact_sha256": record.get("artifact_sha256"),
        "baseline_answers": len(references),
    }
    if not references:
        return {
            **head,
            "changes": ["no baseline answer for this module and set"],
            "large": [],
        }
    changes: list[str] = []
    large: list[str] = []
    for part in (
        _register_moves,
        _status_moves,
        _citation_moves,
        _key_moves,
        _figure_moves,
        _byte_moves,
    ):
        part_changes, part_large = part(record, references)
        changes += part_changes
        large += part_large
    return {**head, "changes": changes, "large": large}


Moves = tuple[list[str], list[str]]


def _always(
    references: Iterable[Mapping[str, Any]],
    read: Callable[[Mapping[str, Any]], set[Any]],
) -> set[Any]:
    sets = [read(item) for item in references]
    return set.intersection(*sets) if sets else set()


def _register_moves(
    record: Mapping[str, Any], references: Sequence[Mapping[str, Any]]
) -> Moves:
    if record.get("registers") is None:
        return ["registers unmeasured (the reader refused this handoff)"], []
    now = record["registers"]
    required = set(record.get("required_registers") or ())
    always = _always(references, lambda item: set(item.get("registers") or {}))
    ever = set().union(*(set(item.get("registers") or {}) for item in references))
    changes: list[str] = []
    large: list[str] = []
    for register in sorted(always - set(now)):
        still = register in required
        line = f"register {register} dropped" + (" (still required)" if still else "")
        changes.append(line)
        if still:
            large.append(line)
    changes += [f"register {register} added" for register in sorted(set(now) - ever)]
    for register in sorted(set(now) & ever):
        rows = [
            item["registers"][register]
            for item in references
            if register in (item.get("registers") or {})
        ]
        if not min(rows) <= now[register] <= max(rows):
            changes.append(
                f"register {register} rows {now[register]} (baseline {_span(rows)})"
            )
    return changes, large


def _span(values: Sequence[int | float]) -> str:
    low, high = min(values), max(values)
    return f"{low}" if low == high else f"{low}-{high}"


def _rank(order: Sequence[str], value: object) -> int | None:
    return order.index(value) if value in order else None


def _status_moves(
    record: Mapping[str, Any], references: Sequence[Mapping[str, Any]]
) -> Moves:
    changes: list[str] = []
    large: list[str] = []
    for name, order in (("qa_status", QA_ORDER), ("committee_status", COMMITTEE_ORDER)):
        line, worse = _status_move(name, order, record, references)
        changes += [line] if line else []
        large += [line] if line and worse else []
    line, fell = _confidence_move(record, references)
    changes += [line] if line else []
    large += [line] if line and fell else []
    return changes, large


def _front(item: Mapping[str, Any], name: str) -> object:
    return (item.get("front_matter") or {}).get(name)


def _status_move(
    name: str,
    order: Sequence[str],
    record: Mapping[str, Any],
    references: Sequence[Mapping[str, Any]],
) -> tuple[str | None, bool]:
    """A status outside the baseline's, and whether it is worse than its worst."""
    was = [_front(item, name) for item in references]
    now = _front(record, name)
    if now in was:
        return None, False
    ranks = [rank for value in was if (rank := _rank(order, value)) is not None]
    rank = _rank(order, now)
    line = f"{name} {now} (baseline {sorted(set(map(str, was)))})"
    return line, rank is not None and bool(ranks) and rank > max(ranks)


def _confidence_move(
    record: Mapping[str, Any], references: Sequence[Mapping[str, Any]]
) -> tuple[str | None, bool]:
    """A score outside the baseline's range, and whether it fell by the margin."""
    scores = [
        score
        for item in references
        if isinstance(score := _front(item, "confidence_score"), int)
    ]
    score = _front(record, "confidence_score")
    if not isinstance(score, int) or not scores or min(scores) <= score <= max(scores):
        return None, False
    line = f"confidence_score {score} (baseline {_span(scores)})"
    return line, score <= min(scores) - CONFIDENCE_DROP


def _citation_moves(
    record: Mapping[str, Any], references: Sequence[Mapping[str, Any]]
) -> Moves:
    now = record.get("citations")
    was = [item["citations"] for item in references if item.get("citations")]
    if not was:
        return [], []
    if not now:
        return ["citations unmeasured (no record given)"], []
    changes: list[str] = []
    large: list[str] = []
    for field in ("count", "anchored"):
        values = [entry[field] for entry in was]
        if not min(values) <= now[field] <= max(values):
            changes.append(f"citations {field} {now[field]} (baseline {_span(values)})")
    lowest = min(entry["anchored"] for entry in was)
    if lowest and now["anchored"] <= lowest * ANCHORED_FALL:
        large.append(f"anchored citations {now['anchored']} (baseline low {lowest})")
    return changes, large


def _met_keys(item: Mapping[str, Any], met: bool) -> set[str]:
    return {
        json.dumps([key["kind"], key["key"]])
        for key in item.get("answer_keys") or ()
        if key.get("met") is met
    }


def _key_moves(
    record: Mapping[str, Any], references: Sequence[Mapping[str, Any]]
) -> Moves:
    met_now = _met_keys(record, True)
    missed_now = _met_keys(record, False)
    always = _always(references, lambda item: _met_keys(item, True))
    ever = set().union(*(_met_keys(item, True) for item in references))
    lost = sorted(always & missed_now)
    changes = [f"answer key lost: {key}" for key in lost]
    changes += [
        f"answer key lost (met by some baseline answers): {key}"
        for key in sorted((ever - always) & missed_now)
    ]
    changes += [f"answer key gained: {key}" for key in sorted(met_now - ever)]
    return changes, [f"answer key lost: {key}" for key in lost]


def _figure_moves(
    record: Mapping[str, Any], references: Sequence[Mapping[str, Any]]
) -> Moves:
    """Always reported; LARGE below `FIGURES_FALL` of the baseline's lowest and
    at least `FIGURES_FLOOR` under it."""
    now = record.get("distinct_figures")
    was = [
        item["distinct_figures"]
        for item in references
        if isinstance(item.get("distinct_figures"), int)
    ]
    if not isinstance(now, int):
        return ["distinct figures unmeasured"], []
    if not was:
        return [f"distinct figures {now} (baseline unmeasured)"], []
    line = f"distinct figures {now} (baseline {_span(was)})"
    if now < FIGURES_FALL * min(was) and now <= min(was) - FIGURES_FLOOR:
        return [line], [f"distinct figures {now} below 80% of baseline low {min(was)}"]
    return [line], []


def _byte_moves(
    record: Mapping[str, Any], references: Sequence[Mapping[str, Any]]
) -> Moves:
    sizes = [item["bytes"] for item in references if isinstance(item.get("bytes"), int)]
    now = record.get("bytes")
    if not sizes or not isinstance(now, int) or min(sizes) <= now <= max(sizes):
        return [], []
    return [f"bytes {now} (baseline {_span(sizes)})"], []


def render_report(compared: Sequence[Mapping[str, Any]]) -> str:
    """The comparison as text: LARGE first, then every change per module."""
    lines = ["LARGE"]
    flagged = [entry for entry in compared if entry["large"]]
    if not flagged:
        lines.append("  none")
    for entry in flagged:
        lines += [f"  {_title(entry)}"] + [f"    {line}" for line in entry["large"]]
    lines.append("")
    lines.append("Changes")
    for entry in compared:
        lines.append(
            f"  {_title(entry)} against {entry['baseline_answers']} baseline answer(s)"
        )
        lines += [f"    {line}" for line in entry["changes"]] or ["    none"]
    return "\n".join(lines) + "\n"


def _title(entry: Mapping[str, Any]) -> str:
    return f"{entry['module_id']} {entry['set']} {str(entry['artifact_sha256'])[:12]}"


def _artifacts(path: Path) -> list[Mapping[str, Any]]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as unreadable:
        raise UsageError(FILE_UNREADABLE) from unreadable
    if isinstance(loaded, dict) and isinstance(loaded.get("artifacts"), list):
        return list(loaded["artifacts"])
    if isinstance(loaded, dict) and "module_id" in loaded:
        return [loaded]
    raise UsageError(JSON_NOT_RECORDS)


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as unreadable:
        raise UsageError(FILE_UNREADABLE) from unreadable


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract", help="print one artifact's record")
    extract.add_argument("artifact", type=Path)
    extract.add_argument("--set", dest="set_dir", type=Path, required=True)
    extract.add_argument("--record", type=Path, help="the host record beside it")
    compare = commands.add_parser("compare", help="compare records to a baseline")
    compare.add_argument("baseline", type=Path)
    compare.add_argument("records", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "extract":
            record = None if args.record is None else _read(args.record)
            print(
                json.dumps(
                    extract_record(_read(args.artifact), args.set_dir, record=record),
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            compared = compare_records(
                _artifacts(args.baseline), _artifacts(args.records)
            )
            sys.stdout.write(render_report(compared))
    except UsageError as usage:
        print(f"quality_compare: {usage}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
