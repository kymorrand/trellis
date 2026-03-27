#!/usr/bin/env python3
"""Screenshot regression testing CLI for Trellis.

Captures screenshots of the Start screen across circadian phases and viewports,
then compares against saved baselines to detect visual regressions.

Usage:
    python scripts/screenshot_test.py --baseline        # Capture reference images
    python scripts/screenshot_test.py                   # Validate against baselines
    python scripts/screenshot_test.py --phase evening   # Single phase
    python scripts/screenshot_test.py --viewport kiosk  # Single viewport
"""

from __future__ import annotations

import argparse
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
from playwright.sync_api import sync_playwright

# Resolve project root relative to this script
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = PROJECT_ROOT / "tests" / "screenshots"
BASELINE_DIR = TESTS_DIR / "baseline"
CURRENT_DIR = TESTS_DIR / "current"
DIFFS_DIR = TESTS_DIR / "diffs"

# Add project root to path so imports work
sys.path.insert(0, str(PROJECT_ROOT))

from trellis.testing.screenshot import ScreenshotComparer  # noqa: E402

PHASES = ["dawn", "day", "afternoon", "evening", "night"]

VIEWPORTS: dict[str, dict[str, int | bool]] = {
    "mobile": {"width": 375, "height": 812, "kiosk": False},
    "desktop": {"width": 1440, "height": 900, "kiosk": False},
    "kiosk": {"width": 2560, "height": 1600, "kiosk": True},
}


def find_free_port() -> int:
    """Find an available port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_web_server(port: int) -> threading.Thread:
    """Start the Trellis web server in a background thread.

    Uses create_app() with minimal config -- no heartbeat, agent state,
    or queue needed for screenshot capture of the static Start page.
    """
    from trellis.senses.web import create_app

    # Use a temp dir for vault_path so the app doesn't crash
    vault_tmp = tempfile.mkdtemp(prefix="trellis-screenshot-vault-")
    app = create_app(config={"vault_path": vault_tmp})

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server to be ready
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:
        print("ERROR: Web server failed to start within 5 seconds", file=sys.stderr)
        sys.exit(2)

    return thread


def capture_screenshots(
    port: int,
    phases: list[str],
    viewports: dict[str, dict[str, int | bool]],
) -> list[Path]:
    """Capture screenshots for each phase x viewport combination.

    Returns list of paths to captured screenshot files.
    """
    CURRENT_DIR.mkdir(parents=True, exist_ok=True)
    captured: list[Path] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()

        for vp_name, vp_config in viewports.items():
            width = int(vp_config["width"])
            height = int(vp_config["height"])
            is_kiosk = bool(vp_config["kiosk"])

            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()

            url = f"http://127.0.0.1:{port}/"
            if is_kiosk:
                url += "?kiosk=true"

            page.goto(url, wait_until="domcontentloaded")
            # Wait for fonts and initial JS to load
            page.wait_for_timeout(1000)

            for phase in phases:
                # Lock circadian phase via JS
                page.evaluate(f"TrellisCircadian.lockToPhase('{phase}')")
                # Wait for CSS transitions and animations to settle
                page.wait_for_timeout(1000)

                name = f"{phase}-{vp_name}"
                screenshot_path = CURRENT_DIR / f"{name}.png"
                page.screenshot(path=str(screenshot_path), full_page=False)
                captured.append(screenshot_path)

            context.close()

        browser.close()

    return captured


def save_baselines(captured: list[Path]) -> None:
    """Copy all captured screenshots to the baseline directory."""
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    for path in captured:
        dest = BASELINE_DIR / path.name
        shutil.copy2(str(path), str(dest))
    print(f"Saved {len(captured)} baseline images to {BASELINE_DIR}")


def validate_screenshots(captured: list[Path]) -> int:
    """Compare captured screenshots against baselines.

    Returns:
        0 if all pass, 1 if any fail, 2 if no baselines found.
    """
    if not BASELINE_DIR.exists() or not any(BASELINE_DIR.glob("*.png")):
        print("No baselines found. Run with --baseline first to capture reference images.")
        return 2

    comparer = ScreenshotComparer(
        baseline_dir=BASELINE_DIR,
        output_dir=TESTS_DIR,
        threshold=0.01,
    )

    print("Screenshot Regression Test")
    print("==========================")

    passed_count = 0
    failed_count = 0
    results: list[str] = []

    for path in captured:
        name = path.stem  # e.g., "dawn-mobile"
        try:
            result = comparer.compare(name, path)
        except FileNotFoundError:
            results.append(f"? {name:<20} (no baseline)")
            failed_count += 1
            continue

        diff_pct = f"{result.diff_ratio * 100:.2f}%"
        if result.passed:
            results.append(f"\u2713 {name:<20} (diff: {diff_pct})")
            passed_count += 1
        else:
            diff_note = ""
            if result.diff_image:
                diff_note = f" -- see {result.diff_image}"
            results.append(f"\u2717 {name:<20} (diff: {diff_pct}){diff_note}")
            failed_count += 1

    for line in results:
        print(line)

    total = passed_count + failed_count
    print(f"\nResults: {passed_count}/{total} passed, {failed_count} failed")

    return 0 if failed_count == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Screenshot regression testing for Trellis",
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Capture new baseline images instead of validating",
    )
    parser.add_argument(
        "--phase",
        choices=PHASES,
        help="Test only a single circadian phase",
    )
    parser.add_argument(
        "--viewport",
        choices=list(VIEWPORTS.keys()),
        help="Test only a single viewport",
    )
    args = parser.parse_args()

    # Filter phases and viewports
    phases = [args.phase] if args.phase else PHASES
    viewports = {args.viewport: VIEWPORTS[args.viewport]} if args.viewport else VIEWPORTS

    # Start web server
    port = find_free_port()
    print(f"Starting web server on port {port}...")
    start_web_server(port)

    # Capture screenshots
    expected = len(phases) * len(viewports)
    print(f"Capturing {expected} screenshots ({len(phases)} phases x {len(viewports)} viewports)...")
    captured = capture_screenshots(port, phases, viewports)
    print(f"Captured {len(captured)} screenshots to {CURRENT_DIR}")

    if args.baseline:
        save_baselines(captured)
        sys.exit(0)
    else:
        exit_code = validate_screenshots(captured)
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
