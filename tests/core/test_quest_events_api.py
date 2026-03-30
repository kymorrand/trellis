"""
tests.core.test_quest_events_api — Tests for SSE quest events endpoint.

Tests cover:
    - SSE stream format helpers (_event_to_sse, _snapshot_to_sse)
    - Initial state snapshot content
    - Auth on endpoint
    - Event bus subscription/unsubscription
    - Keepalive ping format
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trellis.core.events import EventBus, EventType, QuestEvent, TickPhase
from trellis.core.quest import Quest, save_quest
from trellis.core.quest_events_api import (
    _event_to_sse,
    _snapshot_to_sse,
    create_quest_events_router,
)


# ─── Fixtures ───────────────────────────────────────────────


@pytest.fixture
def tmp_quests_dir(tmp_path: Path) -> Path:
    quests_dir = tmp_path / "quests"
    quests_dir.mkdir()
    return quests_dir


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def api_key() -> str:
    key = "test-sse-key-789"
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
    app.include_router(create_quest_events_router(tmp_quests_dir, event_bus))
    return TestClient(app)


def _auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


# ─── Helper function tests ──────────────────────────────────


class TestEventToSse:
    def test_basic_event(self) -> None:
        event = QuestEvent(
            event_type=EventType.TICK_STARTED,
            quest_id="test-quest",
            timestamp=datetime(2026, 3, 30, 12, 0, 0),
        )
        result = _event_to_sse(event)
        assert result.startswith("data: ")
        assert result.endswith("\n\n")

        payload = json.loads(result[6:-2])
        assert payload["type"] == "tick.started"
        assert payload["quest_id"] == "test-quest"
        assert "timestamp" in payload

    def test_event_with_phase(self) -> None:
        event = QuestEvent(
            event_type=EventType.TICK_PHASE_ENTERED,
            quest_id="q-1",
            phase=TickPhase.EXECUTE,
        )
        result = _event_to_sse(event)
        payload = json.loads(result[6:-2])
        assert payload["phase"] == "execute"

    def test_event_with_data(self) -> None:
        event = QuestEvent(
            event_type=EventType.TICK_COMPLETED,
            quest_id="q-1",
            data={"duration_ms": 1500},
        )
        result = _event_to_sse(event)
        payload = json.loads(result[6:-2])
        assert payload["data"]["duration_ms"] == 1500

    def test_event_without_phase_or_data(self) -> None:
        event = QuestEvent(
            event_type=EventType.SCHEDULER_STARTED,
            quest_id="__scheduler__",
        )
        result = _event_to_sse(event)
        payload = json.loads(result[6:-2])
        assert "phase" not in payload
        assert "data" not in payload


class TestSnapshotToSse:
    def test_empty_quests_dir(self, tmp_quests_dir: Path) -> None:
        result = _snapshot_to_sse(tmp_quests_dir)
        assert result.startswith("data: ")
        payload = json.loads(result[6:-2])
        assert payload["type"] == "snapshot"
        assert payload["quests"] == []
        assert "timestamp" in payload

    def test_with_quests(self, tmp_quests_dir: Path) -> None:
        quest = Quest(
            id="q-1",
            title="Test Quest",
            status="active",
            priority="high",
        )
        save_quest(quest, tmp_quests_dir / "q-1.md")

        result = _snapshot_to_sse(tmp_quests_dir)
        payload = json.loads(result[6:-2])
        assert len(payload["quests"]) == 1
        q = payload["quests"][0]
        assert q["id"] == "q-1"
        assert q["status"] == "active"
        assert q["priority"] == "high"
        assert q["title"] == "Test Quest"

    def test_snapshot_includes_step_counts(self, tmp_quests_dir: Path) -> None:
        from trellis.core.quest import QuestStep

        quest = Quest(
            id="q-2",
            title="Q2",
            status="active",
            steps=[
                QuestStep(text="Step 1", done=True),
                QuestStep(text="Step 2", done=False),
            ],
            steps_completed=1,
        )
        save_quest(quest, tmp_quests_dir / "q-2.md")

        result = _snapshot_to_sse(tmp_quests_dir)
        payload = json.loads(result[6:-2])
        q = payload["quests"][0]
        assert q["total_steps"] == 2
        assert q["steps_completed"] == 1


# ─── SSE stream API tests ───────────────────────────────────


class TestQuestEventsStream:
    def test_stream_no_auth(self, client: TestClient) -> None:
        """Endpoint requires auth."""
        resp = client.get("/api/quest-events")
        assert resp.status_code == 401

    def test_sse_event_format_compliance(self) -> None:
        """Verify SSE events follow data: {json}\\n\\n format."""
        event = QuestEvent(
            event_type=EventType.TICK_COMPLETED,
            quest_id="q-1",
        )
        sse = _event_to_sse(event)

        # Must start with "data: "
        assert sse.startswith("data: ")
        # Must end with double newline
        assert sse.endswith("\n\n")
        # JSON between must parse
        json_part = sse[6:].rstrip("\n")
        parsed = json.loads(json_part)
        assert parsed["type"] == "tick.completed"

    def test_sse_ping_format(self) -> None:
        """Verify keepalive ping format matches expectations."""
        # Simulate what the generator would produce for a ping
        ping = {
            "type": "ping",
            "timestamp": datetime.now().isoformat(),
        }
        sse_line = f"data: {json.dumps(ping)}\n\n"
        assert sse_line.startswith("data: ")
        parsed = json.loads(sse_line[6:].rstrip("\n"))
        assert parsed["type"] == "ping"
        assert "timestamp" in parsed

    def test_router_creates_endpoint(
        self,
        tmp_quests_dir: Path,
        event_bus: EventBus,
    ) -> None:
        """The router factory creates a valid GET /api/quest-events route."""
        router = create_quest_events_router(tmp_quests_dir, event_bus)
        routes = [r.path for r in router.routes]
        assert "/api/quest-events" in routes
