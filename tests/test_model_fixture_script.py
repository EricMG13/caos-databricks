"""The Model section's demo fixture is the credit model's own output."""

from __future__ import annotations

import json
from pathlib import Path

from model_fixture import build, dump

FIXTURE = (
    Path(__file__).resolve().parent.parent / "frontend" / "fixtures" / "model.json"
)


def test_the_committed_fixture_is_what_the_script_builds() -> None:
    text = FIXTURE.read_text(encoding="utf8")
    committed = json.loads(text)
    assert build(json.loads(text)) == committed
    # Minified, one line: the bytes `main` writes.
    assert dump(committed) + "\n" == text
    assert text.count("\n") == 1
    body = committed["body"]
    assert (body["currency"], body["unit"]) == ("USD", "MILLIONS")
    assert len(body["columns"]) == 23
    assert body["rate_deck"]["as_of"] == "2026-10-01"
