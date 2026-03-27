# Garden Report — 2026-03-27

## Sprint 5: Screenshot Regression Testing

**Status:** Complete. Merged to main, all 436 tests pass, lint clean.

## What Was Built

### Root — Screenshot Testing Infrastructure
- **`trellis/testing/screenshot.py`** — `ScreenshotComparer` class with pixel-level diff, configurable threshold (default 1%), red-highlight diff image generation
- **`scripts/screenshot_test.py`** — CLI tool: `--baseline` captures 15 reference images (5 phases x 3 viewports), validation mode compares and reports, `--phase`/`--viewport` filtering, self-contained (starts uvicorn in thread)
- **`tests/test_screenshot_system.py`** — 20 unit tests for the comparison module
- **Dependencies added:** `playwright>=1.40.0`, `Pillow>=10.0.0` (dev only)
- **Scope:** Clean. No frontend files touched.

### Bloom — Phase Lock Dev Controls
- **`circadian.js` fix** — `lockToPhase()` now sets `--bg-top` and `--bg-bottom` CSS vars. Previously only set color palette + typography, leaving background stuck on whatever the animation had last rendered. `BG_VALUES` extracted to module scope.
- **Dev panel overlay** — floating bottom-right panel with phase buttons (Dawn/Day/Afternoon/Evening/Night/Auto). Activated by `?dev=true`, toggles with Shift+D, remembers collapsed state in sessionStorage. Styled with semi-transparent backdrop + blur.
- **Scope:** Clean. No backend files touched.

## Review Findings

### Passing
1. Tests written for new code: Yes (20 unit tests for screenshot module)
2. All tests pass: Yes (436/436)
3. Lint clean: Yes
4. Scope boundaries respected: Yes (Root: only backend/tests/scripts, Bloom: only static/)
5. No new dependencies unaccounted for: playwright + Pillow added to pyproject.toml dev deps
6. CHANGELOG updated: Yes (merged entry covers both Root and Bloom work)

### Notes
- **Pillow deprecation warning:** `Image.getdata()` deprecated in favor of `get_flattened_data()`, removal in Pillow 14 (Oct 2027). Non-blocking, future cleanup.
- **Clock text variance:** Root noted dawn-mobile shows ~3% diff on back-to-back runs because the Start page renders live time/date. The 1% threshold catches this. Acceptable — screenshots with phase-locked content will be consistent; only the clock text shifts.
- **Baselines not committed:** By design. Font rendering and GPU differ between machines. Each environment runs `--baseline` to establish its own reference.
- **Merge conflict:** Only in CHANGELOG.md (both agents added entries at top). Resolved cleanly — both entries preserved in chronological order.

## Rules Added This Session

None — clean session. Both agents stayed within scope, wrote tests, updated CHANGELOG, and followed all CLAUDE.md conventions.

**Minor future consideration:** Root's screenshot tool passes `vault_path` as a string to `create_app()`, but some API endpoints call `.is_dir()` on it (Path method). This doesn't break screenshots (Start page doesn't call those endpoints), but if the tool ever captures other pages, it would need `Path(vault_tmp)` instead. Not adding as a rule since it's a contained edge case in test tooling.
