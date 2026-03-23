"""
trellis.memory.vector_store — SQLite vector similarity search

Uses sqlite-vec extension for cosine similarity search over vault embeddings.
Data stored locally at {vault_path}/_ivy/data/vectors.db.

Schema:
    vault_embeddings — metadata table (file_path, content_hash, updated_at)
    vec_vault        — virtual table for vector search (file_path, embedding float[768])
"""

from __future__ import annotations

import logging
import sqlite3
import struct
from datetime import datetime, timezone
from pathlib import Path

import sqlite_vec

from trellis.memory.embeddings import EMBEDDING_DIM

logger = logging.getLogger(__name__)


def _serialize_vector(vec: list[float]) -> bytes:
    """Pack a list of floats into binary format for sqlite-vec."""
    return struct.pack(f"{len(vec)}f", *vec)


class VectorStore:
    """SQLite-backed vector store using sqlite-vec for similarity search."""

    def __init__(self, db_path: Path) -> None:
        """Initialize the vector store, creating DB and tables if needed.

        Args:
            db_path: Path to the SQLite database file.
        """
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(db_path))
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._conn.enable_load_extension(False)

        self._create_tables()

    def _create_tables(self) -> None:
        """Create metadata and vector tables if they don't exist."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS vault_embeddings (
                file_path TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        self._conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_vault USING vec0(
                file_path TEXT,
                embedding float[{EMBEDDING_DIM}]
            )
        """)
        self._conn.commit()

    def upsert(self, file_path: str, embedding: list[float], content_hash: str) -> None:
        """Insert or update an embedding for a file.

        Args:
            file_path: Relative path of the vault file.
            embedding: Vector of floats (length EMBEDDING_DIM).
            content_hash: SHA-256 hash of file content.
        """
        now = datetime.now(timezone.utc).isoformat()
        vec_bytes = _serialize_vector(embedding)

        # Remove existing entry if present (both tables)
        self._conn.execute("DELETE FROM vec_vault WHERE file_path = ?", (file_path,))
        self._conn.execute("DELETE FROM vault_embeddings WHERE file_path = ?", (file_path,))

        # Insert into both tables
        self._conn.execute(
            "INSERT INTO vec_vault(file_path, embedding) VALUES (?, ?)",
            (file_path, vec_bytes),
        )
        self._conn.execute(
            "INSERT INTO vault_embeddings(file_path, content_hash, updated_at) VALUES (?, ?, ?)",
            (file_path, content_hash, now),
        )
        self._conn.commit()

    def search(self, query_embedding: list[float], limit: int = 5) -> list[dict]:
        """Find the closest vectors to the query.

        Args:
            query_embedding: Query vector (length EMBEDDING_DIM).
            limit: Maximum number of results.

        Returns:
            List of {"file_path": str, "distance": float} sorted by distance ascending.
        """
        if self.count() == 0:
            return []

        vec_bytes = _serialize_vector(query_embedding)
        rows = self._conn.execute(
            """
            SELECT file_path, distance
            FROM vec_vault
            WHERE embedding MATCH ?
            ORDER BY distance
            LIMIT ?
            """,
            (vec_bytes, limit),
        ).fetchall()

        return [{"file_path": row[0], "distance": row[1]} for row in rows]

    def delete(self, file_path: str) -> None:
        """Remove a file's embedding from both tables.

        Args:
            file_path: Relative path of the vault file.
        """
        self._conn.execute("DELETE FROM vec_vault WHERE file_path = ?", (file_path,))
        self._conn.execute(
            "DELETE FROM vault_embeddings WHERE file_path = ?", (file_path,)
        )
        self._conn.commit()

    def needs_update(self, file_path: str, content_hash: str) -> bool:
        """Check if a file needs re-embedding.

        Returns True if the file is not in the store or its hash differs.

        Args:
            file_path: Relative path of the vault file.
            content_hash: Current SHA-256 hash of file content.
        """
        row = self._conn.execute(
            "SELECT content_hash FROM vault_embeddings WHERE file_path = ?",
            (file_path,),
        ).fetchone()

        if row is None:
            return True
        return row[0] != content_hash

    def count(self) -> int:
        """Return the number of indexed files."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM vault_embeddings"
        ).fetchone()
        return row[0] if row else 0

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
