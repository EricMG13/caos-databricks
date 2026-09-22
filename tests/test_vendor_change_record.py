"""The vendor change record is an exact projection of Git history."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "docs" / "VENDOR_CHANGES.md"
EXPECTED_DIFF_BASE = "8dee6ab160a42bd3e800647eed89f4e98827b0a5"


def test_vendor_change_inventory_matches_git() -> None:
    text = RECORD.read_text()
    base_match = re.search(r"Vendor diff base: `([0-9a-f]{40})`", text)
    inventory_match = re.search(
        r"## Exact changed-path inventory\n\n(.*?)(?=\n## |\Z)", text, re.DOTALL
    )

    assert base_match, "vendor diff base is not recorded"
    assert inventory_match, "exact vendor changed-path inventory is not recorded"
    assert base_match.group(1) == EXPECTED_DIFF_BASE, "vendor diff base changed"

    lines = [line for line in inventory_match.group(1).splitlines() if line]
    assert all(re.fullmatch(r"- `[^`]+`", line) for line in lines), (
        "vendor inventory contains a malformed line"
    )
    recorded = [line[3:-1] for line in lines]
    assert len(recorded) == len(set(recorded)), "vendor inventory contains duplicates"

    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            base_match.group(1),
            "HEAD",
            "--",
            "vendor/deploy-v",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    actual = [
        path.removeprefix("vendor/deploy-v/") for path in result.stdout.splitlines()
    ]

    assert recorded == sorted(recorded), "vendor inventory must be sorted"
    assert recorded == actual
