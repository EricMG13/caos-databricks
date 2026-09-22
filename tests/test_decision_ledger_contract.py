"""CP-8's canonical contract, on the one pathway that carries it.

`LITE_CREDIT_22 / LITE_DECISION_LEDGER` is CP-0 -> CP-8 and nothing else, so
CP-8's contract tests run over that route rather than parametrised beside the
RELATIVE_VALUE owners (`tests/test_owner_contracts.py`): the same five
boundaries. The three that need no run are here -- a missing register, a wrong
upstream, a restricted handoff keeping its limitations; the two that do -- a
validated, identified, projected and anchored acceptance, and an unanchored
quote -- run the route and live beside it in
`tests/test_lite_decision_ledger_route.py`.

**What a fixture can fake and what a key can pin (Task 9.3 step 1).** CP-8's
eight registers are all critical, so each must be filled, and the fixture
fills them from the authored decision memo and outcome extract in
`canonical_route_fixtures.LEDGER_PACK`. Three of them are judgement a fixture
can only *assert*, never prove: T7.5's attribution label and process verdict,
T7.6's calibration register (pattern-gated to three decisions, so on one
decision it can only say there is no pattern) and T7.7's roll-up. A key over
those would measure the key author's judgement against the model's. What a
key *can* pin is what a document settles: T7.1's decision date and T7.2's
expectations are read off the T0 record, and T7.3's realised values are read
off the T1 document, so a module that reconstructs its thesis after the fact
or misreads an outcome misses a key; T7.4's `Expected` cells must equal what
T7.2 recorded. That is the split `qualification/ccl-fy2025-decision-ledger/`
keys by.

Every provider is deterministic; no live call is made.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from canonical_fixtures import CATALOG, CONTRACT, skill, upstream_ref
from canonical_route_fixtures import (
    LEDGER_PACK,
    LEDGER_QUOTES,
    LEDGER_ROUTE,
    LIMITATION,
    HandoffKnobs,
    ledger_identity,
    ledger_markdown,
)

from caos.methodology.handoff import (
    HostIdentity,
    invocation_fields,
    validate_markdown,
)
from caos.refusals import Refusal, RefusalCode

MODULE = "CP-8"


def _identity() -> HostIdentity:
    refs = tuple(
        upstream_ref(
            ledger_identity(e.source), ledger_markdown(ledger_identity(e.source))
        )
        for e in LEDGER_ROUTE.edges
        if e.target == MODULE
    )
    return ledger_identity(MODULE, refs)


def test_the_cp8_fixture_meets_every_vendor_register() -> None:
    """Both handoffs on the route pass the vendor's own validator and
    completeness check, and every quote they cite is whole tokens of the pack."""
    for module in ("CP-0", MODULE):
        markdown = ledger_markdown(ledger_identity(module)).decode()
        assert CONTRACT.validate_handoff.validate_text(markdown).exit_code == 0
        violations = CONTRACT.completeness_check.check(
            skill(module).decode(), markdown, module
        )[0]
        assert violations == []
        for document, quote in LEDGER_QUOTES[module]:
            assert quote in markdown
            assert quote.encode() in LEDGER_PACK[document]


@pytest.mark.parametrize(
    "register",
    ["T7.1", "T7.2", "T7.3", "T7.4", "T7.5", "T7.6", "T7.7", "T7.8"],
)
def test_cp8_contract_refuses_a_missing_register(register: str) -> None:
    """Every one of the eight registers is required, not only the first."""
    assert (
        register
        in CONTRACT.completeness_check.load_contract(skill(MODULE).decode(), MODULE)[
            "registers"
        ]
    )
    ident = _identity()
    with pytest.raises(Refusal) as refused:
        validate_markdown(
            CONTRACT,
            CATALOG,
            skill(MODULE),
            ledger_markdown(ident, HandoffKnobs(omit_register=register)),
            identity=ident,
            gate_expects=frozenset(),
        )
    assert refused.value.code is RefusalCode.HANDOFF_INCOMPLETE


def test_cp8_contract_refuses_a_wrong_upstream() -> None:
    ident = _identity()
    wrong = replace(
        ident,
        upstream=(replace(ident.upstream[0], sha256="f" * 64), *ident.upstream[1:]),
    )
    with pytest.raises(Refusal) as refused:
        validate_markdown(
            CONTRACT,
            CATALOG,
            skill(MODULE),
            ledger_markdown(
                ident, HandoffKnobs(fields=invocation_fields(CONTRACT, wrong))
            ),
            identity=ident,
            gate_expects=frozenset(),
        )
    assert refused.value.code is RefusalCode.HANDOFF_IDENTITY_MISMATCH


def test_a_restricted_cp8_retains_its_limitations() -> None:
    ident = _identity()
    projection = validate_markdown(
        CONTRACT,
        CATALOG,
        skill(MODULE),
        ledger_markdown(ident, HandoffKnobs(qa_status="Restricted")),
        identity=ident,
        gate_expects=frozenset(),
    )
    assert projection.qa_status == "Restricted"
    assert projection.limitation_flags == (LIMITATION,)
