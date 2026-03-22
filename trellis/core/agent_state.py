"""
trellis.core.agent_state — In-Memory Agent State Tracker

Tracks Ivy's granular state (idle/thinking/acting/waiting/reporting)
and notifies SSE subscribers on change.

State is ephemeral — starts as "idle" on process start, no persistence.
"""

import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

VALID_STATES = ("idle", "thinking", "acting", "waiting", "reporting")

# Minimum time a state must hold before transitioning (prevents UI flicker)
MIN_HOLD_MS = 800


class AgentState:
    """In-memory agent state with async subscriber notification for SSE."""

    def __init__(self):
        self._state: str = "idle"
        self._detail: str = ""
        self._changed_at: datetime = datetime.now()
        self._subscribers: list[asyncio.Queue] = []

    @property
    def state(self) -> str:
        return self._state

    @property
    def detail(self) -> str:
        return self._detail

    @property
    def changed_at(self) -> datetime:
        return self._changed_at

    def set(self, state: str, detail: str = "") -> None:
        """Update state and notify all SSE subscribers."""
        if state not in VALID_STATES:
            logger.warning(f"Invalid agent state: {state!r}")
            return

        if state == self._state and detail == self._detail:
            return  # No change

        self._state = state
        self._detail = detail
        self._changed_at = datetime.now()

        state_dict = self.to_dict()
        logger.debug(f"Agent state → {state}" + (f" ({detail})" if detail else ""))

        # Notify all SSE subscribers
        for queue in self._subscribers:
            try:
                queue.put_nowait(state_dict)
            except asyncio.QueueFull:
                pass  # Drop if subscriber is backed up

    def subscribe(self) -> asyncio.Queue:
        """Register an SSE subscriber. Returns a queue that receives state dicts."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=32)
        self._subscribers.append(queue)
        logger.debug(f"SSE subscriber added (total: {len(self._subscribers)})")
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Remove an SSE subscriber."""
        try:
            self._subscribers.remove(queue)
            logger.debug(f"SSE subscriber removed (total: {len(self._subscribers)})")
        except ValueError:
            pass

    def to_dict(self) -> dict:
        return {
            "state": self._state,
            "detail": self._detail,
            "changed_at": self._changed_at.isoformat(),
        }
