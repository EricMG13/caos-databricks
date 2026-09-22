# Typed surface of the `databricks-langchain` names this repository uses.
# The package ships no `py.typed`; these signatures were read from its source
# at version 0.20.0 (docs/rebuild/decisions.md R10).
from databricks.sdk import WorkspaceClient
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult
from langgraph.checkpoint.postgres import PostgresSaver

class ChatDatabricks(BaseChatModel):
    def __init__(
        self,
        *,
        endpoint: str,
        max_tokens: int | None = ...,
        temperature: float | None = ...,
        extra_params: dict[str, object] | None = ...,
        workspace_client: WorkspaceClient | None = ...,
    ) -> None: ...
    @property
    def _llm_type(self) -> str: ...
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = ...,
        run_manager: CallbackManagerForLLMRun | None = ...,
        **kwargs: object,
    ) -> ChatResult: ...

class CheckpointSaver(PostgresSaver):
    def __init__(
        self,
        *,
        instance_name: str | None = ...,
        autoscaling_endpoint: str | None = ...,
        project: str | None = ...,
        branch: str | None = ...,
        workspace_client: WorkspaceClient | None = ...,
        schema: str | None = ...,
        min_size: int = ...,
        max_size: int = ...,
    ) -> None: ...
    def setup(self) -> None: ...
