"""Conservative, offline pre-request provider token-window enforcement."""
from __future__ import annotations

import json


def conservative_input_token_bound(request: object) -> int:
    """Return a tokenizer-independent upper bound for the visible request payload.

    Every UTF-8 byte is charged as one token. This deliberately overestimates
    normal text and encoded images, but is deterministic, offline, and never
    separates tool calls from their results or image blocks.
    """

    return len(
        json.dumps(
            request, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    )


def exceeds_token_window(
    request: object,
    *,
    context_window_tokens: int,
    output_token_reserve: int,
    prior_context_tokens: int = 0,
) -> bool:
    """Check the complete atomic request plus reserved output against its model window."""

    return (
        prior_context_tokens
        + conservative_input_token_bound(request)
        + output_token_reserve
        > context_window_tokens
    )


__all__ = ["conservative_input_token_bound", "exceeds_token_window"]
