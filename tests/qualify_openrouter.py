#!/usr/bin/env python3
"""Drive `scripts/qualify.py` through the test-only OpenRouter adapter (spec 3.4).

Production qualification runs through the gateway provider `from_environment`
builds. Before a workspace exists, the only model that can answer is the one
OpenRouter serves, and OpenRouter lives under `tests/` alone, so this wrapper
hands the driver a provider built from the adapter and otherwise runs it
unchanged: same store, same blobs, same ceilings, same proof.

    OPENROUTER_API_KEY=... CAOS_MODEL_ENDPOINT=anthropic/claude-opus-5 \\
    CAOS_MODEL_PRICE=anthropic/claude-opus-5,0.000005,0.000025,2026-09-23 \\
    CAOS_QUALIFY_POSTGRES_URL=... CAOS_QUALIFY_BLOB_ROOT=... \\
    uv run python tests/qualify_openrouter.py qualification/ccl-fy2025 \\
        --expect-identity openrouter/anthropic/claude-opus-5/none/65536 --ceiling 14.00

The identity names OpenRouter, never the gateway: a verdict measured here is
not gateway coverage (AR-22), and the key is read by the adapter at call time
and never stored or printed.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any

PLATFORM = "openrouter"
REPO = Path(__file__).resolve().parents[1]


def main(argv: list[str]) -> int:
    for entry in (str(REPO), str(REPO / "scripts"), str(REPO / "tests")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    # The driver is a script, not a package member: loaded by name once the
    # path holds `scripts/`, the way `tests/conftest.py` lets the suite do.
    qualify: Any = importlib.import_module("qualify")
    from openrouter_adapter import openrouter_chat_model

    from caos.models import ChatCompletions
    from caos.pricing import price_from_environment
    from caos.provider import MAX_COMPLETION_TOKENS

    class OpenRouterCompletions(ChatCompletions):
        """The seam's provider with the identity a test measurement must carry."""

        @property
        def qualification_identity(self) -> str:
            effort = self.reasoning_effort or "none"
            return "/".join((PLATFORM, self.model, effort, str(MAX_COMPLETION_TOKENS)))

    def from_environment() -> ChatCompletions:
        """The adapter's model, priced from the same two names the worker reads."""
        model = os.environ.get("CAOS_MODEL_ENDPOINT", "")
        price = price_from_environment(model, os.environ.get("CAOS_MODEL_PRICE", ""))
        return OpenRouterCompletions(openrouter_chat_model(model), model, price)

    qualify.from_environment = from_environment
    return int(qualify.main(argv))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
