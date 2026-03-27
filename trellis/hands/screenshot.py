"""
trellis.hands.screenshot — Screenshot Capture + Vision Validation Hand

Captures screenshots of the Trellis web UI via async Playwright, then
optionally validates them against expectations using Claude's vision API.

Used by:
    - !screenshot Discord command (on-demand)
    - Heartbeat daily screenshot validation (8:30 AM)

Architecture:
    1. Spin up a temporary Uvicorn server serving the Trellis web app
    2. Use async Playwright to navigate and capture a screenshot
    3. Optionally send the screenshot to Claude vision for validation
    4. Return the image path and validation result
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn
from playwright.async_api import async_playwright

if TYPE_CHECKING:
    import anthropic

logger = logging.getLogger(__name__)

# Default viewport sizes
VIEWPORTS = {
    "kiosk": {"width": 1920, "height": 1080},
    "phone": {"width": 390, "height": 844},
    "tablet": {"width": 768, "height": 1024},
}

# Vision model for validation
VISION_MODEL = "claude-sonnet-4-20250514"

# Phase-to-circadian JS snippet: locks the circadian system to a specific phase
PHASE_LOCK_JS = """
(phase) => {
    if (window.TrellisCircadian && window.TrellisCircadian.lockToPhase) {
        window.TrellisCircadian.lockToPhase(phase);
    }
}
"""


@dataclass
class ValidationResult:
    """Result of a vision-based screenshot validation."""

    passed: bool
    summary: str
    details: str
    cost_usd: float


async def _start_temp_server(config: dict, port: int = 8421) -> uvicorn.Server:
    """Start a temporary Uvicorn server for screenshot capture.

    Returns the Server instance so the caller can shut it down.
    """
    from trellis.core.agent_state import AgentState
    from trellis.core.queue import ApprovalQueue
    from trellis.senses.web import create_app

    app = create_app(
        agent_state=AgentState(),
        queue=ApprovalQueue(vault_path=config["vault_path"]),
        config=config,
    )

    uvicorn_config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="error",
    )
    server = uvicorn.Server(uvicorn_config)

    # Start the server in a background task
    serve_task = asyncio.create_task(server.serve())
    # Give the server a moment to bind
    await asyncio.sleep(1.0)

    # Stash the task on the server so we can cancel it later
    server._serve_task = serve_task  # type: ignore[attr-defined]
    return server


async def _stop_temp_server(server: uvicorn.Server) -> None:
    """Shut down a temporary Uvicorn server."""
    server.should_exit = True
    serve_task = getattr(server, "_serve_task", None)
    if serve_task is not None:
        try:
            await asyncio.wait_for(serve_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            serve_task.cancel()


async def capture_screenshot(
    config: dict,
    page_path: str = "/",
    phase: str | None = None,
    viewport: str = "kiosk",
    port: int = 8421,
) -> Path:
    """Capture a screenshot of a Trellis web page.

    Args:
        config: Trellis config dict (must include vault_path).
        page_path: URL path to capture (e.g. "/", "/canvas").
        phase: Circadian phase to lock to (dawn/day/afternoon/evening/night).
        viewport: Viewport preset name (kiosk/phone/tablet).
        port: Port for the temporary server.

    Returns:
        Path to the saved screenshot PNG.
    """
    vault_path = Path(config["vault_path"])
    vp = VIEWPORTS.get(viewport, VIEWPORTS["kiosk"])

    # Ensure screenshots directory exists
    screenshots_dir = vault_path / "_ivy" / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    # Generate filename
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    phase_label = phase or "auto"
    filename = f"screenshot-{phase_label}-{viewport}-{timestamp}.png"
    output_path = screenshots_dir / filename

    server = await _start_temp_server(config, port=port)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(
                viewport={"width": vp["width"], "height": vp["height"]},
            )

            url = f"http://127.0.0.1:{port}{page_path}"
            await page.goto(url, wait_until="networkidle")

            # Lock to phase if requested
            if phase:
                await page.evaluate(PHASE_LOCK_JS, phase)
                # Wait for circadian transition to apply
                await asyncio.sleep(0.5)

            await page.screenshot(path=str(output_path), full_page=False)
            await browser.close()
    finally:
        await _stop_temp_server(server)

    logger.info("Screenshot captured: %s", output_path)
    return output_path


async def capture_start_screen(
    config: dict,
    phase: str = "day",
    viewport: str = "kiosk",
    port: int = 8421,
) -> Path:
    """Convenience: capture the Start screen at a specific phase.

    Args:
        config: Trellis config dict.
        phase: Circadian phase (dawn/day/afternoon/evening/night).
        viewport: Viewport preset name.
        port: Port for the temporary server.

    Returns:
        Path to the saved screenshot PNG.
    """
    return await capture_screenshot(
        config=config,
        page_path="/",
        phase=phase,
        viewport=viewport,
        port=port,
    )


def _sync_vision_call(
    client: anthropic.Anthropic,
    image_path: Path,
    expectations: str,
) -> dict:
    """Make a synchronous vision API call (run in executor from async code).

    Returns a dict with keys: passed, summary, details, cost_usd.
    """
    image_data = base64.standard_b64encode(image_path.read_bytes()).decode("utf-8")

    prompt = (
        "You are a UI validation assistant. Examine this screenshot and evaluate "
        "whether it meets the following expectations:\n\n"
        f"**Expectations:** {expectations}\n\n"
        "Respond with ONLY a JSON object (no markdown fences, no extra text):\n"
        '{"passed": true/false, "summary": "one-line summary", '
        '"details": "detailed observations"}'
    )

    response = client.messages.create(
        model=VISION_MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_data,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )

    # Calculate cost
    usage = response.usage
    input_tokens = usage.input_tokens
    output_tokens = usage.output_tokens
    # Sonnet pricing: $3/M input, $15/M output
    cost = (input_tokens / 1_000_000 * 3.0) + (output_tokens / 1_000_000 * 15.0)

    # Parse response
    text = response.content[0].text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3].strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        result = {
            "passed": False,
            "summary": "Failed to parse vision response",
            "details": text,
        }

    result["cost_usd"] = cost
    return result


async def validate_screenshot(
    image_path: Path,
    expectations: str,
    anthropic_client: anthropic.Anthropic,
) -> ValidationResult:
    """Validate a screenshot against natural-language expectations using Claude vision.

    Args:
        image_path: Path to the PNG screenshot.
        expectations: Natural-language description of what the screenshot should show.
        anthropic_client: Anthropic SDK client (sync — will be run in executor).

    Returns:
        ValidationResult with pass/fail, summary, details, and API cost.
    """
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, _sync_vision_call, anthropic_client, image_path, expectations
    )

    return ValidationResult(
        passed=result.get("passed", False),
        summary=result.get("summary", ""),
        details=result.get("details", ""),
        cost_usd=result.get("cost_usd", 0.0),
    )


async def capture_and_validate(
    config: dict,
    phase: str,
    expectations: str,
    anthropic_client: anthropic.Anthropic,
    viewport: str = "kiosk",
    port: int = 8421,
) -> tuple[Path, ValidationResult]:
    """Capture a Start screen screenshot and validate it with vision.

    Convenience function combining capture_start_screen + validate_screenshot.

    Args:
        config: Trellis config dict.
        phase: Circadian phase to capture.
        expectations: Natural-language validation expectations.
        anthropic_client: Anthropic SDK client.
        viewport: Viewport preset.
        port: Port for temporary server.

    Returns:
        Tuple of (screenshot_path, ValidationResult).
    """
    screenshot_path = await capture_start_screen(
        config=config,
        phase=phase,
        viewport=viewport,
        port=port,
    )

    validation = await validate_screenshot(
        image_path=screenshot_path,
        expectations=expectations,
        anthropic_client=anthropic_client,
    )

    return screenshot_path, validation
