# Changelog

## 2026-03-22 — Sprint 2: Semantic Search, Gardener Activity, Vault Health

Ivy gains semantic understanding of the vault, the runtime gets fully async plumbing, and Armando gets a face — the new `/garden` page shows what the dev team has been doing.

### Semantic Search Pipeline

- **Embeddings** (`trellis/memory/embeddings.py`) — Ollama `/api/embed` integration using nomic-embed-text (768-dim vectors). Async with httpx, 60s timeout, truncates at 32k chars, returns empty list on failure.
- **Vector Store** (`trellis/memory/vector_store.py`) — SQLite + sqlite-vec for cosine similarity search. `upsert()`, `search()`, `delete()`, `needs_update()` with content-hash dedup.
- **Hybrid Search** (`trellis/memory/knowledge.py`) — `KnowledgeManager` combines keyword search (30% weight) with vector search (70% weight), normalizes scores, deduplicates by path. Falls back to keyword-only when Ollama is down.
- **Context Assembly** — `auto_context()` now routes through hybrid search when `KnowledgeManager` is available. `vault_search` tool does the same. Both fall back to keyword-only gracefully.
- **Background Indexing** — Full vault indexed on startup as a non-blocking async task. Heartbeat reindexes every 6 hours. Unchanged files skipped via content hash.

### Runtime Integration

- **File Watcher** — `FileWatcher` wired as a concurrent async task in the main process alongside Discord bot, web server, and heartbeat. Monitors `_ivy/inbox/` for new files.
- **Async Vault Backup** — Nightly backup replaced inline `subprocess.run` with async `vault_backup()` from `trellis/hands/github_client.py` (uses `asyncio.create_subprocess_exec` with pre-push secret scanning). Discord alerts on failure or exception.
- **Approval Queue Wiring** — `ApprovalQueue` connected to `ToolExecutor` and `AgentBrain`. When the permission system returns ASK, a queue item is created with tool name, input summary, and context instead of soft-denying. Works with or without queue (backward compatible).

### Garden Page (`/garden`)

- **Gardener Activity** (`trellis/static/garden.html`) — 1920x1080 kiosk display showing Armando's development reports. Two-column layout: scrollable report list (left) + health sidebar (right).
- **Report cards** — Color-coded by agent: Root (`--color-leaf`), Bloom (`--color-wf-yellow`), Thorn (`--color-wf-red`). Agent tags as tinted pill badges. Grouped by date with Recursive Mono uppercase headers.
- **Garden Health card** — Sidebar card showing knowledge index stats from `GET /api/gardener/health`:
  - Index coverage bar (6px, GSAP-animated fill, color shifts: green >80%, yellow 50-80%, red <50%)
  - Four-stat grid: total files, indexed, stale, orphaned
  - Stale/orphan counts highlight in warn/danger when non-zero
  - Last-indexed timestamp in relative garden time
  - Gracefully hidden when endpoint returns 503 (standalone dev mode)
- **Empty state** — Plant SVG icon + "No reports yet. The garden is quiet."
- **Cross-page navigation** — Header nav links to Canvas, Brief, and Garden
- **GSAP entrance animations** — Staggered card fade-up (0.06s intervals), sidebar slides in from right, coverage bar fills after card appears

### Vault Health API

- **`KnowledgeManager.vault_health()`** — Returns total files, indexed files, stale files (not modified in 90+ days AND under 200 bytes), orphan files (no inbound `[[wikilinks]]`), last indexed timestamp, and index coverage percentage.
- **`GET /api/gardener/status`** — Returns Armando's development reports (status + garden reports) parsed from `_ivy/reports/`. Agent, type, and date extracted from filenames.
- **`GET /api/gardener/health`** — New endpoint exposing vault health stats. Returns 503 when knowledge manager is unavailable (standalone web dev mode).
- **Morning Brief** — Now includes vault health stats (file count, indexed, stale, orphans) when knowledge manager is available, with graceful fallback to simple file count.

### Testing

- **`tests/test_gardener_api.py`** — Tests for gardener status endpoint: empty reports, single status file, garden report, sorting, malformed filenames, fallback summary, missing vault path

### Dependencies Added

- `sqlite-vec>=0.1.6` — Vector similarity search extension for SQLite

---

## 2026-03-21 — Living Canvas: Design System + Web Interface

The Trellis design system and web interface go live. Ivy's heartbeat is now visible on Greenhouse's always-on display.

### Design System (`ivy-vault/projects/trellis/design-system/`)

- **DESIGN.md** — Master spec (11 sections): visual theme, OKLCH color palette, typography (Fraunces + Literata + Recursive Mono), spacing system, component stylings, circadian phases, agent states, garden metaphor rules, GSAP animation language, five interface definitions, anti-patterns
- **palette.md** — 15 color roles x 5 circadian phases, all OKLCH, with contrast validation rules and CSS keyframe interpolation patterns
- **typography.md** — Type scale (Major Third 1.25), variable font axis specs, circadian axis shifts, @font-face declarations
- **components.md** — 13 components (7 atoms, 5 molecules, 3 organisms) with 8-section Pandya specs
- **motion.md** — GSAP easing/duration tokens, 7 animation patterns, 24/7 display stability rules
- **states.md** — 5 agent states, 3 growth stages, 3 display modes with full animation specs
- **circadian.md** — SunCalc integration for Orlando FL, 4-layer implementation architecture
- **anti-patterns.md** — Impeccable base + 20 Trellis-specific rules + anchor image test

### Web Interface

- **FastAPI server** (`trellis/senses/web.py`) — Serves UI and 8 API endpoints
- **Living Canvas** (`/`) — 1920x1080 always-on display with real vault items, live agent state via SSE, approval cards, growth-stage SVG icons, warm cream background with film grain texture
- **Morning Brief** (`/brief`) — Phone-first layout with ScrollTrigger animations, real overnight activity, approval flow, garden stats
- **API endpoints** — `/api/status`, `/api/vault/items`, `/api/journal/recent`, `/api/agent/state`, `/api/agent/state/stream` (SSE), `/api/queue`, `/api/queue/{id}/approve`, `/api/queue/{id}/dismiss`, `/api/brief`
- **Shared JS client** (`trellis-api.js`) — Fetch wrappers, SSE connection, garden time formatting, growth-stage SVG generator

### Circadian System

- **circadian.js** — Inline SunCalc (no external dependency), generates CSS @keyframes for all 15 color roles + typography axes + background gradient. Zero runtime cost after injection.
- 5 phases (dawn/day/afternoon/evening/night) tied to real Orlando solar position
- Background gradient shifts from warm cream (day) to deep brown (night)
- Typography axes shift: Fraunces Softness + weight, Recursive Casual
- `TrellisCircadian.lockToPhase(name)` for testing

### Agent State Tracking

- **AgentState** (`trellis/core/agent_state.py`) — In-memory state with SSE subscriber queues
- Discord bot instrumented: idle → thinking → acting transitions visible on web in real-time
- 5 GSAP-animated states: idle (breathing), thinking (ripple), acting (bob), waiting (pulse), reporting (settle)

### Approval Queue

- **ApprovalQueue** (`trellis/core/queue.py`) — File-based queue using `_ivy/queue/`
- YAML frontmatter format, approve/dismiss moves to subdirectories (audit trail)
- Web UI renders cards with approve/dismiss animations, POST to API endpoints

### Infrastructure

- **Unified process** — `scripts/run_discord.py` now runs Discord bot + web server (:8420) + heartbeat as concurrent async tasks sharing state
- **Kiosk mode** — Chrome fullscreen on Greenhouse display, user-level systemd service with daily restart timer
- **Obsidian theme** — CSS snippet with Fraunces headings, Literata body, Recursive code, full warm palette (light + dark/Root Cellar)
- **Standalone dev server** — `scripts/run_web.py` for frontend development without Discord

### Dependencies Added

- `fastapi>=0.115.0`
- `uvicorn[standard]>=0.32.0`
