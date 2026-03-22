"""Tests for trellis.memory.knowledge — Knowledge manager with hybrid search."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from trellis.memory.knowledge import KnowledgeManager

# Dimension from nomic-embed-text
DIM = 768


def _fake_vec(seed: float = 0.0) -> list[float]:
    """Return a deterministic fake embedding vector."""
    return [(seed + float(i)) / DIM for i in range(DIM)]


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    """Create a minimal vault structure with some markdown files."""
    # Regular vault files
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "market-research.md").write_text(
        "# Market Research\n\nCompetitive analysis of the widget industry.\n"
        "Key players include Acme Corp and Globex.\n",
        encoding="utf-8",
    )
    (knowledge_dir / "project-plan.md").write_text(
        "# Project Plan\n\nQ1 goals and milestones for Trellis development.\n",
        encoding="utf-8",
    )
    (tmp_path / "daily-notes.md").write_text(
        "# Daily Notes\n\nMet with Kyle about strategy.\n",
        encoding="utf-8",
    )

    # Internal dirs (should be skipped)
    ivy_dir = tmp_path / "_ivy" / "journal"
    ivy_dir.mkdir(parents=True)
    (ivy_dir / "2026-03-22.md").write_text("# Journal\nInternal log.\n", encoding="utf-8")

    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("gitconfig", encoding="utf-8")

    # Data dir for vector store
    (tmp_path / "_ivy" / "data").mkdir(parents=True, exist_ok=True)

    return tmp_path


def _mock_embedding_single(seed: float = 1.0):
    """Return an async mock that returns a single embedding."""
    async def _gen(text, ollama_url="http://localhost:11434"):
        return _fake_vec(seed)
    return _gen


def _mock_embedding_batch():
    """Return an async mock that returns one embedding per input."""
    async def _gen(texts, ollama_url="http://localhost:11434"):
        return [_fake_vec(float(i)) for i in range(len(texts))]
    return _gen


def _mock_embedding_down():
    """Return an async mock simulating Ollama being down."""
    async def _gen(text, ollama_url="http://localhost:11434"):
        return []
    return _gen


def _mock_batch_down():
    """Return an async mock simulating Ollama being down for batch."""
    async def _gen(texts, ollama_url="http://localhost:11434"):
        return []
    return _gen


class TestIndexFile:
    """Tests for indexing individual files."""

    @pytest.mark.asyncio
    async def test_new_file_returns_true(self, vault: Path) -> None:
        """Indexing a new file returns True and creates a vector entry."""
        km = KnowledgeManager(vault)
        with patch("trellis.memory.knowledge.generate_embedding", new=_mock_embedding_single()):
            result = await km.index_file(vault / "knowledge" / "market-research.md")
        assert result is True
        assert km.vector_store.count() == 1

    @pytest.mark.asyncio
    async def test_unchanged_file_returns_false(self, vault: Path) -> None:
        """Indexing the same unchanged file again returns False (skipped)."""
        km = KnowledgeManager(vault)
        with patch("trellis.memory.knowledge.generate_embedding", new=_mock_embedding_single()):
            await km.index_file(vault / "knowledge" / "market-research.md")
            result = await km.index_file(vault / "knowledge" / "market-research.md")
        assert result is False

    @pytest.mark.asyncio
    async def test_changed_file_returns_true(self, vault: Path) -> None:
        """Indexing a file after content change returns True (updated)."""
        km = KnowledgeManager(vault)
        file_path = vault / "knowledge" / "market-research.md"
        with patch("trellis.memory.knowledge.generate_embedding", new=_mock_embedding_single()):
            await km.index_file(file_path)
            # Modify the file
            file_path.write_text("# Updated Content\n\nNew stuff.\n", encoding="utf-8")
            result = await km.index_file(file_path)
        assert result is True

    @pytest.mark.asyncio
    async def test_ollama_down_returns_false(self, vault: Path) -> None:
        """If Ollama is down, index_file returns False."""
        km = KnowledgeManager(vault)
        with patch("trellis.memory.knowledge.generate_embedding", new=_mock_embedding_down()):
            result = await km.index_file(vault / "knowledge" / "market-research.md")
        assert result is False


class TestIndexVault:
    """Tests for full vault indexing."""

    @pytest.mark.asyncio
    async def test_counts_are_accurate(self, vault: Path) -> None:
        """index_vault returns correct indexed/skipped/errors counts."""
        km = KnowledgeManager(vault)
        with patch("trellis.memory.knowledge.generate_embedding", new=_mock_embedding_single()):
            stats = await km.index_vault()
        # Should index: market-research.md, project-plan.md, daily-notes.md
        assert stats["indexed"] == 3
        assert stats["skipped"] == 0
        assert stats["errors"] == 0

    @pytest.mark.asyncio
    async def test_internal_dirs_skipped(self, vault: Path) -> None:
        """Files in _ivy, .git, etc. are not indexed."""
        km = KnowledgeManager(vault)
        with patch("trellis.memory.knowledge.generate_embedding", new=_mock_embedding_single()):
            await km.index_vault()
        # Only 3 user-facing files, not the journal or git config
        assert km.vector_store.count() == 3

    @pytest.mark.asyncio
    async def test_reindex_skips_unchanged(self, vault: Path) -> None:
        """Re-indexing skips unchanged files."""
        km = KnowledgeManager(vault)
        with patch("trellis.memory.knowledge.generate_embedding", new=_mock_embedding_single()):
            await km.index_vault()
            stats = await km.index_vault()
        assert stats["indexed"] == 0
        assert stats["skipped"] == 3


class TestSearch:
    """Tests for hybrid search."""

    @pytest.mark.asyncio
    async def test_keyword_only_when_ollama_down(self, vault: Path) -> None:
        """Search falls back to keyword-only when Ollama is down."""
        km = KnowledgeManager(vault)
        with patch("trellis.memory.knowledge.generate_embedding", new=_mock_embedding_down()):
            results = await km.search("competitive analysis")
        # Keyword search should still find market-research.md
        assert len(results) > 0
        paths = [r["path"] for r in results]
        assert any("market-research" in p for p in paths)

    @pytest.mark.asyncio
    async def test_hybrid_merges_results(self, vault: Path) -> None:
        """When both keyword and vector search work, results are merged."""
        km = KnowledgeManager(vault)
        # First index the vault
        with patch("trellis.memory.knowledge.generate_embedding", new=_mock_embedding_single(1.0)):
            await km.index_vault()

        # Now search — mock returns a vector that will match
        with patch("trellis.memory.knowledge.generate_embedding", new=_mock_embedding_single(1.0)):
            results = await km.search("market research competitive")

        assert len(results) > 0
        # Results should have score field
        assert all("score" in r for r in results)
        # Results should have path and matches
        assert all("path" in r for r in results)

    @pytest.mark.asyncio
    async def test_search_deduplicates(self, vault: Path) -> None:
        """Same file from keyword and vector search appears only once."""
        km = KnowledgeManager(vault)
        with patch("trellis.memory.knowledge.generate_embedding", new=_mock_embedding_single(1.0)):
            await km.index_vault()
            results = await km.search("market research")

        paths = [r["path"] for r in results]
        assert len(paths) == len(set(paths)), "Duplicate paths in results"

    @pytest.mark.asyncio
    async def test_search_respects_limit(self, vault: Path) -> None:
        """Search returns at most `limit` results."""
        km = KnowledgeManager(vault)
        with patch("trellis.memory.knowledge.generate_embedding", new=_mock_embedding_single(1.0)):
            await km.index_vault()
            results = await km.search("project plan strategy notes", limit=2)
        assert len(results) <= 2

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, vault: Path) -> None:
        """Empty query returns empty results."""
        km = KnowledgeManager(vault)
        with patch("trellis.memory.knowledge.generate_embedding", new=_mock_embedding_down()):
            results = await km.search("")
        assert results == []
