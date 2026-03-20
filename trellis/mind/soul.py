"""
trellis.mind.soul — SOUL.md Loader & Personality Engine

Loads and parses the agent's SOUL.md file — the personality,
constraints, and behavioral rules that define who Ivy is.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_soul(agent_name: str = "ivy", agents_dir: str = "agents") -> str:
    """Load SOUL.md for the specified agent."""
    soul_path = Path(agents_dir) / agent_name / "SOUL.md"
    if not soul_path.exists():
        logger.error(f"SOUL.md not found at {soul_path}")
        return ""

    with open(soul_path) as f:
        soul = f.read()

    logger.info(f"Loaded soul for '{agent_name}' ({len(soul)} chars)")
    return soul
