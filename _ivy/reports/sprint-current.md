# Sprint 3 — Armando Dispatch Tool

**Date:** 2026-03-22
**Linear Issue:** MOR-21
**Scope:** Root only (backend)
**Status:** In Progress

## Goal

Give Ivy the ability to dispatch Armando (The Gardener) for development work. This is the bridge between Kyle's personal agent and his dev team — Ivy does research/design, then hands off to Armando for implementation.

## Architecture

Ivy calls `armando_dispatch` tool → shells out to `claude -p` with `--agent thorn` → Thorn reads task spec, dispatches Bloom/Root, writes garden report → stdout returned to Ivy.

### Command Format
```
cd {project_dir} && claude --dangerously-skip-permissions --agent thorn -p "{message}" --max-budget-usd 5 --no-session-persistence
```

Flags verified against `claude --help`:
- `-p` / `--print` — Non-interactive mode, print response and exit ✅
- `--agent` — Agent for the session ✅
- `--dangerously-skip-permissions` — Bypass permission checks ✅
- `--max-budget-usd` — Cap API spend per dispatch ✅
- `--no-session-persistence` — Don't save session to disk ✅

## Root's Tasks

### 1. Tool Definition (`trellis/core/loop.py`)
- Add `armando_dispatch` to `TOOL_DEFINITIONS` list
- Schema: `message` (string, required), `project_dir` (string, required)
- Description must warn about 15-30 min runtime

### 2. Tool Handler (`trellis/core/loop.py`)
- Add `case "armando_dispatch"` in `ToolExecutor._run()`
- Implement `_armando_dispatch()` method on ToolExecutor
- Validate message and project_dir are non-empty
- Validate project_dir exists on disk
- Build command with `shlex.quote()` for the message
- Call `execute_command()` with 1800s timeout
- Import `shlex` at top of file (already used in shell.py)

### 3. Permission Key (`trellis/core/loop.py`)
- Add `case "armando_dispatch": return "armando_dispatch"` in `_permission_key()`

### 4. Permission Entry (`trellis/security/permissions.py`)
- Add `"armando_dispatch": Permission.ASK` to PERMISSIONS dict
- This ensures Kyle must approve every dispatch

### 5. Timeout Parameter (`trellis/hands/shell.py`)
- Add optional `timeout` parameter to `execute_command(command, cwd, timeout=TIMEOUT)`
- Pass it through to `asyncio.wait_for()` instead of hardcoded `TIMEOUT`
- Backward compatible — default is still 30s

### 6. Tests (`tests/test_loop.py` + `tests/test_shell.py`)
- `armando_dispatch` is in TOOL_DEFINITIONS
- Permission key maps to `"armando_dispatch"`
- Permission check returns ASK
- Command construction with proper escaping
- project_dir validation (empty, nonexistent)
- message validation (empty)
- Timeout override in execute_command
- Mock the claude CLI call — don't run real sprints

### 7. CHANGELOG.md
- Add entry for armando_dispatch tool

## Files Root May Touch
- `trellis/core/loop.py` — tool def, handler, permission key
- `trellis/hands/shell.py` — timeout parameter
- `trellis/security/permissions.py` — permission entry
- `tests/test_loop.py` — armando_dispatch tests
- `tests/test_shell.py` — timeout parameter tests
- `CHANGELOG.md` — new entry

## Files Root Must NOT Touch
- `trellis/static/**` (Bloom's scope)
- `trellis/senses/web.py` (Bloom's scope)
- `agents/ivy/SOUL.md` (Kyle only)

## Acceptance Criteria
1. `armando_dispatch` appears in TOOL_DEFINITIONS with correct schema
2. Permission is ASK — Ivy can never auto-dispatch without Kyle's approval
3. `execute_command` accepts optional timeout parameter (backward compatible)
4. The dispatch handler validates inputs, builds correct command, calls shell with 1800s timeout
5. All new code has tests — mock the claude CLI, don't run real sprints
6. `python -m pytest tests/ -v` passes
7. `ruff check .` passes
8. CHANGELOG.md updated
