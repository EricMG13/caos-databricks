"""Complete historical input pins. Storage alone grants no execution authority."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import psycopg

from caos import methodology
from caos.boundary_text import BoundaryText
from caos.digest import canonical_digest, canonical_json
from caos.graph.route import ResolvedRoute
from caos.methodology.bundle import Bundle
from caos.methodology.handoff import ADAPTER_ROUTES, RESEARCH_MODULE
from caos.methodology.vendor import (
    VendorContract,
    authority_bundle_sha256,
    cached_contract,
    catalog,
)
from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection, committed_unit
from caos.store.events import RunEvent, append, lock_run
from caos.store.routes import route_pin
from caos.store.source_sets import SourceSet, load_source_set

# The vendor's `validate_handoff.SUBJECT_KEY_RE`, and 0011's CHECK.
SUBJECT_KEY = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$")
COS_RUN_ID = re.compile(r"^COS-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}$")
_SUBJECT_TEXT_BYTES = 1024


@dataclass(frozen=True, slots=True)
class RunSubject:
    """Who and when a run is about. Pinned before approval; never the model's."""

    issuer_id: str
    issuer_name: str
    reporting_period: str
    analysis_date: str


@dataclass(frozen=True, slots=True)
class RunInput:
    run_id: UUID
    case_id: UUID
    source_version: int
    source_fingerprint: str
    route_digest: str
    build_id: str
    manifest_sha256: str
    adapter_version: str
    research_json: str | None
    input_fingerprint: str
    # Format version 2 only: both present, or both absent for version 1.
    subject: RunSubject | None = None
    cos_run_id: str | None = None

    @property
    def format_version(self) -> int:
        return 1 if self.subject is None else 2


def input_fields(pin: RunInput) -> dict[str, object]:
    """The pin as plain data; a version-1 pin keeps its version-1 keys exactly."""
    fields = asdict(pin)
    if pin.format_version == 1:
        del fields["subject"], fields["cos_run_id"]
    return fields


def cos_run_id(run_id: UUID, created_at: datetime) -> str:
    """The vendor run id, from the run's own creation instant converted to UTC."""
    return f"COS-{created_at.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}-{run_id.hex}"


def _subject_text(value: object) -> bool:
    try:
        return (
            type(value) is str
            and value == value.strip()
            and bool(value)
            and "\t" not in value
            and len(value.splitlines()) == 1
            and len(value.encode("utf-8")) <= _SUBJECT_TEXT_BYTES
            and BoundaryText.of(value, limit=_SUBJECT_TEXT_BYTES).value == value
        )
    except Refusal:
        return False


def _subject_valid(subject: RunSubject) -> bool:
    try:
        parsed = date.fromisoformat(subject.analysis_date)
    except (TypeError, ValueError):
        return False
    return (
        type(subject.issuer_id) is str
        and SUBJECT_KEY.fullmatch(subject.issuer_id) is not None
        and len(subject.issuer_id) <= 128
        and _subject_text(subject.issuer_name)
        and _subject_text(subject.reporting_period)
        and parsed.isoformat() == subject.analysis_date
    )


def valid_subject(subject: object) -> bool:
    """Whether `subject` is a `RunSubject` a pin would accept, checked before any
    write so a caller preparing many runs can refuse the whole batch up front."""
    return type(subject) is RunSubject and _subject_valid(subject)


_V1_COLUMNS = (
    "run_id",
    "case_id",
    "source_version",
    "source_fingerprint",
    "route_digest",
    "build_id",
    "manifest_sha256",
    "adapter_version",
    "research_json",
    "input_fingerprint",
)


def _research_value(item: object) -> bool:
    if type(item) is dict:
        return len(item) <= 4096 and all(type(k) is str for k in item)
    if type(item) is list:
        return len(item) <= 4096
    if type(item) is str:
        try:
            return len(item) <= 4096 and BoundaryText.of(item).value == item
        except Refusal:
            return False
    return (
        item is None
        or type(item) is bool
        or (type(item) is int and -(2**63) <= item < 2**63)
        or (type(item) is float and math.isfinite(item))
    )


def _research(value: object) -> str | None:
    """Exact NFC JSON object or absence; bounds are storage policy, not CP_DR schema."""
    if value is None:
        return None
    if type(value) is not dict:
        raise Refusal(RefusalCode.RUN_INPUT_INVALID)
    pending: list[tuple[object, int]] = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > 16 or count > 4096 or not _research_value(item):
            raise Refusal(RefusalCode.RUN_INPUT_INVALID)
        if type(item) is dict:
            pending.extend((v, depth + 1) for pair in item.items() for v in pair)
        elif type(item) is list:
            pending.extend((v, depth + 1) for v in item)
    try:
        raw = canonical_json(value)
    except (TypeError, ValueError, RecursionError):
        raise Refusal(RefusalCode.RUN_INPUT_INVALID) from None
    if len(raw.encode("utf-8")) > 65536:
        raise Refusal(RefusalCode.RUN_INPUT_INVALID)
    return raw


def research_text(value: object) -> str | None:
    """The canonical text a research brief is pinned as: `_research`, public."""
    return _research(value)


# The three bindings only the host may write into a research brief (§96): the
# vendor run id, the accepted CP-0's Markdown digest and the bundle's authority
# digest. A caller's brief carrying any of them is refused at the pin -- the
# host owns identity (invariant 3).
HOST_BOUND_BRIEF_KEYS = frozenset({"run_id", "cp0_sha256", "authority_sha256"})
# The one `source_mode` this host can honour: web discovery is structurally
# absent (invariant 1), so a brief asking for `web_only` or `hybrid` asks for
# a capability nothing here has, and is refused rather than run `Blocked`.
SUPPLIED_ONLY = "supplied_only"
# The CP-0 digest a brief is bound to before the gate has run: the pin's
# stand-in, replaced by the accepted record's digest when CP-DR is invoked.
UNANCHORED_CP0 = "0" * 64
# The brief's declared fields (`CP_DR_RESEARCH_BRIEF_V1.md`, "Run-linked
# brief"): the vendor's `validate_brief` checks each one and ignores any other,
# so the host refuses an undeclared field at its own boundary (wire
# strictness) rather than carry caller text no rule reads into CP-DR's prompt.
BRIEF_KEYS = frozenset(
    {
        "schema",
        "mode",
        "run_id",
        "cp0_sha256",
        "authority_sha256",
        "scope_type",
        "scope_key",
        "subject_name",
        "decision_context",
        "as_of_date",
        "time_horizon",
        "source_mode",
        "budget",
        "authorization_basis",
        "exclusions",
        "questions",
    }
)


def _bound_brief(
    brief: Mapping[str, Any], *, run_id: str, cp0_sha256: str, authority_sha256: str
) -> dict[str, Any]:
    """The caller's brief with the three host bindings written in."""
    return {
        **brief,
        "run_id": run_id,
        "cp0_sha256": cp0_sha256,
        "authority_sha256": authority_sha256,
    }


def _cp0_anchor(
    subject: RunSubject, *, run_id: str, cp0_sha256: str, authority_sha256: str
) -> SimpleNamespace:
    """The CP-0 identity the vendor's `validate_brief` anchors a linked brief
    to, built from what the host pinned rather than read from any handoff."""
    return SimpleNamespace(
        fields={
            "credit_os_run_id": run_id,
            "credit_os_authority_bundle_sha256": authority_sha256,
            "issuer_id": subject.issuer_id,
            "issuer_name": subject.issuer_name,
        },
        sha256=cp0_sha256,
    )


def bound_research_brief(  # noqa: PLR0913 -- one brief, every binding keyword-only
    contract: VendorContract,
    vendor_catalog: Mapping[str, Any],
    *,
    brief: object,
    route: ResolvedRoute,
    subject: RunSubject,
    run_id: str,
    cp0_sha256: str,
    authority_sha256: str,
) -> dict[str, Any]:
    """The caller's brief, host-bound and judged by the vendor's own rules.

    Refuses `RUN_INPUT_INVALID` for: a brief that is not an object, that
    carries a host binding or a field the brief schema does not declare; a
    pinned route no CP-DR node is on (a brief no node reads is a statement
    nobody heard); anything the vendor's `validate_brief`
    refuses against the CP-0 anchor built from the pin -- schema, `mode:
    linked`, `scope_key` and `subject_name` against the subject, the question
    shape; a `source_mode` other than supplied-only (invariant 1); and a
    placement the vendor's own `Route` refuses -- a consumer or predecessor the
    pinned pathway does not select, or one that would cycle. Every vendor
    exception is caught inside its own handler, so no vendor text reaches the
    refusal (invariant 2).
    """
    if (
        type(brief) is not dict
        or HOST_BOUND_BRIEF_KEYS.intersection(brief)
        or not BRIEF_KEYS.issuperset(brief)
        or all(node.module_id != RESEARCH_MODULE for node in route.nodes)
    ):
        raise Refusal(RefusalCode.RUN_INPUT_INVALID)
    bound = _bound_brief(
        brief, run_id=run_id, cp0_sha256=cp0_sha256, authority_sha256=authority_sha256
    )
    anchor = _cp0_anchor(
        subject, run_id=run_id, cp0_sha256=cp0_sha256, authority_sha256=authority_sha256
    )
    valid = False
    try:
        contract.research.validate_brief(bound, cp0=anchor)
        contract.routing.Route(
            vendor_catalog, route.profile_id, route.selection_id, research_brief=bound
        )
        valid = bound["source_mode"] == SUPPLIED_ONLY
    except Exception:  # noqa: BLE001 -- any vendor refusal is this refusal
        valid = False
    if not valid:
        raise Refusal(RefusalCode.RUN_INPUT_INVALID)
    return bound


def _fingerprint(pin: RunInput) -> str:
    fields = input_fields(pin)
    del fields["run_id"], fields["input_fingerprint"]
    fields.update(format_version=pin.format_version, case_id=str(pin.case_id))
    return canonical_digest(fields)


def _validate(pin: RunInput) -> None:
    try:
        if type(pin.source_version) is not int or not 0 < pin.source_version < 2**63:
            raise Refusal(RefusalCode.RUN_INPUT_INVALID)
        if not all(
            re.fullmatch(r"[0-9a-f]{64}", value)
            for value in (
                pin.source_fingerprint,
                pin.route_digest,
                pin.build_id,
                pin.manifest_sha256,
                pin.input_fingerprint,
            )
        ) or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,63}", pin.adapter_version):
            raise Refusal(RefusalCode.RUN_INPUT_INVALID)
        if pin.research_json is not None:
            if len(pin.research_json.encode("utf-8")) > 65536:
                raise Refusal(RefusalCode.RUN_INPUT_INVALID)
            if _research(json.loads(pin.research_json)) != pin.research_json:
                raise Refusal(RefusalCode.RUN_INPUT_INVALID)
        if (pin.subject is None) != (pin.cos_run_id is None) or (
            pin.subject is not None
            and (
                not _subject_valid(pin.subject)
                or COS_RUN_ID.fullmatch(str(pin.cos_run_id)) is None
            )
        ):
            raise Refusal(RefusalCode.RUN_INPUT_INVALID)
        if _fingerprint(pin) != pin.input_fingerprint:
            raise Refusal(RefusalCode.RUN_INPUT_INVALID)
    except (TypeError, ValueError, AttributeError, RecursionError):
        raise Refusal(RefusalCode.RUN_INPUT_INVALID) from None


def load_run_input(conn: StoreConnection, run_id: UUID) -> RunInput | None:
    """Verify historical shape/content; never adopt today's bundle or adapter.

    This read retains the caller's transaction, including on database failure.
    """
    loaded = _load_run_input(conn, run_id)
    return None if loaded is None else loaded[0]


def _load_run_input(
    conn: StoreConnection, run_id: UUID
) -> tuple[RunInput, ResolvedRoute, SourceSet] | None:
    """One verified component load for historical and execution-authority reads."""
    try:
        row = conn.execute(
            "SELECT run_id, case_id, source_version, source_fingerprint, route_digest,"
            " build_id, manifest_sha256, adapter_version, research_json,"
            " input_fingerprint, issuer_id, issuer_name, reporting_period,"
            " analysis_date, cos_run_id, format_version"
            " FROM run_inputs WHERE run_id = %s",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        subject = None if row[10] is None else RunSubject(*row[10:14])
        pin = RunInput(**dict(zip(_V1_COLUMNS, row[:10], strict=True)))
        pin = replace(pin, subject=subject, cos_run_id=row[14])
        _validate(pin)
        run = conn.execute(
            "SELECT case_id, created_at FROM runs WHERE run_id = %s", (run_id,)
        ).fetchone()
        owner = None if run is None else (run[0],)
        created = None if run is None else run[1]
        source = load_source_set(conn, pin.case_id, pin.source_version)
        pinned = route_pin(conn, run_id)
        if (
            row[-1] != pin.format_version
            or owner != (pin.case_id,)
            or (
                pin.cos_run_id is not None
                and (created is None or pin.cos_run_id != cos_run_id(run_id, created))
            )
            or source is None
            or source.fingerprint != pin.source_fingerprint
            or pinned is None
            or pinned[1] != pin.route_digest
        ):
            raise Refusal(RefusalCode.RUN_INPUT_INVALID)
    except psycopg.Error:
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None
    return pin, pinned[0], source


def pin_run_input(  # noqa: PLR0913 -- subject is keyword-only
    conn: StoreConnection,
    run_id: UUID,
    source_version: int,
    bundle: Bundle,
    research: object = None,
    *,
    subject: RunSubject | None = None,
) -> RunInput:
    """Own one case-first/run-locked row/event transaction; setup commits separately.

    Every new pin is format version 2 under the one canonical adapter (§42.1):
    its fingerprint and gate preview bind the `subject` and the UTC vendor run
    id, and a pin without a subject refuses `RUN_INPUT_INVALID`. Stored version
    1 pins stay readable and byte-identical; execution refuses them.
    """
    if conn.autocommit:
        raise Refusal(RefusalCode.STORE_NOT_TRANSACTIONAL)
    with committed_unit(conn):
        candidate = pin_run_input_in(
            conn, run_id, source_version, bundle, research, subject=subject
        )
    return candidate


def _judge_research(
    bundle: Bundle,
    route: ResolvedRoute,
    research: object,
    *,
    subject: RunSubject,
    run_id: str,
) -> None:
    """A new pin's brief, judged as CP-DR will receive it (§96).

    On an enabled pathway carrying CP-DR a brief is required: the vendor's own
    rule -- CP-DR requires a run-scoped brief naming its questions
    (`navigation.plan_from_cp0`) -- asked before anything is spent, since a
    brief-less input would pay for CP-0 and then refuse at CP-DR. A brief that
    is given is host-bound to this run, this bundle and, for now, the
    unanchored gate -- the accepted CP-0's digest replaces the stand-in when
    the node is invoked -- and judged by `bound_research_brief`. Read only when
    a brief is given, so every other pin costs no vendor load.
    """
    if research is None:
        if (route.profile_id, route.selection_id) in ADAPTER_ROUTES and any(
            node.module_id == RESEARCH_MODULE for node in route.nodes
        ):
            raise Refusal(RefusalCode.RUN_INPUT_INVALID)
        return
    bound_research_brief(
        cached_contract(bundle),
        catalog(bundle),
        brief=research,
        route=route,
        subject=subject,
        run_id=run_id,
        cp0_sha256=UNANCHORED_CP0,
        authority_sha256=authority_bundle_sha256(bundle),
    )


def pin_run_input_in(  # noqa: PLR0913 -- pin_run_input's arguments
    conn: StoreConnection,
    run_id: UUID,
    source_version: int,
    bundle: Bundle,
    research: object = None,
    *,
    subject: RunSubject | None = None,
) -> RunInput:
    """`pin_run_input`'s row and event in the caller's transaction; never commits."""
    if type(source_version) is not int or not 0 < source_version < 2**63:
        raise Refusal(RefusalCode.RUN_INPUT_INVALID)
    # Every run pins the canonical adapter, whose handoffs name a subject.
    if subject is None or not _subject_valid(subject):
        raise Refusal(RefusalCode.RUN_INPUT_INVALID)
    raw = _research(research)
    status = lock_run(conn, run_id)
    owner = conn.execute(
        "SELECT case_id, created_at FROM runs WHERE run_id = %s", (run_id,)
    ).fetchone()
    if owner is None:
        raise Refusal(RefusalCode.RUN_NOT_FOUND)
    source = load_source_set(conn, owner[0], source_version)
    pinned = route_pin(conn, run_id)
    if source is None or pinned is None:
        raise Refusal(RefusalCode.RUN_INPUT_INVALID)
    candidate = RunInput(
        run_id,
        owner[0],
        source.version,
        source.fingerprint,
        pinned[1],
        bundle.build_id,
        bundle.manifest_sha256,
        methodology.CANONICAL_ADAPTER_VERSION,
        raw,
        "",
        subject,
        cos_run_id(run_id, owner[1]),
    )
    candidate = replace(candidate, input_fingerprint=_fingerprint(candidate))
    _validate(candidate)
    stored = load_run_input(conn, run_id)
    if stored is not None:
        if stored != candidate:
            raise Refusal(RefusalCode.RUN_INPUT_ALREADY_PINNED)
    else:
        if status is not RunStatus.RUNNING:
            raise Refusal(RefusalCode.RUN_NOT_RUNNING)
        if conn.execute(
            "SELECT 1 FROM run_attempts WHERE run_id = %s LIMIT 1", (run_id,)
        ).fetchone():
            raise Refusal(RefusalCode.RUN_INPUT_TOO_LATE)
        _judge_research(
            bundle,
            pinned[0],
            research,
            subject=subject,
            run_id=cos_run_id(run_id, owner[1]),
        )
        conn.execute(
            "INSERT INTO run_inputs (run_id, case_id, source_version,"
            " source_fingerprint, route_digest, build_id, manifest_sha256,"
            " adapter_version, research_json, input_fingerprint, issuer_id,"
            " issuer_name, reporting_period, analysis_date, cos_run_id,"
            " format_version) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                *(getattr(candidate, name) for name in _V1_COLUMNS),
                subject.issuer_id,
                subject.issuer_name,
                subject.reporting_period,
                subject.analysis_date,
                candidate.cos_run_id,
                candidate.format_version,
            ),
        )
        append(conn, run_id, RunEvent.INPUT_PINNED)
    return candidate
