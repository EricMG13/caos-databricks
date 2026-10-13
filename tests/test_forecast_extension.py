"""CP-CF is host-owned, pinned and never an arbitrary code selector."""

from __future__ import annotations

from pathlib import Path

import pytest
from canonical_fixtures import BUNDLE, CATALOG

from caos.graph.route import RouteExtensions, resolve_route
from caos.methodology.bundle import assemble_authority, delivered_authority
from caos.refusals import Refusal, RefusalCode


def test_forecast_extension_has_complete_verified_host_authority() -> None:
    from host_manifest import generate_host_manifest

    from caos.methodology.host import HOST_ROOT, host_skill

    assert (
        generate_host_manifest() == (HOST_ROOT / "HOST_INTEGRITY_v1.json").read_bytes()
    )
    assert host_skill()["module_id"] == "CP-CF"
    authority = assemble_authority(BUNDLE, "CP-CF")
    assert "SKILL.md" in authority.files
    assert b"cash_flow_forecast" in authority.files["SKILL.md"]
    assert delivered_authority(BUNDLE, "CP-CF").files[0][0] == "SKILL.md"


def test_forecast_extension_pin_binds_the_host_manifest() -> None:
    from caos.methodology.host import verify_extension
    from caos.methodology.host_pin import HOST_MANIFEST_SHA256

    route = resolve_route(
        CATALOG,
        "FULL_CREDIT_32",
        "RELATIVE_VALUE",
        extensions=RouteExtensions(model_extension=True),
    )
    assert dict(route.predicates)["host_manifest_sha256"] == HOST_MANIFEST_SHA256
    verify_extension(route)


def test_forecast_extension_refuses_changed_host_bytes(tmp_path: Path) -> None:
    import shutil

    from caos.methodology.host import HOST_ROOT, verified_host_bytes

    root = tmp_path / "host"
    shutil.copytree(HOST_ROOT, root)
    (root / "stages/cp-cf/references/SKILL.md").write_text("altered")
    with pytest.raises(Refusal) as caught:
        verified_host_bytes("SKILL.md", root=root)
    assert caught.value.code is RefusalCode.AUTHORITY_BYTES_MISMATCH


def test_forecast_extension_refuses_stale_or_absent_pin() -> None:
    from dataclasses import replace

    from caos.methodology.host import verify_extension

    route = resolve_route(
        CATALOG,
        "FULL_CREDIT_32",
        "RELATIVE_VALUE",
        extensions=RouteExtensions(model_extension=True),
    )
    for predicates in ((), (("host_manifest_sha256", "0" * 64),)):
        with pytest.raises(Refusal) as caught:
            verify_extension(replace(route, predicates=predicates))
        assert caught.value.code is RefusalCode.AUTHORITY_BYTES_MISMATCH


def test_the_bundle_pin_is_the_vendored_manifest_s_digest() -> None:
    """F66: `scripts/host_manifest.py` compiles the pin the runtime checks."""
    from host_manifest import bundle_manifest_sha256

    from caos.methodology.bundle_pin import BUNDLE_MANIFEST_SHA256

    assert bundle_manifest_sha256() == BUNDLE_MANIFEST_SHA256
    assert BUNDLE.manifest_sha256 == BUNDLE_MANIFEST_SHA256


@pytest.mark.parametrize("module", ["CP-1", "CP-2G", "CP-4", "CP-CF"])
def test_forecast_extension_delivers_the_current_owned_contract(module: str) -> None:
    """Exercise rendered owner prompts and verified CP-CF authority, not copies."""
    from parity.cases import compute
    from parity.goldens import caos_target

    if module == "CP-CF":
        text = dict(delivered_authority(BUNDLE, module).files)["SKILL.md"].decode()
    else:
        result = compute(caos_target(), "prompt", f"model_owner__{module}")
        assert isinstance(result, dict)
        text = str(result["text"])
    delivered = " ".join(text.split())
    for clause in (
        "all 42 CP-2G financial/growth rows",
        "Required legacy movements remain required",
        "Every scalar leaf and empty array",
        "CP-1 owns opening/periods/units/perimeter/actuals",
        "CP-2G owns drivers/tolerance/projection_basis",
        "CP-4 owns contractual",
        "Missing, null and NOT_APPLICABLE never become zero",
        "net_equity_issue_repay (cash + E)",
        "other_investing_financing (cash + O)",
        "restricted_cash_change (accessible cash - R)",
        "carrying_value_change (debt + C, no cash)",
        "Explicit zero remains present in input and output",
        "absent optional fields preserve legacy result shape and arithmetic",
        "Present equity and otherFI fields equal their matching financial rows "
        "directly",
        "only absent corresponding fields require READY zero rows",
        "Acquisitions/disposals and dividends retain reversed signs",
        "Optional driver.segment_revenue is a complete exact known CP-1 segment-ID",
        "1-40 safe IDs",
        "Its sum equals consolidated driver revenue exactly",
        "corporate/elimination values stay equal to that base",
        "Every map leaf is CP-2G-owned",
        "replacing slot growth only for that driver",
        "must not be applied twice",
        'Optional projection_basis is exactly "OWNED_CASH_DEBT_SERVICE", CP-2G-owned',
        "zero or one shared bridge, explicitly [] for a wholly future forecast",
        "amount (exact signed CP-1 net_debt_issue_repay)",
        "once per scenario's first year, never later",
        "CP-1-owned start_date/end_date",
        "exact days 365/366",
        "PE cannot replace the FY column",
        "supplemental owner statements, not future historical actual columns",
        "contractual.amortisation remains required and exactly []",
        "exactly case, period_id, start_date, end_date, amount",
        "first future span starts the day after actual YTD ends",
        "issuance and optional_repayment cover this future span only",
        "cfo and cash_interest cover the full annual period",
        "H is never interest",
        "net debt cash = H + issuance - optional_repayment - P",
        "absolute 1000, relative 0.001, exact at zero opening",
        "Cash debt-service basis: accepted CP-CF aggregate forecast",
        "NOT_PROJECTED; total debt is explicitly unallocated",
        "Negative cash is unmet funding",
        "Citations verify source location, not economic or legal approval",
    ):
        assert clause in delivered, (module, clause)
    assert "this contract has no corresponding movement" not in delivered


@pytest.mark.parametrize(
    ("owner", "assignment"),
    [
        ("CP-2G", '/drivers/0/net_equity_issue_repay = "0"'),
        ("CP-2G", '/drivers/0/other_investing_financing = "-24"'),
        ("CP-2G", '/drivers/0/restricted_cash_change = "15"'),
        ("CP-2G", '/drivers/0/carrying_value_change = "26"'),
        ("CP-2G", '/drivers/0/segment_revenue/SEG-A = "100"'),
        ("CP-2G", '/projection_basis = "OWNED_CASH_DEBT_SERVICE"'),
        ("CP-1", "/actuals/debt_cash_movements = []"),
        ("CP-1", '/actuals/debt_cash_movements/0/amount = "-98"'),
        ("CP-1", '/periods/0/start_date = "2026-01-01"'),
        ("CP-4", "/contractual/amortisation = []"),
        ("CP-4", '/contractual/aggregate_amortisation/0/amount = "55"'),
    ],
)
def test_forecast_extension_declared_owner_matches_binding_api(
    owner: str, assignment: str
) -> None:
    from caos.methodology.forecast import binds_input

    for module in ("CP-1", "CP-2G", "CP-4"):
        assert binds_input(module, assignment) is (module == owner)


def test_forecast_extension_refuses_altered_owner_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from caos import icm

    verified = icm.prompt_block("forecast_extension")
    (tmp_path / "forecast_extension.md").write_text(
        verified.replace("cash + E", "cash - E")
    )
    monkeypatch.setattr(icm, "PROMPTS", tmp_path)
    icm.prompt_block.cache_clear()
    try:
        with pytest.raises(Refusal) as caught:
            icm.prompt_block("forecast_extension")
        assert caught.value.code is RefusalCode.AUTHORITY_BYTES_MISMATCH
    finally:
        icm.prompt_block.cache_clear()


@pytest.mark.parametrize("module", ["CP-1", "CP-2G", "CP-4"])
def test_forecast_extension_instruction_bytes_are_in_request_budget(
    module: str,
) -> None:
    import re
    from dataclasses import replace
    from decimal import Decimal
    from uuid import UUID

    from canonical_fixtures import RUN_PRICE
    from canonical_route_fixtures import RouteCompletions
    from parity.cases import compute
    from parity.goldens import caos_target

    from caos.methodology.invocation import request_size
    from caos.pricing import priced_request

    result = compute(caos_target(), "prompt", f"model_owner__{module}")
    assert isinstance(result, dict)
    prompt = str(result["text"])
    reduced, count = re.subn(
        r"--- HOST FORECAST EXTENSION [0-9a-f]+ ---.*?"
        r"--- END HOST FORECAST EXTENSION [0-9a-f]+ ---\n",
        "",
        prompt,
        flags=re.DOTALL,
    )
    assert count == 1
    price = replace(RUN_PRICE, input_per_token=Decimal("0.000001"))
    provider = RouteCompletions(UUID(int=1), price=price)
    measured = request_size(provider, prompt)
    assert measured == len(provider.request_bytes(prompt, json_object=True))
    assert measured > request_size(provider, reduced)
    assert priced_request(price, measured) > priced_request(
        price, request_size(provider, reduced)
    )
    assert provider.prompts == []
