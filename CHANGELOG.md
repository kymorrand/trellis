# Changelog

## 2026-03-23 — Fix claude CLI PATH for armando_dispatch under systemd

When Ivy runs under systemd, `armando_dispatch` failed with `claude: not found` because systemd's minimal PATH doesn't include `~/.local/bin/`.

### Changes

- **Path resolution** (`trellis/core/loop.py`) — `_armando_dispatch()` now resolves the full path to `claude` via `shutil.which()`, with a fallback to `/home/kyle/.local/bin/claude`. Returns a clear error if neither works.
- **systemd PATH** (`scripts/trellis.service`) — Added `Environment=PATH=...` line so `shutil.which` can find `claude` in the service environment.
- **Tests** (`tests/test_loop.py`) — 3 new tests: `shutil.which` resolution, fallback path, and not-found error message.

---

## 2026-03-23 — Auto-Select Single Queue Item for !approve / !deny

`!approve` and `!deny` no longer require an ID when there's only one item in the queue — they auto-select it. With zero items, they report the queue is empty. With 2+ items, they list them and ask Kyle to specify.

### Changes

- **`!approve` auto-select** (`trellis/senses/discord_channel.py`) — When called without an ID: 0 items → "Queue is empty", 1 item → auto-approve, 2+ items → list with IDs.
- **`!deny` auto-select** (`trellis/senses/discord_channel.py`) — Same pattern: 0 items → "Queue is empty", 1 item → auto-deny, 2+ items → list with IDs.

---

## 2026-03-23 — Catch-Up Command (MOR-25)

When Kyle types `!catch-up` in Discord, Ivy runs through the ReAct loop with a structured prompt that gathers real data: recent git history, latest reports, pending queue items. Always routes to cloud (force_cloud=True) so Ivy has tool access.

### Changes

- **`!catch-up` command** (`trellis/senses/discord_channel.py`) — New command handler after `!deny`, before vault save check. Sends a structured prompt through `_get_response()` with `force_cloud=True`. The prompt instructs Ivy to use `shell_execute` for git log and ls commands, and `vault_read` for the latest garden report. 120s timeout with graceful error handling. Sets agent state to "catching up" during execution.

---

## 2026-03-22 — Context-Aware Post-Tool Routing (MOR-26)

After Ivy makes a tool call or queues something for approval, Kyle's short follow-up ("yes", "do it") no longer misroutes to the local model.

### Changes

- **`RouteResult.used_tools`** (`trellis/mind/router.py`) — New `used_tools: bool` field on `RouteResult`. Defaults to `False`. Set to `True` by the ReAct loop when any tool calls were executed during the response.
- **ReAct loop tracking** (`trellis/core/loop.py`) — `_react_loop()` tracks `any_tools_used` flag, set on both normal completion and max-rounds fallback returns.
- **`force_cloud` routing override** (`trellis/core/loop.py`) — `AgentBrain.process()` checks `event.metadata["force_cloud"]`. When set, overrides `local` and `light` routes to `cloud`. Respects explicit `/local` and `/claude` prefixes (does not override `force_local` or `force_cloud` classifications).
- **Per-channel tool tracking** (`trellis/senses/discord_channel.py`) — `_last_response_had_tools` dict tracks whether each channel's last response used tools. On the next message, if the flag is set, passes `force_cloud=True` to `_get_response`, which propagates via `Event.metadata` to `AgentBrain`.
- **`_get_response` metadata** (`trellis/senses/discord_channel.py`) — Accepts optional `force_cloud` parameter, passes it through `Event.metadata` to the brain.

### Testing

- **`tests/test_loop.py`** — 7 new tests: `used_tools` flag set/unset/max-rounds, `force_cloud` overrides local, overrides light, does not override `force_local`, does not interfere with `force_cloud`.

---

## 2026-03-22 — Sprint 3b: Discord Approval Commands + Local Model Grounding (MOR-22, MOR-23)

### Discord Approval Commands (MOR-22)

- **Queue item format** (`trellis/core/queue.py`) — `add_item()` now accepts optional `tool_name` and `tool_input` parameters. Stored in YAML frontmatter so pending tool calls can be re-executed on approval. Backward compatible — existing items without these fields still parse correctly.
- **ToolExecutor wiring** (`trellis/core/loop.py`) — `_queue_approval()` now passes `tool_name` and `tool_input` to the queue when creating ASK-level items.
- **Discord commands** (`trellis/senses/discord_channel.py`) — Three new commands:
  - `!queue` — List pending approval items with IDs and summaries
  - `!approve <id>` — Approve item and re-execute the pending tool call, returning the result
  - `!deny <id>` — Deny item and move to dismissed/ without executing

### Local Model Grounding (MOR-23)

- **Strengthen local grounding** (`trellis/mind/soul.py`) — `load_soul_local()` now explicitly tells local models they have no tool access and directs Kyle to use `/claude` for action-requiring requests.
- **Route approval keywords to cloud** (`trellis/mind/router.py`) — Added `approve|approved|deny|denied|confirm|confirmed` to SONNET_KEYWORDS so approval-related messages always route to the cloud model with tool access.

### Testing

- **`tests/test_queue.py`** (new) — 12 tests covering tool_name/tool_input storage, frontmatter serialization, backward compatibility, get/approve/dismiss operations.
- **`tests/test_loop.py`** — Updated `test_ask_permission_with_queue` to verify tool_name and tool_input are passed through.
- **`tests/test_soul.py`** — 2 new tests: no-tool-access warning present, /claude redirect present.
- **`tests/test_router.py`** — 3 new tests: "approved", "deny that request", "confirm the dispatch" all route to cloud.

---

## 2026-03-22 — Sprint 3: Armando Dispatch Tool (MOR-21)

Ivy can now launch Armando (The Gardener) for development work — the bridge between Kyle's personal agent and his multi-agent dev team.

### Armando Dispatch (`armando_dispatch` tool)

- **Tool definition** (`trellis/core/loop.py`) — New `armando_dispatch` tool in TOOL_DEFINITIONS. Schema: `message` (string) + `project_dir` (string), both required. Description warns about 15-30 min runtime.
- **Handler** (`trellis/core/loop.py`) — `ToolExecutor._armando_dispatch()` validates inputs (non-empty message, non-empty project_dir, directory exists on disk), builds the `claude` CLI command with `--dangerously-skip-permissions --agent thorn -p {message} --max-budget-usd 5 --no-session-persistence`, calls `execute_command()` with 1800s timeout.
- **Permission** (`trellis/security/permissions.py`) — `armando_dispatch` set to `Permission.ASK`. Every dispatch requires Kyle's approval via the approval queue.
- **Shell timeout** (`trellis/hands/shell.py`) — `execute_command()` now accepts an optional `timeout` parameter (default 30s, backward compatible). Also added `"claude"` to `ALLOWED_COMMANDS`.

### Ivy Personality Revision (SOUL.md)

- **Personality** — "Be direct" moved to first line. Garden metaphors downgraded from personality trait to "seasoning — not the meal." Added honesty rule for knowledge gaps.
- **Response Quality** (new section) — Concrete over atmospheric. Answer the actual question. Short by default. Cite sources. Admit gaps. Banned filler phrases.

### Testing

- **`tests/test_loop.py`** — 8 new tests: tool definition presence, schema validation, permission key mapping, ASK permission check, empty message/project_dir validation, nonexistent dir validation, correct command construction (mocked), 1800s timeout passthrough.
- **`tests/test_shell.py`** — 2 new tests: custom timeout accepted, timeout expiry kills command.

---

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

### Kyle Context Model (MOR-20)

- **`load_kyle(vault_path)`** (`trellis/mind/soul.py`) — Loads `_ivy/kyle.md` at startup and appends to system prompt after SOUL.md. Kyle's professional context model — energy architecture, communication preferences, working methodology, relationship expectations.
- **`load_kyle_local(vault_path)`** — Condensed version for local models. Extracts only: Energy Architecture, Weekly Operating Framework, Communication Preferences, and What Ivy Should Know About the Relationship (contains Good/Bad/Great). Same grounding rule as `load_soul_local()`.
- **Discord + CLI** — Both senses load kyle.md at startup. Full version appended for Claude, condensed for Ollama. No changes needed in `AgentBrain` — receives the already-assembled prompt.
- kyle.md stays in `_ivy/` (excluded from vault search by design). Loaded explicitly, not discovered.

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
