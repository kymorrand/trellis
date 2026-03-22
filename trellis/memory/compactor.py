"""trellis.memory.compactor — Context Window Compaction

Level-of-detail system for conversation history.
Recent interactions: full detail. Older ones: summarized.
Keeps context within token limits while preserving key information.

Strategy:
    - Last 6 message pairs: full detail (most recent context)
    - Older pairs: compressed to single-line summaries
    - Very old pairs: dropped entirely

This runs client-side — no API call needed for compaction.
Token estimates use word count × 1.3 as a rough approximation.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# How many recent message pairs to keep at full detail
FULL_DETAIL_PAIRS = 6

# How many older pairs to keep as summaries
SUMMARY_PAIRS = 10

# Rough token budget for the compacted context
TOKEN_BUDGET = 4000

# Approximate tokens per word
TOKENS_PER_WORD = 1.3


def estimate_tokens(text: str) -> int:
    """Rough token estimate from word count."""
    return int(len(text.split()) * TOKENS_PER_WORD)


def estimate_history_tokens(history: list[dict]) -> int:
    """Estimate total tokens in a conversation history."""
    return sum(estimate_tokens(msg.get("content", "")) for msg in history)


def compact_history(
    history: list[dict],
    full_detail_pairs: int = FULL_DETAIL_PAIRS,
    summary_pairs: int = SUMMARY_PAIRS,
    token_budget: int = TOKEN_BUDGET,
) -> list[dict]:
    """Compact conversation history to fit within a token budget.

    Args:
        history: List of {"role": "user"|"assistant", "content": "..."} dicts.
        full_detail_pairs: Number of recent pairs to keep in full.
        summary_pairs: Number of older pairs to keep as summaries.
        token_budget: Rough token limit for the compacted history.

    Returns:
        Compacted history list (same format as input).
    """
    if not history:
        return []

    # If already within budget, return as-is
    if estimate_history_tokens(history) <= token_budget:
        return list(history)

    # Split into pairs (user, assistant)
    pairs = []
    i = 0
    while i < len(history) - 1:
        if history[i]["role"] == "user" and history[i + 1]["role"] == "assistant":
            pairs.append((history[i], history[i + 1]))
            i += 2
        else:
            # Odd message — keep as single
            pairs.append((history[i],))
            i += 1
    if i < len(history):
        pairs.append((history[i],))

    total_pairs = len(pairs)

    if total_pairs <= full_detail_pairs:
        return list(history)

    # Split: old pairs get summarized, recent pairs stay full
    recent_start = max(0, total_pairs - full_detail_pairs)
    summary_start = max(0, recent_start - summary_pairs)

    compacted = []

    # Drop anything before summary_start (too old)
    if summary_start > 0:
        compacted.append({
            "role": "user",
            "content": f"[{summary_start} earlier exchanges omitted for brevity]",
        })
        compacted.append({
            "role": "assistant",
            "content": "Understood — I'll focus on the recent context.",
        })

    # Summarized pairs
    for pair in pairs[summary_start:recent_start]:
        if len(pair) == 2:
            user_msg = pair[0]["content"]
            asst_msg = pair[1]["content"]
            # Truncate to first line / 80 chars
            user_summary = _summarize(user_msg)
            asst_summary = _summarize(asst_msg)
            compacted.append({"role": "user", "content": user_summary})
            compacted.append({"role": "assistant", "content": asst_summary})
        else:
            compacted.append({
                "role": pair[0]["role"],
                "content": _summarize(pair[0]["content"]),
            })

    # Recent pairs at full detail
    for pair in pairs[recent_start:]:
        for msg in pair:
            compacted.append(msg)

    # Final token check — if still over budget, trim summaries
    while estimate_history_tokens(compacted) > token_budget and len(compacted) > full_detail_pairs * 2:
        # Remove the oldest pair
        compacted.pop(0)
        compacted.pop(0)

    logger.debug(
        f"Compacted history: {len(history)} → {len(compacted)} messages, "
        f"~{estimate_history_tokens(compacted)} tokens"
    )

    return compacted


def _summarize(text: str, max_len: int = 80) -> str:
    """Create a one-line summary of a message."""
    # Take the first line, truncate
    first_line = text.split("\n")[0].strip()
    if len(first_line) > max_len:
        return first_line[:max_len] + "..."
    if len(first_line) < 10 and len(text) > len(first_line):
        # First line is too short — grab more
        flat = " ".join(text.split()[:20])
        if len(flat) > max_len:
            return flat[:max_len] + "..."
        return flat
    return first_line
