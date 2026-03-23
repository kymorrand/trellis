# Status Report — Root — 2026-03-23

## Task Completed

**Sprint 3c: Fix claude CLI PATH for armando_dispatch under systemd**

## What I Did

1. **`trellis/core/loop.py`** — Updated `_armando_dispatch()` to resolve the full path to `claude` before building the command string:
   - `shutil.which("claude")` as primary resolution
   - Fallback to `/home/kyle/.local/bin/claude` if `shutil.which` returns None
   - Clear error message if neither path resolves
   - Added `import shutil` to imports

2. **`scripts/trellis.service`** — Added `Environment=PATH=/home/kyle/.local/bin:/usr/local/bin:/usr/bin:/bin` so the systemd service environment includes the directory where `claude` is installed.

3. **`tests/test_loop.py`** — Added 3 new tests:
   - `test_armando_dispatch_uses_shutil_which` — verifies full path used when `shutil.which` finds it
   - `test_armando_dispatch_fallback_path` — verifies fallback when `shutil.which` returns None
   - `test_armando_dispatch_claude_not_found` — verifies clear error when neither works
   - Updated existing `test_armando_dispatch_builds_correct_command` to mock `shutil.which`

4. **`CHANGELOG.md`** — Added entry for this fix.

## Verification

- **Tests:** 327 passed, 0 failed (`python -m pytest tests/ -v`)
- **Lint:** Clean on all modified files (`ruff check .`)
- **Import check:** `from trellis.core.loop import AgentBrain` — OK

## Commit

`f1af98e` — `fix: resolve claude CLI full path in armando_dispatch for systemd`

## What's Blocked

Nothing.

## What Needs Kyle

- After merging, run `sudo systemctl daemon-reload && sudo systemctl restart trellis.service` to pick up the new PATH environment variable.
- Verify with a test dispatch: queue an `armando_dispatch` call and `!approve` it.

## Scope Compliance

All changes within Root's scope boundaries. Did not touch `trellis/static/`, `trellis/senses/web.py`, or `agents/ivy/SOUL.md`.
