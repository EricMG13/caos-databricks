"""The reviewer's signature, read rather than minted.

`docs/REBUILD_PLAN.md` Phase 10: a verdict is bound to provider identity,
qualification-set digest, build, date, expiry and reviewer. This module reads
such a document and either returns a `Verdict` or refuses -- it never builds one
from anything the host knows about itself.

Why six. A signature saying "the outputs met the answer keys" is checkable only
if it also says whose outputs, against which cases, from which build, signed
when, current until when, and by whom. Drop `provider` and the same sentence
covers a model nobody measured. Drop `qualification_set_sha256` and it covers a
set of answer keys that has since been edited. Drop `build_id` and it covers
next year's methodology. Drop the dates and it never stops applying. Drop
`reviewer` and nobody is accountable for it. So a missing binding is
`VERDICT_INCOMPLETE` rather than a `None` field, and the reader refuses before
anything downstream can read a hole as a pass.

Expiry is judged against a `now` the caller passes, not against the clock. Route
resolution is pure for the same reason (`CLAUDE.md`): a decision that reads the
clock cannot be replayed, and a verdict's currency is exactly the kind of
decision someone will later need to re-take at the moment it was taken.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from caos.boundary_text import BoundaryText
from caos.qualification import Assurance
from caos.refusals import Refusal, RefusalCode

# The six, in the order `docs/REBUILD_PLAN.md` Phase 10 names them. This tuple
# is the declared shape: it is what a document is checked for and what it is
# closed against, so the two can never disagree.
BINDINGS = (
    "provider",
    "qualification_set_sha256",
    "build_id",
    "decided_at",
    "expires_at",
    "reviewer",
)

# Lower-case hex, fixed width. A digest that is not one binds the verdict to a
# string nobody can recompute, which is a binding in name only.
_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")

# Provider identity and reviewer are human-authored and reach a stored record,
# so they cross the boundary. The bound is deliberately short: neither is prose.
_TEXT_LIMIT = 256


@dataclass(frozen=True, slots=True)
class Verdict:
    """A reviewer's signature, with everything it is bound to.

    Constructed only by `read_verdict`, from a document this repository did not
    write. That is the structural half of Phase 10's second exit test: the one
    carrier of `Assurance.QUALIFIED` cannot be reached except through an
    external input.
    """

    provider: BoundaryText
    qualification_set_sha256: str
    build_id: str
    decided_at: datetime
    expires_at: datetime
    reviewer: BoundaryText

    @property
    def assurance(self) -> Assurance:
        """`QUALIFIED` -- the reviewer's word, relayed, never the host's own."""
        return Assurance.QUALIFIED


def read_verdict(document: object, *, now: datetime) -> Verdict:
    """Read a signed verdict, or refuse it. The host originates nothing here.

    Four refusals, each a different thing being wrong: a binding absent or blank
    is `VERDICT_INCOMPLETE`; one present but not readable as what it claims is
    `VERDICT_BINDING_INVALID`; a key the six do not declare is
    `VERDICT_UNDECLARED_FIELD`; and a complete, readable verdict whose moment
    has passed is `VERDICT_EXPIRED`. Conflating them would leave a reader unable
    to tell a malformed document from a stale signature, which are the two cases
    with entirely different remedies.
    """
    if (
        type(now) is not datetime
        or now.tzinfo is None
        or now.tzinfo.utcoffset(now) is None
    ):
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    fields = _closed(document)

    provider = _boundary_text(fields, "provider")
    reviewer = _boundary_text(fields, "reviewer")
    qualification_set_sha256 = _digest(fields, "qualification_set_sha256")
    build_id = _present(fields, "build_id").strip()
    decided_at = _moment(fields, "decided_at")
    expires_at = _moment(fields, "expires_at")

    if expires_at <= decided_at:
        # Never current for an instant. Refused as unreadable rather than as
        # expired: "it has expired" would suggest it once was not.
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    if decided_at > now:
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    if now >= expires_at:
        raise Refusal(RefusalCode.VERDICT_EXPIRED)

    return Verdict(
        provider=provider,
        qualification_set_sha256=qualification_set_sha256,
        build_id=build_id,
        decided_at=decided_at,
        expires_at=expires_at,
        reviewer=reviewer,
    )


def _closed(document: object) -> dict[str, Any]:
    """The outer shape: a mapping, carrying the six and nothing else."""
    if not isinstance(document, dict):
        raise Refusal(RefusalCode.VERDICT_INCOMPLETE)
    if set(document) - set(BINDINGS):
        raise Refusal(RefusalCode.VERDICT_UNDECLARED_FIELD)
    return document


def _present(fields: dict[str, Any], binding: str) -> str:
    """One binding, present and not blank. Whitespace is absence with a space in
    it, and a verdict signed by `"   "` names nobody."""
    value = fields.get(binding)
    if not isinstance(value, str) or not value.strip():
        raise Refusal(RefusalCode.VERDICT_INCOMPLETE)
    return value


def _boundary_text(fields: dict[str, Any], binding: str) -> BoundaryText:
    """Human-authored, so it crosses the boundary before it is held."""
    return BoundaryText.of(_present(fields, binding).strip(), limit=_TEXT_LIMIT)


def _digest(fields: dict[str, Any], binding: str) -> str:
    value = _present(fields, binding).strip()
    if not _SHA256.match(value):
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    return value


def _moment(fields: dict[str, Any], binding: str) -> datetime:
    """An ISO-8601 instant carrying an offset.

    Without one the moment is in an unstated zone, and comparing it with an
    aware `now` raises rather than answers -- so the refusal here is what keeps
    the expiry check above a decision instead of a crash.
    """
    try:
        moment = datetime.fromisoformat(_present(fields, binding).strip())
    except ValueError:
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID) from None
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise Refusal(RefusalCode.VERDICT_BINDING_INVALID)
    return moment
