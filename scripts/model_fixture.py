"""Regenerate the Model section's demo fixture from the credit model itself.

The worked example's registers (`tests/credit_model_fixture.py`) go through
`credit_model()` and the read's own mapping, so every figure in
`frontend/fixtures/model.json` is the calculator's. The fixture's chrome and its
accepted CP-CF forecast are kept as they are.

    uv run python scripts/model_fixture.py
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURE = ROOT / "frontend" / "fixtures" / "model.json"


def build(document: dict[str, Any]) -> dict[str, Any]:
    """The document with the credit model's columns, lines, units and deck
    replaced by the worked example's."""
    sys.path.insert(0, str(ROOT / "tests"))
    example = importlib.import_module("credit_model_fixture")
    read = importlib.import_module("caos.api.reads.model")
    assemble = importlib.import_module("caos.calculators.credit_model.assemble")
    deck = example.example_deck()
    built = assemble.credit_model(
        assemble.ModelInputs(
            registers=example.example_registers(),
            request=example.example_request(),
            growth=example.example_growth(),
            slots=example.example_slots(),
            deck=deck,
        )
    )
    body = document["body"]
    body["currency"] = built.currency
    body["unit"] = built.unit
    body["rate_deck"] = (
        None
        if built.rate_deck_id is None
        else {"deck_id": "00000000-0000-4000-8000-0000000000d1", "as_of": deck.as_of}
    )
    body["columns"] = [
        read._column(column).model_dump(mode="json") for column in built.columns
    ]
    body["lines"] = [
        read._line(line, {}).model_dump(mode="json") for line in built.lines
    ]
    body["limitations"] = list(built.limitations)
    return document


def dump(document: dict[str, Any]) -> str:
    """The fixture's bytes: minified JSON on one line. It is generated, never
    reviewed by eye, and 108 lines of 23 cells are 50,000 lines pretty-printed."""
    return json.dumps(document, separators=(",", ":"))


def main() -> None:
    document = json.loads(FIXTURE.read_text(encoding="utf8"))
    FIXTURE.write_text(dump(build(document)) + "\n", encoding="utf8")


if __name__ == "__main__":
    main()
