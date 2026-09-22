#!/usr/bin/env python3
"""Refuse a qualification set that names a document the document register does not.

The programme's remaining work is deploying pathways, and every pathway needs
documents its modules demand. Which documents those are is a reading of the
vendored SKILL.md files, and a reading decays: a set gets a new document, the
register is not updated, and nobody can say afterwards where the bytes came
from or whether the owner still has to source something.

So the register is half hand-authored and half emitted. `qualification/
documents.json` carries what only a person can say -- the demand, the public
location, the status. This script carries what only the tree can say -- which
documents the sets actually name, and each one's digest and size from the bytes
on disk -- and refuses when the two disagree.

It fetches nothing and admits nothing. The owner sources every document; the
coordinator admits it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

STATUSES = frozenset({"in_hand", "to_source", "to_author", "not_available"})

# caos/provider.py's ceiling on the whole encoded request. A document larger
# than this cannot reach a prompt whole, whatever else is true of it.
MAX_REQUEST_BYTES = 1_048_576


class UnknownStatus(ValueError):
    """A register row whose status is not one of the four the register declares."""

    def __init__(self, row_id: str, status: str) -> None:
        super().__init__(f"{row_id}: unknown status {status!r}")


@dataclass(frozen=True)
class Document:
    """One register row: a hand-authored demand plus what the bytes say."""

    id: str
    issuer: str | None
    document: str
    modules: tuple[str, ...]
    pathways: tuple[str, ...]
    source: str | None
    status: str
    local_path: str | None
    external_path: str | None
    demand_verified: bool
    note: str


@dataclass(frozen=True)
class Register:
    """The hand-authored half, as read."""

    documents: tuple[Document, ...]
    key_sources: tuple[dict[str, str], ...]


def load_register(path: Path) -> Register:
    """Reads `documents.json`, refusing a row whose status is not one of the four."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for entry in payload["documents"]:
        status = entry["status"]
        if status not in STATUSES:
            raise UnknownStatus(entry["id"], status)
        rows.append(
            Document(
                id=entry["id"],
                issuer=entry["issuer"],
                document=entry["document"],
                modules=tuple(entry["modules"]),
                pathways=tuple(entry["pathways"]),
                source=entry["source"],
                status=status,
                local_path=entry["local_path"],
                external_path=entry["external_path"],
                demand_verified=bool(entry["demand_verified"]),
                note=entry["note"],
            )
        )
    return Register(
        documents=tuple(rows),
        key_sources=tuple(payload.get("key_sources", ())),
    )


def set_documents(root: Path) -> dict[str, tuple[str, ...]]:
    """Every document the `qualification/*/qualification.json` sets name.

    Keyed by set name, with each path relative to the repository root, which is
    the spelling a register row carries.
    """
    found: dict[str, tuple[str, ...]] = {}
    for manifest in sorted(root.glob("*/qualification.json")):
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        named = [
            str((manifest.parent / document).relative_to(root.parent))
            for case in payload.get("cases", ())
            for document in case.get("documents", ())
        ]
        found[manifest.parent.name] = tuple(dict.fromkeys(named))
    return found


def measured(document: Document, repo: Path) -> tuple[int, str] | None:
    """Size and SHA-256 of the row's in-tree bytes, or None when it has none.

    Never the `external_path`: the table is held equal to a committed file on
    every machine, and an out-of-tree folder exists on one. Its measurements
    belong in the row's `note`, dated."""
    if document.local_path is None:
        return None
    path = repo / document.local_path
    if not path.is_file():
        return None
    raw = path.read_bytes()
    return len(raw), hashlib.sha256(raw).hexdigest()


def unlisted(register: Register, sets: dict[str, tuple[str, ...]]) -> list[str]:
    """One line per set document no register row claims as its `local_path`."""
    listed = {row.local_path for row in register.documents if row.local_path}
    return [
        f"{name}: {document!r} is named by the set and absent from the register"
        for name, documents in sorted(sets.items())
        for document in documents
        if document not in listed
    ]


def misplaced(register: Register, repo: Path) -> list[str]:
    """One line per `in_hand` row that is not a file under `qualification/`."""
    found = []
    for row in register.documents:
        if row.status != "in_hand":
            continue
        if row.local_path is None:
            found.append(f"{row.id}: claims in_hand with no local_path")
            continue
        path = repo / row.local_path
        if not path.is_file():
            found.append(
                f"{row.id}: claims in_hand and {row.local_path!r} is not a file"
            )
        elif not row.local_path.startswith("qualification/"):
            found.append(f"{row.id}: claims in_hand outside qualification/")
    return found


def report(register: Register, repo: Path) -> str:
    """The register table, emitted so that `DOCUMENTS.md`'s table is never typed."""
    lines = [
        "| id | issuer | document | status | modules | pathways | bytes |"
        " fits ceiling | sha256 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in register.documents:
        facts = measured(row, repo)
        size = str(facts[0]) if facts else "—"
        digest = f"`{facts[1][:16]}…`" if facts else "—"
        fits = (
            "—" if not facts else ("yes" if facts[0] <= MAX_REQUEST_BYTES else "**no**")
        )
        lines.append(
            f"| `{row.id}` | {row.issuer or '—'} | {row.document} | {row.status} |"
            f" {', '.join(row.modules)} | {', '.join(row.pathways)} |"
            f" {size} | {fits} | {digest} |"
        )
    for key in register.key_sources:
        lines.append(
            f"| `{key['id']}` | {key['issuer']} | {key['document']} |"
            " **key source, never admitted** | — | — | — | — | — |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--register", type=Path, default=REPO / "qualification/documents.json"
    )
    parser.add_argument(
        "--report", action="store_true", help="print the register table"
    )
    args = parser.parse_args(argv)

    register_path = args.register.resolve()
    root = register_path.parent
    repo = root.parent

    register = load_register(register_path)
    sets = set_documents(root)
    if not register.documents or not sets:
        print(
            f"read {len(register.documents)} register rows and {len(sets)}"
            " qualification sets; a scan that scanned nothing is a failure",
            file=sys.stderr,
        )
        return 2

    found = unlisted(register, sets) + misplaced(register, repo)
    for line in found:
        print(line, file=sys.stderr)
    if args.report and not found:
        print(report(register, repo))
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
