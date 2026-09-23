"""Repair Phase 4, slice 4.5b: `GET /api/health`.

`SYSTEM_SPEC.md` §11: liveness and readiness on one strict model -- store,
bundle, blob store -- 200 when all hold, 503 otherwise. The probes really run,
at most once per interval, on one background task with a deadline; the request
path only reads what the last round left, so it does no I/O of its own.
"""

from __future__ import annotations

import asyncio
import itertools
import shutil
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import pytest
from conftest import recorded_statements
from fake_chat import fake_completions
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

import caos.api.health as health
from caos.api.app import app
from caos.api.deps import BLOB_ROOT, DATABASE_URL, VENDORED_BUNDLE, _vendored_bundle
from caos.methodology.bundle import MANIFEST_NAME, Bundle
from caos.refusals import Refusal, RefusalCode
from caos.store import apply_schema, connect, verify_schema
from caos.store.work import beat


def _all(code: health.HealthCode) -> dict[str, Callable[[], health.HealthCode]]:
    return {name: (lambda: code) for name in health.PROBES}


def _ask(state: health.ProbeState | None) -> tuple[int, dict[str, object], str]:
    """The route's answer over the real app, without running its lifespan."""
    if state is None:
        vars(app.state).get("_state", {}).pop("health", None)
    else:
        app.state.health = state
    try:
        response = TestClient(app).get("/api/health")
    finally:
        vars(app.state).get("_state", {}).pop("health", None)
    return response.status_code, response.json(), response.headers["cache-control"]


def _round(state: health.ProbeState) -> None:
    asyncio.run(health.probe_once(state))


def test_health_is_200_only_when_store_bundle_and_blobs_hold(
    empty_database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with connect(empty_database) as conn:
        apply_schema(conn)
    monkeypatch.setenv(DATABASE_URL, empty_database)
    monkeypatch.setenv(BLOB_ROOT, str(tmp_path))

    status, body, _cache = _ask(None)
    assert status == 503
    assert str(body["python_version"]).startswith("3.13.")
    assert body["build_id"] == _vendored_bundle().build_id
    assert {
        k: v for k, v in body.items() if k not in ("python_version", "build_id")
    } == {
        "status": "not_ready",
        "store": "PROBE_NOT_RUN",
        "bundle": "PROBE_NOT_RUN",
        "blobs": "PROBE_NOT_RUN",
        "identity": "PROBE_NOT_RUN",
        "workers": "PROBE_NOT_RUN",
        "checked_at": None,
    }

    state = health.ProbeState()
    _round(state)
    status, body, cache = _ask(state)
    assert (status, body["status"], cache) == (200, "ready", "no-store")
    assert (body["store"], body["bundle"], body["blobs"]) == ("OK", "OK", "OK")
    # Nothing has beaten in this database, and the API is ready anyway: the
    # API is not the worker. Reporting the surface unready because a queue is
    # stalled would take the surface down with it.
    assert body["workers"] == "WORKERS_ABSENT"
    assert datetime.fromisoformat(str(body["checked_at"])).tzinfo is not None

    for failing in ("store", "bundle", "blobs", "identity"):
        probes = _all("OK")
        probes[failing] = lambda: "PROBE_TIMEOUT"
        one_down = health.ProbeState(probes=probes)
        _round(one_down)
        assert _ask(one_down)[:2][0] == 503, failing

    # The worker probe is reported and never gates readiness, whatever it says.
    for code in ("PROBE_TIMEOUT", "WORKERS_STALE", "WORKERS_BACKING_OFF"):
        probes = _all("OK")
        probes["workers"] = lambda code=code: code  # type: ignore[misc]
        queue_down = health.ProbeState(probes=probes)
        _round(queue_down)
        status, body, _cache = _ask(queue_down)
        assert (status, body["workers"]) == (200, code)


def test_each_failed_probe_names_its_code_and_answers_503(
    empty_database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(DATABASE_URL, raising=False)
    assert health.probe_store() == "STORE_NOT_CONFIGURED"
    monkeypatch.setenv(DATABASE_URL, "postgresql://nobody@127.0.0.1:1/none")
    assert health.probe_store() == "STORE_UNAVAILABLE"
    # Reachable, but no migration was ever applied to it.
    monkeypatch.setenv(DATABASE_URL, empty_database)
    assert health.probe_store() == "STORE_SCHEMA_DRIFT"

    root = tmp_path / "bundle"
    root.mkdir()
    assert health.probe_bundle(root, lambda: Bundle(VENDORED_BUNDLE)) == (
        "BUNDLE_INVALID"
    )
    shutil.copy(VENDORED_BUNDLE / MANIFEST_NAME, root / MANIFEST_NAME)
    held = Bundle(root)
    assert health.probe_bundle(root, lambda: held) == "OK"
    (root / MANIFEST_NAME).write_bytes(
        (root / MANIFEST_NAME).read_bytes().replace(b"{", b"{ ", 1)
    )
    assert health.probe_bundle(root, lambda: held) == "BUNDLE_MOVED"

    monkeypatch.delenv(BLOB_ROOT, raising=False)
    assert health.probe_blobs() == "BLOB_ROOT_UNAVAILABLE"
    monkeypatch.setenv(BLOB_ROOT, str(tmp_path / "absent"))
    assert health.probe_blobs() == "BLOB_ROOT_UNAVAILABLE"
    (tmp_path / "a-file").write_text("x")
    monkeypatch.setenv(BLOB_ROOT, str(tmp_path / "a-file"))
    assert health.probe_blobs() == "BLOB_ROOT_UNAVAILABLE"
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o500)
    monkeypatch.setenv(BLOB_ROOT, str(locked))
    try:
        assert health.probe_blobs() == "BLOB_ROOT_UNAVAILABLE"
    finally:
        locked.chmod(0o700)
    assert list(tmp_path.iterdir()) and not any(locked.iterdir())

    for code in ("STORE_SCHEMA_DRIFT", "BUNDLE_MOVED", "BLOB_ROOT_UNAVAILABLE"):
        state = health.ProbeState(probes=_all(code))
        _round(state)
        status, body, _cache = _ask(state)
        assert status == 503
        assert body["status"] == "not_ready"
        assert body["store"] == body["bundle"] == body["blobs"] == code


def test_probes_run_at_most_once_per_ttl_on_one_task() -> None:
    runs: list[str] = []
    release = Event()

    def slow() -> health.HealthCode:
        runs.append("store")
        release.wait(1)
        return "OK"

    probes = _all("OK")
    probes["store"] = slow
    state = health.ProbeState(probes=probes, interval=0.05)

    async def overlapping() -> None:
        first = asyncio.create_task(health.probe_once(state))
        await asyncio.sleep(0.01)
        # A round already in flight is not started again.
        await asyncio.gather(*(health.probe_once(state) for _ in range(5)))
        release.set()
        await first

    asyncio.run(overlapping())
    assert runs == ["store"]

    runs.clear()
    release.set()

    async def loop_for(seconds: float) -> None:
        task = asyncio.create_task(health.probe_loop(state))
        await asyncio.sleep(seconds)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(loop_for(0.3))
    assert 2 <= len(runs) <= 7

    # Asking does not probe: the route reads the last round.
    before = len(runs)
    for _ in range(5):
        _ask(state)
    assert len(runs) == before


def test_the_lifespan_starts_one_probe_task_and_stops_it(
    empty_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[health.ProbeState] = []
    real = health.probe_loop

    async def counted(state: health.ProbeState) -> None:
        started.append(state)
        await real(state)

    monkeypatch.setenv(DATABASE_URL, empty_database)
    monkeypatch.setattr(health, "probe_loop", counted)
    monkeypatch.setattr(health, "PROBES", _all("OK"))
    with TestClient(app) as client:
        answers = [client.get("/api/health").status_code for _ in range(5)]
        for _ in range(200):  # the first round lands on the lifespan's own loop
            if client.get("/api/health").status_code == 200:
                break
            asyncio.run(asyncio.sleep(0.01))
        assert client.get("/api/health").status_code == 200, answers
    assert len(started) == 1
    assert started[0].store == "OK"


def test_a_probe_past_its_deadline_is_a_timeout_not_awaited() -> None:
    never = Event()

    def hangs() -> health.HealthCode:
        never.wait(5)
        return "OK"

    probes = _all("OK")
    probes["blobs"] = hangs
    state = health.ProbeState(probes=probes, deadline=0.05)

    async def timed() -> float:
        loop = asyncio.get_running_loop()
        began = loop.time()
        await health.probe_once(state)
        return loop.time() - began

    try:
        elapsed = asyncio.run(timed())
    finally:
        never.set()
    assert elapsed < 1
    assert (state.store, state.bundle, state.blobs) == ("OK", "OK", "PROBE_TIMEOUT")
    assert health.PROBE_DEADLINE == 5.0
    assert health.PROBE_INTERVAL == 10.0
    assert health.STALE_AFTER == 30.0


def test_a_stale_result_is_not_ready() -> None:
    now = [100.0]
    state = health.ProbeState(
        probes=_all("OK"),
        clock=lambda: now[0],
        wall=lambda: datetime(2026, 9, 14, tzinfo=UTC),
    )
    _round(state)
    assert _ask(state)[0] == 200
    now[0] += health.STALE_AFTER + 1
    status, body, _cache = _ask(state)
    assert status == 503
    assert body["store"] == body["bundle"] == body["blobs"] == "PROBE_STALE"
    assert body["checked_at"] == "2026-09-14T00:00:00Z"


def test_the_health_request_opens_no_store_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[str] = []
    monkeypatch.setattr("caos.store.connect", lambda *a, **k: opened.append("connect"))
    monkeypatch.setattr(health, "connect", lambda *a, **k: opened.append("connect"))
    state = health.ProbeState(probes=_all("OK"))
    _round(state)
    _ask(state)
    _ask(None)
    assert opened == []
    assert health.IO_BUDGET == 0


def test_the_schema_probe_writes_nothing(empty_database: str) -> None:
    with connect(empty_database) as conn:
        with recorded_statements(conn) as statements, pytest.raises(Refusal) as caught:
            verify_schema(conn)
        assert caught.value.code is RefusalCode.STORE_SCHEMA_DRIFT
        conn.rollback()
        tables = conn.execute(
            "SELECT count(*) FROM information_schema.tables"
            " WHERE table_schema = current_schema()"
        ).fetchone()
        assert tables == (0,)

        apply_schema(conn)
        with recorded_statements(conn) as statements:
            verify_schema(conn)
        assert statements
        for statement in statements:
            assert statement.lstrip().upper().startswith("SELECT"), statement
            assert "advisory" not in statement.lower(), statement

        conn.execute("DELETE FROM store_migrations WHERE version = 13")
        with pytest.raises(Refusal) as drifted:
            verify_schema(conn)
        assert drifted.value.code is RefusalCode.STORE_SCHEMA_DRIFT
        conn.rollback()


def test_the_health_body_is_closed_and_carries_no_path_or_exception_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = str(tmp_path / "secret-root")

    def raises() -> health.HealthCode:
        raise OSError(secret)

    monkeypatch.setenv(BLOB_ROOT, secret)
    monkeypatch.setenv(DATABASE_URL, f"postgresql://role:pw@127.0.0.1:1/{secret}")
    state = health.ProbeState(
        probes={
            "store": health.probe_store,
            "bundle": raises,
            "blobs": raises,
            "identity": raises,
            "workers": raises,
        }
    )
    _round(state)
    status, body, _cache = _ask(state)
    assert status == 503
    assert set(body) == set(health.HealthDocument.model_fields)
    assert body["store"] == "STORE_UNAVAILABLE"
    assert body["bundle"] == "BUNDLE_INVALID"
    assert body["blobs"] == "BLOB_ROOT_UNAVAILABLE"
    text = str(body)
    for leaked in (secret, "pw", "127.0.0.1", "OSError", "Traceback"):
        assert leaked not in text
    with pytest.raises(ValueError, match="extra"):
        health.HealthDocument.model_validate({**body, "detail": "x"})


def test_health_needs_no_identity() -> None:
    (route,) = [
        inner
        for route in app.routes
        for inner in getattr(getattr(route, "original_router", None), "routes", [route])
        if isinstance(inner, APIRoute) and inner.path == "/api/health"
    ]
    assert route.endpoint is health.read_health
    assert route.dependant.dependencies == []
    state = health.ProbeState(probes=_all("OK"))
    _round(state)
    assert _ask(state)[0] == 200  # no role header, no subject


def test_the_identity_probe_asks_nothing_off_the_platform_and_the_workspace_on_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F43: off the platform there is nobody to ask; on it, a workspace that
    does not answer is `IDENTITY_UNAVAILABLE`, and that folds into `status`."""
    from caos.api.edge import PLATFORM_ENV

    monkeypatch.delenv(PLATFORM_ENV, raising=False)
    assert health.probe_identity() == "OK"
    monkeypatch.setenv(PLATFORM_ENV, "caos")
    monkeypatch.setenv("DATABRICKS_HOST", "http://127.0.0.1:9")
    monkeypatch.setenv("DATABRICKS_TOKEN", "unused-placeholder")
    monkeypatch.setattr(health, "PROBE_DEADLINE", 30.0)
    import caos.workspace as workspace

    monkeypatch.setattr(workspace, "HTTP_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(workspace, "RETRY_TIMEOUT_SECONDS", 1)
    assert health.probe_identity() == "IDENTITY_UNAVAILABLE"
    probes = _all("OK")
    probes["identity"] = lambda: "IDENTITY_UNAVAILABLE"
    state = health.ProbeState(probes=probes)
    _round(state)
    status, body, _cache = _ask(state)
    assert (status, body["status"], body["identity"]) == (
        503,
        "not_ready",
        "IDENTITY_UNAVAILABLE",
    )


def test_the_identity_probe_asks_the_workspace_the_way_a_request_asks_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EI-W1. The probe used to go through the SDK's client, which resolves
    its own host and asks its own way. Requests go through `identity.scim_me`
    with a hand-parsed `DATABRICKS_HOST`, so a host that parser rejects, a
    SCIM path that moved, or a token scope the workspace refuses made every
    request 401 or 503 while health still reported `ready`. Same path now, and
    only the credential comes from the SDK.
    """
    import caos.workspace as workspace
    from caos.api.edge import PLATFORM_ENV
    from caos.api.identity import WorkspaceUser
    from caos.api.identity import scim_me as identity_scim_me

    minted: dict[str, str] = {"Authorization": "Bearer minted-for-the-app"}
    unmintable = "the workspace would not mint one"

    class _Config:
        def authenticate(self) -> dict[str, str]:
            if not minted:
                raise OSError(unmintable)
            return dict(minted)

    class _Client:
        config = _Config()

    monkeypatch.setenv(PLATFORM_ENV, "caos")
    monkeypatch.setenv("DATABRICKS_HOST", "https://caos.cloud.databricks.com")
    monkeypatch.setattr(workspace, "workspace_client", _Client)
    asked: list[str] = []

    def answering(authorization: str) -> WorkspaceUser:
        asked.append(authorization)
        return WorkspaceUser(scim_id="42", groups=frozenset())

    monkeypatch.setattr(health, "scim_me", answering)
    assert health.probe_identity() == "OK"
    assert asked == ["Bearer minted-for-the-app"], "the SDK's own credential"

    # The scope failure EI-W1 names: SCIM refuses the process's own principal,
    # every request is then 401, and health used to say `ready` regardless.
    def refusing(authorization: str) -> WorkspaceUser:
        raise Refusal(RefusalCode.NOT_AUTHENTICATED)

    monkeypatch.setattr(health, "scim_me", refusing)
    assert health.probe_identity() == "IDENTITY_UNAVAILABLE"

    # A host the request path will not send a bearer to is not `ready` either,
    # and it is the request path's own parser that says so.
    monkeypatch.setenv("DATABRICKS_HOST", "http://workspace.example.com")
    monkeypatch.setattr(health, "scim_me", identity_scim_me)
    assert health.probe_identity() == "IDENTITY_UNAVAILABLE"

    # And credentials the SDK cannot mint at all are the same answer.
    monkeypatch.setattr(health, "scim_me", answering)
    minted.clear()
    assert health.probe_identity() == "IDENTITY_UNAVAILABLE"
    minted["Authorization"] = ""
    assert health.probe_identity() == "IDENTITY_UNAVAILABLE"


def _racing_clock() -> Callable[[], float]:
    """A monotonic clock that moves past every timer between two reads: a
    gate that expires on a timer (AR-11's ceiling) expires before each round,
    as it does at shipped values for a probe that really runs past it."""
    ticks = itertools.count(0.0, 60.0)
    return lambda: next(ticks)


def test_a_probe_still_running_is_never_started_twice() -> None:
    """ED-4 / MAX-02. The round-level gate expired on a timer, twice the
    deadline, so a probe that really ran longer -- a Lakebase mint abandoned
    at 30 s, a SCIM lookup, the SDK's retry budget -- had a second and a
    third copy started against a dependency already struggling, and a late
    return counted the next round's probe out. A probe now keeps the thread
    it runs on: while that thread lives it is not started again and answers
    `PROBE_TIMEOUT`, and the other probes run every round."""
    running: list[int] = []
    runs = [0]
    peak = [0]
    lock = threading.Lock()

    def slow() -> health.HealthCode:
        with lock:
            running.append(1)
            runs[0] += 1
            peak[0] = max(peak[0], len(running))
        time.sleep(0.25)  # five deadlines
        with lock:
            running.pop()
        return "OK"

    probes = _all("OK")
    probes["store"] = slow
    state = health.ProbeState(probes=probes, deadline=0.05, clock=_racing_clock())

    async def rounds() -> list[health.HealthCode]:
        seen = []
        for _ in range(8):
            await health.probe_once(state)
            seen.append(state.store)
            assert state.bundle == state.blobs == "OK"
            await asyncio.sleep(0.05)
        return seen

    seen = asyncio.run(rounds())

    assert peak[0] == 1, "a second copy of a probe still running"
    assert set(seen) == {"PROBE_TIMEOUT"}
    # Started again once the last copy returned, and only then.
    assert 2 <= runs[0] < len(seen)


def test_a_probe_that_never_returns_cannot_starve_the_others() -> None:
    """ED-4. Every probe ran on the loop's shared executor, so one that never
    returns -- the SDK's service-principal token POST carries no timeout --
    left a thread behind per round until the pool was full, and then a
    healthy store and bundle queued behind it into `PROBE_TIMEOUT` too. One
    copy of it, never two, and the rest keep answering."""
    never = Event()
    calls = [0]

    def hangs() -> health.HealthCode:
        calls[0] += 1
        never.wait(30)
        return "OK"

    probes = _all("OK")
    probes["identity"] = hangs
    state = health.ProbeState(probes=probes, deadline=0.05, clock=_racing_clock())

    async def rounds() -> None:
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(4))
        try:
            for _ in range(15):
                await health.probe_once(state)
                assert (state.store, state.bundle, state.blobs, state.workers) == (
                    "OK",
                    "OK",
                    "OK",
                    "OK",
                )
                assert state.identity == "PROBE_TIMEOUT"
        finally:
            never.set()

    asyncio.run(rounds())
    assert calls == [1], "a second copy of a probe that never returned"


def test_an_in_process_worker_answers_for_itself_not_the_fleet(
    empty_database: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """DF-1. Any fresh heartbeat answered `workers=OK`, so on a redeploy the
    previous process's last beat -- fresh for `WORKER_STALE_AFTER` -- stood
    in for a new process whose worker had refused to start, and the deploy's
    health row passed. In-process, the worker is a fact about this process:
    its thread alive, and its own row the only one read.

    The worker is started by `start_in_process` and beats under the id
    `_drive` gives it, so the thread name and the id are the worker's own.
    """
    from caos.graph import worker

    assert health.WORKER_IN_PROCESS == worker.IN_PROCESS
    monkeypatch.setenv(DATABASE_URL, empty_database)
    monkeypatch.setenv(health.WORKER_IN_PROCESS, "1")
    with connect(empty_database) as conn:
        apply_schema(conn)
        beat(conn, worker_id="worker-the-last-process", state="POLLING", faults=0)
        conn.commit()
    assert health.probe_workers() == "WORKERS_ABSENT", "another process's beat"

    beaten = Event()
    ids: list[str] = []

    def run_worker(config: worker.WorkerConfig, **_: object) -> int:
        ids.append(config.worker.value)
        with connect(empty_database) as conn:
            beat(conn, worker_id=config.worker.value, state="POLLING", faults=0)
            conn.commit()
        beaten.set()
        stopping.wait(10)
        return 0

    def configured() -> worker.Configured:
        return worker.Configured(
            completions=fake_completions(),
            url=empty_database,
            root=str(tmp_path),
            bundle=Bundle(VENDORED_BUNDLE),
            saver=MemorySaver(),
        )

    monkeypatch.setattr(worker, "_configured", configured)
    monkeypatch.setattr(worker, "module_execution", lambda *_: None)
    monkeypatch.setattr(worker, "run_worker", run_worker)
    stopping = Event()
    thread = worker.start_in_process(stopping)
    try:
        assert thread is not None and thread.name == health.WORKER_THREAD
        assert beaten.wait(10)
        assert ids == [health._own_worker()]
        assert health.probe_workers() == "OK"
        with connect(empty_database) as conn:
            beat(conn, worker_id=ids[0], state="BACKOFF", faults=3)
            conn.commit()
        assert health.probe_workers() == "WORKERS_BACKING_OFF", "its own row only"
    finally:
        stopping.set()
        if thread is not None:
            thread.join(10)
    assert health.probe_workers() == "WORKERS_ABSENT", "its row outlives it"
