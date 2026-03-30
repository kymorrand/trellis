"""
trellis.core.questions — Question model, parser, and serializer.

Questions live in the ``## Questions`` section of quest markdown files.
Each question has an ID, text, context, urgency, suggested answers,
status (pending/answered), and an answer field.

Format in markdown::

    ### Q-001 [blocking] [pending]
    Should I focus on B2B or B2C models?

    **Context:** Found strong comparables in both directions...

    **Suggestions:**
    - Both -- compare
    - B2B only
    - B2C only

    **Answer:** (none)

Provides:
    Question          — Dataclass for a single question
    parse_questions() — Parse the Questions section into Question list
    serialize_questions() — Serialize Question list back to markdown
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_VALID_URGENCIES = {"blocking", "important", "nice-to-have"}
_VALID_STATUSES = {"pending", "answered"}


@dataclass
class Question:
    """A single question asked by Ivy during a quest tick."""

    id: str
    text: str
    context: str = ""
    urgency: str = "important"
    suggestions: list[str] = field(default_factory=list)
    status: str = "pending"
    answer: str = ""


def parse_questions(section_text: str) -> list[Question]:
    """Parse the Questions section of a quest markdown file.

    Args:
        section_text: The raw text content of the ``## Questions`` section
            (without the ``## Questions`` heading itself).

    Returns:
        List of parsed Question objects.
    """
    if not section_text or not section_text.strip():
        return []

    questions: list[Question] = []
    # Split into question blocks by ### headings
    blocks = re.split(r"(?=^### )", section_text, flags=re.MULTILINE)

    for block in blocks:
        block = block.strip()
        if not block.startswith("### "):
            continue

        question = _parse_question_block(block)
        if question:
            questions.append(question)

    return questions


def _parse_question_block(block: str) -> Question | None:
    """Parse a single question block starting with ``### Q-xxx [urgency] [status]``."""
    lines = block.splitlines()
    if not lines:
        return None

    # Parse heading: ### Q-001 [blocking] [pending]
    heading = lines[0]
    heading_match = re.match(
        r"^###\s+(Q-\d+)\s*"
        r"(?:\[(\w[\w-]*)\])?\s*"
        r"(?:\[(\w+)\])?\s*$",
        heading,
    )
    if not heading_match:
        logger.warning("Skipping unparseable question heading: %s", heading)
        return None

    question_id = heading_match.group(1)
    tag1 = heading_match.group(2) or ""
    tag2 = heading_match.group(3) or ""

    # Determine urgency and status from tags
    urgency = "important"
    status = "pending"
    for tag in (tag1, tag2):
        if tag in _VALID_URGENCIES:
            urgency = tag
        elif tag in _VALID_STATUSES:
            status = tag

    # Parse remaining content into sections
    body = "\n".join(lines[1:])

    # Extract the question text (everything before the first **bold** field)
    text = ""
    context = ""
    suggestions: list[str] = []
    answer = ""

    # Split by bold field markers
    parts = re.split(r"\n\s*\*\*(\w[\w\s]*):\*\*\s*", body)

    # First part is the question text
    text = parts[0].strip()

    # Process remaining field-value pairs
    i = 1
    while i < len(parts) - 1:
        field_name = parts[i].strip().lower()
        field_value = parts[i + 1].strip()
        i += 2

        if field_name == "context":
            context = field_value
        elif field_name == "suggestions":
            suggestions = _parse_suggestions(field_value)
        elif field_name == "answer":
            if field_value == "(none)" or not field_value:
                answer = ""
            else:
                answer = field_value

    return Question(
        id=question_id,
        text=text,
        context=context,
        urgency=urgency,
        suggestions=suggestions,
        status=status,
        answer=answer,
    )


def _parse_suggestions(text: str) -> list[str]:
    """Parse suggestion list items from markdown."""
    suggestions: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("- "):
            suggestions.append(line[2:].strip())
    return suggestions


def serialize_questions(questions: list[Question]) -> str:
    """Serialize a list of Question objects back to markdown format.

    The output is suitable for the ``## Questions`` section body
    (without the ``## Questions`` heading).

    Args:
        questions: List of Question objects.

    Returns:
        Markdown-formatted string.
    """
    if not questions:
        return ""

    blocks: list[str] = []
    for q in questions:
        block = _serialize_question(q)
        blocks.append(block)

    return "\n\n".join(blocks)


def _serialize_question(q: Question) -> str:
    """Serialize a single Question to its markdown block."""
    parts: list[str] = []

    # Heading
    parts.append(f"### {q.id} [{q.urgency}] [{q.status}]")

    # Question text
    if q.text:
        parts.append(q.text)

    # Context
    if q.context:
        parts.append(f"**Context:** {q.context}")

    # Suggestions
    if q.suggestions:
        suggestion_lines = "\n".join(f"- {s}" for s in q.suggestions)
        parts.append(f"**Suggestions:**\n{suggestion_lines}")

    # Answer
    answer_text = q.answer if q.answer else "(none)"
    parts.append(f"**Answer:** {answer_text}")

    return "\n\n".join(parts)


def next_question_id(questions: list[Question]) -> str:
    """Generate the next sequential question ID.

    Args:
        questions: Existing questions to determine the next ID.

    Returns:
        Next ID string like "Q-004".
    """
    max_num = 0
    for q in questions:
        match = re.match(r"Q-(\d+)", q.id)
        if match:
            num = int(match.group(1))
            if num > max_num:
                max_num = num
    return f"Q-{max_num + 1:03d}"
