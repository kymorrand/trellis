"""Tests for trellis.memory.vector_store — SQLite vector similarity search."""

from __future__ import annotations

from pathlib import Path


from trellis.memory.vector_store import VectorStore

# Match nomic-embed-text dimension
DIM = 768


def _vec(seed: float = 0.0) -> list[float]:
    """Generate a deterministic test vector. Different seeds → different vectors."""
    return [(seed + float(i)) / DIM for i in range(DIM)]


class TestVectorStoreInit:
    """Tests for VectorStore creation."""

    def test_creates_db_file(self, tmp_path: Path) -> None:
        """Creating a VectorStore creates the DB file."""
        db_path = tmp_path / "vectors.db"
        VectorStore(db_path)
        assert db_path.exists()

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        """VectorStore creates parent directories if they don't exist."""
        db_path = tmp_path / "deep" / "nested" / "vectors.db"
        VectorStore(db_path)
        assert db_path.exists()

    def test_reopens_existing_db(self, tmp_path: Path) -> None:
        """Reopening an existing DB preserves data."""
        db_path = tmp_path / "vectors.db"
        store1 = VectorStore(db_path)
        store1.upsert("test.md", _vec(1.0), "hash1")
        store1.close()

        store2 = VectorStore(db_path)
        assert store2.count() == 1
        store2.close()


class TestUpsertAndSearch:
    """Tests for insert/update and search operations."""

    def test_upsert_and_search_returns_item(self, tmp_path: Path) -> None:
        """Upserting a vector and searching with the same vector finds it."""
        store = VectorStore(tmp_path / "vectors.db")
        vec = _vec(1.0)
        store.upsert("notes/hello.md", vec, "abc123")

        results = store.search(vec, limit=5)
        assert len(results) >= 1
        assert results[0]["file_path"] == "notes/hello.md"

    def test_upsert_same_path_updates(self, tmp_path: Path) -> None:
        """Upserting the same file_path replaces the embedding."""
        store = VectorStore(tmp_path / "vectors.db")
        store.upsert("notes/hello.md", _vec(1.0), "hash1")
        store.upsert("notes/hello.md", _vec(2.0), "hash2")

        assert store.count() == 1
        # Verify hash was updated
        assert not store.needs_update("notes/hello.md", "hash2")
        assert store.needs_update("notes/hello.md", "hash1")

    def test_search_sorted_by_distance(self, tmp_path: Path) -> None:
        """Search results are sorted by distance ascending (closest first)."""
        store = VectorStore(tmp_path / "vectors.db")
        query = _vec(0.0)
        # Insert vectors at increasing distance from query
        store.upsert("close.md", _vec(0.1), "h1")
        store.upsert("far.md", _vec(100.0), "h2")
        store.upsert("medium.md", _vec(10.0), "h3")

        results = store.search(query, limit=5)
        assert len(results) == 3
        assert results[0]["file_path"] == "close.md"
        # Distances should be ascending
        distances = [r["distance"] for r in results]
        assert distances == sorted(distances)

    def test_search_respects_limit(self, tmp_path: Path) -> None:
        """Search returns at most `limit` results."""
        store = VectorStore(tmp_path / "vectors.db")
        for i in range(10):
            store.upsert(f"file{i}.md", _vec(float(i)), f"h{i}")

        results = store.search(_vec(0.0), limit=3)
        assert len(results) == 3

    def test_empty_store_search_returns_empty(self, tmp_path: Path) -> None:
        """Searching an empty store returns empty list."""
        store = VectorStore(tmp_path / "vectors.db")
        results = store.search(_vec(0.0), limit=5)
        assert results == []


class TestDelete:
    """Tests for deletion."""

    def test_delete_removes_from_both_tables(self, tmp_path: Path) -> None:
        """Delete removes the file from metadata and vector tables."""
        store = VectorStore(tmp_path / "vectors.db")
        store.upsert("notes/hello.md", _vec(1.0), "abc")
        assert store.count() == 1

        store.delete("notes/hello.md")
        assert store.count() == 0

        # Search should return nothing
        results = store.search(_vec(1.0), limit=5)
        assert all(r["file_path"] != "notes/hello.md" for r in results)

    def test_delete_nonexistent_is_noop(self, tmp_path: Path) -> None:
        """Deleting a non-existent path doesn't raise."""
        store = VectorStore(tmp_path / "vectors.db")
        store.delete("nonexistent.md")  # Should not raise


class TestNeedsUpdate:
    """Tests for content hash checking."""

    def test_needs_update_true_for_changed_hash(self, tmp_path: Path) -> None:
        """needs_update returns True when stored hash differs."""
        store = VectorStore(tmp_path / "vectors.db")
        store.upsert("file.md", _vec(1.0), "old_hash")
        assert store.needs_update("file.md", "new_hash") is True

    def test_needs_update_false_for_same_hash(self, tmp_path: Path) -> None:
        """needs_update returns False when hash matches."""
        store = VectorStore(tmp_path / "vectors.db")
        store.upsert("file.md", _vec(1.0), "same_hash")
        assert store.needs_update("file.md", "same_hash") is False

    def test_needs_update_true_for_missing_file(self, tmp_path: Path) -> None:
        """needs_update returns True for a file not in the store."""
        store = VectorStore(tmp_path / "vectors.db")
        assert store.needs_update("missing.md", "any_hash") is True


class TestCount:
    """Tests for count."""

    def test_count_empty(self, tmp_path: Path) -> None:
        """Empty store has count 0."""
        store = VectorStore(tmp_path / "vectors.db")
        assert store.count() == 0

    def test_count_after_inserts(self, tmp_path: Path) -> None:
        """Count reflects number of unique files."""
        store = VectorStore(tmp_path / "vectors.db")
        store.upsert("a.md", _vec(1.0), "h1")
        store.upsert("b.md", _vec(2.0), "h2")
        store.upsert("c.md", _vec(3.0), "h3")
        assert store.count() == 3

    def test_count_after_delete(self, tmp_path: Path) -> None:
        """Count decreases after delete."""
        store = VectorStore(tmp_path / "vectors.db")
        store.upsert("a.md", _vec(1.0), "h1")
        store.upsert("b.md", _vec(2.0), "h2")
        store.delete("a.md")
        assert store.count() == 1
