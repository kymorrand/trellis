"""Tests for trellis.memory.compactor — Context window compaction."""


from trellis.memory.compactor import (
    compact_history,
    estimate_tokens,
    estimate_history_tokens,
    _summarize,
)


# ─── Token estimation ────────────────────────────────────


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_single_word(self):
        result = estimate_tokens("hello")
        assert result == 1  # int(1 * 1.3) = 1

    def test_multi_word(self):
        result = estimate_tokens("one two three four five")
        assert result == int(5 * 1.3)

    def test_returns_int(self):
        assert isinstance(estimate_tokens("hello world"), int)


class TestEstimateHistoryTokens:
    def test_empty_history(self):
        assert estimate_history_tokens([]) == 0

    def test_sums_all_messages(self):
        history = [
            {"role": "user", "content": "one two three"},
            {"role": "assistant", "content": "four five six"},
        ]
        expected = estimate_tokens("one two three") + estimate_tokens("four five six")
        assert estimate_history_tokens(history) == expected

    def test_handles_missing_content(self):
        history = [{"role": "user"}, {"role": "assistant", "content": "hi"}]
        # Missing content treated as ""
        assert estimate_history_tokens(history) == estimate_tokens("hi")


# ─── _summarize ──────────────────────────────────────────


class TestSummarize:
    def test_short_text_returned_as_is(self):
        assert _summarize("hello world") == "hello world"

    def test_long_text_truncated(self):
        long = "a " * 100
        result = _summarize(long, max_len=80)
        assert len(result) <= 84  # 80 + "..."
        assert result.endswith("...")

    def test_multiline_uses_first_line(self):
        text = "First line here\nSecond line\nThird line"
        assert _summarize(text) == "First line here"

    def test_very_short_first_line_grabs_more(self):
        text = "Hi\nThis is a longer continuation of the message with more detail."
        result = _summarize(text)
        # Should grab more than just "Hi"
        assert len(result) > 5


# ─── compact_history ─────────────────────────────────────


def _make_history(n_pairs: int, msg_len: int = 50) -> list[dict]:
    """Helper: create n user/assistant message pairs."""
    history = []
    for i in range(n_pairs):
        history.append({"role": "user", "content": f"User message {i}: " + "word " * msg_len})
        history.append({"role": "assistant", "content": f"Assistant reply {i}: " + "word " * msg_len})
    return history


class TestCompactHistory:
    def test_empty_history(self):
        assert compact_history([]) == []

    def test_short_history_unchanged(self):
        """History under budget returned as-is."""
        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = compact_history(history)
        assert result == history

    def test_returns_list_copy(self):
        """Should return a new list, not the original."""
        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = compact_history(history)
        assert result is not history

    def test_long_history_gets_compacted(self):
        """History with many pairs should be shorter after compaction."""
        history = _make_history(20, msg_len=100)
        result = compact_history(history)
        assert len(result) < len(history)

    def test_recent_messages_preserved_fully(self):
        """The most recent pairs should remain at full detail."""
        history = _make_history(20, msg_len=100)
        result = compact_history(history, full_detail_pairs=6, token_budget=2000)

        # The last message in the original should be the last in compacted
        assert result[-1]["content"] == history[-1]["content"]
        assert result[-2]["content"] == history[-2]["content"]

    def test_old_messages_get_omitted_marker(self):
        """Very old messages should produce an 'omitted' marker."""
        history = _make_history(30, msg_len=100)
        result = compact_history(history, full_detail_pairs=4, summary_pairs=4, token_budget=3000)

        # Should have an omitted marker at the start
        has_omitted = any("omitted" in msg["content"].lower() for msg in result)
        assert has_omitted

    def test_pairs_with_odd_message(self):
        """History with an odd number of messages should still compact and reduce tokens."""
        history = _make_history(15, msg_len=100)
        history.append({"role": "user", "content": "trailing message " + "word " * 100})
        original_tokens = estimate_history_tokens(history)
        result = compact_history(history)
        compacted_tokens = estimate_history_tokens(result)
        # Compactor summarizes old messages, so tokens should decrease
        assert compacted_tokens < original_tokens

    def test_within_budget_not_compacted(self):
        """If total tokens are within budget, return all messages."""
        history = _make_history(3, msg_len=5)  # Very short messages
        result = compact_history(history, token_budget=10000)
        assert len(result) == len(history)

    def test_custom_parameters(self):
        """Custom full_detail_pairs and summary_pairs are respected."""
        history = _make_history(20, msg_len=50)
        result = compact_history(history, full_detail_pairs=2, summary_pairs=2, token_budget=1000)
        # Should be much shorter than original
        assert len(result) < 20
