"""
tests.core.test_questions — Tests for question parsing, serialization, and API.

Tests cover:
    - Parsing questions from markdown format
    - Round-trip: parse -> serialize -> parse produces identical output
    - Answer submission via API (text answer and suggestion index)
    - Bonus tick event emission on answer
    - Auth on all endpoints
    - Edge cases: empty sections, no suggestions, already answered
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trellis.core.events import EventBus, EventType
from trellis.core.quest import Quest, save_quest
from trellis.core.question_api import create_question_router
from trellis.core.questions import (
    Question,
    next_question_id,
    parse_questions,
    serialize_questions,
)

# ─── Test data ──────────────────────────────────────────────

SAMPLE_QUESTIONS_MD = """\
### Q-001 [blocking] [pending]
Should I focus on B2B or B2C models?

**Context:** Found strong comparables in both directions during market scan.

**Suggestions:**
- Both -- compare
- B2B only
- B2C only

**Answer:** (none)

### Q-002 [important] [answered]
Which framework for the prototype?

**Context:** Evaluated three options last tick.

**Suggestions:**
- FastAPI
- Flask

**Answer:** FastAPI
"""

SINGLE_QUESTION_MD = """\
### Q-001 [nice-to-have] [pending]
Any preference on color scheme?

**Answer:** (none)
"""


# ─── Question parsing tests ──────────────────────────────────


class TestParseQuestions:
    def test_parse_multiple_questions(self) -> None:
        questions = parse_questions(SAMPLE_QUESTIONS_MD)
        assert len(questions) == 2

    def test_parse_first_question_fields(self) -> None:
        questions = parse_questions(SAMPLE_QUESTIONS_MD)
        q = questions[0]
        assert q.id == "Q-001"
        assert q.urgency == "blocking"
        assert q.status == "pending"
        assert "B2B or B2C" in q.text
        assert "comparables" in q.context
        assert len(q.suggestions) == 3
        assert q.suggestions[0] == "Both -- compare"
        assert q.answer == ""

    def test_parse_answered_question(self) -> None:
        questions = parse_questions(SAMPLE_QUESTIONS_MD)
        q = questions[1]
        assert q.id == "Q-002"
        assert q.status == "answered"
        assert q.answer == "FastAPI"
        assert q.urgency == "important"
        assert len(q.suggestions) == 2

    def test_parse_question_no_context_no_suggestions(self) -> None:
        questions = parse_questions(SINGLE_QUESTION_MD)
        assert len(questions) == 1
        q = questions[0]
        assert q.id == "Q-001"
        assert q.urgency == "nice-to-have"
        assert q.context == ""
        assert q.suggestions == []

    def test_parse_empty_section(self) -> None:
        assert parse_questions("") == []
        assert parse_questions("   ") == []

    def test_parse_no_question_blocks(self) -> None:
        assert parse_questions("Some random text without headings") == []


class TestSerializeQuestions:
    def test_serialize_round_trip(self) -> None:
        """Parse -> serialize -> parse should produce identical questions."""
        original = parse_questions(SAMPLE_QUESTIONS_MD)
        serialized = serialize_questions(original)
        reparsed = parse_questions(serialized)

        assert len(reparsed) == len(original)
        for orig, new in zip(original, reparsed):
            assert orig.id == new.id
            assert orig.text == new.text
            assert orig.context == new.context
            assert orig.urgency == new.urgency
            assert orig.status == new.status
            assert orig.suggestions == new.suggestions
            assert orig.answer == new.answer

    def test_serialize_empty_list(self) -> None:
        assert serialize_questions([]) == ""

    def test_serialize_single_question(self) -> None:
        q = Question(
            id="Q-010",
            text="Test question?",
            urgency="blocking",
            status="pending",
        )
        result = serialize_questions([q])
        assert "### Q-010 [blocking] [pending]" in result
        assert "Test question?" in result
        assert "**Answer:** (none)" in result


class TestNextQuestionId:
    def test_next_id_empty_list(self) -> None:
        assert next_question_id([]) == "Q-001"

    def test_next_id_after_existing(self) -> None:
        questions = [
            Question(id="Q-001", text="a"),
            Question(id="Q-003", text="b"),
        ]
        assert next_question_id(questions) == "Q-004"


# ─── API tests ──────────────────────────────────────────────


@pytest.fixture
def tmp_quests_dir(tmp_path: Path) -> Path:
    quests_dir = tmp_path / "quests"
    quests_dir.mkdir()
    return quests_dir


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def quest_with_questions(tmp_quests_dir: Path) -> Quest:
    """Create a quest file with sample questions."""
    quest = Quest(
        id="test-quest",
        title="Test Quest",
        status="active",
        questions=SAMPLE_QUESTIONS_MD,
    )
    save_quest(quest, tmp_quests_dir / "test-quest.md")
    return quest


@pytest.fixture
def api_key() -> str:
    key = "test-api-key-123"
    os.environ["TRELLIS_API_KEY"] = key
    yield key
    os.environ.pop("TRELLIS_API_KEY", None)


@pytest.fixture
def client(
    tmp_quests_dir: Path,
    event_bus: EventBus,
    api_key: str,
) -> TestClient:
    app = FastAPI()
    app.include_router(create_question_router(tmp_quests_dir, event_bus))
    return TestClient(app)


def _auth_header(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


class TestQuestionApiList:
    def test_list_questions(
        self,
        client: TestClient,
        api_key: str,
        quest_with_questions: Quest,
    ) -> None:
        resp = client.get(
            "/api/quests/test-quest/questions",
            headers=_auth_header(api_key),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert data["questions"][0]["id"] == "Q-001"
        assert data["questions"][0]["urgency"] == "blocking"

    def test_list_questions_quest_not_found(
        self,
        client: TestClient,
        api_key: str,
    ) -> None:
        resp = client.get(
            "/api/quests/nonexistent/questions",
            headers=_auth_header(api_key),
        )
        assert resp.status_code == 404

    def test_list_questions_no_auth(
        self,
        client: TestClient,
        quest_with_questions: Quest,
    ) -> None:
        resp = client.get("/api/quests/test-quest/questions")
        assert resp.status_code == 401

    def test_list_questions_empty(
        self,
        client: TestClient,
        api_key: str,
        tmp_quests_dir: Path,
    ) -> None:
        """Quest with no questions section returns empty list."""
        quest = Quest(id="empty-quest", title="Empty", status="active")
        save_quest(quest, tmp_quests_dir / "empty-quest.md")
        resp = client.get(
            "/api/quests/empty-quest/questions",
            headers=_auth_header(api_key),
        )
        assert resp.status_code == 200
        assert resp.json()["count"] == 0


class TestQuestionApiAnswer:
    def test_answer_with_text(
        self,
        client: TestClient,
        api_key: str,
        quest_with_questions: Quest,
    ) -> None:
        resp = client.post(
            "/api/quests/test-quest/questions/Q-001/answer",
            json={"answer": "Go B2B first"},
            headers=_auth_header(api_key),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "answered"
        assert data["answer"] == "Go B2B first"

    def test_answer_with_suggestion_index(
        self,
        client: TestClient,
        api_key: str,
        quest_with_questions: Quest,
    ) -> None:
        resp = client.post(
            "/api/quests/test-quest/questions/Q-001/answer",
            json={"suggestion_index": 1},
            headers=_auth_header(api_key),
        )
        assert resp.status_code == 200
        assert resp.json()["answer"] == "B2B only"

    def test_answer_persists_to_file(
        self,
        client: TestClient,
        api_key: str,
        quest_with_questions: Quest,
        tmp_quests_dir: Path,
    ) -> None:
        client.post(
            "/api/quests/test-quest/questions/Q-001/answer",
            json={"answer": "B2C"},
            headers=_auth_header(api_key),
        )
        # Re-read from file
        resp = client.get(
            "/api/quests/test-quest/questions",
            headers=_auth_header(api_key),
        )
        q001 = [q for q in resp.json()["questions"] if q["id"] == "Q-001"][0]
        assert q001["status"] == "answered"
        assert q001["answer"] == "B2C"

    def test_answer_triggers_bonus_tick_event(
        self,
        client: TestClient,
        api_key: str,
        quest_with_questions: Quest,
        event_bus: EventBus,
    ) -> None:
        queue = event_bus.subscribe()
        client.post(
            "/api/quests/test-quest/questions/Q-001/answer",
            json={"answer": "test"},
            headers=_auth_header(api_key),
        )
        # The event should be in the queue
        event = asyncio.run(asyncio.wait_for(queue.get(), timeout=2.0))
        assert event.event_type == EventType.BONUS_TICK_TRIGGERED
        assert event.quest_id == "test-quest"
        assert event.data["question_id"] == "Q-001"

    def test_answer_already_answered(
        self,
        client: TestClient,
        api_key: str,
        quest_with_questions: Quest,
    ) -> None:
        # Q-002 is already answered
        resp = client.post(
            "/api/quests/test-quest/questions/Q-002/answer",
            json={"answer": "Flask"},
            headers=_auth_header(api_key),
        )
        assert resp.status_code == 409

    def test_answer_question_not_found(
        self,
        client: TestClient,
        api_key: str,
        quest_with_questions: Quest,
    ) -> None:
        resp = client.post(
            "/api/quests/test-quest/questions/Q-999/answer",
            json={"answer": "test"},
            headers=_auth_header(api_key),
        )
        assert resp.status_code == 404

    def test_answer_no_body(
        self,
        client: TestClient,
        api_key: str,
        quest_with_questions: Quest,
    ) -> None:
        resp = client.post(
            "/api/quests/test-quest/questions/Q-001/answer",
            json={},
            headers=_auth_header(api_key),
        )
        assert resp.status_code == 400

    def test_answer_suggestion_index_out_of_range(
        self,
        client: TestClient,
        api_key: str,
        quest_with_questions: Quest,
    ) -> None:
        resp = client.post(
            "/api/quests/test-quest/questions/Q-001/answer",
            json={"suggestion_index": 99},
            headers=_auth_header(api_key),
        )
        assert resp.status_code == 400

    def test_answer_no_auth(
        self,
        client: TestClient,
        quest_with_questions: Quest,
    ) -> None:
        resp = client.post(
            "/api/quests/test-quest/questions/Q-001/answer",
            json={"answer": "test"},
        )
        assert resp.status_code == 401
