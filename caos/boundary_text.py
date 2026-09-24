"""The type every string crossing into pinned state must be.

A bare `str` reaching pinned state, a revision, a frozen payload or an audit
event is a defect. NFC-normalised before the length bound, so what is measured
is what is stored; then refused if it carries a lone surrogate, a Cc control
other than CR/LF/TAB, or a bidirectional override or isolate.

The bidi controls are the reason the type exists rather than a length check:
U+202E makes an audit event render backwards while the bytes say something else,
so the sentence a human approves and the sentence the store holds differ.

`hides_text` states the neighbouring rule -- a character that renders as
nothing -- for the two callers that read untrusted text, and `visible` takes
exactly those characters out of text the host shows. It is deliberately not
part of `BoundaryText.of`, whose table is pinned by the parity goldens.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from caos.refusals import Refusal, RefusalCode

DEFAULT_LIMIT = 4096

# LRE, RLE, PDF, LRO, RLO (U+202A-U+202E), then the isolates LRI, RLI, FSI,
# PDI (U+2066-U+2069). Written as code points on purpose: a literal bidi
# control here would make this file itself render deceptively, which is the
# trojan-source class (CVE-2021-42574) this module exists to refuse.
_BIDI = frozenset(map(chr, [*range(0x202A, 0x202F), *range(0x2066, 0x206A)]))
_KEPT_CONTROLS = frozenset("\r\n\t")

# The three format characters a shaped script or a hyphenation hint actually
# needs: zero-width non-joiner, zero-width joiner, soft hyphen. Every other
# Cf code point renders as nothing at all, so a reader and an approver cannot
# see it -- including the tag block U+E0000-U+E007F, which encodes ASCII
# invisibly and is the shape a hidden instruction arrives in. The three shape
# only the drawn character before them, so each is text only there (W5):
# after a drawn character, a zero-width joiner also after the presentation
# selector of an emoji it joins, and the joiners run together only as the
# Unicode Standard combines them (23.2: <ZWJ, ZWNJ>, <ZWNJ, ZWJ> and
# <ZWJ, ZWNJ, ZWJ> between two letters). Anywhere else -- at the start, after
# a space, after a hidden character or after one another -- they draw and
# shape nothing, and a run of them is a byte channel as a run of selectors is.
SHAPING_FORMAT = frozenset("\u200c\u200d\u00ad")
_SHAPING = "\u200c\u200d\u00ad"
# Every Unicode Cf code point except those three, as ranges. Written out rather
# than derived, because deriving it means asking `unicodedata.category` about a
# million code points, and asked per character it is 2.7 s over 5 MB of
# non-ASCII text -- the cost this rule exists to refuse, paid on every document
# and every handoff. One compiled expression is 0.14 s over the same text.
# `tests/test_boundary_text.py` regenerates the table from `unicodedata` and
# refuses a drift, so a Unicode upgrade that adds a format character is loud.
FORMAT_RANGES = (
    "\u0600-\u0605\u061c\u06dd\u070f\u0890-\u0891\u08e2\u180e\u200b\u200e-\u200f"
    "\u202a-\u202e\u2060-\u2064\u2066-\u206f\ufeff\ufff9-\ufffb\U000110bd"
    "\U000110cd\U00013430-\U0001343f\U0001bca0-\U0001bca3\U0001d173-\U0001d17a"
    "\U000e0001\U000e0020-\U000e007f"
)
# The code points Unicode itself says render as nothing -- Default_Ignorable_
# Code_Point in DerivedCoreProperties (15.1) -- that are not `Cf` and so not in
# the table above, and the braille blank, which is drawn as an empty cell (EV-3).
# The tag block, the Hangul fillers and the reserved ranges show nothing at
# all: an approver's preview cannot show what they say. The selectors among the
# default ignorables are below, because they are sometimes text.
IGNORABLE_RANGES = (
    "\u115f-\u1160\u17b4-\u17b5\u2065\u2800\u3164"
    "\uffa0\ufff0-\ufff8\U000e0000-\U000e00ff\U000e01f0-\U000e0fff"
)
# The selectors, each visible only as a change to the character before it
# (N49): a registered ideographic variation sequence is how a Japanese name
# keeps its glyph, U+26A0 U+FE0F is the warning sign drawn as an emoji, and the
# grapheme joiner keeps two Hebrew points in their written order. Exactly one is
# kept directly after the base it can change; anywhere else -- at the start,
# after a space, a hidden or a shaping character, and after another selector --
# it draws nothing, and a run of them is the byte channel EV-3 carried an
# instruction through (W5: ZWJ + selector pairs rebuilt the run).
VARIATION_SELECTORS = "\ufe00-\ufe0f"
# VS15 and VS16, text and emoji presentation: after any drawn character, a
# combining mark included.
PRESENTATION_SELECTORS = "\ufe0e\ufe0f"
# VS1-VS14 change a glyph only where a variant is registered for the character
# before them (StandardizedVariants.txt), which a Latin letter never has: after
# any drawn character they left four hidden bits per letter (W5). Kept after a
# CJK ideograph, and after the two small sets the standard registers outside
# them that a document plausibly carries, written out rather than read from a
# data file: VS1 on the mathematical operators with a serif or stroke variant
# (the digit zero's is left out: it would put a hidden bit on every zero of a
# financial table), and VS1-VS2 on the East Asian full stops, commas and marks
# with a corner-justified and a centred form.
MATH_VARIANT_BASES = (
    "\u2205\u2229\u222a\u2268\u2269\u2272\u2273\u228a\u228b\u2293\u2294\u2295"
    "\u2297\u229c\u22da\u22db\u2a3c\u2a3d\u2a9d\u2a9e\u2aac\u2aad\u2acb\u2acc"
)
PUNCTUATION_VARIANT_BASES = "\u3001\u3002\uff01\uff0c\uff0e\uff1a\uff1b\uff1f"
# The combining grapheme joiner keeps two combining marks apart in their
# written order, so it is text only between two of them (W5).
GRAPHEME_JOINER = "\u034f"
# VS17-VS256, the Ideographic Variation Database's: after an ideograph only.
IDEOGRAPHIC_SELECTORS = "\U000e0100-\U000e01ef"
# FVS1-FVS4: after a Mongolian letter only.
MONGOLIAN_SELECTORS = "\u180b-\u180d\u180f"
# Their bases, written out for the reason `FORMAT_RANGES` is and regenerated
# from `unicodedata` names by `tests/test_boundary_text.py`: every CJK unified
# and compatibility ideograph, and every Mongolian letter.
CJK_IDEOGRAPHS = (
    "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufa6d\ufa70-\ufad9\U00020000-\U0002a6df"
    "\U0002a700-\U0002b739\U0002b740-\U0002b81d\U0002b820-\U0002cea1"
    "\U0002ceb0-\U0002ebe0\U0002ebf0-\U0002ee5d\U0002f800-\U0002fa1d"
    "\U00030000-\U0003134a\U00031350-\U000323af"
)
MONGOLIAN_LETTERS = "\u1820-\u1878\u1880-\u1884\u1887-\u18a8\u18aa"
_SELECTORS = (
    f"{VARIATION_SELECTORS}{GRAPHEME_JOINER}{IDEOGRAPHIC_SELECTORS}"
    f"{MONGOLIAN_SELECTORS}"
)
_HIDDEN_SET = f"{FORMAT_RANGES}{IGNORABLE_RANGES}"
# A drawn character: none of the above, no shaping character and no space.
_DRAWN = f"[^{_HIDDEN_SET}{_SELECTORS}{_SHAPING}\\s]"
_ZWNJ, _ZWJ = "\u200c", "\u200d"
_VS2_BASES = f"{CJK_IDEOGRAPHS}{PUNCTUATION_VARIANT_BASES}"
_VS1_BASES = f"{_VS2_BASES}{MATH_VARIANT_BASES}"
# Each selector and shaping character is hidden unless one of the lookbehinds
# names the character before it as the base it can change -- a lookbehind finds
# nothing at the start of the text, so there it is hidden too. The grapheme
# joiner reads the character after it as well, so it is matched here and
# decided by `_hidden` (`_joins_marks`).
_HIDDEN = re.compile(
    f"[{_HIDDEN_SET}]"
    f"|[{PRESENTATION_SELECTORS}](?<!{_DRAWN}[{PRESENTATION_SELECTORS}])"
    f"|\ufe00(?<![{_VS1_BASES}]\ufe00)"
    f"|\ufe01(?<![{_VS2_BASES}]\ufe01)"
    f"|[\ufe02-\ufe0d](?<![{CJK_IDEOGRAPHS}][\ufe02-\ufe0d])"
    f"|[{IDEOGRAPHIC_SELECTORS}](?<![{CJK_IDEOGRAPHS}][{IDEOGRAPHIC_SELECTORS}])"
    f"|[{MONGOLIAN_SELECTORS}](?<![{MONGOLIAN_LETTERS}][{MONGOLIAN_SELECTORS}])"
    f"|[{_SHAPING}](?<!{_DRAWN}[{_SHAPING}])(?<!{_DRAWN}{_ZWJ}{_ZWNJ})"
    f"(?<!{_DRAWN}[{_ZWNJ}{PRESENTATION_SELECTORS}]{_ZWJ})"
    f"(?<!{_DRAWN}{_ZWJ}{_ZWNJ}{_ZWJ})"
    f"|{GRAPHEME_JOINER}"
)
# What a grapheme joiner may sit between: a combining mark that is none of the
# characters this module hides or selects with.
_NOT_A_MARK = re.compile(f"[{_HIDDEN_SET}{_SELECTORS}]")


def hides_text(text: str) -> bool:
    """Whether `text` carries a character no reader can see.

    `BoundaryText` itself keeps them: its accept/refuse table is pinned by the
    `boundary_text` parity goldens (`tag_character`, `byte_order_mark`,
    `word_joiner`, `zero_width_space`, `arabic_letter_mark`,
    `right_to_left_mark` all record the character passing through), and a type
    used for filenames, audit sentences and identity strings is not where a
    document-admission rule belongs. The two callers that read untrusted text
    -- evidence admission and the canonical handoff -- ask this instead, so the
    text a human approves is the text the model is given (AI-2).

    Every `Cf` but the three shaping characters, every other default-ignorable
    code point and the braille blank (EV-3), a selector that does not directly
    follow the base it can change -- one of them after it is text, a second
    never is (N49) -- and a shaping character that follows nothing it can
    shape (W5). ASCII carries none, so the common line costs one C call.
    """
    if text.isascii():
        return False
    return any(_hidden(found) for found in _HIDDEN.finditer(text))


def visible(text: str) -> str:
    """`text` without every character `hides_text` refuses in it.

    One expression serves both, so the host never shows text its own reader
    would refuse: `visible(text) == text` exactly when `hides_text(text)` is
    false, and `hides_text(visible(text))` is always false -- a selector or a
    shaping character kept follows the drawn base it changes, or a kept
    presentation selector or joiner before it, and a grapheme joiner kept sits
    between two combining marks: nothing here removes any of them (EV-5, W5).
    """
    if text.isascii():
        return text
    return _HIDDEN.sub(_shown, text)


def _hidden(found: re.Match[str]) -> bool:
    """Whether a match of `_HIDDEN` is hidden: every one is, but a grapheme
    joiner between two combining marks."""
    return found.group() != GRAPHEME_JOINER or not _joins_marks(
        found.string, found.start()
    )


def _shown(found: re.Match[str]) -> str:
    return "" if _hidden(found) else found.group()


def _joins_marks(text: str, at: int) -> bool:
    """Whether the grapheme joiner at `at` sits between two combining marks,
    the one place it keeps anything apart (W5). Neither neighbour is ever taken
    out by `visible`, so a joiner kept here is kept in what it returns."""
    return 0 < at < len(text) - 1 and all(
        unicodedata.category(text[near]).startswith("M")
        and _NOT_A_MARK.match(text[near]) is None
        for near in (at - 1, at + 1)
    )


def _is_refused(character: str) -> bool:
    if character in _KEPT_CONTROLS:
        return False
    return character in _BIDI or unicodedata.category(character) in {"Cc", "Cs"}


@dataclass(frozen=True, slots=True)
class BoundaryText:
    """Text that has passed the boundary. Construct it with `of`, never directly."""

    value: str

    @classmethod
    def of(cls, raw: str, *, limit: int = DEFAULT_LIMIT) -> BoundaryText:
        normalised = unicodedata.normalize("NFC", raw)
        if any(_is_refused(character) for character in normalised):
            raise Refusal(RefusalCode.BOUNDARY_TEXT_INVALID)
        if len(normalised) > limit:
            raise Refusal(RefusalCode.BOUNDARY_TEXT_TOO_LONG)
        return cls(normalised)
