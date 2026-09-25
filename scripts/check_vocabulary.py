#!/usr/bin/env python3
"""Refuse an identifier that spells a CONTEXT.md term by one of its synonyms.

Naming inconsistency is ~2x more frequent in agent-written code. CONTEXT.md
is the single glossary; this check is what makes it binding on code rather
than on intention.

Only identifiers are examined -- never prose, never string literals -- because
the defect being prevented is two spellings of one concept minting two lineages.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Iterator
from pathlib import Path

from tracked import tracked_python

REPO = Path(__file__).resolve().parents[1]
CONTEXT_MD = REPO / "CONTEXT.md"

# Synonyms with no plausible non-domain meaning in this repository. An
# identifier containing one of these is always the wrong word.
ENFORCED = frozenset(
    {
        "deal",
        "corpus",
        "chunk",
        "fragment",
        "passage",
        "footnote",
        "pipeline",
        "workflow",
        "ready_set",
        "benchmark",
        "golden_set",
    }
)

# Synonyms that also carry an ordinary technical meaning here. Enforcing them on
# identifiers would refuse `file_path`, `node_states`, `response_model` and the
# `users` table, so each is exempt for a stated reason instead of silently.
NOT_ENFORCED = {
    "project": "Python packaging metadata is a [project] table",
    "file": "a filesystem file is a file",
    "upload": "an HTTP multipart upload is an upload",
    "attachment": "email and docx attachments are attachments",
    "pack": "an intake pack is admitted or refused as a whole",
    "reference": "reference_files is the bundle's own field name",
    "agent": "an agent module is the bundle's own word for CP-CF and CP-DR",
    "step": "a build step or CI step is a step",
    "task": "an asyncio task is a task",
    "graph": "no domain use; retained for the frontend dependency drawing",
    "queue": "a work queue for model builds is a queue",
    "result": "subprocess and DB cursor results are results",
    "response": "an HTTP response is a response",
    "version": "source-set and schema versions are versions",
    "state": "node_states is the bundle's own word (CONTEXT.md node states)",
    "draft": "deliverable_drafts is the store's own table",
    "report": "a scanner report is a report (scan_floors.py)",
    "output": "max_output_tokens is the registry's own field name",
    "export": "static export and workbook export are the spec's words",
    "approval": "plan_approval is the registry's own field name",
    "sign_off_of_the_deliverable": "multi-word prose, not an identifier shape",
    "publication": "deliverable_publications is the spec's own table",
    "release": "a Deploy V release is a release (CLAUDE.md invariant 4)",
}


def _normalise(phrase: str) -> str:
    """Lower-case a phrase or identifier to underscore-joined word tokens.

    Two boundaries, not one: lower-to-upper (`loadDeal` -> `load_Deal`) and,
    since a run of capitals is itself one word, the acronym-to-word boundary
    inside it (`HTTPResponse` -> `HTTP_Response`). Splitting only the first
    left an acronym-prefixed spelling of a banned word -- `APICorpus` -- as
    one token that matched neither the word nor its plural.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", phrase)
    spaced = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", spaced)
    return re.sub(r"[^a-z0-9]+", "_", spaced.lower()).strip("_")


def banned_terms(context_md: str) -> dict[str, str]:
    """Map every synonym in CONTEXT.md's Domain table to the term it displaces."""
    banned: dict[str, str] = {}
    for line in context_md.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 3 or not cells[0].startswith("**"):
            continue
        term = cells[0].strip("*")
        for phrase in cells[2].split(","):
            token = _normalise(phrase)
            if token:
                banned[token] = term
    return banned


def unclassified(banned: dict[str, str]) -> tuple[set[str], set[str]]:
    """Synonyms CONTEXT.md declares but this file does not classify, and vice versa."""
    classified = set(ENFORCED) | set(NOT_ENFORCED)
    return set(banned) - classified, classified - set(banned)


def identifiers(tree: ast.Module) -> Iterator[tuple[int, str]]:
    """Every name this module defines: functions, classes, arguments, targets.

    A PEP 695 type parameter (`def f[Corpus](...)`, `class C[Chunk]:`) is a
    name this module defines as surely as an argument is: `ast.walk` already
    reaches it through the `type_params` field, but a `TypeVar`, `ParamSpec`
    or `TypeVarTuple` node carries its name as a plain string attribute, not
    a nested `ast.Name`, so it was walked past rather than classified. A
    `type X = ...` alias's own name is already a `Name` node in `Store`
    context and needs no separate branch.
    """
    for node in ast.walk(tree):
        name = _bound_name(node)
        if name:
            yield getattr(node, "lineno", 1), name


# Each node that binds a name, by the attribute holding it as a plain
# string. A star capture binds one as surely as a plain capture does (N4):
# `case [first, *rest]` through `MatchStar.name`, `case {**rest}` through
# `MatchMapping.rest`; `*_` and `case _` bind none.
_NAMED: dict[type[ast.AST], str] = {
    ast.FunctionDef: "name",
    ast.AsyncFunctionDef: "name",
    ast.ClassDef: "name",
    ast.arg: "arg",
    ast.ExceptHandler: "name",
    ast.MatchAs: "name",
    ast.MatchStar: "name",
    ast.MatchMapping: "rest",
    ast.TypeVar: "name",
    ast.ParamSpec: "name",
    ast.TypeVarTuple: "name",
}


def _bound_name(node: ast.AST) -> str | None:
    """The name `node` binds in this module, or None when it binds none."""
    if isinstance(node, ast.Name):
        return node.id if isinstance(node.ctx, ast.Store) else None
    if isinstance(node, ast.Attribute):
        return node.attr if isinstance(node.ctx, ast.Store) else None
    if isinstance(node, ast.alias):
        return node.asname or node.name
    attribute = _NAMED.get(type(node))
    value = getattr(node, attribute, None) if attribute else None
    return value if isinstance(value, str) and value else None


def violations(path: Path, banned: dict[str, str]) -> Iterator[str]:
    """One line per identifier that uses a synonym, naming the term to use instead."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    named = [(1, path.stem), *identifiers(tree)]
    for lineno, name in named:
        # Digits end a word as an underscore does (N4): `chunk2` is `chunk`.
        normalised = re.sub(r"_*[0-9]+_*", "_", _normalise(name)).strip("_")
        words = set(normalised.split("_"))
        # `chunks` is the same wrong word as `chunk`; plural collection
        # names are the shape agent-written code reaches for most.
        words |= {word[:-1] for word in words if word.endswith("s")}
        for token in ENFORCED:
            hit = token in normalised if "_" in token else token in words
            if hit:
                yield f"{path}:{lineno}: {name!r} says {token!r}; use {banned[token]!r}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args(argv)

    banned = banned_terms(CONTEXT_MD.read_text(encoding="utf-8"))
    missing, stale = unclassified(banned)
    if missing or stale:
        print(
            "CONTEXT.md and check_vocabulary.py disagree. "
            f"unclassified: {sorted(missing)}; not in CONTEXT.md: {sorted(stale)}",
            file=sys.stderr,
        )
        return 2

    paths = args.paths or tracked_python(REPO)
    if not paths:
        print(
            "scanned no files; a scan that scanned nothing is a failure",
            file=sys.stderr,
        )
        return 2

    found = [line for path in paths for line in violations(path, banned)]
    for line in found:
        print(line)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
