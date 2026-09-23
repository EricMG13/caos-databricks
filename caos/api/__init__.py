"""The HTTP surface: what reaches a browser, and what is refused before it does."""

from __future__ import annotations

# The package itself serves no request path, so it costs the store nothing;
# `scripts/io_budget.py` reads every module of this directory, its packages'
# own included (DQ-10).
IO_BUDGET = 0
