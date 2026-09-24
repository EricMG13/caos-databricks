"""Test-only support: end a run `RUN_FAILED`, with no artifact.

No production path produces `RunStatus.FAILED` (SI-7,
`docs/rebuild/findings-round2.md`): `complete_run`, `block_run` and
`cancel_run` each have a production caller in `caos/graph/runtime.py` or
`caos/graph/worker.py`, and `fail_run` had none -- it lived in
`caos/store/runs.py` only because the suite's fixtures needed a run ended
without an artifact, and RUN_FAILED is that shape. It is kept here instead,
so a reader of `caos/store/runs.py` sees only the transitions production
takes, and delegates to that module's own private `_transition` rather than
copying its transactional rule (locking, the exactly-once terminal event,
`mark_work_done`) a second time.
"""

from __future__ import annotations

from uuid import UUID

from caos.store import RunStatus, StoreConnection
from caos.store.events import RunEvent
from caos.store.runs import _transition
from caos.store.work import Lease


def fail_run(
    conn: StoreConnection, run_id: UUID, *, lease: Lease | None = None
) -> bool:
    """End a run without an artifact. Returns whether this call ended it."""
    return _transition(conn, run_id, RunStatus.FAILED, RunEvent.RUN_FAILED, lease)
