"""Portable packages; saved revision chain tests live in test_filing_chain."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from caos.boundary_text import BoundaryText
from caos.deliverable.package import (
    EXPORT,
    PAYLOAD,
    build_package,
    packed_receipt,
    verify_package,
    write_package,
)
from caos.deliverable.render import render

REVISION = BoundaryText.of("rev-001")
# The same visible label in the two Unicode normal forms: composed e-acute,
# then "e" followed by a combining acute. Written as escapes so the file says
# which is which rather than relying on how an editor saved it.
NFC_LABEL = BoundaryText.of("rev-caf\u00e9")
NFD_SPELLING = "rev-cafe\u0301"

# The canonical shape `render()` understands since the claims render path was
# deleted (f-2a): one artifact carries a
# Markdown handoff and its host record, each addressed by digest, bound by
# hand -- these tests only need bytes `render()` accepts, not a store-produced
# record.
_MARKDOWN = "Total debt at 31 December 2026 was USD 1,240.0m.\n"
_DIGEST = hashlib.sha256(_MARKDOWN.encode()).hexdigest()
_RECORD = {
    "artifact_sha256": _DIGEST,
    "build_id": "a43cb903ca2751f79e77b6da71f6ea131b8462a3",
    "authority_digest": "0302b789df5d0cae" + "0" * 48,
    "projections": {
        "module_id": "CP-1",
        "qa_status": "Passed",
        "committee_status": "Committee Ready",
        "decision_scope": "COMMITTEE",
        "limitation_flags": [],
    },
    "citations": [
        {
            "document_sha256": "6fc4a221c5d5" + "0" * 52,
            "page": 1,
            "matched_text": "Total debt at 31 December 2026",
        }
    ],
}
_RECORD_JSON = json.dumps(_RECORD, sort_keys=True, separators=(",", ":"))

PAYLOAD_DATA: dict[str, Any] = {
    "case_title": "Acme Holdings plc",
    "revision_id": REVISION.value,
    "artifacts": [
        {
            "markdown": _MARKDOWN,
            "record": _RECORD_JSON,
            "artifact_sha256": _DIGEST,
            "record_sha256": hashlib.sha256(_RECORD_JSON.encode()).hexdigest(),
        }
    ],
    "narrative": "Leverage is inside the covenant with limited headroom.",
}
PAYLOAD_BYTES = json.dumps(PAYLOAD_DATA, sort_keys=True).encode("utf-8")


def test_a_package_that_is_not_a_readable_archive_does_not_verify() -> None:
    """The verifier trusts nothing about its input, including that it is a
    zip file at all -- a retained copy could have been truncated or corrupted
    on the way to wherever it is checked."""
    verification = verify_package(b"not a zip archive")

    assert verification.verified is False
    assert verification.reason == "the archive is not a readable package"


def test_a_receipt_naming_fewer_than_three_people_does_not_verify() -> None:
    """The three-actor shape is checked here too, not only at filing time. A
    receipt that survived to verification with the same person in two roles is
    exactly the chain `APPROVER_NOT_INDEPENDENT` exists to prevent -- this is
    the archive's own defence if that check were ever bypassed."""
    same_actor = str(uuid4())
    receipt = json.dumps(
        {
            "payload_sha256": hashlib.sha256(PAYLOAD_BYTES).hexdigest(),
            "signed_by": same_actor,
            "frozen_by": same_actor,
            "filed_by": str(uuid4()),
        }
    ).encode("utf-8")

    verification = verify_package(
        build_package(PAYLOAD_BYTES, receipt, render(PAYLOAD_DATA))
    )

    assert verification.verified is False
    assert verification.reason == "the receipt names fewer than three people"


def test_a_receipt_naming_one_person_under_two_spellings_does_not_verify() -> None:
    """CF-084: a role is a UUID, case-insensitive by RFC 4122. Comparing the
    three roles as bare strings let the same person sign and file under two
    different spellings of one UUID and counted as three distinct people."""
    same_actor = str(uuid4())
    receipt = json.dumps(
        {
            "payload_sha256": hashlib.sha256(PAYLOAD_BYTES).hexdigest(),
            "signed_by": same_actor.upper(),
            "frozen_by": str(uuid4()),
            "filed_by": same_actor.lower(),
        }
    ).encode("utf-8")

    verification = verify_package(
        build_package(PAYLOAD_BYTES, receipt, render(PAYLOAD_DATA))
    )

    assert verification.verified is False
    assert verification.reason == "the receipt names fewer than three people"


def test_a_receipt_that_omits_a_role_does_not_verify() -> None:
    """The gap beside the test above: absent, not duplicated.

    The three actors were read into a set and counted, so a role the receipt
    simply does not carry arrived as `None` and counted as a person. Two named
    signatories and a missing third made a set of three and verified -- the one
    shape this check exists to refuse, passing because nothing asserted the
    roles were filled before asserting they differed.

    `verify_package` is the control for an archive nobody here produced, five
    years from now, so what it does with a malformed receipt is the whole of
    what it is for.
    """
    receipt = json.dumps(
        {
            "payload_sha256": hashlib.sha256(PAYLOAD_BYTES).hexdigest(),
            "signed_by": str(uuid4()),
            "frozen_by": str(uuid4()),
        }
    ).encode("utf-8")

    verification = verify_package(
        build_package(PAYLOAD_BYTES, receipt, render(PAYLOAD_DATA))
    )

    assert verification.verified is False
    assert verification.reason == "the receipt does not name all three roles"


def test_a_receipt_naming_a_role_with_blank_text_does_not_verify() -> None:
    """A role filled with spaces names nobody, and is absence with a space in
    it -- the same reading `caos/qualification/verdict.py` takes of a binding
    that is present and empty."""
    receipt = json.dumps(
        {
            "payload_sha256": hashlib.sha256(PAYLOAD_BYTES).hexdigest(),
            "signed_by": str(uuid4()),
            "frozen_by": str(uuid4()),
            "filed_by": "   ",
        }
    ).encode("utf-8")

    verification = verify_package(
        build_package(PAYLOAD_BYTES, receipt, render(PAYLOAD_DATA))
    )

    assert verification.verified is False
    assert verification.reason == "the receipt does not name all three roles"


def test_a_package_is_the_same_bytes_for_the_same_inputs() -> None:
    """A package whose bytes moved with the clock could not be compared against
    a retained copy, which is what detecting a rewrite depends on."""
    first = build_package(PAYLOAD_BYTES, b"{}", b"<html></html>")
    second = build_package(PAYLOAD_BYTES, b"{}", b"<html></html>")

    assert first == second


def test_a_package_holds_the_five_files_a_reader_needs() -> None:
    import zipfile
    from io import BytesIO

    archive = build_package(PAYLOAD_BYTES, b"{}", b"<html></html>")

    with zipfile.ZipFile(BytesIO(archive)) as opened:
        assert set(opened.namelist()) == {
            PAYLOAD,
            "receipt.json",
            EXPORT,
            "render.py",
            "verify_package.py",
        }


def test_a_filed_package_is_never_overwritten(tmp_path: Path) -> None:
    """§7: never overwriting. A filed deliverable that could be replaced in
    place is not one anybody can rely on having read."""
    path = tmp_path / "package.zip"
    write_package(path, build_package(PAYLOAD_BYTES, b"{}", b"<html></html>"))

    with pytest.raises(FileExistsError):
        write_package(path, build_package(PAYLOAD_BYTES, b"{}", b"<html></html>"))


def test_packed_receipt_reads_a_packages_receipt_and_nothing_else() -> None:
    """W1: the package download serves a stored archive only while the receipt
    it carries is the filing's own; anything that is not a package carrying
    one reads as none."""
    receipt = b'{"payload_sha256":"x"}'
    archive = build_package(PAYLOAD_BYTES, receipt, render(PAYLOAD_DATA))
    assert packed_receipt(archive) == {"payload_sha256": "x"}
    assert packed_receipt(b"not a zip") is None
    assert packed_receipt(build_package(PAYLOAD_BYTES, b"not json", b"")) is None
