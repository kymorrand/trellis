# Sprint 3c — Fix `claude` PATH for Armando Dispatch Under systemd

**Date:** 2026-03-23
**Scope:** Root only (backend)
**Status:** Complete — shipped as `f1af98e`

## Problem

When Ivy runs under systemd, `claude` isn't on the PATH. systemd provides a minimal PATH (`/usr/local/bin:/usr/bin:/bin`) that doesn't include `/home/kyle/.local/bin/` where the `claude` CLI is installed. This causes `armando_dispatch` to fail with `claude: not found`.

## Implementation

### 1. Resolve `claude` binary path dynamically (`trellis/core/loop.py`)
- In `_armando_dispatch()`, use `shutil.which("claude")` to find the binary
- If not found on PATH, fall back to `/home/kyle/.local/bin/claude`
- If still not found, return a clear error message
- Add `import shutil` (if not already present)

### 2. Update systemd service (`scripts/trellis.service`)
- Add `Environment=PATH=/home/kyle/.local/bin:/usr/local/bin:/usr/bin:/bin`
- This ensures all user-installed tools are accessible from the service

### 3. Tests
- Test that `_armando_dispatch` uses full path to claude binary
- Test fallback when `shutil.which` returns None

### Files (Root scope)
- `trellis/core/loop.py` — Update `_armando_dispatch()` to resolve full path
- `scripts/trellis.service` — Add PATH environment
- `tests/test_loop.py` — Add tests for path resolution
- `CHANGELOG.md` — Add entry

### Files NOT to touch
- `trellis/static/` — Bloom's scope
- `trellis/senses/web.py` — Bloom's scope
- `agents/ivy/SOUL.md` — Kyle approval required

## Acceptance Criteria
1. `_armando_dispatch` resolves `claude` to full path before executing
2. Clear error if `claude` binary not found anywhere
3. systemd service file includes user PATH
4. Tests pass, lint clean, CHANGELOG updated
5. After deploy: `!approve` on an armando_dispatch queue item should execute successfully
