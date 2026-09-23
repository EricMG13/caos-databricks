"""One canonical invocation: the host identity from the store, then its prompt (§41).

`host_identity` reads every host-owned fact from what the store pinned -- the
run input's subject and vendor run id, the attempt's stored ordinal, the pinned
route and the accepted upstream artifacts -- so no caller's copy of an identity
survives (invariant 3). `build_handoff_prompt` hands the module those exact
front-matter lines to copy, every delivered authority file whole, the exact
upstream Markdown as context labelled with its edge's `allowed_use`, a register
of each upstream's host-anchored citations (quote existence proven, support left
to CP-5), and every delivered block as evidence. `within_request_ceiling`
bounds the whole encoded request the provider would send, and refuses an
over-ceiling context rather than cut anything out of it (§45).

`canonical.py` calls both for every canonical attempt, before and after the
call, and once under `prospective_identity` before the attempt exists.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import threading
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any
from uuid import UUID

from caos import methodology
from caos.blobs import BlobStore
from caos.boundary_text import visible
from caos.digest import canonical_json
from caos.evidence.citations import AnchoredCitation
from caos.graph.route import (
    BLOCKING,
    MODEL_MODULE,
    NamedObjects,
    ResolvedRoute,
    RouteNode,
)
from caos.icm import prompt_block
from caos.methodology.bundle import (
    Bundle,
    DeliveredAuthority,
    assemble_authority,
    authority_digest,
    delivered_authority,
    delivered_authority_digest,
    verified_bytes,
)
from caos.methodology.executor import SKILL, Delivery
from caos.methodology.handoff import (
    ADAPTER_MODULES,
    ADAPTER_ROUTES,
    GATE_MODULE,
    INVISIBLE,
    RESEARCH_MODULE,
    CanonicalRecord,
    HostIdentity,
    LineageRef,
    UpstreamRef,
    expected_filename,
    invocation_fields,
    research_brief_of,
    stored_lineage,
)
from caos.methodology.vendor import (
    VENDOR_MODULE,
    VendorContract,
    authority_bundle_sha256,
    cached_contract,
    catalog,
)
from caos.provider import MAX_REQUEST_BYTES, CompletionProvider
from caos.refusals import Refusal, RefusalCode
from caos.store import StoreConnection
from caos.store.outcomes import accepted_rows, artifact_digests
from caos.store.routes import resolved_route
from caos.store.run_inputs import (
    RunSubject,
    bound_research_brief,
    load_run_input,
)
from caos.store.runs import MAX_ATTEMPT_ORDINAL, attempt_ordinal
from caos.store.source_sets import SourceSet

_CATALOG = "references/CREDIT_OS_V_MODULE_CATALOG_v2.json"

# One accepted upstream handoff's bytes, whole. The per-section bound §45.3
# never gave: the request ceiling bounds the sum and names no part, so the
# first wide pathway would refuse CONTEXT_OVER_CEILING with nothing said about
# which section was large. Declared rather than derived from the ceiling, so a
# reader sees the number. The legacy 32 KiB was sized for another model's
# handoffs: the first live Claude Opus 5 answer, CP-0 over a six-line
# document, ran to 36,544 bytes and the next node refused
# UPSTREAM_SECTION_OVER_CEILING before any call (F110). 52 KiB is the most the
# catalog's widest node can carry: CP-5 takes 16 direct upstreams, and 16
# sections at this bound beside its 165,548 bytes of delivered authority fit
# the request (the widest-node test in `tests/test_handoff_invocation.py`),
# with the 4 MiB ceiling (D29) leaving most of it for evidence; a node that
# still reaches the ceiling fails closed there, typed. Nothing is ever truncated:
# per-node evidence selection (§95, `caos/methodology/selection.py`) narrows a
# node's evidence to the members its gate row names, but a named member is
# delivered whole and the upstream sections are bounded here, not selected.
MAX_UPSTREAM_HANDOFF_BYTES = 53_248


def host_identity(  # noqa: PLR0913 -- the brief's keyword-only identity inputs
    conn: StoreConnection,
    bundle: Bundle,
    *,
    run_id: UUID,
    route: ResolvedRoute,
    node: RouteNode,
    attempt_id: UUID,
) -> HostIdentity:
    """This attempt's host identity, read inside the caller's transaction.

    Refuses `RUN_INPUT_INVALID` for a pin that is not canonical (format 2 with a
    subject) or was taken under another bundle build; `ROUTE_IDENTITY_INVALID`
    when the caller's route or node is not the pin, or a blocking upstream has
    no accepted artifact; `ATTEMPT_NOT_FOUND` for an attempt of another run or
    node. `module_name` is not pinned on `RouteNode`, so it is read from the
    verified bundle catalog the pin's build names.
    """
    return _identity(
        conn, bundle, run_id=run_id, route=route, node=node, attempt_id=attempt_id
    )


def prospective_identity(
    conn: StoreConnection,
    bundle: Bundle,
    *,
    run_id: UUID,
    route: ResolvedRoute,
    node: RouteNode,
) -> HostIdentity:
    """The identity the node's next attempt will carry, before it exists.

    `host_identity`'s reads and refusals without an attempt row, at
    `MAX_ATTEMPT_ORDINAL`: the ordinal reaches the prompt only through the
    vendor's fixed-width attempt id and invocation digest, so the prompt's size
    is the one the real attempt's will be. Used only to meet the context ceiling
    before an attempt is started or anything reserved (§45.3).
    """
    return _identity(conn, bundle, run_id=run_id, route=route, node=node)


def _identity(  # noqa: PLR0913 -- one identity, keyword-only
    conn: StoreConnection,
    bundle: Bundle,
    *,
    run_id: UUID,
    route: ResolvedRoute,
    node: RouteNode,
    attempt_id: UUID | None = None,
) -> HostIdentity:
    pin = load_run_input(conn, run_id)
    if (
        pin is None
        or pin.subject is None
        or pin.cos_run_id is None
        or pin.adapter_version != methodology.CANONICAL_ADAPTER_VERSION
        or (pin.build_id, pin.manifest_sha256)
        != (bundle.build_id, bundle.manifest_sha256)
    ):
        raise Refusal(RefusalCode.RUN_INPUT_INVALID)
    stored = resolved_route(conn, run_id)
    if stored is None or stored != route or node not in stored.nodes:
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
    # A module the adapter does not own, or one on a pathway no contract test
    # proves (§42.2), has no canonical identity to build -- the same two sets
    # `gates.require_adapter_route` refuses at execution input and acceptance.
    if (
        node.module_id not in ADAPTER_MODULES
        or (stored.profile_id, stored.selection_id) not in ADAPTER_ROUTES
    ):
        raise Refusal(RefusalCode.HANDOFF_MODULE_UNSUPPORTED)
    ordinal = MAX_ATTEMPT_ORDINAL
    if attempt_id is not None:
        owner = conn.execute(
            "SELECT run_id, route_node_id FROM run_attempts WHERE attempt_id = %s",
            (attempt_id,),
        ).fetchone()
        if owner != (run_id, node.route_node_id):
            raise Refusal(RefusalCode.ATTEMPT_NOT_FOUND)
        ordinal = attempt_ordinal(conn, attempt_id)
    subject = pin.subject
    upstream = _upstream(
        stored,
        node,
        artifact_digests(conn, run_id),
        run_id=pin.cos_run_id,
        period=subject.reporting_period,
    )
    # §45.5: a non-gate node's CP-0 anchor comes only from a direct CP-0 ref.
    gate = [ref for ref in upstream if ref.module_id == GATE_MODULE]
    if node.module_id != GATE_MODULE and not gate:
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
    authority = authority_bundle_sha256(bundle)
    return HostIdentity(
        run_id=pin.cos_run_id,
        profile_id=stored.profile_id,
        selection_id=stored.selection_id,
        route_node_id=node.route_node_id,
        module_id=node.module_id,
        module_name=_module_name(bundle, stored, node),
        issuer_id=subject.issuer_id,
        issuer_name=subject.issuer_name,
        reporting_period=subject.reporting_period,
        analysis_date=subject.analysis_date,
        ordinal=ordinal,
        authority_bundle_sha256=authority,
        upstream=upstream,
        research_brief=(
            _research_binding(
                bundle,
                stored,
                pin_research=pin.research_json,
                subject=subject,
                run_id=pin.cos_run_id,
                cp0_sha256=gate[0].sha256,
                authority_sha256=authority,
            )
            if node.module_id == RESEARCH_MODULE
            else None
        ),
    )


def _research_binding(  # noqa: PLR0913 -- one binding, keyword-only
    bundle: Bundle,
    route: ResolvedRoute,
    *,
    pin_research: str | None,
    subject: RunSubject,
    run_id: str,
    cp0_sha256: str,
    authority_sha256: str,
) -> str:
    """CP-DR's brief, bound now to the accepted gate (§96).

    The pin stored the caller's brief unanchored; here the accepted CP-0's
    Markdown digest replaces the stand-in, and the vendor's own `validate_brief`
    and `Route` judge the bound result again. A CP-DR node whose pin carries no
    brief refuses `RUN_INPUT_INVALID` -- before any attempt, reservation or
    call, because `check_context` builds this identity first -- rather than
    prompting a research module with nothing to research. Only the brief's
    canonical text travels; no vendor text reaches the refusal.
    """
    if pin_research is None:
        raise Refusal(RefusalCode.RUN_INPUT_INVALID)
    bound = bound_research_brief(
        cached_contract(bundle),
        catalog(bundle),
        brief=json.loads(pin_research),
        route=route,
        subject=subject,
        run_id=run_id,
        cp0_sha256=cp0_sha256,
        authority_sha256=authority_sha256,
    )
    return canonical_json(bound)


def call_time_identity(
    conn: StoreConnection,
    route: ResolvedRoute,
    host: HostIdentity,
    *,
    attempt_id: UUID,
    record: bytes | None,
) -> HostIdentity:
    """`host` with only the upstream refs this attempt's call could have named.

    `host_identity` names every input accepted now. A soft input accepted after
    the attempt started was not there to name, so the refs narrow to those the
    stored `record` names -- except a blocking ref, never optional, and a soft
    ref whose artifact was accepted before the attempt started, which the call
    had to name. Nothing the record says is added. Keeping a ref the record
    omits is what makes `read_record` refuse it; an unreadable `record` names
    nothing, and `read_record` refuses it on its own. Caller owns the read.
    """
    named: set[str] = set()
    try:
        document = json.loads(record or b"null")
        named = {ref["route_node_id"] for ref in document["identity"]["upstream"]}
    except (ValueError, KeyError, TypeError):
        named = set()
    by_module = {n.module_id: n.route_node_id for n in route.nodes}
    named |= {
        str(by_module.get(edge.source))
        for edge in route.edges
        if edge.target == host.module_id and edge.type in BLOCKING
    }
    later = {
        str(row[0])
        for row in conn.execute(
            "SELECT a.route_node_id FROM artifacts a"
            " JOIN run_attempts t ON t.run_id = a.run_id"
            " WHERE t.attempt_id = %s AND a.created_at > t.started_at",
            (attempt_id,),
        ).fetchall()
    }
    kept = tuple(
        ref
        for ref in host.upstream
        if ref.route_node_id in named or ref.route_node_id not in later
    )
    return replace(host, upstream=kept)


def record_authority_matches(
    record: CanonicalRecord, *, bundle: Bundle, module_id: str, verify: bool = False
) -> bool:
    """Whether a record was written under this bundle for this pinned module.

    The one comparison every reader of an accepted record makes (invariant 4):
    the canonical adapter, and the bundle's build, manifest, the module's
    authority digest and its delivered-authority digest (§45.1), re-derived from
    the bytes here now. `read_record` binds
    the invocation; this binds the methodology. `module_id` is the pin's, never
    the record's. Each caller raises its own code on False.

    `verify=True` re-reads and verifies every authority file now instead of
    answering from the per-manifest cache: the proof and the deliverable use it,
    so a file tampered on disk under an unchanged manifest refuses there whatever
    this process read before (invariant 4).
    """
    manifest_sha256, build_id = bundle.manifest_sha256, bundle.build_id
    return (
        record.adapter_version,
        record.build_id,
        record.manifest_sha256,
        record.authority_digest,
        record.delivered_authority_digest,
    ) == (
        methodology.CANONICAL_ADAPTER_VERSION,
        build_id,
        manifest_sha256,
        *(
            _read_authority_digests(bundle, module_id)
            if verify
            else _authority_digests(bundle, module_id, manifest_sha256, build_id)
        ),
    )


# (bundle root, manifest sha256, build, module) to the module's two authority
# digests. The manifest pins every file's hash and each digest is over those
# hashes, so for one manifest the values cannot differ; a moved manifest is
# another key. What a cached reading gives up is re-reading the files: the
# executor's prompt still verifies every delivered byte at use.
_AUTHORITY_DIGESTS: dict[tuple[str, str, str, str], tuple[str, str]] = {}
_AUTHORITY_LOCK = threading.Lock()


def _authority_digests(
    bundle: Bundle, module_id: str, manifest_sha256: str, build_id: str
) -> tuple[str, str]:
    key = (str(bundle.root.resolve()), manifest_sha256, build_id, module_id)
    with _AUTHORITY_LOCK:
        cached = _AUTHORITY_DIGESTS.get(key)
    if cached is None:
        cached = _read_authority_digests(bundle, module_id)
        with _AUTHORITY_LOCK:
            _AUTHORITY_DIGESTS[key] = cached
    return cached


def _read_authority_digests(bundle: Bundle, module_id: str) -> tuple[str, str]:
    return (
        authority_digest(assemble_authority(bundle, module_id)),
        delivered_authority_digest(delivered_authority(bundle, module_id)),
    )


def accepted_lineage(
    conn: StoreConnection,
    blobs: BlobStore,
    *,
    run_id: UUID,
    upstream: Sequence[UpstreamRef],
    accepted: Mapping[str, tuple[str, str | None]] | None = None,
) -> tuple[LineageRef, ...]:
    """The whole accepted chain behind `upstream`, as the store holds it now.

    `stored_lineage` over the run's accepted rows: what a record's `lineage`
    must equal when read (§45.4). `accepted` maps each accepted node to its
    (artifact, record) pair when the caller's unit already read them, so a
    reader of every row queries once rather than once per record; otherwise one
    query, none without upstream. Caller owns the read.
    `ARTIFACT_RECORD_MISMATCH` when the chain does not bind.
    """
    if not upstream:
        return ()
    if accepted is None:
        accepted = {
            node: (artifact, record)
            for node, _attempt, artifact, record in accepted_rows(conn, run_id)
        }
    return stored_lineage(blobs, upstream, accepted)


def _module_name(bundle: Bundle, route: ResolvedRoute, node: RouteNode) -> str:
    if node.module_id == MODEL_MODULE:
        from caos.methodology.host import HOST_NAME, verify_extension

        verify_extension(route)
        return HOST_NAME
    try:
        catalog = json.loads(verified_bytes(bundle, VENDOR_MODULE, _CATALOG))
        pathway = catalog["profiles"][route.profile_id]["pathways"]
        nodes = pathway[route.selection_id]["nodes"]
        names = [
            entry["module_name"]
            for entry in nodes
            if entry["route_node_id"] == node.route_node_id
            and entry["module_id"] == node.module_id
        ]
    except (ValueError, KeyError, TypeError):
        names = []
    if len(names) != 1 or not isinstance(names[0], str) or not names[0]:
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
    return names[0]


def _upstream(
    route: ResolvedRoute,
    node: RouteNode,
    accepted: Mapping[str, str],
    *,
    run_id: str,
    period: str,
) -> tuple[UpstreamRef, ...]:
    """Every accepted direct input; a missing blocking one refuses.

    The vendor's `routing.expected_upstream_digests` without its predicates and
    readiness: a CONDITIONAL edge blocks unconditionally here (the host
    evaluates no predicate), and a soft edge whose source has not been accepted
    is omitted, as the vendor omits it.
    """
    by_module = {n.module_id: n for n in route.nodes}
    refs: dict[str, UpstreamRef] = {}
    for edge in route.edges:
        if edge.target != node.module_id:
            continue
        source = by_module.get(edge.source)
        digest = None if source is None else accepted.get(source.route_node_id)
        if source is None or digest is None:
            if edge.type in BLOCKING:
                raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
            continue
        refs[source.route_node_id] = UpstreamRef(
            route_node_id=source.route_node_id,
            module_id=source.module_id,
            run_id=run_id,
            period=period,
            sha256=digest,
        )
    return tuple(refs[key] for key in sorted(refs))


def upstream_markdown(
    blobs: BlobStore, refs: Sequence[UpstreamRef]
) -> tuple[tuple[UpstreamRef, bytes], ...]:
    """Each accepted upstream handoff's exact Markdown, proven by its digest."""

    def read(ref: UpstreamRef) -> bytes:
        try:
            return blobs.get(ref.sha256)
        except (Refusal, OSError):
            pass
        raise Refusal(RefusalCode.ORCHESTRATION_ARTIFACT_UNREADABLE)

    return tuple((ref, read(ref)) for ref in refs)


_INSTRUCTION = prompt_block("instruction")

_TAGGED = prompt_block("tagged")

_FINAL_CHECK = prompt_block("final_check")

# The second paragraph is `cp-0-source-readiness/SKILL.md` quoted back at the
# module that ships it, and nothing else. The host states no methodology of its
# own here (invariant 4): CP-0 already receives that file in full, and the run
# that ended BLOCKED had the rule in front of it and put a sequencing condition
# in a readiness column anyway. A final check is where a rule that gets
# forgotten belongs; if it is forgotten again with the rule restated, that is
# evidence about `CONDITIONAL` being undefined rather than about this module.
_CP0_FINAL_CHECK = prompt_block("cp0_final_check")

# Only a route carrying CP-CF hands its forecast owners this section; no
# LITE fixture builds one, so its markers are asserted on the text directly.
_FORECAST_EXTENSION = prompt_block("forecast_extension")

# Every script a LITE module's SKILL.md names, by who performs it. No script is
# delivered. The host runs the first set itself; scoring has no host step, so
# the module authors it by the rules the authority states for its script.
HOST_PERFORMED_SCRIPTS = frozenset(
    {"prepare_invocation.py", "validate_handoff.py", "completeness_check.py"}
)
MODULE_AUTHORED_SCRIPTS = frozenset({"confidence_score.py"})

_HOST_STEPS = prompt_block("host_steps")

_GATE_INSTRUCTION = prompt_block("gate_instruction")

# A node's one second attempt after a refused answer (D30): what the checks
# reported, as written. The host adds no rule of its own here (invariant 4).
_RETRY_FEEDBACK = prompt_block("validator_feedback")

# An edge whose catalog entry declares no `allowed_use` says so, rather than
# leaving the label out.
NOT_DECLARED = "NOT_DECLARED"


def _yaml(fields: Mapping[str, Any]) -> str:
    """The front matter as the vendor's restricted YAML, every scalar JSON-quoted."""
    lines = []
    for key, value in fields.items():
        if isinstance(value, list) and value:
            lines.append(f"{key}:")
            for item in value:
                for n, (name, scalar) in enumerate(item.items()):
                    marker = "  - " if n == 0 else "    "
                    lines.append(f"{marker}{name}: {json.dumps(scalar)}")
        else:
            lines.append(f"{key}: {json.dumps(value)}")
    return "\n".join(lines)


def allowed_uses(
    catalog: Mapping[str, Any], route: ResolvedRoute, target: str
) -> dict[str, str]:
    """Source module to the `allowed_use` of its edge into `target`.

    Read from the verified catalog's typed edges for the pinned profile, so the
    label is the bundle's (the pin binds the build); `Edge` does not carry it,
    and the route digest is unchanged. An edge the route does not carry is not
    labelled; a pair the catalog labels twice differently refuses
    `ROUTE_IDENTITY_INVALID`.
    """
    pinned = {(edge.source, edge.target) for edge in route.edges}
    try:
        edges = [
            (edge["source"], edge["target"], edge.get("allowed_use", NOT_DECLARED))
            for edge in catalog["profiles"][route.profile_id]["edges"]
        ]
    except (KeyError, TypeError, AttributeError):
        edges = None
    if edges is None:
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
    uses: dict[str, set[object]] = {}
    for source, edge_target, use in edges:
        if not (
            isinstance(source, str)
            and isinstance(edge_target, str)
            and isinstance(use, str)
            and use
        ):
            raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
        if edge_target == target and (source, edge_target) in pinned:
            uses.setdefault(source, set()).add(use)
    if any(
        len(values) != 1 or not all(isinstance(v, str) and v for v in values)
        for values in uses.values()
    ):
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
    result = {source: str(values.pop()) for source, values in uses.items()}
    if target == MODEL_MODULE:
        result.update(
            {
                source: "Accepted forecast inputs within the host CP-CF contract"
                for source, edge_target in pinned
                if edge_target == target
            }
        )
    return result


def owned_objects(
    catalog: Mapping[str, Any], route: ResolvedRoute, target: str
) -> dict[str, str]:
    """Each direct input of `target` on the pinned route to the object its
    catalog `artifact_contract.owned_object` names, `NOT_DECLARED` when none.

    A catalog whose module list cannot be read, or that declares one module
    twice, refuses `ROUTE_IDENTITY_INVALID`, as `allowed_uses` does.
    """
    sources = {edge.source for edge in route.edges if edge.target == target}
    try:
        entries = [
            (entry["module_id"], entry.get("artifact_contract") or {})
            for entry in catalog["modules"]
        ]
        declared = {
            module: contract.get("owned_object", NOT_DECLARED)
            for module, contract in entries
        }
    except (KeyError, TypeError, AttributeError):
        declared = {}
        entries = []
    if not entries or len(declared) != len(entries):
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
    owned = {source: declared.get(source, NOT_DECLARED) for source in sources}
    if not all(isinstance(value, str) and value for value in owned.values()):
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
    return dict(sorted(owned.items()))


# The vendor's words for the named-object boundary (§46.1). The block is read
# from the module's own verified SKILL.md; nothing here names a module.
NAMED_LITE_OBJECT_ACCEPTED = "NAMED_LITE_OBJECT_ACCEPTED"
_LITE_HEADING = "## LITE profile compatibility — "
_LITE_BOUNDARY = re.compile(
    r"`([A-Z0-9_]+)`; (?:the|its) retained input boundary is `([A-Z_]+)`"
)
_LITE_IDS = re.compile(r"^- \*\*accepted_lite_object_ids\*\*: (.*)$", re.MULTILINE)
_OBJECT_ID = re.compile(r"`([a-z0-9_]+)`")
_NO_IDS = "none"


def lite_object_requirement(
    skill: bytes, module_id: str, profile_id: str
) -> frozenset[str] | None:
    """The object ids `module_id`'s LITE compatibility block accepts, when that
    block names `profile_id` and retains `NAMED_LITE_OBJECT_ACCEPTED`.

    `None` when `skill` has no block headed `— <module_id>` (an unkeyed prose
    heading is not a block), or the block names another profile or boundary.
    A block that is present but duplicated, without exactly one boundary
    sentence and one `accepted_lite_object_ids` line, whose ids are neither
    `none` nor a list of distinct backticked ids, or that retains the named
    boundary with no ids, refuses `AUTHORITY_BYTES_MISMATCH`: a boundary the
    host cannot read is never read as absent.
    """
    lines = _utf8(skill, RefusalCode.AUTHORITY_BYTES_MISMATCH).split("\n")
    heading = _LITE_HEADING + module_id
    starts = [n for n, line in enumerate(lines) if line.rstrip() == heading]
    if not starts:
        return None
    body: list[str] = []
    for line in lines[starts[0] + 1 :]:
        if line.startswith("## "):
            break
        body.append(line)
    block = "\n".join(body)
    boundary = _LITE_BOUNDARY.findall(block)
    listed = _LITE_IDS.findall(block)
    written = listed[0].rstrip() if len(listed) == 1 else ""
    ids = _OBJECT_ID.findall(written)
    well_formed = written == _NO_IDS or (
        bool(ids)
        and len(set(ids)) == len(ids)
        and written == ", ".join(f"`{i}`" for i in ids)
    )
    named = len(boundary) == 1 and boundary[0][1] == NAMED_LITE_OBJECT_ACCEPTED
    if len(starts) != 1 or len(boundary) != 1 or not well_formed or (named and not ids):
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    if boundary[0][0] != profile_id or not named:
        return None
    return frozenset(ids)


def _verified_catalog(bundle: Bundle) -> dict[str, Any]:
    """The vendor catalog, or the code for authority that will not parse.

    Verified bytes that are not a JSON object are the bundle disagreeing with
    itself, which every reader answers with `AUTHORITY_BYTES_MISMATCH`; a bare
    `json.loads` here raised `ValueError` past the typed boundary instead.
    """
    try:
        catalog = json.loads(verified_bytes(bundle, VENDOR_MODULE, _CATALOG))
    except ValueError:
        catalog = None
    if not isinstance(catalog, dict):
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    return catalog


def named_objects(bundle: Bundle, route: ResolvedRoute) -> NamedObjects:
    """The pinned route's named-object boundary, from verified bundle bytes.

    Every node's `SKILL.md` is read through `verified_bytes` and parsed by
    `lite_object_requirement`; owners come from the verified catalog through
    `owned_objects`. A module the manifest does not carry (a host extension)
    has no vendor block to retain.
    """
    catalog = _verified_catalog(bundle)
    owned: dict[str, str] = {}
    accepted_ids: dict[str, frozenset[str]] = {}
    for node in route.nodes:
        owned.update(
            (source, value)
            for source, value in owned_objects(catalog, route, node.module_id).items()
            if value != NOT_DECLARED
        )
        try:
            skill = verified_bytes(bundle, node.module_id, SKILL)
        except Refusal as refused:
            if refused.code is not RefusalCode.AUTHORITY_MODULE_UNKNOWN:
                raise
            continue
        ids = lite_object_requirement(skill, node.module_id, route.profile_id)
        if ids is not None:
            accepted_ids[node.module_id] = ids
    carried = _carried_objects(catalog, route.profile_id)
    offered = NamedObjects(owned=owned, accepted_ids={}, carried=carried)
    # A boundary no input on this pinned route can meet -- the vendor names an
    # object no module on it owns or carries -- is not enforced: holding the
    # node forever would be a host-invented graph, not the vendor's (§46.1
    # review). Only CP-5's boundary on the LITE earnings route is executable.
    meetable = {
        module: ids
        for module, ids in accepted_ids.items()
        if any(
            offered.offers(edge.source, module) & ids
            for edge in route.edges
            if edge.target == module
        )
    }
    return NamedObjects(owned=owned, accepted_ids=meetable, carried=carried)


def _carried_objects(
    catalog: Mapping[str, Any], profile_id: str
) -> dict[tuple[str, str], str]:
    """Each catalog edge's declared `accepted_object_id`, keyed by the edge."""
    carried: dict[tuple[str, str], str] = {}
    try:
        edges = catalog["profiles"][profile_id]["edges"]
        pairs = [
            ((str(edge["source"]), str(edge["target"])), edge.get("accepted_object_id"))
            for edge in edges
        ]
    except (KeyError, TypeError, AttributeError):
        pairs = None
    if pairs is None or any(
        value is not None and (not isinstance(value, str) or not value)
        for _, value in pairs
    ):
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
    seen: dict[tuple[str, str], object] = {}
    for key, value in pairs:
        if key in seen and seen[key] != value:
            raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
        seen[key] = value
    carried.update((key, value) for key, value in pairs if value is not None)
    return carried


def _utf8(data: bytes, code: RefusalCode) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    raise Refusal(code)


def _upstream_section(
    upstream: Sequence[tuple[UpstreamRef, bytes]],
    uses: Mapping[str, str],
    owned: Mapping[str, str],
    tag: str = "",
) -> str:
    if not upstream:
        return ""
    sections = []
    for ref, data in upstream:
        text = _utf8(data, RefusalCode.ORCHESTRATION_ARTIFACT_UNREADABLE)
        if (
            hashlib.sha256(data).hexdigest() != ref.sha256
            or ref.module_id not in uses
            or ref.module_id not in owned
        ):
            raise Refusal(RefusalCode.ORCHESTRATION_ARTIFACT_UNREADABLE)
        # After the identity comparison, not before it. These bytes are already
        # whole in memory from the blob read, so checking the size first bought
        # no memory and cost an answer: a handoff both altered and oversize
        # reported a capacity problem to an operator who has an integrity one.
        # The host owns identity (invariant 3); a host policy bound does not
        # get to answer ahead of it.
        if len(data) > MAX_UPSTREAM_HANDOFF_BYTES:
            raise Refusal(RefusalCode.UPSTREAM_SECTION_OVER_CEILING)
        sections.append(
            f"module_id: {ref.module_id}\nroute_node_id: {ref.route_node_id}\n"
            f"sha256: {ref.sha256}\nallowed_use: {uses[ref.module_id]}\n"
            f"owned_object: {owned[ref.module_id]}\n{text}"
        )
    return (
        f"\n--- UPSTREAM {tag} (accepted handoffs, exact bytes: context, not "
        "evidence, each within its allowed_use; cite only the evidence below) ---\n"
        + "\n\n".join(sections)
        + f"\n--- END UPSTREAM {tag} ---\n"
    )


# Each register line's two host labels (§41.3, brief 3.3 scope 4): the host
# proved the quote exists in delivered evidence; nobody here judged support.
QUOTE_EXISTENCE = "quote_existence: HOST_VERIFIED_IN_DELIVERED_EVIDENCE"
SUPPORT = "support: NOT_ASSESSED_BY_HOST (CP-5 audit)"


def _citation_register(
    upstream: Sequence[tuple[UpstreamRef, bytes]],
    citations: Mapping[str, tuple[AnchoredCitation, ...]],
    tag: str = "",
) -> str:
    """Each direct upstream's anchored citations, as host-owned context.

    Exactly the citations the host re-located when that upstream was accepted,
    in the record's order; never read from its Markdown. Labelled context, not
    evidence: a quote here is not citable, and its listing says nothing about
    whether it supports anything the handoff states.
    """
    if not upstream:
        return ""
    sections = []
    for ref, _data in upstream:
        lines = [
            f"module_id: {ref.module_id}\nroute_node_id: {ref.route_node_id}\n"
            f"handoff_sha256: {ref.sha256}"
        ]
        lines += [
            f"- document_sha256: {c.document_sha256} page: {c.page} "
            f"matched_text: {json.dumps(c.matched_text, ensure_ascii=False)} "
            f"{QUOTE_EXISTENCE} {SUPPORT}"
            for c in citations[ref.route_node_id]
        ]
        sections.append("\n".join(lines))
    return (
        f"\n--- UPSTREAM CITATION REGISTER {tag} (host-owned context, not "
        "evidence: each line is a quote an accepted upstream handoff cited, which "
        "the host located word for word in the evidence delivered to that module "
        "when it was accepted. The host has not assessed whether any quote "
        "supports any statement; that is CP-5's audit. Never cite these lines; "
        "cite only the evidence below) ---\n"
        + "\n\n".join(sections)
        + f"\n--- END UPSTREAM CITATION REGISTER {tag} ---\n"
    )


def _authority_text(module_id: str, name: str, data: bytes) -> str:
    # Only these manifest-verified workbook references are binary.
    if (module_id, name) in {
        ("CP-3", "references/REF_CP-3B_Portfolio_Constraints.xlsx"),
        ("CP-3", "references/REF_CP-3_Sector_RV.xlsx"),
        ("CP-6", "references/REF_CP-6A_Portfolio_Debate_Inputs.xlsx"),
    }:
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
        return "ENCODING: base64 (complete XLSX reference bytes)\n" + base64.b64encode(
            data
        ).decode("ascii")
    return _utf8(data, RefusalCode.AUTHORITY_BYTES_MISMATCH)


def _authority_sections(authority: DeliveredAuthority, tag: str) -> str:
    return "".join(
        f"\n--- AUTHORITY {tag} FILE {name} SHA256 "
        f"{hashlib.sha256(data).hexdigest()} ---\n"
        f"{_authority_text(authority.module_id, name, data)}"
        f"\n--- END AUTHORITY {tag} FILE {name} ---\n"
        for name, data in authority.files
    )


def _printable(value: str) -> str:
    """A string the host attributes to itself, with nothing invisible in it.

    `BoundaryText` keeps U+2028, U+2029 and U+FEFF -- one text that reads as
    two -- while `handoff.INVISIBLE` refuses them in a module's answer. A
    filename is chosen by whoever admitted the document, and it is rendered
    here under a marker the prompt calls host-owned. Copied into CP-0's
    inventory exactly as the instruction demands, such a filename would be
    refused `HANDOFF_MALFORMED`: a host defect recorded as the model's answer.
    Dropping the characters is the narrow fix; the document keeps its name
    everywhere the host owns the comparison.

    The handoff refuses `hides_text` as well (AI-2), so what is dropped is that
    set too, through the one expression that states it (`boundary_text.visible`):
    a zero-width space or a tag character in a filename was shown to CP-0 and
    its answer quoting it refused (EV-5).
    """
    return visible(
        "".join(character for character in value if character not in INVISIBLE)
    )


def _member_identity(stored: str) -> object:
    """One pinned extraction identity, as the store holds it.

    These are bytes this host wrote at admission, so text that will not parse
    is a store fault with a code -- never a `ValueError` out of the builder.
    """
    try:
        return json.loads(stored)
    except ValueError:
        raise Refusal(RefusalCode.SOURCE_IDENTITY_INVALID) from None


# §98: said once, beside the metadata, when any source is shown as a page map.
_PAGE_MAP_NOTE = (
    "A source whose entry carries evidence_delivery PAGE_MAP is larger than "
    "the host shows this gate whole: its EVIDENCE is the first "
    "leading_lines_per_page lines of each of its pages (lines_shown of lines), "
    "and no other line of it is in your evidence or may be cited. The "
    "authority's Step I rules 5 and 8 say how to attach it by page.\n"
)


def _source_preparation_section(
    source_set: SourceSet | None,
    tag: str,
    page_maps: Mapping[UUID, Mapping[str, int]] | None = None,
) -> str:
    """CP-0's verified source provenance, deliberately outside evidence.

    Every source says how its evidence was delivered (§102): `PAGE_MAP` with
    its map fields (§98), and one note on what a map is; otherwise `WHOLE`, so
    CP-0 never reads the page-map rule onto a source it was handed entire.
    """
    if source_set is None:
        return ""
    maps = page_maps or {}
    metadata = {
        "source_set_version": source_set.version,
        "source_set_fingerprint": source_set.fingerprint,
        "managed_workspace": {
            "kind": "host-pinned-run",
            "original_store": "immutable content-addressed BlobStore",
            "note": (
                "The original_root values identify retained originals; they are "
                "not model-accessible paths."
            ),
        },
        "sources": [
            {
                "source_id": str(member.source_id),
                "filename": _printable(member.filename),
                "admitted_at": member.admitted_at,
                "original_root": f"blob://sha256/{member.document_sha256}",
                "original_sha256": member.document_sha256,
                "extractor_identity": _member_identity(member.extractor_identity),
                "output_sha256": member.output_sha256,
                "extraction_sha256": member.extraction_sha256,
            }
            | (
                {"evidence_delivery": "PAGE_MAP", **maps[member.source_id]}
                if member.source_id in maps
                else {"evidence_delivery": "WHOLE"}
            )
            for member in source_set.members
        ],
    }
    body = json.dumps(metadata, sort_keys=True, ensure_ascii=False, indent=2)
    return (
        f"\n--- HOST SOURCE PREPARATION {tag} (host-owned preparation metadata, "
        "not citable evidence) ---\n"
        "The host verified these pinned source and original-blob identities before "
        "this call. This does not attest that CP-0's triage, parsing, fidelity, "
        "representation or package workflow has run: author and validate P1-P8 "
        "yourself. Cite only the EVIDENCE section for source-content claims.\n"
        + (_PAGE_MAP_NOTE if maps else "")
        + body
        + f"\n--- END HOST SOURCE PREPARATION {tag} ---\n"
    )


def _research_section(identity: HostIdentity, tag: str = "") -> str:
    """CP-DR's bound brief as a host-owned section (§96), and nothing for any
    other module -- so every other module's prompt is byte for byte what it
    was. The brief is a run control, not evidence and not an instruction:
    its questions say what to research, and `source_mode: supplied_only`
    says that every answer rests on the EVIDENCE section alone."""
    if identity.research_brief is None:
        return ""
    body = json.dumps(
        research_brief_of(identity), sort_keys=True, ensure_ascii=False, indent=2
    )
    return (
        f"\n--- RESEARCH BRIEF {tag} (host-owned run control: the pinned research "
        "brief with its host-filled bindings -- run_id, cp0_sha256, "
        "authority_sha256. It is a bounded plan, not evidence and not an "
        "instruction to search: source_mode supplied_only means web research is "
        "absent here, so answer every question from the EVIDENCE section alone, "
        "record what it cannot answer as UNRESOLVED, and cite only the evidence "
        "below) ---\n" + body + f"\n--- END RESEARCH BRIEF {tag} ---\n"
    )


def _evidence_section(delivered: Sequence[Delivery]) -> str:
    """Every delivered line under one `source_id`/`page` header per run.

    Blocks are separated by one blank line and groups by two, so a line is
    never cut or merged and the header is paid once per page rather than
    once per line. Grouping follows the delivered order (source, then block),
    so a page's lines stay together as the store ordered them.
    """
    groups: list[tuple[tuple[UUID, int], list[str]]] = []
    for item in delivered:
        key = (item.source_id, item.page)
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append(item.text.value)
    return "\n\n\n".join(
        f"source_id: {source_id}\npage: {page}\n\n" + "\n\n".join(lines)
        for (source_id, page), lines in groups
    )


def build_handoff_prompt(  # noqa: PLR0913 -- one prompt, each input keyword-only
    contract: VendorContract,
    *,
    identity: HostIdentity,
    authority: DeliveredAuthority,
    catalog: Mapping[str, Any],
    delivered: Sequence[Delivery],
    upstream: Sequence[tuple[UpstreamRef, bytes]],
    upstream_citations: Mapping[str, tuple[AnchoredCitation, ...]],
    route: ResolvedRoute,
    source_set: SourceSet | None = None,
    page_maps: Mapping[UUID, Mapping[str, int]] | None = None,
    retry_feedback: Sequence[str] = (),
) -> str:
    """The task, the host-owned front matter, the host's own steps, every
    delivered authority file, upstream, its citation register, evidence.

    `authority` is this module's delivered set (§45.1): each file whole, UTF-8,
    in its own section named with its digest, `SKILL.md` first; any other
    module's set, or a file that is not UTF-8, refuses
    `AUTHORITY_BYTES_MISMATCH`. `upstream` must be exactly `identity.upstream`
    with bytes that hash to each ref, each labelled with its edge's
    `allowed_use` from `catalog`. `upstream_citations` maps exactly those refs'
    route nodes to their accepted records' anchored citations, each non-empty
    (`ROUTE_IDENTITY_INVALID` otherwise), rendered as a register that is
    context, never evidence. CP-0's T8 modules are the pinned route's,
    never a caller's list. Section markers carry a tag derived from every
    section's own bytes, the host-owned front matter included, so neither a
    section's text nor a host-owned field value can reproduce one. CP-0 also
    receives its host-verified pinned source metadata as context, never as
    evidence; it must still author and validate its P1-P8 workflow. Nothing is
    cut or summarised; the caller bounds it with `within_request_ceiling`.
    Evidence carries one header per `(source_id, page)` run of `delivered`
    (ordered by source then block) and nothing per line: the citation rule is
    stated once, in the final check, and it is the rule `verify_citations`
    enforces. `retry_feedback` is non-empty only on a node's one second
    attempt (D30): the checks its refused answer failed, rendered last and
    folded into the tag, so a first attempt's bytes are exactly what they were
    and the refused answer could not have known the markers around them.
    """
    if identity.module_id not in ADAPTER_MODULES:
        raise Refusal(RefusalCode.HANDOFF_MODULE_UNSUPPORTED)
    if (source_set is None) != (identity.module_id != GATE_MODULE) or (
        source_set is not None
        and {member.source_id for member in source_set.members}
        != {item.source_id for item in delivered}
    ):
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
    if (
        tuple(ref for ref, _ in upstream) != identity.upstream
        or identity.route_node_id not in {n.route_node_id for n in route.nodes}
        or set(upstream_citations) != {ref.route_node_id for ref in identity.upstream}
        or not all(upstream_citations.values())
    ):
        raise Refusal(RefusalCode.ROUTE_IDENTITY_INVALID)
    if (
        authority.module_id != identity.module_id
        or not authority.files
        or authority.files[0][0] != SKILL
    ):
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    gate_expects = (
        frozenset(n.module_id for n in route.nodes) - {GATE_MODULE, MODEL_MODULE}
        if identity.module_id == GATE_MODULE
        else frozenset()
    )
    uses = allowed_uses(catalog, route, identity.module_id)
    owned = owned_objects(catalog, route, identity.module_id)
    gate = (
        _GATE_INSTRUCTION.format(module_ids=", ".join(sorted(gate_expects)))
        if gate_expects
        else ""
    )
    evidence = _evidence_section(delivered)
    sections = (
        _HOST_STEPS
        + _authority_sections(authority, "")
        + _upstream_section(upstream, uses, owned)
        + _citation_register(upstream, upstream_citations)
        + _research_section(identity)
        + _source_preparation_section(source_set, "", page_maps)
        + evidence
    )
    # Host-owned values join the derivation: none of them can pre-compute a tag.
    host_fields = invocation_fields(contract, identity)
    front_matter = _yaml(host_fields)
    feedback = _feedback_lines(retry_feedback)
    untagged = front_matter + sections + feedback
    tag = hashlib.sha256(untagged.encode("utf-8")).hexdigest()[:16]
    prompt = (
        _INSTRUCTION.format(
            module_id=identity.module_id,
            module_name=identity.module_name,
            route_node_id=identity.route_node_id,
            filename=expected_filename(identity),
        )
        + gate
        + _TAGGED.format(tag=tag)
        + f"\n--- HOST-OWNED FRONT MATTER {tag} (copy exactly) ---\n"
        + front_matter
        + f"\n--- END HOST-OWNED FRONT MATTER {tag} ---\n"
        + f"\n--- HOST-PERFORMED STEPS {tag} ---\n"
        + _HOST_STEPS
        + f"--- END HOST-PERFORMED STEPS {tag} ---\n"
        + _authority_sections(authority, tag)
        + _upstream_section(upstream, uses, owned, tag)
        + _citation_register(upstream, upstream_citations, tag)
        + _research_section(identity, tag)
        + _source_preparation_section(source_set, tag, page_maps)
        + f"\n--- EVIDENCE {tag} ---\n"
        + evidence
        + f"\n--- END EVIDENCE {tag} ---\n"
    )
    if identity.module_id in {"CP-1", "CP-2G", "CP-4"} and any(
        n.module_id == MODEL_MODULE for n in route.nodes
    ):
        prompt += "\n" + _FORECAST_EXTENSION.format(tag=tag)
    canonical_headings = contract.validate_handoff.CANONICAL_HEADINGS
    headings = " -> ".join(canonical_headings)
    # CP-DR authors its three research verdict fields beside the common ones;
    # the vendor's validator requires them of CP-DR alone.
    required = (
        *contract.validate_handoff.REQUIRED_FIELDS,
        *(
            contract.validate_handoff.CP_DR_FIELDS
            if identity.module_id == RESEARCH_MODULE
            else ()
        ),
    )
    authored_fields = ", ".join(name for name in required if name not in host_fields)
    prompt += _FINAL_CHECK.format(
        tag=tag,
        heading_count=len(canonical_headings),
        headings=headings,
        authored_fields=authored_fields,
        source_ids=json.dumps(
            sorted({str(item.source_id) for item in delivered}), separators=(",", ":")
        ),
    )
    if identity.module_id == GATE_MODULE:
        t8_header = "| " + " | ".join(contract.navigation.NEW_HEADERS) + " |"
        prompt += _CP0_FINAL_CHECK.format(tag=tag, t8_header=t8_header)
    return prompt + _retry_section(tag, feedback)


def _feedback_lines(lines: Sequence[str]) -> str:
    """A second attempt's checks as the block lists them; empty on a first."""
    return "".join(f"- {line}\n" for line in lines)


def _retry_section(tag: str, feedback: str) -> str:
    """The last section of a node's one second attempt (D30), or nothing."""
    return _RETRY_FEEDBACK.format(tag=tag, messages=feedback) if feedback else ""


def request_size(provider: CompletionProvider, prompt: str) -> int:
    """The whole request the provider would send for `prompt`, in bytes, or
    `CONTEXT_OVER_CEILING` past `MAX_REQUEST_BYTES` (§45.3).

    Model, parameters and JSON escapes, not the prompt's encoding alone. A
    canonical call always asks for a JSON object, so that is the request
    measured. The number is what the call is priced and reserved on (Task 8.2),
    so the bytes bounded and the bytes paid for are the same bytes.
    """
    measured = len(provider.request_bytes(prompt, json_object=True))
    if measured > MAX_REQUEST_BYTES:
        raise Refusal(RefusalCode.CONTEXT_OVER_CEILING)
    return measured


def within_request_ceiling(provider: CompletionProvider, prompt: str) -> str:
    """`prompt`, bounded by `request_size`."""
    request_size(provider, prompt)
    return prompt
