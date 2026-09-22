"""A qualification set as a declared form on disk, and the loader that reads it.

`CLAUDE.md`'s Phase 10 ledger asked for this: a set that lives only in memory is
enough for a digest to be checkable and not enough for two people to be sure
they hold the same set, and once a case carried its documents as bytes, writing
one in Python stopped being reasonable at any real size.

**A directory, not a file.** A case carries documents, and documents are bytes.
Base64 inside one JSON file would make the set unreadable to the reviewer who is
supposed to check it; a directory lets them open the documents. So the form is a
manifest naming its cases, and the documents beside it:

    acme-q3/
      qualification.json
      documents/acme-2026/report.txt
      documents/borealis-2026/report.txt

**The digest does not move.** `qualification_set_digest` already covers each
document's filename and the hash of its bytes, so a set read from here digests
exactly as the same set built in Python -- which is the property that lets a
verdict's `qualification_set_sha256` name a directory someone is holding. The
loader adds nothing to the digest and takes nothing away; it only produces the
same dataclasses from bytes rather than from a literal.

**A document's filename is its path's last segment.** One field rather than two,
because two would be two things that can disagree and the digest covers the
filename -- a manifest that named a document `report.txt` while reading
`other.txt` would digest as the first and admit the second.

**Read the way a verdict is read.** The manifest is authored, possibly not here
and possibly years from now, so it gets the treatment `caos/qualification/
verdict.py` gives a signed document: a closed shape, undeclared keys refused,
nothing coerced. Malformed is one code because it has one remedy -- fix the
file. A path leaving the set's own directory is the exception, and is kept apart
because its remedy is not the same and neither is its seriousness.

**What it does not do.** It does not judge whether the set measures anything:
`assert_measurable` is the one place that rule lives (`matrix.py`), and the
harness applies it before it spends. A loader that re-stated it would be the
second copy that drifts.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from caos.boundary_text import BoundaryText
from caos.evidence.extract import DEFAULT_LIMITS
from caos.evidence.ingest import Document
from caos.qualification.matrix import (
    PROJECTION_FIELDS,
    ExpectedCitation,
    ExpectedForecast,
    ExpectedProjection,
    ExpectedRegister,
    ForecastValue,
    QualificationCase,
    QualificationSet,
)
from caos.refusals import Refusal, RefusalCode
from caos.store.run_inputs import RunSubject, research_text, valid_subject

# The manifest's name inside the set's directory. Named, because "the JSON file
# in there" is not a declared form.
MANIFEST = "qualification.json"

# A manifest names cases; it never carries a document's bytes.
MAX_MANIFEST_BYTES = 1024 * 1024

# The keys each declared object carries, and nothing else. Closed both ways for
# the reason every wire model here is (`CLAUDE.md`, wire strictness): a key this
# loader ignores is a statement the author believed they had made.
_CASE_KEYS = frozenset(
    {
        "label",
        "profile_id",
        "selection_id",
        "documents",
        "expects",
    }
)
_OPTIONAL_CASE_KEYS = frozenset(
    {
        "forecast",
        "expected_refusal",
        "expects_ready",
        "expects_blocked",
        "expects_projection",
        "expects_register",
        "model_extension",
        "research_brief",
    }
)
_EXPECT_KEYS = frozenset({"module_id", "document_sha256", "matched_text"})
_FORECAST_KEYS = frozenset(
    {
        "scenario",
        "period_id",
        "values",
        "currency",
        "scale",
        "perimeter",
        "qa_status",
        "limitation_flags",
        "readiness",
    }
)
_FORECAST_VALUE_KEYS = frozenset({"name", "value"})
# Optional on a case, closed when present. Whether the values are a subject a
# pin accepts is `prepare`'s question, asked before it writes anything.
_SUBJECT_KEY = "subject"
_SUBJECT_KEYS = frozenset(
    {"issuer_id", "issuer_name", "reporting_period", "analysis_date"}
)

# The same bound `matrix.py` puts on a label when it digests one. Stated here
# too because this is where an authored label first arrives.
_LABEL_LIMIT = 128
# A manifest names cases; it never carries a document's bytes.
MAX_MANIFEST_BYTES = 1024 * 1024
_PROJECTION_KEYS = frozenset({"module_id", "field", "value"})
_REGISTER_KEYS = frozenset(
    {"module_id", "register_id", "row_key", "column", "expected"}
)


def load_qualification_set(root: Path) -> QualificationSet:
    """Read the set at `root`, or refuse it.

    Returns the same `QualificationSet` a caller would have built in Python, so
    everything downstream -- the digest, `assert_measurable`, the harness --
    cannot tell the two apart, which is the whole point.
    """
    cases = _declared(_manifest(root), "cases")
    return QualificationSet(
        cases=tuple(_case(root, entry) for entry in cases),
    )


def _bounded_bytes(path: Path, limit: int) -> bytes:
    """A regular file's bytes, refused before reading if it is too large.

    `read_bytes` on a path nobody bounded is the whole defect: a declared
    document of several gigabytes is read into memory before `admit_pack`'s own
    ceilings ever see it, and a FIFO at the declared path blocks the loader for
    as long as nothing writes to it. `is_file()` answers the second -- it is
    false for a FIFO, a socket and a directory -- and `st_size` answers the
    first without reading anything.

    The document limit is `admit_pack`'s own, so a set that would be refused at
    admission is refused at load instead of being read first.
    """
    status = path.stat()  # OSError here is the caller's refusal
    if not path.is_file() or status.st_size > limit:
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
    return path.read_bytes()


def _manifest(root: Path) -> Mapping[str, Any]:
    """The manifest, parsed. Absent or unparseable says nothing about a set."""
    try:
        parsed = json.loads(_bounded_bytes(root / MANIFEST, MAX_MANIFEST_BYTES))
    except (OSError, ValueError):
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID) from None
    if not isinstance(parsed, dict):
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
    if set(parsed) - {"cases"}:
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
    return parsed


def _case(root: Path, entry: object) -> QualificationCase:
    """One declared case, with its documents read from beside the manifest."""
    declared = isinstance(entry, dict) and _SUBJECT_KEY in entry
    keys = _CASE_KEYS | {
        key for key in _OPTIONAL_CASE_KEYS if isinstance(entry, dict) and key in entry
    }
    if declared:
        keys |= {_SUBJECT_KEY}
    fields = _closed(entry, keys)
    documents = _declared(fields, "documents")
    expects = _declared(fields, "expects")
    ready = _ready(fields.get("expects_ready"))
    blocked = _ready(fields.get("expects_blocked"))
    if set(ready) & set(blocked):
        # One module cleared and refused at once: no run can meet the case.
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
    return QualificationCase(
        label=_text(fields, "label"),
        documents=tuple(_document(root, path) for path in documents),
        profile_id=_text(fields, "profile_id"),
        selection_id=_text(fields, "selection_id"),
        expects=tuple(_expect(item) for item in expects),
        subject=_subject(fields[_SUBJECT_KEY]) if declared else None,
        forecast=_forecast(fields.get("forecast")),
        expected_refusal=_refusal(fields.get("expected_refusal")),
        expects_ready=ready,
        expects_blocked=blocked,
        expects_projection=_projections(fields.get("expects_projection")),
        expects_register=_registers(fields.get("expects_register")),
        model_extension=_extension(fields.get("model_extension")),
        research_brief=_brief(fields.get("research_brief")),
    )


def _subject(item: object) -> RunSubject:
    """The run subject a case declares: exactly its four strings."""
    fields = _closed(item, _SUBJECT_KEYS)
    declared = RunSubject(
        issuer_id=_text(fields, "issuer_id"),
        issuer_name=_text(fields, "issuer_name"),
        reporting_period=_text(fields, "reporting_period"),
        analysis_date=_text(fields, "analysis_date"),
    )
    # The pin's own rule: a manifest cannot digest a subject no pin accepts.
    if not valid_subject(declared):
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
    return declared


def _document(root: Path, declared: object) -> Document:
    """One document, read from a path that cannot leave the set.

    Resolved and compared against the resolved root rather than inspected for
    `..`: a string check answers the spellings someone thought of, and
    `Path.resolve` answers the question actually being asked -- where does this
    end up. An absolute path is the same escape by a shorter route, and
    `joinpath` would quietly discard the root it was given.
    """
    if not isinstance(declared, str) or not declared.strip():
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)

    base = root.resolve()
    target = (base / declared).resolve()
    if target == base or base not in target.parents:
        raise Refusal(RefusalCode.QUALIFICATION_SET_PATH_ESCAPES)

    try:
        data = _bounded_bytes(target, DEFAULT_LIMITS.max_document_bytes)
    except OSError:
        # Named and not there. A set is its bytes; one document short is not a
        # smaller set, it is a set nobody can measure the same way twice.
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID) from None

    return Document(filename=_boundary(target.name), data=data)


def _expect(item: object) -> ExpectedCitation:
    """One expected citation from the answer key."""
    fields = _closed(item, _EXPECT_KEYS)
    return ExpectedCitation(
        module_id=_text(fields, "module_id"),
        document_sha256=_text(fields, "document_sha256"),
        matched_text=_text(fields, "matched_text"),
    )


def _forecast(item: object) -> ExpectedForecast | None:
    if item is None:
        return None
    fields = _closed(item, _FORECAST_KEYS)
    values = _declared(fields, "values")
    readiness = _declared(fields, "readiness")
    return ExpectedForecast(
        scenario=_text(fields, "scenario"),
        period_id=_text(fields, "period_id"),
        values=tuple(
            ForecastValue(**_closed(value, _FORECAST_VALUE_KEYS)) for value in values
        ),
        currency=_text(fields, "currency"),
        scale=_text(fields, "scale"),
        perimeter=_text(fields, "perimeter"),
        qa_status=_text(fields, "qa_status"),
        limitation_flags=_strings(fields, "limitation_flags"),
        readiness=tuple(_pair(value) for value in readiness),
    )


def _projections(item: object) -> tuple[ExpectedProjection, ...]:
    """The host-projected conclusions the case expects, or a refusal.

    The field name is checked here rather than at comparison time: a key naming
    a field the host does not project would otherwise read as the module having
    concluded the wrong thing, which is the one failure a key must never have.
    """
    if item is None:
        return ()
    if not isinstance(item, list) or not item:
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
    expects = []
    for value in item:
        if not isinstance(value, dict) or set(value) != _PROJECTION_KEYS:
            raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
        field = value["field"]
        if not isinstance(field, str) or field not in PROJECTION_FIELDS:
            raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
        expects.append(
            ExpectedProjection(
                module_id=_bounded(value["module_id"]),
                field=field,
                value=_bounded(value["value"]),
            )
        )
    if len({(e.module_id, e.field, e.value) for e in expects}) != len(expects):
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
    return tuple(expects)


def _registers(item: object) -> tuple[ExpectedRegister, ...]:
    """The register cells the case expects, or a refusal.

    Each row is `{module_id, register_id, row_key, column, expected}`, with
    `row_key` an object of column to value -- the cells that name the one row,
    which the digest then covers as a set. Every string is bounded here, because
    this is where an authored key crosses into pinned state.

    An empty `row_key` is refused with its own code: the file is well formed and
    the key is not answerable, since "any row of the register" is not one row,
    and a remedy that says "fix the manifest" would send the author looking at
    the wrong thing.
    """
    if item is None:
        return ()
    if not isinstance(item, list) or not item:
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
    expects = []
    for value in item:
        if not isinstance(value, dict) or set(value) != _REGISTER_KEYS:
            raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
        row_key = value["row_key"]
        if not isinstance(row_key, dict):
            raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
        if not row_key:
            raise Refusal(RefusalCode.QUALIFICATION_KEY_AMBIGUOUS)
        # Sorted on the bounded name, not the authored one, so two manifests
        # naming the same cells carry the same key whatever the padding.
        named = tuple(
            sorted(
                (_bounded(column), _bounded(cell)) for column, cell in row_key.items()
            )
        )
        if len({column for column, _cell in named}) != len(named):
            # Two spellings of one column name, bounded to the same string: the
            # key names a row twice and may name it differently each time.
            raise Refusal(RefusalCode.QUALIFICATION_KEY_AMBIGUOUS)
        expects.append(
            ExpectedRegister(
                module_id=_bounded(value["module_id"]),
                register_id=_bounded(value["register_id"]),
                row_key=named,
                column=_bounded(value["column"]),
                expected=_bounded(value["expected"]),
            )
        )
    if len(set(expects)) != len(expects):
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
    return tuple(expects)


def _bounded(value: object) -> str:
    """One string from a declared key, bounded as pinned state must be."""
    if not isinstance(value, str) or not value.strip():
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
    return BoundaryText.of(value.strip(), limit=_LABEL_LIMIT).value


def _ready(item: object) -> tuple[str, ...]:
    """The module ids CP-0 must find ready -- or, for `expects_blocked`, must
    refuse -- or a refusal.

    Declared as a list of module ids; absent means the case asks nothing of
    readiness. Bounded and de-duplicated here, because this crosses into the
    set's digest and a key that differs only by repetition would digest twice.
    """
    if item is None:
        return ()
    if not isinstance(item, list) or not item:
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
    modules = []
    for value in item:
        if not isinstance(value, str) or not value.strip():
            raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
        modules.append(BoundaryText.of(value.strip(), limit=_LABEL_LIMIT).value)
    if len(set(modules)) != len(modules):
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
    return tuple(modules)


def _refusal(item: object) -> RefusalCode | None:
    if item is None:
        return None
    if not isinstance(item, str):
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
    try:
        return RefusalCode(item)
    except ValueError:
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID) from None


def _extension(item: object) -> bool:
    if item is None:
        return False
    if type(item) is not bool:
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
    return item


def _brief(item: object) -> str | None:
    """A case's research brief, as the canonical text a pin stores. Its shape
    is the storage bound `research_text` states; whether the vendor accepts it
    is the pin's question, asked by `prepare` before anything is spent."""
    if item is None:
        return None
    if not isinstance(item, dict):
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
    try:
        return research_text(item)
    except Refusal:
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID) from None


def _closed(entry: object, keys: frozenset[str]) -> Mapping[str, Any]:
    """A declared object: a mapping carrying exactly `keys`."""
    if not isinstance(entry, dict) or set(entry) != keys:
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
    return entry


def _declared(fields: Mapping[str, Any], key: str) -> Sequence[Any]:
    """A declared list. Empty is left to `assert_measurable`, which owns that
    rule; what is refused here is a list that is not one."""
    value = fields.get(key)
    if not isinstance(value, list):
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
    return value


def _text(fields: Mapping[str, Any], key: str) -> str:
    """One declared string, present and not blank."""
    value = fields.get(key)
    if not isinstance(value, str) or not value.strip():
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
    return value


def _strings(fields: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = _declared(fields, key)
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
    return tuple(value)


def _pair(item: object) -> tuple[str, str]:
    if (
        not isinstance(item, list)
        or len(item) != 2
        or any(not isinstance(value, str) or not value.strip() for value in item)
    ):
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID)
    return item[0], item[1]


def _boundary(name: str) -> BoundaryText:
    """A filename crossing into a set that will be digested and admitted.

    `BoundaryText` refuses what it always refuses; the refusal is retyped so a
    malformed manifest reads as a malformed manifest rather than as a boundary
    failure a caller of this function cannot place.
    """
    try:
        return BoundaryText.of(name, limit=_LABEL_LIMIT)
    except Refusal:
        raise Refusal(RefusalCode.QUALIFICATION_SET_FILE_INVALID) from None
