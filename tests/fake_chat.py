"""A scripted chat model: the seam production fills with `ChatDatabricks`.

The executor and billing suites used to script an HTTP transport under the
OpenRouter client. The transport is gone (D7); what a suite scripts now is the
`BaseChatModel` behind `caos.models.completions`, which is exactly the object
the gateway model is in production. An `answer` is an `AIMessage`, an
exception to raise mid-call, or a callable answering the prompt it was sent.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGeneration, ChatResult
from openai import OpenAIError
from pydantic import Field

from caos.models import ChatCompletions, completions
from caos.pricing import ModelPrice

MODEL = "a-model/for-the-test"
# 1,000 input and 1,500 output tokens at these rates is exactly 0.25, the
# charge the legacy wire fixtures reported, so every ledger assertion holds.
PRICE = ModelPrice(MODEL, Decimal("0.0001"), Decimal("0.0001"), date(2026, 9, 22))
DEFAULT_TOKENS = (1000, 1500)

Answer = AIMessage | Exception | Callable[[str], "AIMessage | Exception"]


class ScriptedChat(BaseChatModel):
    """Answers every prompt from `answer`; records what it was asked."""

    answer: Any
    before: Any = None
    prompts: list[str] = Field(default_factory=list)
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        content = messages[-1].content
        prompt = content if isinstance(content, str) else str(content)
        self.calls += 1
        self.prompts.append(prompt)
        if self.before is not None:
            self.before()
        chosen = self.answer
        if callable(chosen) and not isinstance(chosen, Exception):
            chosen = chosen(prompt)
        if isinstance(chosen, Exception):
            raise chosen
        return ChatResult(generations=[ChatGeneration(message=chosen)])


class StatusError(OpenAIError):
    """A vendor error carrying only a status code; its text never travels."""

    def __init__(self, status_code: int) -> None:
        super().__init__("private")
        self.status_code = status_code


def answer(
    content: str = "private",
    *,
    finish: str = "length",
    tokens: tuple[int, int] | None = DEFAULT_TOKENS,
    generation: str | None = "generation",
) -> AIMessage:
    """One response: content, finish reason, token usage and generation id."""
    usage: UsageMetadata | None = None
    if tokens is not None:
        usage = UsageMetadata(
            input_tokens=tokens[0],
            output_tokens=tokens[1],
            total_tokens=tokens[0] + tokens[1],
        )
    return AIMessage(
        content=content,
        id=generation,
        response_metadata={"finish_reason": finish},
        usage_metadata=usage,
    )


def fake_completions(
    chat: BaseChatModel | None = None,
    *,
    model: str = MODEL,
    price: ModelPrice | None = None,
) -> ChatCompletions:
    """The production provider over a scripted model, priced for `model`."""
    priced = price if price is not None else PRICE
    if priced.model != model:
        priced = ModelPrice(
            model, priced.input_per_token, priced.output_per_token, priced.as_of
        )
    return completions(
        priced, chat=chat or ScriptedChat(answer=answer()), endpoint=model
    )
