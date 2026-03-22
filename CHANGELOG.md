# Changelog

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
