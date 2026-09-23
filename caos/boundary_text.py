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
# invisibly and is the shape a hidden instruction arrives in.
SHAPING_FORMAT = frozenset("\u200c\u200d\u00ad")
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
# The variation selectors carry a byte each past one visible character, and the
# tag block, the Hangul fillers, the combining grapheme joiner and the reserved
# ranges show nothing at all: an approver's preview cannot show what they say.
IGNORABLE_RANGES = (
    "\u034f\u115f-\u1160\u17b4-\u17b5\u180b-\u180d\u180f\u2065\u2800\u3164"
    "\ufe00-\ufe0d\uffa0\ufff0-\ufff8\U000e0000-\U000e0fff"
)
# Text and emoji presentation, the two selectors ordinary text carries (the
# warning sign drawn as an emoji is U+26A0 U+FE0F). Visible as a change to the
# character before them, so one after a character that is drawn is kept, and
# any other -- at the start, after a space, after another selector -- is hidden.
PRESENTATION_SELECTORS = "\ufe0e\ufe0f"
_HIDDEN_SET = f"{FORMAT_RANGES}{IGNORABLE_RANGES}"
_NOT_DRAWN = f"{_HIDDEN_SET}{PRESENTATION_SELECTORS}\\s"
_HIDDEN = re.compile(
    f"[{_HIDDEN_SET}]"
    f"|[{PRESENTATION_SELECTORS}](?<=[{_NOT_DRAWN}][{PRESENTATION_SELECTORS}])"
    f"|\\A[{PRESENTATION_SELECTORS}]"
)


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
    code point and the braille blank (EV-3), and a presentation selector that
    follows nothing drawn. ASCII carries none, so the common line costs one C
    call.
    """
    if text.isascii():
        return False
    return _HIDDEN.search(text) is not None


def visible(text: str) -> str:
    """`text` without every character `hides_text` refuses in it.

    One expression serves both, so the host never shows text its own reader
    would refuse: `visible(text) == text` exactly when `hides_text(text)` is
    false, and `hides_text(visible(text))` is always false -- a selector kept
    follows a drawn character, which nothing here removes (EV-5).
    """
    if text.isascii():
        return text
    return _HIDDEN.sub("", text)


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
