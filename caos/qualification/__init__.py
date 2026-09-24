"""Two words, and the line this package exists to hold between them.

Qualification defines both, because nothing else does:

`ORCHESTRATION_PROOF` is what the host can assert **on its own** -- the pinned
methodology ran as pinned, against the pinned sources, and every citation
re-located. Every one of those is a fact this repository holds the records for,
so a control here can check it and say so.

`QUALIFIED` is a reviewer's signature that the outputs met the answer keys. It
is not a fact the host holds, and no amount of green suite makes it one. It
remains an **external input** until the credential and the analyst approvals
exist, which is why it arrives only as a verdict someone signed and never as a
value a function here computed.

The distinction is the whole phase. A system that could mint its own
`QUALIFIED` would be certifying itself, and the word would mean "this build
believes it is correct" -- which is what every build believes. So the two words
live in one enum, and only one of them has a host control that produces it:
`caos.qualification.verdict.read_verdict` relays the reviewer's, and nothing
else in this repository constructs it.
"""

from __future__ import annotations

from enum import StrEnum


class Assurance(StrEnum):
    """What may be said about a build's outputs, and by whom.

    Two members, two authors. The host writes the first from its own records;
    only a reviewer writes the second.
    """

    ORCHESTRATION_PROOF = "ORCHESTRATION_PROOF"
    QUALIFIED = "QUALIFIED"
