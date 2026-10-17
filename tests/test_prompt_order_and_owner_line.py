"""Two host prompt facts of the D152 R5 and R8 re-pin.

N143(c): CP-5 under LITE_FULL_CREDIT_SCREEN is told the owner-restriction rule
on its first attempt, not first on its retry. N166: CP-0's source-preparation
members are listed in the evidence's own order (D113).
"""

from __future__ import annotations

import re
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from canonical_fixtures import (
    BUNDLE,
    CATALOG,
    CONTRACT,
    handoff_markdown,
    identity,
    upstream_ref,
)
from test_handoff_invocation import LITE_ROUTE, _delivered, _tag

from caos.boundary_text import BoundaryText
from caos.graph.route import ResolvedRoute, resolve_route
from caos.icm import prompt_block
from caos.methodology.bundle import delivered_authority
from caos.methodology.executor import Delivery
from caos.methodology.handoff import HostIdentity, UpstreamRef
from caos.methodology.invocation import build_handoff_prompt
from caos.store.source_sets import SourceSet, SourceSetMember

SCREEN = "LITE_FULL_CREDIT_SCREEN"


def _on(
    route: ResolvedRoute, module_id: str, upstream: tuple[UpstreamRef, ...] = ()
) -> HostIdentity:
    """The host identity of `module_id` on `route`."""
    node = next(n for n in route.nodes if n.module_id == module_id)
    return replace(
        identity(module_id, upstream),
        profile_id=route.profile_id,
        selection_id=route.selection_id,
        route_node_id=node.route_node_id,
    )


def _owner_prompt(selection: str, module_id: str = "CP-5") -> str:
    """`module_id`'s first prompt over a Restricted CP-0 and a CP-L10 that
    carries one flag and two warnings."""
    route = resolve_route(CATALOG, "LITE_CREDIT_22", selection)
    first = _on(route, "CP-0")
    gate = handoff_markdown(
        first,
        authored={"qa_status": "Restricted", "limitation_flags": ["FLAG_ONE"]},
    )
    gate_ref = upstream_ref(first, gate)
    second = _on(route, "CP-L10", (gate_ref,))
    screen = handoff_markdown(
        second,
        authored={
            "limitation_flags": ["FLAG_ONE"],
            "validation_warnings": ["WARN_A", "WARN_B"],
        },
    )
    upstream = ((gate_ref, gate), (upstream_ref(second, screen), screen))
    return _built(route, module_id, upstream if module_id == "CP-5" else upstream[:1])


def _built(
    route: ResolvedRoute,
    module_id: str,
    upstream: tuple[tuple[UpstreamRef, bytes], ...],
) -> str:
    refs = tuple(ref for ref, _ in upstream)
    of = _on(route, module_id, refs)
    return build_handoff_prompt(
        CONTRACT,
        identity=of,
        authority=delivered_authority(BUNDLE, module_id),
        catalog=CATALOG,
        delivered=_delivered(),
        upstream=upstream,
        upstream_citations={ref.route_node_id: () for ref in refs},
        route=route,
    )


def test_cp5_first_attempt_lists_the_upstream_flags_and_warnings_it_must_carry() -> (
    None
):
    prompt = _owner_prompt(SCREEN)
    tag = _tag(prompt)
    start = prompt.index(f"--- HOST OWNER RESTRICTIONS {tag} ")
    end = prompt.index(f"--- END HOST OWNER RESTRICTIONS {tag} ---")
    section = prompt[start:end]
    assert "qa_status must be Restricted while an upstream handoff's is" in section
    assert "Restricted: CP-0" in section
    assert "limitation_flags: «FLAG_ONE» (from CP-0, CP-L10)" in section
    assert "validation_warnings: «WARN_A» (from CP-L10), «WARN_B» (from CP-L10)" in (
        section
    )
    assert prompt.index("--- UPSTREAM CITATION REGISTER") < start
    assert end < prompt.index(f"--- FINAL RESPONSE CHECK {tag} ---")


@pytest.mark.parametrize(
    ("selection", "module_id"),
    [("LITE_EARNINGS_UPDATE", "CP-5"), (SCREEN, "CP-L10")],
)
def test_the_owner_section_is_cp5_under_the_credit_screen_alone(
    selection: str, module_id: str
) -> None:
    assert "HOST OWNER RESTRICTIONS" not in _owner_prompt(selection, module_id)


def test_cp5_with_nothing_to_carry_gets_no_owner_section() -> None:
    route = resolve_route(CATALOG, "LITE_CREDIT_22", SCREEN)
    gate = handoff_markdown(_on(route, "CP-0"))
    prompt = _built(route, "CP-5", ((upstream_ref(_on(route, "CP-0"), gate), gate),))
    assert "HOST OWNER RESTRICTIONS" not in prompt


def _member(source: UUID, name: str, digest: str) -> SourceSetMember:
    return SourceSetMember(
        source,
        digest * 64,
        name,
        "2026-09-15T00:00:00+00:00",
        '{"config":{},"name":"caos.test","version":"1"}',
        "e" * 64,
        "f" * 64,
    )


def test_cp0_source_preparation_lists_members_in_the_evidence_order() -> None:
    """The evidence is ordered by filename (bytewise), document digest, then
    source_id (D113); the members follow it, not `load_source_set`'s source_id
    order (N166)."""
    ids = sorted(uuid4() for _ in range(4))
    members = (
        _member(ids[0], "z.pdf", "1"),
        _member(ids[1], "Z.pdf", "1"),
        _member(ids[2], "a.pdf", "2"),
        _member(ids[3], "a.pdf", "1"),
    )
    evidence_order = [ids[1], ids[3], ids[2], ids[0]]
    delivered = [
        Delivery(source, f"{n:06d}", 1, BoundaryText.of(f"Line {n}."))
        for n, source in enumerate(evidence_order, start=1)
    ]
    prompt = build_handoff_prompt(
        CONTRACT,
        identity=identity("CP-0"),
        authority=delivered_authority(BUNDLE, "CP-0"),
        catalog=CATALOG,
        delivered=delivered,
        upstream=(),
        upstream_citations={},
        route=LITE_ROUTE,
        source_set=SourceSet(uuid4(), 1, "b" * 64, members),
    )
    section = prompt[prompt.index(f"--- HOST SOURCE PREPARATION {_tag(prompt)}") :]
    found = re.findall(r'"source_id": "([0-9a-f-]{36})"', section)
    assert [UUID(item) for item in found] == evidence_order


def test_the_final_check_bounds_every_citation_marker_by_the_list() -> None:
    """N217: a marker above the highest listed citation names none and
    refuses the answer; the final check says so before the answer is written."""
    block = " ".join(prompt_block("final_check").split())
    assert "A marker that names no citation refuses the answer" in block
    assert "No marker may be numbered above the last citation in your list" in block


def test_the_repair_block_does_not_call_the_carried_answer_the_previous_one() -> None:
    """N218(7): under F649 the carried answer may be from an earlier attempt."""
    block = " ".join(prompt_block("validator_repair").split())
    assert "Your previous answer" not in block
    assert "An earlier answer of yours was refused" in block
    assert "That answer, as the host received it" in block


def test_an_unreadable_upstream_handoff_leaves_the_owner_section_out() -> None:
    """The section is guidance: a handoff the vendor parser cannot read shows
    no half-read list, and acceptance is unchanged."""
    route = resolve_route(CATALOG, "LITE_CREDIT_22", SCREEN)
    first = _on(route, "CP-0")
    good = handoff_markdown(first, authored={"limitation_flags": ["FLAG_ONE"]})
    junk = b"not a handoff"
    second = _on(route, "CP-L10", (upstream_ref(first, good),))
    prompt = _built(
        route,
        "CP-5",
        ((upstream_ref(first, good), good), (upstream_ref(second, junk), junk)),
    )
    assert "HOST OWNER RESTRICTIONS" not in prompt
