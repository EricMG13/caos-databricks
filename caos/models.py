"""The one model factory: every production call goes through Databricks AI Gateway.

Spec section 3 (D7, D8). `chat_model` returns the LangChain chat model the host
talks to -- `ChatDatabricks` against the configured serving endpoint -- and
`ChatCompletions` adapts it to the `CompletionProvider` seam the canonical
executor was built on, so nothing downstream of this module knows which vendor
answered. Tests inject another `BaseChatModel` through `completions(chat=...)`;
the app package never imports one.

Two things differ from the legacy transport and are decided here, not hidden.
The charge is computed: a gateway response carries token counts, not money, so
the call is billed as `tokens x the dated price` under one Decimal context
(invariant 7). The generation id is the response's own when it names one; a
response that does not is given a host-minted one, prefixed so a reader can
tell, because an accepted artifact must be able to say what produced it
(invariant 3) and a blank would be refused outright.
"""

from __future__ import annotations

import contextvars
import hashlib
import math
import os
import threading
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from decimal import Decimal, DecimalException
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from openai import OpenAIError

from caos.pricing import ModelPrice, exact_context, price_from_environment
from caos.provider import (
    MAX_COMPLETION_TOKENS,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    NEVER_RETRIED,
    TIMEOUT_SECONDS,
    TRANSIENT,
    Completion,
    check_resend,
    encode_request,
    finish_refusal,
    reported_charge,
)
from caos.refusals import Refusal, RefusalCode
from caos.store.outcomes import producer_identifier

# The serving endpoint the gateway routes to. A bundle target sets it per
# workspace; the default is the pay-per-token Claude endpoint the spec names.
ENDPOINT_ENV = "CAOS_MODEL_ENDPOINT"
DEFAULT_ENDPOINT = "databricks-claude-opus-5"
# `model,input_per_token,output_per_token,YYYY-MM-DD` for exactly that endpoint.
MODEL_PRICE_ENV = "CAOS_MODEL_PRICE"
# Reserved for the effort passthrough (next.md N2): refused while it is not
# sent, so no identity ever names an effort the model did not receive (AR-15).
REASONING_EFFORT_ENV = "CAOS_REASONING_EFFORT"
PLATFORM = "databricks"
HOST_MINTED = "host-"
# A 429 reached no model, so it is asked again under the same reservation
# (DP-5): this many tries in all, waiting `Retry-After` up to the cap.
RATE_LIMITED = 429
RATE_LIMIT_TRIES = 3
RETRY_AFTER_SECONDS = 2.0
RETRY_AFTER_CAP_SECONDS = 20.0
_sleep = time.sleep
_clock = time.monotonic


def identity_of(model: str, reasoning_effort: str | None = None) -> str:
    """The execution profile a verdict binds (D8), from the names alone, so a
    caller can refuse an unexpected one before any client is built."""
    return "/".join(
        (PLATFORM, model, reasoning_effort or "none", str(MAX_COMPLETION_TOKENS))
    )


def configured_endpoint() -> str:
    """The endpoint the environment names, else the default."""
    return os.environ.get(ENDPOINT_ENV) or DEFAULT_ENDPOINT


def chat_model(*, endpoint: str | None = None) -> BaseChatModel:
    """The production chat model: `ChatDatabricks` on the configured endpoint.

    Imported here rather than at module load so the seam's tests, which inject
    their own model, never touch the Databricks SDK. Authentication is the
    SDK's unified chain -- the app's service-principal variables on Databricks
    Apps, a CLI profile locally -- and no credential is read by this code.
    """
    from databricks_langchain import ChatDatabricks

    from caos.workspace import workspace_client

    # A read deadline no longer than the whole call's (brief D5, F40, ST-9),
    # and no retry below the seam: a retry is the caller's reservation. The client
    # is the process's bounded one (CR-6): the default the library would
    # build carries the SDK's five-minute discovery budget.
    return ChatDatabricks(
        endpoint=endpoint or configured_endpoint(),
        max_tokens=MAX_COMPLETION_TOKENS,
        timeout=TIMEOUT_SECONDS,
        max_retries=0,
        workspace_client=workspace_client(),
    )


@dataclass(frozen=True, slots=True)
class ChatCompletions:
    """A `CompletionProvider` over one LangChain chat model, priced and identified.

    `model` is the endpoint name: the identity the host configured, which is
    what a run's price must name and what an accepted artifact records.
    """

    chat: BaseChatModel = field(repr=False)
    model: str
    price: ModelPrice
    reasoning_effort: str | None = None

    @property
    def qualification_identity(self) -> str:
        """The execution profile a qualification verdict binds (D8)."""
        return identity_of(self.model, self.reasoning_effort)

    def request_bytes(self, prompt: str, *, json_object: bool = False) -> bytes:
        """The request the call is priced on: model, prompt, ceiling, format."""
        return encode_request(self.model, prompt, json_object=json_object)

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion:
        """Ask once; a rate limit alone is asked again, under the same
        reservation and inside one deadline for the whole call (ST-9)."""
        if producer_identifier(self.model, limit=256) is None:
            raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED)
        if not isinstance(prompt, str) or (
            len(self.request_bytes(prompt, json_object=json_object)) > MAX_REQUEST_BYTES
        ):
            raise Refusal(RefusalCode.PROVIDER_CALL_INVALID)
        # JSON mode travels on the wire (F27): the legacy request carried it,
        # `request_bytes` already budgets for it, and the canonical executor
        # asks for it on every module call.
        options: dict[str, Any] = {}
        if json_object:
            options["response_format"] = {"type": "json_object"}
        # One deadline for every try and every wait (ST-9, MAX-21), so the
        # worst case the lease and the stale threshold are sized against is
        # `TIMEOUT_SECONDS`, not three of them and two waits.
        deadline = _clock() + TIMEOUT_SECONDS
        sent = 0
        while True:
            sent += 1
            answer = _invoked(self.chat, prompt, options, deadline - _clock())
            if isinstance(answer, OpenAIError):
                if not _waited_out(answer, sent, deadline):
                    return Completion(None, None, None, _status_refusal(answer))
                # Nothing was billed yet; what the caller installed decides
                # whether the call may still be made (ST-7), and raises if not.
                check_resend()
                continue
            if answer is None:
                # Indeterminate: the request may have been delivered and
                # billed, so the attempt keeps its reservation. Nothing of
                # the error travels.
                return Completion(None, None, None, RefusalCode.PROVIDER_UNAVAILABLE)
            if not isinstance(answer, AIMessage):
                return Completion(
                    None, None, None, RefusalCode.PROVIDER_RESPONSE_INVALID
                )
            return self._completion(prompt, answer, json_object=json_object)

    def _completion(
        self, prompt: str, message: AIMessage, *, json_object: bool = False
    ) -> Completion:
        content = _text(message.content)
        charge = self._charge(
            message.usage_metadata,
            sent=len(self.request_bytes(prompt, json_object=json_object)),
            answered=bool(content),
        )
        generation = producer_identifier(_claimed_id(message), limit=512)
        if generation is None:
            generation = (
                HOST_MINTED
                + hashlib.sha256(
                    (prompt + (content or "")).encode("utf-8", "surrogatepass")
                ).hexdigest()[:40]
            )
        # A finish reason the response does not state is not `stop` (F34):
        # `stop` is the one completed reason, and an answer with none is a
        # response the host does not understand.
        finish = message.response_metadata.get("finish_reason")
        refusal = (
            finish_refusal(finish)
            if isinstance(finish, str) and finish
            else RefusalCode.PROVIDER_RESPONSE_INVALID
        )
        if refusal is not None:
            return Completion(None, charge, generation, refusal)
        if content is None or charge is None:
            return Completion(
                None, charge, generation, RefusalCode.PROVIDER_RESPONSE_INVALID
            )
        if len(content.encode("utf-8", "surrogatepass")) > MAX_RESPONSE_BYTES:
            # Billed, never stored or parsed (F35): no prefix of an oversize
            # answer is an answer.
            return Completion(
                None, charge, generation, RefusalCode.PROVIDER_RESPONSE_INVALID
            )
        return Completion(content, charge, generation)

    def _charge(
        self, usage: Mapping[str, Any] | None, *, sent: int, answered: bool
    ) -> Decimal | None:
        """`tokens x price`, exact, or unknown when the usage is not accounting
        the host understands.

        Counts are whole and never negative (AR-14), and possible (ST-11,
        MAX-05): the client reads an absent or null count as zero, so a
        request billed no input, or an answer billed no output, is a count
        the provider never stated; no request carries more tokens than bytes
        (the premise `priced_request` reserves on) and no answer more than
        `MAX_COMPLETION_TOKENS`. The product is computed in the reservation's
        own exact context (MAX-N03), so it is refused rather than rounded.
        """
        if usage is None:
            return None
        try:
            input_tokens = _count(usage["input_tokens"], most=sent)
            output_tokens = _count(usage["output_tokens"], most=MAX_COMPLETION_TOKENS)
            if not input_tokens or (answered and not output_tokens):
                return None
            exact = exact_context()
            amount = exact.add(
                exact.multiply(Decimal(input_tokens), self.price.input_per_token),
                exact.multiply(Decimal(output_tokens), self.price.output_per_token),
            )
        except (KeyError, TypeError, ValueError, DecimalException):
            return None
        return reported_charge(amount)


def _count(value: object, *, most: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= most:
        raise ValueError
    return value


def _invoked(
    chat: BaseChatModel, prompt: str, options: dict[str, Any], seconds: float
) -> object:
    """One `invoke`: its answer, the vendor error it raised, or None when the
    call is indeterminate.

    Abandoned once `seconds` pass (ST-9): the client's timeout bounds each
    read, not the call, so a server that sends a byte at a time would hold it
    open with no limit, past the lease it was sized in. The call runs on a
    helper thread; an answer that has not arrived by the deadline is None, as
    a socket timeout is. An abandoned thread holds only its own socket and
    never writes to the store.

    Once the request may have been sent, whatever else the stack raises is
    None too (ST-8): an empty `choices` is an `IndexError` from the client,
    and no failure may escape untyped ahead of `record_outcome`.
    """
    answered: list[object] = []
    context = contextvars.copy_context()

    def send() -> None:
        with suppress(Exception):  # indeterminate, never text (ST-8)
            try:
                answered.append(
                    context.run(chat.invoke, [HumanMessage(content=prompt)], **options)
                )
            except OpenAIError as failed:
                answered.append(failed)

    sender = threading.Thread(target=send, name="caos-model-call", daemon=True)
    sender.start()
    sender.join(max(seconds, 0.0))
    return answered[0] if answered else None


def _waited_out(failed: OpenAIError, sent: int, deadline: float) -> bool:
    """Whether a rate limit was waited out and the call may be sent again: a
    429 reached no model (DP-5), within the tries, and the wait ends before
    the call's one deadline (ST-9)."""
    if not _rate_limited(failed) or sent >= RATE_LIMIT_TRIES:
        return False
    wait = _retry_after(failed)
    if wait >= deadline - _clock():
        return False
    _sleep(wait)
    return True


def _rate_limited(failed: OpenAIError) -> bool:
    return getattr(failed, "status_code", None) == RATE_LIMITED


def _retry_after(failed: OpenAIError) -> float:
    """The gateway's `Retry-After` in seconds, capped; the default otherwise."""
    headers = getattr(getattr(failed, "response", None), "headers", None)
    stated = headers.get("retry-after") if headers is not None else None
    try:
        seconds = float(stated) if isinstance(stated, str) else RETRY_AFTER_SECONDS
    except ValueError:
        seconds = RETRY_AFTER_SECONDS
    if not math.isfinite(seconds):
        # `nan` survives the clamp below and `sleep(nan)` raises (ST-8, MAX-16).
        seconds = RETRY_AFTER_SECONDS
    return min(max(seconds, 0.0), RETRY_AFTER_CAP_SECONDS)


# LangChain fills an id the response did not carry with its own run id, so a
# message id with this prefix names nothing the provider said (F36).
_LANGCHAIN_RUN_PREFIX = "lc_run"


def _claimed_id(message: AIMessage) -> object:
    """The id the response itself carried, or None: the completion's id when
    the client surfaced it, else the message id unless LangChain minted it."""
    claimed = message.response_metadata.get("id")
    if isinstance(claimed, str) and claimed:
        return claimed
    own = message.id
    if isinstance(own, str) and own.startswith(_LANGCHAIN_RUN_PREFIX):
        return None
    return own


def _status_refusal(failed: OpenAIError) -> RefusalCode:
    """A vendor error by its status class alone; its message never travels."""
    status = getattr(failed, "status_code", None)
    if isinstance(status, int) and status in NEVER_RETRIED:
        return RefusalCode.PROVIDER_CALL_INVALID
    if isinstance(status, int) and (status in TRANSIENT or status >= 500):
        return RefusalCode.PROVIDER_UNAVAILABLE
    return RefusalCode.PROVIDER_UNAVAILABLE


def _text(content: object) -> str | None:
    """The answer as one string, with a single code fence unwrapped.

    A chat model asked for JSON may wrap it in a fence; the fence is transport
    dressing, not the answer, so it is removed here and nowhere else. The
    envelope is still parsed and validated by the host (invariant 3).
    """
    if isinstance(content, list):
        parts = [
            part if isinstance(part, str) else str(part.get("text", ""))
            for part in content
            if isinstance(part, (str, dict))
        ]
        content = "".join(parts)
    if not isinstance(content, str):
        return None
    text = content.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1 and text.endswith("```"):
            text = text[first_newline + 1 : -3].strip()
    return text


def completions(
    price: ModelPrice,
    *,
    chat: BaseChatModel | None = None,
    endpoint: str | None = None,
    reasoning_effort: str | None = None,
) -> ChatCompletions:
    """The provider a run executes through, priced for exactly its endpoint.

    `chat` is the test seam: a suite passes its own `BaseChatModel` and the
    Databricks SDK is never imported. Production passes nothing and gets
    `chat_model()`.
    """
    name = endpoint or configured_endpoint()
    if price.model != name:
        raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED)
    return ChatCompletions(
        chat if chat is not None else chat_model(endpoint=name),
        name,
        price,
        reasoning_effort,
    )


def from_environment() -> ChatCompletions:
    """The provider the environment configures, or `PROVIDER_NOT_CONFIGURED`.

    Three names and nothing else; read at the call, never at import. Values
    are never printed.
    """
    endpoint = configured_endpoint()
    price = price_from_environment(endpoint, os.environ.get(MODEL_PRICE_ENV, ""))
    if os.environ.get(REASONING_EFFORT_ENV):
        # Not sent to the endpoint (next.md N2), so not configurable: an
        # identity naming an effort the model never received would bind
        # qualification verdicts to a profile that was not run (AR-15).
        raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED)
    return completions(price, endpoint=endpoint)
