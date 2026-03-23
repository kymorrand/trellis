# Root Status Report — 2026-03-22

## Sprint 2 Complete — All Phases Delivered

---

## Phase 1: Semantic Search (Tasks 1A-1E)
- VectorStore with sqlite-vec for embedding storage (16 tests)
- Ollama embedding generation via nomic-embed-text (10 tests)
- KnowledgeManager with hybrid search — 30% keyword + 70% vector (12 tests)
- Wired into context assembly and tool executor (7 tests)
- Background vault indexing on startup, reindex every 6h via heartbeat

## Phase 2: Runtime Integration (Tasks 2A-2C)
- **Task 2A** — FileWatcher wired as concurrent async task in `run_discord.py`
- **Task 2B** — Replaced inline `subprocess.run` backup with async `vault_backup()` from `github_client.py`. Discord alerts on failure/exception.
- **Task 2C** — ApprovalQueue wired into `AgentBrain` and `ToolExecutor`. ASK-level permissions now create queue items with full context instead of soft-denying.

## Phase 3: Vault Health & Gardener API (Tasks 3A-3B)
- **Task 3A** — `KnowledgeManager.vault_health()` returns total/indexed/stale/orphan file counts, index coverage %, last indexed timestamp. Stale = not modified in 90+ days AND under 200 bytes. Orphans detected via `[[wikilink]]` analysis.
- **Task 3B** — `GET /api/gardener/health` endpoint added to `web.py`. `create_app()` accepts `knowledge_manager` param. Morning brief includes vault health stats when available.

## Verification
- `python -m pytest tests/ -v` — **245 passed** (all green)
- `ruff check .` — clean on all new/modified files (only pre-existing E402 in scripts/)

## Files Modified (Phase 2+3)
| File | Change |
|------|--------|
| `trellis/memory/knowledge.py` | Added `vault_health()`, `_count_orphans()`, wikilink regex, stale/orphan constants |
| `trellis/core/heartbeat.py` | Async backup via `vault_backup()`, vault health in morning brief |
| `trellis/core/loop.py` | `approval_queue` param on `ToolExecutor`/`AgentBrain`, `_queue_approval()` method |
| `trellis/senses/discord_channel.py` | `set_approval_queue()` method |
| `trellis/senses/web.py` | `GET /api/gardener/health`, `knowledge_manager` param on `create_app()` |
| `scripts/run_discord.py` | FileWatcher, approval_queue, knowledge_manager wiring |
| `tests/test_knowledge.py` | 8 new tests (vault health + last_indexed) |
| `tests/test_heartbeat.py` | 4 new tests (async backup + vault health brief) |
| `tests/test_loop.py` | 3 new tests (approval queue wiring) |
| `tests/test_gardener_api.py` | 3 new tests (health endpoint) |

## Handoffs
- **Bloom**: `GET /api/gardener/health` is ready. Returns `{total_files, indexed_files, stale_files, orphan_files, last_indexed, index_coverage_pct}`. Build the health card on the garden page.
- **Thorn**: All sprint tasks complete. Ready for review.

## Notes
- `run_web.py` calls `create_app()` without `knowledge_manager` — the health endpoint returns 503 in standalone web dev mode. This is intentional.
- All new parameters default to `None` for backward compatibility.
- Orphan detection uses file stems to match wikilinks, handles `[[folder/note]]` paths.
