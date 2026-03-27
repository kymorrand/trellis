# Sprint 5 — Screenshot Regression Testing for Start Screen

**Date:** 2026-03-27
**Scope:** Root (backend/tooling) + Bloom (frontend controls) — parallel dispatch
**Status:** In Progress

## Overview

Build a screenshot regression testing system that catches visual regressions in the
Start screen across all circadian phases and viewport sizes. Prevents the work-loss
cycle where feature iterations overwrite visual improvements (e.g., circadian text
fix overwrote kiosk display scaling).

## Problem Statement

We keep losing visual changes between feature iterations. Manual checking of each
circadian phase after changes is error-prone and time-consuming. We need automated
visual validation before commits.

---

## Root — Screenshot Testing Infrastructure

### 1. Dependencies (`pyproject.toml`)

Add to `[project.optional-dependencies] dev`:
- `playwright>=1.40.0` — headless browser for screenshot capture
- `Pillow>=10.0.0` — image comparison and diff generation

After install: `playwright install chromium` to get the browser binary.

### 2. `scripts/screenshot_test.py` (NEW) — CLI Validation Tool

Single-command tool that validates all circadian phases render correctly.

**Usage:**
```bash
# Capture baselines (first run or after intentional changes)
python scripts/screenshot_test.py --baseline

# Validate against baselines (pre-commit check)
python scripts/screenshot_test.py

# Test a single phase
python scripts/screenshot_test.py --phase evening

# Test a single viewport
python scripts/screenshot_test.py --viewport kiosk
```

**Behavior:**
1. Start the Trellis web server (import `create_app`, run with uvicorn programmatically)
2. For each phase × viewport combination:
   a. Navigate to `http://localhost:{port}/`
   b. Execute `TrellisCircadian.lockToPhase('{phase}')` via page.evaluate()
   c. Wait for CSS transitions to settle (~500ms)
   d. If kiosk viewport, also add `?kiosk=true` query param
   e. Capture full-page screenshot
3. If `--baseline`: save to `tests/screenshots/baseline/`
4. If validation: compare against baselines, report failures

**Phases to test:** dawn, day, afternoon, evening, night (5 phases from circadian.js)
**Viewports:** mobile (375×812), desktop (1440×900), kiosk (2560×1600)
**Total:** 15 screenshots per run

**File naming:** `{phase}-{viewport}.png` (e.g., `evening-kiosk.png`)

**Exit codes:**
- 0: all phases match baselines (within threshold)
- 1: visual diff detected (regression)
- 2: no baselines found (need `--baseline` first)

### 3. `trellis/testing/__init__.py` + `trellis/testing/screenshot.py` (NEW)

Reusable screenshot comparison module:

```python
class ScreenshotComparer:
    """Compare screenshots against baselines with configurable tolerance."""

    def __init__(self, baseline_dir: Path, output_dir: Path, threshold: float = 0.01):
        """threshold: max allowed pixel diff ratio (0.01 = 1% pixels can differ)"""

    def compare(self, name: str, current: Path) -> CompareResult:
        """Compare current screenshot against baseline. Returns diff details."""

    def save_baseline(self, name: str, image: Path) -> Path:
        """Save an image as the new baseline."""

    def generate_diff_image(self, baseline: Path, current: Path) -> Path:
        """Generate a visual diff image highlighting changed pixels."""
```

**CompareResult dataclass:**
```python
@dataclass
class CompareResult:
    name: str
    passed: bool
    diff_ratio: float      # 0.0 = identical, 1.0 = completely different
    diff_pixels: int       # absolute count of differing pixels
    total_pixels: int
    diff_image: Path | None  # path to visual diff if failed
    baseline: Path
    current: Path
```

### 4. `tests/test_screenshot_system.py` (NEW)

Tests for the comparison module itself (NOT the visual tests — those are separate):
- Test CompareResult with identical images → passes
- Test CompareResult with different images → fails with correct diff ratio
- Test threshold: small diff below threshold passes, above threshold fails
- Test diff image generation creates a valid PNG
- Test baseline save/load cycle
- Test missing baseline returns appropriate error

### 5. Screenshot baseline storage

```
tests/screenshots/
├── baseline/           # Committed reference images
│   ├── dawn-mobile.png
│   ├── dawn-desktop.png
│   ├── dawn-kiosk.png
│   ├── day-mobile.png
│   ├── ...
│   └── night-kiosk.png
├── current/            # Latest run (gitignored)
└── diffs/              # Visual diffs (gitignored)
```

Add to `.gitignore`:
```
tests/screenshots/current/
tests/screenshots/diffs/
```

### Root Files
| File | Action |
|------|--------|
| `pyproject.toml` | MODIFY — add playwright + Pillow to dev deps |
| `scripts/screenshot_test.py` | CREATE |
| `trellis/testing/__init__.py` | CREATE |
| `trellis/testing/screenshot.py` | CREATE |
| `tests/test_screenshot_system.py` | CREATE |
| `.gitignore` | MODIFY — add screenshot working dirs |
| `CHANGELOG.md` | MODIFY — add entry |

### Root Does NOT Touch
- `trellis/static/` — Bloom's scope
- `trellis/senses/web.py` — no changes needed (start page already served)
- `agents/ivy/SOUL.md` — Kyle approval required

---

## Bloom — Phase Lock Developer Controls

### 1. `trellis/static/start.html` — Dev Controls Overlay

Add a collapsible developer panel (bottom-right corner, hidden by default) with:

- **Phase lock buttons:** Dawn, Day, Afternoon, Evening, Night, Auto (resets to real-time)
- Toggle with keyboard shortcut: `Shift+D` to show/hide
- Only visible when `?dev=true` query param is present
- Current active phase highlighted
- Compact, doesn't interfere with page layout
- Uses existing circadian color vars for styling

**Implementation:**
- Call `TrellisCircadian.lockToPhase(phase)` on button click
- "Auto" button calls `TrellisCircadian.init()` to restore real-time
- Panel remembers collapsed state in sessionStorage
- Add `?dev=true` param check in init() to auto-show

### 2. `trellis/static/js/circadian.js` — Background gradient update for lockToPhase

Currently `lockToPhase()` sets color vars and typography but does NOT update the
background gradient vars (`--bg-top`, `--bg-bottom`). This is needed both for
manual testing AND for screenshot accuracy.

Add background gradient values to `lockToPhase()` using the same `bgValues` mapping
from `generateBgKeyframes()`.

### Bloom Files
| File | Action |
|------|--------|
| `trellis/static/start.html` | MODIFY — add dev controls overlay |
| `trellis/static/js/circadian.js` | MODIFY — add bg gradient to lockToPhase |

### Bloom Does NOT Touch
- `trellis/core/`, `trellis/mind/`, `trellis/hands/`, `trellis/memory/`, `trellis/security/`
- `trellis/senses/discord_channel.py`
- API endpoints in web.py
- `scripts/` — Root's scope for CLI tooling

---

## Dependency Order

**Root and Bloom work in parallel.** No dependencies between their changes.

Root's screenshot tool uses `page.evaluate('TrellisCircadian.lockToPhase(...)')` which
already exists. Bloom's enhancement to lockToPhase (adding background gradients) makes
screenshots more accurate but isn't blocking — Root can capture baselines after Bloom's
change lands.

## Acceptance Criteria

1. `python scripts/screenshot_test.py --baseline` captures 15 screenshots (5 phases × 3 viewports)
2. `python scripts/screenshot_test.py` validates all phases match baselines → exit 0
3. Modifying CSS and re-running → detects regression → exit 1
4. Visual diff images generated for failures showing exactly what changed
5. Dev controls visible with `?dev=true`, hidden otherwise
6. Phase lock buttons correctly switch circadian phase including background gradient
7. Shift+D toggles dev panel visibility
8. All existing tests still pass
9. Lint clean
10. CHANGELOG updated
