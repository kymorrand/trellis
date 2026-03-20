# Trellis Architecture Overview

## The Game Loop

Trellis is built around a dual-loop architecture inspired by real-time game engines and OpenClaw's agent design.

**Reactive Loop (Main):** Processes events as they arrive — Discord messages, file drops, CLI input. This is like a game's input processing and update cycle.

**Proactive Loop (Heartbeat):** Runs on a cron schedule — morning briefs, inbox checks, nightly curation. This is like a game's background AI tick that keeps the world moving even when the player is idle.

## Module Map

```
trellis/
├── core/        → Game loop. Event processing, heartbeat scheduler, state, config.
├── mind/        → AI brain. Model routing, context assembly, personality, roles.
├── senses/      → Input. Discord, file watcher, CLI — how Ivy perceives the world.
├── hands/       → Output. Vault, Linear, calendar, GitHub, shell — how Ivy acts.
├── memory/      → Save system. Journal, knowledge base, context compaction.
└── security/    → Permissions. Access control, sanitization, audit trail.
```

## Maps to Layers Concepts

| Trellis | Layers | Notes |
|---------|--------|-------|
| Obsidian vault | Context Library | File-based knowledge store |
| SOUL.md | Ditto professional context model | Agent personality and constraints |
| Roles (YAML) | Ditto Roles | Behavioral orientations per work type |
| Heartbeat scheduler | Background Sessions | Proactive autonomous work |
| Discord channels | Sessions | Scoped workspaces for different work |
| Reactive + Proactive loops | C4 Runtime Cycle | Collect → Curate → Coordinate → Compound |
| mind/router.py | Strategy level inference | Model selection and routing |
| hands/* | Tool system | Composable tools within sessions |

## Data Flow

```
Input (Discord, file drop, heartbeat)
  → Sanitize (security/sanitizer.py)
  → Assemble context (mind/context.py + memory/knowledge.py)
  → Route to model (mind/router.py → local Ollama or cloud Claude)
  → Parse response for tool calls
  → Check permissions (security/permissions.py)
  → Execute tools (hands/*)
  → Log to audit trail (security/audit.py)
  → Persist to journal (memory/journal.py)
  → Update state (core/state.py)
```

## Key Design Decisions

1. **Python, not TypeScript.** Better Anthropic SDK, faster prototyping, better ML ecosystem.
2. **No database.** Files on disk. Markdown for knowledge, JSON for state, YAML for config.
3. **No LangChain.** Direct Anthropic SDK calls. No abstractions we don't control.
4. **No third-party plugins.** Every tool is hand-written. Security over convenience.
5. **Anthropic-first inference.** Claude for cloud. Only alternatives when Anthropic doesn't offer something.
