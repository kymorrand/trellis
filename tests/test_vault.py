"""Tests for trellis.hands.vault — Vault read/write/search operations."""

import pytest

from trellis.hands.vault import (
    search_vault,
    read_vault_file,
    save_to_vault,
    format_search_results,
)


@pytest.fixture
def vault(tmp_path):
    """Create a minimal vault structure with test files."""
    # Knowledge file
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "ai-agents.md").write_text(
        "# AI Agents\n\nAgents are autonomous systems that act on behalf of users.\n",
        encoding="utf-8",
    )
    (knowledge / "solarpunk.md").write_text(
        "# Solarpunk\n\nA genre focused on sustainability and optimism.\n",
        encoding="utf-8",
    )

    # Internal dir (should be skipped in searches)
    ivy_dir = tmp_path / "_ivy" / "journal"
    ivy_dir.mkdir(parents=True)
    (ivy_dir / "2026-03-21.md").write_text("# Internal journal\nagents mentioned here\n")

    return tmp_path


class TestSearchVault:
    def test_finds_matching_file(self, vault):
        results = search_vault(vault, "agents")
        assert len(results) == 1
        assert results[0]["path"] == "knowledge/ai-agents.md"

    def test_no_match(self, vault):
        results = search_vault(vault, "blockchain")
        assert results == []

    def test_empty_query_returns_empty(self, vault):
        assert search_vault(vault, "") == []
        assert search_vault(vault, "   ") == []

    def test_skips_internal_dirs(self, vault):
        # "_ivy" dir has "agents" in it but should be skipped
        results = search_vault(vault, "Internal journal")
        assert results == []

    def test_nonexistent_vault(self, tmp_path):
        results = search_vault(tmp_path / "nope", "anything")
        assert results == []

    def test_multiple_results_sorted_by_relevance(self, vault):
        # "solarpunk" only matches one file; "agents autonomous" matches the other more
        results = search_vault(vault, "agents autonomous")
        assert len(results) >= 1
        assert results[0]["path"] == "knowledge/ai-agents.md"


class TestReadVaultFile:
    def test_read_existing(self, vault):
        content = read_vault_file(vault, "knowledge/ai-agents.md")
        assert "autonomous systems" in content

    def test_read_nonexistent(self, vault):
        assert read_vault_file(vault, "nope.md") is None

    def test_path_traversal_blocked(self, vault):
        result = read_vault_file(vault, "../../etc/passwd")
        assert result is None


class TestSaveToVault:
    def test_save_drop(self, tmp_path):
        path = save_to_vault(tmp_path, "A quick note", "test note", category="drop")
        assert path.exists()
        assert "_ivy/inbox/drops" in str(path)
        content = path.read_text(encoding="utf-8")
        assert "A quick note" in content
        assert "tags: [drop]" in content

    def test_save_knowledge(self, tmp_path):
        path = save_to_vault(tmp_path, "Reference material", "ref item", category="knowledge")
        assert path.exists()
        assert "knowledge" in str(path)

    def test_duplicate_filename_gets_suffix(self, tmp_path):
        p1 = save_to_vault(tmp_path, "first", "same-title", category="drop")
        p2 = save_to_vault(tmp_path, "second", "same-title", category="drop")
        assert p1 != p2
        assert p2.exists()

    def test_empty_title_uses_timestamp(self, tmp_path):
        path = save_to_vault(tmp_path, "content", "", category="drop")
        assert path.exists()


class TestFormatSearchResults:
    def test_empty(self):
        assert format_search_results([]) == ""

    def test_formats_results(self):
        results = [{"path": "foo.md", "matches": ["line one", "line two"]}]
        formatted = format_search_results(results)
        assert "**foo.md**" in formatted
        assert "> line one" in formatted
