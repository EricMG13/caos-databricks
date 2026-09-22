"""Every stored digest these sites produce, pinned byte for byte.

Task 14 moved where the canonical JSON is written, not what it emits. A digest
here names audit chains, signed payloads, filed receipts, route pins, command
receipts and qualification sets that already exist in databases, so a value
that moves is not a refactor -- it is stored rows that stop verifying. The
fixture carries non-ASCII text and decimal strings because that is where the
`ensure_ascii` split between the two families of sites is visible: the converted
sites emit the characters, the escaping sites left alone escape them.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from hashlib import sha256
from typing import Any
from uuid import UUID

import pytest

from caos.boundary_text import BoundaryText
from caos.deliverable.canonical import payload_bytes
from caos.deliverable.filing import Receipt, receipt_bytes
from caos.digest import canonical_digest, canonical_json
from caos.evidence.citations import AnchoredCitation
from caos.evidence.extract import ExtractorIdentity
from caos.evidence.ingest import Document
from caos.methodology.handoff import (
    CanonicalRecord,
    HostIdentity,
    LineageRef,
    Projections,
    record_bytes,
)
from caos.qualification.matrix import (
    ExpectedCitation,
    QualificationCase,
    QualificationSet,
    qualification_set_digest,
)
from caos.qualification.store import Evidence
from caos.qualification.store import _digest as performed_digest
from caos.store.audit import digest_of
from caos.store.commands import request_digest
from caos.store.run_inputs import _research

# Non-ASCII where `ensure_ascii` would show, and money as a decimal string,
# which is how every money path on the wire is written.
FIXTURE: dict[str, Any] = {
    "issuer": "Société Générale",
    "amount": "€1,240.0m",
    "ratio": "4.2x",
    "nested": {"zeta": None, "alpha": True, "naïve": [1, 2, "straße"]},
}


def _uuid(digit: str) -> UUID:
    return UUID(f"{digit * 8}-{digit * 4}-{digit * 4}-{digit * 4}-{digit * 12}")


def _identity() -> ExtractorIdentity:
    return ExtractorIdentity(
        name="caos.pdfminer",
        version="v2",
        config={"word_margin": 0.1, "crop_policy": "drop-outside", "société": True},
    )


def _record() -> CanonicalRecord:
    return CanonicalRecord(
        artifact_sha256="a" * 64,
        adapter_version="canonical-markdown-v3",
        build_id="build-1",
        manifest_sha256="b" * 64,
        authority_bundle_sha256="c" * 64,
        authority_digest="d" * 64,
        delivered_authority_digest="e" * 64,
        identity=HostIdentity(
            run_id=str(_uuid("1")),
            profile_id="LITE_CREDIT_22",
            selection_id="LITE_EARNINGS_UPDATE",
            route_node_id="CP-0",
            module_id="CP-0",
            module_name="Source Readiness",
            issuer_id="issuer-1",
            issuer_name="Société Générale",
            reporting_period="FY26",
            analysis_date="2026-09-17",
            ordinal=1,
            authority_bundle_sha256="c" * 64,
            upstream=(),
        ),
        lineage=(
            LineageRef(
                route_node_id="CP-0",
                module_id="CP-0",
                artifact_sha256="f" * 64,
                record_sha256="0" * 64,
            ),
        ),
        projections=Projections(
            module_id="CP-0",
            qa_status="Passed",
            committee_status="Committee Ready",
            confidence_score=93,
            confidence_band="HIGH",
            limitation_flags=("SOURCE_LIMITED_NOT_COMMITTEE_READY",),
            validation_warnings=(),
            downstream_consumers=("CP-5",),
            readiness=(("CP-5", "READY"),),
            blockers=(),
            decision_scope="SCREENING_ONLY",
        ),
        citations=(
            AnchoredCitation(
                document_sha256="9" * 64,
                page=4,
                matched_text="Société Générale €1,240.0m",
                bboxes=(),
            ),
        ),
    )


def _receipt() -> Receipt:
    return Receipt(
        case_id=_uuid("1"),
        run_id=_uuid("2"),
        revision_id=_uuid("3"),
        payload_sha256="a" * 64,
        signed_by=_uuid("4"),
        frozen_by=_uuid("5"),
        filed_by=_uuid("6"),
        renderer_sha256="b" * 64,
        filed_event_sha256="c" * 64,
    )


def _qualification_set() -> QualificationSet:
    return QualificationSet(
        cases=(
            QualificationCase(
                label="Société Générale FY26",
                documents=(
                    Document(
                        filename=BoundaryText.of("société.txt"),
                        data="€1,240.0m".encode(),
                    ),
                ),
                profile_id="LITE_CREDIT_22",
                selection_id="LITE_EARNINGS_UPDATE",
                expects=(
                    ExpectedCitation(
                        module_id="CP-5",
                        document_sha256="9" * 64,
                        matched_text="Société Générale €1,240.0m",
                    ),
                ),
            ),
        )
    )


def _hex(value: bytes | str) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return sha256(raw).hexdigest()


# Every site this task touched, reduced to one hex string. The converted sites
# come first; the ones that only gained `allow_nan=False` follow.
# `caos/calculators/cash_flow.py` is deliberately absent: it is byte-pinned by
# `methodology/skills/HOST_INTEGRITY_v1.json`, so it was left exactly as it was.
DIGESTS: dict[str, Callable[[], str]] = {
    "digest.canonical_json": lambda: _hex(canonical_json(FIXTURE)),
    "digest.canonical_digest": lambda: canonical_digest(FIXTURE),
    "evidence.extract.ExtractorIdentity.canonical": lambda: _hex(
        _identity().canonical()
    ),
    "store.run_inputs._research": lambda: _hex(str(_research(FIXTURE))),
    "store.commands.request_digest": lambda: request_digest(
        "admit",
        case_id=_uuid("1"),
        run_id=None,
        gate=None,
        body=FIXTURE,
    ),
    "methodology.handoff.record_bytes": lambda: _hex(record_bytes(_record())),
    "store.audit.digest_of": lambda: digest_of(FIXTURE),
    "deliverable.canonical.payload_bytes": lambda: _hex(payload_bytes(FIXTURE)),
    "deliverable.filing.receipt_bytes": lambda: _hex(receipt_bytes(_receipt())),
    "qualification.matrix.qualification_set_digest": lambda: qualification_set_digest(
        _qualification_set()
    ),
    "qualification.store.Evidence.sha256": lambda: Evidence(
        qualification_set_sha256="a" * 64,
        performed_sha256="b" * 64,
        build_id="build-1",
        adapter_version="canonical-markdown-v3",
        provider="openrouter/google-ai-studio/high/65536",
        model="google/gemini-3.8-flash",
    ).sha256,
    "qualification.store._digest": lambda: performed_digest(FIXTURE),
}

# Computed by running each callable at b194943, the parent of this task's first
# commit. A value that moves is a stored digest that stops verifying.
GOLDEN: dict[str, str] = {
    "deliverable.canonical.payload_bytes": (
        "44a2913914e4e55fe847ce3f3b947cc8a9031ebda4365f3289cd92adc181ff6b"
    ),
    "deliverable.filing.receipt_bytes": (
        "d544b9997f407139cdcc35090f239d925d288d8f16dce29bfc076d85977e805e"
    ),
    "digest.canonical_digest": (
        "44a2913914e4e55fe847ce3f3b947cc8a9031ebda4365f3289cd92adc181ff6b"
    ),
    "digest.canonical_json": (
        "44a2913914e4e55fe847ce3f3b947cc8a9031ebda4365f3289cd92adc181ff6b"
    ),
    "evidence.extract.ExtractorIdentity.canonical": (
        "1476b17d2f2daf763d0d33a4ec2c4e8401fbbe46f82f59060ac1d9db60b50a8d"
    ),
    "methodology.handoff.record_bytes": (
        "f72a09d1d7a4f36bb65a112f576e9dc7d3165c0c9e56b83c9b6bf982ef682fb4"
    ),
    "qualification.matrix.qualification_set_digest": (
        "1e39e8c2fd0b203154e46c02044080f854b3b0da4a772e908c3b2ed19c494b0e"
    ),
    "qualification.store.Evidence.sha256": (
        "c52589fbbda4ba55adc96c48d971eabf29e15a2af3db58ab2bf6c437362b8cc4"
    ),
    "qualification.store._digest": (
        "8befb6d6b5297dfe0429d0017cebc74121485e3df24e1276846ad4bdfcbc5e83"
    ),
    "store.audit.digest_of": (
        "8befb6d6b5297dfe0429d0017cebc74121485e3df24e1276846ad4bdfcbc5e83"
    ),
    "store.commands.request_digest": (
        "11d67b0ea862c32d7dd668df8fccfdb593f36474a8a541c73871c45569e998ef"
    ),
    "store.run_inputs._research": (
        "44a2913914e4e55fe847ce3f3b947cc8a9031ebda4365f3289cd92adc181ff6b"
    ),
}


@pytest.mark.parametrize("name", sorted(DIGESTS))
def test_every_existing_digest_is_byte_identical_after_the_move(name: str) -> None:
    assert DIGESTS[name]() == GOLDEN[name], name


@pytest.mark.parametrize(
    "serialise",
    [payload_bytes, digest_of, performed_digest, canonical_json],
    ids=["payload_bytes", "audit.digest_of", "qualification._digest", "canonical_json"],
)
def test_no_digested_payload_emits_nan(serialise: Callable[[Any], object]) -> None:
    """`NaN` is not JSON. Before this task three of these four wrote it into the
    bytes they then hashed, so the digest named a document no reader could parse."""
    with pytest.raises(ValueError):
        serialise({"x": float("nan")})


def test_a_command_receipt_never_digests_nan() -> None:
    with pytest.raises(ValueError):
        request_digest("admit", case_id=None, run_id=None, gate=None, body=float("nan"))


def test_the_two_flag_families_stay_different() -> None:
    """`ensure_ascii` is why the escaping sites were not folded into the helper."""
    assert "Société" in canonical_json(FIXTURE)
    assert digest_of(FIXTURE) != canonical_digest(FIXTURE)


def test_the_shared_helper_is_the_flag_set_the_converted_sites_had() -> None:
    assert canonical_json(FIXTURE) == json.dumps(
        FIXTURE,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
