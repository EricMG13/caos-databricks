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

The call streams (F511). Four live runs stopped PROVIDER_UNAVAILABLE after 138
to 300 s with no charge, short of `TIMEOUT_SECONDS`. An idle cut on a call
that sends no byte until it is done was one candidate, unconfirmed: calls of
334 to 358 s completed whole, and what the wire did is not known (F513 now
names it). Streamed, the provider sends keep-alives and tokens as it works,
and a provider error arrives as an SSE `error` event; `invoke` still returns
one message with the whole text, the usage and the completion id
`caos.models` reads.

The stream is read here, not by `ChatOpenAI`'s own streaming (F512). OpenRouter
repeats `role` on every delta and sends its usage in a frame that repeats the
`finish_reason` in one choice, where OpenAI sends an empty `choices`; the
library's JSON-mode stream summed the roles into `assistantassistant`, dropped
the usage of what was then no assistant message and joined the finishes into
`stopstop`, so the first live streamed call was refused
PROVIDER_RESPONSE_INVALID. `streamed_message` reads the frames as OpenRouter
documents them: the content deltas alone (reasoning deltas never join the
answer), the first stated finish, the usage frame's counts and the stream's
id. An SSE `error` event raises the client's `APIError`, which the seam types
as PROVIDER_UNAVAILABLE; a stream that ends without a finish or a usage is
an answer the seam refuses.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from caos.provider import MAX_COMPLETION_TOKENS, TIMEOUT_SECONDS

if TYPE_CHECKING:
    import httpx
    from langchain_core.callbacks import CallbackManagerForLLMRun

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


def _whole(value: object) -> int | None:
    """A count the usage states: a whole, non-negative number, else None."""
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _usage(stated: object) -> UsageMetadata | None:
    """The usage frame's counts, or None when it states no whole input and
    output count: an unknown charge, never a zero one."""
    if not isinstance(stated, Mapping):
        return None
    sent = _whole(stated.get("prompt_tokens"))
    answered = _whole(stated.get("completion_tokens"))
    if sent is None or answered is None:
        return None
    total = _whole(stated.get("total_tokens"))
    usage = UsageMetadata(
        input_tokens=sent,
        output_tokens=answered,
        total_tokens=sent + answered if total is None else total,
    )
    details = stated.get("completion_tokens_details")
    reasoning = (
        _whole(details.get("reasoning_tokens"))
        if isinstance(details, Mapping)
        else None
    )
    if reasoning is not None:
        usage["output_token_details"] = {"reasoning": reasoning}
    return usage


def _first_choice(frame: Mapping[str, Any], text: list[str]) -> str | None:
    """Add the first choice's content delta to `text`; its finish, if stated."""
    for choice in frame.get("choices") or ():
        if choice.get("index", 0) != 0:
            continue
        content = (choice.get("delta") or {}).get("content")
        if isinstance(content, str):
            text.append(content)
        stated = choice.get("finish_reason")
        return stated if isinstance(stated, str) and stated else None
    return None


def streamed_message(frames: Iterable[Mapping[str, Any]]) -> AIMessage:
    """One assistant message from a stream's chat-completion frames, read as
    OpenRouter sends them (F512): the first choice's content deltas up to the
    first stated `finish_reason`, that finish once, the usage the stream
    states, and the stream's id. Nothing is filled in: a stream that states no
    finish or no usage gives a message without one, which the seam refuses."""
    text: list[str] = []
    finish: str | None = None
    usage: UsageMetadata | None = None
    metadata: dict[str, Any] = {}
    for frame in frames:
        for name, key in (("id", "id"), ("model_name", "model")):
            if isinstance(frame.get(key), str):
                metadata.setdefault(name, frame[key])
        if finish is None:
            finish = _first_choice(frame, text)
        if frame.get("usage") is not None:
            usage = _usage(frame["usage"])
    if finish is not None:
        metadata["finish_reason"] = finish
    return AIMessage(
        content="".join(text), response_metadata=metadata, usage_metadata=usage
    )


class OpenRouterChat(ChatOpenAI):
    """`ChatOpenAI` whose every call streams on the wire and is read by
    `streamed_message` (F512): the request is the one `ChatOpenAI` builds,
    with `stream` and `stream_options.include_usage` set."""

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        payload = self._get_request_payload(messages, stop=stop, **kwargs)
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        with self.client.create(**payload) as stream:
            message = streamed_message(frame.model_dump() for frame in stream)
        return ChatResult(generations=[ChatGeneration(message=message)])


def openrouter_chat_model(
    model: str = MODEL, *, http_client: httpx.Client | None = None
) -> BaseChatModel:
    """A streaming chat model over OpenRouter, or a `RuntimeError` naming the
    missing name. `http_client` is the test seam: a fake transport, no network."""
    key = os.environ.get(KEY_ENV)
    if not key:
        unset = f"{KEY_ENV} is unset: live tests cannot run"
        raise RuntimeError(unset)
    extra_body = extra_body_from_environment()

    # The same deadline and no retry below the seam as the production model
    # (F40): the library's defaults (600 s, two retries) held a live run on
    # the wire for over half an hour before this was set.
    return OpenRouterChat(
        base_url=BASE_URL,
        api_key=SecretStr(key),
        model=model,
        max_completion_tokens=MAX_COMPLETION_TOKENS,
        timeout=TIMEOUT_SECONDS,
        max_retries=0,
        extra_body=extra_body or None,
        # `_generate` streams itself; the library's own stream never runs.
        disable_streaming=True,
        http_client=http_client,
    )
