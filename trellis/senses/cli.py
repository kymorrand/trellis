"""
trellis.senses.cli — Terminal Interface

Direct terminal interaction with Ivy for development and quick commands.
Uses the AgentBrain for full ReAct loop with tool calling.

Usage: python -m trellis.senses.cli
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import anthropic

from trellis.core.agent_state import AgentState
from trellis.core.config import load_config
from trellis.core.loop import AgentBrain, Event
from trellis.memory.journal import log_entry
from trellis.mind.router import ModelRouter
from trellis.mind.soul import load_kyle, load_kyle_local, load_soul, load_soul_local

logger = logging.getLogger(__name__)


async def run_cli(config: dict):
    """Run the interactive CLI session."""
    vault_path = config["vault_path"]
    agent_state = AgentState()

    # Set up model infrastructure
    anthropic_client = anthropic.Anthropic(api_key=config["anthropic_key"])
    router = ModelRouter(
        anthropic_client=anthropic_client,
        ollama_url=config.get("ollama_url", "http://localhost:11434"),
    )

    system_prompt = load_soul()
    local_system_prompt = load_soul_local()

    if not system_prompt:
        print("Error: SOUL.md not found. Run from the trellis repo root.")
        return

    # Append Kyle's context model
    kyle_context = load_kyle(vault_path)
    if kyle_context:
        system_prompt += "\n\n---\n\n" + kyle_context
    kyle_context_local = load_kyle_local(vault_path)
    if kyle_context_local:
        local_system_prompt += "\n\n---\n\n" + kyle_context_local

    brain = AgentBrain(
        anthropic_client=anthropic_client,
        router=router,
        vault_path=vault_path,
        system_prompt=system_prompt,
        local_system_prompt=local_system_prompt,
        agent_state=agent_state,
    )

    history: list[dict] = []
    print("\n\033[32m🌱 Ivy CLI — type a message, 'quit' to exit, '!clear' to reset\033[0m")
    print(f"   Vault: {vault_path}")
    print("   Tools: vault_search, vault_read, vault_save, shell_execute, journal_read")
    print()

    while True:
        try:
            user_input = input("\033[1mKyle>\033[0m ")
        except (EOFError, KeyboardInterrupt):
            print("\n\033[32m🌱 Goodbye!\033[0m")
            break

        stripped = user_input.strip()
        if not stripped:
            continue

        if stripped.lower() in ("quit", "exit", "/quit", "/exit"):
            print("\033[32m🌱 Goodbye!\033[0m")
            break

        if stripped.lower() == "!clear":
            history.clear()
            print("\033[33mConversation cleared.\033[0m\n")
            continue

        # Log input
        log_entry(vault_path, "MESSAGE_IN", "Kyle via CLI", stripped)

        # Process through brain
        event = Event(
            source="cli",
            content=stripped,
            channel_name="cli",
        )

        try:
            result = await brain.process(event, history)
        except Exception as e:
            print(f"\033[31mError: {e}\033[0m\n")
            logger.error(f"CLI error: {e}", exc_info=True)
            continue

        # Display response
        indicator = result.indicator
        cost_str = f" (${result.cost_usd:.4f})" if result.cost_usd > 0 else ""
        print(f"\n\033[36mIvy {indicator}{cost_str}>\033[0m {result.response}\n")

        # Update history
        history.append({"role": "user", "content": stripped})
        history.append({"role": "assistant", "content": result.response})

        # Trim history
        if len(history) > 40:
            history[:] = history[-40:]

        # Log output
        log_entry(
            vault_path,
            "MESSAGE_OUT",
            f"Ivy → CLI via {result.model_used}{cost_str}",
            result.response[:500],
        )


def main():
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    # Find repo root
    repo_root = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(repo_root))

    config = load_config(str(repo_root / ".env"))

    if not config.get("anthropic_key"):
        print("Error: IVY_ANTHROPIC_KEY not set in .env")
        sys.exit(1)

    asyncio.run(run_cli(config))


if __name__ == "__main__":
    main()
