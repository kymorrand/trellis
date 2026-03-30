"""
trellis.core.quest — Quest File Schema & Loader

Quests live at {vault_path}/_ivy/quests/{quest-id}.md — markdown files
with YAML frontmatter following the Obsidian vault convention.

Provides:
    Quest         — Dataclass representing parsed quest state
    load_quest()  — Parse a quest markdown file into a Quest
    save_quest()  — Serialize a Quest back to markdown
    list_quests() — List all non-archived quests in a directory
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ─── Default values ──────────────────────────────────────────

_DEFAULT_STATUS = "draft"
_DEFAULT_TYPE = "research"
_DEFAULT_PRIORITY = "standard"
_DEFAULT_ROLE = "_default"
_DEFAULT_TICK_INTERVAL = "5m"
_DEFAULT_TICK_WINDOW = "8am-11pm"

_VALID_STATUSES = {"draft", "active", "waiting", "paused", "complete", "abandoned"}
_VALID_TYPES = {"research", "writing", "review", "side-quest"}
_VALID_PRIORITIES = {"urgent", "high", "standard", "low"}

# Sections we parse from the markdown body (case-insensitive match)
_KNOWN_SECTIONS = {
    "goal",
    "success criteria",
    "steps",
    "questions",
    "artifacts",
    "log",
    "blockers",
}


# ─── Step parsing ────────────────────────────────────────────

@dataclass
class QuestStep:
    """A single step in a quest checklist."""

    text: str
    done: bool = False
    blocked_by: str | None = None


def _parse_steps(section_text: str) -> list[QuestStep]:
    """Parse checklist items from the Steps section.

    Supports:
        - [ ] Step text
        - [x] Completed step
        - [ ] Step text <!-- blocked_by: step-id -->
    """
    steps: list[QuestStep] = []
    for line in section_text.splitlines():
        line = line.strip()
        # Match checkbox lines: - [ ] or - [x]
        m = re.match(r"^-\s+\[([ xX])\]\s+(.+)$", line)
        if not m:
            continue
        done = m.group(1).lower() == "x"
        text = m.group(2).strip()

        # Check for blocked_by metadata in HTML comment
        blocked_by = None
        bm = re.search(r"<!--\s*blocked_by:\s*(\S+)\s*-->", text)
        if bm:
            blocked_by = bm.group(1)
            text = text[: bm.start()].strip()

        steps.append(QuestStep(text=text, done=done, blocked_by=blocked_by))
    return steps


def _serialize_steps(steps: list[QuestStep]) -> str:
    """Serialize steps back to markdown checklist format."""
    lines = []
    for step in steps:
        check = "x" if step.done else " "
        text = step.text
        if step.blocked_by:
            text += f" <!-- blocked_by: {step.blocked_by} -->"
        lines.append(f"- [{check}] {text}")
    return "\n".join(lines)


# ─── Quest dataclass ─────────────────────────────────────────

@dataclass
class Quest:
    """Parsed quest state from a quest markdown file."""

    # Identity
    id: str
    title: str

    # Status
    status: str = _DEFAULT_STATUS
    type: str = _DEFAULT_TYPE
    priority: str = _DEFAULT_PRIORITY
    role: str = _DEFAULT_ROLE

    # Dates
    created: date | None = None
    updated: date | None = None

    # Tick config
    tick_interval: str = _DEFAULT_TICK_INTERVAL
    tick_window: str = _DEFAULT_TICK_WINDOW

    # Budget
    budget_claude: int = 0
    budget_spent_claude: int = 0

    # Progress
    steps_completed: int = 0
    goal_hash: str = ""
    drift_check_interval: int = 5

    # Extra frontmatter fields (forward compatibility)
    extra: dict[str, Any] = field(default_factory=dict)

    # Parsed body sections
    goal: str = ""
    success_criteria: str = ""
    steps: list[QuestStep] = field(default_factory=list)
    questions: str = ""
    artifacts: str = ""
    log: str = ""
    blockers: str = ""

    # Raw body sections we don't recognize (for round-trip fidelity)
    _extra_sections: dict[str, str] = field(default_factory=dict, repr=False)

    @property
    def total_steps(self) -> int:
        """Total number of steps in the quest."""
        return len(self.steps)

    def compute_goal_hash(self) -> str:
        """Compute SHA256 hash of the Goal section for drift detection."""
        return hashlib.sha256(self.goal.strip().encode("utf-8")).hexdigest()[:12]


# ─── Frontmatter parsing helpers ─────────────────────────────

def _parse_date(value: Any) -> date | None:
    """Parse a date from YAML frontmatter (may be date, datetime, or string)."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            logger.warning("Invalid date format: %s", value)
            return None
    return None


def _parse_int(value: Any, default: int = 0) -> int:
    """Parse an integer from YAML frontmatter, with default."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


# ─── Section extraction ──────────────────────────────────────

def _split_frontmatter_and_body(content: str) -> tuple[dict[str, Any], str]:
    """Split a markdown file into YAML frontmatter dict and body string.

    Returns ({}, body) if no valid frontmatter is found.
    """
    content = content.lstrip()
    if not content.startswith("---"):
        return {}, content

    # Find the closing ---
    end = content.find("---", 3)
    if end == -1:
        return {}, content

    yaml_str = content[3:end].strip()
    body = content[end + 3:].strip()

    try:
        fm = yaml.safe_load(yaml_str)
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse YAML frontmatter: %s", exc)
        return {}, content

    if not isinstance(fm, dict):
        return {}, content

    return fm, body


def _extract_body_sections(body: str) -> dict[str, str]:
    """Parse markdown body into {heading_lower: content} by ## headings.

    Heading keys are lowercased for matching. Content preserves original text.
    """
    sections: dict[str, str] = {}
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in body.splitlines():
        if line.startswith("## "):
            if current_heading is not None:
                sections[current_heading] = "\n".join(current_lines).strip()
            current_heading = line[3:].strip().lower()
            current_lines = []
        elif current_heading is not None:
            current_lines.append(line)

    if current_heading is not None:
        sections[current_heading] = "\n".join(current_lines).strip()

    return sections


# ─── Public API ──────────────────────────────────────────────

def load_quest(path: Path) -> Quest:
    """Parse a quest markdown file into a Quest dataclass.

    Args:
        path: Path to the quest .md file.

    Returns:
        Parsed Quest object.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file has no valid id in frontmatter or filename.
    """
    if not path.exists():
        raise FileNotFoundError(f"Quest file not found: {path}")

    content = path.read_text(encoding="utf-8")
    fm, body = _split_frontmatter_and_body(content)

    # ID: from frontmatter, or from filename (without .md)
    quest_id = fm.pop("id", None) or path.stem
    title = fm.pop("title", None) or quest_id.replace("-", " ").title()

    # Known frontmatter fields
    status = fm.pop("status", _DEFAULT_STATUS)
    if status not in _VALID_STATUSES:
        logger.warning("Invalid quest status '%s', defaulting to '%s'", status, _DEFAULT_STATUS)
        status = _DEFAULT_STATUS

    quest_type = fm.pop("type", _DEFAULT_TYPE)
    if quest_type not in _VALID_TYPES:
        logger.warning("Invalid quest type '%s', defaulting to '%s'", quest_type, _DEFAULT_TYPE)
        quest_type = _DEFAULT_TYPE

    priority = fm.pop("priority", _DEFAULT_PRIORITY)
    if priority not in _VALID_PRIORITIES:
        logger.warning("Invalid quest priority '%s', defaulting to '%s'", priority, _DEFAULT_PRIORITY)
        priority = _DEFAULT_PRIORITY

    role = fm.pop("role", _DEFAULT_ROLE)
    created = _parse_date(fm.pop("created", None))
    updated = _parse_date(fm.pop("updated", None))
    tick_interval = fm.pop("tick_interval", _DEFAULT_TICK_INTERVAL)
    tick_window = fm.pop("tick_window", _DEFAULT_TICK_WINDOW)
    budget_claude = _parse_int(fm.pop("budget_claude", None))
    budget_spent_claude = _parse_int(fm.pop("budget_spent_claude", None))
    steps_completed = _parse_int(fm.pop("steps_completed", None))
    goal_hash = str(fm.pop("goal_hash", ""))
    drift_check_interval = _parse_int(fm.pop("drift_check_interval", None), default=5)

    # Remaining frontmatter → extra
    extra = fm

    # Parse body sections
    sections = _extract_body_sections(body)

    goal = sections.pop("goal", "")
    success_criteria = sections.pop("success criteria", "")
    steps_text = sections.pop("steps", "")
    steps = _parse_steps(steps_text) if steps_text else []
    questions = sections.pop("questions", "")
    artifacts = sections.pop("artifacts", "")
    log_text = sections.pop("log", "")
    blockers = sections.pop("blockers", "")

    # Anything left is an extra section (preserve for round-trip)
    extra_sections = sections

    quest = Quest(
        id=quest_id,
        title=title,
        status=status,
        type=quest_type,
        priority=priority,
        role=role,
        created=created,
        updated=updated,
        tick_interval=tick_interval,
        tick_window=tick_window,
        budget_claude=budget_claude,
        budget_spent_claude=budget_spent_claude,
        steps_completed=steps_completed,
        goal_hash=goal_hash,
        drift_check_interval=drift_check_interval,
        extra=extra,
        goal=goal,
        success_criteria=success_criteria,
        steps=steps,
        questions=questions,
        artifacts=artifacts,
        log=log_text,
        blockers=blockers,
        _extra_sections=extra_sections,
    )

    logger.info("Loaded quest '%s' (status=%s, steps=%d)", quest.id, quest.status, quest.total_steps)
    return quest


def save_quest(quest: Quest, path: Path) -> None:
    """Serialize a Quest back to a markdown file with YAML frontmatter.

    Preserves round-trip fidelity: load_quest → save_quest → load_quest
    produces identical Quest state.

    Args:
        quest: The Quest object to serialize.
        path: Path to write the markdown file.
    """
    # Build frontmatter dict
    fm: dict[str, Any] = {
        "id": quest.id,
        "title": quest.title,
        "status": quest.status,
        "type": quest.type,
        "priority": quest.priority,
        "role": quest.role,
    }

    if quest.created:
        fm["created"] = quest.created.isoformat()
    if quest.updated:
        fm["updated"] = quest.updated.isoformat()

    fm["tick_interval"] = quest.tick_interval
    fm["tick_window"] = quest.tick_window
    fm["budget_claude"] = quest.budget_claude
    fm["budget_spent_claude"] = quest.budget_spent_claude
    fm["steps_completed"] = quest.steps_completed
    fm["goal_hash"] = quest.goal_hash
    fm["drift_check_interval"] = quest.drift_check_interval

    # Merge extra frontmatter fields
    fm.update(quest.extra)

    # Build YAML frontmatter
    yaml_str = yaml.dump(fm, default_flow_style=False, sort_keys=False, allow_unicode=True).strip()

    # Build body sections
    parts: list[str] = []

    if quest.goal:
        parts.append(f"## Goal\n\n{quest.goal}")
    if quest.success_criteria:
        parts.append(f"## Success criteria\n\n{quest.success_criteria}")
    if quest.steps:
        parts.append(f"## Steps\n\n{_serialize_steps(quest.steps)}")
    if quest.questions:
        parts.append(f"## Questions\n\n{quest.questions}")
    if quest.artifacts:
        parts.append(f"## Artifacts\n\n{quest.artifacts}")
    if quest.log:
        parts.append(f"## Log\n\n{quest.log}")
    if quest.blockers:
        parts.append(f"## Blockers\n\n{quest.blockers}")

    # Extra sections (for round-trip fidelity)
    for heading, content in quest._extra_sections.items():
        # Restore original casing: title-case the heading
        heading_display = heading.title()
        parts.append(f"## {heading_display}\n\n{content}")

    body = "\n\n".join(parts)

    content = f"---\n{yaml_str}\n---\n\n{body}\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.info("Saved quest '%s' to %s", quest.id, path)


def list_quests(quests_dir: Path) -> list[Quest]:
    """List all non-archived quests in the given directory.

    Skips files in _templates/ and _archive/ subdirectories.
    Returns quests sorted by priority (urgent first), then by updated date.

    Args:
        quests_dir: Path to the quests directory.

    Returns:
        List of parsed Quest objects.
    """
    if not quests_dir.is_dir():
        logger.warning("Quests directory not found: %s", quests_dir)
        return []

    skip_dirs = {"_templates", "_archive"}
    quests: list[Quest] = []

    for md_file in quests_dir.glob("*.md"):
        # Skip files in subdirectories (shouldn't match glob, but be safe)
        if any(part in skip_dirs for part in md_file.relative_to(quests_dir).parts):
            continue

        try:
            quest = load_quest(md_file)
            quests.append(quest)
        except Exception as exc:
            logger.error("Failed to load quest %s: %s", md_file, exc)

    # Sort: priority order, then by updated date (most recent first)
    priority_order = {"urgent": 0, "high": 1, "standard": 2, "low": 3}
    quests.sort(
        key=lambda q: (
            priority_order.get(q.priority, 99),
            -(q.updated or date.min).toordinal(),
        )
    )

    logger.info("Listed %d quests from %s", len(quests), quests_dir)
    return quests
