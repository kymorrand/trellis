"""
Entry point for Ivy — Discord bot, web server, and heartbeat scheduler.
Run from the trellis repo root: python scripts/run_discord.py

All four run as concurrent async tasks in a single process,
sharing agent state, approval queue, and heartbeat data.
"""

import asyncio
import logging
import sys
from pathlib import Path

import httpx
import uvicorn

# Ensure repo root is on the path so trellis package is importable
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from trellis.core.agent_state import AgentState  # noqa: E402
from trellis.core.config import load_config  # noqa: E402
from trellis.core.heartbeat import HeartbeatScheduler  # noqa: E402
from trellis.core.queue import ApprovalQueue  # noqa: E402
from trellis.memory.knowledge import KnowledgeManager  # noqa: E402
from trellis.senses.discord_channel import create_bot  # noqa: E402
from trellis.senses.file_watcher import FileWatcher  # noqa: E402
from trellis.senses.web import create_app  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ivy")


async def _index_vault_background(knowledge_manager: KnowledgeManager) -> None:
    """Run vault indexing in the background — don't block bot startup."""
    try:
        from trellis.memory.journal import log_entry

        logger.info("Background vault indexing started")
        stats = await knowledge_manager.index_vault()
        logger.info(
            "Vault indexing complete: %d indexed, %d skipped, %d errors",
            stats["indexed"],
            stats["skipped"],
            stats["errors"],
        )
        log_entry(
            knowledge_manager.vault_path,
            "SYSTEM",
            "Vault indexing complete",
            f"Indexed: {stats['indexed']}, Skipped: {stats['skipped']}, Errors: {stats['errors']}",
        )
    except Exception as e:
        logger.error("Background vault indexing failed: %s", e, exc_info=True)


async def run_all(config: dict):
    """Run Discord bot, web server, heartbeat, and file watcher as concurrent async tasks."""
    # Shared state objects
    agent_state = AgentState()
    approval_queue = ApprovalQueue(vault_path=config["vault_path"])

    # Knowledge manager for hybrid search
    ollama_url = config.get("ollama_url", "http://localhost:11434")
    knowledge_manager = KnowledgeManager(
        vault_path=config["vault_path"],
        ollama_url=ollama_url,
    )

    # Discord bot
    bot = create_bot(config)
    bot.set_agent_state(agent_state)
    bot.set_knowledge_manager(knowledge_manager)
    bot.set_approval_queue(approval_queue)

    # Heartbeat scheduler
    heartbeat = HeartbeatScheduler(
        vault_path=config["vault_path"],
        budget_monthly=config.get("budget_monthly", 100.0),
        discord_post_callback=bot.post_to_discord,
        knowledge_manager=knowledge_manager,
    )
    bot.set_heartbeat(heartbeat)

    # File watcher — monitors _ivy/inbox/ for new files
    file_watcher = FileWatcher(vault_path=config["vault_path"])

    # Web server
    web_app = create_app(
        heartbeat=heartbeat,
        agent_state=agent_state,
        queue=approval_queue,
        config=config,
        knowledge_manager=knowledge_manager,
    )
    uvicorn_config = uvicorn.Config(
        web_app,
        host="0.0.0.0",
        port=8420,
        log_level="warning",  # Reduce uvicorn noise; app logs via Python logging
    )
    web_server = uvicorn.Server(uvicorn_config)

    # Check for startup message file (one-shot messages to send on connect)
    startup_msg_path = repo_root / ".startup_message"
    if startup_msg_path.exists():
        try:
            import json as _json
            msg_data = _json.loads(startup_msg_path.read_text(encoding="utf-8"))
            bot.queue_startup_message(msg_data["channel"], msg_data["message"])
            startup_msg_path.unlink()
            logger.info(f"Queued startup message for #{msg_data['channel']}")
        except Exception as e:
            logger.warning(f"Failed to load startup message: {e}")

    # Start all as concurrent tasks
    async with bot:
        heartbeat_task = asyncio.create_task(heartbeat.start())
        web_task = asyncio.create_task(web_server.serve())
        watcher_task = asyncio.create_task(file_watcher.start())

        # Background vault indexing — non-blocking
        index_task = asyncio.create_task(_index_vault_background(knowledge_manager))

        logger.info("All systems online — Discord + Web (:8420) + Heartbeat + FileWatcher")
        try:
            await bot.start(config["discord_token"])
        finally:
            # Graceful shutdown
            await heartbeat.stop()
            await file_watcher.stop()
            heartbeat_task.cancel()
            watcher_task.cancel()
            index_task.cancel()
            web_server.should_exit = True
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            try:
                await watcher_task
            except asyncio.CancelledError:
                pass
            try:
                await index_task
            except asyncio.CancelledError:
                pass
            await web_task


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

    logger.info("Starting Ivy — Discord + Web + Heartbeat + FileWatcher...")
    asyncio.run(run_all(config))


if __name__ == "__main__":
    main()
