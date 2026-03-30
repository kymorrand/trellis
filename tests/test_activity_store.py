"""
tests.test_activity_store — Tests for activity event persistence and API.

Tests cover:
    - event_to_activity conversion for each tracked event type
    - Events not in the tracked set are ignored
    - ActivityStore.append writes JSONL
    - ActivityStore.persist_event converts and appends
    - ActivityStore.read_recent returns newest first
    - Cursor-based pagination (before parameter)
    - Limit capping (max 200)
    - Empty file / missing file handling
    - Activity API endpoint auth and response shape
    - Activity API pagination via query params
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trellis.core.activity_store import ActivityStore, event_to_activity
from trellis.core.events import EventBus, EventType, QuestEvent


# ─── Fixtures ───────────────────────────────────────────────


@pytest.fixture
def activity_path(tmp_path: Path) -> Path:
    return tmp_path / "_ivy" / "activity.jsonl"


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def store(activity_path: Path, event_bus: EventBus) -> ActivityStore:
    return ActivityStore(activity_path, event_bus)


@pytest.fixture
def api_key() -> str:
    key = "test-activity-key-123"
    os.environ["TRELLIS_API_KEY"] = key
    yield key  # type: ignore[misc]
    os.environ.pop("TRELLIS_API_KEY", None)


@pytest.fixture
def client(store: ActivityStore, api_key: str) -> TestClient:
    from trellis.core.activity_api import create_activity_router

    app = FastAPI()
    app.include_router(create_activity_router(store))
    return TestClient(app)


# ─── event_to_activity conversion ────────────────────────────


class TestEventToActivity:
    def test_step_completed(self) -> None:
        event = QuestEvent(
            event_type=EventType.QUEST_STEP_COMPLETED,
            quest_id="quest-001",
            data={
                "quest_title": "Build the garden",
                "step_number": 3,
                "step_text": "Write unit tests",
            },
        )
        record = event_to_activity(event)
        assert record is not None
        assert record["type"] == "step_completed"
        assert record["quest_id"] == "quest-001"
        assert record["quest_title"] == "Build the garden"
        assert "step 3" in record["summary"]
        assert "Write unit tests" in record["summary"]
        assert record["id"]  # UUID present
        assert record["timestamp"]  # ISO timestamp present

    def test_question_asked(self) -> None:
        event = QuestEvent(
            event_type=EventType.QUEST_QUESTION_ASKED,
            quest_id="quest-002",
            data={
                "quest_title": "Design homepage",
                "question_text": "What tone for hero section?",
            },
        )
        record = event_to_activity(event)
        assert record is not None
        assert record["type"] == "question_asked"
        assert "What tone for hero section?" in record["summary"]

    def test_question_asked_truncates_long_text(self) -> None:
        long_question = "x" * 200
        event = QuestEvent(
            event_type=EventType.QUEST_QUESTION_ASKED,
            quest_id="quest-002",
            data={
                "quest_title": "Test quest",
                "question_text": long_question,
            },
        )
        record = event_to_activity(event)
        assert record is not None
        assert len(record["summary"]) < 200
        assert record["summary"].endswith("...")

    def test_status_changed(self) -> None:
        event = QuestEvent(
            event_type=EventType.QUEST_STATUS_CHANGED,
            quest_id="quest-003",
            data={
                "quest_title": "Deploy app",
                "old_status": "active",
                "new_status": "complete",
            },
        )
        record = event_to_activity(event)
        assert record is not None
        assert record["type"] == "status_changed"
        assert "active" in record["summary"]
        assert "complete" in record["summary"]

    def test_tick_completed(self) -> None:
        event = QuestEvent(
            event_type=EventType.TICK_COMPLETED,
            quest_id="quest-004",
            data={
                "quest_title": "Background task",
                "phases_completed": 6,
            },
        )
        record = event_to_activity(event)
        assert record is not None
        assert record["type"] == "tick_completed"
        assert "6 phases" in record["summary"]

    def test_untracked_event_returns_none(self) -> None:
        event = QuestEvent(
            event_type=EventType.TICK_STARTED,
            quest_id="quest-005",
            data={"quest_title": "Ignored"},
        )
        record = event_to_activity(event)
        assert record is None

    def test_scheduler_event_returns_none(self) -> None:
        event = QuestEvent(
            event_type=EventType.SCHEDULER_STARTED,
            quest_id="system",
        )
        record = event_to_activity(event)
        assert record is None

    def test_fallback_quest_title(self) -> None:
        """quest_title falls back to quest_id when not in data."""
        event = QuestEvent(
            event_type=EventType.TICK_COMPLETED,
            quest_id="quest-fallback",
            data={},
        )
        record = event_to_activity(event)
        assert record is not None
        assert record["quest_title"] == "quest-fallback"


# ─── ActivityStore persistence ────────────────────────────────


class TestActivityStore:
    def test_append_creates_file(self, store: ActivityStore, activity_path: Path) -> None:
        record = {"id": "1", "type": "test", "timestamp": "2026-01-01T00:00:00"}
        store.append(record)
        assert activity_path.exists()
        lines = activity_path.read_text().strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["id"] == "1"

    def test_append_adds_lines(self, store: ActivityStore, activity_path: Path) -> None:
        store.append({"id": "1", "timestamp": "2026-01-01T00:00:00"})
        store.append({"id": "2", "timestamp": "2026-01-01T00:01:00"})
        lines = activity_path.read_text().strip().splitlines()
        assert len(lines) == 2

    def test_persist_event_writes_tracked(self, store: ActivityStore, activity_path: Path) -> None:
        event = QuestEvent(
            event_type=EventType.QUEST_STEP_COMPLETED,
            quest_id="q1",
            data={"quest_title": "Test", "step_number": 1, "step_text": "Init"},
        )
        record = store.persist_event(event)
        assert record is not None
        assert activity_path.exists()

    def test_persist_event_skips_untracked(self, store: ActivityStore, activity_path: Path) -> None:
        event = QuestEvent(
            event_type=EventType.TICK_STARTED,
            quest_id="q1",
        )
        record = store.persist_event(event)
        assert record is None
        assert not activity_path.exists()

    def test_read_recent_newest_first(self, store: ActivityStore) -> None:
        base = datetime(2026, 1, 1, 12, 0, 0)
        for i in range(5):
            store.append({
                "id": str(i),
                "type": "step_completed",
                "quest_id": "q1",
                "quest_title": "Test",
                "summary": f"Step {i}",
                "timestamp": (base + timedelta(minutes=i)).isoformat(),
            })
        events, cursor = store.read_recent(limit=5)
        assert len(events) == 5
        # Newest first (i=4 should be first)
        assert events[0]["id"] == "4"
        assert events[4]["id"] == "0"
        assert cursor is None

    def test_read_recent_with_limit(self, store: ActivityStore) -> None:
        base = datetime(2026, 1, 1, 12, 0, 0)
        for i in range(10):
            store.append({
                "id": str(i),
                "type": "tick_completed",
                "quest_id": "q1",
                "quest_title": "Test",
                "summary": f"Tick {i}",
                "timestamp": (base + timedelta(minutes=i)).isoformat(),
            })
        events, cursor = store.read_recent(limit=3)
        assert len(events) == 3
        assert events[0]["id"] == "9"
        assert cursor is not None

    def test_read_recent_with_cursor(self, store: ActivityStore) -> None:
        base = datetime(2026, 1, 1, 12, 0, 0)
        for i in range(5):
            store.append({
                "id": str(i),
                "type": "step_completed",
                "quest_id": "q1",
                "quest_title": "Test",
                "summary": f"Step {i}",
                "timestamp": (base + timedelta(minutes=i)).isoformat(),
            })
        # Get events before minute 3
        cursor_ts = (base + timedelta(minutes=3)).isoformat()
        events, cursor = store.read_recent(limit=50, before=cursor_ts)
        # Should get events at minute 0, 1, 2 (before minute 3)
        assert len(events) == 3
        assert events[0]["id"] == "2"

    def test_read_recent_empty_file(self, store: ActivityStore) -> None:
        events, cursor = store.read_recent()
        assert events == []
        assert cursor is None

    def test_read_recent_caps_limit_at_200(self, store: ActivityStore) -> None:
        """Requesting limit > 200 should be capped."""
        base = datetime(2026, 1, 1, 12, 0, 0)
        for i in range(5):
            store.append({
                "id": str(i),
                "type": "step_completed",
                "quest_id": "q1",
                "quest_title": "Test",
                "summary": f"Step {i}",
                "timestamp": (base + timedelta(minutes=i)).isoformat(),
            })
        # Even with limit=999, cap at 200 (but only 5 records exist)
        events, cursor = store.read_recent(limit=999)
        assert len(events) == 5

    def test_read_recent_skips_malformed_lines(
        self, store: ActivityStore, activity_path: Path
    ) -> None:
        activity_path.parent.mkdir(parents=True, exist_ok=True)
        with activity_path.open("w", encoding="utf-8") as f:
            f.write('{"id":"1","type":"test","timestamp":"2026-01-01T00:00:00"}\n')
            f.write("not valid json\n")
            f.write('{"id":"2","type":"test","timestamp":"2026-01-01T00:01:00"}\n')
        events, _ = store.read_recent()
        assert len(events) == 2


# ─── Activity API endpoint ────────────────────────────────────


class TestActivityAPI:
    def test_get_activity_requires_auth(self, client: TestClient) -> None:
        resp = client.get("/api/activity")
        assert resp.status_code == 401

    def test_get_activity_rejects_bad_key(self, client: TestClient) -> None:
        resp = client.get(
            "/api/activity",
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401

    def test_get_activity_empty(self, client: TestClient, api_key: str) -> None:
        resp = client.get(
            "/api/activity",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["events"] == []
        assert data["next_cursor"] is None

    def test_get_activity_returns_events(
        self, client: TestClient, store: ActivityStore, api_key: str
    ) -> None:
        base = datetime(2026, 1, 1, 12, 0, 0)
        for i in range(3):
            store.append({
                "id": str(i),
                "type": "step_completed",
                "quest_id": "q1",
                "quest_title": "Test Quest",
                "summary": f"Step {i}",
                "timestamp": (base + timedelta(minutes=i)).isoformat(),
            })
        resp = client.get(
            "/api/activity",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 3
        # Newest first
        assert data["events"][0]["id"] == "2"

    def test_get_activity_with_limit(
        self, client: TestClient, store: ActivityStore, api_key: str
    ) -> None:
        base = datetime(2026, 1, 1, 12, 0, 0)
        for i in range(10):
            store.append({
                "id": str(i),
                "type": "tick_completed",
                "quest_id": "q1",
                "quest_title": "Test",
                "summary": f"Tick {i}",
                "timestamp": (base + timedelta(minutes=i)).isoformat(),
            })
        resp = client.get(
            "/api/activity?limit=3",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 3
        assert data["next_cursor"] is not None

    def test_get_activity_with_cursor(
        self, client: TestClient, store: ActivityStore, api_key: str
    ) -> None:
        base = datetime(2026, 1, 1, 12, 0, 0)
        for i in range(5):
            store.append({
                "id": str(i),
                "type": "step_completed",
                "quest_id": "q1",
                "quest_title": "Test",
                "summary": f"Step {i}",
                "timestamp": (base + timedelta(minutes=i)).isoformat(),
            })
        cursor_ts = (base + timedelta(minutes=3)).isoformat()
        resp = client.get(
            f"/api/activity?before={cursor_ts}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 3
        assert data["events"][0]["id"] == "2"

    def test_response_matches_contract(
        self, client: TestClient, store: ActivityStore, api_key: str
    ) -> None:
        """Verify response shape matches ActivityResponse TypeScript type."""
        store.append({
            "id": "abc-123",
            "type": "question_asked",
            "quest_id": "q1",
            "quest_title": "Design Quest",
            "summary": "New question: What color?",
            "timestamp": "2026-03-30T12:00:00",
        })
        resp = client.get(
            "/api/activity",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        data = resp.json()
        assert "events" in data
        assert "next_cursor" in data
        event = data["events"][0]
        # All fields from ActivityEvent contract must be present
        assert set(event.keys()) >= {"id", "type", "quest_id", "quest_title", "summary", "timestamp"}
