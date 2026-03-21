"""Tests for trellis.mind.router — Model routing classification."""

import pytest

from trellis.mind.router import ModelRouter, COMPLEX_KEYWORDS


class TestClassify:
    """Test the classify() routing heuristics."""

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

    # --- Complex messages → cloud ---

    def test_draft_keyword(self, router):
        assert router.classify("draft a blog post about AI") == "cloud"

    def test_analyze_keyword(self, router):
        assert router.classify("analyze this data") == "cloud"

    def test_write_keyword(self, router):
        assert router.classify("write a summary of the meeting") == "cloud"

    def test_strategy_keyword(self, router):
        assert router.classify("what's our strategy for Q3?") == "cloud"

    def test_long_message(self, router):
        msg = " ".join(["word"] * 51)
        assert router.classify(msg) == "cloud"

    def test_multi_paragraph(self, router):
        msg = "paragraph one\n\nparagraph two\n\nparagraph three"
        assert router.classify(msg) == "cloud"

    # --- Edge cases ---

    def test_keyword_at_word_boundary(self, router):
        # "draft" should match, but "undrafted" should not (word boundary)
        assert router.classify("undrafted") == "local"

    def test_exactly_50_words_is_local(self, router):
        msg = " ".join(["word"] * 50)
        assert router.classify(msg) == "local"


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
