"""Token budgeting, bounded LLM calls, and central LLM-call accounting."""

from __future__ import annotations

import contextvars
import functools
import logging
import threading
import time
from typing import Any

import tiktoken
from langchain_core.messages import HumanMessage, SystemMessage

import config

logger = logging.getLogger(__name__)

MAX_LLM_INPUT_TOKENS = config.LLM_MAX_INPUT_TOKENS
MAX_LLM_OUTPUT_TOKENS = config.LLM_OUTPUT_TOKENS
_TOKENIZER = tiktoken.get_encoding("o200k_base")

# Per-node counter of LLM calls (F-23). Each graph node runs in its own
# context, so parallel nodes never share a counter.
_call_counter: contextvars.ContextVar[list[int] | None] = contextvars.ContextVar(
    "llm_call_counter", default=None
)


# Token accounting for one request (admin console). A plain dict, shared by reference, so
# every thread a request fans out to (parallel agents) adds to the same totals.
usage_var: contextvars.ContextVar[dict[str, int] | None] = contextvars.ContextVar("llm_usage", default=None)
_usage_lock = threading.Lock()


def new_usage() -> dict[str, int]:
    return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "llm_calls": 0}


def record_usage(input_tokens: int, output_tokens: int, total_tokens: int | None = None) -> None:
    usage = usage_var.get()
    if usage is None:
        return
    with _usage_lock:
        usage["input_tokens"] += input_tokens
        usage["output_tokens"] += output_tokens
        usage["total_tokens"] += total_tokens if total_tokens else input_tokens + output_tokens
        usage["llm_calls"] += 1


def counts_llm_calls(node):
    """Decorator: add the number of LLM calls the node made to its update.

    The graph state field ``llm_calls`` uses an additive reducer, so nodes
    return only their own delta.
    """

    @functools.wraps(node)
    def wrapper(*args, **kwargs):
        counter = [0]
        token = _call_counter.set(counter)
        try:
            update = node(*args, **kwargs)
        finally:
            _call_counter.reset(token)

        update = dict(update or {})
        update["llm_calls"] = counter[0]
        return update

    return wrapper


def truncate_context(value: Any, max_tokens: int = 700) -> str:
    """Keep MCP and graph context from growing without bound."""

    text = str(value or "")
    tokens = _TOKENIZER.encode(text, disallowed_special=())

    if len(tokens) <= max_tokens:
        return text

    return (
        _TOKENIZER.decode(tokens[:max_tokens]).rstrip()
        + "\n[Context shortened to fit the model token budget.]"
    )


def fence(tag: str, value: Any, max_tokens: int) -> str:
    """Wrap untrusted text in a labelled block (F-08).

    The closing tag is stripped from the content so it cannot break out of
    the block, and the content is truncated to its token budget.
    """

    text = truncate_context(value, max_tokens)
    for marker in (f"</{tag}>", f"<{tag}>"):
        text = text.replace(marker, "")
    return f"<{tag}>\n{text}\n</{tag}>"


def invoke_with_token_budget(
    llm: Any,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int | None = None,
):
    """Bound each prompt while preserving its opening context and final instructions."""

    system_tokens = len(_TOKENIZER.encode(system_prompt, disallowed_special=()))
    prompt_tokens = _TOKENIZER.encode(user_prompt, disallowed_special=())
    available_tokens = max(1, MAX_LLM_INPUT_TOKENS - system_tokens - 64)

    if len(prompt_tokens) > available_tokens:
        suffix_budget = min(512, available_tokens // 5)
        marker = _TOKENIZER.encode(
            "\n[Earlier context shortened to fit the model token budget.]\n",
            disallowed_special=(),
        )
        prefix_budget = available_tokens - suffix_budget - len(marker)
        prompt_tokens = (
            prompt_tokens[:prefix_budget] + marker + prompt_tokens[-suffix_budget:]
        )
        user_prompt = _TOKENIZER.decode(prompt_tokens)

    counter = _call_counter.get()
    if counter is not None:
        counter[0] += 1

    started = time.perf_counter()
    response = llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ],
        max_tokens=max_output_tokens or MAX_LLM_OUTPUT_TOKENS,
    )

    usage = getattr(response, "usage_metadata", None) or {}
    if usage.get("input_tokens") is not None or usage.get("output_tokens") is not None:
        record_usage(int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0),
                     int(usage.get("total_tokens") or 0))
    else:  # the provider sent no counts: estimate with the local tokenizer
        record_usage(
            system_tokens + len(prompt_tokens),
            len(_TOKENIZER.encode(str(getattr(response, "content", "")), disallowed_special=())),
        )
    meta = getattr(response, "response_metadata", None) or {}
    finish = meta.get("finish_reason", "")
    logger.info(
        "llm_call ms=%d input_tokens=%s output_tokens=%s finish=%s",
        (time.perf_counter() - started) * 1000,
        usage.get("input_tokens", "?"),
        usage.get("output_tokens", "?"),
        finish or "?",
    )
    if finish == "length":
        logger.warning("LLM output hit the max_tokens cap; the answer may be cut off.")

    return response
