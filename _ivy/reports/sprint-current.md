# Sprint 3b — Discord Approval Commands + Local Model Grounding

**Date:** 2026-03-22
**Linear Issues:** MOR-22, MOR-23
**Scope:** Root only (backend)
**Status:** In Progress

## MOR-22: Discord Approval Commands

### Problem
Queue items land in `_ivy/queue/` but Kyle can't approve them from Discord.

### Implementation

**1. Extend queue item format (`trellis/core/queue.py`)**
- Add `tool_name` and `tool_input` fields to `add_item()` and frontmatter
- These store the pending tool call so it can be re-executed on approval
- Backward compatible — existing items without these fields still work

**2. Add Discord commands (`trellis/senses/discord_channel.py`)**
- `!queue` — List pending items with IDs
- `!approve <id>` — Approve item, re-execute the tool call, return result
- `!deny <id>` — Deny item with optional reason, move to dismissed/

**3. Wire approval to ToolExecutor**
- On `!approve`, read queue item, extract tool_name + tool_input
- Execute through ToolExecutor (bypassing permission check since Kyle approved)
- Move item to approved/
- Send result to Discord

### Files
- `trellis/core/queue.py` — Add tool_name/tool_input to add_item and _parse_item
- `trellis/senses/discord_channel.py` — Add !queue, !approve, !deny commands
- `trellis/core/loop.py` — Update _queue_approval to pass tool context to queue
- `tests/test_loop.py` — Update queue tests for new fields
- `CHANGELOG.md`

## MOR-23: Prevent Local Model Fabrication

### Problem
qwen3 fabricates tool actions in text responses when it has no tool access.

### Implementation (both options from the issue)

**Option A: Strengthen local grounding (`trellis/mind/soul.py`)**
- Append to `load_soul_local()` output, after the IMPORTANT section:
  "You do NOT have access to any tools. You cannot search the vault, execute 
  commands, dispatch Armando, or approve queue items. If Kyle asks you to DO 
  something that requires a tool, tell him to prefix with /claude so the 
  request routes to the cloud model which has tool access."

**Option B: Route follow-ups to cloud (`trellis/mind/router.py`)**
- Add "approve", "approved", "deny", "denied", "confirm" to SONNET_KEYWORDS

### Files
- `trellis/mind/soul.py` — Strengthen local grounding
- `trellis/mind/router.py` — Add approval keywords
- `tests/test_soul.py` — Test grounding text present
- `tests/test_router.py` — Test approve/deny route to cloud

## Acceptance Criteria
1. `!queue` lists pending items in Discord
2. `!approve <id>` executes the pending tool and returns result
3. `!deny <id>` moves item to dismissed/ without executing
4. Local model explicitly says it can't use tools
5. "approved"/"approve"/"deny" route to cloud
6. All tests pass, lint clean, CHANGELOG updated
