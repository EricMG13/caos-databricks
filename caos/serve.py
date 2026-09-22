"""The one process a Databricks App runs: the API, with the worker beside it.

`app.yaml` runs `python -m caos.serve`. The bind host comes from the
environment (`CAOS_BIND_HOST`; the App sets the platform's all-interfaces
address, local development keeps loopback) and the port from
`DATABRICKS_APP_PORT`, which the platform injects. The worker thread starts
only when `CAOS_WORKER_IN_PROCESS=1` (D11), and a refused configuration is
printed as its typed code while the API still serves.
"""

from __future__ import annotations

import os
import sys
from threading import Event

import uvicorn

from caos.graph.worker import start_in_process

BIND_HOST = "CAOS_BIND_HOST"
PORT = "DATABRICKS_APP_PORT"
LOCAL_PORT = 8000
# One uvicorn worker, a bounded number of in-flight requests (legacy §53).
LIMIT_CONCURRENCY = 32


def main() -> int:
    stopping = Event()
    worker = start_in_process(stopping)
    try:
        uvicorn.run(
            "caos.api.site:application",
            host=os.environ.get(BIND_HOST) or "127.0.0.1",
            port=int(os.environ.get(PORT) or LOCAL_PORT),
            limit_concurrency=LIMIT_CONCURRENCY,
            proxy_headers=False,
        )
    finally:
        stopping.set()
        if worker is not None:
            worker.join(timeout=30)
    return 0


if __name__ == "__main__":
    sys.exit(main())
