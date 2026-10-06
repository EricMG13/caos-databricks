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
import re
import sys
import threading
import time
import warnings
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from decimal import Decimal, DecimalException
from types import TracebackType
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from openai import APIConnectionError, OpenAIError

# The configuration names live beside the price they configure, so the API,
# which may not import this module (D4), reads them too.
from caos.pricing import DEFAULT_ENDPOINT as DEFAULT_ENDPOINT
from caos.pricing import ENDPOINT_ENV as ENDPOINT_ENV
from caos.pricing import MODEL_PRICE_ENV as MODEL_PRICE_ENV
from caos.pricing import REASONING_EFFORT_ENV as REASONING_EFFORT_ENV
from caos.pricing import ModelPrice, exact_context, model_choices
from caos.pricing import configured_endpoint as configured_endpoint
from caos.provider import (
    MAX_COMPLETION_TOKENS,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    NEVER_RETRIED,
    TIMEOUT_SECONDS,
    Completion,
    DropKind,
    check_resend,
    encode_request,
    finish_refusal,
    reported_charge,
)
from caos.refusals import Refusal, RefusalCode
from caos.store.outcomes import producer_identifier

PLATFORM = "databricks"
HOST_MINTED = "host-"
# A 429 reached no model, so it is asked again under the same reservation
# (DP-5): this many tries in all, waiting `Retry-After` up to the cap.
RATE_LIMITED = 429
RATE_LIMIT_TRIES = 3
RETRY_AFTER_SECONDS = 2.0
RETRY_AFTER_CAP_SECONDS = 20.0
# A re-send starts only with at least this long left of the call's one
# deadline (N11): half of it, 210 s since D83 (the 120 s whole-call deadline
# F89 measured as too short to deliver a few thousand tokens at real
# throughput was half of the 240 before it). A re-send started with less is
# expected to be abandoned mid-generation at the deadline while the provider
# may still bill it, so the 429 is the answer instead. Two capped waits spend
# at most 40 s of the 420, so a rate limit answered promptly is still re-sent;
# only 429s that were themselves slow to arrive leave less.
MIN_RESEND_SECONDS = TIMEOUT_SECONDS / 2
_sleep = time.sleep
_clock = time.monotonic


def identity_of(model: str, reasoning_effort: str | None = None) -> str:
    """The execution profile a verdict binds (D8), from the names alone, so a
    caller can refuse an unexpected one before any client is built."""
    return "/".join(
        (PLATFORM, model, reasoning_effort or "none", str(MAX_COMPLETION_TOKENS))
    )


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
        started = _clock()
        deadline = started + TIMEOUT_SECONDS
        sent = 0
        while True:
            sent += 1
            answer = _invoked(self.chat, prompt, options, deadline - _clock())
            if isinstance(answer, OpenAIError):
                if not _sends_again(answer, sent, deadline):
                    return _unanswered(_status_refusal(answer), answer, started)
                continue
            if answer is None or isinstance(answer, _Raised):
                # Indeterminate: the request may have been delivered and
                # billed, so the attempt keeps its reservation. Nothing of
                # the error travels; its class is named on stderr (F513).
                return _unanswered(RefusalCode.PROVIDER_UNAVAILABLE, answer, started)
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
        # Blank text -- empty, whitespace, a fence around nothing -- is no
        # answer, as no text is (CF-047): billed, and never handed on as a
        # handoff to be refused as malformed.
        if not content or charge is None:
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


@dataclass(frozen=True, slots=True)
class _Raised:
    """A call the client ended by raising something that is no vendor error:
    indeterminate. Only its facts are kept, never the exception, so the
    raising frames -- and the prompt they hold -- go with the call (F513)."""

    kind: DropKind
    facts: str


class _Indeterminate:
    """`suppress(Exception)` -- its own `__exit__`, so its exception-group
    split too -- keeping the facts of what it held back: the documented
    fail-open of ST-8, named on stderr by class (F513). What it does not hold
    back propagates as before."""

    facts: str | None = None

    def __init__(self) -> None:
        self._held = suppress(Exception)

    def __enter__(self) -> _Indeterminate:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        failed: BaseException | None,
        trace: TracebackType | None,
    ) -> bool:
        held = bool(self._held.__exit__(kind, failed, trace))
        if held:
            self.facts = _facts(failed)
        return held


def _invoked(
    chat: BaseChatModel, prompt: str, options: dict[str, Any], seconds: float
) -> object:
    """One `invoke`: its answer, the vendor error it raised, `_Raised` for
    anything else it raised, or None when the deadline passed first.

    Abandoned once `seconds` pass (ST-9): the client's timeout bounds each
    read, not the call, so a server that sends a byte at a time would hold it
    open with no limit, past the lease it was sized in. The call runs on a
    helper thread; an answer that has not arrived by the deadline is None, as
    a socket timeout is. An abandoned thread holds only its own socket and
    never writes to the store.

    Once the request may have been sent, whatever else the stack raises is
    indeterminate too (ST-8): an empty `choices` is an `IndexError` from the
    client, and no failure may escape untyped ahead of `record_outcome`.
    """
    answered: list[object] = []
    context = contextvars.copy_context()

    def send() -> None:
        try:
            with _Indeterminate() as held:  # indeterminate, never text (ST-8)
                try:
                    with _content_parts_contained():
                        answered.append(
                            context.run(
                                chat.invoke, [HumanMessage(content=prompt)], **options
                            )
                        )
                except OpenAIError as failed:
                    answered.append(failed)
        except BaseException as escaped:
            # Not held back, as `suppress(Exception)` held it not: it still
            # ends this thread, and the call is named `escaped` (F513).
            answered.append(_Raised(DropKind.ESCAPED, _facts(escaped)))
            raise
        if held.facts is not None:
            answered.append(_Raised(DropKind.RAISED, held.facts))

    sender = threading.Thread(target=send, name="caos-model-call", daemon=True)
    sender.start()
    sender.join(max(seconds, 0.0))
    return answered[0] if answered else None


# Pydantic's serializer warning when the client dumps a response message whose
# `content` is a list of parts where its model declares a string (CF-077). The
# warning quotes that value -- the model's answer, which quotes the evidence --
# and Python prints it to stderr. Matched by category and the whole message:
# one content-list entry, nothing after it; no other warning is touched.
_CONTENT_PARTS_WARNING = (
    r"Pydantic serializer warnings:\s+PydanticSerializationUnexpectedValue\("
    r"Expected `str` - serialized value may not be as expected \["
    r"field_name='content', input_value=.*, input_type=list\]\)\Z"
)


@contextmanager
def _content_parts_contained() -> Iterator[None]:
    """Contain `_CONTENT_PARTS_WARNING` for the one call inside the block.

    Python 3.13's filter state is process-wide. A call abandoned at its
    deadline and still running when the next one starts can end the next
    call's containment early, or leave this one filter in place after both;
    neither touches any other warning.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message=_CONTENT_PARTS_WARNING, category=UserWarning
        )
        yield


def _sends_again(failed: OpenAIError, sent: int, deadline: float) -> bool:
    """Whether the call is sent again after `failed`: a rate limit waited out
    (`_waited_out`), every installed check asked, and `MIN_RESEND_SECONDS`
    still left."""
    if not _waited_out(failed, sent, deadline):
        return False
    # Nothing was billed yet; what the caller installed decides whether the
    # call may still be made (ST-7), and raises if not.
    check_resend()
    # The wait and the fence can spend what was left (R24-08): nothing is
    # started without the time a generation needs (N11), past the one deadline
    # least of all, and the rate limit is then the answer.
    return deadline - _clock() >= MIN_RESEND_SECONDS


def _waited_out(failed: OpenAIError, sent: int, deadline: float) -> bool:
    """Whether a rate limit was waited out and the call may be sent again: a
    429 reached no model (DP-5), within the tries, and the wait still leaves
    `MIN_RESEND_SECONDS` of the call's one deadline (ST-9, N11) -- a wait that
    could not be followed by a re-send is not waited."""
    if not _rate_limited(failed) or sent >= RATE_LIMIT_TRIES:
        return False
    wait = _retry_after(failed)
    if wait + MIN_RESEND_SECONDS > deadline - _clock():
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
    return RefusalCode.PROVIDER_UNAVAILABLE


# What a stderr line may carry (F513): never words. A class name is an
# identifier; a provider error's code is an HTTP status; its type one of the
# documented provider `error_type` values (the source is named in F513).
# Anything else is shown as `?`, so a provider echoing input cannot put it here.
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_ERROR_TYPES = frozenset(
    {
        "authentication",
        "content_policy_violation",
        "context_length_exceeded",
        "image_download_failed",
        "image_not_found",
        "image_too_large",
        "image_too_small",
        "invalid_image",
        "invalid_prompt",
        "invalid_request",
        "max_tokens_exceeded",
        "not_found",
        "payload_too_large",
        "payment_required",
        "permission_denied",
        "precondition_failed",
        "provider_overloaded",
        "provider_unavailable",
        "rate_limit_exceeded",
        "refusal",
        "server",
        "string_too_long",
        "timeout",
        "token_limit_exceeded",
        "unmapped",
        "unprocessable",
        "unsupported_image_format",
    }
)
# The statuses a provider fails a call with (D110, F530): 4xx and 5xx.
FAILURE_STATUSES = (400, 599)
_NO_FACTS = "class=- cause=- status=- error_code=- error_type=-"
_UNKNOWN_FACTS = "class=? cause=? status=? error_code=? error_type=?"


def _name(value: object) -> str:
    return value if isinstance(value, str) and _NAME.fullmatch(value) else "?"


def _status(value: object) -> str:
    """An HTTP status, three or four digits, from an int or a digit string."""
    if value is None:
        return "-"
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value) if len(value) <= 4 else None
    if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 9999:
        return str(value)
    return "?"


def _error_type(value: object) -> str:
    if value is None:
        return "-"
    return value if isinstance(value, str) and value in _ERROR_TYPES else "?"


def _error_body(failed: BaseException) -> Mapping[str, Any]:
    """The provider's error object, from a vendor error's parsed body or the
    mapping a client raised as its argument; empty when there is none."""
    body = getattr(failed, "body", None)
    if not isinstance(body, Mapping) and failed.args:
        body = failed.args[0]
    if not isinstance(body, Mapping):
        return {}
    inner = body.get("error")
    return inner if isinstance(inner, Mapping) else body


def _failure_facts(failed: BaseException | None) -> str:
    """The class, its causes, the status and the provider's error code and
    type: what tells a 200 carrying an error body from a reset, a 5xx or a
    parse failure (F513). Never the message or the body's words."""
    if failed is None:
        return _NO_FACTS
    causes: list[str] = []
    link = failed.__cause__ or failed.__context__
    while link is not None and len(causes) < 3:
        causes.append(_name(type(link).__name__))
        link = link.__cause__ or link.__context__
    body = _error_body(failed)
    metadata = body.get("metadata")
    kind = metadata.get("error_type") if isinstance(metadata, Mapping) else None
    return " ".join(
        (
            f"class={_name(type(failed).__name__)}",
            f"cause={'<'.join(causes) or '-'}",
            f"status={_status(getattr(failed, 'status_code', None))}",
            f"error_code={_status(body.get('code'))}",
            f"error_type={_error_type(kind)}",
        )
    )


def _facts(failed: BaseException | None) -> str:
    """`_failure_facts`, or `_UNKNOWN_FACTS` when reading the failure raises:
    a property that raises, an int too long to print. The diagnostic is a
    fail-open (F513): it never changes the call's outcome."""
    facts = _UNKNOWN_FACTS
    with suppress(Exception):  # fail-open, documented above (F513)
        facts = _failure_facts(failed)
    return facts


def _unanswered(code: RefusalCode, answer: object, started: float) -> Completion:
    """The refusal of a call that got no answer, after one stderr line for it
    (F513): the code, how it ended -- `vendor` (a vendor error), `raised`
    (anything else the client raised, held back), `escaped` (raised and not
    held back) or `deadline` (nothing by then) -- the facts and the seconds
    since it was first sent. One `write`, newline included, so two calls'
    lines never interleave; a write that fails is dropped (a fail-open: the
    line never changes the outcome). Nothing here quotes the prompt, an
    answer or an error's text. The refusal carries the same kind, typed, a
    vendor error split by whether the provider declared it (D110)."""
    drop, facts = DropKind.DEADLINE, _NO_FACTS
    if isinstance(answer, _Raised):
        drop, facts = answer.kind, answer.facts
    elif isinstance(answer, BaseException):
        unavailable = code is RefusalCode.PROVIDER_UNAVAILABLE
        drop = (
            DropKind.DECLARED if unavailable and _declared(answer) else DropKind.VENDOR
        )
        facts = _facts(answer)
    kind = "vendor" if drop is DropKind.DECLARED else drop.value
    with suppress(Exception):  # fail-open, documented above (F513)
        line = f"{code.value} call={kind} {facts} elapsed={_clock() - started:.1f}\n"
        sys.stderr.write(line)
    return Completion(None, None, None, code, drop)


def _declared(failed: BaseException) -> bool:
    """Whether the provider itself stated this vendor error a failure (D110):
    a failure status, 400 to 599, or, with no status at all, its own error
    object as the error's body (an SSE `error` event) -- never a status that
    says the call succeeded (a `200` the client could not read, F530), an
    argument that is no body, or a connection's failure (a reset, a client
    timeout), after which what was received is unknown. An error that raises
    while it is read is not declared: the re-attempt fails closed."""
    declared = False
    with suppress(Exception):  # fail closed, documented above (D110)
        status = getattr(failed, "status_code", None)
        body = getattr(failed, "body", None)
        if isinstance(failed, APIConnectionError):
            declared = False
        elif status is not None:
            declared = (
                type(status) is int
                and FAILURE_STATUSES[0] <= status <= (FAILURE_STATUSES[1])
            )
        else:
            declared = isinstance(body, Mapping) and bool(body)
    return declared


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
    """The provider for the configured endpoint, or `PROVIDER_NOT_CONFIGURED`
    for it or for any malformed choice beside it (`model_choices`)."""
    endpoint = configured_endpoint()
    return completions(model_choices()[endpoint], endpoint=endpoint)
