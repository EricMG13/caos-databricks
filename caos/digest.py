"""The one canonical JSON serialisation the digesting sites share.

Several places in this tree turn a value into bytes and hash it, each writing
the same four `json.dumps` flags out longhand -- `caos/evidence/ingest.py`
did, and `caos/store/extraction_integrity.py`, `caos/store/run_inputs.py`
and `caos/store/source_sets.py` each imported that module's private
`_digest` to reuse it, a cross-module import of an underscore-prefixed name.
They are the same four flags because the result is a stored digest -- an
extraction identity, a run-input fingerprint, a source-set snapshot, a
command receipt -- and two sites that disagree by a flag produce two digests
for one value.

Every flag earns its place. `sort_keys` and `separators` make one value into
one string. `ensure_ascii=False` keeps a non-ASCII string as itself rather
than as escapes, which is only safe because the string is encoded UTF-8 here
and nowhere else. `allow_nan=False` refuses `NaN` and `Infinity`, which are
not JSON and would be a digest over bytes no other reader could parse.

The sites that escape non-ASCII (`caos/store/audit.py`,
`caos/deliverable/filing.py`, `caos/graph/route.py`,
`caos/store/routes.py`, `caos/qualification/matrix.py` and
`caos/qualification/store.py`) are deliberately not here: `ensure_ascii`
moves the bytes for any non-ASCII input, so folding them in would invalidate
every digest already stored.

Two more sites spell the same four flags out and are still not callers, for a
different reason -- both use `ensure_ascii=False` already, matching this
module exactly, but each is pinned against a different constraint.
`caos/deliverable/canonical.py` writes the payload that is signed, so a
caller change there is a signature-format change and not a refactor.
`caos/calculators/cash_flow.py` is byte-pinned by
`icm/HOST_INTEGRITY_v1.json` -- an edit of any kind there
refuses `AUTHORITY_BYTES_MISMATCH`, so its longhand stays exactly as it is.

This function computes byte-identical output to the `_digest` it replaces:
relocating it changes no stored digest.
"""

from __future__ import annotations

import json
from hashlib import sha256


def canonical_json(value: object) -> str:
    """One value, one string. Raises `ValueError` on a non-finite number."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_digest(value: object) -> str:
    """The SHA-256 of `canonical_json(value)` encoded UTF-8."""
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()
