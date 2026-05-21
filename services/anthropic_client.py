"""Thin wrapper around the Anthropic Python SDK.

All agents call `ask()` or `ask_with_web_search()` from this module rather than
instantiating the SDK themselves, so model defaults, auth, and error handling
live in one place.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 1024

# Web search tool definition — server-side, Anthropic executes the searches.
_WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}


@lru_cache(maxsize=1)
def _client() -> Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and paste your key."
        )
    return Anthropic(api_key=api_key)


def ask(
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str:
    """Send one prompt to Claude and return the text response."""
    response = _client().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


def ask_with_usage(
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict[str, Any]:
    """Like ask() but also returns token usage for cost logging.

    Returns:
        text          str      — model's text response
        input_tokens  int      — prompt tokens used
        output_tokens int      — completion tokens used
        web_searches  int      — always 0 (no web search)
        error         str|None — error message if the call failed
    """
    try:
        response = _client().messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as exc:
        return {
            "text": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "web_searches": 0,
            "error": str(exc),
        }

    text = "".join(block.text for block in response.content if block.type == "text")
    return {
        "text": text,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "web_searches": 0,
        "error": None,
    }


def ask_with_web_search(
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """Call Claude with the built-in web search tool enabled.

    Returns a dict:
        text          str   — model's final text response
        input_tokens  int   — prompt tokens used
        output_tokens int   — completion tokens used
        web_searches  int   — number of web searches performed
        error         str|None — error message if the call failed
    """
    try:
        response = _client().messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            tools=[_WEB_SEARCH_TOOL],
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as exc:
        err = str(exc)
        # Surface a clear message if web search isn't available on this plan/model.
        if "web_search" in err.lower() or "tool" in err.lower():
            err = (
                f"Web search tool is not available: {exc}\n\n"
                "Check that your Anthropic API plan supports web search "
                "(claude-sonnet-4-6 or later with web search enabled)."
            )
        return {
            "text": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "web_searches": 0,
            "error": err,
        }

    # If the model stopped to use a client-side tool (not expected for web search),
    # surface it as a clear error rather than silently returning empty text.
    if response.stop_reason == "tool_use":
        tool_names = [
            getattr(b, "name", "unknown")
            for b in response.content
            if getattr(b, "type", "") == "tool_use"
        ]
        return {
            "text": "",
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "web_searches": 0,
            "error": (
                f"Model stopped for client-side tool use ({', '.join(tool_names)}). "
                "Web search was expected to run server-side — check your API plan."
            ),
        }

    # Collect all text blocks (model may emit text before and after searching).
    text = "\n".join(
        block.text for block in response.content if getattr(block, "type", "") == "text"
    ).strip()

    # Count web searches: try server-side usage field first, then content blocks.
    web_searches: int = 0
    usage = response.usage
    server_use = getattr(usage, "server_tool_use", None)
    if server_use is not None:
        web_searches = getattr(server_use, "web_search_requests", 0) or 0
    if web_searches == 0:
        web_searches = sum(
            1
            for b in response.content
            if getattr(b, "type", "") == "tool_use"
            and getattr(b, "name", "") == "web_search"
        )

    return {
        "text": text,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "web_searches": web_searches,
        "error": None,
    }
