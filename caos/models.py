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

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Context, Decimal, DecimalException
from typing import Any

from langchain_core.exceptions import LangChainException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from openai import OpenAIError

from caos.pricing import ModelPrice, price_from_environment
from caos.provider import (
    MAX_COMPLETION_TOKENS,
    MAX_REQUEST_BYTES,
    NEVER_RETRIED,
    TRANSIENT,
    Completion,
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
# Reserved for the effort passthrough (next.md N2); recorded, never sent.
REASONING_EFFORT_ENV = "CAOS_REASONING_EFFORT"
PLATFORM = "databricks"
HOST_MINTED = "host-"

# Exact arithmetic, no rounding: a charge is tokens times a per-token price and
# both are decimals with a handful of digits, so the product is exact.
_CHARGE_CONTEXT = Context(prec=60)


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

    return ChatDatabricks(
        endpoint=endpoint or configured_endpoint(), max_tokens=MAX_COMPLETION_TOKENS
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
        return "/".join(
            (
                PLATFORM,
                self.model,
                self.reasoning_effort or "none",
                str(MAX_COMPLETION_TOKENS),
            )
        )

    def request_bytes(self, prompt: str, *, json_object: bool = False) -> bytes:
        """The request the call is priced on: model, prompt, ceiling, format."""
        return encode_request(self.model, prompt, json_object=json_object)

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion:
        """Ask once; never retry (a retry is the caller's reservation)."""
        if producer_identifier(self.model, limit=256) is None:
            raise Refusal(RefusalCode.PROVIDER_NOT_CONFIGURED)
        if not isinstance(prompt, str) or (
            len(self.request_bytes(prompt, json_object=json_object)) > MAX_REQUEST_BYTES
        ):
            raise Refusal(RefusalCode.PROVIDER_CALL_INVALID)
        try:
            message = self.chat.invoke([HumanMessage(content=prompt)])
        except OpenAIError as failed:
            return Completion(None, None, None, _status_refusal(failed))
        except (OSError, ValueError, RuntimeError, LangChainException):
            # Indeterminate: the request may have been delivered and billed, so
            # the attempt keeps its reservation. Nothing of the error travels.
            return Completion(None, None, None, RefusalCode.PROVIDER_UNAVAILABLE)
        if not isinstance(message, AIMessage):
            return Completion(None, None, None, RefusalCode.PROVIDER_RESPONSE_INVALID)
        return self._completion(prompt, message)

    def _completion(self, prompt: str, message: AIMessage) -> Completion:
        charge = self._charge(message.usage_metadata)
        generation = producer_identifier(
            message.id or message.response_metadata.get("id"), limit=512
        )
        content = _text(message.content)
        if generation is None:
            generation = (
                HOST_MINTED
                + hashlib.sha256(
                    (prompt + (content or "")).encode("utf-8", "surrogatepass")
                ).hexdigest()[:40]
            )
        finish = message.response_metadata.get("finish_reason", "stop")
        refusal = finish_refusal(finish) if isinstance(finish, str) else None
        if refusal is not None:
            return Completion(None, charge, generation, refusal)
        if content is None or charge is None:
            return Completion(
                None, charge, generation, RefusalCode.PROVIDER_RESPONSE_INVALID
            )
        return Completion(content, charge, generation)

    def _charge(self, usage: Mapping[str, Any] | None) -> Decimal | None:
        """`tokens x price`, exact, or unknown when the response carried no usage."""
        if usage is None:
            return None
        try:
            input_tokens = Decimal(int(usage["input_tokens"]))
            output_tokens = Decimal(int(usage["output_tokens"]))
            amount = _CHARGE_CONTEXT.add(
                _CHARGE_CONTEXT.multiply(input_tokens, self.price.input_per_token),
                _CHARGE_CONTEXT.multiply(output_tokens, self.price.output_per_token),
            )
        except (KeyError, TypeError, ValueError, DecimalException):
            return None
        return reported_charge(amount)


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
    effort = os.environ.get(REASONING_EFFORT_ENV) or None
    return completions(price, endpoint=endpoint, reasoning_effort=effort)
