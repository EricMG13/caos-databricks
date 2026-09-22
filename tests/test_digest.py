"""caos/digest.py: the one canonical JSON encoding every digest site shares."""

from __future__ import annotations

from hashlib import sha256

import pytest

from caos.digest import canonical_digest, canonical_json


def test_key_order_and_whitespace_do_not_change_the_digest() -> None:
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert canonical_digest({"b": 1, "a": 2}) == canonical_digest({"a": 2, "b": 1})


def test_non_ascii_is_kept_as_itself_not_escaped() -> None:
    assert canonical_json({"name": "Société"}) == '{"name":"Société"}'


def test_a_non_finite_number_refuses_rather_than_serialising() -> None:
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})
    with pytest.raises(ValueError):
        canonical_json({"x": float("inf")})


def test_the_digest_is_sha256_of_the_canonical_json_utf8() -> None:
    value = {"case_id": "c1", "body": [1, 2, 3]}
    assert (
        canonical_digest(value)
        == sha256(canonical_json(value).encode("utf-8")).hexdigest()
    )
