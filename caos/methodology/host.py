"""The single CP-CF host extension, verified against its compiled manifest pin."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from caos.graph.route import MODEL_MODULE, ResolvedRoute
from caos.methodology.host_pin import HOST_MANIFEST_SHA256
from caos.refusals import Refusal, RefusalCode

HOST_ROOT = Path(__file__).resolve().parents[2] / "icm"
HOST_NAME = "CashFlowForecast"
_CODE = Path(__file__).resolve().parents[1] / "calculators/cash_flow.py"


def host_skill(root: Path = HOST_ROOT) -> dict[str, Any]:
    """Read the one host manifest within its ceiling and compiled identity."""
    try:
        with (root / "HOST_INTEGRITY_v1.json").open("rb") as stream:
            raw = stream.read(16385)
    except OSError:
        raw = b""
    if len(raw) > 16384 or sha256(raw).hexdigest() != HOST_MANIFEST_SHA256:
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    result: dict[str, Any] = json.loads(raw)
    return result


def verified_host_bytes(name: str, *, root: Path = HOST_ROOT) -> bytes:
    """Only two fixed files, neither a provider-selected path nor imported code."""
    entry = host_skill(root)["relative_file_hashes"].get(name)
    paths = {
        "SKILL.md": root / "stages/cp-cf/references/SKILL.md",
        "scripts/cash_flow.py": _CODE,
    }
    if name not in paths or not isinstance(entry, dict):
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    try:
        with paths[name].open("rb") as stream:
            data = stream.read(entry["bytes"] + 1)
    except OSError:
        data = b""
    if len(data) != entry["bytes"] or sha256(data).hexdigest() != entry["sha256"]:
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    return data


def verify_extension(route: ResolvedRoute) -> None:
    """A model node needs the supported pathway, pinned host and current code."""
    if not any(n.module_id == MODEL_MODULE for n in route.nodes):
        return
    if (route.profile_id, route.selection_id) != (
        "FULL_CREDIT_32",
        "RELATIVE_VALUE",
    ) or dict(route.predicates).get("host_manifest_sha256") != HOST_MANIFEST_SHA256:
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    for name in host_skill()["relative_file_hashes"]:
        verified_host_bytes(name)
