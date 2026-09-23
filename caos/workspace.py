"""The one way this package builds a workspace client (F43).

The SDK's client performs a discovery probe when it is built and retries
under a five-minute budget by default, so every construction here carries
bounded budgets. Authentication is the SDK's unified chain -- the app's
service-principal variables on Databricks Apps, a CLI profile locally -- and
no credential is read by this code.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient

HTTP_TIMEOUT_SECONDS = 15
RETRY_TIMEOUT_SECONDS = 30


def workspace_client() -> WorkspaceClient:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.config import Config

    config = Config(
        http_timeout_seconds=HTTP_TIMEOUT_SECONDS,
        retry_timeout_seconds=RETRY_TIMEOUT_SECONDS,
    )
    return WorkspaceClient(config=config)
