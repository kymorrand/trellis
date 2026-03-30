"""
trellis.core.activity_store — Activity event persistence.

Subscribes to EventBus and persists selected event types to a JSONL file
at {vault_path}/_ivy/activity.jsonl. Each line is one JSON object with:
id, type, quest_id, quest_title, summary, timestamp (ISO 8601).

Event types persisted:
    step_completed, question_asked, approval_requested,
    status_changed, tick_completed
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from trellis.core.events import EventBus, EventType, QuestEvent

logger = logging.getLogger(__name__)

# Map EventBus EventType values to activity type strings matching the
# ActivityEvent TypeScript contract in trellis-app/lib/types.ts.
_EVENT_TYPE_MAP: dict[EventType, str] = {
    EventType.QUEST_STEP_COMPLETED: "step_completed",
    EventType.QUEST_QUESTION_ASKED: "question_asked",
    EventType.TICK_COMPLETED: "tick_completed",
    EventType.QUEST_STATUS_CHANGED: "status_changed",
}


def _generate_summary(event: QuestEvent, activity_type: str) -> str:
    """Generate a human-readable summary from an event."""
    data = event.data

    if activity_type == "step_completed":
        step_num = data.get("step_number", "?")
        step_text = data.get("step_text", "")
        if step_text:
            return f"Completed step {step_num}: {step_text}"
        return f"Completed step {step_num}"

    if activity_type == "question_asked":
        question_text = data.get("question_text", "")
        if question_text:
            # Truncate long questions
            if len(question_text) > 80:
                question_text = question_text[:77] + "..."
            return f"New question: {question_text}"
        return "New question asked"

    if activity_type == "approval_requested":
        title = data.get("approval_title", "")
        if title:
            return f"Approval requested: {title}"
        return "Approval requested"

    if activity_type == "status_changed":
        old_status = data.get("old_status", "?")
        new_status = data.get("new_status", "?")
        return f"Status changed: {old_status} -> {new_status}"

    if activity_type == "tick_completed":
        phase_count = data.get("phases_completed", None)
        if phase_count is not None:
            return f"Tick completed ({phase_count} phases)"
        return "Tick completed"

    return f"Event: {activity_type}"


def event_to_activity(event: QuestEvent) -> dict[str, Any] | None:
    """Convert a QuestEvent to an activity record dict, or None if not tracked.

    Returns a dict matching the ActivityEvent TypeScript interface:
        { id, type, quest_id, quest_title, summary, timestamp }
    """
    activity_type = _EVENT_TYPE_MAP.get(event.event_type)
    if activity_type is None:
        # Also check for approval_requested which comes through data
        if event.data.get("approval_requested"):
            activity_type = "approval_requested"
        else:
            return None

    quest_title = event.data.get("quest_title", event.quest_id)
    summary = _generate_summary(event, activity_type)

    return {
        "id": str(uuid.uuid4()),
        "type": activity_type,
        "quest_id": event.quest_id,
        "quest_title": quest_title,
        "summary": summary,
        "timestamp": event.timestamp.isoformat(),
    }


class ActivityStore:
    """Persists activity events to a JSONL file and supports paginated reads.

    Args:
        activity_path: Path to the activity.jsonl file.
        event_bus: EventBus instance to subscribe to.
    """

    def __init__(self, activity_path: Path, event_bus: EventBus | None = None) -> None:
        self._path = activity_path
        self._event_bus = event_bus
        # Ensure parent directory exists
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: dict[str, Any]) -> None:
        """Append a single activity record to the JSONL file."""
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def persist_event(self, event: QuestEvent) -> dict[str, Any] | None:
        """Convert and persist a QuestEvent. Returns the record or None."""
        record = event_to_activity(event)
        if record is not None:
            self.append(record)
            logger.debug("Persisted activity: %s for quest %s", record["type"], record["quest_id"])
        return record

    def read_recent(
        self,
        limit: int = 50,
        before: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Read recent activity events, newest first, with cursor pagination.

        Args:
            limit: Maximum number of events to return (capped at 200).
            before: ISO 8601 timestamp cursor — only return events before this.

        Returns:
            Tuple of (events list, next_cursor or None if no more).
        """
        limit = min(max(limit, 1), 200)

        if not self._path.exists():
            return [], None

        # Read all lines and reverse for newest-first
        lines = self._path.read_text(encoding="utf-8").strip().splitlines()
        lines.reverse()

        results: list[dict[str, Any]] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed activity line: %s", line[:80])
                continue

            ts = record.get("timestamp", "")

            # Apply cursor filter
            if before and ts >= before:
                continue

            results.append(record)
            if len(results) >= limit + 1:
                break

        # Determine next_cursor
        if len(results) > limit:
            results = results[:limit]
            next_cursor = results[-1]["timestamp"]
        else:
            next_cursor = None

        return results, next_cursor

    async def listen(self) -> None:
        """Subscribe to the EventBus and persist events.

        This is a long-running coroutine — run it as an asyncio task.
        """
        if self._event_bus is None:
            raise RuntimeError("Cannot listen without an EventBus")

        queue = self._event_bus.subscribe()
        logger.info("ActivityStore listening for events")
        try:
            while True:
                event = await queue.get()
                try:
                    self.persist_event(event)
                except Exception:
                    logger.exception("Error persisting activity event: %s", event)
        finally:
            self._event_bus.unsubscribe(queue)
            logger.info("ActivityStore stopped listening")
