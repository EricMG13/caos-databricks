"""The HTTP surface: what reaches a browser, and what is refused before it does."""

from __future__ import annotations


# No request path serves anything yet, so no module here declares an IO_BUDGET.
# The floor scripts/io_budget.py enforces keys on this directory; the first route
# brings the first budget with it.
