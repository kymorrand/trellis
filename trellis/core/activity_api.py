"""
trellis.core.activity_api — Activity feed REST endpoint.

Provides:
    GET /api/activity — Returns recent activity events with cursor pagination.

Query params:
    limit  — Max events to return (default 50, max 200)
    before — ISO 8601 timestamp cursor for pagination

Response matches ActivityResponse TypeScript interface in trellis-app/lib/types.ts:
    { events: ActivityEvent[], next_cursor: string | null }

All endpoints require Authorization: Bearer {TRELLIS_API_KEY} header.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from trellis.core.activity_store import ActivityStore

logger = logging.getLogger(__name__)


# ─── Auth dependency ──────────────────────────────────────────


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


# ─── Router factory ──────────────────────────────────────────


def create_activity_router(store: ActivityStore) -> APIRouter:
    """Create the activity API router.

    Args:
        store: ActivityStore instance for reading persisted events.
    """
    router = APIRouter(
        prefix="/api",
        tags=["activity"],
        dependencies=[Depends(verify_api_key)],
    )

    @router.get("/activity")
    async def get_activity(
        limit: int = Query(default=50, ge=1, le=200),
        before: str | None = Query(default=None),
    ) -> dict:
        """Return recent activity events with cursor pagination."""
        events, next_cursor = store.read_recent(limit=limit, before=before)
        return {
            "events": events,
            "next_cursor": next_cursor,
        }

    return router
