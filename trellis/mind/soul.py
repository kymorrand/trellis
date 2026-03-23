"""
trellis.mind.soul — SOUL.md & kyle.md Loader & Personality Engine

Loads and parses the agent's SOUL.md file — the personality,
constraints, and behavioral rules that define who Ivy is.

Also loads kyle.md — the professional context model for working
with Kyle. Located at {vault_path}/_ivy/kyle.md, loaded explicitly
at startup (not via vault search, since _ivy/ is excluded from
search by design).
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


def load_kyle(vault_path: Path | str) -> str:
    """Load kyle.md — Kyle's professional context model.

    Located at {vault_path}/_ivy/kyle.md. This file lives in _ivy/
    (excluded from vault search by design) and is loaded explicitly
    at startup to be included in the system prompt.

    Args:
        vault_path: Path to the Obsidian vault root.

    Returns:
        Full contents of kyle.md, or empty string if not found.
    """
    kyle_path = Path(vault_path) / "_ivy" / "kyle.md"
    if not kyle_path.exists():
        logger.warning("kyle.md not found at %s", kyle_path)
        return ""

    try:
        content = kyle_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error("Failed to read kyle.md: %s", exc)
        return ""

    logger.info("Loaded kyle.md (%d chars)", len(content))
    return content


def load_kyle_local(vault_path: Path | str) -> str:
    """Load a condensed version of kyle.md for local models.

    Extracts only the sections a small model needs to work effectively
    with Kyle without hallucinating on the full context:
    - Energy Architecture
    - Weekly Operating Framework
    - Communication Preferences
    - What Ivy Should Know About the Relationship (contains Good/Bad/Great)

    Adds the same grounding rule as load_soul_local().

    Args:
        vault_path: Path to the Obsidian vault root.

    Returns:
        Condensed kyle.md content, or empty string if not found.
    """
    kyle_path = Path(vault_path) / "_ivy" / "kyle.md"
    if not kyle_path.exists():
        logger.warning("kyle.md not found at %s", kyle_path)
        return ""

    try:
        full_content = kyle_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error("Failed to read kyle.md: %s", exc)
        return ""

    sections = _extract_sections(full_content)

    # Sections that give local models enough context without overload.
    # Headings in kyle.md are numbered ("4. Energy Architecture") so we
    # match by substring to be resilient to renumbering.
    keep_substrings = [
        "Energy Architecture",
        "Weekly Operating Framework",
        "Communication Preferences",
        "What Ivy Should Know About the Relationship",
    ]

    parts = []
    for heading, body in sections.items():
        if any(sub in heading for sub in keep_substrings):
            parts.append(f"## {heading}\n\n{body}")

    if not parts:
        logger.warning("kyle.md found but no matching sections extracted")
        return ""

    condensed = "# Kyle — Working Context\n\n" + "\n\n".join(parts)

    # Same grounding rule as load_soul_local
    condensed += (
        "\n\n## IMPORTANT\n\n"
        "Only reference real information from the conversation. "
        "Never invent projects, data, metrics, collaborations, or status updates. "
        "If you don't know something, say so. Keep responses concise and direct."
    )

    logger.info("Loaded condensed kyle.md (%d chars)", len(condensed))
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
