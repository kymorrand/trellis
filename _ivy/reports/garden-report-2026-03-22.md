# Garden Report — 2026-03-22

## Session: Sprint 3 — Armando Dispatch + Ivy Personality Revision

### Commits
- `381d8f8` — Add armando_dispatch tool (MOR-21)
- `4a6b7e3` — Sharpen Ivy's personality — directness first, metaphors as seasoning
- `0ea17bd` — Rewrite /status to structured data, fix CHANGELOG ordering
- `f8df447` — Include Response Quality in local model prompt

### What Shipped

**armando_dispatch tool (MOR-21)** — Ivy can now shell out to `claude --agent thorn` to launch Armando dev sprints. Permission is ASK (requires Kyle's approval). Shell timeout parameter made configurable. 10 new tests, all mocked.

**SOUL.md revision** — Personality rewritten: "be direct" is now line 1, garden metaphors explicitly downgraded to seasoning. New Response Quality section with concrete rules: facts over atmosphere, short by default, cite sources, admit gaps, banned filler phrases.

**/status rewrite** — Status report now returns structured single-line metrics instead of decorated prose. Includes queue count and actionable "needs attention" line.

**Local model prompt fix** — `load_soul_local()` wasn't extracting the new Response Quality section. Local model (qwen3) never saw the new rules. Fixed by adding "Response Quality" to the `keep` list.

### Issues Found & Resolved

1. **Zombie process causing duplicate Discord messages** — A rogue `nohup` process from a previous session survived the systemd restart. Two bot instances connected to Discord with the same token = every message got two replies. Fixed by `kill -9`. Added rule to CLAUDE.md.

2. **SOUL.md changes invisible to local model** — New sections added to SOUL.md don't automatically appear in the local model's condensed prompt. `load_soul_local()` has an explicit `keep` list that must be updated. Added rule to CLAUDE.md.

3. **CHANGELOG ordering** — Root placed the SOUL.md entry above the Armando Dispatch intro paragraph. Fixed in same session.

### Test Results
- 289 tests passing (288 existing + 1 new soul test)
- Lint clean on all source files
- Worktree directories have pre-existing lint noise (not addressed — separate cleanup task)

### Rules Added This Session
1. When adding new sections to SOUL.md, update `load_soul_local()` `keep` list — local model won't see new sections otherwise.
2. Never launch Ivy via `nohup` — always use systemd. Rogue processes cause duplicate Discord connections.
3. After restarting Ivy, verify single-instance with `ps aux | grep run_discord`.
