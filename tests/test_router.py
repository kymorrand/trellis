"""Tests for trellis.mind.router — Three-tier model routing classification."""

import pytest

from trellis.mind.router import ModelRouter


class TestClassify:
    """Test the classify() three-tier routing heuristics."""

    @pytest.fixture
    def router(self):
        """Router with a dummy anthropic client (classification doesn't call APIs)."""
        r = ModelRouter.__new__(ModelRouter)
        r.ollama_url = "http://localhost:11434"
        r._session_cost = 0.0
        return r

    # --- Force overrides ---

    def test_force_local(self, router):
        assert router.classify("/local hey there") == "force_local"

    def test_force_local_case_insensitive(self, router):
        assert router.classify("/LOCAL do this") == "force_local"

    def test_force_cloud(self, router):
        assert router.classify("/claude tell me about X") == "force_cloud"

    def test_force_cloud_case_insensitive(self, router):
        assert router.classify("/Claude what is this?") == "force_cloud"

    # --- Simple messages → local ---

    def test_greeting(self, router):
        assert router.classify("hey") == "local"

    def test_short_question(self, router):
        assert router.classify("what time is it?") == "local"

    def test_yes(self, router):
        assert router.classify("yes") == "local"

    def test_thanks(self, router):
        assert router.classify("thanks!") == "local"

    def test_empty_string(self, router):
        assert router.classify("") == "local"

    def test_short_casual(self, router):
        assert router.classify("sounds good") == "local"

    def test_greeting_yo(self, router):
        assert router.classify("yo") == "local"

    # --- Medium complexity → light (Haiku) ---

    def test_draft_keyword(self, router):
        assert router.classify("draft a blog post about AI") == "light"

    def test_analyze_keyword(self, router):
        assert router.classify("analyze this data") == "light"

    def test_write_keyword(self, router):
        assert router.classify("write a summary of the meeting") == "light"

    def test_explain_keyword(self, router):
        assert router.classify("explain how the heartbeat works") == "light"

    def test_summarize_keyword(self, router):
        assert router.classify("summarize what happened yesterday") == "light"

    def test_moderate_length(self, router):
        msg = " ".join(["word"] * 35)
        assert router.classify(msg) == "light"

    def test_single_paragraph_break(self, router):
        msg = "first part of the question\n\nsecond part here"
        assert router.classify(msg) == "light"

    # --- Complex messages → cloud (Sonnet) ---

    def test_architect_keyword(self, router):
        assert router.classify("help me architect a new module") == "cloud"

    def test_debug_keyword(self, router):
        assert router.classify("debug this error in the router") == "cloud"

    def test_strategy_keyword(self, router):
        assert router.classify("what's our strategy for Q3?") == "cloud"

    def test_tradeoffs_keyword(self, router):
        assert router.classify("what are the trade-offs here?") == "cloud"

    def test_very_long_message(self, router):
        msg = " ".join(["word"] * 101)
        assert router.classify(msg) == "cloud"

    def test_many_paragraphs(self, router):
        msg = "p1\n\np2\n\np3\n\np4"
        assert router.classify(msg) == "cloud"

    # --- Edge cases ---

    def test_keyword_at_word_boundary(self, router):
        # "draft" should match, but "undrafted" should not (word boundary)
        assert router.classify("undrafted") == "local"

    def test_exactly_30_words_is_local(self, router):
        msg = " ".join(["word"] * 30)
        assert router.classify(msg) == "local"

    def test_31_words_is_light(self, router):
        msg = " ".join(["word"] * 31)
        assert router.classify(msg) == "light"

    def test_100_words_is_light(self, router):
        msg = " ".join(["word"] * 100)
        assert router.classify(msg) == "light"


class TestStripPrefix:
    @pytest.fixture
    def router(self):
        r = ModelRouter.__new__(ModelRouter)
        r.ollama_url = "http://localhost:11434"
        r._session_cost = 0.0
        return r

    def test_strip_local(self, router):
        assert router.strip_prefix("/local do this") == "do this"

    def test_strip_claude(self, router):
        assert router.strip_prefix("/claude tell me") == "tell me"

    def test_no_prefix(self, router):
        assert router.strip_prefix("hello there") == "hello there"

    def test_strip_preserves_rest(self, router):
        assert router.strip_prefix("/local  extra spaces") == "extra spaces"
