# Sprint 7: Dual-Capture Screenshot System

**Date:** 2026-03-27
**Goal:** Enable Ivy to see both "code reality" (Playwright DOM) and "user reality" (actual display via mss) to catch rendering discrepancies.

## Architecture

Two capture paths feeding into comparison:
1. **Playwright capture** (existing in `trellis/hands/screenshot.py`) — headless browser renders the page → "code reality"
2. **mss capture** (new in `trellis/hands/display_capture.py`) — screen grab of actual display → "user reality"
3. **Comparison** — Ivy receives both, can flag discrepancies via vision API (integration phase)

## Tasks

### Root — Backend Display Capture Endpoint
**Status:** Dispatched
**Files to CREATE:** `trellis/hands/display_capture.py`, `tests/test_display_capture.py`
**Files to MODIFY:** `trellis/senses/web.py` (API section ONLY — add `/api/screenshot` endpoint), `pyproject.toml` (add mss dep)
**Acceptance criteria:**
- [ ] `POST /api/screenshot` endpoint returns `{image: base64, metadata: {timestamp, url, viewport, display}}`
- [ ] Uses `mss` library for cross-platform screen capture
- [ ] Handles multiple monitors (selects primary display)
- [ ] Stores temp screenshots in `temp/screenshots/` with auto-cleanup (max 50 files, oldest deleted)
- [ ] `mss` added to `[project.optional-dependencies] dev` in pyproject.toml
- [ ] Unit tests for capture logic, endpoint, cleanup, multi-monitor handling
- [ ] CHANGELOG entry prepended (NOT replacing existing content)
- [ ] Lint clean, all existing tests still pass

**web.py ownership:** Root adds ONLY the `/api/screenshot` POST endpoint in the API section (after existing API blocks, before `return app`). Does NOT touch pages, existing endpoints, or imports beyond what's needed.

### Bloom — Frontend Debug Capture Panel
**Status:** Dispatched
**Files to CREATE:** `trellis/static/js/debug-capture.js`, `trellis/static/debug-panel.css`
**Files to MODIFY:** All `.html` files in `trellis/static/` (add script/css includes)
**Acceptance criteria:**
- [ ] Floating debug panel (bottom-right) with "📸 Capture for Ivy" button
- [ ] Keyboard shortcut Cmd/Ctrl+Shift+S triggers capture
- [ ] Panel only visible in dev mode (`location.hostname === 'localhost'` or `?debug=1`)
- [ ] Follows Trellis design system (oklch colors, warm cream aesthetic, grain-compatible)
- [ ] Shows capture status feedback (loading state, success/error toast)
- [ ] Calls `POST /api/screenshot` and displays result metadata
- [ ] No modifications to web.py or any backend files
- [ ] CHANGELOG entry prepended (NOT replacing existing content)

### Integration (Post-merge follow-up, not this sprint)
- Connect mss endpoint to existing Playwright screenshot flow
- Add dual-capture comparison function using Claude vision
- Update `!screenshot` Discord command to optionally include display capture

## Dependency Order
Root and Bloom are **independent** — dispatched simultaneously.
Root's endpoint works standalone (testable with curl).
Bloom's panel calls the endpoint (works once Root's branch is merged).

## web.py Ownership (CRITICAL — shared territory rule)
- **Root:** Adds `/api/screenshot` POST endpoint ONLY. No page routes, no existing endpoint changes.
- **Bloom:** Does NOT touch web.py at all. Works entirely in `trellis/static/`.

## Risk Notes
- `mss` on headless Linux needs `$DISPLAY` — Greenhouse has a physical display, OK
- Temp dir cleanup: max 50 files, FIFO deletion, prevents disk bloat
