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
- `trellis/core/heartbeat.py` — Proactive scheduler (background tasks, briefs, cost tracking)
- `trellis/mind/context.py` — Auto-context assembly (keyword extraction + vault search)
- `scripts/run_discord.py` — Entry point: Discord bot + heartbeat as concurrent async tasks
- `scripts/trellis.service` — Systemd service file for running Ivy as a daemon

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

## Heartbeat Schedule
The heartbeat runs as an async background task alongside the Discord bot:
- **Every 30 min** — Inbox check (`_ivy/inbox/`) — silent, logs to journal
- **Midnight** — Nightly vault backup (git add/commit/push), journal rollover, cost report
- **8:00 AM** — Morning brief posted to Discord (overnight activity, queue, vault stats)
- **6:00 PM** — End of day summary posted to Discord (messages, saves, API cost)
- **Budget alerts** — Warns on Discord if monthly API spend exceeds 75% of IVY_BUDGET_MONTHLY

## Discord Commands
- `!clear` — Clear conversation history
- `/status` — On-demand status report (uptime, vault stats, API spend, activity)
- `/local <msg>` — Force local model (Ollama)
- `/claude <msg>` — Force cloud model (Anthropic)
- `remember this: <content>` — Save to vault

## Auto-Context Assembly
On every non-trivial message, Ivy automatically:
1. Extracts 2-3 keywords from the message (filtering stop words)
2. Searches the vault with those keywords
3. Includes relevant results as context in the model prompt
This means mentioning people, projects, or concepts pulls in vault knowledge without explicit "search the vault" commands.

## Running
- **Development:** `python scripts/run_discord.py`
- **Production:** `sudo bash scripts/install-service.sh` (systemd, auto-restart, survives reboots)
- **Tests:** `python -m pytest tests/ -v`

## Companion Repo
- kymorrand/ivy-vault (private) — Obsidian vault knowledge base at ~/projects/ivy-vault