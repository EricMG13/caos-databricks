"""The one way this package builds a workspace client (F43).

The SDK's client performs a discovery probe when it is built and retries
under a five-minute budget by default, so every construction here carries
bounded budgets. Authentication is the SDK's unified chain -- the app's
service-principal variables on Databricks Apps, a CLI profile locally -- and
no credential is read by this code.

One client per process and per identity (W2): a client costs host metadata
and OIDC discovery to build, and the SDK refreshes its own token source, so
building one per blob request and twice per health round was three round
trips each. The cache is keyed on the variables that name the workspace and
the principal, never on a secret. A construction that fails raises the typed
`STORE_UNAVAILABLE` (CR-1): the SDK reports an unreachable host or a refused
token as `ValueError`, and nothing above this seam catches that.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import TYPE_CHECKING

from caos.refusals import Refusal, RefusalCode

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient

HTTP_TIMEOUT_SECONDS = 15
RETRY_TIMEOUT_SECONDS = 30
# What names the workspace and the principal; a change to any of them is a
# different client (the loopback stand-in starts a new host per test).
IDENTITY_ENV = (
    "DATABRICKS_HOST",
    "DATABRICKS_CONFIG_PROFILE",
    "DATABRICKS_CLIENT_ID",
    "DATABRICKS_APP_NAME",
)


def workspace_client() -> WorkspaceClient:
    """The process's bounded client for this identity, or `STORE_UNAVAILABLE`."""
    return _client(tuple(os.environ.get(name, "") for name in IDENTITY_ENV))


@lru_cache(maxsize=8)
def _client(identity: tuple[str, ...]) -> WorkspaceClient:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.config import Config

    del identity  # the cache key; the SDK reads the same variables itself
    try:
        config = Config(
            http_timeout_seconds=HTTP_TIMEOUT_SECONDS,
            retry_timeout_seconds=RETRY_TIMEOUT_SECONDS,
        )
        return WorkspaceClient(config=config)
    except (ValueError, OSError):
        # The SDK's message names the host and the variables it read.
        raise Refusal(RefusalCode.STORE_UNAVAILABLE) from None


def forget_clients() -> None:
    """Drop every cached client (tests that stand up a new workspace)."""
    _client.cache_clear()
