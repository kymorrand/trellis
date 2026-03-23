# Garden Report — 2026-03-22

## Sprint 2: Semantic Search, Integration Wiring, Knowledge Management

**Status:** ✅ Both agents shipped. Ready for merge.

---

## What Shipped

### Root — 9 commits across all 3 phases (1,921 lines added)

**Phase 1 — Semantic Search:**
- `trellis/memory/embeddings.py` (new, 129 lines) — Ollama embedding generation via nomic-embed-text. Async httpx calls, graceful degradation on connection failure, text truncation at 32K chars.
- `trellis/memory/vector_store.py` (new, 161 lines) — SQLite + sqlite-vec for cosine similarity search. Clean schema with metadata + virtual table, upsert/search/delete/needs_update.
- `trellis/memory/knowledge.py` (rewrite, 327 lines) — KnowledgeManager with hybrid search (30% keyword / 70% vector), vault indexing pipeline with batch processing, vault health stats with stale file and orphan detection via wikilink analysis.
- `trellis/mind/context.py` (modified) — `auto_context()` now accepts optional KnowledgeManager, uses hybrid search when available, falls back to keyword-only.
- `trellis/core/loop.py` (modified) — ToolExecutor and AgentBrain accept knowledge_manager + approval_queue params. vault_search tool uses hybrid search. ASK permissions create queue items.

**Phase 2 — Integration Wiring:**
- `scripts/run_discord.py` (modified) — FileWatcher, KnowledgeManager, and ApprovalQueue all wired as concurrent async tasks. Background vault indexing on startup.
- `trellis/core/heartbeat.py` (modified) — Nightly backup replaced with async `vault_backup()` from github_client.py (fixes subprocess.run in async code). Vault reindex every 6 hours. Vault health in morning brief.
- `trellis/senses/discord_channel.py` (modified) — `set_knowledge_manager()` and `set_approval_queue()` methods.

**Phase 3 — Vault Health:**
- `trellis/senses/web.py` (modified) — `GET /api/gardener/health` endpoint, `create_app()` accepts knowledge_manager param.

**Tests:** 5 new test files, 61 new tests total.
- `tests/test_embeddings.py` — 10 tests
- `tests/test_vector_store.py` — 13 tests
- `tests/test_knowledge.py` — 19 tests (indexing + search + vault health)
- `tests/test_loop.py` — +7 new tests (hybrid search + approval queue)
- `tests/test_context.py` — +3 new tests (knowledge_manager param)
- `tests/test_heartbeat.py` — +4 new tests (async backup + vault health brief)
- `tests/test_gardener_api.py` — +3 new tests (health endpoint)

### Bloom — 1 commit (Task 3B)
- `trellis/static/garden.html` (modified) — Added sidebar with Garden Health card. Shows index coverage bar, total/indexed/stale/orphan stats. Color-coded: green for coverage, yellow for stale, red for orphans > 10. GSAP animated bar fill. Gracefully handles 503 when knowledge_manager unavailable.

---

## Review Checklist

| # | Check | Root | Bloom |
|---|-------|------|-------|
| 1 | Tests for new code? | ✅ 61 new tests across 7 files | N/A (HTML) |
| 2 | Existing tests pass? | ✅ 245 passed, 0 failures | N/A (no Python changes) |
| 3 | `ruff check .` pass? | ⚠️ See issues below | ✅ (HTML only) |
| 4 | Stayed within file scope? | ⚠️ See issue #3 | ✅ static/garden.html only |
| 5 | Follows CLAUDE.md conventions? | ⚠️ See issues | ✅ |
| 6 | New dependencies? | ✅ `sqlite-vec` (approved) + `pytest-asyncio` (dev) | None |
| 7 | CHANGELOG updated? | ❌ **Not updated** | ❌ **Not updated** |

---

## Issues Found

### 🔴 Issue 1: CHANGELOG not updated — AGAIN (Root + Bloom)
We added a CLAUDE.md rule for this literally hours ago: "Don't skip CHANGELOG updates — every feature shipped needs an entry in CHANGELOG.md." Neither agent updated it. This is the exact same mistake from Sprint 1.

**Verdict:** Blocking. Both agents must add CHANGELOG entries before merge. This is not optional.

### 🟡 Issue 2: Root re-introduced unused `import os` in web.py (line 31)
Bloom cleaned this up in Sprint 1. Root's branch still has the old `import os` that's never used. The ruff output confirms: `F401 os imported but unused → trellis/senses/web.py:31`.

**Verdict:** Root should remove it. Minor, but it's literally the same lint issue Bloom fixed last time.

### 🟡 Issue 3: Root re-introduced f-string without placeholders (web.py lines 332, 350)
Bloom fixed the `f"event: ping\ndata: {{}}\n\n"` → `"event: ping\ndata: {}\n\n"` issue in Sprint 1. Root's branch reverted this fix (the diff shows it going back to f-strings).

**Verdict:** Same as above — the merge will need to keep Bloom's fixes. Root's branch is based on pre-Bloom-fix code.

### 🟡 Issue 4: Dead sort line from Sprint 1 still present (web.py line 549)
The `__hash__`-based sort that was flagged in Sprint 1 review is still in Root's branch. Same dead code, same line.

**Verdict:** Expected — Root's branch diverged before the Sprint 1 cleanup. Will be resolved at merge time.

### 🟡 Issue 5: Root deleted Bloom's `/garden` route from web.py
Root's web.py diff shows the `/garden` page route being removed (lines 151-154 deleted). This is because Root's branch diverged from before Bloom's Sprint 1 merge. Bloom's Sprint 2 branch still has the route.

**Verdict:** Merge artifact. Bloom's branch has the route. Must merge carefully — Root first (adds API endpoint + knowledge_manager param), then Bloom (keeps page route + adds health card). Verify the `/garden` route survives.

### 🟢 Issue 6: `pytest-asyncio` added to dev deps without explicit approval
Root added `pytest-asyncio>=0.24.0` to `[project.optional-dependencies] dev`. This wasn't in the sprint plan, but it's a standard test dependency needed for async test functions and the project already uses `asyncio: mode=Mode.STRICT` in pyproject.toml.

**Verdict:** Reasonable addition. Dev dependency, not runtime. Fine.

---

## Scope Boundary Audit

**Root touched:**
- ✅ `trellis/memory/embeddings.py` (new — Root's scope)
- ✅ `trellis/memory/vector_store.py` (new — Root's scope)
- ✅ `trellis/memory/knowledge.py` (rewrite — Root's scope)
- ✅ `trellis/mind/context.py` (modify — Root's scope)
- ✅ `trellis/core/loop.py` (modify — Root's scope)
- ✅ `trellis/core/heartbeat.py` (modify — Root's scope)
- ✅ `trellis/senses/discord_channel.py` (modify — Root's scope)
- ⚠️ `trellis/senses/web.py` (API endpoint — sprint plan authorized)
- ✅ `scripts/run_discord.py` (modify — Root's scope)
- ✅ `tests/*` (all test files — Root's scope)
- ✅ `pyproject.toml` (dependency — Root's scope)

**Bloom touched:**
- ✅ `trellis/static/garden.html` (Bloom's scope)

Clean. Root's web.py change was authorized by the sprint plan. Bloom stayed entirely in static/.

---

## Architecture Assessment

### What Root Built Well

- **The embedding pipeline is clean.** `embeddings.py` → `vector_store.py` → `knowledge.py` is a proper layer cake. Each module has a single responsibility. The VectorStore doesn't know about Ollama. The embeddings module doesn't know about SQLite. The KnowledgeManager orchestrates both.

- **Graceful degradation everywhere.** Ollama down? Falls back to keyword search. Vector store empty? Returns keyword-only results. knowledge_manager is None? Everything works like before. No hard dependencies on the new infrastructure.

- **The heartbeat backup fix was the right call.** Replacing `subprocess.run` in async code with the existing `vault_backup()` from github_client.py is cleaner AND adds secret scanning. Root removed ~40 lines of inline subprocess code and replaced it with a single function call.

- **Approval queue wiring is minimal and correct.** The `_queue_approval()` method creates rich queue items with tool name, input summary, and context. Falls back to the old soft-deny message if no queue is available.

- **Background vault indexing on startup** doesn't block the bot. Good. The 6-hour reindex heartbeat task ensures the index stays fresh without hammering Ollama.

### What Bloom Built Well

- **The health card is well-designed.** Coverage bar with GSAP animation, color-coded thresholds, hidden until data loads, graceful 503 handling for standalone dev mode. All design tokens, no hardcoded values.

- **The layout change from single-column to sidebar is a good UX call.** Reports on the left, health stats on the right. The page needed a second panel once we added health data.

---

## Merge Notes

This merge is more complex than Sprint 1. Both branches modified `web.py` and diverged from different points.

**Recommended merge order:**
1. Root first — adds API endpoint, knowledge_manager param, imports
2. Bloom second — adds garden route (if missing), garden.html updates
3. Post-merge verification (mandatory per CLAUDE.md):
   ```bash
   source .venv/bin/activate
   python3 -c "from trellis.senses.web import create_app; print('imports OK')"
   python -m pytest tests/ -v
   ruff check .
   ```

**Known conflicts to watch:**
- web.py imports: Root adds `os` + `re` + `KnowledgeManager`. Bloom removes `os` and `re` (from Sprint 1 state). Keep Root's `re` (needed for gardener API regex), drop `os` (unused).
- web.py f-strings: Keep Bloom's fix (plain strings, not f-strings).
- web.py `/garden` route: Must survive from Bloom's branch.
- web.py dead sort line: Delete it during merge.

---

## Queued for Kyle

1. **CHANGELOG entries required** — both agents skipped it again. Enforce before merge.
2. **Merge web.py carefully** — see conflict notes above. Import block is the danger zone.
3. **Test semantic search manually** after merge:
   ```bash
   source .venv/bin/activate
   python3 -c "
   import asyncio
   from pathlib import Path
   from trellis.memory.knowledge import KnowledgeManager
   km = KnowledgeManager(Path.home() / 'projects/ivy-vault')
   result = asyncio.run(km.index_vault())
   print(result)
   "
   ```
4. **Sprint 3 recommendation:** Split web.py. This is the third sprint where both agents touched it. The file is now 560+ lines with pages, API endpoints, and SSE streaming all in one place.

---

## By The Numbers

| Metric | Sprint 1 | Sprint 2 | Total |
|--------|----------|----------|-------|
| Tests | 184 | 245 | 245 |
| New tests | 11 | 61 | 72 |
| New modules | 0 | 3 | 3 |
| Lines added | ~800 | ~1,900 | ~2,700 |
| Root commits | 1 | 9 | 10 |
| Bloom commits | 1 | 1 | 2 |
| CHANGELOG entries | 0 | 0 | **0** 🔴 |

---

*Armando's second sprint delivered the biggest functional upgrade yet. The garden now understands meaning, not just words. But we still can't remember to update the CHANGELOG.*

*Report by Thorn — 2026-03-22*
