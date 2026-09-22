"""Slice 3.4a: the vendor-derived realistic LITE fixture builder validates.

Proves `tests/lite_route_fixtures.py` before any runtime slice depends on it:
each module's realistic handoff is a conforming handoff for its own identity
(the same `validate_markdown` every real run uses), CP-L10's topic set is the
vendor's own -- not retyped here -- the disclosed leverage conflict is byte-
identical wherever it is carried, every wire body fits the completion cap, and
`Restricted` keeps its limitation flags.
"""

from __future__ import annotations

import json
from uuid import uuid4

from canonical_fixtures import (
    CATALOG,
    CONTRACT,
    PINNED,
    QUOTE,
    identity,
    skill,
    upstream_ref,
)
from lite_route_fixtures import (
    CONFLICT_TEXT,
    LiteHandoffKnobs,
    RealisticLiteCompletions,
    canonical_topic_ids,
    cp5_t51_rows,
    cp5_t53_rows,
    cp_l10_topic_rows,
    policy_disposition_values,
    policy_evidence_status_values,
    policy_materiality_values,
    realistic_handoff_markdown,
)
from lite_route_fixtures import _yaml as _frontmatter_yaml

from caos.methodology.handoff import invocation_fields, validate_markdown
from caos.provider import MAX_COMPLETION_TOKENS


def _cp0_markdown(*, readiness: dict[str, str] | None = None) -> bytes:
    return realistic_handoff_markdown(
        identity("CP-0"), LiteHandoffKnobs(readiness=readiness)
    )


def _cp_l10_markdown(*, cp0_markdown: bytes, qa_status: str = "Passed") -> bytes:
    upstream = (upstream_ref(identity("CP-0"), cp0_markdown),)
    return realistic_handoff_markdown(
        identity("CP-L10", upstream=upstream), LiteHandoffKnobs(qa_status=qa_status)
    )


def _cp5_markdown(
    *, cp0_markdown: bytes, cp_l10_markdown: bytes, qa_status: str = "Passed"
) -> bytes:
    upstream = (
        upstream_ref(identity("CP-0"), cp0_markdown),
        upstream_ref(identity("CP-L10"), cp_l10_markdown),
    )
    return realistic_handoff_markdown(
        identity("CP-5", upstream=upstream), LiteHandoffKnobs(qa_status=qa_status)
    )


def _built() -> tuple[bytes, bytes, bytes]:
    cp0 = _cp0_markdown()
    cp_l10 = _cp_l10_markdown(cp0_markdown=cp0)
    cp5 = _cp5_markdown(cp0_markdown=cp0, cp_l10_markdown=cp_l10)
    return cp0, cp_l10, cp5


def test_realistic_cp0_handoff_validates_with_pinned_readiness() -> None:
    cp0 = _cp0_markdown()
    projections = validate_markdown(
        CONTRACT,
        CATALOG,
        skill("CP-0"),
        cp0,
        identity=identity("CP-0"),
        gate_expects=PINNED,
    )
    assert projections.module_id == "CP-0"
    assert projections.qa_status == "Passed"


def test_realistic_cp_l10_handoff_validates() -> None:
    cp0, cp_l10, _cp5 = _built()
    ident = identity("CP-L10", upstream=(upstream_ref(identity("CP-0"), cp0),))
    projections = validate_markdown(
        CONTRACT,
        CATALOG,
        skill("CP-L10"),
        cp_l10,
        identity=ident,
        gate_expects=frozenset(),
    )
    assert projections.module_id == "CP-L10"
    assert projections.qa_status == "Passed"


def test_realistic_cp5_handoff_validates() -> None:
    cp0, cp_l10, cp5 = _built()
    ident = identity(
        "CP-5",
        upstream=(
            upstream_ref(identity("CP-0"), cp0),
            upstream_ref(identity("CP-L10"), cp_l10),
        ),
    )
    projections = validate_markdown(
        CONTRACT, CATALOG, skill("CP-5"), cp5, identity=ident, gate_expects=frozenset()
    )
    assert projections.module_id == "CP-5"
    assert projections.qa_status == "Passed"


def test_cp_l10_topic_ids_are_the_vendors_own_canonical_set() -> None:
    topics = canonical_topic_ids()
    assert topics == (
        "SOURCE_BASIS",
        "EARNINGS_MARGIN_CHANGE",
        "CASH_CONVERSION",
        "LEVERAGE_COVERAGE",
        "LIQUIDITY_MATURITIES",
        "KPI_COMPARABILITY",
    )
    # cp_l10_topic_rows emits exactly one row per canonical topic, in order.
    rows = cp_l10_topic_rows()
    assert [row[0] for row in rows] == list(topics)


def test_cp_l10_topic_rows_use_only_policy_valid_values() -> None:
    materiality = set(policy_materiality_values())
    evidence_status = set(policy_evidence_status_values())
    disposition = set(policy_disposition_values())
    rows = cp_l10_topic_rows()
    for row in rows:
        mat, status, disp = row[3], row[4], row[5]
        assert mat in materiality, mat
        assert status in evidence_status, status
        assert disp in disposition, disp


def test_exactly_one_high_topic_is_conflicted_and_gap_only() -> None:
    rows = cp_l10_topic_rows()
    flagged = [
        row for row in rows if row[3] == "HIGH" and row[4] in {"MISSING", "CONFLICTED"}
    ]
    assert len(flagged) == 1, rows
    materiality, status, disposition = flagged[0][3], flagged[0][4], flagged[0][5]
    assert materiality == "HIGH"
    assert status == "CONFLICTED"
    assert disposition == "GAP_ONLY"
    assert CONFLICT_TEXT in flagged[0][7]


def test_cp5_t51_names_each_upstream_by_expected_filename_and_run_id() -> None:
    rows = cp5_t51_rows()
    modules = [row[0] for row in rows]
    assert modules == ["CP-0", "CP-L10"]
    for row in rows:
        assert row[0] in row[1]
        assert ".md" in row[1]


def test_cp5_t53_carries_the_cp_l10_conflict_unresolved() -> None:
    rows = cp5_t53_rows()
    assert len(rows) == 1
    module, source_conflict = rows[0][1], rows[0][4]
    assert module == "CP-L10"
    assert source_conflict == CONFLICT_TEXT


def test_disclosed_conflict_is_byte_identical_in_cp_l10_and_cp5() -> None:
    _cp0, cp_l10, cp5 = _built()
    assert CONFLICT_TEXT.encode() in cp_l10
    assert CONFLICT_TEXT.encode() in cp5
    # Every occurrence in each artifact is the exact same bytes -- there is
    # only one conflict text, never a paraphrase, in either handoff.
    for markdown in (cp_l10, cp5):
        text = markdown.decode()
        assert text.count(CONFLICT_TEXT) >= 1


def test_realistic_fixture_handoffs_fit_the_completion_cap() -> None:
    cp0, cp_l10, cp5 = _built()
    for module_id, markdown in (("CP-0", cp0), ("CP-L10", cp_l10), ("CP-5", cp5)):
        citation = {"source_id": "0" * 32, "page": 1, "matched_text": QUOTE}
        wire = json.dumps(
            {"canonical_markdown": markdown.decode("utf-8"), "citations": [citation]}
        ).encode("utf-8")
        assert len(wire) <= MAX_COMPLETION_TOKENS, (module_id, len(wire))


def test_restricted_cp_l10_keeps_limitation_flags() -> None:
    cp0 = _cp0_markdown()
    cp_l10 = _cp_l10_markdown(cp0_markdown=cp0, qa_status="Restricted")
    ident = identity("CP-L10", upstream=(upstream_ref(identity("CP-0"), cp0),))
    projections = validate_markdown(
        CONTRACT,
        CATALOG,
        skill("CP-L10"),
        cp_l10,
        identity=ident,
        gate_expects=frozenset(),
    )
    assert projections.qa_status == "Restricted"
    assert projections.limitation_flags


def test_restricted_cp5_over_restricted_cp_l10_keeps_limitation_flags() -> None:
    cp0 = _cp0_markdown()
    cp_l10 = _cp_l10_markdown(cp0_markdown=cp0, qa_status="Restricted")
    cp5 = _cp5_markdown(
        cp0_markdown=cp0, cp_l10_markdown=cp_l10, qa_status="Restricted"
    )
    ident = identity(
        "CP-5",
        upstream=(
            upstream_ref(identity("CP-0"), cp0),
            upstream_ref(identity("CP-L10"), cp_l10),
        ),
    )
    projections = validate_markdown(
        CONTRACT,
        CATALOG,
        skill("CP-5"),
        cp5,
        identity=ident,
        gate_expects=frozenset(),
    )
    assert projections.qa_status == "Restricted"
    assert projections.limitation_flags


def test_provider_answers_realistic_handoffs_from_prompt_front_matter() -> None:
    """`RealisticLiteCompletions` mirrors `CanonicalCompletions`'s shape."""
    provider = RealisticLiteCompletions(source_id=uuid4())
    cp0 = _cp0_markdown()
    lite = identity("CP-L10", upstream=(upstream_ref(identity("CP-0"), cp0),))
    host = invocation_fields(CONTRACT, lite)
    prompt = (
        "--- HOST-OWNED FRONT MATTER 0123456789abcdef (copy exactly) ---\n"
        + _frontmatter_yaml(host)
        + "\n--- END HOST-OWNED FRONT MATTER 0123456789abcdef ---\n"
    )
    completion = provider.complete(prompt, json_object=True)
    assert completion.content is not None
    parsed = json.loads(completion.content)
    assert "canonical_markdown" in parsed
    assert "citations" in parsed
    assert provider.prompts == [prompt]
    assert len(provider.answers) == 1
    projections = validate_markdown(
        CONTRACT,
        CATALOG,
        skill("CP-L10"),
        provider.answers[0],
        identity=lite,
        gate_expects=frozenset(),
    )
    assert projections.module_id == "CP-L10"
