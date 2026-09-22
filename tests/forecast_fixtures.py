"""Independent forecast inputs; expected values live in the tests' hand tables."""

from __future__ import annotations

from typing import Any


def forecast_request(*, quarterly: bool = False) -> dict[str, Any]:
    """Two chained periods in each annual case, or two base quarters."""
    periods = []
    drivers = []
    amortisation = []
    for case in ["BASE"] if quarterly else ["BASE", "DOWNSIDE"]:
        for index in range(2):
            period = f"Q{index + 1}" if quarterly else f"FY{26 + index}"
            downside = case == "DOWNSIDE"
            periods.append(
                {
                    "period_id": period,
                    "fiscal_year": "2026" if quarterly else str(2026 + index),
                    "case": case,
                    "days": "90" if quarterly else "365",
                }
            )
            drivers.append(
                {
                    "case": case,
                    "period_id": period,
                    "status": "READY",
                    "revenue": "100" if quarterly else "500",
                    "ebitda": "25" if quarterly else ("50" if downside else "100"),
                    "cfo": "20" if quarterly else ("40" if downside else "80"),
                    "capex": "5" if quarterly else "20",
                    "cash_interest": "2" if quarterly else "10",
                    "cash_taxes": "1" if quarterly else "5",
                    "distributions": "0" if quarterly else "4",
                    "issuance": "5" if quarterly else "30",
                    "optional_repayment": "1" if quarterly else "10",
                    "pik": "1" if quarterly else "2",
                    "capitalised_interest": "0" if quarterly else "3",
                    "fx_perimeter": "0" if quarterly else "-5",
                    "acquisitions_disposals": "-2" if quarterly else "15",
                    "stated_closing_debt": ["1003", "1006"][index]
                    if quarterly
                    else "1000",
                    "stated_closing_cash": ["116", "132"][index]
                    if quarterly
                    else (["86", "72"][index] if downside else ["126", "152"][index]),
                }
            )
            amortisation.append(
                {
                    "case": case,
                    "period_id": period,
                    "facility_id": "TERM",
                    "amount": "2" if quarterly else "20",
                }
            )
    return {
        "opening": {
            "cash": "100",
            "as_of_period_id": "FY25",
            "debt_by_facility": [
                {"facility_id": "TERM", "amount": "700"},
                {"facility_id": "BOND", "amount": "300"},
            ],
        },
        "periods": periods,
        "drivers": drivers,
        "contractual": {"amortisation": amortisation},
        "units": {"currency": "USD", "scale": "millions"},
        "perimeter": "Consolidated",
    }
