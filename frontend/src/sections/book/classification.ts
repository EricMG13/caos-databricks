// The Book's classification vocabularies as the Add to Book dialog offers them
// (spec B3, B5): GICS sectors and their industry groups, the outlook words, the
// withdrawal reasons. They are `caos/book/classification.py` and
// `caos.store.book.WITHDRAWAL_REASONS` written out, in the same order; the
// server judges every word again at commit, and `tests/test_book_classification.py`
// fails if either side moves without the other. The rating scales are
// `./view`'s.
export { MOODYS_SCALE, SP_FITCH_SCALE } from "./view";

export const GICS_SECTORS: Readonly<Record<string, readonly string[]>> = {
  Energy: ["Energy"],
  Materials: ["Materials"],
  Industrials: ["Capital Goods", "Commercial & Professional Services", "Transportation"],
  "Consumer Discretionary": [
    "Automobiles & Components",
    "Consumer Durables & Apparel",
    "Consumer Services",
    "Consumer Discretionary Distribution & Retail",
  ],
  "Consumer Staples": [
    "Consumer Staples Distribution & Retail",
    "Food, Beverage & Tobacco",
    "Household & Personal Products",
  ],
  "Health Care": [
    "Health Care Equipment & Services",
    "Pharmaceuticals, Biotechnology & Life Sciences",
  ],
  Financials: ["Banks", "Financial Services", "Insurance"],
  "Information Technology": [
    "Software & Services",
    "Technology Hardware & Equipment",
    "Semiconductors & Semiconductor Equipment",
  ],
  "Communication Services": ["Telecommunication Services", "Media & Entertainment"],
  Utilities: ["Utilities"],
  "Real Estate": [
    "Equity Real Estate Investment Trusts (REITs)",
    "Real Estate Management & Development",
  ],
};

export const OUTLOOKS = [
  ["STABLE", "Stable"],
  ["POSITIVE", "Positive"],
  ["NEGATIVE", "Negative"],
  ["DEVELOPING", "Developing"],
  ["WATCH_POS", "Watch positive"],
  ["WATCH_NEG", "Watch negative"],
  ["WATCH_DEV", "Watch developing"],
] as const;

export const AGENCIES = [
  { key: "moodys", label: "Moody's", scale: "moodys" },
  { key: "sp", label: "S&P", scale: "sp_fitch" },
  { key: "fitch", label: "Fitch", scale: "sp_fitch" },
] as const;

export const WITHDRAWAL_REASONS = [
  ["ADDED_IN_ERROR", "Added in error"],
  ["DATA_ERROR", "Data error"],
  ["SUPERSEDED_SOURCES", "Sources superseded"],
  ["OTHER", "Other"],
] as const;

/** The note a withdrawal carries at most; the wire's bound. */
export const WITHDRAWAL_NOTE_MAX = 1000;
