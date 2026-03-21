# Trellis — Claude Code Context

## What This Is
Trellis is an experimental personal agent runtime built by Kyle Morrand (CEO of Mirror Factory). It's a paper prototype of the Layers product architecture. This is R&D, not product code.

## Agent: Ivy
Ivy is the AI assistant running on Trellis. Her personality is defined in agents/ivy/SOUL.md. She runs on a dedicated Lenovo Legion Pro 7 (Ubuntu 24.04, i9-13900HX, 32GB RAM, RTX 4090 Mobile) called "greenhouse."

## Architecture
- `trellis/core/` — Event loop and heartbeat scheduler (game loop pattern)
- `trellis/mind/` — Model routing, context assembly, personality engine
- `trellis/senses/` — Input channels (Discord, file watcher, CLI)
- `trellis/hands/` — Output tools (vault, Linear, calendar, GitHub, shell)
- `trellis/memory/` — Journal, knowledge management, context compaction
- `trellis/security/` — Permissions, sanitization, audit trail

## Key Files
- `agents/ivy/SOUL.md` — Ivy's personality and constraints (READ THIS FIRST)
- `agents/ivy/roles/_default.yaml` — Default role configuration
- `.env` — API keys and runtime config (NEVER commit)
- `trellis/security/permissions.py` — What Ivy is allowed to do

## Tech Stack
- Python 3.12+, no LangChain, no third-party plugins
- Anthropic SDK for Claude API (primary cloud model)
- Ollama for local inference (qwen3:14b primary, llama3.2:3b fast)
- discord.py for Discord integration
- File-based everything: Markdown knowledge, JSON state, YAML config

## Design Principles
1. Modular — every component swappable
2. Anthropic-first — Claude is primary, only go elsewhere when needed
3. File-based — Markdown on disk, Obsidian-compatible
4. Conservative security — least privilege, no third-party code, audit everything
5. Experiment, not product

## Security Rules
- NEVER commit .env or credentials
- All actions logged to audit trail
- Only process Discord messages from Kyle (IVY_DISCORD_ALLOWED_USER_ID)
- Shell commands whitelisted only — no sudo, no arbitrary execution
- Cloud API budget capped at $100/month
- Vault access restricted to ~/projects/ivy-vault only

## Companion Repo
- kymorrand/ivy-vault (private) — Obsidian vault knowledge base at ~/projects/ivy-vault