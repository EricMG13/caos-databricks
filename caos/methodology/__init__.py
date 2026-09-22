"""The methodology boundary: the bundle, the registry, the calculator seam."""

from __future__ import annotations

# The one host adapter every run pins (`docs/DECISIONS.md` §42.1, retired
# dispatch). A route with a module outside `handoff.ADAPTER_MODULES` pins it
# too and is refused at execution and acceptance (§42.2).
CANONICAL_ADAPTER_VERSION = "canonical-markdown-v3"
