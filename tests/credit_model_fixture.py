"""Example Gaming Co.: a CP-1 register set for the credit model's tests.

USD millions. Every figure is invented and reconciles: the quarters sum to the
fiscal years, FY2025 + H1 2026 - H1 2025 is the LTM, segment revenue sums to
revenue, EBIT less D&A is EBITDA, EBITDA + the add-backs is adjusted EBITDA, and
the cash flow statement moves cash from one period end to the next. The figures
are the worked example's (`model-layout-example.py` in the plan's folder), in
CP-1's sign convention: outflows negative (D&A included), so no row is
sign-normalised.

Data only. In each figure table a line is one key and a column one period; a
key is an account `metric_id`, or `bu:`, `addback:`, `kpi:` or `fac:` and the
register's id; `-` is no row. The half years and the LTM are CP-1's derived
periods (no source, status `CALCULATED`; the half years name their quarters
in `component_period_ids`), so the host has stated figures to compare. Debt and KPI rows
exist at quarter and fiscal-year ends only. Total debt excludes the finance
lease, as CP-1's `total_debt` does. The pro forma register is the Silverlake
Resort acquisition after the LTM: its EBITDA, the interest on the $600m of
add-on 7.000% notes that fund it, the cash it uses and the notes themselves.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

from caos.calculators.credit_model.frame import Case, SourceRef
from caos.calculators.credit_model.projection import RateDeck, RateDeckYear
from caos.methodology.model_inputs import (
    AccountRow,
    AddbackRow,
    Cp1Registers,
    DivisionGrowth,
    FacilityRow,
    KpiRow,
    PeriodRow,
    PfAdjustmentRow,
    SegmentRow,
    SlotAllocation,
)

_PERIODS = """
period_id   year q type    start      end        days components      source
FY2023      2023 - FY      2023-01-01 2023-12-31  365 -               S1
Q1_2024     2024 1 QUARTER 2024-01-01 2024-03-31   91 -               S4
Q2_2024     2024 2 QUARTER 2024-04-01 2024-06-30   91 -               S5
Q3_2024     2024 3 QUARTER 2024-07-01 2024-09-30   92 -               S6
Q4_2024     2024 4 QUARTER 2024-10-01 2024-12-31   92 -               S2
FY2024      2024 - FY      2024-01-01 2024-12-31  366 -               S2
Q1_2025     2025 1 QUARTER 2025-01-01 2025-03-31   90 -               S7
Q2_2025     2025 2 QUARTER 2025-04-01 2025-06-30   91 -               S8
H1_2025     2025 2 YTD     2025-01-01 2025-06-30  181 Q1_2025;Q2_2025 -
Q3_2025     2025 3 QUARTER 2025-07-01 2025-09-30   92 -               S9
Q4_2025     2025 4 QUARTER 2025-10-01 2025-12-31   92 -               S3
FY2025      2025 - FY      2025-01-01 2025-12-31  365 -               S3
Q1_2026     2026 1 QUARTER 2026-01-01 2026-03-31   90 -               S10
Q2_2026     2026 2 QUARTER 2026-04-01 2026-06-30   91 -               S11
H1_2026     2026 2 YTD     2026-01-01 2026-06-30  181 Q1_2026;Q2_2026 -
LTM_Q2_2026 2026 2 LTM     2025-07-01 2026-06-30  365 -               -
"""

_SOURCES = {
    "S1": "10-K FY2023, Item 8",
    "S2": "10-K FY2024, Item 8 and quarterly data",
    "S3": "10-K FY2025, Item 8 and quarterly data",
    "S4": "10-Q Q1 2024, Item 1",
    "S5": "10-Q Q2 2024, Item 1",
    "S6": "10-Q Q3 2024, Item 1",
    "S7": "10-Q Q1 2025, Item 1",
    "S8": "10-Q Q2 2025, Item 1",
    "S9": "10-Q Q3 2025, Item 1",
    "S10": "10-Q Q1 2026, Item 1",
    "S11": "10-Q Q2 2026, Item 1",
    "S12": "Lender presentation, Silverlake Resort acquisition, page 14",
}

_FIGURES_2023_2024 = """
key                               FY2023 Q1_2024 Q2_2024 Q3_2024 Q4_2024  FY2024
revenue                            10697    2725    2850    2807    2783   11165
cogs                               -4493   -1144   -1197   -1179   -1169   -4689
opex_including_da                  -3741    -958    -988    -978    -972   -3896
depreciation_amortization          -1120    -290    -290    -290    -290   -1160
ebit                                2463     623     665     650     642    2580
ebitda                              3583     913     955     940     932    3740
adjusted_ebitda                     3715     946     988     973     965    3872
operating_lease_cost                -112     -28     -28     -28     -28    -112
cash_interest_paid                  -939    -225    -224    -224    -221    -894
cash_taxes_paid                     -110     -30     -30     -30     -30    -120
working_capital_change                55     -19      15       8      40      44
cfo_ncfo                            2641     652     729     707     734    2822
lease_payments_in_financing          -16      -4      -4      -4      -4     -16
interest_paid_in_financing             0       0       0       0       0       0
capex_and_intangible_investment    -1250    -330    -330    -330    -330   -1320
acquisitions_disposals                 0       0       0       0       0       0
net_debt_issue_repay                -624      -6      -6      -6      -6     -24
net_equity_issue_repay              -719    -354    -331    -439    -326   -1450
dividends_paid                         0       0       0       0       0       0
other_investing_financing            -48     -12     -12     -12     -12     -48
net_cash_change                        0     -50      50     -80      60     -20
cash_and_equivalents                1000     950    1000     920     980     980
rcf_commitment                      2200    2200    2200    2200    2200    2200
rcf_drawn                              0       0       0       0       0       0
total_debt                         13906   13900   13894   13888   13882   13882
net_accounts_receivable              264     269     281     277     274     274
inventory                             43      44      46      45      45      45
accounts_payable                     394     401     420     413     410     410
bu:las_vegas                        3933    1010    1060    1000    1020    4090
bu:regional                         5549    1380    1440    1450    1390    5660
bu:digital                           950     270     280     290     300    1140
bu:managed_other                     325      80      85      82      88     335
bu:corporate_eliminations            -60     -15     -15     -15     -15     -60
addback:restructuring                 32       8       8       8       8      32
addback:stock_based_compensation      88      22      22      22      22      88
addback:transaction_costs             12       3       3       3       3      12
addback:run_rate_cost_savings          0       0       0       0       0       0
kpi:lv_room_nights                  9310    2374    2491    2350    2397    9612
kpi:lv_occupancy                    90.9    91.8    93.5    92.0    90.6    92.0
kpi:rewards_members                 62.0    62.5    63.0    63.4    64.0    64.0
fac:rcf                                0       0       0       0       0       0
fac:tlb                             2376    2370    2364    2358    2352    2352
fac:ssn29                           2000    2000    2000    2000    2000    2000
fac:ssn31                           1000    1000    1000    1000    1000    1000
fac:sun29                           3600    3600    3600    3600    3600    3600
fac:sun32                           3500    3500    3500    3500    3500    3500
fac:sub27                           1600    1600    1600    1600    1600    1600
fac:finl                             260     260     260     260     260     260
fac:disc                            -170    -170    -170    -170    -170    -170
"""

_FIGURES_2025 = """
key                              Q1_2025 Q2_2025 H1_2025 Q3_2025 Q4_2025  FY2025
revenue                             2810    2940    5750    2896    2873   11519
cogs                               -1180   -1235   -2415   -1216   -1207   -4838
opex_including_da                   -988   -1021   -2009   -1010   -1004   -4023
depreciation_amortization           -300    -300    -600    -300    -300   -1200
ebit                                 642     684    1326     670     662    2658
ebitda                               942     984    1926     970     962    3858
adjusted_ebitda                      975    1017    1992    1022    1005    4019
operating_lease_cost                 -28     -28     -56     -28     -28    -112
cash_interest_paid                  -218    -218    -436    -218    -216    -870
cash_taxes_paid                      -38     -38     -76     -38     -38    -152
working_capital_change               -19      14      -5       7      41      43
cfo_ncfo                             680     755    1435     753     772    2960
lease_payments_in_financing           -4      -4      -8      -4      -4     -16
interest_paid_in_financing             0       0       0       0       0       0
capex_and_intangible_investment     -360    -360    -720    -360    -360   -1440
acquisitions_disposals                 0       0       0       0       0       0
net_debt_issue_repay                  -6      -6     -12      -6      -6     -24
net_equity_issue_repay              -332    -327    -659    -455    -334   -1448
dividends_paid                         0       0       0       0       0       0
other_investing_financing            -12     -12     -24     -12     -12     -48
net_cash_change                      -30      50      20     -80      60       0
cash_and_equivalents                 950    1000    1000     920     980     980
rcf_commitment                      2200    2200    2200    2200    2200    2200
rcf_drawn                              0       0       0       0       0       0
total_debt                         13876   13870   13870   13864   13858   13858
net_accounts_receivable              277     290     290     286     283     283
inventory                             45      47      47      47      46      46
accounts_payable                     414     433     433     426     423     423
bu:las_vegas                        1040    1092    2132    1030    1051    4213
bu:regional                         1401    1462    2863    1472    1411    5746
bu:digital                           302     314     616     325     336    1277
bu:managed_other                      82      87     169      84      90     343
bu:corporate_eliminations            -15     -15     -30     -15     -15     -60
addback:restructuring                  8       8      16       8       8      32
addback:stock_based_compensation      22      22      44      22      22      88
addback:transaction_costs              3       3       6      12       3      21
addback:run_rate_cost_savings          0       0       0      10      10      20
kpi:lv_room_nights                  2444    2566       -    2420    2470    9900
kpi:lv_occupancy                    92.4    94.1       -    92.6    91.2    92.6
kpi:rewards_members                 64.6    65.1       -    65.6    66.2    66.2
fac:rcf                                0       0       -       0       0       0
fac:tlb                             2346    2340       -    2334    2328    2328
fac:ssn29                           2000    2000       -    2000    2000    2000
fac:ssn31                           1000    1000       -    1000    1000    1000
fac:sun29                           3600    3600       -    3600    3600    3600
fac:sun32                           3500    3500       -    3500    3500    3500
fac:sub27                           1600    1600       -    1600    1600    1600
fac:finl                             260     260       -     260     260     260
fac:disc                            -170    -170       -    -170    -170    -170
"""

_FIGURES_2026 = """
key                               Q1_2026  Q2_2026  H1_2026 LTM_Q2_2026
revenue                              2877     3008     5885       11654
cogs                                -1208    -1263    -2471       -4894
opex_including_da                   -1015    -1047    -2062       -4076
depreciation_amortization            -310     -310     -620       -1220
ebit                                  654      698     1352        2684
ebitda                                964     1008     1972        3904
adjusted_ebitda                      1009     1053     2062        4089
operating_lease_cost                  -28      -28      -56        -112
cash_interest_paid                   -214     -214     -428        -862
cash_taxes_paid                       -42      -42      -84        -160
working_capital_change                -20       14       -6          42
cfo_ncfo                              713      791     1504        3029
lease_payments_in_financing            -4       -4       -8         -16
interest_paid_in_financing              0        0        0           0
capex_and_intangible_investment      -380     -380     -760       -1480
acquisitions_disposals                  0        0        0           0
net_debt_issue_repay                   -6       -6      -12         -24
net_equity_issue_repay               -345     -343     -688       -1477
dividends_paid                          0        0        0           0
other_investing_financing             -12      -12      -24         -48
net_cash_change                       -30       50       20           0
cash_and_equivalents                  950     1000     1000        1000
rcf_commitment                       2200     2200     2200        2200
rcf_drawn                               0        0        0           0
total_debt                          13852    13846    13846       13846
net_accounts_receivable               284      297      297         297
inventory                              46       48       48          48
accounts_payable                      424      443      443         443
bu:las_vegas                         1061     1114     2175        4256
bu:regional                          1415     1476     2891        5774
bu:digital                            333      345      678        1339
bu:managed_other                       83       88      171         345
bu:corporate_eliminations             -15      -15      -30         -60
addback:restructuring                   8        8       16          32
addback:stock_based_compensation       24       24       48          92
addback:transaction_costs               3        3        6          21
addback:run_rate_cost_savings          10       10       20          40
kpi:lv_room_nights                   2493     2618        -           -
kpi:lv_occupancy                     92.9     94.3        -           -
kpi:rewards_members                  66.8     67.3        -           -
fac:rcf                                 0        0        -           -
fac:tlb                              2322     2316        -           -
fac:ssn29                            2000     2000        -           -
fac:ssn31                            1000     1000        -           -
fac:sun29                            3600     3600        -           -
fac:sun32                            3500     3500        -           -
fac:sub27                            1600     1600        -           -
fac:finl                              260      260        -           -
fac:disc                             -170     -170        -           -
"""

_SEGMENTS = {  # segment_id: name, type, display_priority
    "las_vegas": ("Las Vegas", "OPERATING_SEGMENT", 1),
    "regional": ("Regional", "OPERATING_SEGMENT", 2),
    "digital": ("Digital", "OPERATING_SEGMENT", 3),
    "managed_other": ("Managed and other", "OPERATING_SEGMENT", 4),
    "corporate_eliminations": (
        "Corporate and eliminations",
        "CORPORATE_ELIMINATION",
        5,
    ),
}

_ADDBACKS = {  # addback_id: label, classification, realization, priority
    "restructuring": ("Restructuring", "RESTRUCTURING", "REALIZED", 1),
    "stock_based_compensation": ("Stock-based compensation", "SBC", "REALIZED", 2),
    "transaction_costs": ("Transaction costs", "TRANSACTION_COSTS", "REALIZED", 3),
    "run_rate_cost_savings": ("Run-rate cost savings", "RUN_RATE", "UNREALIZED", 4),
}

_KPIS = {  # kpi_id: label, unit, value_type, display_priority
    "lv_room_nights": (
        "Las Vegas room nights (thousands)",
        "THOUSANDS",
        "PERIOD_FLOW",
        1,
    ),
    "lv_occupancy": ("Las Vegas hotel occupancy", "PERCENT", "RATE", 2),
    "rewards_members": ("Rewards members, period end", "MILLIONS", "PERIOD_END", 3),
}

# The terms each facility's rows carry; `period_id` and the carrying value are
# set per row. Only the term loan amortises: 1.0% a year of $2,400m.
_FLOATING = FacilityRow(
    facility_id="rcf",
    facility_name="Revolving credit facility ($2,200m commitment)",
    period_id="",
    facility_type="REVOLVING_CREDIT_FACILITY",
    currency="USD",
    carrying_value=None,
    commitment=Decimal(2200),
    drawn_amount=None,
    secured_status="SECURED",
    seniority="SUPER_SENIOR",
    lease_classification="NOT_LEASE",
    maturity_date="2030-01-31",
    margin_or_coupon="SOFR + 225 bp",
    rate_type="FLOATING",
    reference_rate="SOFR",
    spread_bps=Decimal(225),
    floor_bps=None,
    fixed_rate=None,
    annual_amortisation=Decimal(0),
    source=None,
)
_TERM_LOAN = replace(
    _FLOATING,
    facility_id="tlb",
    facility_name="Term loan B",
    facility_type="TERM_LOAN",
    commitment=None,
    seniority="SENIOR",
    maturity_date="2030-02-28",
    margin_or_coupon="SOFR + 275 bp, 0.50% floor",
    spread_bps=Decimal(275),
    floor_bps=Decimal(50),
    annual_amortisation=Decimal(24),
)
_NOTES = replace(
    _FLOATING,
    facility_type="NOTES",
    commitment=None,
    seniority="SENIOR",
    rate_type="FIXED",
    reference_rate="NONE",
    spread_bps=None,
)
_NOT_STATED = replace(
    _NOTES,
    secured_status="NOT_STATED",
    seniority="NOT_STATED",
    maturity_date=None,
    margin_or_coupon="Not applicable",
    rate_type="NOT_STATED",
    reference_rate="NOT_STATED",
    annual_amortisation=None,
)


def _note(facility_id: str, name: str, maturity: str, coupon: str) -> FacilityRow:
    return replace(
        _NOTES,
        facility_id=facility_id,
        facility_name=name,
        maturity_date=maturity,
        margin_or_coupon=f"{coupon}%",
        fixed_rate=Decimal(coupon),
    )


_FACILITIES = {
    terms.facility_id: terms
    for terms in (
        _FLOATING,
        _TERM_LOAN,
        _note("ssn29", "6.500% senior secured notes", "2029-02-15", "6.500"),
        _note("ssn31", "7.000% senior secured notes", "2031-02-15", "7.000"),
        replace(
            _note("sun29", "4.625% senior notes", "2029-10-15", "4.625"),
            secured_status="UNSECURED",
        ),
        replace(
            _note("sun32", "6.000% senior notes", "2032-10-15", "6.000"),
            secured_status="UNSECURED",
        ),
        replace(
            _note("sub27", "8.125% senior subordinated notes", "2027-07-01", "8.125"),
            secured_status="UNSECURED",
            seniority="SENIOR_SUBORDINATED",
        ),
        replace(
            _NOT_STATED,
            facility_id="finl",
            facility_name="Finance lease liabilities",
            facility_type="FINANCE_LEASE",
            lease_classification="FINANCE_LEASE",
            margin_or_coupon="Not stated",
        ),
        replace(
            _NOT_STATED,
            facility_id="disc",
            facility_name="Unamortised discount and issuance costs",
            facility_type="DEBT ADJUSTMENT",
        ),
    )
}


# The LTM's pro forma register (S12), in CP-1's sign convention.
_PRO_FORMA = """
adjustment_id        metric_id            value label
silverlake_ebitda    adjusted_ebitda         45 Silverlake Resort LTM adjusted EBITDA
silverlake_interest  cash_interest_paid     -42 Interest on the add-on 7.000% notes
silverlake_cash      cash_and_equivalents   -50 Cash used in the acquisition
silverlake_notes     facility:ssn31         600 Add-on 7.000% senior secured notes
"""


def _table(text: str) -> list[list[str]]:
    return [line.split() for line in text.strip().splitlines()[1:]]


def _figures() -> list[tuple[str, str, str]]:
    """(key, period_id, cell text) for every figure the tables state."""
    figures: list[tuple[str, str, str]] = []
    for text in (_FIGURES_2023_2024, _FIGURES_2025, _FIGURES_2026):
        header = text.strip().splitlines()[0].split()[1:]
        for key, *cells in _table(text):
            figures.extend(
                (key, period_id, cell)
                for period_id, cell in zip(header, cells, strict=True)
                if cell != "-"
            )
    return figures


def _source(
    period_source: dict[str, str], period_id: str, cell: str
) -> SourceRef | None:
    source_id = period_source[period_id]
    if source_id == "-":
        return None
    return SourceRef(source_id, _SOURCES[source_id], cell)


def _period(fields: list[str]) -> PeriodRow:
    period_id, year, quarter, kind, start, end, days, components, _ = fields
    return PeriodRow(
        period_id=period_id,
        fiscal_year=year,
        fiscal_quarter=None if quarter == "-" else quarter,
        period_type=kind,
        start_date=start,
        end_date=end,
        day_count=int(days),
        currency="USD",
        unit="MILLIONS",
        component_period_ids=() if components == "-" else tuple(components.split(";")),
    )


def _pro_forma() -> tuple[PfAdjustmentRow, ...]:
    return tuple(
        PfAdjustmentRow(
            adjustment_id=adjustment_id,
            label=" ".join(label),
            period_id="LTM_Q2_2026",
            classification="ACQUISITION",
            metric_id=metric_id,
            value=Decimal(value),
            source=SourceRef("S12", _SOURCES["S12"], value),
        )
        for adjustment_id, metric_id, value, *label in _table(_PRO_FORMA)
    )


def with_figures(
    regs: Cp1Registers, period_id: str, figures: dict[str, Decimal]
) -> Cp1Registers:
    """`regs` with the period's account figures in `figures` replaced."""
    return replace(
        regs,
        accounts=tuple(
            replace(a, value=figures[a.metric_id])
            if a.period_id == period_id and a.metric_id in figures
            else a
            for a in regs.accounts
        ),
    )


def example_registers() -> Cp1Registers:
    """Example Gaming Co.'s CP-1 registers: FY2023-FY2025, the quarters from
    Q1 2024 to Q2 2026, H1 2025 and H1 2026, CP-1's LTM to Q2 2026 and its
    pro forma register."""
    period_fields = _table(_PERIODS)
    period_source = {fields[0]: fields[-1] for fields in period_fields}
    accounts: list[AccountRow] = []
    segments: list[SegmentRow] = []
    addbacks: list[AddbackRow] = []
    kpis: list[KpiRow] = []
    facilities: list[FacilityRow] = []
    for key, period_id, cell in _figures():
        value = Decimal(cell)
        source = _source(period_source, period_id, cell)
        prefix, _, register_id = key.rpartition(":")
        if prefix == "bu":
            name, kind, priority = _SEGMENTS[register_id]
            segments.append(
                SegmentRow(register_id, name, kind, priority, period_id, value, source)
            )
        elif prefix == "addback":
            label, classification, realization, priority = _ADDBACKS[register_id]
            addbacks.append(
                AddbackRow(
                    register_id,
                    label,
                    classification,
                    realization,
                    priority,
                    period_id,
                    value,
                    source,
                )
            )
        elif prefix == "kpi":
            label, unit, value_type, priority = _KPIS[register_id]
            kpis.append(
                KpiRow(
                    register_id,
                    label,
                    priority,
                    period_id,
                    value,
                    unit,
                    value_type,
                    source,
                )
            )
        elif prefix == "fac":
            facilities.append(
                replace(
                    _FACILITIES[register_id],
                    period_id=period_id,
                    carrying_value=value,
                    drawn_amount=value if register_id == "rcf" else None,
                    source=source,
                )
            )
        else:
            status = "VERIFIED" if source is not None else "CALCULATED"
            accounts.append(AccountRow(register_id, period_id, value, status, source))
    return Cp1Registers(
        periods=tuple(_period(fields) for fields in period_fields),
        accounts=tuple(accounts),
        addbacks=tuple(addbacks),
        segments=tuple(segments),
        kpis=tuple(kpis),
        facilities=tuple(facilities),
        pro_forma=_pro_forma(),
        currency="USD",
        unit="MILLIONS",
    )


# The projections (CP-2G and CP-CF), the worked example's Base and Downside
# cases. CP-2G binds three division slots; managed and other is in none, so
# the host holds it flat. Each year's growth by slot:
_GROWTH = """
case     year DIVISION_1 DIVISION_2 DIVISION_3
BASE     2026      0.025      0.010       0.10
BASE     2027      0.030      0.015       0.08
BASE     2028      0.030      0.015       0.06
DOWNSIDE 2026      -0.06      -0.04       0.02
DOWNSIDE 2027      -0.03      -0.02       0.03
DOWNSIDE 2028       0.01       0.01       0.04
"""
_CASES: dict[str, Case] = {"BASE": "BASE", "DOWNSIDE": "DOWNSIDE"}
_SLOTS = {"DIVISION_1": "las_vegas", "DIVISION_2": "regional", "DIVISION_3": "digital"}

# CP-CF's drivers, unsigned: revenue is the slot growth on FY2025's business
# units (rounded), EBITDA the example's margin on its revenue, `cfo` before
# interest and taxes (EBITDA less lease cash 16, other 80 and the working
# capital outflow), distributions the buybacks. Base sweeps cash to the term
# loan. The stated closings follow CP-CF's own roll-forward from FY2025.
_DRIVERS = """
case     year revenue ebitda  cfo interest taxes capex distrib repaid  debt cash
BASE     2026   11809   4136 4025      859   170  1700     400    822 13012 1030
BASE     2027   12138   4290 4179      798   180  1650     400   1097 11891 1060
BASE     2028   12451   4427 4316      728   190  1600     400    337 11530 2097
DOWNSIDE 2026   11062   3319 3183      882   120  1500       0      0 13834 1637
DOWNSIDE 2027   10872   3099 2983      894   100  1300       0      0 13810 2302
DOWNSIDE 2028   11018   3196 3090      889   110  1200       0      0 13786 3169
"""
_FY2025_DEBT = {  # CP-CF's opening: CP-1's total debt, finance lease excluded
    "rcf": "0",
    "tlb": "2328",
    "ssn29": "2000",
    "ssn31": "1000",
    "sun29": "3600",
    "sun32": "3500",
    "sub27": "1600",
    "disc": "-170",
}
# The SOFR deck, as decimals: FY+1 is FY2026.
_DECK = (
    ("1", "0.0380", "0.0480"),
    ("2", "0.0340", "0.0540"),
    ("3", "0.0325", "0.0525"),
)


def example_growth() -> tuple[DivisionGrowth, ...]:
    """CP-2G's division growth, a decimal fraction per case, year and slot."""
    lines = _GROWTH.strip().splitlines()
    slots = lines[0].split()[2:]
    return tuple(
        DivisionGrowth(_CASES[case], year, slot, Decimal(value))
        for case, year, *values in (line.split() for line in lines[1:])
        for slot, value in zip(slots, values, strict=True)
    )


def example_slots() -> tuple[SlotAllocation, ...]:
    """CP-1's slot allocation: one segment per division slot."""
    return tuple(SlotAllocation(slot, (segment,)) for slot, segment in _SLOTS.items())


def example_deck() -> RateDeck:
    """The pinned rate deck: SOFR for FY+1 to FY+3, Base and Downside."""
    return RateDeck(
        deck_id="deck-1",
        as_of="2026-10-01",
        years=tuple(
            RateDeckYear("SOFR", int(offset), Decimal(base), Decimal(downside))
            for offset, base, downside in _DECK
        ),
    )


def example_request() -> dict[str, Any]:
    """CP-CF's accepted request: FY2026-FY2028 for Base and Downside, from
    FY2025's closing debt and cash, the term loan amortising 24 a year."""
    rows = [line.split() for line in _DRIVERS.strip().splitlines()[1:]]
    drivers = []
    for case, year, revenue, ebitda, cfo, interest, taxes, capex, *rest in rows:
        distributions, optional, debt, cash = rest
        drivers.append(
            {
                "case": case,
                "period_id": f"FY{year}",
                "status": "READY",
                "stated_closing_debt": debt,
                "stated_closing_cash": cash,
                "revenue": revenue,
                "ebitda": ebitda,
                "cfo": cfo,
                "capex": capex,
                "acquisitions_disposals": "0",
                "cash_interest": interest,
                "cash_taxes": taxes,
                "distributions": distributions,
                "issuance": "0",
                "optional_repayment": optional,
                "pik": "0",
                "capitalised_interest": "0",
                "fx_perimeter": "0",
            }
        )
    return {
        "opening": {
            "cash": "980",
            "as_of_period_id": "FY2025",
            "debt_by_facility": [
                {"facility_id": facility_id, "amount": amount}
                for facility_id, amount in _FY2025_DEBT.items()
            ],
        },
        "periods": [
            {
                "case": row[0],
                "period_id": f"FY{row[1]}",
                "fiscal_year": row[1],
                "days": "365",
            }
            for row in rows
        ],
        "drivers": drivers,
        "contractual": {
            "amortisation": [
                {
                    "case": row[0],
                    "period_id": f"FY{row[1]}",
                    "facility_id": "tlb",
                    "amount": "24",
                }
                for row in rows
            ]
        },
        "units": {"currency": "USD", "scale": "millions"},
        "perimeter": "Example Gaming Co. consolidated",
    }
