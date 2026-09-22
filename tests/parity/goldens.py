"""Where the goldens live and how a group's manifest is read and written.

`golden/<group>/manifest.json` names every case with the SHA-256 of its
canonical JSON output, and `golden/<group>/<case>.json` holds that output. The
manifest digest is over `canonical(output)`, never over the file's bytes, so a
formatter's trailing newline changes nothing.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Mapping
from pathlib import Path

from parity.cases import Json, Target, canonical, sha256_hex

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
MANIFEST = "manifest.json"


def caos_target() -> Target:
    """The new package, imported from this repository."""
    return Target(importlib.import_module("caos"))


def manifest_path(group: str, base: Path = GOLDEN_DIR) -> Path:
    return base / group / MANIFEST


def golden_path(group: str, name: str, base: Path = GOLDEN_DIR) -> Path:
    return base / group / f"{name}.json"


def read_manifest(group: str, base: Path = GOLDEN_DIR) -> dict[str, str]:
    """Case name to output digest, as the generator wrote it."""
    document = json.loads(manifest_path(group, base).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("cases"), dict):
        message = f"{group}: manifest carries no cases object"
        raise TypeError(message)
    cases = document["cases"]
    return {str(name): str(digest) for name, digest in cases.items()}


def read_golden(group: str, name: str, base: Path = GOLDEN_DIR) -> Json:
    """One case's recorded output; `Json` because the writer wrote `canonical`."""
    loaded: Json = json.loads(
        golden_path(group, name, base).read_text(encoding="utf-8")
    )
    return loaded


def write_group(
    group: str, outputs: Mapping[str, Json], *, package: str, base: Path = GOLDEN_DIR
) -> dict[str, str]:
    """Write every case of `group` and its manifest; return the manifest's cases."""
    directory = base / group
    directory.mkdir(parents=True, exist_ok=True)
    digests: dict[str, str] = {}
    for name in sorted(outputs):
        text = canonical(outputs[name])
        digests[name] = sha256_hex(text.encode("utf-8"))
        golden_path(group, name, base).write_text(text + "\n", encoding="utf-8")
    manifest: Json = {
        "group": group,
        "package": package,
        "cases": dict[str, Json](digests),
    }
    manifest_path(group, base).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return digests
