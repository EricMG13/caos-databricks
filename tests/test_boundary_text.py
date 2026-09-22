"""BoundaryText — the type every string crossing into pinned state must be.

Invariant (CLAUDE.md, standing rules): every string that can reach pinned state,
a revision, a frozen payload or an audit event carries BoundaryText, never a
bare str. NFC-normalised before the length bound; rejects lone surrogates, Cc
controls except CR/LF/TAB, and bidirectional override/isolate controls.

A bidi override is the attack this exists for: U+202E makes an audit event read
backwards on screen while the bytes say something else, so what a human approves
and what the store holds are different sentences.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from caos.boundary_text import BoundaryText
from caos.refusals import Refusal, RefusalCode

REPO = Path(__file__).resolve().parents[1]

# What this repository writes, and therefore what it is answerable for. Mirrors
# `sonar-project.properties`'s source list; `vendor/` is upstream authority
# nobody may edit, and the build outputs under it are not ours either.
WRITTEN = (
    "scripts",
    "server",
    "tests",
    "frontend/src",
    "frontend/scripts",
    "frontend/tests",
    ".github",
    "docs",
)

# LRE, RLE, PDF, LRO, RLO, and the isolates LRI, RLI, FSI, PDI.
BIDI_CONTROLS = [
    "\u202a",
    "\u202b",
    "\u202c",
    "\u202d",
    "\u202e",
    "\u2066",
    "\u2067",
    "\u2068",
    "\u2069",
]


@pytest.mark.parametrize("control", BIDI_CONTROLS)
def test_boundary_text_rejects_bidi_override(control: str) -> None:
    with pytest.raises(Refusal) as caught:
        BoundaryText.of(f"Acme Holdings{control} Ltd")
    assert caught.value.code is RefusalCode.BOUNDARY_TEXT_INVALID


def test_boundary_text_refusal_carries_no_offending_text() -> None:
    secret = "Acme Holdings\u202e Ltd"
    with pytest.raises(Refusal) as caught:
        BoundaryText.of(secret)
    # Never log document-derived text: the refusal names the code, not the input.
    rendered = f"{caught.value!r} {caught.value!s} {caught.value.args}"
    assert "Acme" not in rendered


def test_boundary_text_normalises_to_nfc_before_bounding() -> None:
    # e + U+0301 is two code points; NFC folds each pair into one. Six code
    # points in, three out -- a limit of 3 passes only if NFC ran first.
    decomposed = "e\u0301" * 3
    assert BoundaryText.of(decomposed, limit=3).value == "\u00e9" * 3


def test_boundary_text_bounds_length_after_normalising() -> None:
    with pytest.raises(Refusal) as caught:
        BoundaryText.of("e\u0301" * 4, limit=3)
    assert caught.value.code is RefusalCode.BOUNDARY_TEXT_TOO_LONG


@pytest.mark.parametrize("control", ["\x00", "\x07", "\x1b", "\x7f"])
def test_boundary_text_rejects_cc_controls(control: str) -> None:
    with pytest.raises(Refusal):
        BoundaryText.of(f"Acme{control}Ltd")


@pytest.mark.parametrize("kept", ["\r", "\n", "\t"])
def test_boundary_text_keeps_the_three_allowed_controls(kept: str) -> None:
    assert BoundaryText.of(f"Acme{kept}Ltd").value == f"Acme{kept}Ltd"


def test_boundary_text_rejects_a_lone_surrogate() -> None:
    with pytest.raises(Refusal):
        BoundaryText.of("Acme\ud800Ltd")


def test_no_file_this_repository_writes_carries_a_literal_bidi_control() -> None:
    """The rule `caos/boundary_text.py` states in a comment, enforced.

    That comment says a bidi control is written as a code point "on purpose: a
    literal bidi control here would make this file itself render deceptively,
    which is the trojan-source class (CVE-2021-42574) this module exists to
    refuse." It was true and it was not checked, so the first test written
    against `BoundaryText` from outside this file pasted a literal U+202E into
    the suite and nothing said so until an external analyzer did.

    A host that refuses a bidi override in an audit event and ships one in its
    own source is refusing the attack in the one place it does not live. The
    escape form -- `"\\u202e"` -- is the same character at run time and no
    control byte in the file.
    """
    offenders: list[str] = []
    scanned = 0
    for root in WRITTEN:
        for path in sorted((REPO / root).rglob("*")):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # not text this repository authored as text
            scanned += 1
            for control in BIDI_CONTROLS:
                if control in text:
                    line = text[: text.index(control)].count("\n") + 1
                    offenders.append(
                        f"{path.relative_to(REPO)}:{line}: "
                        f"U+{ord(control):04X}, write it as an escape"
                    )

    # A scanner that scanned nothing is a failure, not a pass (`CLAUDE.md`).
    assert scanned > 100, f"only {scanned} files scanned; the roots moved"
    assert not offenders, offenders
