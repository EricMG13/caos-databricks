"""The test-only OpenRouter adapter (spec section 3.4).

Only tests import this module. It builds a LangChain `ChatOpenAI` against
OpenRouter's OpenAI-compatible endpoint and hands it to the same
`caos.models.completions` seam production uses, so a live test drives the
real graph and the real executor with the only difference being who answers.
The key is read from the environment at call time and never stored; only
synthetic or public fixtures may travel through it (never client data); and
nothing here counts as gateway coverage.

Two optional names, read at call time, shape the request (F479). With neither
set the request is the one this module always sent. `OPENROUTER_REASONING_EFFORT`
(`minimal`, `low`, `medium`, `high` or `xhigh`) sends `reasoning: {"effort": ...}`;
`OPENROUTER_PROVIDER` (a comma-separated list of provider names or endpoint
tags such as `openai/flex`) sends `provider: {"order": [...], "allow_fallbacks":
false}`, so a call never lands on a host that was not named. Both travel in the
`ChatOpenAI` `extra_body`. Production never sends an effort (N2, AR-15); this is
test-only.

The identity a verdict binds is one plain string, so `qualify.py
--expect-identity` stays a string compare: `openrouter/<model>/<effort>/<max
tokens>`, with `none` as the effort when none is sent, and `openrouter/<model>@
<order>/<effort>/<max tokens>` when a provider pin is set, `<order>` the
pinned names joined by `,`. For example `openrouter/openai/gpt-6-luna/high/65536`
and `openrouter/openai/gpt-6-luna-pro@openai/flex/none/65536`.

The call streams (F511). A long call sent whole sent no byte until the answer
was done, and three live runs were cut after about 195 to 299 s with no
generation and no charge, short of `TIMEOUT_SECONDS`. Streamed, the provider
sends keep-alives and tokens as it works; `invoke` still returns one message
with the whole text, the usage (`stream_usage`) and, in JSON mode -- the mode
every module call uses -- the completion id `caos.models` reads.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr

from caos.provider import MAX_COMPLETION_TOKENS, TIMEOUT_SECONDS

if TYPE_CHECKING:
    import httpx

KEY_ENV = "OPENROUTER_API_KEY"
EFFORT_ENV = "OPENROUTER_REASONING_EFFORT"
PROVIDER_ENV = "OPENROUTER_PROVIDER"
EFFORTS = ("minimal", "low", "medium", "high", "xhigh")
PLATFORM = "openrouter"
BASE_URL = "https://openrouter.ai/api/v1"
# The same family the gateway endpoint serves (D7): Claude Opus 5, under the
# id OpenRouter serves (it lists no dated Anthropic ids).
MODEL = "anthropic/claude-opus-5"


def effort_from_environment() -> str | None:
    """The reasoning effort to send, or None; anything outside `EFFORTS` is refused.

    An empty or whitespace-only value counts as unset, and matching is
    case-sensitive: `High` is refused, not folded to `high`."""
    effort = os.environ.get(EFFORT_ENV, "").strip()
    if not effort:
        return None
    if effort not in EFFORTS:
        bad = f"{EFFORT_ENV} must be one of {', '.join(EFFORTS)}"
        raise RuntimeError(bad)
    return effort


def provider_order_from_environment() -> tuple[str, ...]:
    """The pinned provider names or endpoint tags, in order; empty when unpinned."""
    listed = os.environ.get(PROVIDER_ENV, "").split(",")
    return tuple(name.strip() for name in listed if name.strip())


def extra_body_from_environment() -> dict[str, object]:
    """The OpenRouter fields the two names ask for; empty when neither is set."""
    body: dict[str, object] = {}
    effort = effort_from_environment()
    if effort:
        body["reasoning"] = {"effort": effort}
    order = provider_order_from_environment()
    if order:
        body["provider"] = {"order": list(order), "allow_fallbacks": False}
    return body


def qualification_identity(model: str) -> str:
    """The profile a verdict binds: the model, the pin and the effort actually sent."""
    order = provider_order_from_environment()
    named = f"{model}@{','.join(order)}" if order else model
    effort = effort_from_environment() or "none"
    return "/".join((PLATFORM, named, effort, str(MAX_COMPLETION_TOKENS)))


def openrouter_chat_model(
    model: str = MODEL, *, http_client: httpx.Client | None = None
) -> BaseChatModel:
    """A streaming chat model over OpenRouter, or a `RuntimeError` naming the
    missing name. `http_client` is the test seam: a fake transport, no network."""
    key = os.environ.get(KEY_ENV)
    if not key:
        unset = f"{KEY_ENV} is unset: live tests cannot run"
        raise RuntimeError(unset)
    from langchain_openai import ChatOpenAI

    extra_body = extra_body_from_environment()

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
        extra_body=extra_body or None,
        streaming=True,
        stream_usage=True,
        http_client=http_client,
    )
