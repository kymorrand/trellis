"""
tests.test_admin_api — Tests for admin REST API endpoints.

Tests cover:
    - Quest status changes: pause, resume, abandon with state validation
    - Tick config updates: interval and window changes with validation
    - Usage endpoint: aggregated budget data from quest files
    - Tick history: filtered tick events from activity store
    - Auth: all endpoints require valid API key
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trellis.core.activity_store import ActivityStore
from trellis.core.admin_api import create_admin_router
from trellis.core.quest import Quest, QuestStep, save_quest

# ─── Constants ───────────────────────────────────────────────

TEST_API_KEY = "test-admin-key-12345"


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_API_KEY}"}


def _bad_auth() -> dict[str, str]:
    return {"Authorization": "Bearer wrong-key"}


# ─── Fixtures ────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRELLIS_API_KEY", TEST_API_KEY)


@pytest.fixture
def quests_dir(tmp_path: Path) -> Path:
    qdir = tmp_path / "quests"
    qdir.mkdir()
    return qdir


@pytest.fixture
def activity_path(tmp_path: Path) -> Path:
    return tmp_path / "_ivy" / "activity.jsonl"


@pytest.fixture
def activity_store(activity_path: Path) -> ActivityStore:
    return ActivityStore(activity_path, event_bus=None)


@pytest.fixture
def app(quests_dir: Path, activity_store: ActivityStore) -> FastAPI:
    app = FastAPI()
    app.include_router(create_admin_router(quests_dir, activity_store))
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def populated_quests_dir(quests_dir: Path) -> Path:
    """Create quests with various statuses and budgets."""
    save_quest(
        Quest(
            id="quest-active",
            title="Active Quest",
            status="active",
            budget_claude=50,
            budget_spent_claude=12,
            tick_interval="5m",
            tick_window="8am-11pm",
            steps=[QuestStep(text="Step 1", done=True), QuestStep(text="Step 2")],
        ),
        quests_dir / "quest-active.md",
    )
    save_quest(
        Quest(
            id="quest-paused",
            title="Paused Quest",
            status="paused",
            budget_claude=100,
            budget_spent_claude=30,
            tick_interval="10m",
            tick_window="8am-6pm",
        ),
        quests_dir / "quest-paused.md",
    )
    save_quest(
        Quest(
            id="quest-draft",
            title="Draft Quest",
            status="draft",
            budget_claude=50,
            budget_spent_claude=0,
        ),
        quests_dir / "quest-draft.md",
    )
    return quests_dir


@pytest.fixture
def populated_client(
    populated_quests_dir: Path, activity_store: ActivityStore
) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_admin_router(populated_quests_dir, activity_store)
    )
    return TestClient(app)


# ─── Auth tests ──────────────────────────────────────────────


class TestAdminAuth:
    """All admin endpoints require valid API key."""

    def test_status_no_auth(self, populated_client: TestClient) -> None:
        resp = populated_client.patch(
            "/api/quests/quest-active/status",
            json={"action": "pause"},
        )
        assert resp.status_code == 401

    def test_status_bad_auth(self, populated_client: TestClient) -> None:
        resp = populated_client.patch(
            "/api/quests/quest-active/status",
            json={"action": "pause"},
            headers=_bad_auth(),
        )
        assert resp.status_code == 401

    def test_tick_config_no_auth(self, populated_client: TestClient) -> None:
        resp = populated_client.patch(
            "/api/quests/quest-active/tick-config",
            json={"tick_interval": "10m"},
        )
        assert resp.status_code == 401

    def test_usage_no_auth(self, populated_client: TestClient) -> None:
        resp = populated_client.get("/api/admin/usage")
        assert resp.status_code == 401

    def test_ticks_no_auth(self, populated_client: TestClient) -> None:
        resp = populated_client.get("/api/admin/ticks")
        assert resp.status_code == 401

    def test_usage_bad_auth(self, populated_client: TestClient) -> None:
        resp = populated_client.get(
            "/api/admin/usage", headers=_bad_auth()
        )
        assert resp.status_code == 401


# ─── PATCH /api/quests/{quest_id}/status ─────────────────────


class TestQuestStatus:
    def test_pause_active_quest(self, populated_client: TestClient) -> None:
        resp = populated_client.patch(
            "/api/quests/quest-active/status",
            json={"action": "pause"},
            headers=_auth(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["quest_id"] == "quest-active"
        assert data["status"] == "paused"
        assert "updated_at" in data

    def test_resume_paused_quest(self, populated_client: TestClient) -> None:
        resp = populated_client.patch(
            "/api/quests/quest-paused/status",
            json={"action": "resume"},
            headers=_auth(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"

    def test_abandon_active_quest(self, populated_client: TestClient) -> None:
        resp = populated_client.patch(
            "/api/quests/quest-active/status",
            json={"action": "abandon"},
            headers=_auth(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "abandoned"

    def test_abandon_draft_quest(self, populated_client: TestClient) -> None:
        resp = populated_client.patch(
            "/api/quests/quest-draft/status",
            json={"action": "abandon"},
            headers=_auth(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "abandoned"

    def test_pause_persists_to_disk(
        self, populated_quests_dir: Path, populated_client: TestClient
    ) -> None:
        populated_client.patch(
            "/api/quests/quest-active/status",
            json={"action": "pause"},
            headers=_auth(),
        )
        from trellis.core.quest import load_quest

        quest = load_quest(populated_quests_dir / "quest-active.md")
        assert quest.status == "paused"

    def test_cannot_resume_active_quest(
        self, populated_client: TestClient
    ) -> None:
        resp = populated_client.patch(
            "/api/quests/quest-active/status",
            json={"action": "resume"},
            headers=_auth(),
        )
        assert resp.status_code == 400
        assert "Cannot resume" in resp.json()["detail"]

    def test_cannot_pause_draft_quest(
        self, populated_client: TestClient
    ) -> None:
        resp = populated_client.patch(
            "/api/quests/quest-draft/status",
            json={"action": "pause"},
            headers=_auth(),
        )
        assert resp.status_code == 400
        assert "Cannot pause" in resp.json()["detail"]

    def test_cannot_abandon_already_abandoned(
        self, populated_client: TestClient
    ) -> None:
        # First abandon
        populated_client.patch(
            "/api/quests/quest-active/status",
            json={"action": "abandon"},
            headers=_auth(),
        )
        # Try again
        resp = populated_client.patch(
            "/api/quests/quest-active/status",
            json={"action": "abandon"},
            headers=_auth(),
        )
        assert resp.status_code == 400
        assert "Cannot abandon" in resp.json()["detail"]

    def test_quest_not_found(self, populated_client: TestClient) -> None:
        resp = populated_client.patch(
            "/api/quests/nonexistent/status",
            json={"action": "pause"},
            headers=_auth(),
        )
        assert resp.status_code == 404

    def test_invalid_action(self, populated_client: TestClient) -> None:
        resp = populated_client.patch(
            "/api/quests/quest-active/status",
            json={"action": "delete"},
            headers=_auth(),
        )
        assert resp.status_code == 422  # Pydantic validation


# ─── PATCH /api/quests/{quest_id}/tick-config ────────────────


class TestTickConfig:
    def test_update_interval(self, populated_client: TestClient) -> None:
        resp = populated_client.patch(
            "/api/quests/quest-active/tick-config",
            json={"tick_interval": "10m"},
            headers=_auth(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["quest_id"] == "quest-active"
        assert data["tick_interval"] == "10m"
        assert data["tick_window"] == "8am-11pm"  # unchanged
        assert "updated_at" in data

    def test_update_window(self, populated_client: TestClient) -> None:
        resp = populated_client.patch(
            "/api/quests/quest-active/tick-config",
            json={"tick_window": "8am-6pm"},
            headers=_auth(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tick_window"] == "8am-6pm"
        assert data["tick_interval"] == "5m"  # unchanged

    def test_update_both(self, populated_client: TestClient) -> None:
        resp = populated_client.patch(
            "/api/quests/quest-active/tick-config",
            json={"tick_interval": "30m", "tick_window": "24h"},
            headers=_auth(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tick_interval"] == "30m"
        assert data["tick_window"] == "24h"

    def test_persists_to_disk(
        self, populated_quests_dir: Path, populated_client: TestClient
    ) -> None:
        populated_client.patch(
            "/api/quests/quest-active/tick-config",
            json={"tick_interval": "15m"},
            headers=_auth(),
        )
        from trellis.core.quest import load_quest

        quest = load_quest(populated_quests_dir / "quest-active.md")
        assert quest.tick_interval == "15m"

    def test_invalid_interval(self, populated_client: TestClient) -> None:
        resp = populated_client.patch(
            "/api/quests/quest-active/tick-config",
            json={"tick_interval": "2m"},
            headers=_auth(),
        )
        assert resp.status_code == 400
        assert "Invalid tick_interval" in resp.json()["detail"]

    def test_invalid_window(self, populated_client: TestClient) -> None:
        resp = populated_client.patch(
            "/api/quests/quest-active/tick-config",
            json={"tick_window": "midnight"},
            headers=_auth(),
        )
        assert resp.status_code == 400
        assert "Invalid tick_window" in resp.json()["detail"]

    def test_empty_body(self, populated_client: TestClient) -> None:
        resp = populated_client.patch(
            "/api/quests/quest-active/tick-config",
            json={},
            headers=_auth(),
        )
        assert resp.status_code == 400
        assert "Must provide at least one" in resp.json()["detail"]

    def test_quest_not_found(self, populated_client: TestClient) -> None:
        resp = populated_client.patch(
            "/api/quests/nonexistent/tick-config",
            json={"tick_interval": "10m"},
            headers=_auth(),
        )
        assert resp.status_code == 404


# ─── GET /api/admin/usage ────────────────────────────────────


class TestUsage:
    def test_usage_aggregates(self, populated_client: TestClient) -> None:
        resp = populated_client.get("/api/admin/usage", headers=_auth())
        assert resp.status_code == 200
        data = resp.json()
        # 3 quests: active(50/12), paused(100/30), draft(50/0)
        assert data["total_budget"] == 200.0
        assert data["total_spent"] == 42.0
        assert len(data["by_quest"]) == 3

    def test_usage_per_quest_fields(
        self, populated_client: TestClient
    ) -> None:
        resp = populated_client.get("/api/admin/usage", headers=_auth())
        data = resp.json()
        active_quest = next(
            q for q in data["by_quest"] if q["quest_id"] == "quest-active"
        )
        assert active_quest["title"] == "Active Quest"
        assert active_quest["spent"] == 12.0
        assert active_quest["budget"] == 50.0

    def test_usage_empty_dir(self, client: TestClient) -> None:
        resp = client.get("/api/admin/usage", headers=_auth())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_spent"] == 0.0
        assert data["total_budget"] == 0.0
        assert data["by_quest"] == []


# ─── GET /api/admin/ticks ────────────────────────────────────


class TestTickHistory:
    def _seed_ticks(
        self, store: ActivityStore, count: int = 5
    ) -> None:
        """Write tick events (and some non-tick events) to the store."""
        base = datetime(2026, 3, 30, 12, 0, 0)
        for i in range(count):
            store.append({
                "id": f"tick-{i}",
                "type": "tick_completed",
                "quest_id": "quest-active",
                "quest_title": "Active Quest",
                "tick_number": i + 1,
                "summary": f"Tick {i + 1} completed",
                "timestamp": (base + timedelta(minutes=i)).isoformat(),
                "duration_ms": 4500,
            })
        # Add some non-tick events
        store.append({
            "id": "step-1",
            "type": "step_completed",
            "quest_id": "quest-active",
            "quest_title": "Active Quest",
            "summary": "Step 1 done",
            "timestamp": (base + timedelta(minutes=count)).isoformat(),
        })

    def test_returns_tick_events(
        self, populated_client: TestClient, activity_store: ActivityStore
    ) -> None:
        self._seed_ticks(activity_store)
        resp = populated_client.get("/api/admin/ticks", headers=_auth())
        assert resp.status_code == 200
        data = resp.json()
        # Should only have tick events, not step_completed
        assert len(data["ticks"]) == 5
        for tick in data["ticks"]:
            assert tick["status"] == "completed"
            assert tick["quest_id"] == "quest-active"

    def test_filters_non_tick_events(
        self, populated_client: TestClient, activity_store: ActivityStore
    ) -> None:
        self._seed_ticks(activity_store, count=2)
        resp = populated_client.get("/api/admin/ticks", headers=_auth())
        data = resp.json()
        types = [t["status"] for t in data["ticks"]]
        # No step_completed events should appear
        assert all(s in ("completed", "failed", "skipped") for s in types)

    def test_tick_entry_fields(
        self, populated_client: TestClient, activity_store: ActivityStore
    ) -> None:
        self._seed_ticks(activity_store, count=1)
        resp = populated_client.get("/api/admin/ticks", headers=_auth())
        data = resp.json()
        tick = data["ticks"][0]
        assert tick["quest_id"] == "quest-active"
        assert tick["quest_title"] == "Active Quest"
        assert tick["tick_number"] == 1
        assert tick["status"] == "completed"
        assert tick["duration_ms"] == 4500
        assert tick["timestamp"]

    def test_respects_limit(
        self, populated_client: TestClient, activity_store: ActivityStore
    ) -> None:
        self._seed_ticks(activity_store, count=10)
        resp = populated_client.get(
            "/api/admin/ticks?limit=3", headers=_auth()
        )
        data = resp.json()
        assert len(data["ticks"]) == 3
        assert data["next_cursor"] is not None

    def test_empty_store(self, populated_client: TestClient) -> None:
        resp = populated_client.get("/api/admin/ticks", headers=_auth())
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticks"] == []
        assert data["next_cursor"] is None

    def test_failed_tick_status(
        self, populated_client: TestClient, activity_store: ActivityStore
    ) -> None:
        activity_store.append({
            "id": "fail-1",
            "type": "tick_failed",
            "quest_id": "quest-active",
            "quest_title": "Active Quest",
            "tick_number": 1,
            "summary": "Tick failed",
            "timestamp": "2026-03-30T12:00:00",
        })
        resp = populated_client.get("/api/admin/ticks", headers=_auth())
        data = resp.json()
        assert len(data["ticks"]) == 1
        assert data["ticks"][0]["status"] == "failed"

    def test_skipped_tick_status(
        self, populated_client: TestClient, activity_store: ActivityStore
    ) -> None:
        activity_store.append({
            "id": "skip-1",
            "type": "tick_skipped",
            "quest_id": "quest-active",
            "quest_title": "Active Quest",
            "tick_number": 1,
            "summary": "Tick skipped",
            "timestamp": "2026-03-30T12:00:00",
        })
        resp = populated_client.get("/api/admin/ticks", headers=_auth())
        data = resp.json()
        assert len(data["ticks"]) == 1
        assert data["ticks"][0]["status"] == "skipped"
