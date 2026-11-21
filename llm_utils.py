from typing import Any

import tiktoken
from langchain_core.messages import HumanMessage, SystemMessage


MAX_LLM_INPUT_TOKENS = 5200
MAX_LLM_OUTPUT_TOKENS = 768
_TOKENIZER = tiktoken.get_encoding("o200k_base")


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


def invoke_with_token_budget(
    llm: Any,
    system_prompt: str,
    user_prompt: str,
):
    """Bound each prompt while preserving its opening context and final instructions."""

    system_tokens = len(
        _TOKENIZER.encode(system_prompt, disallowed_special=())
    )
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
            prompt_tokens[:prefix_budget]
            + marker
            + prompt_tokens[-suffix_budget:]
        )
        user_prompt = _TOKENIZER.decode(prompt_tokens)

    return llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ],
        max_tokens=MAX_LLM_OUTPUT_TOKENS,
    )
