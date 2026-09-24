"""The vendored bundle is the authority, and it is the one the spec was written
against.

Invariant 4: the bundle is the methodology authority, integrity checked on the
bytes. This is the pin -- every fact `docs/DECISIONS.md` §2 and §5 rest on,
asserted against the bytes in `vendor/`. A bundle swap that changes any of them
fails here rather than silently changing every route the system runs.

Verification at *use* is Phase 5. This is verification at rest: the vendored
copy is byte-identical to the manifest it shipped with.
"""

from __future__ import annotations

import collections
import copy
import dataclasses
import hashlib
import json
import shutil
import types
from pathlib import Path

import pytest
from canonical_fixtures import CONTRACT, handoff_markdown, identity, upstream_ref
from lite_route_fixtures import realistic_handoff_markdown

from caos.graph import route
from caos.refusals import Refusal, RefusalCode

VENDOR = Path(__file__).resolve().parents[1] / "vendor"
BUNDLE = VENDOR / "deploy-v"


def clear_vendor_bytecode(root: Path) -> int:
    """Remove every `__pycache__` under `root` that holds only `.pyc` files,
    returning how many; refuse, removing nothing, if one holds anything else.

    No vendored file is bytecode (`git ls-files vendor` carries none), so this
    touches only what an interpreter wrote beside the vendored bytes."""
    caches = sorted(root.rglob("__pycache__"), reverse=True)
    for cache in caches:
        foreign = [p for p in cache.rglob("*") if p.is_file() and p.suffix != ".pyc"]
        assert not foreign, f"not bytecode, not removed: {foreign}"
    for cache in caches:
        shutil.rmtree(cache, ignore_errors=True)
    return len(caches)


CATALOG = (
    BUNDLE / "skills/cp-os-credit-os/references/CREDIT_OS_V_MODULE_CATALOG_v2.json"
)

# docs/DECISIONS.md §96 and §98 together moved the §13 pin last (after §61,
# §63, §92). A run pinned to one build never executes under another.
BUILD_ID = "820dfc7c624af6ef920eefff9e809c9cb41c83be230e374e481a814e7953ac8a"


def _load(path: Path) -> dict[str, object]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def catalog() -> dict[str, object]:
    return _load(CATALOG)


@pytest.fixture(scope="module")
def integrity() -> dict[str, object]:
    return _load(BUNDLE / "DEPLOY_V_INTEGRITY_v1.json")


def test_the_vendored_build_is_the_pinned_one(integrity: dict[str, object]) -> None:
    assert integrity["build_id"] == BUILD_ID


def test_every_vendored_byte_matches_the_manifest(integrity: dict[str, object]) -> None:
    roots = integrity["root_file_hashes"]
    skills = integrity["skills"]
    assert isinstance(roots, dict)
    assert isinstance(skills, list)

    expected: dict[Path, str] = {
        BUNDLE / name: str(entry["sha256"]) for name, entry in roots.items()
    }
    for skill in skills:
        folder = BUNDLE / "skills" / str(skill["folder_slug"])
        for name, entry in dict(skill["relative_file_hashes"]).items():
            expected[folder / name] = str(entry["sha256"])

    assert len(expected) > 300, "a manifest covering almost nothing is not a check"
    wrong = [
        path.relative_to(BUNDLE)
        for path, digest in expected.items()
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest
    ]
    assert wrong == [], f"vendored copy differs from its manifest: {wrong[:5]}"


def test_the_typed_edges_are_where_the_spec_says(catalog: dict[str, object]) -> None:
    profiles = catalog["profiles"]
    assert isinstance(profiles, dict)
    assert set(profiles) == {"FULL_CREDIT_32", "LITE_CREDIT_22"}

    counted = collections.Counter(
        edge["type"] for edge in profiles["FULL_CREDIT_32"]["edges"]
    )
    # docs/DECISIONS.md §2: the numbers the predecessor's defect was measured in.
    assert counted == {"REQUIRED": 44, "OPTIONAL": 25, "ADVISORY": 22, "QA_GATE": 1}


def test_navigation_dependencies_is_the_untyped_list_we_must_not_read(
    catalog: dict[str, object],
) -> None:
    navigation = catalog["navigation"]
    assert isinstance(navigation, dict)
    pairs = navigation["dependencies"]
    assert isinstance(pairs, list)
    assert len(pairs) == 97
    # It carries no type at all -- which is why reading it enforced 47 soft
    # edges as mandatory and made the one QA_GATE not gate.
    assert all("type" not in pair for pair in pairs)


def test_the_catalog_carries_eighteen_pathways(catalog: dict[str, object]) -> None:
    profiles = catalog["profiles"]
    assert isinstance(profiles, dict)
    assert sum(len(profile["pathways"]) for profile in profiles.values()) == 18


def test_cp_parse_is_superseded_upstream_and_stage_zero_is_not_runnable(
    catalog: dict[str, object],
) -> None:
    # Both premises of the DECISIONS.md §5 carve-out. If upstream ever stops
    # saying either, the carve-out needs revisiting rather than carrying on.
    superseded = catalog["superseded_module_ids"]
    assert isinstance(superseded, dict)
    assert superseded["CP-PARSE"]["absorbed_by"] == "CP-0"
    preparation = catalog["preparation_stage"]
    assert isinstance(preparation, dict)
    assert preparation == {
        "module_id": "CP-0",
        "phase": "preparation",
        "required_before": "CP-0 readiness phase",
        "runnable": False,
    }


def test_the_catalog_declares_no_conditional_edge(catalog: dict[str, object]) -> None:
    # CONDITIONAL is a live edge type in CONTEXT.md and no edge uses it today,
    # so predicate freezing has nothing to act on. Recorded, not assumed.
    # The census beside this one pins the other four counts and drives the
    # engine's guard; this stays as the one-line pin `docs/PHASE_7_EXIT_
    # EVIDENCE.md` and the ledger cite by name.
    profiles = catalog["profiles"]
    assert isinstance(profiles, dict)
    conditional = [
        edge
        for profile in profiles.values()
        for edge in profile["edges"]
        if edge["type"] == "CONDITIONAL"
    ]
    assert conditional == []


# Counted at this build. CONDITIONAL is absent and is the one type
# `caos/graph/route.py` refuses, because nothing evaluates a predicate.
EDGE_CENSUS = {"REQUIRED": 60, "OPTIONAL": 26, "ADVISORY": 29, "QA_GATE": 1}


def test_the_vendored_catalog_carries_no_edge_this_engine_cannot_evaluate(
    catalog: dict[str, object],
) -> None:
    """The whole typed-edge census, not only the type that matters.

    A bundle pull that moves any of the four counts is visible here rather than
    silently changing every route the system runs, and one that introduces a
    CONDITIONAL edge is refused by `resolve_route` rather than pinned -- which
    the mutated copy below proves against the real catalog, since a hand-built
    profile cannot show that the vendored one would be caught.
    """
    profiles = catalog["profiles"]
    assert isinstance(profiles, dict)
    counted = collections.Counter(
        str(edge["type"]) for profile in profiles.values() for edge in profile["edges"]
    )

    assert dict(counted) == EDGE_CENSUS
    assert counted["CONDITIONAL"] == 0

    # Through the engine, not only the bytes: every pathway of every profile
    # resolves today, and retyping one edge of a profile to CONDITIONAL refuses
    # every pathway of that profile whose nodes carry it.
    resolved = 0
    refused = 0
    for profile_id, profile in profiles.items():
        for selection_id in profile["pathways"]:
            route.resolve_route(catalog, profile_id, selection_id)
            resolved += 1

        mutated = copy.deepcopy(catalog)
        mutated_profile = mutated["profiles"][profile_id]  # type: ignore[index]
        mutated_profile["edges"][0]["type"] = "CONDITIONAL"
        source = str(mutated_profile["edges"][0]["source"])
        target = str(mutated_profile["edges"][0]["target"])
        for selection_id in profile["pathways"]:
            carried = {
                str(node["module_id"])
                for node in profile["pathways"][selection_id]["nodes"]
            }
            if not {source, target} <= carried:
                continue
            with pytest.raises(Refusal) as caught:
                route.resolve_route(mutated, profile_id, selection_id)
            assert caught.value.code is RefusalCode.ROUTE_EDGE_UNSUPPORTED
            refused += 1

    # A census that counted nothing, or a mutation no pathway carried, would
    # read as a clean pass (CLAUDE.md: a scanner that scanned nothing is a
    # failure).
    assert resolved == 18
    assert refused > 0


def test_clearing_vendor_bytecode_removes_only_bytecode(tmp_path: Path) -> None:
    """The vendored tree is shared by every process in this checkout, and any
    one importing a vendor script leaves `__pycache__` beside it; the two tests
    that refuse bytecode clear it first, so they measure this repository's own
    behaviour and not the machine's. Clearing removes bytecode and nothing
    else: a vendored byte is never touched (invariant 4)."""
    tree = tmp_path / "vendor" / "bundle" / "scripts"
    tree.mkdir(parents=True)
    script = tree / "tool.py"
    script.write_text("print(1)\n", encoding="utf-8")
    cache = tree / "__pycache__"
    cache.mkdir()
    (cache / "tool.cpython-314.pyc").write_bytes(b"\x00")
    (tmp_path / "vendor" / "__pycache__").mkdir()

    assert clear_vendor_bytecode(tmp_path / "vendor") == 2
    assert not list((tmp_path / "vendor").rglob("__pycache__"))
    assert script.read_text(encoding="utf-8") == "print(1)\n"

    cache.mkdir()
    (cache / "notes.txt").write_text("not bytecode", encoding="utf-8")
    with pytest.raises(AssertionError, match=r"notes\.txt"):
        clear_vendor_bytecode(tmp_path / "vendor")
    assert (cache / "notes.txt").is_file()


def test_the_bundle_verifies_with_its_own_tool() -> None:
    # A second, independent verifier: the package's own read-only checker must
    # still accept the vendored bytes. `-B` because it refuses a tree that
    # carries bytecode, and cwd is the bundle because it resolves paths there.
    import subprocess
    import sys

    clear_vendor_bytecode(VENDOR)
    result = subprocess.run(
        [sys.executable, "-B", "verify_package.py"],
        cwd=BUNDLE,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]


# `docs/DECISIONS.md` §61: the three places CP-0 reads `CONDITIONAL` from must
# say the same thing -- a source condition, discharged by supplying the source
# and re-running CP-0, never an upstream handoff that has not run yet.
CP0_CONDITIONAL_TEXTS = (
    "skills/cp-0-source-readiness/SKILL.md",
    "skills/cp-0-source-readiness/references/REF_CP-0_STEPS.md",
    "skills/cp-0-source-readiness/references/CP-0__SourceReadiness__payload.schema.txt",
)


@pytest.mark.parametrize("relative", CP0_CONDITIONAL_TEXTS)
def test_cp0_defines_conditional_as_a_source_condition_everywhere_it_is_read(
    relative: str,
) -> None:
    text = (BUNDLE / relative).read_text(encoding="utf-8")
    assert "never a readiness ground" in text, relative
    assert "CP-0 is re-run" in text, relative


# `docs/DECISIONS.md` §98: T8's `Source files to attach` may carry a page range
# beside a filename, and a source the host shows CP-0 as a page map is attached
# by page, never whole. The bundle states both, in the step CP-0 authors T8
# from, so the grammar the host reads is the bundle's and not the host's.
CP0_STEPS = "skills/cp-0-source-readiness/references/REF_CP-0_STEPS.md"


def test_cp0_states_the_page_range_form_and_the_page_map_rule() -> None:
    text = (BUNDLE / CP0_STEPS).read_text(encoding="utf-8")
    step_i = text[text.index('step="I"') : text.index("## CP-MODEL boundary")]
    assert "`<filename> pages <first>-<last>`" in step_i
    assert "`<filename> page <n>`" in step_i
    assert "one range per item" in step_i
    assert "8. A source the host delivers as a page map" in step_i
    assert "never the file alone" in step_i


# `docs/DECISIONS.md` §63: T5B.5 is where CP-5 records what became of a
# calculation, and "not calculable from provided materials" is the answer its
# runbook asks for when the sources carry none. Its two status columns are
# exempt from the placeholder disqualifiers; its seven substantive columns are
# not, so a validator still cannot pass by leaving the work blank.
CP5_SKILL = "skills/cp-5-evidence-trace-validator/SKILL.md"
T5B5_STATUS_COLUMNS = ("Status", "Claim Status")
T5B5_PLACEHOLDER = "Not Calculable from Provided Materials"


def _cp5_handoff() -> str:
    cp0 = realistic_handoff_markdown(identity("CP-0"))
    cp0_ref = upstream_ref(identity("CP-0"), cp0)
    l10 = realistic_handoff_markdown(identity("CP-L10", upstream=(cp0_ref,)))
    upstream = (cp0_ref, upstream_ref(identity("CP-L10"), l10))
    return realistic_handoff_markdown(identity("CP-5", upstream=upstream)).decode()


def _with_t5b5_cell(markdown: str, column: str, value: str) -> str:
    """The fixture's first T5B.5 body row with one cell replaced, by column name."""
    start = markdown.index("#### T5B.5\n")
    lines = markdown[start:].split("\n")
    columns = [cell.strip() for cell in lines[2].strip().strip("|").split("|")]
    cells = [cell.strip() for cell in lines[4].strip().strip("|").split("|")]
    cells[columns.index(column)] = value
    lines[4] = "| " + " | ".join(cells) + " |"
    return markdown[:start] + "\n".join(lines)


def test_cp5_exempts_only_its_status_columns_from_the_disqualifiers() -> None:
    skill = (BUNDLE / CP5_SKILL).read_text(encoding="utf-8")
    rules = CONTRACT.completeness_check.load_contract(skill, "CP-5")
    register = rules["registers"]["T5B.5"]
    assert register["disqualifier_exempt_columns"] == list(T5B5_STATUS_COLUMNS)
    assert register["critical_columns"] == register["columns"]
    assert T5B5_PLACEHOLDER.casefold() in rules["blocklist"]
    substantive = [c for c in register["columns"] if c not in T5B5_STATUS_COLUMNS]
    assert len(substantive) == 7

    handoff = _cp5_handoff()
    check = CONTRACT.completeness_check.check
    assert check(skill, handoff, "CP-5")[0] == []
    for column in T5B5_STATUS_COLUMNS:
        honest = _with_t5b5_cell(handoff, column, T5B5_PLACEHOLDER)
        assert check(skill, honest, "CP-5")[0] == [], column
    for column in substantive:
        blank = _with_t5b5_cell(handoff, column, T5B5_PLACEHOLDER)
        assert check(skill, blank, "CP-5")[0] == [
            f"T5B.5 row 1: critical column '{column}' holds a disqualifying "
            f"placeholder '{T5B5_PLACEHOLDER}'"
        ]


# `docs/DECISIONS.md` §92: the owner's authorised build carrying the six
# 2026-09-17 vendor requests. Each test below drives the bundle's own code
# through the verified contract, so the host still reads and invents nothing.
CANON = "CANON_SHARED.md"
CP0_SKILL = "skills/cp-0-source-readiness/SKILL.md"
L10_SKILL = "skills/cp-l10-financial-change-screen/SKILL.md"
CP3C_SKILL = "skills/cp-3c-refinancing-lme-risk/SKILL.md"
FIXTURE_FLAGS = {
    "INTEGRATION_FIXTURE_ONLY",
    "PRESENTATION_FIXTURE_NOT_CURRENT_GOLDEN",
    "SYNTHETIC_FORWARD_ASSUMPTIONS",
}
THIN_EVIDENCE_FLAG = "SOURCE_LIMITED_NOT_COMMITTEE_READY"


def _t8_table(headers: tuple[str, ...], rows: list[list[str]]) -> str:
    head = "| " + " | ".join(headers) + " |\n| " + " | ".join("---" for _ in headers)
    return head + " |\n" + "".join("| " + " | ".join(r) + " |\n" for r in rows)


def test_the_t8_parser_keeps_the_source_files_column(
    catalog: dict[str, object],
) -> None:
    """Request 2026-09-17-t8-source-files-column: `Recommendation` carries T8's
    fifth column, which the vendor validated for width and then dropped, so a
    per-module evidence demand has one reader -- the bundle's."""
    nav = CONTRACT.navigation
    validated = nav.validate_catalog(catalog)
    rows = nav.parse_t8(
        realistic_handoff_markdown(identity("CP-0")).decode(), validated
    )
    assert {row.source_files_to_attach for row in rows} == {"Source p1"}
    assert {row.module_id for row in rows} == {"CP-L10", "CP-5"}

    legacy = _t8_table(
        nav.LEGACY_HEADERS,
        [
            [
                "1",
                "CP-L10",
                "Run CP-L10",
                "Q3 and Q4 releases",
                "None",
                "READY",
                "Now.",
            ],
            [
                "2",
                "CP-5",
                "Run CP-5",
                "Audited statements",
                "CP-L10",
                "BLOCKED",
                "Gap.",
            ],
        ],
    )
    parsed = nav.parse_t8("## Analysis\n\n" + legacy, validated)
    assert [row.source_files_to_attach for row in parsed] == [
        "Q3 and Q4 releases",
        "Audited statements",
    ]
    assert [row.readiness for row in parsed] == ["READY", "BLOCKED"]


def test_the_t8_parser_accepts_the_cp_dr_row_cp0s_contract_permits(
    catalog: dict[str, object],
) -> None:
    """Request 2026-09-18-t8-cp-dr-row (§96): CP-DR is navigable with no layer,
    which `validate_catalog` admits and CP-0's T8 contract lists; `parse_t8`
    now reads its row instead of refusing it, so a pathway whose only consumer
    is CP-DR has a T8 the bundle accepts. A layerless module that is not CP-DR
    is still refused, and so is an empty T8."""
    nav = CONTRACT.navigation
    validated = nav.validate_catalog(catalog)
    assert validated.modules["CP-DR"].navigable
    assert validated.modules["CP-DR"].layer_id is None
    row = ["1", "CP-DR", "Run CP-DR", "Run CP-DR", "Pack", "Why", "READY", "Now."]
    parsed = nav.parse_t8(
        "## Analysis\n\n" + _t8_table(nav.NEW_HEADERS, [row]), validated
    )
    assert [(r.module_id, r.readiness) for r in parsed] == [("CP-DR", "READY")]
    with pytest.raises(nav.NavigationError, match="no navigable recommendation"):
        nav.parse_t8("## Analysis\n\n" + _t8_table(nav.NEW_HEADERS, []), validated)
    # Any other layerless module is still refused -- by the catalog first, and
    # by the parser if a catalog ever carried one.
    module = validated.modules["CP-L10"]
    bent = dataclasses.replace(
        validated,
        modules=types.MappingProxyType(
            {**validated.modules, "CP-L10": dataclasses.replace(module, layer_id=None)}
        ),
    )
    other = ["1", "CP-L10", "Run CP-L10", "Run CP-L10", "Pack", "Why", "READY", "Now."]
    with pytest.raises(nav.NavigationError, match="non-navigable module: CP-L10"):
        nav.parse_t8("## Analysis\n\n" + _t8_table(nav.NEW_HEADERS, [other]), bent)


def _profiles_with_disqualifiers() -> list[tuple[str, str]]:
    """Every `(SKILL.md, module_id)` whose output profile declares the split."""
    found = []
    for path in sorted(BUNDLE.glob("skills/*/SKILL.md")):
        text = path.read_text(encoding="utf-8")
        for module_id in CONTRACT.completeness_check.profile_bodies(text):
            if module_id is None:
                continue
            rules = CONTRACT.completeness_check.load_contract(text, module_id)
            if rules["fixture_flags"] or rules["evidence_flags"]:
                found.append((str(path.relative_to(BUNDLE)), module_id))
    return found


def test_the_fixture_markers_are_split_from_the_thin_evidence_marker() -> None:
    """Request 2026-09-17-disqualifier-marker-split (§66): a fixture marker is a
    completeness disqualifier and the bundle's checker enforces it; the
    thin-evidence marker is a projected limitation and refuses nothing."""
    declared = _profiles_with_disqualifiers()
    assert len(declared) >= 21, declared
    for relative, module_id in declared:
        rules = CONTRACT.completeness_check.load_contract(
            (BUNDLE / relative).read_text(encoding="utf-8"), module_id
        )
        assert THIN_EVIDENCE_FLAG not in rules["fixture_flags"], (relative, module_id)
        assert "source-limited" not in rules["fixture_substrings"], (
            relative,
            module_id,
        )
        assert not set(rules["fixture_flags"]) & set(rules["evidence_flags"])
    cp0 = CONTRACT.completeness_check.load_contract(
        (BUNDLE / CP0_SKILL).read_text(encoding="utf-8"), "CP-0"
    )
    assert set(cp0["fixture_flags"]) == FIXTURE_FLAGS
    assert cp0["evidence_flags"] == [THIN_EVIDENCE_FLAG]
    assert "source-limited" in cp0["evidence_substrings"]
    assert "integration fixture" in cp0["fixture_substrings"]

    skill = (BUNDLE / CP0_SKILL).read_text(encoding="utf-8")
    check = CONTRACT.completeness_check.check
    honest = handoff_markdown(
        identity("CP-0"),
        authored={"limitation_flags": [THIN_EVIDENCE_FLAG]},
        body_note="The two releases are source-limited; see the gaps register.",
    ).decode()
    assert check(skill, honest, "CP-0")[0] == []
    for flag in sorted(FIXTURE_FLAGS):
        fixture = handoff_markdown(
            identity("CP-0"), authored={"limitation_flags": [flag]}
        ).decode()
        assert check(skill, fixture, "CP-0")[0] == [
            f"limitation_flags declares the fixture marker {flag!r}"
        ]
    warned = handoff_markdown(
        identity("CP-0"), authored={"validation_warnings": ["PRESENTATION_FIXTURE"]}
    ).decode()
    assert check(skill, warned, "CP-0")[0] == [
        "validation_warnings declares the fixture marker 'PRESENTATION_FIXTURE'"
    ]
    marked = handoff_markdown(
        identity("CP-0"), body_note="Built from an Integration Fixture pack."
    ).decode()
    assert check(skill, marked, "CP-0")[0] == [
        "document contains the fixture marker text 'integration fixture'"
    ]


def test_screening_only_never_permits_committee_ready() -> None:
    """Request 2026-09-17-lite-scope-status: the validator maps each
    `decision_scope` to the committee statuses it permits, and the canon says
    the same; a caller that names no scope gets the bare enum as before."""
    vendor = CONTRACT.validate_handoff
    every = frozenset(vendor.COMMITTEE_STATUSES)
    assert vendor.COMMITTEE_STATUSES_BY_SCOPE == {
        "FULL": every,
        "SCREENING_ONLY": every - {"Committee Ready"},
    }
    canon = (BUNDLE / CANON).read_text(encoding="utf-8")
    assert "SCREENING_ONLY never permits Committee Ready" in canon

    cp0 = realistic_handoff_markdown(identity("CP-0"))
    l10 = identity("CP-L10", upstream=(upstream_ref(identity("CP-0"), cp0),))
    markdown = handoff_markdown(l10, authored={"committee_status": "Committee Ready"})
    text = markdown.decode()
    assert vendor.validate_text(text).errors == ()
    assert vendor.validate_text(text, decision_scope="FULL").errors == ()
    screened = vendor.validate_text(text, decision_scope="SCREENING_ONLY")
    assert screened.errors == (
        "committee_status 'Committee Ready' is not permitted under "
        "decision_scope SCREENING_ONLY",
    )
    unknown = vendor.validate_text(text, decision_scope="PARTIAL")
    assert unknown.errors == ("decision_scope 'PARTIAL' is not a declared scope",)
    draft = handoff_markdown(l10).decode()
    assert vendor.validate_text(draft, decision_scope="SCREENING_ONLY").errors == ()


def test_every_lite_edge_into_a_named_object_consumer_declares_the_object_it_carries(
    catalog: dict[str, object],
) -> None:
    """Request 2026-09-17-lite-producers, option 1: each `CP-L10` edge whose
    target retains `NAMED_LITE_OBJECT_ACCEPTED` names one accepted object the
    source's handoff carries, and CP-3C's block is keyed so the host reads it."""
    from caos.methodology.invocation import lite_object_requirement

    profiles = catalog["profiles"]
    modules = catalog["modules"]
    assert isinstance(profiles, dict) and isinstance(modules, list)
    edges = [
        edge
        for edge in profiles["LITE_CREDIT_22"]["edges"]
        if edge["source"] == "CP-L10"
    ]
    assert len(edges) >= 5
    declared: set[str] = set()
    for edge in edges:
        target = str(edge["target"])
        skill_md = next(m["skill_md"] for m in modules if m["module_id"] == target)
        accepted = lite_object_requirement(
            (BUNDLE / skill_md).read_bytes(), target, "LITE_CREDIT_22"
        )
        if accepted is None:
            continue
        declared.add(target)
        assert edge.get("accepted_object_id") in accepted, edge
        assert isinstance(edge.get("allowed_use"), str) and edge["allowed_use"], edge
    # The two edges §92 added carry the same declared use as their siblings.
    assert declared >= {"CP-2A", "CP-3C", "CP-2H", "CP-4C"}, declared
    added = {e["target"]: e for e in edges if e["target"] in {"CP-2A", "CP-3C"}}
    assert added["CP-2A"]["accepted_object_id"] == "lite_fundamental_credit_screen"
    assert added["CP-3C"]["accepted_object_id"] == "lite_liquidity_sensitivity_screen"
    assert {e["allowed_use"] for e in added.values()} == {"SCREENING_ONLY"}
    profiles_json = _load(BUNDLE / "CP_DEPLOY_V_EXECUTION_PROFILES_v1.json")
    compatibility = profiles_json["retained_lite_capabilities"]
    assert isinstance(compatibility, list)
    row = next(r for r in compatibility if r["module_id"] == "CP-3C")
    keyed = lite_object_requirement(
        (BUNDLE / CP3C_SKILL).read_bytes(), "CP-3C", "LITE_CREDIT_22"
    )
    assert keyed is not None
    assert set(row["accepted_lite_object_ids"]) == set(keyed)


def _l10_handoff() -> str:
    cp0 = realistic_handoff_markdown(identity("CP-0"))
    ref = upstream_ref(identity("CP-0"), cp0)
    return realistic_handoff_markdown(identity("CP-L10", upstream=(ref,))).decode()


def _with_register_cell(
    markdown: str, register: str, row: int, column: str, value: str
) -> str:
    """The fixture's `register` body row `row` (1-based) with one cell replaced."""
    start = markdown.index(f"#### {register}\n")
    lines = markdown[start:].split("\n")
    columns = [cell.strip() for cell in lines[2].strip().strip("|").split("|")]
    cells = [cell.strip() for cell in lines[3 + row].strip().strip("|").split("|")]
    cells[columns.index(column)] = value
    lines[3 + row] = "| " + " | ".join(cells) + " |"
    return markdown[:start] + "\n".join(lines)


def test_the_vendor_enforces_cp_l10s_semantic_rules() -> None:
    """Request 2026-09-17-unshipped-rules, rule 1: `semantic_rules` are read
    from the profile and enforced by the bundle's checker, so a duplicated or
    missing topic id and a screen without its OVERALL row are violations."""
    skill = (BUNDLE / L10_SKILL).read_text(encoding="utf-8")
    rules = CONTRACT.completeness_check.load_contract(skill, "CP-L10")
    assert [rule["rule_id"] for rule in rules["semantic_rules"]] == [
        "cp_l10.topic_ids_unique",
        "cp_l10.topic_ids_complete",
        "cp_l10.overall_screen_present",
    ]
    check = CONTRACT.completeness_check.check
    handoff = _l10_handoff()
    assert check(skill, handoff, "CP-L10")[0] == []

    doubled = _with_register_cell(handoff, "TL10.2", 2, "topic_id", "SOURCE_BASIS")
    assert check(skill, doubled, "CP-L10")[0] == [
        "TL10.2: cp_l10.topic_ids_unique -- column 'topic_id' repeats 'SOURCE_BASIS'",
        "TL10.2: cp_l10.topic_ids_complete -- column 'topic_id' lacks "
        "'EARNINGS_MARGIN_CHANGE'",
    ]
    lowered = _with_register_cell(handoff, "TL10.3", 1, "screen_item", "overall")
    assert check(skill, lowered, "CP-L10")[0] == [
        "TL10.3: cp_l10.overall_screen_present -- column 'screen_item' lacks 'OVERALL'"
    ]


def test_the_vendor_checks_a_lite_payloads_required_fields() -> None:
    """Request 2026-09-17-unshipped-rules, rule 3: `required_payload_fields`
    are read from the profile and a payload's `runtime_output` is checked
    against them by the bundle. The canonical adapter holds no payload, so the
    host has nothing to hand it today (§92)."""
    skill = (BUNDLE / L10_SKILL).read_text(encoding="utf-8")
    rules = CONTRACT.completeness_check.load_contract(skill, "CP-L10")
    fields = rules["required_payload_fields"]
    assert len(fields) == 13 and fields[0] == "cross_topic_synthesis"
    runtime: dict[str, str] = dict.fromkeys(fields, "x")
    payload: dict[str, object] = {"module_id": "CP-L10", "runtime_output": runtime}
    check_payload = CONTRACT.completeness_check.check_payload
    assert check_payload(skill, payload, "CP-L10") == []
    del runtime["upgrade_plan"]
    assert check_payload(skill, payload, "CP-L10") == [
        "runtime_output lacks the required payload field 'upgrade_plan'"
    ]
    assert check_payload(skill, {"module_id": "CP-L10"}, "CP-L10") == [
        "payload has no runtime_output object"
    ]
    cp0 = (BUNDLE / CP0_SKILL).read_text(encoding="utf-8")
    load_contract = CONTRACT.completeness_check.load_contract
    assert load_contract(cp0, "CP-0")["required_payload_fields"] == []
