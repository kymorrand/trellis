"""
trellis.core.loop — The Main Event Loop

This is the game loop. Everything starts here.

Architecture:
    LISTEN  → Check all input channels for new events
    THINK   → Assemble context and call the model
    ACT     → Execute tool calls based on model response
    PERSIST → Save state, update memory, log the interaction

The loop runs continuously. When no events are pending, it idles.
The heartbeat scheduler (heartbeat.py) injects proactive events on a cron schedule.
"""

import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


async def run():
    """Main agent loop. This is Ivy's heartbeat."""
    logger.info("🌱 Trellis starting up...")
    logger.info(f"   Time: {datetime.now().isoformat()}")
    logger.info("   Agent: Ivy")
    logger.info("   Mode: Initializing...")

    # TODO: Phase 1 implementation
    # 1. Load configuration from .env
    # 2. Load SOUL.md and parse agent personality
    # 3. Initialize input channels (Discord, file watcher, CLI)
    # 4. Initialize output tools (vault, Linear, calendar)
    # 5. Initialize model router (Ollama local + Anthropic cloud)
    # 6. Start heartbeat scheduler
    # 7. Enter main loop

    logger.info("🌱 Trellis loop placeholder — ready for implementation")
    logger.info("   Next step: implement config loading and channel initialization")

    # Placeholder loop — keeps the process alive
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("🌱 Trellis shutting down gracefully...")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(name)s | %(message)s")
    asyncio.run(run())
