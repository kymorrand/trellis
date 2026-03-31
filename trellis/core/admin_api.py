"""
trellis.core.admin_api — Admin REST API Endpoints

Provides admin controls for quest management and system monitoring.

Endpoints:
    PATCH  /api/quests/{quest_id}/status      — Pause/resume/abandon a quest
    PATCH  /api/quests/{quest_id}/tick-config  — Update tick interval/window
    GET    /api/admin/usage                    — Aggregated model usage across quests
    GET    /api/admin/ticks                    — Recent tick events from activity store

All endpoints require Authorization: Bearer {TRELLIS_API_KEY} header.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from trellis.core.activity_store import ActivityStore
from trellis.core.quest import list_quests, load_quest, save_quest

logger = logging.getLogger(__name__)

# ─── Valid values ────────────────────────────────────────────

_VALID_ACTIONS = {"pause", "resume", "abandon"}

_ACTION_TO_STATUS: dict[str, str] = {
    "pause": "paused",
    "resume": "active",
    "abandon": "abandoned",
}

_VALID_TICK_INTERVALS = {"5m", "10m", "15m", "30m", "1h"}
_VALID_TICK_WINDOWS = {"8am-11pm", "8am-6pm", "24h"}


# ─── Auth dependency ────────────────────────────────────────


def _get_api_key() -> str:
    """Read the API key from environment."""
    return os.getenv("TRELLIS_API_KEY", "")


def verify_api_key(authorization: str = Header(default="")) -> None:
    """Verify Bearer token matches TRELLIS_API_KEY."""
    expected = _get_api_key()
    if not expected:
        raise HTTPException(
            status_code=500,
            detail="TRELLIS_API_KEY not configured on server",
        )

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0] != "Bearer":
        raise HTTPException(
            status_code=401,
            detail="Invalid Authorization format (expected 'Bearer <key>')",
        )

    if parts[1] != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ─── Request/Response models ────────────────────────────────


class QuestStatusRequest(BaseModel):
    """Request body for PATCH /api/quests/{quest_id}/status."""

    action: Literal["pause", "resume", "abandon"]


class QuestStatusResponse(BaseModel):
    """Response for quest status change."""

    quest_id: str
    status: str
    updated_at: str


class TickConfigRequest(BaseModel):
    """Request body for PATCH /api/quests/{quest_id}/tick-config."""

    tick_interval: str | None = None
    tick_window: str | None = None


class TickConfigResponse(BaseModel):
    """Response for tick config update."""

    quest_id: str
    tick_interval: str
    tick_window: str
    updated_at: str


class QuestUsage(BaseModel):
    """Per-quest usage data."""

    quest_id: str
    title: str
    spent: float
    budget: float


class UsageResponse(BaseModel):
    """Response for GET /api/admin/usage."""

    total_spent: float
    total_budget: float
    by_quest: list[QuestUsage]


class TickHistoryEntry(BaseModel):
    """A single tick event in the history."""

    quest_id: str
    quest_title: str
    tick_number: int
    timestamp: str
    status: str
    duration_ms: int | None = None


class TickHistoryResponse(BaseModel):
    """Response for GET /api/admin/ticks."""

    ticks: list[TickHistoryEntry]
    next_cursor: str | None = None


# ─── Router factory ─────────────────────────────────────────


def create_admin_router(
    quests_dir: Path,
    activity_store: ActivityStore,
) -> APIRouter:
    """Create the admin API router.

    Args:
        quests_dir: Path to the quests directory.
        activity_store: ActivityStore for reading tick history.

    Returns:
        FastAPI APIRouter with admin endpoints.
    """
    router = APIRouter(tags=["admin"])

    # ── PATCH /api/quests/{quest_id}/status ───────────────

    @router.patch(
        "/api/quests/{quest_id}/status",
        response_model=QuestStatusResponse,
        dependencies=[Depends(verify_api_key)],
    )
    async def update_quest_status(
        quest_id: str,
        body: QuestStatusRequest,
    ) -> QuestStatusResponse:
        """Pause, resume, or abandon a quest."""
        quest_path = quests_dir / f"{quest_id}.md"
        if not quest_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Quest '{quest_id}' not found",
            )

        quest = load_quest(quest_path)
        new_status = _ACTION_TO_STATUS[body.action]

        # Validate state transitions
        if body.action == "resume" and quest.status not in ("paused", "waiting"):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot resume quest with status '{quest.status}' (must be paused or waiting)",
            )

        if body.action == "pause" and quest.status not in ("active", "waiting"):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot pause quest with status '{quest.status}' (must be active or waiting)",
            )

        if body.action == "abandon" and quest.status in ("abandoned", "complete"):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot abandon quest with status '{quest.status}'",
            )

        quest.status = new_status
        quest.updated = date.today()
        save_quest(quest, quest_path)

        updated_at = datetime.now().isoformat()
        logger.info(
            "Quest '%s' status changed to '%s' via admin API",
            quest_id,
            new_status,
        )

        return QuestStatusResponse(
            quest_id=quest_id,
            status=new_status,
            updated_at=updated_at,
        )

    # ── PATCH /api/quests/{quest_id}/tick-config ──────────

    @router.patch(
        "/api/quests/{quest_id}/tick-config",
        response_model=TickConfigResponse,
        dependencies=[Depends(verify_api_key)],
    )
    async def update_tick_config(
        quest_id: str,
        body: TickConfigRequest,
    ) -> TickConfigResponse:
        """Update a quest's tick interval and/or window."""
        quest_path = quests_dir / f"{quest_id}.md"
        if not quest_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Quest '{quest_id}' not found",
            )

        # Validate inputs
        if body.tick_interval is not None and body.tick_interval not in _VALID_TICK_INTERVALS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid tick_interval '{body.tick_interval}'. "
                       f"Valid values: {', '.join(sorted(_VALID_TICK_INTERVALS))}",
            )

        if body.tick_window is not None and body.tick_window not in _VALID_TICK_WINDOWS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid tick_window '{body.tick_window}'. "
                       f"Valid values: {', '.join(sorted(_VALID_TICK_WINDOWS))}",
            )

        if body.tick_interval is None and body.tick_window is None:
            raise HTTPException(
                status_code=400,
                detail="Must provide at least one of tick_interval or tick_window",
            )

        quest = load_quest(quest_path)

        if body.tick_interval is not None:
            quest.tick_interval = body.tick_interval
        if body.tick_window is not None:
            quest.tick_window = body.tick_window

        quest.updated = date.today()
        save_quest(quest, quest_path)

        updated_at = datetime.now().isoformat()
        logger.info(
            "Quest '%s' tick config updated: interval=%s, window=%s",
            quest_id,
            quest.tick_interval,
            quest.tick_window,
        )

        return TickConfigResponse(
            quest_id=quest_id,
            tick_interval=quest.tick_interval,
            tick_window=quest.tick_window,
            updated_at=updated_at,
        )

    # ── GET /api/admin/usage ─────────────────────────────

    @router.get(
        "/api/admin/usage",
        response_model=UsageResponse,
        dependencies=[Depends(verify_api_key)],
    )
    async def get_usage() -> UsageResponse:
        """Get aggregated model usage across all quests."""
        quests = list_quests(quests_dir)

        total_spent = 0.0
        total_budget = 0.0
        by_quest: list[QuestUsage] = []

        for q in quests:
            spent = float(q.budget_spent_claude)
            budget = float(q.budget_claude)
            total_spent += spent
            total_budget += budget
            by_quest.append(
                QuestUsage(
                    quest_id=q.id,
                    title=q.title,
                    spent=spent,
                    budget=budget,
                )
            )

        return UsageResponse(
            total_spent=total_spent,
            total_budget=total_budget,
            by_quest=by_quest,
        )

    # ── GET /api/admin/ticks ─────────────────────────────

    @router.get(
        "/api/admin/ticks",
        response_model=TickHistoryResponse,
        dependencies=[Depends(verify_api_key)],
    )
    async def get_tick_history(
        limit: int = Query(default=50, ge=1, le=200),
        before: str | None = Query(default=None),
    ) -> TickHistoryResponse:
        """Get recent tick events from the activity store."""
        _TICK_TYPES = {"tick_completed", "tick_failed", "tick_skipped"}

        # Read a larger batch to filter from
        # We over-fetch to account for non-tick events in the stream
        fetch_limit = limit * 5  # Over-fetch since most events may not be ticks
        if fetch_limit > 200:
            fetch_limit = 200

        all_events, _ = activity_store.read_recent(
            limit=fetch_limit,
            before=before,
        )

        tick_entries: list[TickHistoryEntry] = []
        for event in all_events:
            event_type = event.get("type", "")
            if event_type not in _TICK_TYPES:
                continue

            # Map activity type to tick status
            if event_type == "tick_completed":
                status = "completed"
            elif event_type == "tick_failed":
                status = "failed"
            else:
                status = "skipped"

            tick_entries.append(
                TickHistoryEntry(
                    quest_id=event.get("quest_id", ""),
                    quest_title=event.get("quest_title", ""),
                    tick_number=event.get("tick_number", 0),
                    timestamp=event.get("timestamp", ""),
                    status=status,
                    duration_ms=event.get("duration_ms"),
                )
            )

            if len(tick_entries) >= limit:
                break

        # Determine next_cursor from the last tick entry
        next_cursor: str | None = None
        if len(tick_entries) >= limit and tick_entries:
            next_cursor = tick_entries[-1].timestamp

        return TickHistoryResponse(
            ticks=tick_entries,
            next_cursor=next_cursor,
        )

    return router
