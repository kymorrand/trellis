"""
trellis.core.question_api — Question REST API Endpoints

Provides FastAPI router for per-quest question read and answer operations.

Endpoints:
    GET    /api/quests/{quest_id}/questions                        — List questions
    POST   /api/quests/{quest_id}/questions/{question_id}/answer   — Answer a question

All endpoints require Authorization: Bearer {TRELLIS_API_KEY} header.
"""

from __future__ import annotations

import logging
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from trellis.core.events import EventBus, EventType, QuestEvent
from trellis.core.quest import load_quest, save_quest
from trellis.core.quest_api import verify_api_key
from trellis.core.questions import Question, parse_questions, serialize_questions

logger = logging.getLogger(__name__)


# ─── Pydantic models ────────────────────────────────────────


class QuestionResponse(BaseModel):
    """API representation of a single question."""

    id: str
    text: str
    context: str = ""
    urgency: str = "important"
    suggestions: list[str] = Field(default_factory=list)
    status: str = "pending"
    answer: str = ""


class QuestionListResponse(BaseModel):
    """Response for GET /api/quests/{id}/questions."""

    questions: list[QuestionResponse]
    count: int


class AnswerRequest(BaseModel):
    """Request body for answering a question."""

    answer: str | None = None
    suggestion_index: int | None = None


# ─── Helpers ────────────────────────────────────────────────


def _question_to_response(q: Question) -> QuestionResponse:
    return QuestionResponse(
        id=q.id,
        text=q.text,
        context=q.context,
        urgency=q.urgency,
        suggestions=q.suggestions,
        status=q.status,
        answer=q.answer,
    )


# ─── Router factory ────────────────────────────────────────


def create_question_router(
    quests_dir: Path,
    event_bus: EventBus,
) -> APIRouter:
    """Create an APIRouter with question endpoints.

    Args:
        quests_dir: Path to the quests directory.
        event_bus: EventBus for publishing bonus tick events.

    Returns:
        FastAPI APIRouter with question endpoints.
    """
    router = APIRouter(
        prefix="/api/quests",
        tags=["questions"],
    )

    @router.get(
        "/{quest_id}/questions",
        response_model=QuestionListResponse,
    )
    async def list_questions(
        quest_id: str,
        _: None = Depends(verify_api_key),
    ) -> QuestionListResponse:
        """List questions for a specific quest."""
        quest_path = quests_dir / f"{quest_id}.md"
        if not quest_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Quest '{quest_id}' not found",
            )

        quest = load_quest(quest_path)
        questions = parse_questions(quest.questions)
        return QuestionListResponse(
            questions=[_question_to_response(q) for q in questions],
            count=len(questions),
        )

    @router.post(
        "/{quest_id}/questions/{question_id}/answer",
        response_model=QuestionResponse,
    )
    async def answer_question(
        quest_id: str,
        question_id: str,
        body: AnswerRequest,
        _: None = Depends(verify_api_key),
    ) -> QuestionResponse:
        """Answer a specific question and trigger a bonus tick."""
        quest_path = quests_dir / f"{quest_id}.md"
        if not quest_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Quest '{quest_id}' not found",
            )

        quest = load_quest(quest_path)
        questions = parse_questions(quest.questions)

        # Find the target question
        target: Question | None = None
        for q in questions:
            if q.id == question_id:
                target = q
                break

        if target is None:
            raise HTTPException(
                status_code=404,
                detail=f"Question '{question_id}' not found in quest '{quest_id}'",
            )

        if target.status == "answered":
            raise HTTPException(
                status_code=409,
                detail=f"Question '{question_id}' is already answered",
            )

        # Determine the answer text
        if body.answer is not None:
            answer_text = body.answer
        elif body.suggestion_index is not None:
            if body.suggestion_index < 0 or body.suggestion_index >= len(
                target.suggestions
            ):
                raise HTTPException(
                    status_code=400,
                    detail=f"suggestion_index {body.suggestion_index} out of range "
                    f"(0-{len(target.suggestions) - 1})",
                )
            answer_text = target.suggestions[body.suggestion_index]
        else:
            raise HTTPException(
                status_code=400,
                detail="Must provide either 'answer' or 'suggestion_index'",
            )

        # Update the question
        target.status = "answered"
        target.answer = answer_text

        # Serialize back to quest and save
        quest.questions = serialize_questions(questions)
        save_quest(quest, quest_path)

        # Trigger bonus tick event
        await event_bus.publish(
            QuestEvent(
                event_type=EventType.BONUS_TICK_TRIGGERED,
                quest_id=quest_id,
                data={"question_id": question_id, "answer": answer_text},
            )
        )

        logger.info(
            "Answered question %s in quest %s, bonus tick triggered",
            question_id,
            quest_id,
        )

        return _question_to_response(target)

    return router
