"""Golden-output parity between the legacy `server` snapshot and `caos` (spec §10).

A package rather than a bare directory so that `mypy tests` sees
`parity.test_digest` beside `tests/test_digest.py` instead of two modules of
one name, and so the group tests import `parity.cases` from the `tests/` root.
"""
