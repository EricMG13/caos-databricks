"""The Book's classification vocabularies and the composite rating."""

from __future__ import annotations

from typing import cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from caos.book.classification import (
    AGENCIES,
    GICS_SECTORS,
    MOODYS_SCALE,
    OUTLOOKS,
    SP_FITCH_SCALE,
    ClassificationRefused,
    bucket,
    composite_label,
    composite_notch,
    notch,
    valid_domicile,
)


def test_middle_of_three_is_the_median_notch() -> None:
    ratings = [notch("MOODYS", "Ba1"), notch("SP", "BBB-"), notch("FITCH", "BB")]
    assert composite_notch(ratings) == 11
    assert composite_notch([14, 9, 12]) == 12
    assert composite_notch([5, 5, 20]) == 5


def test_lower_of_two_is_the_worse_rating() -> None:
    assert composite_notch([notch("SP", "BBB-"), notch("MOODYS", "Ba1")]) == 11
    assert composite_notch([16, 3]) == 16
    assert composite_notch([7]) == 7
    assert composite_notch([]) is None


def test_composite_refuses_more_than_three_ratings() -> None:
    with pytest.raises(ClassificationRefused, match="MORE_RATINGS_THAN_AGENCIES"):
        composite_notch([1, 2, 3, 4])


def test_buckets_split_at_bbb_minus_bb_minus_and_b_minus() -> None:
    assert bucket(1) == "IG"
    assert bucket(notch("SP", "BBB-")) == "IG"
    assert bucket(notch("SP", "BB+")) == "BB"
    assert bucket(notch("FITCH", "BB-")) == "BB"
    assert bucket(notch("SP", "B+")) == "B"
    assert bucket(notch("MOODYS", "B3")) == "B"
    assert bucket(notch("SP", "CCC+")) == "CCC_AND_BELOW"
    assert bucket(notch("SP", "D")) == "CCC_AND_BELOW"
    assert bucket(None) == "NR"


def test_composite_label_spells_the_notch_as_sp_and_fitch_do() -> None:
    assert composite_label(1) == "AAA"
    assert composite_label(10) == "BBB-"
    assert composite_label(notch("MOODYS", "Ca")) == "CC"
    assert composite_label(22) == "D"
    assert composite_label(None) == "NR"
    with pytest.raises(ClassificationRefused, match="NOTCH_OUT_OF_RANGE"):
        composite_label(23)
    with pytest.raises(ClassificationRefused, match="NOTCH_OUT_OF_RANGE"):
        composite_label(0)


def test_every_scale_entry_has_a_notch() -> None:
    assert len(MOODYS_SCALE) == 21
    assert len(SP_FITCH_SCALE) == 22
    assert [notch("MOODYS", r) for r in MOODYS_SCALE] == list(range(1, 22))
    for agency in ("SP", "FITCH"):
        assert [notch(agency, r) for r in SP_FITCH_SCALE] == list(range(1, 23))
    assert notch("MOODYS", "Baa3") == notch("SP", "BBB-") == 10
    assert notch("MOODYS", "Ca") == 20
    assert notch("MOODYS", "C") == 21
    assert notch("SP", "D") == 22


def test_notch_refuses_an_unknown_rating_or_agency() -> None:
    with pytest.raises(ClassificationRefused, match="UNKNOWN_RATING"):
        notch("MOODYS", "BBB")
    with pytest.raises(ClassificationRefused, match="UNKNOWN_RATING"):
        notch("SP", "D-")
    with pytest.raises(ClassificationRefused, match="UNKNOWN_RATING"):
        notch("MOODYS", "D")
    with pytest.raises(ClassificationRefused, match="UNKNOWN_AGENCY") as refused:
        notch("DBRS", "AAA")
    assert refused.value.code == "UNKNOWN_AGENCY"
    assert isinstance(refused.value, ValueError)


def test_agencies_and_outlooks_are_the_closed_vocabularies() -> None:
    assert AGENCIES == ("MOODYS", "SP", "FITCH")
    assert OUTLOOKS == (
        "STABLE",
        "POSITIVE",
        "NEGATIVE",
        "DEVELOPING",
        "WATCH_POS",
        "WATCH_NEG",
        "WATCH_DEV",
    )
    for agency in AGENCIES:
        assert notch(agency, "C") == 21


def test_industry_groups_belong_to_their_sector() -> None:
    assert len(GICS_SECTORS) == 11
    groups = [group for sector in GICS_SECTORS.values() for group in sector]
    assert len(groups) == 25
    assert len(set(groups)) == 25
    assert GICS_SECTORS["Industrials"] == (
        "Capital Goods",
        "Commercial & Professional Services",
        "Transportation",
    )
    discretionary = GICS_SECTORS["Consumer Discretionary"]
    assert "Consumer Discretionary Distribution & Retail" in discretionary
    assert "Consumer Staples Distribution & Retail" in GICS_SECTORS["Consumer Staples"]
    assert GICS_SECTORS["Financials"] == ("Banks", "Financial Services", "Insurance")
    assert GICS_SECTORS["Real Estate"] == (
        "Equity Real Estate Investment Trusts (REITs)",
        "Real Estate Management & Development",
    )
    assert GICS_SECTORS["Energy"] == ("Energy",)
    assert GICS_SECTORS["Utilities"] == ("Utilities",)


def test_gics_sectors_cannot_be_mutated() -> None:
    with pytest.raises(TypeError):
        cast("dict[str, tuple[str, ...]]", GICS_SECTORS)["Energy"] = ("Oil",)


def test_valid_domicile_is_two_upper_case_letters() -> None:
    assert valid_domicile("GB")
    assert valid_domicile("US")
    assert not valid_domicile("gb")
    assert not valid_domicile("GBR")
    assert not valid_domicile("G")
    assert not valid_domicile("")
    assert not valid_domicile("GB\n")
    assert not valid_domicile("G1")


@settings(deadline=None, max_examples=200)
@given(st.lists(st.integers(min_value=1, max_value=22), min_size=1, max_size=3))
def test_composite_is_one_of_the_inputs_for_any_ratings(notches: list[int]) -> None:
    composite = composite_notch(notches)
    assert composite in notches
    assert min(notches) <= composite <= max(notches)
    assert composite_notch(list(reversed(notches))) == composite


def test_the_frontends_dialog_vocabularies_are_these() -> None:
    """The Add to Book dialog offers the words written out in
    `frontend/src/sections/book/classification.ts`; the sectors, groups,
    outlooks and withdrawal reasons there are these, in this order."""
    from pathlib import Path

    from caos.store.book import WITHDRAWAL_REASONS

    source = (
        Path(__file__).resolve().parents[1]
        / "frontend/src/sections/book/classification.ts"
    ).read_text(encoding="utf-8")
    words: list[str] = []
    for sector, groups in GICS_SECTORS.items():
        words.extend((sector, *groups))
    words.extend(OUTLOOKS)
    words.extend(WITHDRAWAL_REASONS)
    at = 0
    for word in words:
        # Multi-word sectors are quoted keys; single words may be bare keys.
        found = [
            source.find(f'"{word}"', at),
            source.find(f"  {word}:", at),
            source.find(f'["{word}"', at),
        ]
        index = min((i for i in found if i >= 0), default=-1)
        assert index >= at, word
        at = index
