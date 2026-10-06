"""A run's pinned command qualifiers: the vendor's run-local inputs above the
evidence (D109, N146).

The vendor resolves a module's run-local inputs from "current command
qualifier > current conversation value > validated matching upstream handoff >
approved live module reference > declared safe module default > MISSING"
(`CANON_SHARED.md`; CP-2G's `SKILL.md` entry protocol), and CP-0 assesses
readiness against "the user's stated objective" (its hard rule 6). This host
has no conversation, so the one channel is the command: a closed map of
module id to qualifier name to one line of text, pinned once in the run input
and fingerprinted with it (invariant 10), and delivered to the named node only
as a host-owned "current command" section.

Closed both ways. A module takes only the names `QUALIFIER_FIELDS` lists; for a
module whose `SKILL.md` declares its stage fields (`ux_stage_fields`), each
listed name must also be one of those, read from the verified bytes at the pin
(invariant 4). CP-0's `objective` is hard rule 6's stated objective.

The owner's rule (D109): when a route carries CP-2G and the pin states no
`forecast_horizon` or `base_period`, the host derives it from the pinned
reporting period (`derived_scope`), writes it into the pin marked `derived`,
and refuses a period the rule cannot read rather than guess. A stated value
always wins. `cases` is never derived.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from caos.boundary_text import BoundaryText, hides_text
from caos.digest import canonical_json
from caos.refusals import Refusal, RefusalCode

FORECAST_MODULE = "CP-2G"
OBJECTIVE_MODULE = "CP-0"
OBJECTIVE = "objective"
FORECAST_HORIZON = "forecast_horizon"
BASE_PERIOD = "base_period"
CASES = "cases"
# Every module this host takes a command for, and the names it takes. CP-2G's
# are its UX contract's stage fields (`SKILL.md`: "Stages: forecast_scope
# (forecast_horizon) -> base (base_period) -> cases (cases)").
QUALIFIER_FIELDS: Mapping[str, tuple[str, ...]] = {
    OBJECTIVE_MODULE: (OBJECTIVE,),
    FORECAST_MODULE: (FORECAST_HORIZON, BASE_PERIOD, CASES),
}
# The modules whose names must also be stage fields of their verified SKILL.md.
STAGE_FIELD_MODULES = frozenset({FORECAST_MODULE})
# Who stated a value: the run's caller (or its qualification case), or the host
# by the owner's rule.
PINNED = "pinned"
DERIVED = "derived"
_BASES = frozenset({PINNED, DERIVED})
_TEXT_BYTES = 1024
# F524: each CP-2G value's own grammar. The scope takes the forms the owner's
# rule writes and an explicit FY range (the card's `FY26-FY28`); `cases` is a
# short list of words. Nothing else is a value the card can carry unaltered.
_FY_RANGE = re.compile(r"^FY(?P<start>[0-9]{4})-FY(?P<end>[0-9]{4})$")
_FY_SHORT_RANGE = re.compile(r"^FY(?P<start>[0-9]{2})-FY(?P<end>[0-9]{2})$")
_BASE = re.compile(r"^(?:Q[1-4] [0-9]{4} LTM|FY[0-9]{4})$")
_CASES = re.compile(r"^[A-Za-z/ -]{1,64}$")
# Open and close punctuation the card could read as its own `[` or `]`:
# every one but the parentheses an objective may carry.
_KEPT_PUNCTUATION = frozenset("()")
_UX_BLOCK = re.compile(
    r"<!-- UX_CONTRACT:BEGIN -->(.*?)<!-- UX_CONTRACT:END -->", re.DOTALL
)
_STAGES = re.compile(r"^Stages: (.+)$", re.MULTILINE)
_STAGE_FIELDS = re.compile(r"\(([^()]*)\)")
_FIELD = re.compile(r"^[a-z][a-z_]*$")
# A latest reporting period the rule reads: `FY2025`, `FY 2025`, `FY25`,
# `Q2 2026`, `Q2-26`. Anything else is refused, never guessed.
_PERIOD = re.compile(r"^(?:FY ?|Q(?P<quarter>[1-4])[ -])(?P<year>[0-9]{4}|[0-9]{2})$")


def ux_stage_fields(skill: bytes) -> frozenset[str]:
    """The field names a `SKILL.md`'s UX contract lists on its one `Stages:`
    line, each stage's parenthesised fields; empty when it lists none.
    `AUTHORITY_BYTES_MISMATCH` for bytes that are not UTF-8, more than one UX
    block or `Stages:` line, or a field that is not a lower-case name."""
    try:
        text = skill.decode("utf-8")
    except UnicodeDecodeError:
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH) from None
    blocks = _UX_BLOCK.findall(text)
    if len(blocks) > 1:
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    lines = _STAGES.findall(blocks[0]) if blocks else []
    if len(lines) > 1:
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    names = [
        name.strip()
        for group in (_STAGE_FIELDS.findall(lines[0]) if lines else [])
        for name in group.split(",")
    ]
    if not all(_FIELD.fullmatch(name) for name in names):
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    return frozenset(names)


def derived_scope(reporting_period: str) -> dict[str, str]:
    """CP-2G's forecast scope by the owner's rule (D109), from the run's latest
    reporting period: after Q1, Q2 or Q3 of year Y the horizon is FY(Y) to
    FY(Y+2) and the base the LTM to that quarter; after Q4 or FY of year Y the
    horizon is FY(Y+1) to FY(Y+3) and the base that fiscal year. A two-digit
    year is 20YY. `REPORTING_PERIOD_UNREADABLE` for any other spelling, or a
    year outside 1900 to 2999."""
    matched = _PERIOD.fullmatch(reporting_period)
    if matched is None:
        raise Refusal(RefusalCode.REPORTING_PERIOD_UNREADABLE)
    digits = matched["year"]
    year = 2000 + int(digits) if len(digits) == 2 else int(digits)
    if not 1900 <= year <= 2999:
        raise Refusal(RefusalCode.REPORTING_PERIOD_UNREADABLE)
    quarter = matched["quarter"]
    if quarter is not None and quarter != "4":
        return {
            FORECAST_HORIZON: f"FY{year}-FY{year + 2}",
            BASE_PERIOD: f"Q{quarter} {year} LTM",
        }
    return {FORECAST_HORIZON: f"FY{year + 1}-FY{year + 3}", BASE_PERIOD: f"FY{year}"}


def _text(value: object) -> bool:
    """One line of caller text the card can carry: NFC, nothing a reader
    cannot see (`hides_text`, the rule evidence, handoffs and filenames are
    held to, AI-2; the one-line rule already refuses U+2028 and U+2029, so
    with it this is `handoff.INVISIBLE` too), and no bracket or bracket
    lookalike, which would end or fake a `[name: value]` (F524)."""
    try:
        return (
            type(value) is str
            and bool(value)
            and value == value.strip()
            and "\t" not in value
            and len(value.splitlines()) == 1
            and len(value.encode("utf-8")) <= _TEXT_BYTES
            and BoundaryText.of(value, limit=_TEXT_BYTES).value == value
            and not hides_text(value)
            and not any(
                unicodedata.category(character) in {"Ps", "Pe"}
                and character not in _KEPT_PUNCTUATION
                for character in value
            )
        )
    except Refusal:
        return False


def _horizon(value: str) -> bool:
    """An FY range in one width whose end is not before its start."""
    matched = _FY_RANGE.fullmatch(value) or _FY_SHORT_RANGE.fullmatch(value)
    return matched is not None and matched["start"] <= matched["end"]


def _value(name: str, value: object) -> bool:
    """`value` as `name` takes it: one line of `_text`, and for CP-2G's
    three names their own grammar (F524)."""
    if not _text(value):
        return False
    text = str(value)
    if name == FORECAST_HORIZON:
        return _horizon(text)
    if name == BASE_PERIOD:
        return _BASE.fullmatch(text) is not None
    if name == CASES:
        return _CASES.fullmatch(text) is not None
    return True


def stated_command(
    qualifiers: Mapping[str, Mapping[str, str]] | None, objective: str | None
) -> dict[str, dict[str, str]]:
    """A caller's qualifiers and objective as one closed map, or
    `RUN_QUALIFIER_INVALID`: a module or name `QUALIFIER_FIELDS` does not list,
    `objective` given both ways, a value that is not one line of text."""
    stated: dict[str, dict[str, str]] = {}
    for module_id, names in (qualifiers or {}).items():
        if type(module_id) is not str or not isinstance(names, Mapping) or not names:
            raise Refusal(RefusalCode.RUN_QUALIFIER_INVALID)
        stated[module_id] = dict(names)
    if objective is not None:
        if OBJECTIVE in stated.get(OBJECTIVE_MODULE, {}):
            raise Refusal(RefusalCode.RUN_QUALIFIER_INVALID)
        stated.setdefault(OBJECTIVE_MODULE, {})[OBJECTIVE] = objective
    for module_id, names in stated.items():
        allowed = QUALIFIER_FIELDS.get(module_id, ())
        if not all(
            type(name) is str and name in allowed and _value(name, value)
            for name, value in names.items()
        ):
            raise Refusal(RefusalCode.RUN_QUALIFIER_INVALID)
    return stated


def pinned_command(
    stated: Mapping[str, Mapping[str, str]],
    *,
    route_modules: frozenset[str],
    stage_fields: Mapping[str, frozenset[str]],
    reporting_period: str,
) -> str | None:
    """The command a pin stores: `stated` (from `stated_command`), each value
    marked `pinned`, and CP-2G's unstated scope `derived` by the owner's rule
    when the route carries CP-2G; canonical JSON, or None when empty.

    `RUN_QUALIFIER_INVALID` for a module the route does not carry (a command
    no node reads is a statement nobody heard); `AUTHORITY_BYTES_MISMATCH` when
    a name this host lists is not a stage field of the module's verified
    `SKILL.md` (`stage_fields`, read by the caller for `STAGE_FIELD_MODULES`
    on the route); `REPORTING_PERIOD_UNREADABLE` when a value must be derived
    from a period the rule cannot read.
    """
    if not route_modules.issuperset(stated):
        raise Refusal(RefusalCode.RUN_QUALIFIER_INVALID)
    for module_id in STAGE_FIELD_MODULES & route_modules:
        if not stage_fields.get(module_id, frozenset()).issuperset(
            QUALIFIER_FIELDS[module_id]
        ):
            raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    command = {
        module_id: {
            name: {"basis": PINNED, "value": value} for name, value in names.items()
        }
        for module_id, names in stated.items()
    }
    if FORECAST_MODULE in route_modules:
        scope = command.setdefault(FORECAST_MODULE, {})
        missing = {FORECAST_HORIZON, BASE_PERIOD} - set(scope)
        if missing:
            derived = derived_scope(reporting_period)
            scope.update(
                (name, {"basis": DERIVED, "value": derived[name]}) for name in missing
            )
    return canonical_json(command) if command else None


def read_command(text: str, *, reporting_period: str) -> dict[str, Any]:
    """A stored command, checked as the pin wrote it: canonical JSON, closed
    names, every value one line of text, and every `derived` value exactly the
    owner's rule over the pinned `reporting_period`. `ValueError` otherwise,
    which the run-input reader answers `RUN_INPUT_INVALID`."""
    command = json.loads(text)
    if type(command) is not dict or not command or canonical_json(command) != text:
        raise ValueError
    derived = _derived(reporting_period)
    for module_id, names in command.items():
        if (
            type(names) is not dict
            or not names
            or not all(
                _stored_entry(module_id, name, entry, derived)
                for name, entry in names.items()
            )
        ):
            raise ValueError
    return command


def _stored_entry(
    module_id: str, name: str, entry: object, derived: Mapping[str, str]
) -> bool:
    """One stored qualifier as the pin writes it: a name the module takes, one
    `basis` and one line of `value`; a `derived` one only for CP-2G's scope,
    and exactly the rule's value (`derived`, empty for an unreadable period)."""
    if (
        name not in QUALIFIER_FIELDS.get(module_id, ())
        or type(entry) is not dict
        or set(entry) != {"basis", "value"}
        or entry["basis"] not in _BASES
        or not _value(name, entry["value"])
    ):
        return False
    return entry["basis"] != DERIVED or (
        module_id == FORECAST_MODULE and derived.get(name) == entry["value"]
    )


def _derived(reporting_period: str) -> dict[str, str]:
    """`derived_scope`, or nothing for a period it refuses: a stored value
    the rule cannot reproduce is a stored input that does not verify."""
    try:
        return derived_scope(reporting_period)
    except Refusal:
        return {}


def module_command(command: str | None, module_id: str) -> str | None:
    """One module's part of a stored command as canonical JSON, or None when
    the command names it not. The stored text was read by `read_command`."""
    if command is None:
        return None
    names = json.loads(command).get(module_id)
    return None if names is None else canonical_json(names)


def command_card(module_id: str, names: Mapping[str, Mapping[str, str]]) -> str:
    """The vendor's command card for `module_id` (CP-2G's `SKILL.md`: `Run
    CP-2G [forecast horizon: FY26-FY28] [base period: Q1 2026 LTM] ...`), each
    name as the card spells it and in `QUALIFIER_FIELDS` order, then one line
    per value saying who stated it. `ValueError` for a part that is not one
    the pin writes: no names, a name the module does not take, or an entry
    that is not one `basis` and one `value`."""
    allowed = QUALIFIER_FIELDS.get(module_id, ())
    if (
        not isinstance(names, Mapping)
        or not names
        or not set(names) <= set(allowed)
        or not all(
            isinstance(entry, Mapping)
            and set(entry) == {"basis", "value"}
            and entry["basis"] in _BASES
            for entry in names.values()
        )
    ):
        raise ValueError
    order = [name for name in allowed if name in names]
    card = f"Run {module_id}" + "".join(
        f" [{name.replace('_', ' ')}: {names[name]['value']}]" for name in order
    )
    basis = [
        f"{name.replace('_', ' ')}: "
        + (
            "derived by the host from the pinned reporting period under the"
            " owner's rule (D109)"
            if names[name]["basis"] == DERIVED
            else "stated in the run's pinned input"
        )
        for name in order
    ]
    return card + "\n" + "\n".join(basis)
