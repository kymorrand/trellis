"""
trellis.core.quest_api — Quest REST API Endpoints

Provides FastAPI router for quest CRUD operations. Registered onto
the main FastAPI app in web.py.

Endpoints:
    GET    /api/quests          — List all quests with summary state
    GET    /api/quests/{id}     — Full quest detail (parsed frontmatter + markdown)
    POST   /api/quests          — Create new quest (from template or raw)
    PATCH  /api/quests/{id}     — Update quest fields (status, priority, budget)

All endpoints require Authorization: Bearer {TRELLIS_API_KEY} header.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from trellis.core.quest import (
    Quest,
    list_quests,
    load_quest,
    save_quest,
)

logger = logging.getLogger(__name__)

# ─── Auth dependency ──────────────────────────────────────────


def _get_api_key() -> str:
    """Read the API key from environment."""
    return os.getenv("TRELLIS_API_KEY", "")


def verify_api_key(authorization: str = Header(default="")) -> None:
    """Verify Bearer token matches TRELLIS_API_KEY.

    Raises HTTPException 401 if missing or invalid.
    """
    expected = _get_api_key()
    if not expected:
        raise HTTPException(
            status_code=500,
            detail="TRELLIS_API_KEY not configured on server",
        )

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    # Accept "Bearer <key>" format
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0] != "Bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization format (expected 'Bearer <key>')")

    if parts[1] != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ─── Pydantic request/response models ────────────────────────


class QuestSummary(BaseModel):
    """Summary representation of a quest for list endpoints."""

    id: str
    title: str
    status: str
    priority: str
    type: str
    role: str
    steps_completed: int
    total_steps: int
    budget_claude: int
    budget_spent_claude: int
    updated: str | None = None


class QuestStepResponse(BaseModel):
    """Step in a quest checklist."""

    text: str
    done: bool
    blocked_by: str | None = None


class QuestDetail(BaseModel):
    """Full quest detail for single-quest endpoints."""

    id: str
    title: str
    status: str
    type: str
    priority: str
    role: str
    created: str | None = None
    updated: str | None = None
    tick_interval: str
    tick_window: str
    budget_claude: int
    budget_spent_claude: int
    steps_completed: int
    total_steps: int
    goal_hash: str
    drift_check_interval: int
    goal: str
    success_criteria: str
    steps: list[QuestStepResponse]
    questions: str
    artifacts: str
    log: str
    blockers: str
    extra: dict[str, Any] = Field(default_factory=dict)


class CreateQuestRequest(BaseModel):
    """Request body for creating a new quest."""

    title: str
    template: str | None = None  # "research" or "writing"
    type: str = "research"
    priority: str = "standard"
    role: str = "_default"


class PatchQuestRequest(BaseModel):
    """Request body for partial quest updates."""

    title: str | None = None
    status: str | None = None
    priority: str | None = None
    type: str | None = None
    role: str | None = None
    tick_interval: str | None = None
    tick_window: str | None = None
    budget_claude: int | None = None
    budget_spent_claude: int | None = None
    steps_completed: int | None = None
    goal_hash: str | None = None
    drift_check_interval: int | None = None


class QuestListResponse(BaseModel):
    """Response for GET /api/quests."""

    quests: list[QuestSummary]
    count: int


# ─── Helpers ──────────────────────────────────────────────────


def _quest_to_summary(q: Quest) -> QuestSummary:
    return QuestSummary(
        id=q.id,
        title=q.title,
        status=q.status,
        priority=q.priority,
        type=q.type,
        role=q.role,
        steps_completed=q.steps_completed,
        total_steps=q.total_steps,
        budget_claude=q.budget_claude,
        budget_spent_claude=q.budget_spent_claude,
        updated=q.updated.isoformat() if q.updated else None,
    )


def _quest_to_detail(q: Quest) -> QuestDetail:
    return QuestDetail(
        id=q.id,
        title=q.title,
        status=q.status,
        type=q.type,
        priority=q.priority,
        role=q.role,
        created=q.created.isoformat() if q.created else None,
        updated=q.updated.isoformat() if q.updated else None,
        tick_interval=q.tick_interval,
        tick_window=q.tick_window,
        budget_claude=q.budget_claude,
        budget_spent_claude=q.budget_spent_claude,
        steps_completed=q.steps_completed,
        total_steps=q.total_steps,
        goal_hash=q.goal_hash,
        drift_check_interval=q.drift_check_interval,
        goal=q.goal,
        success_criteria=q.success_criteria,
        steps=[
            QuestStepResponse(text=s.text, done=s.done, blocked_by=s.blocked_by)
            for s in q.steps
        ],
        questions=q.questions,
        artifacts=q.artifacts,
        log=q.log,
        blockers=q.blockers,
        extra=q.extra,
    )


def _slugify(title: str) -> str:
    """Convert a title to a quest ID slug."""
    slug = title.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def _load_template(templates_dir: Path, template_name: str) -> str | None:
    """Load a template file, returning its content or None."""
    template_path = templates_dir / f"{template_name}-quest.md"
    if not template_path.exists():
        return None
    return template_path.read_text(encoding="utf-8")


# ─── Router factory ──────────────────────────────────────────


def create_quest_router(quests_dir: Path) -> APIRouter:
    """Create an APIRouter with quest CRUD endpoints.

    Args:
        quests_dir: Path to the quests directory (e.g., vault/_ivy/quests/).

    Returns:
        FastAPI APIRouter with /api/quests endpoints.
    """
    router = APIRouter(prefix="/api/quests", tags=["quests"])
    templates_dir = quests_dir / "_templates"

    @router.get("", response_model=QuestListResponse)
    async def list_all_quests(_: None = Depends(verify_api_key)) -> QuestListResponse:
        """List all quests with summary state."""
        quests = list_quests(quests_dir)
        summaries = [_quest_to_summary(q) for q in quests]
        return QuestListResponse(quests=summaries, count=len(summaries))

    @router.get("/{quest_id}", response_model=QuestDetail)
    async def get_quest(quest_id: str, _: None = Depends(verify_api_key)) -> QuestDetail:
        """Get full quest detail by ID."""
        quest_path = quests_dir / f"{quest_id}.md"
        if not quest_path.exists():
            raise HTTPException(status_code=404, detail=f"Quest '{quest_id}' not found")

        quest = load_quest(quest_path)
        return _quest_to_detail(quest)

    @router.post("", response_model=QuestDetail, status_code=201)
    async def create_quest(
        body: CreateQuestRequest,
        _: None = Depends(verify_api_key),
    ) -> QuestDetail:
        """Create a new quest from template or raw."""
        quest_id = _slugify(body.title)
        quest_path = quests_dir / f"{quest_id}.md"

        if quest_path.exists():
            raise HTTPException(
                status_code=409,
                detail=f"Quest '{quest_id}' already exists",
            )

        today = date.today()

        if body.template:
            # Load template and fill placeholders
            template_content = _load_template(templates_dir, body.template)
            if not template_content:
                raise HTTPException(
                    status_code=400,
                    detail=f"Template '{body.template}' not found",
                )

            content = template_content.replace("{quest-id}", quest_id)
            content = content.replace("{title}", body.title)
            content = content.replace("{date}", today.isoformat())

            # Ensure parent dir exists
            quests_dir.mkdir(parents=True, exist_ok=True)
            quest_path.write_text(content, encoding="utf-8")
            quest = load_quest(quest_path)

            # Override fields from request
            quest.type = body.type
            quest.priority = body.priority
            quest.role = body.role
            save_quest(quest, quest_path)
            quest = load_quest(quest_path)
        else:
            # Create from scratch
            quest = Quest(
                id=quest_id,
                title=body.title,
                status="draft",
                type=body.type,
                priority=body.priority,
                role=body.role,
                created=today,
                updated=today,
            )
            save_quest(quest, quest_path)
            quest = load_quest(quest_path)

        logger.info("Created quest '%s' at %s", quest.id, quest_path)
        return _quest_to_detail(quest)

    @router.patch("/{quest_id}", response_model=QuestDetail)
    async def patch_quest(
        quest_id: str,
        body: PatchQuestRequest,
        _: None = Depends(verify_api_key),
    ) -> QuestDetail:
        """Update quest frontmatter fields (partial update)."""
        quest_path = quests_dir / f"{quest_id}.md"
        if not quest_path.exists():
            raise HTTPException(status_code=404, detail=f"Quest '{quest_id}' not found")

        quest = load_quest(quest_path)

        # Apply partial updates
        updates = body.model_dump(exclude_none=True)
        for field_name, value in updates.items():
            if hasattr(quest, field_name):
                setattr(quest, field_name, value)

        # Always bump updated date on patch
        quest.updated = date.today()

        save_quest(quest, quest_path)

        # Re-load to ensure consistency
        quest = load_quest(quest_path)
        logger.info("Updated quest '%s': %s", quest_id, list(updates.keys()))
        return _quest_to_detail(quest)

    return router
