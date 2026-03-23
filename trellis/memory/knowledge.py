"""
trellis.memory.knowledge — Knowledge Manager with Hybrid Search

Manages the persistent knowledge base in the Obsidian vault.
Combines keyword search (existing vault search) with semantic vector
search (via Ollama embeddings + sqlite-vec) for hybrid retrieval.

Hybrid search algorithm:
    1. Keyword search via search_vault() — top 10
    2. Vector search via VectorStore.search() — top 10
    3. Normalize both score sets to 0-1
    4. Combine: 30% keyword + 70% vector
    5. Deduplicate by file path, keep highest combined score
    6. Return top N results
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from trellis.hands.vault import INTERNAL_DIRS, search_vault
from trellis.memory.embeddings import generate_embedding
from trellis.memory.vector_store import VectorStore

logger = logging.getLogger(__name__)

# Hybrid search weights
KEYWORD_WEIGHT = 0.3
VECTOR_WEIGHT = 0.7

# Batch size for indexing (don't overwhelm Ollama)
INDEX_BATCH_SIZE = 10

# Vault health thresholds
STALE_DAYS = 90
STALE_MIN_BYTES = 200

# Wikilink pattern for orphan detection
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]")


def _content_hash(content: str) -> str:
    """SHA-256 hash of file content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class KnowledgeManager:
    """Manages vault indexing and hybrid search."""

    def __init__(
        self,
        vault_path: Path,
        ollama_url: str = "http://localhost:11434",
    ) -> None:
        """Initialize the knowledge manager.

        Args:
            vault_path: Path to the Obsidian vault root.
            ollama_url: Base URL for the Ollama API.
        """
        self.vault_path = Path(vault_path)
        self.ollama_url = ollama_url
        self._last_indexed_at: datetime | None = None

        db_path = self.vault_path / "_ivy" / "data" / "vectors.db"
        self.vector_store = VectorStore(db_path)

    async def index_vault(self) -> dict:
        """Full vault reindex. Skips unchanged files.

        Returns:
            {"indexed": int, "skipped": int, "errors": int}
        """
        stats = {"indexed": 0, "skipped": 0, "errors": 0}

        if not self.vault_path.is_dir():
            logger.warning("Vault path does not exist: %s", self.vault_path)
            return stats

        md_files = []
        for f in self.vault_path.rglob("*.md"):
            rel = f.relative_to(self.vault_path)
            if any(part in INTERNAL_DIRS for part in rel.parts):
                continue
            md_files.append(f)

        # Process in batches
        for i in range(0, len(md_files), INDEX_BATCH_SIZE):
            batch = md_files[i : i + INDEX_BATCH_SIZE]
            for file_path in batch:
                try:
                    result = await self.index_file(file_path)
                    if result:
                        stats["indexed"] += 1
                    else:
                        stats["skipped"] += 1
                except Exception as exc:
                    logger.error("Error indexing %s: %s", file_path, exc)
                    stats["errors"] += 1

        self._last_indexed_at = datetime.now()

        logger.info(
            "Vault index complete: %d indexed, %d skipped, %d errors",
            stats["indexed"],
            stats["skipped"],
            stats["errors"],
        )
        return stats

    async def index_file(self, file_path: Path) -> bool:
        """Index a single file. Returns True if indexed, False if skipped/failed.

        Args:
            file_path: Absolute path to a markdown file in the vault.
        """
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Failed to read %s: %s", file_path, exc)
            return False

        rel_path = str(file_path.relative_to(self.vault_path))
        file_hash = _content_hash(content)

        # Skip if unchanged
        if not self.vector_store.needs_update(rel_path, file_hash):
            return False

        # Generate embedding
        embedding = await generate_embedding(content, ollama_url=self.ollama_url)
        if not embedding:
            logger.warning("Failed to generate embedding for %s", rel_path)
            return False

        # Store
        self.vector_store.upsert(rel_path, embedding, file_hash)
        logger.debug("Indexed: %s", rel_path)
        return True

    async def search(self, query: str, limit: int = 5) -> list[dict]:
        """Hybrid search: combine keyword + vector results.

        Args:
            query: Search query text.
            limit: Maximum number of results.

        Returns:
            List of {"path": str, "matches": list[str], "score": float}
            sorted by score descending.
        """
        if not query.strip():
            return []

        # 1. Keyword search
        keyword_results = search_vault(self.vault_path, query, max_results=10)

        # 2. Vector search (may fail if Ollama is down)
        query_embedding = await generate_embedding(query, ollama_url=self.ollama_url)
        vector_results: list[dict] = []
        if query_embedding:
            vector_results = self.vector_store.search(query_embedding, limit=10)

        # 3. Merge with normalized scores
        merged = self._merge_results(keyword_results, vector_results)

        # 4. Sort by combined score descending, return top N
        merged.sort(key=lambda r: r["score"], reverse=True)
        return merged[:limit]

    async def vault_health(self) -> dict:
        """Compute vault health statistics.

        Returns:
            {
                "total_files": int,
                "indexed_files": int,
                "stale_files": int,
                "orphan_files": int,
                "last_indexed": str | None,   # ISO format datetime
                "index_coverage_pct": float,
            }
        """
        if not self.vault_path.is_dir():
            return {
                "total_files": 0,
                "indexed_files": 0,
                "stale_files": 0,
                "orphan_files": 0,
                "last_indexed": None,
                "index_coverage_pct": 0.0,
            }

        # Collect all vault .md files (excluding internal dirs)
        md_files: list[Path] = []
        for f in self.vault_path.rglob("*.md"):
            rel = f.relative_to(self.vault_path)
            if any(part in INTERNAL_DIRS for part in rel.parts):
                continue
            md_files.append(f)

        total_files = len(md_files)
        indexed_files = self.vector_store.count()

        # Stale files: not modified in 90+ days AND under 200 bytes
        now = datetime.now()
        stale_cutoff = now - timedelta(days=STALE_DAYS)
        stale_files = 0
        for f in md_files:
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                size = f.stat().st_size
                if mtime < stale_cutoff and size < STALE_MIN_BYTES:
                    stale_files += 1
            except OSError:
                continue

        # Orphan files: .md files with no inbound [[wikilink]] from other files
        orphan_files = self._count_orphans(md_files)

        # Coverage
        index_coverage_pct = (
            round(indexed_files / total_files * 100, 1)
            if total_files > 0
            else 0.0
        )

        last_indexed = (
            self._last_indexed_at.isoformat()
            if self._last_indexed_at
            else None
        )

        return {
            "total_files": total_files,
            "indexed_files": indexed_files,
            "stale_files": stale_files,
            "orphan_files": orphan_files,
            "last_indexed": last_indexed,
            "index_coverage_pct": index_coverage_pct,
        }

    def _count_orphans(self, md_files: list[Path]) -> int:
        """Count files with no inbound wikilinks from other vault files."""
        # Collect all outbound link targets across the vault
        linked_stems: set[str] = set()
        for f in md_files:
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for match in _WIKILINK_RE.finditer(content):
                target = match.group(1).strip()
                # Handle paths like "folder/note" — just use the last part
                if "/" in target:
                    target = target.rsplit("/", 1)[-1]
                linked_stems.add(target)

        # Orphans: files whose stem is not in any other file's outbound links
        orphan_count = 0
        for f in md_files:
            if f.stem not in linked_stems:
                orphan_count += 1

        return orphan_count

    def _merge_results(
        self,
        keyword_results: list[dict],
        vector_results: list[dict],
    ) -> list[dict]:
        """Merge keyword and vector results with weighted scoring.

        Keyword results have "relevance" (0-1).
        Vector results have "distance" (lower = closer).
        """
        # Build a combined map keyed by path
        combined: dict[str, dict] = {}

        # Normalize keyword scores (already 0-1 via relevance)
        for kr in keyword_results:
            path = kr["path"]
            keyword_score = kr.get("relevance", 0.0)
            combined[path] = {
                "path": path,
                "matches": kr.get("matches", []),
                "keyword_score": keyword_score,
                "vector_score": 0.0,
            }

        # Normalize vector distances to 0-1 scores (invert: low distance = high score)
        if vector_results:
            max_dist = max(vr["distance"] for vr in vector_results) or 1.0
            for vr in vector_results:
                path = vr["file_path"]
                # Convert distance to similarity score (0-1, higher is better)
                vector_score = 1.0 - (vr["distance"] / max_dist) if max_dist > 0 else 1.0

                if path in combined:
                    combined[path]["vector_score"] = vector_score
                else:
                    combined[path] = {
                        "path": path,
                        "matches": [],
                        "keyword_score": 0.0,
                        "vector_score": vector_score,
                    }

        # Compute final weighted score
        results = []
        for entry in combined.values():
            score = (
                KEYWORD_WEIGHT * entry["keyword_score"]
                + VECTOR_WEIGHT * entry["vector_score"]
            )
            results.append({
                "path": entry["path"],
                "matches": entry["matches"],
                "score": round(score, 4),
            })

        return results
