"""
Entry point for Ivy's Discord bot.
Run from the trellis repo root: python scripts/run_discord.py

Starts the Discord bot and heartbeat scheduler as concurrent async tasks.
"""

import asyncio
import logging
import sys
from pathlib import Path

import httpx

# Ensure repo root is on the path so trellis package is importable
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from trellis.core.config import load_config
from trellis.core.heartbeat import HeartbeatScheduler
from trellis.senses.discord_channel import create_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ivy.discord")


async def run_bot_with_heartbeat(config: dict):
    """Run the Discord bot and heartbeat scheduler concurrently."""
    bot = create_bot(config)

    # Create heartbeat with Discord posting callback
    heartbeat = HeartbeatScheduler(
        vault_path=config["vault_path"],
        budget_monthly=config.get("budget_monthly", 100.0),
        discord_post_callback=bot.post_to_discord,
    )
    bot.set_heartbeat(heartbeat)

    # Start both as concurrent tasks
    async with bot:
        heartbeat_task = asyncio.create_task(heartbeat.start())
        try:
            await bot.start(config["discord_token"])
        finally:
            await heartbeat.stop()
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass


def main():
    config = load_config(str(repo_root / ".env"))
    logging.getLogger().setLevel(config.get("log_level", "INFO"))

    if not config.get("discord_token"):
        logger.error("IVY_DISCORD_TOKEN not set in .env — cannot start Discord bot")
        sys.exit(1)

    # Pre-flight checks
    vault_path = config["vault_path"]
    if not vault_path.is_dir():
        vault_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created vault directory: {vault_path}")
    else:
        logger.info(f"Vault: {vault_path}")

    ollama_url = config.get("ollama_url", "http://localhost:11434")
    try:
        resp = httpx.get(f"{ollama_url}/api/tags", timeout=5.0)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        logger.info(f"Ollama: connected ({len(models)} models available)")
    except Exception as e:
        logger.warning(f"Ollama: not reachable at {ollama_url} — local routing will fall back to cloud ({e})")

    logger.info("Starting Ivy Discord bot with heartbeat scheduler...")
    asyncio.run(run_bot_with_heartbeat(config))


if __name__ == "__main__":
    main()
