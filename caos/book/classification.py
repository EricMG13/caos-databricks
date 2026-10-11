"""Classification vocabularies and the composite rating: pure, no I/O.

A rating is an ordinal notch, 1 (AAA / Aaa) to 22 (D); a higher number is a
worse rating. Moody's has no D, so its scale stops at C = 21.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Literal

type Bucket = Literal["IG", "BB", "B", "CCC_AND_BELOW", "NR"]

# GICS structure in force since March 2023: 11 sectors, 25 industry groups.
GICS_SECTORS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "Energy": ("Energy",),
        "Materials": ("Materials",),
        "Industrials": (
            "Capital Goods",
            "Commercial & Professional Services",
            "Transportation",
        ),
        "Consumer Discretionary": (
            "Automobiles & Components",
            "Consumer Durables & Apparel",
            "Consumer Services",
            "Consumer Discretionary Distribution & Retail",
        ),
        "Consumer Staples": (
            "Consumer Staples Distribution & Retail",
            "Food, Beverage & Tobacco",
            "Household & Personal Products",
        ),
        "Health Care": (
            "Health Care Equipment & Services",
            "Pharmaceuticals, Biotechnology & Life Sciences",
        ),
        "Financials": ("Banks", "Financial Services", "Insurance"),
        "Information Technology": (
            "Software & Services",
            "Technology Hardware & Equipment",
            "Semiconductors & Semiconductor Equipment",
        ),
        "Communication Services": (
            "Telecommunication Services",
            "Media & Entertainment",
        ),
        "Utilities": ("Utilities",),
        "Real Estate": (
            "Equity Real Estate Investment Trusts (REITs)",
            "Real Estate Management & Development",
        ),
    }
)

AGENCIES = ("MOODYS", "SP", "FITCH")
OUTLOOKS = (
    "STABLE",
    "POSITIVE",
    "NEGATIVE",
    "DEVELOPING",
    "WATCH_POS",
    "WATCH_NEG",
    "WATCH_DEV",
)

MOODYS_SCALE: tuple[str, ...] = (
    "Aaa",
    "Aa1",
    "Aa2",
    "Aa3",
    "A1",
    "A2",
    "A3",
    "Baa1",
    "Baa2",
    "Baa3",
    "Ba1",
    "Ba2",
    "Ba3",
    "B1",
    "B2",
    "B3",
    "Caa1",
    "Caa2",
    "Caa3",
    "Ca",
    "C",
)
SP_FITCH_SCALE: tuple[str, ...] = (
    "AAA",
    "AA+",
    "AA",
    "AA-",
    "A+",
    "A",
    "A-",
    "BBB+",
    "BBB",
    "BBB-",
    "BB+",
    "BB",
    "BB-",
    "B+",
    "B",
    "B-",
    "CCC+",
    "CCC",
    "CCC-",
    "CC",
    "C",
    "D",
)

_SCALES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {"MOODYS": MOODYS_SCALE, "SP": SP_FITCH_SCALE, "FITCH": SP_FITCH_SCALE}
)
_IG_FLOOR = 10  # BBB- / Baa3
_BB_FLOOR = 13  # BB- / Ba3
_B_FLOOR = 16  # B- / B3
_DOMICILE = re.compile(r"[A-Z]{2}")


class ClassificationRefused(ValueError):
    """A typed refusal: the code names the fault, and no input is echoed."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def notch(agency: str, rating: str) -> int:
    """The 1-based notch of `rating` on `agency`'s scale; refused if unknown."""
    scale = _SCALES.get(agency)
    if scale is None:
        raise ClassificationRefused("UNKNOWN_AGENCY")
    if rating not in scale:
        raise ClassificationRefused("UNKNOWN_RATING")
    return scale.index(rating) + 1


def composite_notch(notches: Sequence[int]) -> int | None:
    """Middle of three, the worse (higher) of two, the single one, None for none."""
    if len(notches) > len(AGENCIES):
        raise ClassificationRefused("MORE_RATINGS_THAN_AGENCIES")
    if not notches:
        return None
    # Index len // 2 of the sorted notches is the single one, the worse of two
    # and the median of three.
    ordered = sorted(notches)
    return ordered[len(ordered) // 2]


def bucket(n: int | None) -> Bucket:
    """IG to BBB-, then BB to BB-, B to B-, CCC and below; NR for None."""
    if n is None:
        return "NR"
    if n <= _IG_FLOOR:
        return "IG"
    if n <= _BB_FLOOR:
        return "BB"
    if n <= _B_FLOOR:
        return "B"
    return "CCC_AND_BELOW"


def composite_label(n: int | None) -> str:
    """The S&P/Fitch spelling of a notch, or "NR" for None."""
    if n is None:
        return "NR"
    if not 1 <= n <= len(SP_FITCH_SCALE):
        raise ClassificationRefused("NOTCH_OUT_OF_RANGE")
    return SP_FITCH_SCALE[n - 1]


def valid_domicile(code: str) -> bool:
    """Two upper-case ASCII letters, the ISO 3166-1 alpha-2 shape."""
    # ponytail: format only, no country table; a well-formed code that names no
    # country passes. Upgrade to an ISO 3166-1 table if a bad code ever lands.
    return _DOMICILE.fullmatch(code) is not None
