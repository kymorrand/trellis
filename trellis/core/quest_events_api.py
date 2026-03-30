"""
trellis.core.quest_events_api — SSE endpoint for quest system events.

Streams real-time quest system state changes to the frontend dashboard.

Endpoint:
    GET /api/quest-events  — SSE stream of quest events from EventBus

Requires Authorization: Bearer {TRELLIS_API_KEY} header.

Event format (SSE):
    data: {"type":"tick.started","quest_id":"...","timestamp":"..."}\n\n

Includes:
    - Initial state snapshot on connect (list of active quests with status)
    - Keepalive pings every 30 seconds
    - Graceful disconnect handling (unsubscribe from EventBus)
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from trellis.core.events import EventBus, QuestEvent
from trellis.core.quest import list_quests
from trellis.core.quest_api import verify_api_key

logger = logging.getLogger(__name__)

# Keepalive interval in seconds
_KEEPALIVE_INTERVAL = 30.0


def _event_to_sse(event: QuestEvent) -> str:
    """Format a QuestEvent as an SSE data line."""
    payload: dict[str, object] = {
        "type": event.event_type.value,
        "quest_id": event.quest_id,
        "timestamp": event.timestamp.isoformat(),
    }
    if event.phase is not None:
        payload["phase"] = event.phase.value
    if event.data:
        payload["data"] = event.data
    return f"data: {json.dumps(payload)}\n\n"


def _snapshot_to_sse(quests_dir: Path) -> str:
    """Build an SSE event containing the current quest state snapshot."""
    quests = list_quests(quests_dir)
    snapshot = {
        "type": "snapshot",
        "timestamp": datetime.now().isoformat(),
        "quests": [
            {
                "id": q.id,
                "title": q.title,
                "status": q.status,
                "priority": q.priority,
                "steps_completed": q.steps_completed,
                "total_steps": q.total_steps,
            }
            for q in quests
        ],
    }
    return f"data: {json.dumps(snapshot)}\n\n"


def create_quest_events_router(
    quests_dir: Path,
    event_bus: EventBus,
) -> APIRouter:
    """Create an APIRouter with the quest events SSE endpoint.

    Args:
        quests_dir: Path to the quests directory (for initial snapshot).
        event_bus: EventBus to subscribe to for quest events.

    Returns:
        FastAPI APIRouter with ``GET /api/quest-events``.
    """
    router = APIRouter(tags=["quest-events"])

    @router.get("/api/quest-events")
    async def quest_events_stream(
        _: None = Depends(verify_api_key),
    ) -> StreamingResponse:
        """SSE stream of quest system events."""

        async def event_generator() -> AsyncIterator[str]:
            queue = event_bus.subscribe()
            try:
                # Send initial state snapshot
                yield _snapshot_to_sse(quests_dir)

                while True:
                    try:
                        event: QuestEvent = await asyncio.wait_for(
                            queue.get(),
                            timeout=_KEEPALIVE_INTERVAL,
                        )
                        yield _event_to_sse(event)
                    except asyncio.TimeoutError:
                        # Send keepalive ping
                        ping = {
                            "type": "ping",
                            "timestamp": datetime.now().isoformat(),
                        }
                        yield f"data: {json.dumps(ping)}\n\n"
            except asyncio.CancelledError:
                pass
            finally:
                event_bus.unsubscribe(queue)
                logger.debug("Quest events SSE client disconnected")

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router
