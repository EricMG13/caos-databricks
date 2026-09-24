"""Apply the hosted PR line-count policy to a caller-supplied base commit."""

from __future__ import annotations

import re
import shutil
import subprocess  # nosec B404
import sys

# This gate invokes only an absolute git executable with an argv list.

LIMIT = 800
EXCLUSIONS = (
    ":!*.lock",
    ":!requirements*.txt",
    # Root-anchored: git's default pathspec matching needs a `/` before the
    # name, so `**/vendor/**` would not match the bundle at `vendor/deploy-v/`.
    ":!vendor/**",
    ":!docs/**",
    # Immutable Phase 2 public evidence is indivisible; its manifests and
    # tests remain counted by this gate.
    ":!qualification/ccl-fy2025-full-relative-value/documents/**",
    ":!qualification/ccl-fy2025-lite-covenant-refinancing/documents/**",
    ":!qualification/ccl-fy2025-lite-full-credit-screen/documents/**",
    ":!qualification/ccl-fy2025-market-dislocation/documents/**",
    ":!qualification/save-2024-distressed-restructuring/documents/**",
    ":!qualification/save-2024-lite-distressed-restructuring/documents/**",
    # Immutable Phase 6 public evidence is also indivisible; each new set is
    # named explicitly so unrelated qualification changes remain counted.
    ":!qualification/ba-fy2025/documents/**",
    ":!qualification/ccl-fy2025-covenant-refinancing/documents/**",
    ":!qualification/ccl-fy2025-earnings-update/documents/**",
    ":!qualification/ccl-fy2025-liquidity/documents/**",
    ":!qualification/f-fy2025/documents/**",
    ":!qualification/vmo2-fy2025-full-deep-research/documents/**",
    ":!qualification/ccl-fy2025-relative-value/documents/CCL_FY2025_10K.txt",
    ":!qualification/ccl-fy2025-relative-value/documents/NCLH_Q4_2025_Earnings_Release.txt",
    ":!qualification/ccl-fy2025-relative-value/documents/RCL_Q4_2025_Earnings_Release.txt",
    ":!qualification/ccl-fy2025-relative-value/run-2026-09-18-capture.json",
    ":!qualification/ccl-fy2025-relative-value/run-2026-09-18b-capture.json",
    ":!qualification/vmo2-fy2025-deep-research/run-2026-09-18-capture.json",
    ":!qualification/vmo2-fy2025-deep-research/run-2026-09-18b-capture.json",
    ":!qualification/vmo2-fy2025-portfolio/run-2026-09-18b-capture.json",
    ":!qualification/vmo2-fy2025-portfolio/run-2026-09-18c-capture.json",
    ":!*package-lock.json",
    ":!frontend/fixtures/**",
)

# A git revision: branch, tag, or hex SHA, optionally with the ~/^/@ suffixes
# git itself accepts. Anchored full-match, not a blocklist: a base that is
# not entirely this shape is refused before it reaches argv, rather than
# only a base shaped like a known-bad option.
SAFE_REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/~^@-]*")


def changed_lines(base: str) -> int:
    git = shutil.which("git")
    if git is None:
        raise FileNotFoundError("git")
    # No shell: the caller's base is one opaque argv value. Command argument
    # injection (distinct from shell injection) is still possible without a
    # shell -- a base git could read as an option rather than a revision,
    # e.g. "--upload-pack=...". An anchored allowlist match is what refuses
    # that shape before base ever reaches argv.
    if not SAFE_REVISION.fullmatch(base):
        message = f"PR_BASE is not a plain git revision: {base!r}"
        raise ValueError(message)
    subprocess.run(  # nosec B603
        [git, "rev-parse", "--verify", f"{base}^{{commit}}"],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    # Fixed command and pathspec; the base is already refused above if it
    # could be read as an option, so the revision range is safe unquoted.
    result = subprocess.run(  # nosec B603
        [git, "diff", "--numstat", f"{base}...HEAD", "--", ".", *EXCLUSIONS],
        check=True,
        capture_output=True,
        text=True,
    )
    total = 0
    binary: list[str] = []
    for line in result.stdout.splitlines():
        added, removed, path = line.split("\t", 2)
        if added == "-" or removed == "-":
            # `git diff --numstat` prints "-\t-\t<path>" for a binary file:
            # no line count to add, and none was added (FP-10). Silently
            # skipping it let a PR add or change an unbounded binary blob
            # under no line-count ceiling at all; it is refused instead.
            binary.append(path)
            continue
        total += int(added) + int(removed)
    if binary:
        message = (
            "binary file(s) changed; this gate counts lines and cannot "
            f"measure them: {', '.join(binary)}"
        )
        raise ValueError(message)
    return total


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1]:
        print("PR_BASE is required: pass the exact PR base commit", file=sys.stderr)
        return 2
    try:
        count = changed_lines(sys.argv[1])
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError) as refusal:
        print(
            f"cannot measure the change against {sys.argv[1]}: {refusal}",
            file=sys.stderr,
        )
        return 2
    print(f"changed lines: {count}")
    if count > LIMIT:
        print("PR too large; split it", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
