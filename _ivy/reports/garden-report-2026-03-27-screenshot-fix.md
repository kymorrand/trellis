# Garden Report — Screenshot SSE Timeout Fix

**Date:** 2026-03-27
**Agent:** Thorn (PM)
**Machine:** Kyle's dev machine (dispatched to Greenhouse)

## Issue

Both `!screenshot` and `!screenshotnow` Discord commands failed with `TimeoutError` after Sprint 6 shipped them. The commands were dead on arrival — never worked in production.

## Root Cause

Playwright's `wait_until="networkidle"` waits for all network connections to settle (500ms with no activity). Every Trellis page opens a persistent SSE connection to `/api/agent/state/stream` on load. This connection never closes — it's the live agent state feed. So `networkidle` waited forever and timed out.

- `!screenshot` timed out at 30s (temp server on :8421)
- `!screenshotnow` timed out at 15s (live server on :8420)

## Fix

Root changed `wait_until="networkidle"` to `wait_until="domcontentloaded"` in both `capture_screenshot()` and `capture_screenshot_live()`, plus added a 1.5s settle sleep for GSAP animations to complete before capture.

## Review

- **Code fix: Clean.** Two-line change per function — minimal, targeted.
- **Tests: 2 new tests** explicitly assert `domcontentloaded` strategy. All 480 tests pass.
- **Lint: Clean.**
- **Scope: Within boundaries** — Root only touched `trellis/hands/screenshot.py` and `tests/test_screenshot_hand.py`.

### Issue Found: CHANGELOG Nuked

Root **deleted the entire CHANGELOG history** (Sprints 1-5, all entries) and replaced it with just the fix entry. This was caught in review and manually repaired before merge. All previous entries restored.

## Verification

- 480 tests pass
- Lint clean
- Imports OK
- CHANGELOG restored with fix entry prepended

## Next Steps

- Restart Ivy's service on Greenhouse to load the fix
- Test `!screenshotnow` and `!screenshot day` in Discord
- Verify single instance after restart

## Rules Added This Session

1. **Don't use `wait_until="networkidle"` with Playwright on Trellis pages** — every page opens an SSE connection that never closes. Use `domcontentloaded` + settle sleep instead.
2. **Don't nuke CHANGELOG history when adding entries** — prepend new entries at the top, don't replace the file.
