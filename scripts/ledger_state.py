#!/usr/bin/env python3
"""Read the known-gaps ledger in CLAUDE.md as structured entries.

The ledger is the contract's honest record of accepted limitations, and it rots
in one direction: an entry stays open after the work that closed it has landed,
so a reader is warned about a gap the tree no longer has. `CLAUDE.md` already
says an entry describing a gap the tree has since closed "is the same defect as
a missing one, read the other way round" -- this module is what lets a test say
so mechanically instead of trusting a reviewer to notice.

It parses and judges nothing. `tests/test_ledger.py` holds the rules, because
which entries may be open is repository policy rather than a property of the
text. `--report` prints what this reader sees, which is how a person checks the
parser itself rather than the ledger.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONTRACT = REPO / "CLAUDE.md"
HEADING = "## Known gaps (honest ledger)"

# A struck entry opens `- ~~**Title.**~~`; an open one `- **Title.**`. The bold
# run may wrap, so the title is read from the whole entry rather than line one.
_TITLE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_TEST = re.compile(r"\btest_[a-z0-9_]+")
# Seven or more hex digits in backticks. That is how this repository writes a
# commit and also how it writes a methodology bundle build id (`30222a49`,
# `cdea0c9f`), and nothing in the text distinguishes them -- so the field is
# named for what it holds rather than for commits. Separating them would mean
# asking git whether each id resolves, which is I/O this reader does not do.
_HEX_ID = re.compile(r"`([0-9a-f]{7,40})`")
_PHASE = re.compile(r"^\*\*(.+?)\.?\*\*$")
_MOVED = f"the contract has no {HEADING!r} section"
_UNSEPARATED = "ledger heading {heading} has no blank line before it"
_FOREIGN = "ledger line {line!r} is a list item this reader does not count"
# Any list marker but the one this ledger uses. Each was silently absorbed
# into the entry above it, so an entry written this way was invisible to
# every rule -- which an adversary can use and an author can do by accident.
_FOREIGN_ITEM = re.compile(r"^(?:\s+[-*+]\s|[*+]\s|\d+[.)]\s)")


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One ledger bullet: what it claims, and the evidence it cites."""

    phase: str
    title: str
    struck: bool
    tests: tuple[str, ...]
    hex_ids: tuple[str, ...]
    upgrade: bool
    body: str

    @property
    def open(self) -> bool:
        return not self.struck


def _ledger_text(text: str) -> str:
    """The ledger section alone, or `ValueError` if the heading has moved.

    A reader that silently returned nothing would make every rule above it
    vacuously true, which is the failure mode `scan_floors.py` exists to stop.
    """
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(HEADING)]
    if not starts:
        raise ValueError(_MOVED)
    start = starts[0]
    # An H1 ends the section as surely as an H2: the contract carries an
    # appended `# GitNexus` block, which was being read as ledger body.
    after = [
        i
        for i, line in enumerate(lines)
        if i > start and (line.startswith("## ") or line.startswith("# "))
    ]
    end = after[0] if after else len(lines)
    return "\n".join(lines[start:end])


def entries(text: str) -> list[LedgerEntry]:
    """Every top-level bullet of the ledger section, in file order."""
    phase = ""
    collected: list[LedgerEntry] = []
    current: list[str] = []

    def flush() -> None:
        if not current:
            return
        body = "\n".join(current).strip()
        found = _TITLE.search(body)
        title = " ".join(found.group(1).split()) if found else body[:80]
        collected.append(
            LedgerEntry(
                phase=phase,
                title=title.rstrip("."),
                struck=current[0].startswith("- ~~"),
                tests=tuple(sorted(frozenset(_TEST.findall(body)))),
                hex_ids=tuple(sorted(frozenset(_HEX_ID.findall(body)))),
                upgrade="*Upgrade:*" in body,
                body=body,
            )
        )
        current.clear()

    for line, was_blank in _readable(_ledger_text(text)):
        heading = _PHASE.fullmatch(line.strip())
        if heading is not None and not line.startswith("- "):
            # Refused rather than absorbed. A heading whose blank line was
            # deleted used to be read as entry text, which silently moved every
            # entry below it under the previous phase and left the entry count
            # unchanged -- so the one signal a reviewer is likely to check could
            # not see it. It happened here, in this file's own history.
            if not was_blank:
                raise ValueError(_UNSEPARATED.format(heading=line.strip()))
            flush()
            phase = heading.group(1)
            continue
        if line.startswith("- "):
            flush()
            current.append(line)
        elif current:
            current.append(line)
    flush()
    return collected


def _readable(section: str) -> Iterator[tuple[str, bool]]:
    """Each line of the section the parser may read, with whether a blank
    preceded it.

    Two shapes are filtered here rather than in `entries`. A fenced block's
    contents are an example, not entries -- two struck bullets inside one were
    being counted as closed gaps. And any list marker but this ledger's `- `
    is refused outright: `*`, `+`, a numbered item and an indented dash were
    each absorbed into the entry above, so an entry written that way was
    invisible to every rule, which an adversary can exploit and an author can
    do by accident.
    """
    blank_before = True
    fenced = False
    for line in section.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if _FOREIGN_ITEM.match(line):
            raise ValueError(_FOREIGN.format(line=line.strip()[:60]))
        was_blank, blank_before = blank_before, not line.strip()
        yield line, was_blank


def read(path: Path = CONTRACT) -> list[LedgerEntry]:
    """The ledger of one contract file."""
    return entries(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # Path-traversal scanners flag `--contract` as a generic "user request"
    # source reaching a file-read sink -- the template does not know this is
    # argv, not a request body. There is no HTTP boundary here: this module
    # is a CLI script an operator runs from their own shell (never imported
    # by server/), so the path is exactly as trusted as any other argument
    # to a command they typed themselves.
    parser.add_argument("--contract", type=Path, default=CONTRACT)
    parser.add_argument(
        "--report", action="store_true", help="print one line per entry"
    )
    args = parser.parse_args(argv)

    try:
        found = read(args.contract)
    except (OSError, ValueError) as error:
        print(f"ledger unreadable: {error}", file=sys.stderr)
        return 2
    if not found:
        print("read no ledger entries; a scan of nothing is a failure", file=sys.stderr)
        return 2

    if args.report:
        for entry in found:
            state = "closed" if entry.struck else "open  "
            evidence = ",".join(entry.tests or entry.hex_ids) or "-"
            print(f"{state} [{entry.phase}] {entry.title[:72]} :: {evidence[:60]}")
    closed = sum(1 for entry in found if entry.struck)
    print(f"{len(found)} entries, {closed} closed, {len(found) - closed} open")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
