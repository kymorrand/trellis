# Trellis — Claude Code Context

## What This Is
Trellis is an experimental personal agent runtime built by Kyle Morrand (CEO of Mirror Factory). It's a paper prototype of the Layers product architecture. This is R&D, not product code.

## Agent: Ivy
Ivy is the AI assistant running on Trellis. Her personality is defined in agents/ivy/SOUL.md. She runs on a dedicated Lenovo Legion Pro 7 (Ubuntu 24.04, i9-13900HX, 32GB RAM, RTX 4090 Mobile) called "Greenhouse."

## Armando — The Gardener (Multi-Agent Dev Team)
Armando is the multi-agent Claude Code development team that builds and maintains Trellis. Named after an engineer and gardener who kept complex systems running far from shore. Ivy is the plant. Armando tends the garden.

Kyle can refer to the system as "Armando" the same way he refers to "Ivy" — one is his personal agent, the other is his dev team.

- **Thorn** (PM) — Prunes, guards quality, plans work. Never writes code directly.
- **Bloom** (Frontend) — Builds the visible layer: UI, design system, web interface.
- **Root** (Backend) — Builds the foundation: runtime, memory, security, integrations.

Agent definitions: `.claude/agents/thorn.md`, `bloom.md`, `root.md`

## Architecture
- `trellis/core/` — Event loop (`loop.py` — ReAct agent brain), heartbeat scheduler, state, config, approval queue
- `trellis/mind/` — Model routing (local/cloud), context assembly, personality engine, roles
- `trellis/senses/` — Input channels (Discord, CLI, file watcher, web UI)
- `trellis/hands/` — Output tools (vault, shell, Linear, calendar, GitHub)
- `trellis/memory/` — Journal, knowledge management, context compaction
- `trellis/security/` — Permissions, sanitization, audit trail

### Core Event Loop (core/loop.py)
The ReAct loop is Ivy's brain. It processes events through:
1. **LISTEN** — Receive event from any sense (Discord, CLI, file watcher, heartbeat)
2. **THINK** — Assemble context (auto-context from vault), call model with tool definitions
3. **ACT** — Execute tool calls (vault search/read/save, shell, journal), send results back
4. **PERSIST** — Log to journal, update state

Tool definitions: vault_search, vault_read, vault_save, shell_execute, journal_read.
Max 8 tool call rounds per request. Local models (Ollama) get chat-only path — no tools.

## Key Files
- `agents/ivy/SOUL.md` — Ivy's personality and constraints (READ THIS FIRST)
- `agents/ivy/roles/_default.yaml` — Default role configuration
- `.env` — API keys and runtime config (NEVER commit)
- `trellis/core/loop.py` — ReAct event loop with tool calling (AgentBrain class)
- `trellis/core/heartbeat.py` — Proactive scheduler (background tasks, briefs, cost tracking)
- `trellis/mind/context.py` — Auto-context assembly (keyword extraction + vault search)
- `trellis/mind/router.py` — Hybrid model routing (Ollama local / Claude cloud)
- `trellis/hands/shell.py` — Sandboxed shell execution (whitelist + audit)
- `trellis/hands/vault.py` — Obsidian vault read/write/search
- `trellis/memory/compactor.py` — Conversation history compression
- `trellis/security/permissions.py` — Action permission system (ALLOW/ASK/DENY)
- `trellis/senses/discord_channel.py` — Discord bot (uses AgentBrain for ReAct loop)
- `trellis/senses/web.py` — FastAPI web UI + API endpoints
- `scripts/run_discord.py` — Entry point: Discord bot + web server + heartbeat
- `scripts/run_web.py` — Standalone web dev server
- `scripts/trellis.service` — Systemd service file for running Ivy as a daemon

## Tech Stack
- Python 3.12+, no LangChain, no third-party agent frameworks
- Anthropic SDK for Claude API (primary cloud model)
- Ollama for local inference (qwen3:14b primary, llama3.2:3b fast)
- discord.py for Discord integration
- FastAPI + Uvicorn for web interface
- GSAP for UI animation (client-side JS)
- File-based everything: Markdown knowledge, JSON state, YAML config

## Design Principles
1. Modular — every component swappable
2. Anthropic-first — Claude is primary, only go elsewhere when needed
3. File-based — Markdown on disk, Obsidian-compatible
4. Conservative security — least privilege, no third-party code, audit everything
5. Experiment, not product — move fast, document everything

## Development Commands
- **Run (full):** `python scripts/run_discord.py` (Discord + Web :8420 + Heartbeat)
- **Run (web only):** `python scripts/run_web.py` (standalone frontend dev)
- **Tests:** `python -m pytest tests/ -v`
- **Single test:** `python -m pytest tests/test_vault.py -v`
- **Lint:** `ruff check .`
- **Lint fix:** `ruff check . --fix`
- **Type check:** `mypy trellis/` (when available)
- **Import check:** `python -c "from trellis.core.loop import AgentBrain; print('OK')"`

## Agent Scope Boundaries

### Thorn (PM) — Read everything, write to reports/queue/CLAUDE.md only
- Reads: git log, test results, `_ivy/reports/`, all source code
- Writes: `_ivy/reports/`, `_ivy/queue/`, CLAUDE.md "What NOT to Do" section
- NEVER modifies source code in `trellis/` or `agents/ivy/SOUL.md`

### Bloom (Frontend) — `trellis/static/` + `trellis/senses/web.py` only
- Reads: DESIGN.md, CLAUDE.md, all of `trellis/` for context
- Writes: `trellis/static/**`, `trellis/senses/web.py`, `scripts/run_web.py`
- NEVER modifies backend modules (core/, mind/, hands/, memory/, security/)
- NEVER modifies `trellis/senses/discord_channel.py`

### Root (Backend) — Everything except static/
- Reads: Everything
- Writes: `trellis/core/`, `trellis/mind/`, `trellis/hands/`, `trellis/memory/`,
  `trellis/security/`, `trellis/senses/discord_channel.py`, `trellis/senses/cli.py`,
  `trellis/senses/file_watcher.py`, `tests/`, `agents/ivy/roles/`, `scripts/`
- NEVER modifies `trellis/static/` or `trellis/senses/web.py`
- NEVER modifies `agents/ivy/SOUL.md` without Kyle's approval

## Security Rules
- NEVER commit .env or credentials
- All actions logged to audit trail
- Only process Discord messages from Kyle (IVY_DISCORD_ALLOWED_USER_ID)
- Shell commands whitelisted only — no sudo, no arbitrary execution
- Cloud API budget capped at $100/month
- Vault access restricted to ~/projects/ivy-vault only
- No third-party packages without Kyle's review

## Heartbeat Schedule
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

## Companion Repo
- kymorrand/ivy-vault (private) — Obsidian vault knowledge base at ~/projects/ivy-vault

## What NOT to Do
<!-- This section grows over time. Every mistake becomes a rule. -->
- Don't use `pip install` directly — use `pip install -e ".[dev]"` from repo root
- Don't modify `agents/ivy/SOUL.md` without Kyle's explicit approval
- Don't add dependencies without checking pyproject.toml first
- Don't use `asyncio.run()` inside async functions — use `await`
- Don't hardcode the vault path — always use `config["vault_path"]`
- Don't ship code without tests — every new module needs a corresponding test file
- Don't skip `ruff check .` before committing
- Don't use LangChain, CrewAI, LangGraph, or any third-party agent framework
- `litellm` is in deps but not actively used — don't build on it
- `schedule` is in deps but heartbeat uses asyncio — don't mix the two
- Don't modify files outside your agent scope boundary (see above)
- Don't use `subprocess.run` in async code — use `asyncio.create_subprocess_shell`
- Don't leave dead code in commits — clean it before pushing. If you wrote a line then replaced it with a better approach, delete the dead one. (Sprint 1: Root left a dead `__hash__`-based sort at web.py:546 that was immediately overwritten by correct stable sorts below it.)
- Don't skip CHANGELOG updates — every feature shipped needs an entry in `CHANGELOG.md`. Both Root and Bloom missed this on Sprint 1. Add the entry before or alongside your commit, not as an afterthought.
- `web.py` is shared territory between Bloom (pages/routes) and Root (API endpoints). When both need to touch it in the same sprint, the sprint plan MUST explicitly define who owns which sections. Future sprint should split into `web_pages.py` (Bloom) and `web_api.py` (Root) to eliminate this conflict zone.
- After merging worktree branches, ALWAYS run this verification sequence:
  ```
  source .venv/bin/activate
  python3 -c "from trellis.senses.web import create_app; print('imports OK')"
  python -m pytest tests/ -v
  ruff check .
  ```
  Merges can silently drop imports when both branches modify the same file. Sprint 1 lost `import re` and `import os` on first merge.
- When using `git merge -X theirs` or `-X ours` to resolve conflicts, always verify that imports from the OTHER branch survived. These strategies keep one side's content but can drop the other side's additions to shared sections like import blocks.
- Don't forget to activate the venv before running any Python commands on Greenhouse: `source ~/projects/trellis/.venv/bin/activate`
