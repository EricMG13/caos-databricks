"""The test-only OpenRouter adapter (spec section 3.4).

Only tests import this module. It builds a LangChain `ChatOpenAI` against
OpenRouter's OpenAI-compatible endpoint and hands it to the same
`caos.models.completions` seam production uses, so a live test drives the
real graph and the real executor with the only difference being who answers.
The key is read from the environment at call time and never stored; only
synthetic or public fixtures may travel through it (never client data); and
nothing here counts as gateway coverage.
"""

from __future__ import annotations

import os

from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr

from caos.provider import MAX_COMPLETION_TOKENS, TIMEOUT_SECONDS

KEY_ENV = "OPENROUTER_API_KEY"
BASE_URL = "https://openrouter.ai/api/v1"
# The same family the gateway endpoint serves (D7): Claude Opus 5, under the
# id OpenRouter serves (it lists no dated Anthropic ids).
MODEL = "anthropic/claude-opus-5"


def openrouter_chat_model(model: str = MODEL) -> BaseChatModel:
    """A chat model over OpenRouter, or a `RuntimeError` naming the missing name."""
    key = os.environ.get(KEY_ENV)
    if not key:
        unset = f"{KEY_ENV} is unset: live tests cannot run"
        raise RuntimeError(unset)
    from langchain_openai import ChatOpenAI

    # The same deadline and no retry below the seam as the production model
    # (F40): the library's defaults (600 s, two retries) held a live run on
    # the wire for over half an hour before this was set.
    return ChatOpenAI(
        base_url=BASE_URL,
        api_key=SecretStr(key),
        model=model,
        max_completion_tokens=MAX_COMPLETION_TOKENS,
        timeout=TIMEOUT_SECONDS,
        max_retries=0,
    )
