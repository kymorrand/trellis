"""
trellis.core.approval_api — Approval REST API Endpoints

Provides FastAPI router for listing and acting on approvals.

Endpoints:
    GET    /api/approvals                — List pending approvals
    POST   /api/approvals/{approval_id}  — Approve or reject

All endpoints require Authorization: Bearer {TRELLIS_API_KEY} header.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from trellis.core.approvals import Approval, ApprovalStore
from trellis.core.events import EventBus, EventType, QuestEvent
from trellis.core.quest_api import verify_api_key

logger = logging.getLogger(__name__)


# ─── Pydantic models ────────────────────────────────────────


class ApprovalResponse(BaseModel):
    """API representation of a single approval."""

    id: str
    quest_id: str
    quest_name: str
    title: str
    description: str
    status: str = "pending"
    cost_estimate: str | None = None
    created_at: str = ""
    resolved_at: str | None = None
    reject_reason: str | None = None


class ApprovalListResponse(BaseModel):
    """Response for GET /api/approvals."""

    approvals: list[ApprovalResponse]
    count: int


class ApprovalActionRequest(BaseModel):
    """Request body for POST /api/approvals/{id}."""

    action: str  # "approve" or "reject"
    reason: str = ""


# ─── Helpers ────────────────────────────────────────────────


def _approval_to_response(a: Approval) -> ApprovalResponse:
    return ApprovalResponse(
        id=a.id,
        quest_id=a.quest_id,
        quest_name=a.quest_name,
        title=a.title,
        description=a.description,
        status=a.status,
        cost_estimate=a.cost_estimate,
        created_at=a.created_at,
        resolved_at=a.resolved_at,
        reject_reason=a.reject_reason,
    )


# ─── Router factory ────────────────────────────────────────


def create_approval_router(
    approvals_dir: Path,
    event_bus: EventBus,
) -> APIRouter:
    """Create an APIRouter with approval endpoints.

    Args:
        approvals_dir: Path to the ``_ivy/approvals/`` directory.
        event_bus: EventBus for publishing approval events.

    Returns:
        FastAPI APIRouter with approval endpoints.
    """
    router = APIRouter(prefix="/api/approvals", tags=["approvals"])
    store = ApprovalStore(approvals_dir)

    @router.get("", response_model=ApprovalListResponse)
    async def list_approvals(
        _: None = Depends(verify_api_key),
    ) -> ApprovalListResponse:
        """List all pending approvals across all quests."""
        approvals = store.list_pending()
        return ApprovalListResponse(
            approvals=[_approval_to_response(a) for a in approvals],
            count=len(approvals),
        )

    @router.post("/{approval_id}", response_model=ApprovalResponse)
    async def act_on_approval(
        approval_id: str,
        body: ApprovalActionRequest,
        _: None = Depends(verify_api_key),
    ) -> ApprovalResponse:
        """Approve or reject a pending approval."""
        if body.action not in ("approve", "reject"):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid action '{body.action}'. Must be 'approve' or 'reject'.",
            )

        if body.action == "approve":
            approval = store.approve(approval_id)
        else:
            approval = store.reject(approval_id, reason=body.reason)

        if approval is None:
            raise HTTPException(
                status_code=404,
                detail=f"Approval '{approval_id}' not found",
            )

        # Emit event so the scheduler knows to proceed (or halt)
        event_type = (
            EventType.QUEST_STATUS_CHANGED
            if body.action == "approve"
            else EventType.QUEST_STATUS_CHANGED
        )
        await event_bus.publish(
            QuestEvent(
                event_type=event_type,
                quest_id=approval.quest_id,
                data={
                    "approval_id": approval_id,
                    "action": body.action,
                    "reason": body.reason if body.action == "reject" else "",
                },
            )
        )

        logger.info(
            "Approval %s %sd for quest %s",
            approval_id,
            body.action,
            approval.quest_id,
        )

        return _approval_to_response(approval)

    return router
