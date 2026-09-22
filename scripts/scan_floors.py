#!/usr/bin/env python3
"""Refuse a scanner report that covered nothing, or that failed to parse a file.

bandit 1.7.10 reaches for `ast.Constant.s`, which newer interpreters no longer
provide: under Python 3.14 it skips every server file and exits 0. A green SAST
gate that scanned nothing is worse than a red one, because it is believed.
See docs/AI_CODE_QUALITY.md section 4.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from tracked import tracked_python

# Cobertura carries `filename` on `<class>` and on no other element, so this is
# the set of files the report measured.
MEASURED = re.compile(r'\bfilename="([^"]*)"')


def scanned_targets(report: Mapping[str, object]) -> list[str]:
    """The targets a Trivy report actually examined.

    An image report with no Results at all is the same failure as a bandit
    report with no metrics: the scan ran, exited zero, and looked at nothing.
    """
    results = report.get("Results")
    if not isinstance(results, list):
        return []
    return [
        str(result.get("Target"))
        for result in results
        if isinstance(result, dict) and result.get("Target")
    ]


def covered_files(report: Mapping[str, object]) -> list[str]:
    """The files a bandit report actually measured, excluding its own totals row."""
    metrics = report.get("metrics")
    if not isinstance(metrics, dict):
        return []
    return [name for name in metrics if name != "_totals"]


def cobertura_metrics(report: str) -> Mapping[str, object]:
    """A Cobertura coverage report normalised to the shape the floors already read.

    A coverage report is a scanner report and falls through the same floor: one
    that measured nothing is a report SonarQube imports as a number rather than
    as an error. Read as text rather than parsed -- `xml.etree` is vulnerable to
    entity expansion (bandit B314) for one attribute of one element.
    """
    return {"metrics": {name: {} for name in MEASURED.findall(report)}}


def report_within(path: Path, base: Path) -> Path:
    """`path` resolved, provided it lies under `base`; refused otherwise.

    `report` is the one argument that reaches the filesystem, so nothing
    stopped `scan_floors.py ../../etc/passwd` reading a file outside the
    tree. A scanner report is a build output of the tree being scanned, so
    it is read only from under the directory the gate ran in.

    `os.path.realpath` and `startswith` rather than `Path.resolve` and
    `is_relative_to`: this is the documented sanitizer shape for the rule
    that flags this (bandit path-traversal, SonarPython S8707-class).
    """
    resolved = os.path.realpath(path)
    root = os.path.realpath(base)
    # The separator is load-bearing: "/base-secret/x" starts with "/base".
    if not resolved.startswith(root + os.sep):
        message = (
            f"{path} is outside {base}; a scanner report is read only from "
            "under the directory the gate was invoked in"
        )
        raise ValueError(message)
    return Path(resolved)


def _parse_errors(report: Mapping[str, object]) -> list[object]:
    errors = report.get("errors")
    return list(errors) if isinstance(errors, list) else []


@dataclass(frozen=True, slots=True)
class Claims:
    """What the scan says it covers, what it says it does not, and what exists.

    Between `cover` and `unscanned` every tracked `.py` must be claimed. The
    third category -- a file neither list mentions -- is the one nobody decided
    about, and it is a failure rather than a default, because the alternative is
    a directory joining the tree and being scanned by nothing.
    """

    cover: tuple[str, ...] = ()
    unscanned: tuple[str, ...] = ()
    tracked: tuple[str, ...] = ()

    def _under(self, path: str, roots: tuple[str, ...]) -> bool:
        return any(path == root or path.startswith(f"{root}/") for root in roots)

    def skipped(self, covered: frozenset[str]) -> list[str]:
        """Tracked files this scan claimed to cover and did not measure."""
        return [
            path
            for path in self.tracked
            if self._under(path, self.cover) and path not in covered
        ]

    def unclaimed(self) -> list[str]:
        """Tracked files neither list mentions."""
        return [
            path
            for path in self.tracked
            if not self._under(path, self.cover)
            and not self._under(path, self.unscanned)
        ]


def floor_failures(
    report: Mapping[str, object],
    *,
    min_files: int = 1,
    no_parse_errors: bool = False,
    claims: Claims | None = None,
) -> list[str]:
    """One line per floor the report fell through."""
    failures = []
    covered = covered_files(report)
    if len(covered) < min_files:
        failures.append(
            f"scanned {len(covered)} files, floor is {min_files}; "
            "a scan that scanned nothing is a failure"
        )
    errors = _parse_errors(report)
    if no_parse_errors and errors:
        failures.append(f"report carries {len(errors)} parse error(s)")
    if claims is not None:
        failures.extend(_claim_failures(claims, frozenset(covered)))
    return failures


def _claim_failures(claims: Claims, covered: frozenset[str]) -> list[str]:
    failures = []
    skipped = claims.skipped(covered)
    if skipped:
        failures.append(
            f"the scan covers {', '.join(claims.cover)} but did not measure "
            f"{len(skipped)} tracked file(s): {', '.join(sorted(skipped))}"
        )
    unclaimed = claims.unclaimed()
    if unclaimed:
        failures.append(
            f"{len(unclaimed)} tracked file(s) claimed by neither --cover nor "
            f"--unscanned: {', '.join(sorted(unclaimed))}"
        )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--min-files", type=int, default=1)
    parser.add_argument("--no-parse-errors", action="store_true")
    parser.add_argument("--trivy", action="store_true")
    parser.add_argument("--cover", nargs="*", default=[])
    parser.add_argument("--unscanned", nargs="*", default=[])
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--cobertura",
        action="store_true",
        help="read a Cobertura coverage report rather than a bandit JSON one",
    )
    args = parser.parse_args(argv)

    try:
        report_path = report_within(args.report, Path.cwd())
    except ValueError as refusal:
        parser.error(str(refusal))
    text = report_path.read_text(encoding="utf-8")
    # `--trivy` reads the scanner's own JSON, so it takes the same branch a
    # bandit report does; only `--cobertura` reshapes what was read.
    report = cobertura_metrics(text) if args.cobertura else json.loads(text)

    if args.trivy:
        targets = scanned_targets(report)
        if not targets:
            print(
                f"{args.report}: the image scan examined no targets; "
                "a scan that scanned nothing is a failure",
                file=sys.stderr,
            )
            return 1
        print(f"image scan examined {len(targets)} target(s)")
        return 0

    claims = None
    if args.cover:
        repo = args.repo.resolve()
        claims = Claims(
            cover=tuple(args.cover),
            unscanned=tuple(args.unscanned),
            tracked=tuple(str(path.relative_to(repo)) for path in tracked_python(repo)),
        )
    failures = floor_failures(
        report,
        min_files=args.min_files,
        no_parse_errors=args.no_parse_errors,
        claims=claims,
    )
    for line in failures:
        print(f"{args.report}: {line}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
