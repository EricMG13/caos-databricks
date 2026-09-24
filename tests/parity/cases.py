"""Package-agnostic parity cases: one input set, computed under `server` or `caos`.

Every builder registered in `GROUPS` takes a `Target` -- the imported package
root and, through it, the repository it lives in -- and returns JSON-ready
output. Submodules are named by their legacy dotted path (`engine.route`), which
`Target.module` maps onto the new layout (`graph.route`) when the package is
`caos`; test fixtures are imported from the target repository's own `tests/`
directory, so the legacy snapshot's fixtures drive the legacy package and the
new repository's fixtures drive `caos`. Nothing here needs a store, a provider
or a clock: every case is a pure function of committed bytes.

Values JSON cannot carry are pinned the same way on both sides by `jsonable`:
`Decimal` as its string, `bytes` as `{sha256, length}`, dataclasses through
`dataclasses.asdict`, enums by value, sets sorted, UUIDs and dates as text. A
typed refusal is recorded as `{"refusal": <code>}` rather than propagated.

Two facts differ between the snapshots by design and are masked or skipped
rather than compared. The model-extension route predicate `host_manifest_sha256`
pins `calculators/cash_flow.py`, whose two import lines are four bytes shorter
after the package rename, so the predicate is replaced by a fixed marker before
the route is digested and the fact that it equals the package's own pin is
recorded instead. CP-CF's delivered authority carries those same bytes, so the
prompt group covers every other adapter module and names CP-CF as the one it
cannot. Citation anchoring is exercised at the pure level below the store
(`_unique_run` and `_rectangles` over `_Token`), because both public entry
points read the token index from a connection.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import importlib
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from datetime import date
from decimal import Decimal
from enum import Enum
from pathlib import Path
from types import ModuleType
from uuid import UUID

type Json = None | bool | int | float | str | list[Json] | dict[str, Json]
type CaseFn = Callable[[Target], Json]

_ENGINE_PACKAGE = {"server": "engine", "caos": "graph"}
_MASKED_PIN = "<host_manifest_sha256>"


@dataclasses.dataclass(frozen=True, slots=True)
class Target:
    """The package under comparison and the repository it is checked out in."""

    package: ModuleType

    @property
    def name(self) -> str:
        return self.package.__name__

    @property
    def root(self) -> Path:
        """The repository root: the parent of the package directory."""
        location = self.package.__file__
        if location is None:
            message = f"{self.name} has no file; a namespace package cannot be compared"
            raise ValueError(message)
        return Path(location).resolve().parents[1]

    def module(self, dotted: str) -> ModuleType:
        """Import a submodule by its legacy dotted name, mapped onto this package."""
        head, _, rest = dotted.partition(".")
        if head == "engine":
            head = _ENGINE_PACKAGE.get(self.name, head)
        name = f"{self.name}.{head}.{rest}" if rest else f"{self.name}.{head}"
        return importlib.import_module(name)

    def fixture(self, name: str) -> ModuleType:
        """Import a module from the target repository's `tests/` directory."""
        tests = str(self.root / "tests")
        if tests not in sys.path:
            sys.path.insert(0, tests)
        return importlib.import_module(name)


def attr(value: object, name: str) -> object:
    """A dynamic attribute read; the package objects here are typed as `object`."""
    return getattr(value, name)


def call(owner: object, name: str, *args: object, **kwargs: object) -> object:
    """Call `owner.<name>(*args, **kwargs)` on a dynamically imported package."""
    function = getattr(owner, name)
    return function(*args, **kwargs)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Json) -> str:
    """The one canonical JSON spelling every manifest digest is taken over."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def jsonable(value: object) -> Json:
    """`value` as JSON-ready data, pinned identically under either package."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return {"sha256": sha256_hex(value), "length": len(value)}
    if isinstance(value, Enum):
        return jsonable(value.value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return jsonable(dataclasses.asdict(value))
    return _jsonable_container(value)


def _jsonable_container(value: object) -> Json:
    if isinstance(value, Mapping):
        return {_key(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(item) for item in value]
    if isinstance(value, set | frozenset):
        return sorted((jsonable(item) for item in value), key=canonical)
    if isinstance(value, UUID | Path | date):
        return str(value)
    message = f"no JSON form for {type(value).__name__}"
    raise TypeError(message)


def _key(key: object) -> str:
    return key if isinstance(key, str) else str(key)


def _exception_type(module: ModuleType, name: str) -> type[BaseException]:
    found = getattr(module, name)
    if not (isinstance(found, type) and issubclass(found, BaseException)):
        message = f"{module.__name__}.{name} is not an exception type"
        raise TypeError(message)
    return found


def refusal_or(target: Target, thunk: Callable[[], object]) -> Json:
    """The thunk's output, or `{"refusal": code}` when it raised a `Refusal`."""
    refusal = _exception_type(target.module("refusals"), "Refusal")
    try:
        value = thunk()
    except refusal as exc:
        return {"refusal": str(attr(attr(exc, "code"), "value"))}
    return jsonable(value)


def _as_dict(value: Json) -> dict[str, Json]:
    if not isinstance(value, dict):
        message = f"expected an object, got {type(value).__name__}"
        raise TypeError(message)
    return value


def _as_list(value: Json) -> list[Json]:
    if not isinstance(value, list):
        message = f"expected an array, got {type(value).__name__}"
        raise TypeError(message)
    return value


def _as_str(value: Json) -> str:
    if not isinstance(value, str):
        message = f"expected a string, got {type(value).__name__}"
        raise TypeError(message)
    return value


def _as_int(value: Json) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        message = f"expected an integer, got {type(value).__name__}"
        raise TypeError(message)
    return value


# ---------------------------------------------------------------------------
# Request mutation, as data. The legacy suites build every cash-flow input by
# taking `forecast_request()` and editing it in place; the edits are spelled
# here as paths so the same table drives both packages' fixture copies.
# ---------------------------------------------------------------------------

type _Path = tuple[str | int, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class _Op:
    kind: str
    path: _Path
    value: object = None


def _set(path: _Path, value: object) -> _Op:
    return _Op("set", path, value)


def _delete(path: _Path) -> _Op:
    return _Op("delete", path)


def _append(path: _Path, value: object) -> _Op:
    return _Op("append", path, value)


def _duplicate(path: _Path, index: int = 0) -> _Op:
    return _Op("duplicate", path, index)


def _reorder(path: _Path, order: tuple[int, ...]) -> _Op:
    return _Op("reorder", path, order)


def _keep(path: _Path, count: int) -> _Op:
    return _Op("keep", path, count)


def _child(node: object, step: str | int) -> object:
    if isinstance(node, dict) and isinstance(step, str):
        return node[step]
    if isinstance(node, list) and isinstance(step, int):
        return node[step]
    message = f"cannot step {step!r} into {type(node).__name__}"
    raise TypeError(message)


def _at(root: object, path: _Path) -> object:
    node = root
    for step in path:
        node = _child(node, step)
    return node


def _indices(value: object) -> list[int]:
    if isinstance(value, int) and not isinstance(value, bool):
        return [value]
    if isinstance(value, tuple) and all(isinstance(item, int) for item in value):
        return [item for item in value if isinstance(item, int)]
    message = f"not an index or index tuple: {value!r}"
    raise TypeError(message)


def _apply_to_list(container: list[object], op: _Op) -> None:
    if op.kind == "append":
        container.append(deepcopy(op.value))
    elif op.kind == "duplicate":
        container.append(deepcopy(container[_indices(op.value)[0]]))
    elif op.kind == "reorder":
        container[:] = [container[index] for index in _indices(op.value)]
    elif op.kind == "keep":
        del container[_indices(op.value)[0] :]
    else:
        message = f"unknown list operation {op.kind!r}"
        raise ValueError(message)


def _apply(root: object, op: _Op) -> None:
    if op.kind not in {"set", "delete"}:
        container = _at(root, op.path)
        if isinstance(container, list):
            _apply_to_list(container, op)
            return
    else:
        parent, key = _at(root, op.path[:-1]), op.path[-1]
        if isinstance(parent, dict) and isinstance(key, str):
            if op.kind == "set":
                parent[key] = op.value
            else:
                del parent[key]
            return
        if isinstance(parent, list) and isinstance(key, int) and op.kind == "delete":
            del parent[key]
            return
    message = f"{op.kind} does not apply at {op.path!r}"
    raise TypeError(message)


def _forecast_request(
    target: Target, *, quarterly: bool = False, ops: Sequence[_Op] = ()
) -> object:
    """`tests/forecast_fixtures.py::forecast_request`, then the suite's edits."""
    request = call(
        target.fixture("forecast_fixtures"), "forecast_request", quarterly=quarterly
    )
    for op in ops:
        _apply(request, op)
    return request


# ---------------------------------------------------------------------------
# cash_flow
# ---------------------------------------------------------------------------

_DRIVER0: _Path = ("drivers", 0)
_BAD_NUMBERS: tuple[tuple[str, object], ...] = (
    ("float", 1.5),
    ("int", 1),
    ("bool", True),
    ("none", None),
    ("exponent", "1e4"),
    ("huge_exponent", "1e1000000"),
    ("nineteen_digits", "1" * 19),
    ("seven_decimals", "0.1234567"),
    ("plus_sign", "+1"),
    ("leading_space", " 1"),
    ("leading_zero", "01"),
    ("nan", "NaN"),
    ("infinity", "Infinity"),
    ("decimal_object", Decimal(1)),
    ("negative", "-1"),
    ("trailing_newline", "1\n"),
)
_UNKNOWN_KEYS: tuple[tuple[str, _Path], ...] = (
    ("top_policy", ("policy",)),
    ("top_unknown", ("unknown",)),
    ("contractual_maturities", ("contractual", "maturities")),
    ("contractual_coupons", ("contractual", "coupons")),
    ("opening_unknown", ("opening", "unknown")),
    ("units_unknown", ("units", "unknown")),
    ("driver_financing_investing", (*_DRIVER0, "financing_investing")),
    ("period_unknown", ("periods", 0, "unknown")),
    ("amortisation_unknown", ("contractual", "amortisation", 0, "unknown")),
    ("facility_unknown", ("opening", "debt_by_facility", 0, "unknown")),
)
_MALFORMED: tuple[tuple[str, str, object], ...] = (
    ("perimeter_empty", "perimeter", ""),
    ("perimeter_too_long", "perimeter", "x" * 65),
    ("perimeter_bidi", "perimeter", "x\u202ey"),
    ("units_lowercase_currency", "units", {"currency": "usd", "scale": "millions"}),
    ("units_scale_not_text", "units", {"currency": "USD", "scale": []}),
    ("opening_none", "opening", None),
    ("drivers_none", "drivers", None),
    ("periods_empty", "periods", []),
    ("tolerance_negative", "tolerance", "-0.001"),
    ("amortisation_none", "contractual", {"amortisation": None}),
)
_DAYS: tuple[tuple[str, object], ...] = (
    ("zero", "0"),
    ("367", "367"),
    ("decimal", "1.0"),
    ("negative", "-1"),
    ("int", 90),
)
_ROUTE_REQUEST_OPS: tuple[_Op, ...] = (
    _keep(("periods",), 1),
    _set(("periods", 0, "period_id"), "FY2026"),
    _keep(("drivers",), 1),
    _set((*_DRIVER0, "period_id"), "FY2026"),
    _set((*_DRIVER0, "acquisitions_disposals"), "0"),
    _set((*_DRIVER0, "distributions"), "0"),
    _set((*_DRIVER0, "stated_closing_debt"), "600"),
    _set((*_DRIVER0, "stated_closing_cash"), "145"),
    _set(("opening", "debt_by_facility"), [{"facility_id": "TERM", "amount": "600"}]),
    _keep(("contractual", "amortisation"), 1),
    _set(("contractual", "amortisation", 0, "period_id"), "FY2026"),
)
_EXTRA_PAYMENTS: tuple[_Op, ...] = (
    _append(
        ("contractual", "amortisation"),
        {"case": "BASE", "period_id": "FY26", "facility_id": "BOND", "amount": "5"},
    ),
    _append(
        ("contractual", "amortisation"),
        {"case": "BASE", "period_id": "FY26", "facility_id": "TERM", "amount": "3"},
    ),
    _set((*_DRIVER0, "stated_closing_debt"), "992"),
    _set((*_DRIVER0, "stated_closing_cash"), "118"),
)


def _work_factor_periods() -> list[dict[str, str]]:
    return [
        {"case": "BASE", "period_id": str(n), "fiscal_year": "2026", "days": "bad"}
        for n in range(41)
    ]


def _six_by_forty_periods() -> list[dict[str, str]]:
    return [
        {
            "case": str(case),
            "period_id": f"{case}-{period}",
            "fiscal_year": "2026",
            "days": "366",
        }
        for case in range(6)
        for period in range(40)
    ]


def _cash_flow_table() -> dict[str, tuple[bool, tuple[_Op, ...]]]:
    table: dict[str, tuple[bool, tuple[_Op, ...]]] = {
        "annual": (False, ()),
        "quarterly": (True, ()),
        "annual_missing_cfo": (False, (_delete((*_DRIVER0, "cfo")),)),
        "annual_missing_driver": (False, (_delete(_DRIVER0),)),
        "quarterly_missing_distributions": (
            True,
            (_delete((*_DRIVER0, "distributions")),),
        ),
        "annual_driver_draft": (False, (_set((*_DRIVER0, "status"), "DRAFT"),)),
        "annual_duplicate_period": (False, (_duplicate(("periods",)),)),
        "annual_duplicate_driver": (False, (_duplicate(("drivers",)),)),
        "annual_duplicate_amortisation": (
            False,
            (_duplicate(("contractual", "amortisation")),),
        ),
        "annual_driver_unknown_period": (
            False,
            (_set((*_DRIVER0, "period_id"), "UNKNOWN"),),
        ),
        "annual_amortisation_unknown_period": (
            False,
            (_set(("contractual", "amortisation", 0, "period_id"), "UNKNOWN"),),
        ),
        "annual_duplicate_facility": (
            False,
            (
                _append(
                    ("opening", "debt_by_facility"),
                    {"facility_id": "TERM", "amount": "1"},
                ),
            ),
        ),
        "annual_zero_ebitda": (False, (_set((*_DRIVER0, "ebitda"), "0"),)),
        "annual_residual_within_tolerance": (
            False,
            (_set((*_DRIVER0, "stated_closing_cash"), "126.001"),),
        ),
        "annual_residual_over_tolerance": (
            False,
            (_set((*_DRIVER0, "stated_closing_cash"), "125.998999"),),
        ),
        "annual_without_units": (False, (_delete(("units",)),)),
        "annual_without_perimeter": (False, (_delete(("perimeter",)),)),
        "work_factor_periods": (False, (_set(("periods",), _work_factor_periods()),)),
        "work_factor_cases": (
            False,
            (_set(("periods",), [{"case": str(n), "days": "bad"} for n in range(7)]),),
        ),
        "work_factor_facilities": (
            False,
            (_set(("opening", "debt_by_facility"), [{} for _ in range(41)]),),
        ),
        "work_factor_amortisation": (
            False,
            (_set(("contractual", "amortisation"), [{} for _ in range(2001)]),),
        ),
        "annual_reordered_cases": (False, (_reorder(("periods",), (2, 0, 3, 1)),)),
        "annual_reordered_with_hidden_bad_values": (
            False,
            (
                _reorder(("periods",), (2, 0, 3, 1)),
                _set((*_DRIVER0, "status"), "DRAFT"),
                _set(("drivers", 1, "capex"), "NaN"),
            ),
        ),
        "quarterly_negative_closing_debt": (
            True,
            (
                _set((*_DRIVER0, "optional_repayment"), "1005"),
                _set((*_DRIVER0, "stated_closing_debt"), "-1"),
                _set((*_DRIVER0, "stated_closing_cash"), "-888"),
            ),
        ),
        "quarterly_largest_numbers": (
            True,
            (
                _set(("opening", "cash"), "999999999999999999.999999"),
                _set((*_DRIVER0, "stated_closing_cash"), "999999999999999999.999999"),
                _set((*_DRIVER0, "ebitda"), "0.000001"),
            ),
        ),
        "annual_amortisation_sums": (False, _EXTRA_PAYMENTS),
        "annual_amortisation_unknown_facility": (
            False,
            (
                *_EXTRA_PAYMENTS,
                _set(("contractual", "amortisation", 5, "facility_id"), "UNKNOWN"),
            ),
        ),
        "six_cases_forty_periods": (
            False,
            (
                _set(("drivers",), []),
                _set(("contractual", "amortisation"), []),
                _set(("periods",), _six_by_forty_periods()),
            ),
        ),
        "annual_signed_opening": (
            False,
            (
                _set(("opening", "debt_by_facility", 0, "amount"), "-700"),
                _set(("opening", "cash"), "-100"),
                _set((*_DRIVER0, "stated_closing_debt"), "-400"),
                _set((*_DRIVER0, "stated_closing_cash"), "-74"),
            ),
        ),
        "route_request": (False, _ROUTE_REQUEST_OPS),
    }
    for name, value in _BAD_NUMBERS:
        table[f"annual_cfo_{name}"] = (False, (_set((*_DRIVER0, "cfo"), value),))
    for name, path in _UNKNOWN_KEYS:
        table[f"annual_unknown_key_{name}"] = (False, (_set(path, "0"),))
    for name, field, value in _MALFORMED:
        table[f"annual_malformed_{name}"] = (False, (_set((field,), value),))
    for name, value in _DAYS:
        table[f"annual_days_{name}"] = (False, (_set(("periods", 0, "days"), value),))
    return table


def _cash_flow_case(quarterly: bool, ops: tuple[_Op, ...], target: Target) -> Json:
    request = _forecast_request(target, quarterly=quarterly, ops=ops)
    module = target.module("calculators.cash_flow")
    return {
        "forecast": refusal_or(
            target, functools.partial(call, module, "cash_flow_forecast", request)
        ),
        "bytes": refusal_or(
            target, functools.partial(call, module, "forecast_bytes", request)
        ),
    }


def _cash_flow_cases() -> dict[str, CaseFn]:
    return {
        name: functools.partial(_cash_flow_case, quarterly, ops)
        for name, (quarterly, ops) in _cash_flow_table().items()
    }


# ---------------------------------------------------------------------------
# pricing
# ---------------------------------------------------------------------------

_MODEL = "a-model/for-the-test"
_PRICES: dict[str, tuple[object, object, object, object]] = {
    "test_price": (
        _MODEL,
        Decimal("0.0000001"),
        Decimal("0.000002"),
        date(2026, 9, 13),
    ),
    "opus_price": (
        "anthropic/claude-opus-5-20260723",
        Decimal("0.000005"),
        Decimal("0.000025"),
        date(2026, 9, 22),
    ),
    # `Decimal("0.10") / MAX_COMPLETION_TOKENS`, written out so the case does
    # not depend on the ambient context.
    "output_only_price": (
        _MODEL,
        Decimal(0),
        Decimal("0.00000152587890625"),
        date(2026, 9, 13),
    ),
}
_INVALID_PRICES: dict[str, tuple[object, object, object, object]] = {
    "input_nan": (_MODEL, Decimal("NaN"), Decimal("0.000002"), date(2026, 9, 13)),
    "output_negative": (
        _MODEL,
        Decimal("0.0000001"),
        Decimal("-0.1"),
        date(2026, 9, 13),
    ),
    "output_float": (_MODEL, Decimal("0.0000001"), 0.1, date(2026, 9, 13)),
    "input_bool": (_MODEL, True, Decimal("0.000002"), date(2026, 9, 13)),
    "model_empty": ("", Decimal("0.0000001"), Decimal("0.000002"), date(2026, 9, 13)),
    "input_1200_digits": (
        _MODEL,
        Decimal("0." + "1" * 1200),
        Decimal("0.000002"),
        date(2026, 9, 13),
    ),
    "free": (_MODEL, Decimal(0), Decimal(0), date(2026, 9, 13)),
}
_REQUEST_SIZES: tuple[tuple[str, object], ...] = (
    ("0", 0),
    ("1", 1),
    ("2", 2),
    ("100", 100),
    ("4096", 4096),
    ("65536", 65_536),
    ("1000000", 1_000_000),
    # The legacy ceiling, priced since D29 raised the transport ceiling.
    ("1048576", 1_048_576),
    ("1048577", 1_048_577),
    ("ceiling", 4_194_304),
    ("over_ceiling", 4_194_305),
    ("negative", -1),
    ("bool", True),
    ("float", 100.0),
)


def _price(target: Target, parts: tuple[object, object, object, object]) -> object:
    return call(target.module("pricing"), "ModelPrice", *parts)


def _priced_request_case(
    parts: tuple[object, object, object, object], size: object, target: Target
) -> Json:
    pricing = target.module("pricing")
    price = _price(target, parts)
    return refusal_or(
        target, functools.partial(call, pricing, "priced_request", price, size)
    )


def _worst_case_case(
    parts: tuple[object, object, object, object], target: Target
) -> Json:
    pricing = target.module("pricing")
    price = _price(target, parts)
    return refusal_or(target, functools.partial(call, pricing, "worst_case", price))


def _pricing_cases() -> dict[str, CaseFn]:
    cases: dict[str, CaseFn] = {}
    for price_name, parts in _PRICES.items():
        for size_name, size in _REQUEST_SIZES:
            cases[f"{price_name}__request_{size_name}"] = functools.partial(
                _priced_request_case, parts, size
            )
        cases[f"{price_name}__worst_case"] = functools.partial(_worst_case_case, parts)
    for price_name, parts in _INVALID_PRICES.items():
        cases[f"invalid_{price_name}__worst_case"] = functools.partial(
            _worst_case_case, parts
        )
    return cases


# ---------------------------------------------------------------------------
# budget: `validate_spend` and the default ceiling. `remaining`, `ceiling_of`,
# `reserve` and `reserved_for` each read the store, so they are out of scope.
# ---------------------------------------------------------------------------

_SPEND: tuple[tuple[str, object], ...] = (
    ("bool", True),
    ("int", 1),
    ("float", 0.1),
    ("str", "0.1"),
    ("nan", Decimal("NaN")),
    ("snan", Decimal("sNaN")),
    ("infinity", Decimal("Infinity")),
    ("negative_infinity", Decimal("-Infinity")),
    ("negative", Decimal("-0.01")),
    ("exponent_131072", Decimal("1e131072")),
    ("exponent_minus_16384", Decimal("1e-16384")),
    ("zero_exponent_minus_16384", Decimal("0e-16384")),
    ("zero_exponent_131072", Decimal("0e131072")),
    ("scaled_exponent_minus_16383", Decimal("1.00e-16383")),
    ("zero", Decimal("0")),
    ("negative_zero", Decimal("-0.00")),
    ("quarter", Decimal("0.2500")),
    ("exponent_131071", Decimal("1e131071")),
    ("exponent_minus_16383", Decimal("1e-16383")),
    ("ceiling", Decimal("5.00")),
    ("per_token", Decimal("0.0000001")),
)


def _validate_spend_case(amount: object, target: Target) -> Json:
    budget = target.module("store.budget")
    outcome = refusal_or(
        target, functools.partial(call, budget, "validate_spend", amount)
    )
    return {"validate_spend": "accepted" if outcome is None else outcome}


def _ceiling_case(target: Target) -> Json:
    return jsonable(attr(target.module("store.budget"), "CEILING"))


def _budget_cases() -> dict[str, CaseFn]:
    cases: dict[str, CaseFn] = {
        f"validate_spend_{name}": functools.partial(_validate_spend_case, amount)
        for name, amount in _SPEND
    }
    cases["default_ceiling"] = _ceiling_case
    return cases


# ---------------------------------------------------------------------------
# forecast
# ---------------------------------------------------------------------------


def _forecast_markdown(target: Target, request: object, bindings: Json = None) -> bytes:
    """`tests/test_forecast_handoff.py::forecast_markdown`, with optional bindings."""
    result = call(target.module("calculators.cash_flow"), "cash_flow_forecast", request)
    document = {"request": request, "bindings": bindings or {}, "forecast": result}
    return ("```caos-forecast-v1\n" + json.dumps(document) + "\n```\n").encode()


def _assignment_rows(value: Json, pointer: str = "") -> dict[str, str]:
    """`tests/test_forecast_route.py::assignment_rows`."""
    if isinstance(value, dict) and value:
        return {
            p: v
            for k, item in value.items()
            for p, v in _assignment_rows(item, pointer + "/" + k).items()
        }
    if isinstance(value, list) and value:
        return {
            p: v
            for i, item in enumerate(value)
            for p, v in _assignment_rows(item, pointer + "/" + str(i)).items()
        }
    return {pointer: pointer + " = " + json.dumps(value)}


def _owner(pointer: str) -> str:
    if pointer.startswith("/contractual/"):
        return "CP-4"
    if pointer.startswith("/drivers/"):
        return "CP-2G"
    return "CP-1"


@dataclasses.dataclass(frozen=True, slots=True)
class _Bound:
    """A forecast handoff whose every requested value is bound to an owner quote."""

    markdown: bytes
    upstream: dict[str, bytes]
    quotes: dict[str, str]


def _bound(target: Target, defect: str = "") -> _Bound:
    request = _forecast_request(target, ops=_ROUTE_REQUEST_OPS)
    rows = _assignment_rows(jsonable(request))
    quotes = {
        m: "\n".join(v for p, v in rows.items() if _owner(p) == m)
        for m in ("CP-1", "CP-2G", "CP-4")
    }
    bindings: dict[str, Json] = {
        p: {"module_id": _owner(p), "quote": quotes[_owner(p)]} for p in rows
    }
    if defect == "missing":
        del bindings["/opening/cash"]
    elif defect == "wrong-owner":
        bindings["/opening/cash"] = {"module_id": "CP-2G", "quote": quotes["CP-2G"]}
    block = _forecast_markdown(target, request, bindings)
    markdown = block + "\n".join(quotes.values()).encode() + b"\n"
    upstream = {m: q.encode() for m, q in quotes.items()}
    if defect == "quote-not-upstream":
        upstream["CP-1"] = b""
    return _Bound(markdown, upstream, quotes)


def _anchored_quote(target: Target, quote: str) -> object:
    citations = target.module("evidence.citations")
    return call(citations, "AnchoredCitation", "c" * 64, 1, quote, ())


def _projection_case(variant: str, target: Target) -> Json:
    forecast = target.module("methodology.forecast")
    if variant == "quarterly":
        markdown = _forecast_markdown(target, _forecast_request(target, quarterly=True))
    elif variant == "route_request":
        markdown = _forecast_markdown(
            target, _forecast_request(target, ops=_ROUTE_REQUEST_OPS)
        )
    elif variant == "not_ready":
        draft = _forecast_request(
            target, ops=(_set((*_DRIVER0, "status"), "NOT_READY"),)
        )
        markdown = _forecast_markdown(target, draft)
    else:
        markdown = _forecast_markdown(target, _forecast_request(target))
    if variant == "changed_result":
        markdown = markdown.replace(b'"126.000000"', b'"999.000000"')
    elif variant == "two_blocks":
        markdown += markdown
    elif variant == "code_selection":
        markdown = markdown.replace(
            b'"request":', b'"calculator": "os.system", "request":'
        )
    elif variant == "duplicate_keys":
        markdown = markdown.replace(
            b'"bindings": {}', b'"bindings": {}, "bindings": {}'
        )
    return {
        "projection": refusal_or(
            target, functools.partial(call, forecast, "forecast_projection", markdown)
        ),
        "inputs": refusal_or(
            target, functools.partial(call, forecast, "forecast_inputs", markdown)
        ),
    }


def _bindings_case(defect: str, target: Target) -> Json:
    forecast = target.module("methodology.forecast")
    if defect == "empty":
        thunk = functools.partial(
            call,
            forecast,
            "validate_forecast_bindings",
            _forecast_markdown(target, _forecast_request(target)),
            {},
            {},
        )
    else:
        bound = _bound(target, defect)
        citations = {m: (_anchored_quote(target, q),) for m, q in bound.quotes.items()}
        thunk = functools.partial(
            call,
            forecast,
            "validate_forecast_bindings",
            bound.markdown,
            bound.upstream,
            citations,
        )
    outcome = refusal_or(target, thunk)
    return {"validate_forecast_bindings": "accepted" if outcome is None else outcome}


def _driver_mapping_case(variant: str, target: Target) -> Json:
    forecast = target.module("methodology.forecast")
    fixtures = target.fixture("canonical_fixtures")
    routes = target.fixture("canonical_route_fixtures")
    owner = call(routes, "canonical_markdown", call(routes, "route_identity", "CP-2G"))
    if not isinstance(owner, bytes):
        message = "canonical_markdown did not return bytes"
        raise TypeError(message)
    ops: tuple[_Op, ...] = _ROUTE_REQUEST_OPS
    if variant == "wrong_scale":
        ops = (*ops, _set(("units", "scale"), "units"))
    markdown = _forecast_markdown(target, _forecast_request(target, ops=ops))
    if variant == "changed_movement":
        owner = owner.replace(b"| 0 | CURRENCY_MM", b"| 1 | CURRENCY_MM", 1)
    outcome = refusal_or(
        target,
        functools.partial(
            call,
            forecast,
            "validate_driver_mapping",
            attr(fixtures, "CONTRACT"),
            markdown,
            owner,
        ),
    )
    return {
        "owner_sha256": sha256_hex(owner),
        "validate_driver_mapping": "accepted" if outcome is None else outcome,
    }


def _forecast_cases() -> dict[str, CaseFn]:
    cases: dict[str, CaseFn] = {}
    for variant in (
        "annual",
        "quarterly",
        "route_request",
        "changed_result",
        "not_ready",
        "two_blocks",
        "code_selection",
        "duplicate_keys",
    ):
        cases[f"projection_{variant}"] = functools.partial(_projection_case, variant)
    for defect in ("empty", "bound", "missing", "wrong-owner", "quote-not-upstream"):
        cases[f"bindings_{defect.replace('-', '_')}"] = functools.partial(
            _bindings_case, defect
        )
    for variant in ("vendor_rows", "changed_movement", "wrong_scale"):
        cases[f"driver_mapping_{variant}"] = functools.partial(
            _driver_mapping_case, variant
        )
    return cases


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------

# `methodology/handoff.py::ADAPTER_ROUTES`, spelled here so the case names are
# known before any package is imported; `test_routes.py` holds the two equal.
ADAPTER_ROUTES: tuple[tuple[str, str], ...] = (
    ("FULL_CREDIT_32", "COVENANT_REFINANCING"),
    ("FULL_CREDIT_32", "DECISION_LEDGER"),
    ("FULL_CREDIT_32", "DEEP_RESEARCH"),
    ("FULL_CREDIT_32", "DISTRESSED_RESTRUCTURING"),
    ("FULL_CREDIT_32", "EARNINGS_UPDATE"),
    ("FULL_CREDIT_32", "FULL_CREDIT_ASSESSMENT"),
    ("FULL_CREDIT_32", "LIQUIDITY_REVIEW"),
    ("FULL_CREDIT_32", "MARKET_DISLOCATION"),
    ("FULL_CREDIT_32", "PORTFOLIO_DECISION"),
    ("FULL_CREDIT_32", "RELATIVE_VALUE"),
    ("LITE_CREDIT_22", "LITE_COVENANT_REFINANCING"),
    ("LITE_CREDIT_22", "LITE_DECISION_LEDGER"),
    ("LITE_CREDIT_22", "LITE_DEEP_RESEARCH"),
    ("LITE_CREDIT_22", "LITE_DISTRESSED_RESTRUCTURING"),
    ("LITE_CREDIT_22", "LITE_EARNINGS_UPDATE"),
    ("LITE_CREDIT_22", "LITE_FULL_CREDIT_SCREEN"),
    ("LITE_CREDIT_22", "LITE_PORTFOLIO_DECISION"),
    ("LITE_CREDIT_22", "LITE_RELATIVE_VALUE"),
)
_CATALOG_PATH = Path(
    "vendor/deploy-v/skills/cp-os-credit-os/references/CREDIT_OS_V_MODULE_CATALOG_v2.json"
)
_BRIEF = {"question": "refinancing"}
_ROUTE_VARIANTS: dict[str, tuple[Mapping[str, str] | None, bool]] = {
    "plain": (None, False),
    "research": (_BRIEF, False),
    "model": (None, True),
    "research_and_model": (_BRIEF, True),
}


@functools.cache
def _catalog(root: Path) -> dict[str, Json]:
    return _as_dict(json.loads((root / _CATALOG_PATH).read_text(encoding="utf-8")))


def _pairs(value: object) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    if not isinstance(value, tuple):
        message = f"predicates are not a tuple: {type(value).__name__}"
        raise TypeError(message)
    for item in value:
        if not (isinstance(item, tuple) and len(item) == 2):
            message = "a predicate is not a pair"
            raise TypeError(message)
        pairs.append((str(item[0]), str(item[1])))
    return pairs


def _masked_route(target: Target, route: object) -> tuple[object, bool | None]:
    """`route` with the host pin predicate replaced, and whether it was current."""
    route_mod = target.module("engine.route")
    pin = str(attr(target.module("methodology.host_pin"), "HOST_MANIFEST_SHA256"))
    current: bool | None = None
    masked: list[tuple[str, str]] = []
    for key, value in _pairs(attr(route, "predicates")):
        if key == "host_manifest_sha256":
            current = value == pin
            masked.append((key, _MASKED_PIN))
        else:
            masked.append((key, value))
    copy = call(
        route_mod,
        "ResolvedRoute",
        profile_id=attr(route, "profile_id"),
        selection_id=attr(route, "selection_id"),
        nodes=attr(route, "nodes"),
        edges=attr(route, "edges"),
        predicates=tuple(masked),
    )
    return copy, current


def _describe_route(target: Target, route: object) -> Json:
    route_mod = target.module("engine.route")
    masked, current = _masked_route(target, route)
    modules = [
        _as_str(_as_dict(node)["module_id"])
        for node in _as_list(jsonable(attr(route, "nodes")))
    ]
    return {
        "nodes": jsonable(attr(route, "nodes")),
        "edges": jsonable(attr(route, "edges")),
        "predicates": jsonable(attr(masked, "predicates")),
        "host_pin_is_current": current,
        "digest": jsonable(call(route_mod, "route_digest", masked)),
        "route_json": jsonable(call(route_mod, "route_json", masked)),
        "frontier": jsonable(call(route_mod, "frontier", route, {})),
        "node_states": jsonable(call(route_mod, "node_states", route, {})),
        "predecessors": {
            module: jsonable(call(route_mod, "predecessors", route, module))
            for module in modules
        },
    }


def _resolve(
    target: Target,
    selection: tuple[str, str],
    *,
    research_brief: Mapping[str, str] | None = None,
    model_extension: bool = False,
) -> object:
    route_mod = target.module("engine.route")
    extensions = call(
        route_mod,
        "RouteExtensions",
        research_brief=research_brief,
        model_extension=model_extension,
    )
    return call(
        route_mod,
        "resolve_route",
        _catalog(target.root),
        *selection,
        extensions=extensions,
    )


def _route_case(selection: tuple[str, str], variant: str, target: Target) -> Json:
    brief, model = _ROUTE_VARIANTS[variant]

    def describe() -> Json:
        route = _resolve(target, selection, research_brief=brief, model_extension=model)
        return _describe_route(target, route)

    return refusal_or(target, describe)


def _routes_cases() -> dict[str, CaseFn]:
    return {
        f"{profile}__{selection}__{variant}": functools.partial(
            _route_case, (profile, selection), variant
        )
        for profile, selection in ADAPTER_ROUTES
        for variant in _ROUTE_VARIANTS
    }


# ---------------------------------------------------------------------------
# digest
# ---------------------------------------------------------------------------

_DIGEST_VALUES: dict[str, object] = {
    "key_order": {"b": 1, "a": 2},
    "non_ascii_kept": {"name": "Soci\u00e9t\u00e9"},
    "nested": {
        "z": [1, 2.5, {"y": None, "x": [True, False, "\u00fc", "\u65e5\u672c\u8a9e"]}],
        "a": {"nested": {"deep": [[], {}, ""]}},
        "n": -0.0,
        "big": 12345678901234567890,
        "emoji": "smile \U0001f600 joiner \u200d done",
    },
    "unicode_forms": {
        "nfc": "\u00e9",
        "nfd": "e\u0301",
        "line_separator": "a\u2028b",
        "controls": "tab\there\nnewline\r\n",
        "quote": 'she said "hi" \\ back',
        "astral": "\U0001d518\U0001d52b",
    },
    "key_sorting_by_code_point": {"\u00e9": 1, "e": 2, "z": 3, "Z": 4, "10": 1, "9": 2},
    "nested_lists": [[[]], [1, [2, [3, [4]]]], [None, [None]]],
    "empty_containers": {"dict": {}, "list": [], "str": ""},
    "numbers": {
        "float": 0.1 + 0.2,
        "large": 1e100,
        "small": 5e-324,
        "int": -1,
        "one": 1.0,
    },
    "decimals_as_strings": {
        "amount": str(Decimal("1.10")),
        "exact": str(Decimal("0.0000001")),
        "rows": [str(Decimal("-0.00")), str(Decimal("1E+3"))],
    },
    "scalar_string": "just a string",
    "scalar_none": None,
    "scalar_true": True,
    "decimal_object": {"amount": Decimal("1.10")},
    "nan": {"x": float("nan")},
    "infinity": [float("inf")],
}


def _digest_case(value: object, target: Target) -> Json:
    digest = target.module("digest")
    try:
        text = call(digest, "canonical_json", value)
        hexdigest = call(digest, "canonical_digest", value)
    except (TypeError, ValueError) as exc:
        return {"error": type(exc).__name__}
    return {"canonical_json": jsonable(text), "canonical_digest": jsonable(hexdigest)}


def _digest_cases() -> dict[str, CaseFn]:
    return {
        name: functools.partial(_digest_case, value)
        for name, value in _DIGEST_VALUES.items()
    }


# ---------------------------------------------------------------------------
# boundary_text
# ---------------------------------------------------------------------------

_BIDI = ("202a", "202b", "202c", "202d", "202e", "2066", "2067", "2068", "2069")
_BOUNDARY: dict[str, tuple[str, int | None]] = {
    "plain": ("Acme Holdings Ltd", None),
    "empty": ("", None),
    "nfc_composes_within_limit": ("e\u0301" * 3, 3),
    "nfc_composes_over_limit": ("e\u0301" * 4, 3),
    "hangul_composes": ("\u1100\u1161", None),
    "combining_marks_reordered": ("a\u0323\u0307", None),
    "combining_marks_reordered_other_way": ("a\u0307\u0323", None),
    "fullwidth_letter_kept": ("\uff21cme", None),
    "compatibility_ligature_kept": ("\ufb01nance", None),
    "at_limit": ("x" * 4096, None),
    "over_limit": ("x" * 4097, None),
    "limit_zero_empty": ("", 0),
    "limit_zero_one_char": ("a", 0),
    "kept_carriage_return": ("Acme\rLtd", None),
    "kept_newline": ("Acme\nLtd", None),
    "kept_tab": ("Acme\tLtd", None),
    "crlf_mixed": ("line one\r\nline two\n\tindented", None),
    "control_nul": ("Acme\x00Ltd", None),
    "control_bell": ("Acme\x07Ltd", None),
    "control_escape": ("Acme\x1bLtd", None),
    "control_delete": ("Acme\x7fLtd", None),
    "control_next_line": ("Acme\x85Ltd", None),
    "lone_high_surrogate": ("Acme\ud800Ltd", None),
    "lone_low_surrogate": ("Acme\udfffLtd", None),
    "zero_width_space": ("Acme\u200bLtd", None),
    "zero_width_joiner": ("Acme\u200dLtd", None),
    "byte_order_mark": ("\ufeffAcme", None),
    "no_break_space": ("Acme\u00a0Ltd", None),
    "line_separator": ("Acme\u2028Ltd", None),
    "paragraph_separator": ("Acme\u2029Ltd", None),
    "private_use": ("Acme\ue000Ltd", None),
    "unassigned": ("Acme\u0378Ltd", None),
    "noncharacter": ("Acme\ufffeLtd", None),
    "replacement_character": ("Acme\ufffdLtd", None),
    "astral_letters": ("\U0001d518\U0001d52b\U0001d526", None),
    "emoji_sequence": ("\U0001f469\u200d\U0001f4bb", None),
    "tag_character": ("Acme\U000e0041Ltd", None),
    "soft_hyphen": ("Acme\u00adLtd", None),
    "word_joiner": ("Acme\u2060Ltd", None),
    "arabic_letter_mark": ("Acme\u061cLtd", None),
    "right_to_left_mark": ("Acme\u200fLtd", None),
}


def _boundary_case(raw: str, limit: int | None, target: Target) -> Json:
    boundary = attr(target.module("boundary_text"), "BoundaryText")
    kwargs: dict[str, object] = {} if limit is None else {"limit": limit}
    outcome = refusal_or(target, functools.partial(call, boundary, "of", raw, **kwargs))
    return {"input_code_points": len(raw), "outcome": outcome}


def _boundary_cases() -> dict[str, CaseFn]:
    cases: dict[str, CaseFn] = {
        name: functools.partial(_boundary_case, raw, limit)
        for name, (raw, limit) in _BOUNDARY.items()
    }
    for code in _BIDI:
        cases[f"bidi_{code}"] = functools.partial(
            _boundary_case, f"Acme Holdings{chr(int(code, 16))} Ltd", None
        )
    return cases


# ---------------------------------------------------------------------------
# extraction
# ---------------------------------------------------------------------------

# Three small public plain-text documents under `qualification/*/documents/`,
# each named by the qualification set whose answer key quotes it.
DOCUMENTS: tuple[tuple[str, str], ...] = (
    ("ccl-fy2025-market-dislocation", "CCL_FINRA_TRACE_143658BY7_2026-09-19.txt"),
    ("ccl-fy2025-relative-value", "RCL_Q4_2025_Earnings_Release.txt"),
    ("ccl-fy2025-relative-value", "NCLH_Q4_2025_Earnings_Release.txt"),
)
_FULL_TABLE_TOKENS = 2000
_TWO_PARAGRAPHS = b"""Total debt at 31 December 2026
was USD 1,240.0m.

Cash stood at USD 310.5m.
"""
_SYNTHETIC_TEXT: dict[str, bytes] = {
    "two_paragraphs": _TWO_PARAGRAPHS,
    "single_word": b"Leverage\n",
    "column_gap": b"net    leverage\n",
    "second_page": b"\n".join(b"line %d" % n for n in range(62)),
    "tab_and_no_break_space": "Total\tdebt\u00a0was USD 1,240.0m".encode(),
    "tab_column": b"Total\tdebt",
    "long_run_is_cut": b"x" * 5000 + b" y",
    "empty": b"",
    "blank_lines_only": b"\n\n   \n\t\n",
    "not_utf8": b"\xff\xfe\x00 not text",
    "windows_newlines": b"one two\r\nthree\r\n\r\nfour",
    "unicode_words": (
        "Soci\u00e9t\u00e9 G\u00e9n\u00e9rale \u65e5\u672c \U0001f600"
    ).encode(),
}


def _document(target: Target, qualification_set: str, filename: str) -> bytes:
    path = target.root / "qualification" / qualification_set / "documents" / filename
    return path.read_bytes()


def _tokens(target: Target, data: bytes) -> object:
    extractor = call(target.module("evidence.extract"), "PlainTextExtractor")
    return call(extractor, "extract", data)


def _token_summary(target: Target, data: bytes) -> Json:
    ingest = target.module("evidence.ingest")
    table = _as_list(jsonable(_tokens(target, data)))
    rows = [_as_dict(row) for row in table]
    pages = {_as_int(row["page"]) for row in rows}
    regions = {_as_int(row["region_id"]) for row in rows}
    lines = sorted({_as_int(row["line_id"]) for row in rows})
    blocks = jsonable(call(ingest, "block_ids_by_line", dict.fromkeys(lines, 1)))
    groups = [
        len(_as_list(jsonable(call(ingest, "line_groups", line))))
        for line in data.decode("utf-8").splitlines()
    ]
    tokens: Json = (
        table
        if len(table) <= _FULL_TABLE_TOKENS
        else jsonable(
            {
                "sha256": sha256_hex(canonical(table).encode("utf-8")),
                "head": table[:40],
                "tail": table[-10:],
            }
        )
    )
    return {
        "token_count": len(table),
        "page_count": len(pages),
        "region_count": len(regions),
        "line_count": len(lines),
        "tokens": tokens,
        "blocks": blocks
        if len(lines) <= _FULL_TABLE_TOKENS
        else {
            "sha256": sha256_hex(canonical(blocks).encode("utf-8")),
            "count": len(lines),
        },
        "line_groups": {"total": sum(groups), "max_per_line": max(groups, default=0)},
    }


def _extraction_case(data: bytes, target: Target) -> Json:
    extract = target.module("evidence.extract")
    extractor = call(extract, "dispatch_by_content", data)
    identity = call(attr(extractor, "identity"), "canonical")
    return {
        "document_sha256": sha256_hex(data),
        "bytes": len(data),
        "identity": jsonable(identity),
        "extraction": refusal_or(
            target, functools.partial(_token_summary, target, data)
        ),
    }


def _public_extraction_case(
    qualification_set: str, filename: str, target: Target
) -> Json:
    return _extraction_case(_document(target, qualification_set, filename), target)


def _extraction_cases() -> dict[str, CaseFn]:
    cases: dict[str, CaseFn] = {
        f"synthetic_{name}": functools.partial(_extraction_case, data)
        for name, data in _SYNTHETIC_TEXT.items()
    }
    for qualification_set, filename in DOCUMENTS:
        cases[f"{qualification_set}__{filename}"] = functools.partial(
            _public_extraction_case, qualification_set, filename
        )
    return cases


# ---------------------------------------------------------------------------
# citations: the pure search rule, `_unique_run` then `_rectangles`, over the
# plain-text extractor's tokens re-shaped as the matcher's own `_Token`.
# ---------------------------------------------------------------------------

_SYNTHETIC_QUOTES: tuple[tuple[str, str, bool], ...] = (
    ("exact_line", "Total debt at 31 December 2026", False),
    ("edge_punctuation", '"Total debt at 31 December 2026."', False),
    ("wraps_within_region", "December 2026 was USD", False),
    ("crosses_region", "1,240.0m. Cash stood", False),
    ("ambiguous_word", "USD", False),
    ("empty", "", False),
    ("case_mismatch", "debt at 31 december", False),
    ("interior_punctuation_differs", "Total debt, at 31", False),
    ("whitespace_variants", "Total\tdebt   at\u00a031 December", False),
    ("tracking_off_single_letters", "Heading word", False),
    ("tracking_on_single_letters", "Heading word", True),
    # EV-8: the normalised pass compares NFC and never NFKC. Each quote below
    # is the page's words under compatibility folding (a superscript, a
    # ligature, full-width digits), which no NFC comparison equates.
    ("compatibility_superscript", "leverage x2 on", False),
    ("compatibility_ligature", "on financing of", True),
    ("compatibility_fullwidth_digits", "of 12 per", False),
    ("compatibility_verbatim", "leverage x\u00b2 on \ufb01nancing of", False),
)
_TRACKING_TEXT = b"H e a d i n g word\nA B\n"
_COMPATIBILITY_TEXT = (
    "Net leverage x\u00b2 on \ufb01nancing of \uff11\uff12 per cent\n".encode()
)


def _matcher_tokens(target: Target, data: bytes) -> dict[int, list[object]]:
    """The extractor's tokens per page, as `citations._Token` values."""
    citations = target.module("evidence.citations")
    by_page: dict[int, list[object]] = {}
    for row in _as_list(jsonable(_tokens(target, data))):
        fields = _as_dict(row)
        page = _as_int(fields.pop("page"))
        by_page.setdefault(page, []).append(call(citations, "_Token", **fields))
    return by_page


def _locate(
    target: Target, page: int, tokens: list[object], quote: str, tracking: bool
) -> Json:
    citations = target.module("evidence.citations")

    def rectangles() -> object:
        run = call(citations, "_unique_run", tokens, quote, tracking=tracking)
        return call(citations, "_rectangles", run, page)

    return refusal_or(target, rectangles)


def _quote_case(
    target: Target, by_page: Mapping[int, list[object]], quote: str, tracking: bool
) -> Json:
    located: dict[str, Json] = {}
    refused: dict[str, list[Json]] = {}
    for page, tokens in sorted(by_page.items()):
        outcome = _locate(target, page, tokens, quote, tracking)
        if isinstance(outcome, dict) and "refusal" in outcome:
            refused.setdefault(_as_str(outcome["refusal"]), []).append(page)
        else:
            located[str(page)] = outcome
    return {
        "matched_text": quote,
        "tracking": tracking,
        "located": located,
        "refused": jsonable(refused),
    }


def _synthetic_citation_case(
    name: str, quote: str, tracking: bool, target: Target
) -> Json:
    data = _TRACKING_TEXT if name.startswith("tracking") else _TWO_PARAGRAPHS
    if name.startswith("compatibility"):
        data = _COMPATIBILITY_TEXT
    return _quote_case(target, _matcher_tokens(target, data), quote, tracking)


def _answer_key_quotes(
    target: Target, qualification_set: str, digest: str
) -> list[str]:
    path = target.root / "qualification" / qualification_set / "qualification.json"
    document = _as_dict(json.loads(path.read_text(encoding="utf-8")))
    quotes: list[str] = []
    for case in _as_list(document["cases"]):
        for expect in _as_list(_as_dict(case).get("expects", [])):
            fields = _as_dict(expect)
            quote = _as_str(fields["matched_text"])
            if fields.get("document_sha256") == digest and quote not in quotes:
                quotes.append(quote)
    if not quotes:
        message = f"{qualification_set} names no answer-key quote for {digest[:12]}"
        raise ValueError(message)
    return quotes


def _public_citation_case(
    qualification_set: str, filename: str, target: Target
) -> Json:
    data = _document(target, qualification_set, filename)
    digest = sha256_hex(data)
    by_page = _matcher_tokens(target, data)
    return {
        "document_sha256": digest,
        "quotes": [
            _quote_case(target, by_page, quote, False)
            for quote in _answer_key_quotes(target, qualification_set, digest)
        ],
    }


def _citations_cases() -> dict[str, CaseFn]:
    cases: dict[str, CaseFn] = {
        f"synthetic_{name}": functools.partial(
            _synthetic_citation_case, name, quote, tracking
        )
        for name, quote, tracking in _SYNTHETIC_QUOTES
    }
    for qualification_set, filename in DOCUMENTS:
        cases[f"{qualification_set}__{filename}"] = functools.partial(
            _public_citation_case, qualification_set, filename
        )
    return cases


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------

_RENDER_MARKDOWN = "Total debt at 31 December 2026 was USD 1,240.0m.\n"
_BUILD_ID = "a43cb903ca2751f79e77b6da71f6ea131b8462a3"
_AUTHORITY_DIGEST = "0302b789df5d0cae" + "0" * 48
_RENDER_QUOTE = "Total debt at 31 December 2026"
_DOCUMENT_SHA256 = "6fc4a221c5d5" + "0" * 52
_PROJECTIONS: dict[str, Json] = {
    "module_id": "CP-1",
    "qa_status": "Passed",
    "committee_status": "Committee Ready",
    "decision_scope": "COMMITTEE",
    "limitation_flags": [],
}
_MARKDOWN_HANDOFF = (
    "---\n"
    "module_id: CP-1\n"
    "---\n"
    "## Audit Summary\n\n"
    "Total debt at 31 December 2026 was **USD 1,240.0m**.\n\n"
    "### Registers\n\n"
    "| Metric | Value |\n"
    "| --- | --- |\n"
    "| Net leverage | 4.2x |\n\n"
    "- One limitation\n"
    "- Another limitation\n\n"
    "> The covenant headroom is thin.\n"
)
_AUTHORED_SOURCE = "\n\n".join(
    [
        "# Heading one",
        "###### Heading six",
        "Ordinary prose with **strong**, *emphasis* and `a code span`.",
        "<!-- MATERIAL: management refused the covenant schedule -->",
        "A [link](https://example.test) and an ![image](x.png).",
        "A raw <span data-x='1'>tag</span> and an entity &amp;.",
        "7. Covenant headroom breached\n9. Waiver requested",
        "- bullet one\n- bullet two",
        "> A quoted caveat from the issuer.",
        '```caos-forecast-v1\n{"driver": 1}\n``` trailing note',
        "| Leverage | Headroom |\n| --- | --- |\n| 4.2x | 0.3x |",
        "Leverage | covenant headroom\n---",
        "***",
    ]
)
_NESTED_LISTS = "- one\n  - two\n    - three\n      - four\n        - five\n"
_INLINE_EDGE_CASES = (
    "net_debt_to_ebitda is 2 * 3 and *unpaired\n\n"
    "`a*b*c` keeps its stars and *a **b* c** is literal\n\n"
    "**strong *nested* strong** then `code`\n"
)


def _artifact(
    markdown: str, projections: Json = None, citations: Json = None
) -> dict[str, Json]:
    """`tests/test_deliverable_render.py::_artifact`: one bound canonical artifact."""
    digest = sha256_hex(markdown.encode("utf-8"))
    record: dict[str, Json] = {
        "artifact_sha256": digest,
        "build_id": _BUILD_ID,
        "authority_digest": _AUTHORITY_DIGEST,
        "projections": deepcopy(_PROJECTIONS) if projections is None else projections,
        "citations": (
            [
                {
                    "document_sha256": _DOCUMENT_SHA256,
                    "page": 1,
                    "matched_text": _RENDER_QUOTE,
                }
            ]
            if citations is None
            else citations
        ),
    }
    record_json = json.dumps(record, sort_keys=True, separators=(",", ":"))
    return {
        "markdown": markdown,
        "record": record_json,
        "artifact_sha256": digest,
        "record_sha256": sha256_hex(record_json.encode("utf-8")),
    }


def _payload(artifact: Json | None = None, **changes: Json) -> dict[str, Json]:
    payload: dict[str, Json] = {
        "case_title": "Acme Holdings plc",
        "revision_id": "rev-001",
        "artifacts": [_artifact(_RENDER_MARKDOWN) if artifact is None else artifact],
        "narrative": "Leverage is inside the covenant with limited headroom.",
    }
    payload.update(changes)
    return payload


def _restricted_projections() -> Json:
    return {
        **_PROJECTIONS,
        "qa_status": "Restricted",
        "committee_status": "Restricted",
        "decision_scope": "SCREENING_ONLY",
        "limitation_flags": ["Only one source report was delivered", "<b>escaped</b>"],
    }


def _figure() -> Json:
    return {
        "document_sha256": _DOCUMENT_SHA256,
        "page": 2,
        "matched_text": _RENDER_QUOTE,
    }


def _render_payloads() -> dict[str, dict[str, Json]]:
    no_narrative = _payload()
    del no_narrative["narrative"]
    return {
        "frozen_payload": _payload(),
        "cp_cf_projection": _artifact_payload({**_PROJECTIONS, "module_id": "CP-CF"}),
        "restricted_screening_only": _artifact_payload(_restricted_projections()),
        "markdown_handoff": _payload(_artifact(_MARKDOWN_HANDOFF)),
        "every_element": _payload(_artifact(_AUTHORED_SOURCE)),
        "inline_edge_cases": _payload(_artifact(_INLINE_EDGE_CASES)),
        "ordered_list_start": _payload(_artifact("7. First\n8. Second")),
        "prose_line_with_pipe": _payload(
            _artifact("Leverage | covenant headroom\n---")
        ),
        "html_escaped_text": _payload(
            _artifact("<script>alert(1)</script> & \"quotes\" 'apostrophes'")
        ),
        "narrative_spans": _payload(
            narrative=[
                [
                    {"text": "Leverage is "},
                    {"figure": _figure()},
                    {"text": " as shown."},
                ],
                [{"text": "Second paragraph."}],
            ]
        ),
        "narrative_empty_list": _payload(narrative=[]),
        "no_narrative": no_narrative,
        "two_artifacts": _payload(
            artifacts=[_artifact(_RENDER_MARKDOWN), _artifact(_MARKDOWN_HANDOFF)]
        ),
        "uncited_figure": _payload(_artifact(_RENDER_MARKDOWN, citations=[])),
        "no_artifacts": _payload(artifacts=[]),
        "artifacts_not_a_list": _payload(artifacts="not-a-list"),
        "artifact_not_a_mapping": _payload(artifacts=["not-a-mapping"]),
        "record_not_json": _payload(
            {**_artifact(_RENDER_MARKDOWN), "record": "not json"}
        ),
        "projections_not_a_mapping": _payload(
            _artifact(_RENDER_MARKDOWN, projections="not-a-mapping")
        ),
        "citations_not_a_list": _payload(
            _artifact(_RENDER_MARKDOWN, citations="not-a-list")
        ),
        "citation_not_a_mapping": _payload(
            _artifact(_RENDER_MARKDOWN, citations=["not-a-mapping"])
        ),
        "citation_without_page": _payload(
            _artifact(
                _RENDER_MARKDOWN,
                citations=[
                    {"document_sha256": _DOCUMENT_SHA256, "matched_text": _RENDER_QUOTE}
                ],
            )
        ),
        "case_title_empty": _payload(case_title=""),
        "narrative_not_text": _payload(narrative=123),
        "table_row_mismatch": _payload(_artifact("| a | b |\n| --- | --- |\n| 1 |\n")),
        "unclosed_fence": _payload(_artifact("```\nnever closed\n")),
        "unclosed_front_matter": _payload(_artifact("---\nmodule_id: CP-1\nno end")),
        "list_nested_too_deep": _payload(_artifact(_NESTED_LISTS)),
        "unclosed_comment": _payload(_artifact("<!-- open comment\nstill open")),
    }


def _artifact_payload(projections: Json) -> dict[str, Json]:
    return _payload(_artifact(_RENDER_MARKDOWN, projections=projections))


def _render_case(payload: Mapping[str, Json], target: Target) -> Json:
    render = target.module("deliverable.render")
    refused = _exception_type(render, "RenderRefused")
    try:
        page = call(render, "render", deepcopy(dict(payload)))
    except refused as exc:
        return {"refusal": str(attr(exc, "code"))}
    if not isinstance(page, bytes):
        message = "render did not return bytes"
        raise TypeError(message)
    return {
        "sha256": sha256_hex(page),
        "length": len(page),
        "html": page.decode("utf-8"),
    }


def _canonical_bound_case(target: Target) -> Json:
    render = target.module("deliverable.render")
    bound = _artifact(_RENDER_MARKDOWN)
    tampered = {**bound, "markdown": _RENDER_MARKDOWN + " "}
    return {
        "bound": jsonable(call(render, "canonical_bound", bound)),
        "tampered_markdown": jsonable(call(render, "canonical_bound", tampered)),
        "record_not_json": jsonable(
            call(render, "canonical_bound", {**bound, "record": "x"})
        ),
        "not_a_mapping": jsonable(call(render, "canonical_bound", "artifact")),
    }


def _render_cases() -> dict[str, CaseFn]:
    cases: dict[str, CaseFn] = {
        name: functools.partial(_render_case, payload)
        for name, payload in _render_payloads().items()
    }
    cases["canonical_bound"] = _canonical_bound_case
    return cases


# ---------------------------------------------------------------------------
# prompt: `methodology/invocation.py::build_handoff_prompt`, one assignment per
# adapter module the fixtures can build without a store. LITE earnings nodes
# come from `canonical_fixtures` (`identity`, `handoff_markdown`,
# `upstream_ref`), RELATIVE_VALUE nodes from `canonical_route_fixtures`
# (`route_identity`, `canonical_markdown`), the decision-ledger nodes from its
# `ledger_identity`/`ledger_markdown`; every other adapter module is built on
# the first `ADAPTER_ROUTES` pathway that runs it, with placeholder upstream
# handoffs (the prompt binds upstream by digest and never parses it). CP-CF is
# the one module not covered: its delivered authority includes
# `scripts/cash_flow.py`, whose bytes differ between the packages.
# ---------------------------------------------------------------------------

_DELIVERIES: tuple[tuple[int, str, int, str], ...] = (
    (1, "000001", 1, "Revenue rose 4% to 1,240."),
    (2, "000002", 3, "Net leverage was 4.2x."),
)
_LITE = ("LITE_CREDIT_22", "LITE_EARNINGS_UPDATE")
_RELATIVE_VALUE = ("FULL_CREDIT_32", "RELATIVE_VALUE")
_LEDGER = ("LITE_CREDIT_22", "LITE_DECISION_LEDGER")
_LITE_MODULES = ("CP-0", "CP-L10", "CP-5")
_RELATIVE_VALUE_MODULES = (
    "CP-0",
    "CP-1",
    "CP-4",
    "CP-1C",
    "CP-2A",
    "CP-3D",
    "CP-2",
    "CP-2G",
    "CP-3",
)
_MODEL_OWNERS = ("CP-1", "CP-2G", "CP-4")
_LEDGER_MODULES = ("CP-0", "CP-8")
_PLACEHOLDER_MODULES = (
    "CP-1A",
    "CP-1B",
    "CP-1D",
    "CP-2D",
    "CP-2E",
    "CP-2H",
    "CP-3C",
    "CP-4C",
    "CP-6",
    "CP-DR",
)
UNCOVERED_PROMPT_MODULES = ("CP-CF",)
_RESEARCH_MODULE = "CP-DR"


def _deliveries(target: Target) -> list[object]:
    executor = target.module("methodology.executor")
    boundary = attr(target.module("boundary_text"), "BoundaryText")
    return [
        call(executor, "Delivery", UUID(int=n), block, page, call(boundary, "of", text))
        for n, block, page, text in _DELIVERIES
    ]


def _source_set(target: Target) -> object:
    sets = target.module("store.source_sets")
    members = tuple(
        call(
            sets,
            "SourceSetMember",
            UUID(int=n),
            f"{n:x}" * 64,
            "issuer-report.pdf",
            "2026-09-15T00:00:00+00:00",
            '{"config":{},"name":"caos.test","version":"1"}',
            f"{n + 1:x}" * 64,
            f"{n + 2:x}" * 64,
        )
        for n, _block, _page, _text in _DELIVERIES
    )
    return call(sets, "SourceSet", UUID(int=9), 1, "b" * 64, members)


def _anchored(target: Target) -> tuple[object, ...]:
    citations = target.module("evidence.citations")
    rect = call(citations, "Rect", page=1, x0=1, y0=2, x1=3, y1=4)
    return (
        call(citations, "AnchoredCitation", "c" * 64, 1, "Recorded source p1", (rect,)),
    )


def _route_nodes(target: Target, route: object) -> list[tuple[str, str]]:
    """`(route_node_id, module_id)` in route order."""
    return [
        (_as_str(_as_dict(node)["route_node_id"]), _as_str(_as_dict(node)["module_id"]))
        for node in _as_list(jsonable(attr(route, "nodes")))
    ]


def _predecessors(target: Target, route: object, module: str) -> list[str]:
    found = jsonable(call(target.module("engine.route"), "predecessors", route, module))
    return [_as_str(item) for item in _as_list(found)]


def _build_prompt(
    target: Target,
    *,
    identity: object,
    route: object,
    upstream: tuple[tuple[object, bytes], ...],
) -> Json:
    """`tests/test_handoff_invocation.py::_prompt`, with fixed deliveries."""
    fixtures = target.fixture("canonical_fixtures")
    invocation = target.module("methodology.invocation")
    bundle = target.module("methodology.bundle")
    module_id = str(attr(identity, "module_id"))
    prompt = call(
        invocation,
        "build_handoff_prompt",
        attr(fixtures, "CONTRACT"),
        identity=identity,
        authority=call(
            bundle, "delivered_authority", attr(fixtures, "BUNDLE"), module_id
        ),
        catalog=attr(fixtures, "CATALOG"),
        delivered=_deliveries(target),
        upstream=upstream,
        upstream_citations={
            str(attr(ref, "route_node_id")): _anchored(target) for ref, _ in upstream
        },
        route=route,
        source_set=_source_set(target) if module_id == "CP-0" else None,
    )
    if not isinstance(prompt, str):
        message = "build_handoff_prompt did not return text"
        raise TypeError(message)
    return {
        "module_id": module_id,
        "route_node_id": str(attr(identity, "route_node_id")),
        "profile_id": str(attr(identity, "profile_id")),
        "selection_id": str(attr(identity, "selection_id")),
        "upstream": [str(attr(ref, "module_id")) for ref, _ in upstream],
        "sha256": sha256_hex(prompt.encode("utf-8")),
        "length": len(prompt),
        "text": prompt,
    }


@dataclasses.dataclass(frozen=True, slots=True)
class _Chain:
    """How one fixture family builds a node's identity and its accepted bytes."""

    identity: Callable[[str, tuple[object, ...]], object]
    markdown: Callable[[object], bytes]
    ref: Callable[[object, bytes], object]


def _upstream_ref(target: Target, identity: object, markdown: bytes) -> object:
    handoff = target.module("methodology.handoff")
    return call(
        handoff,
        "UpstreamRef",
        route_node_id=attr(identity, "route_node_id"),
        module_id=attr(identity, "module_id"),
        run_id=attr(identity, "run_id"),
        period=attr(identity, "reporting_period"),
        sha256=sha256_hex(markdown),
    )


def _bytes_of(value: object) -> bytes:
    if not isinstance(value, bytes):
        message = f"expected bytes, got {type(value).__name__}"
        raise TypeError(message)
    return value


def _lite_chain(target: Target) -> _Chain:
    fixtures = target.fixture("canonical_fixtures")
    return _Chain(
        identity=lambda module, refs: call(fixtures, "identity", module, refs),
        markdown=lambda identity: _bytes_of(
            call(fixtures, "handoff_markdown", identity)
        ),
        ref=lambda identity, markdown: call(
            fixtures, "upstream_ref", identity, markdown
        ),
    )


def _relative_value_chain(target: Target) -> _Chain:
    routes = target.fixture("canonical_route_fixtures")
    return _Chain(
        identity=lambda module, refs: call(routes, "route_identity", module, refs),
        markdown=lambda identity: _bytes_of(
            call(routes, "canonical_markdown", identity)
        ),
        ref=functools.partial(_upstream_ref, target),
    )


def _ledger_chain(target: Target) -> _Chain:
    routes = target.fixture("canonical_route_fixtures")
    return _Chain(
        identity=lambda module, refs: call(routes, "ledger_identity", module, refs),
        markdown=lambda identity: _bytes_of(call(routes, "ledger_markdown", identity)),
        ref=functools.partial(_upstream_ref, target),
    )


def _placeholder_handoff(module: str) -> bytes:
    return (
        f"---\nmodule_id: {module}\n---\n## Audit Summary\n\n"
        f"Accepted {module} handoff (parity placeholder).\n"
    ).encode()


def _chain_prompt(
    target: Target, chain: _Chain, selection: tuple[str, str], module: str
) -> Json:
    """The prompt for `module`, its upstream chain built node by node in route order."""
    route = _resolve(target, selection)
    refs: dict[str, object] = {}
    markdown: dict[str, bytes] = {}
    for _node_id, each in _route_nodes(target, route):
        preds = _predecessors(target, route, each)
        identity = chain.identity(each, tuple(refs[p] for p in preds))
        if each == module:
            return _build_prompt(
                target,
                identity=identity,
                route=route,
                upstream=tuple((refs[p], markdown[p]) for p in preds),
            )
        markdown[each] = chain.markdown(identity)
        refs[each] = chain.ref(identity, markdown[each])
    message = f"{module} is not on {selection}"
    raise ValueError(message)


def _model_owner_prompt(target: Target, module: str) -> Json:
    """An owner's prompt on the model-extended route: the plain identity, the
    extended route, and the forecast-extension section the extension adds."""
    chain = _relative_value_chain(target)
    plain = _resolve(target, _RELATIVE_VALUE)
    extended = _resolve(target, _RELATIVE_VALUE, model_extension=True)
    refs: dict[str, object] = {}
    markdown: dict[str, bytes] = {}
    for _node_id, each in _route_nodes(target, plain):
        preds = _predecessors(target, plain, each)
        identity = chain.identity(each, tuple(refs[p] for p in preds))
        if each == module:
            return _build_prompt(
                target,
                identity=identity,
                route=extended,
                upstream=tuple((refs[p], markdown[p]) for p in preds),
            )
        markdown[each] = chain.markdown(identity)
        refs[each] = chain.ref(identity, markdown[each])
    message = f"{module} is not a model owner on the RELATIVE_VALUE route"
    raise ValueError(message)


def _first_route_with(target: Target, module: str) -> tuple[tuple[str, str], object]:
    for selection in ADAPTER_ROUTES:
        route = _resolve(target, selection)
        if any(each == module for _node_id, each in _route_nodes(target, route)):
            return selection, route
    message = f"no adapter route runs {module}"
    raise ValueError(message)


def _module_name(target: Target, selection: tuple[str, str], node_id: str) -> str:
    profiles = _as_dict(_catalog(target.root)["profiles"])
    pathways = _as_dict(_as_dict(profiles[selection[0]])["pathways"])
    for node in _as_list(_as_dict(pathways[selection[1]])["nodes"]):
        fields = _as_dict(node)
        if fields["route_node_id"] == node_id:
            return _as_str(fields["module_name"])
    message = f"{node_id} is not on {selection}"
    raise ValueError(message)


def _research_brief(target: Target, refs: Sequence[object]) -> str:
    fixtures = target.fixture("canonical_fixtures")
    vendor = target.module("methodology.vendor")
    brief = _as_dict(jsonable(call(fixtures, "research_brief")))
    gate = [
        str(attr(ref, "sha256")) for ref in refs if attr(ref, "module_id") == "CP-0"
    ]
    brief["run_id"] = str(attr(fixtures, "RUN"))
    brief["cp0_sha256"] = gate[0] if gate else "0" * 64
    brief["authority_sha256"] = str(
        call(vendor, "authority_bundle_sha256", attr(fixtures, "BUNDLE"))
    )
    return canonical(brief)


def _placeholder_prompt(target: Target, module: str) -> Json:
    """`module` on the first adapter route that runs it, every upstream a
    digest-bound placeholder handoff; CP-DR carries a bound research brief."""
    selection, route = _first_route_with(target, module)
    fixtures = target.fixture("canonical_fixtures")
    handoff = target.module("methodology.handoff")
    vendor = target.module("methodology.vendor")
    nodes = {each: node_id for node_id, each in _route_nodes(target, route)}
    run = str(attr(fixtures, "RUN"))
    upstream: list[tuple[object, bytes]] = []
    for pred in _predecessors(target, route, module):
        data = _placeholder_handoff(pred)
        ref = call(
            handoff,
            "UpstreamRef",
            route_node_id=nodes[pred],
            module_id=pred,
            run_id=run,
            period="FY2025",
            sha256=sha256_hex(data),
        )
        upstream.append((ref, data))
    refs = tuple(ref for ref, _ in upstream)
    identity = call(
        handoff,
        "HostIdentity",
        run,
        *selection,
        nodes[module],
        module,
        _module_name(target, selection, nodes[module]),
        "ACME",
        "Acme Holdings plc",
        "FY2025",
        "2026-09-08",
        1,
        call(vendor, "authority_bundle_sha256", attr(fixtures, "BUNDLE")),
        refs,
        _research_brief(target, refs) if module == _RESEARCH_MODULE else None,
    )
    return _build_prompt(
        target, identity=identity, route=route, upstream=tuple(upstream)
    )


def _fixture_prompt(family: str, module: str, target: Target) -> Json:
    if family == "lite":
        return _chain_prompt(target, _lite_chain(target), _LITE, module)
    if family == "relative_value":
        return _chain_prompt(
            target, _relative_value_chain(target), _RELATIVE_VALUE, module
        )
    if family == "ledger":
        return _chain_prompt(target, _ledger_chain(target), _LEDGER, module)
    if family == "model_owner":
        return _model_owner_prompt(target, module)
    return _placeholder_prompt(target, module)


def _prompt_cases() -> dict[str, CaseFn]:
    cases: dict[str, CaseFn] = {}
    families = (
        ("lite", _LITE_MODULES),
        ("relative_value", _RELATIVE_VALUE_MODULES),
        ("model_owner", _MODEL_OWNERS),
        ("ledger", _LEDGER_MODULES),
        ("placeholder_upstream", _PLACEHOLDER_MODULES),
    )
    for family, modules in families:
        for module in modules:
            cases[f"{family}__{module}"] = functools.partial(
                _fixture_prompt, family, module
            )
    return cases


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

GROUPS: dict[str, dict[str, CaseFn]] = {
    "cash_flow": _cash_flow_cases(),
    "pricing": _pricing_cases(),
    "budget": _budget_cases(),
    "forecast": _forecast_cases(),
    "routes": _routes_cases(),
    "digest": _digest_cases(),
    "boundary_text": _boundary_cases(),
    "extraction": _extraction_cases(),
    "citations": _citations_cases(),
    "render": _render_cases(),
    "prompt": _prompt_cases(),
}
GROUP_NAMES: tuple[str, ...] = tuple(GROUPS)


def compute(target: Target, group: str, name: str) -> Json:
    """One case's JSON-ready output under `target`."""
    return GROUPS[group][name](target)
