"""Tests for trellis.mind.context — Keyword extraction and auto-context assembly."""

import pytest
from pathlib import Path

from trellis.mind.context import extract_keywords, should_auto_search, auto_context


class TestExtractKeywords:
    def test_basic_extraction(self):
        keywords = extract_keywords("What do we know about Mirror Factory?")
        assert "Mirror" in keywords or "Factory" in keywords

    def test_stops_words_removed(self):
        keywords = extract_keywords("I want to know about the project")
        assert "I" not in keywords
        assert "want" not in keywords
        assert "the" not in keywords
        assert "project" in keywords

    def test_max_keywords_limit(self):
        keywords = extract_keywords(
            "Mirror Factory Layers product architecture design roadmap strategy",
            max_keywords=3,
        )
        assert len(keywords) <= 3

    def test_empty_message(self):
        assert extract_keywords("") == []

    def test_only_stop_words(self):
        assert extract_keywords("hi how are you") == []

    def test_preserves_compound_words(self):
        keywords = extract_keywords("What about Mirror-Factory plans?")
        assert any("Mirror-Factory" in kw for kw in keywords)

    def test_strips_command_prefix(self):
        keywords = extract_keywords("/claude tell me about Bobby")
        assert "claude" not in [k.lower() for k in keywords]
        assert "Bobby" in keywords

    def test_deduplication(self):
        keywords = extract_keywords("Bobby Bobby Bobby status")
        assert keywords.count("Bobby") == 1

    def test_single_character_filtered(self):
        keywords = extract_keywords("I need a B plan")
        assert "B" not in keywords

    def test_names_preserved(self):
        keywords = extract_keywords("What did Bobby say about Alfonso?")
        assert "Bobby" in keywords
        assert "Alfonso" in keywords

    def test_technical_terms(self):
        keywords = extract_keywords("How does the Anthropic API handle streaming?")
        assert "Anthropic" in keywords
        assert "API" in keywords


class TestShouldAutoSearch:
    def test_short_message_skipped(self):
        assert should_auto_search("hi") is False
        assert should_auto_search("ok") is False

    def test_two_words_skipped(self):
        assert should_auto_search("thanks ivy") is False

    def test_three_words_triggers(self):
        assert should_auto_search("tell me about solarpunk") is True

    def test_command_skipped(self):
        assert should_auto_search("!clear") is False
        assert should_auto_search("/status") is False

    def test_normal_message_triggers(self):
        assert should_auto_search("What do you know about Mirror Factory?") is True

    def test_empty_skipped(self):
        assert should_auto_search("") is False


class TestAutoContext:
    @pytest.fixture
    def vault(self, tmp_path):
        """Create a vault with searchable content."""
        knowledge = tmp_path / "knowledge"
        knowledge.mkdir()
        (knowledge / "mirror-factory.md").write_text(
            "# Mirror Factory\n\n"
            "Mirror Factory is a human factors research company building Layers.\n"
            "CEO: Kyle Morrand. Co-founders: Bobby Torres, Alfonso Morales.\n",
            encoding="utf-8",
        )
        (knowledge / "solarpunk.md").write_text(
            "# Solarpunk\n\nA genre focused on sustainability and optimism.\n",
            encoding="utf-8",
        )
        (knowledge / "bobby-torres.md").write_text(
            "# Bobby Torres\n\nCo-founder of Mirror Factory. Product design lead.\n",
            encoding="utf-8",
        )
        # Internal dir (should not be searched)
        ivy_dir = tmp_path / "_ivy" / "journal"
        ivy_dir.mkdir(parents=True)
        (ivy_dir / "2026-03-21.md").write_text("# Journal\nMirror Factory mentioned\n")
        return tmp_path

    def test_finds_relevant_context(self, vault):
        result = auto_context(vault, "Tell me about Mirror Factory plans")
        assert "Mirror Factory" in result

    def test_finds_person_context(self, vault):
        result = auto_context(vault, "Tell me about Bobby Torres and his role")
        assert "Bobby" in result

    def test_short_message_returns_empty(self, vault):
        result = auto_context(vault, "hi")
        assert result == ""

    def test_no_match_returns_empty(self, vault):
        result = auto_context(vault, "Tell me about quantum computing research")
        assert result == ""

    def test_command_returns_empty(self, vault):
        result = auto_context(vault, "/status check please")
        assert result == ""

    def test_nonexistent_vault_returns_empty(self, tmp_path):
        result = auto_context(tmp_path / "nope", "Tell me about something")
        assert result == ""
