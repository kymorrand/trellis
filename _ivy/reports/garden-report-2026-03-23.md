# Garden Report — 2026-03-23

## Session: Sprint 3 continued — MOR-21 through MOR-26

### Commits This Session
- `381d8f8` — Add armando_dispatch tool (MOR-21)
- `4a6b7e3` — Sharpen Ivy's personality — directness first, metaphors as seasoning
- `0ea17bd` — Rewrite /status to structured data, fix CHANGELOG ordering
- `f8df447` — Include Response Quality in local model prompt
- `f9946ff` — Sprint 3 garden report + 3 new CLAUDE.md rules
- `f45fbea` — Route tool-requiring messages to cloud — fix armando dispatch routing
- `0ac23a4` — Discord approval commands + prevent local model fabrication (MOR-22, MOR-23)
- `69db5b7` — Context-aware routing — force cloud after tool use (MOR-26)
- `7fdcfaa` — Add !catch-up command (MOR-25)

### Issues Completed
- **MOR-21** — armando_dispatch tool (Ivy can launch Armando sprints)
- **MOR-22** — Discord approval commands (!queue, !approve, !deny)
- **MOR-23** — Local model grounding (can't fabricate tool actions)
- **MOR-24** — SOUL.md response quality improvements (was already done earlier in session)
- **MOR-25** — !catch-up command for context briefing
- **MOR-26** — Context-aware routing (force cloud after tool use)

### Bugs Found & Fixed During Session
1. **Zombie nohup process** — Duplicate Discord bot connections causing double replies. Root cause: old nohup process survived systemd restart.
2. **Router misclassifying tool requests** — "Dispatch Armando" routed to local model (no tools). Fixed by adding tool keywords to SONNET_KEYWORDS.
3. **Local model fabricating actions** — qwen3 responded as if it executed tools it doesn't have access to. Fixed with explicit grounding rules + approval keyword routing.
4. **SOUL.md invisible to local model** — New Response Quality section wasn't in `load_soul_local()` keep list.
5. **Post-tool follow-ups routing to local** — "approved" after a tool queue went to qwen3. Fixed with per-channel used_tools tracking.

### Test Results
- 324 tests passing
- Lint clean on all source files

### Rules Added This Session
1. When adding new sections to SOUL.md, update `load_soul_local()` `keep` list.
2. Never launch Ivy via `nohup` — always use systemd.
3. After restarting Ivy, verify single-instance with `ps aux | grep run_discord`.

### Session End — Linear Board Update
- MOR-21 through MOR-26: all moved to **Done**
- **MOR-29** created: [Root] Graceful SIGTERM handling for Ivy service (Priority: High)
  - SIGTERM not handled → 90+ second shutdown → systemd SIGKILL
  - Acceptance: register signal handler, graceful disconnect, <5s shutdown

### Pending for Kyle
- Restart Ivy service to pick up MOR-25/MOR-26 changes (local model grounding + router keywords)
- MOR-29 ready for next sprint planning
