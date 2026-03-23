# Sprint 2: Semantic Search, Integration Wiring, Knowledge Management

**Start:** 2026-03-22
**Status:** Planning
**Goal:** Close the three biggest functional gaps from the OpenClaw audit: semantic search (Priority 1), wire existing integrations into the runtime (Priority 2), and implement knowledge management (Priority 3).

This is a large sprint. Three priorities, phased. Priority 1 (semantic search) is the foundation — Priorities 2 and 3 depend on parts of it.

---

## Phase 1: Semantic Search (Root)

The single biggest functional gap. Keyword search misses relevant content when wording differs. "What do we know about competitive analysis" should find notes about "market research."

### New Dependency

**`sqlite-vec`** — SQLite extension for vector similarity search. Single pip install, no external services, data stays local.

```
pip install sqlite-vec
```

Must be added to `pyproject.toml` dependencies. Kyle approves before Root begins.

### Task 1A: Embedding Generation — `trellis/memory/embeddings.py` (new)
**Owner:** Root
**Scope:** `trellis/memory/embeddings.py` (new), `tests/test_embeddings.py` (new)

**Requirements:**
- Generate embeddings via Ollama's `/api/embed` endpoint (local, free, private).
- Model: `nomic-embed-text` (768 dimensions, good quality, runs on RTX 4090).
- Functions:
  ```python
  async def generate_embedding(text: str, ollama_url: str = "http://localhost:11434") -> list[float]:
      """Generate a 768-dim embedding vector for a text string."""

  async def generate_embeddings_batch(texts: list[str], ollama_url: str = "http://localhost:11434") -> list[list[float]]:
      """Batch embedding generation. Ollama handles batching internally."""
  ```
- Use `httpx.AsyncClient` for the Ollama API call.
- Truncate input text to 8192 tokens (Nomic's context window) — estimate at 4 chars/token, truncate at 32000 chars.
- Return empty list on Ollama connection failure (graceful degradation — don't crash if Ollama is down).

**Tests (`tests/test_embeddings.py`):**
- Mock the Ollama HTTP call (don't require running Ollama in CI).
- Single text returns list[float] of length 768.
- Batch returns correct number of embeddings.
- Empty text returns a valid embedding (not an error).
- Ollama connection failure returns empty list.
- Text over 32000 chars is truncated before sending.

### Task 1B: Vector Index — `trellis/memory/vector_store.py` (new)
**Owner:** Root
**Scope:** `trellis/memory/vector_store.py` (new), `tests/test_vector_store.py` (new)

**Requirements:**
- SQLite database at `{vault_path}/_ivy/data/vectors.db`.
- Uses `sqlite-vec` extension for cosine similarity search.
- Schema:
  ```sql
  CREATE TABLE IF NOT EXISTS vault_embeddings (
      file_path TEXT PRIMARY KEY,
      content_hash TEXT NOT NULL,
      updated_at TEXT NOT NULL
  );
  CREATE VIRTUAL TABLE IF NOT EXISTS vec_vault USING vec0(
      file_path TEXT,
      embedding float[768]
  );
  ```
- Functions:
  ```python
  class VectorStore:
      def __init__(self, db_path: Path): ...
      def upsert(self, file_path: str, embedding: list[float], content_hash: str) -> None: ...
      def search(self, query_embedding: list[float], limit: int = 5) -> list[dict]: ...
      def delete(self, file_path: str) -> None: ...
      def needs_update(self, file_path: str, content_hash: str) -> bool: ...
      def count(self) -> int: ...
  ```
- `search` returns `[{"file_path": str, "distance": float}, ...]` sorted by distance ascending (closest first).
- `needs_update` checks if the stored `content_hash` matches — skip re-embedding unchanged files.
- `content_hash` is SHA-256 of the file content. Root computes it in the indexing pipeline, not in VectorStore.

**Tests (`tests/test_vector_store.py`):**
- Create store in tmp_path, verify DB file created.
- Upsert + search returns the inserted item.
- Upsert same file_path updates embedding.
- Search returns results sorted by distance.
- Delete removes from both tables.
- needs_update returns True for changed hash, False for same hash.
- count returns correct number.
- Empty store search returns empty list.

### Task 1C: Indexing Pipeline — `trellis/memory/knowledge.py` (rewrite)
**Owner:** Root
**Scope:** `trellis/memory/knowledge.py` (rewrite — currently empty stub), `tests/test_knowledge.py` (new)

**Requirements:**
- Replaces the empty stub with a working knowledge manager.
- Functions:
  ```python
  class KnowledgeManager:
      def __init__(self, vault_path: Path, ollama_url: str = "http://localhost:11434"): ...

      async def index_vault(self) -> dict:
          """Full vault reindex. Returns {"indexed": int, "skipped": int, "errors": int}."""

      async def index_file(self, file_path: Path) -> bool:
          """Index a single file. Returns True if indexed, False if skipped/failed."""

      async def search(self, query: str, limit: int = 5) -> list[dict]:
          """Hybrid search: combine keyword + vector results.
          Returns [{"path": str, "matches": list[str], "score": float}]"""
  ```
- **Hybrid search algorithm:**
  1. Run keyword search via existing `search_vault()` — get top 10.
  2. Generate query embedding, run vector search via `VectorStore.search()` — get top 10.
  3. Merge results: normalize both score sets to 0-1, combine with weights: 30% keyword + 70% vector (matches OpenClaw's proven ratio).
  4. Deduplicate by file path, keep highest combined score.
  5. Return top `limit` results.
- `index_vault` walks all `.md` files (excluding INTERNAL_DIRS), checks `needs_update`, generates embeddings for new/changed files.
- Batch indexing: process files in batches of 10 to avoid overwhelming Ollama.
- Hashes stored in VectorStore so unchanged files are skipped on re-index.

**Tests (`tests/test_knowledge.py`):**
- Mock Ollama embeddings (return fixed vectors).
- index_file on a new file returns True, creates vector entry.
- index_file on unchanged file returns False (skipped).
- index_file on changed file returns True (updated).
- search with keyword-only results (Ollama down) still works.
- search with both keyword + vector merges correctly.
- index_vault counts are accurate.
- Internal dirs skipped during indexing.

### Task 1D: Wire Hybrid Search into Context Assembly
**Owner:** Root
**Scope:** `trellis/mind/context.py` (modify), `trellis/core/loop.py` (modify `vault_search` tool)

**Requirements:**
- `auto_context()` gains an optional `knowledge_manager: KnowledgeManager | None` parameter.
- If `knowledge_manager` is provided, use `knowledge_manager.search()` instead of `search_vault()`.
- Falls back to keyword-only search if knowledge_manager is None (backward compatible).
- `vault_search` tool in `loop.py` also uses hybrid search when available.
- `AgentBrain.__init__` gains optional `knowledge_manager` parameter, passes it to ToolExecutor.
- ToolExecutor stores the knowledge_manager reference, uses it in `_vault_search` if available.

**Tests:** Update `tests/test_context.py` and `tests/test_loop.py` to cover the new parameter. Existing tests must still pass with knowledge_manager=None.

### Task 1E: Vault Indexing on Startup + Heartbeat
**Owner:** Root
**Scope:** `scripts/run_discord.py` (modify), `trellis/core/heartbeat.py` (modify)

**Requirements:**
- On startup in `run_discord.py`: create `KnowledgeManager`, run `index_vault()` as a background task (don't block bot startup).
- Pass `knowledge_manager` to `AgentBrain` (via `create_bot` or directly).
- Add heartbeat task: every 6 hours, run `index_vault()` to pick up vault changes.
- Log indexing stats to journal.

---

## Phase 2: Wire Up Existing Integrations (Root)

The hard work is done — clients exist. They just need to be connected.

### Task 2A: Wire File Watcher into Runtime
**Owner:** Root
**Scope:** `scripts/run_discord.py` (modify)

**Requirements:**
- Import `FileWatcher` from `trellis.senses.file_watcher`.
- Create a `FileWatcher` instance in `run_all()` with `vault_path`.
- Start it as a concurrent async task alongside heartbeat and web server.
- Stop it in the shutdown handler.
- No callback needed for now — the watcher already logs to journal and moves files to processed.

**This is ~10 lines of code.** The FileWatcher class is fully implemented and tested-by-use.

### Task 2B: Connect vault_backup to Heartbeat (async version)
**Owner:** Root
**Scope:** `trellis/core/heartbeat.py` (modify)

**Requirements:**
- Replace the `subprocess.run` backup in `_nightly_backup()` with a call to `github_client.vault_backup()`.
- The async version in `github_client.py` already does everything the heartbeat's inline version does (git add, commit, push) PLUS pre-push secret scanning.
- Remove the inline subprocess backup code from heartbeat.py.
- Import is: `from trellis.hands.github_client import vault_backup`.

**Why:** The heartbeat currently uses `subprocess.run` (synchronous) in an async function. CLAUDE.md says "Don't use subprocess.run in async code." The github_client already has the proper `asyncio.create_subprocess_exec` version with secret scanning. This is a cleanup + upgrade.

### Task 2C: Wire ASK Permissions to Approval Queue
**Owner:** Root
**Scope:** `trellis/core/loop.py` (modify ToolExecutor), `trellis/core/queue.py` (read existing API)

**Requirements:**
- Currently, `ToolExecutor.execute()` returns a denial string for ASK-level permissions. The comment says "In the future, this will queue an approval request."
- The future is now. `ApprovalQueue` exists and works.
- When `perm == Permission.ASK`: create a queue item via `ApprovalQueue.add_item()` with the tool name, input, and a description.
- Return a message like: "This action requires Kyle's approval. I've added it to the queue."
- ToolExecutor needs access to the ApprovalQueue — add it as an optional constructor parameter.
- Pass it through from AgentBrain → ToolExecutor.

**Tests:** Update `tests/test_loop.py` — the ASK permission test should verify a queue item was created (mock the queue).

---

## Phase 3: Knowledge Management (Root + Bloom)

### Task 3A: Vault Health Stats
**Owner:** Root
**Scope:** `trellis/memory/knowledge.py` (add method), `trellis/core/heartbeat.py` (add to morning brief)

**Requirements:**
- Add to KnowledgeManager:
  ```python
  async def vault_health(self) -> dict:
      """Returns {"total_files": int, "indexed_files": int, "stale_files": int, "orphan_files": int}"""
  ```
- `stale_files`: .md files not modified in 90+ days and under 200 bytes (seeds that never grew).
- `orphan_files`: .md files with no inbound links from other vault files (basic `[[wikilink]]` detection).
- Add vault health to morning brief output — one line: "Vault: 142 files (138 indexed, 3 stale, 7 orphans)".

### Task 3B: Vault Health API + Garden Page Update
**Owner:** Root (API) + Bloom (UI)

**Root's scope:** `trellis/senses/web.py` — new endpoint (see web.py ownership note below)

**API Contract — `GET /api/gardener/health`:**
```json
{
  "total_files": 142,
  "indexed_files": 138,
  "stale_files": 3,
  "orphan_files": 7,
  "last_indexed": "2026-03-22T14:30:00",
  "index_coverage_pct": 97.2
}
```

**Bloom's scope:** `trellis/static/garden.html` — add a "Vault Health" card above the report list, showing the stats. Use `--color-leaf` for coverage percentage, `--color-wf-yellow` for stale count, `--color-wf-red` if orphans > 10.

---

## web.py Ownership Protocol (Sprint 2)

Per Sprint 1 lessons, explicitly defining who touches what:

| Section | Owner | What |
|---------|-------|------|
| Module docstring | Whoever adds their entry | Both update the docstring for their additions |
| Imports | Root | Root adds `import` lines needed for API endpoints |
| Pages section (`# Pages`) | Bloom | Bloom adds page routes |
| API sections | Root | Root adds all new API endpoints |
| Existing endpoint code | Nobody | Don't touch existing endpoints unless fixing a bug |

**Sprint 3 goal:** Split `web.py` into `web_pages.py` (Bloom) and `web_api.py` (Root). This sprint we manage the conflict manually. Root merges first, Bloom second.

---

## Sequence

```
Phase 1 (Root only — sequential)
  1A: embeddings.py ──► 1B: vector_store.py ──► 1C: knowledge.py ──► 1D: context wiring ──► 1E: startup wiring

Phase 2 (Root only — can parallel with late Phase 1)
  2A: file watcher wiring  }
  2B: backup async upgrade } ── all independent, can ship together
  2C: ASK → queue wiring   }

Phase 3 (Root + Bloom — after Phase 1 ships)
  3A: vault health stats (Root) ──► 3B: API + UI (Root then Bloom)
```

Root does Phase 1A-1C first. Once hybrid search works, Phase 1D-1E wires it in. Phase 2 tasks are independent plumbing — Root can interleave them. Phase 3 depends on Phase 1's KnowledgeManager existing.

**Bloom's only task is 3B (garden page update).** She's blocked until Root ships the health API.

---

## Definition of Done (whole sprint)

- [ ] `pip install sqlite-vec` added to pyproject.toml
- [ ] `nomic-embed-text` model pulled on Greenhouse (`ollama pull nomic-embed-text`)
- [ ] Hybrid search returns semantically relevant results (manual test: "competitive analysis" finds "market research" notes)
- [ ] `python -m pytest tests/ -v` — all pass, including new tests
- [ ] `ruff check .` — clean
- [ ] File watcher runs on startup
- [ ] Nightly backup uses async github_client (no more subprocess.run in heartbeat)
- [ ] ASK permissions create queue items
- [ ] Vault health shows in morning brief and /garden page
- [ ] CHANGELOG.md updated (both Root and Bloom add their entries)
- [ ] Status reports written by both agents
- [ ] Thorn review passes

---

## Pre-Sprint Checklist (Kyle)

Before handing off to Root:

1. **Approve `sqlite-vec` dependency** — needs to go in pyproject.toml
2. **Pull the embedding model on Greenhouse:**
   ```bash
   ollama pull nomic-embed-text
   ```
3. **Verify Ollama embeddings work:**
   ```bash
   curl http://localhost:11434/api/embed -d '{"model": "nomic-embed-text", "input": "test"}'
   ```
   Should return a JSON object with an `embeddings` array.
4. **Create worktree branches** (if not reusing existing ones):
   ```bash
   cd ~/projects/trellis
   git checkout -B worktree-trellis-backend
   git checkout -B worktree-trellis-frontend
   git checkout main
   ```

---

## Notes

- `sqlite-vec` is the only new dependency. It's a C extension distributed as a wheel — no build tools needed.
- Ollama embeddings are free and local. No API cost for indexing.
- The hybrid 30/70 keyword/vector ratio comes from OpenClaw's tuning. We can adjust later.
- `nomic-embed-text` was chosen over `mxbai-embed-large` because it has a larger context window (8192 tokens vs 512) and better benchmark scores at similar size.
- If Ollama is down, everything falls back to keyword-only search. No hard dependency on the embedding service.
