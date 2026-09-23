"""The one process a Databricks App runs: the API, with the worker beside it.

`app.yaml` runs `python -m caos.serve`. The bind host comes from the
environment (`CAOS_BIND_HOST`; the App sets the platform's all-interfaces
address, local development keeps loopback) and the port from
`DATABRICKS_APP_PORT`, which the platform injects. The worker thread starts
only when `CAOS_WORKER_IN_PROCESS=1` (D11), and a refused configuration is
printed as its typed code while the API still serves.

On the platform's SIGTERM uvicorn stops taking connections, gives the open
ones `GRACEFUL_SECONDS` to end, then runs the app's shutdown, which drains
the worker (DP-4): `stopping` is set and the thread is given
`LIMIT_JOIN_SECONDS` to finish the node in flight, all inside the grace the
platform allows before it kills the process. A call still on the wire past
that is abandoned with its reservation held and the run is reclaimed after
its lease. uvicorn re-raises the signal after shutdown, so nothing after
`uvicorn.run` can be relied on to run; the drain lives in the lifespan.
"""

from __future__ import annotations

import logging
import os
import sys
from threading import Event

import uvicorn

from caos.api.app import on_shutdown
from caos.api.stream import STREAM_LIMIT
from caos.graph.worker import start_in_process

BIND_HOST = "CAOS_BIND_HOST"
PORT = "DATABRICKS_APP_PORT"
LOCAL_PORT = 8000
# One uvicorn worker, a bounded number of connections (legacy §53). uvicorn
# counts idle keep-alive connections too (DP-7), so the bound leaves every
# event-stream slot open and forty more for requests and the proxy's pool.
LIMIT_CONCURRENCY = STREAM_LIMIT + 40
# Inside the platform's grace before SIGKILL, with the drain after it.
GRACEFUL_SECONDS = 2
LIMIT_JOIN_SECONDS = 12
SERVER_LOGGER = "uvicorn.error"


class _NoExceptionText(logging.Filter):
    """uvicorn logs an unhandled fault with its traceback, which carries
    `str(exc)` and so may carry document text (AS-6). The edge already
    writes the class and the frame; the traceback is dropped here."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info is not None:
            record.exc_info = None
            record.exc_text = None
        return True


def install_log_filter() -> None:
    """Strip exception text from uvicorn's error log (AS-6); idempotent."""
    logger = logging.getLogger(SERVER_LOGGER)
    if not any(isinstance(f, _NoExceptionText) for f in logger.filters):
        logger.addFilter(_NoExceptionText())


def main() -> int:
    install_log_filter()
    stopping = Event()
    worker = start_in_process(stopping)

    def drain() -> None:
        stopping.set()
        if worker is None:
            return
        worker.join(timeout=LIMIT_JOIN_SECONDS)
        word = "abandoned" if worker.is_alive() else "stopped"
        print(f"worker {word}", file=sys.stderr)

    on_shutdown(drain)
    try:
        uvicorn.run(
            "caos.api.site:application",
            host=os.environ.get(BIND_HOST) or "127.0.0.1",
            port=int(os.environ.get(PORT) or LOCAL_PORT),
            limit_concurrency=LIMIT_CONCURRENCY,
            timeout_graceful_shutdown=GRACEFUL_SECONDS,
            proxy_headers=False,
        )
    finally:
        drain()
    return 0


if __name__ == "__main__":
    sys.exit(main())
