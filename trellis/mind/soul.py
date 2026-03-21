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

    with open(soul_path, encoding="utf-8") as f:
        soul = f.read()

    logger.info(f"Loaded soul for '{agent_name}' ({len(soul)} chars)")
    return soul


def load_soul_local(agent_name: str = "ivy", agents_dir: str = "agents") -> str:
    """Load a condensed version of SOUL.md for local models.

    Smaller models hallucinate when given the full SOUL.md — they treat
    role descriptions and company context as creative writing prompts and
    fabricate fictional projects, data, and status updates. This function
    extracts only Identity, Personality, and Constraints, then adds an
    explicit grounding rule.
    """
    soul_path = Path(agents_dir) / agent_name / "SOUL.md"
    if not soul_path.exists():
        logger.error(f"SOUL.md not found at {soul_path}")
        return ""

    with open(soul_path, encoding="utf-8") as f:
        full_soul = f.read()

    # Extract sections by heading
    sections = _extract_sections(full_soul)

    # Keep only the sections a small model can handle without hallucinating
    keep = ["Identity", "Personality", "Constraints"]
    parts = []
    for heading in keep:
        if heading in sections:
            parts.append(f"## {heading}\n\n{sections[heading]}")

    condensed = "# Ivy — Agent Soul\n\n" + "\n\n".join(parts)

    # Grounding rule — the critical addition for local models
    condensed += (
        "\n\n## IMPORTANT\n\n"
        "Only reference real information from the conversation. "
        "Never invent projects, data, metrics, collaborations, or status updates. "
        "If you don't know something, say so. Keep responses concise and direct."
    )

    logger.info(f"Loaded condensed soul for '{agent_name}' ({len(condensed)} chars)")
    return condensed


def _extract_sections(markdown: str) -> dict[str, str]:
    """Parse a Markdown document into {heading: content} by ## headings."""
    sections: dict[str, str] = {}
    current_heading = None
    current_lines: list[str] = []

    for line in markdown.splitlines():
        if line.startswith("## "):
            # Save previous section
            if current_heading is not None:
                sections[current_heading] = "\n".join(current_lines).strip()
            current_heading = line[3:].strip()
            current_lines = []
        elif current_heading is not None:
            current_lines.append(line)

    # Save last section
    if current_heading is not None:
        sections[current_heading] = "\n".join(current_lines).strip()

    return sections
