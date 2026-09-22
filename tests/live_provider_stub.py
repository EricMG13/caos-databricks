"""Harmless collection target for the live-provider selection gate tests."""

from __future__ import annotations

import pytest


@pytest.mark.live_provider
def test_harmless_live_provider_stub() -> None:
    """Prove explicit selection reaches a marked test without a provider call."""
    assert True
