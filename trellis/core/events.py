"""
trellis.core.events — Event types and async event bus for quest notifications.

Provides:
    TickPhase       — Enum of the six tick execution phases
    EventType       — Enum of all emittable event types
    QuestEvent      — Dataclass representing a single event
    EventBus        — Async event bus with subscribe/publish pattern
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class TickPhase(str, Enum):
    """The six phases of a quest tick execution."""

    AWAKE = "awake"
    INPUT = "input"
    PLAN = "plan"
    EXECUTE = "execute"
    PERSIST = "persist"
    NOTIFY = "notify"


class EventType(str, Enum):
    """All event types emitted by the tick scheduler."""

    # Scheduler lifecycle
    SCHEDULER_STARTED = "scheduler.started"
    SCHEDULER_STOPPED = "scheduler.stopped"

    # Quest tick lifecycle
    TICK_STARTED = "tick.started"
    TICK_PHASE_ENTERED = "tick.phase_entered"
    TICK_PHASE_COMPLETED = "tick.phase_completed"
    TICK_COMPLETED = "tick.completed"
    TICK_FAILED = "tick.failed"
    TICK_TIMED_OUT = "tick.timed_out"
    TICK_SKIPPED = "tick.skipped"

    # Quest state changes
    QUEST_STATUS_CHANGED = "quest.status_changed"
    QUEST_STEP_COMPLETED = "quest.step_completed"
    QUEST_QUESTION_ASKED = "quest.question_asked"

    # Bonus tick
    BONUS_TICK_TRIGGERED = "bonus_tick.triggered"


@dataclass(frozen=True)
class QuestEvent:
    """A single event emitted by the tick scheduler or executor."""

    event_type: EventType
    quest_id: str
    timestamp: datetime = field(default_factory=datetime.now)
    phase: TickPhase | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        phase_str = f" phase={self.phase.value}" if self.phase else ""
        return f"<QuestEvent {self.event_type.value} quest={self.quest_id}{phase_str}>"


class EventBus:
    """Async event bus for quest tick notifications.

    Subscribers receive events via asyncio.Queue instances. The bus supports
    multiple concurrent subscribers, each getting every event.

    Usage:
        bus = EventBus()
        queue = bus.subscribe()
        # ... events are published elsewhere ...
        event = await queue.get()

        # When done:
        bus.unsubscribe(queue)
    """

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[QuestEvent]] = []
        self._lock = asyncio.Lock()

    async def publish(self, event: QuestEvent) -> None:
        """Publish an event to all subscribers."""
        async with self._lock:
            for queue in self._subscribers:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(
                        "Event queue full, dropping event %s for quest %s",
                        event.event_type.value,
                        event.quest_id,
                    )

    def subscribe(self, maxsize: int = 1000) -> asyncio.Queue[QuestEvent]:
        """Create a new subscription queue and return it."""
        queue: asyncio.Queue[QuestEvent] = asyncio.Queue(maxsize=maxsize)
        self._subscribers.append(queue)
        logger.debug("New subscriber added (total: %d)", len(self._subscribers))
        return queue

    def unsubscribe(self, queue: asyncio.Queue[QuestEvent]) -> None:
        """Remove a subscription queue."""
        try:
            self._subscribers.remove(queue)
            logger.debug("Subscriber removed (total: %d)", len(self._subscribers))
        except ValueError:
            logger.warning("Attempted to unsubscribe a queue that was not subscribed")

    @property
    def subscriber_count(self) -> int:
        """Number of active subscribers."""
        return len(self._subscribers)
