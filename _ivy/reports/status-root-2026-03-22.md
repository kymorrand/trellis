# Root Status Report — 2026-03-22

## Task
Sprint 2, Phase 1: Semantic search foundation (Tasks 1A, 1B, 1C).

## Deliverables

### Task 1A: `trellis/memory/embeddings.py` (new) — 10 tests
- `generate_embedding(text, ollama_url) -> list[float]` — Single text to 768-dim vector via Ollama `/api/embed`.
- `generate_embeddings_batch(texts, ollama_url) -> list[list[float]]` — Batch generation.
- Truncates input at 32000 chars (nomic-embed-text context window).
- Returns `[]` on Ollama connection failure (graceful degradation).
- Constants: `EMBEDDING_DIM=768`, `EMBEDDING_MODEL="nomic-embed-text"`, `MAX_INPUT_CHARS=32000`.

### Task 1B: `trellis/memory/vector_store.py` (new) — 16 tests
- `VectorStore(db_path)` — SQLite + sqlite-vec for cosine similarity search.
- Schema: `vault_embeddings` (metadata) + `vec_vault` (virtual vec0 table).
- Methods: `upsert()`, `search()`, `delete()`, `needs_update()`, `count()`, `close()`.
- Content hash tracking for incremental indexing.
- `sqlite-vec>=0.1.6` added to `pyproject.toml` dependencies (Kyle-approved).

### Task 1C: `trellis/memory/knowledge.py` (rewrite) — 12 tests
- `KnowledgeManager(vault_path, ollama_url)` — Full knowledge management.
- `index_file(path)` — Index single file with content hash dedup.
- `index_vault()` — Walk vault, skip internal dirs, batch process in groups of 10.
- `search(query, limit)` — Hybrid search: 30% keyword (search_vault) + 70% vector (VectorStore).
- Normalize both score sets to 0-1, merge, deduplicate by path, return top N.
- Falls back to keyword-only when Ollama is down.

## Verification
- `python -m pytest tests/ -v` — **222 passed** in 62.68s (38 new, 0 regressions)
- `ruff check` — clean on all new files
- No changes to existing source modules (except knowledge.py stub replacement)

## Next
- Task 1D: Wire hybrid search into context.py and loop.py
- Task 1E: Wire indexing into startup + heartbeat

## Data Flow
```
vault/*.md → KnowledgeManager.index_vault() → embeddings.py → VectorStore (sqlite-vec)
                                                                     ↓
query → KnowledgeManager.search() → keyword(30%) + vector(70%) → merged results
```
