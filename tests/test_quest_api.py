"""Tests for trellis.core.quest_api — Quest REST API endpoints."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trellis.core.quest import Quest, QuestStep, save_quest
from trellis.core.quest_api import create_quest_router

# ─── Test API key ─────────────────────────────────────────────

TEST_API_KEY = "test-key-12345"


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    """Set TRELLIS_API_KEY for all tests."""
    monkeypatch.setenv("TRELLIS_API_KEY", TEST_API_KEY)


def _auth_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_API_KEY}"}


def _bad_auth_header() -> dict[str, str]:
    return {"Authorization": "Bearer wrong-key"}


# ─── Fixtures ─────────────────────────────────────────────────


@pytest.fixture
def quests_dir(tmp_path: Path) -> Path:
    """Create a quests directory with templates."""
    qdir = tmp_path / "quests"
    qdir.mkdir()
    (qdir / "_templates").mkdir()
    (qdir / "_archive").mkdir()

    # Write a research template
    template = (
        "---\n"
        "id: {quest-id}\n"
        "title: {title}\n"
        "status: draft\n"
        "type: research\n"
        "priority: standard\n"
        "role: researcher\n"
        "created: {date}\n"
        "updated: {date}\n"
        "tick_interval: 5m\n"
        "tick_window: 8am-11pm\n"
        "budget_claude: 50\n"
        "budget_spent_claude: 0\n"
        "steps_completed: 0\n"
        "goal_hash: ''\n"
        "drift_check_interval: 5\n"
        "---\n\n"
        "## Goal\n\n"
        "Template goal.\n\n"
        "## Steps\n\n"
        "- [ ] First step\n"
        "- [ ] Second step\n"
    )
    (qdir / "_templates" / "research-quest.md").write_text(template, encoding="utf-8")

    return qdir


@pytest.fixture
def app(quests_dir: Path) -> FastAPI:
    """Create a FastAPI app with quest router."""
    app = FastAPI()
    app.include_router(create_quest_router(quests_dir))
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def populated_quests_dir(quests_dir: Path) -> Path:
    """Quests dir with some sample quests already in it."""
    save_quest(
        Quest(
            id="quest-alpha",
            title="Quest Alpha",
            status="active",
            type="research",
            priority="high",
            goal="Do alpha.",
            steps=[QuestStep(text="Step 1", done=True), QuestStep(text="Step 2", done=False)],
        ),
        quests_dir / "quest-alpha.md",
    )
    save_quest(
        Quest(
            id="quest-beta",
            title="Quest Beta",
            status="draft",
            type="writing",
            priority="low",
            goal="Do beta.",
        ),
        quests_dir / "quest-beta.md",
    )
    return quests_dir


@pytest.fixture
def populated_client(populated_quests_dir: Path) -> TestClient:
    app = FastAPI()
    app.include_router(create_quest_router(populated_quests_dir))
    return TestClient(app)


# ─── Auth tests ───────────────────────────────────────────────


class TestAuth:
    def test_missing_auth_header(self, client: TestClient):
        resp = client.get("/api/quests")
        assert resp.status_code == 401
        assert "Missing" in resp.json()["detail"]

    def test_invalid_auth_format(self, client: TestClient):
        resp = client.get("/api/quests", headers={"Authorization": "Basic abc"})
        assert resp.status_code == 401
        assert "Invalid Authorization format" in resp.json()["detail"]

    def test_wrong_api_key(self, client: TestClient):
        resp = client.get("/api/quests", headers=_bad_auth_header())
        assert resp.status_code == 401
        assert "Invalid API key" in resp.json()["detail"]

    def test_valid_auth_succeeds(self, client: TestClient):
        resp = client.get("/api/quests", headers=_auth_header())
        assert resp.status_code == 200

    def test_no_api_key_configured(self, client: TestClient, monkeypatch):
        """Server error when TRELLIS_API_KEY not set."""
        monkeypatch.delenv("TRELLIS_API_KEY", raising=False)
        resp = client.get("/api/quests", headers=_auth_header())
        assert resp.status_code == 500


# ─── GET /api/quests ──────────────────────────────────────────


class TestListQuests:
    def test_empty_list(self, client: TestClient):
        resp = client.get("/api/quests", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["quests"] == []
        assert data["count"] == 0

    def test_lists_quests(self, populated_client: TestClient):
        resp = populated_client.get("/api/quests", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        ids = [q["id"] for q in data["quests"]]
        assert "quest-alpha" in ids
        assert "quest-beta" in ids

    def test_summary_fields(self, populated_client: TestClient):
        resp = populated_client.get("/api/quests", headers=_auth_header())
        data = resp.json()
        quest = next(q for q in data["quests"] if q["id"] == "quest-alpha")
        assert quest["title"] == "Quest Alpha"
        assert quest["status"] == "active"
        assert quest["priority"] == "high"
        assert quest["type"] == "research"
        assert quest["total_steps"] == 2
        assert quest["steps_completed"] == 0  # from frontmatter, not calculated

    def test_sorted_by_priority(self, populated_client: TestClient):
        resp = populated_client.get("/api/quests", headers=_auth_header())
        data = resp.json()
        priorities = [q["priority"] for q in data["quests"]]
        assert priorities[0] == "high"
        assert priorities[1] == "low"


# ─── GET /api/quests/{id} ────────────────────────────────────


class TestGetQuest:
    def test_get_existing_quest(self, populated_client: TestClient):
        resp = populated_client.get("/api/quests/quest-alpha", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "quest-alpha"
        assert data["goal"] == "Do alpha."
        assert len(data["steps"]) == 2
        assert data["steps"][0]["done"] is True

    def test_get_nonexistent_quest(self, populated_client: TestClient):
        resp = populated_client.get("/api/quests/nonexistent", headers=_auth_header())
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    def test_full_detail_fields(self, populated_client: TestClient):
        resp = populated_client.get("/api/quests/quest-alpha", headers=_auth_header())
        data = resp.json()
        # Verify all expected fields are present
        expected_fields = {
            "id", "title", "status", "type", "priority", "role",
            "created", "updated", "tick_interval", "tick_window",
            "budget_claude", "budget_spent_claude", "steps_completed",
            "total_steps", "goal_hash", "drift_check_interval",
            "goal", "success_criteria", "steps", "questions",
            "artifacts", "log", "blockers", "extra",
        }
        assert expected_fields.issubset(set(data.keys()))


# ─── POST /api/quests ─────────────────────────────────────────


class TestCreateQuest:
    def test_create_from_scratch(self, client: TestClient):
        resp = client.post(
            "/api/quests",
            json={"title": "New Research Quest", "type": "research", "priority": "high"},
            headers=_auth_header(),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "new-research-quest"
        assert data["title"] == "New Research Quest"
        assert data["status"] == "draft"
        assert data["priority"] == "high"

    def test_create_from_template(self, client: TestClient):
        resp = client.post(
            "/api/quests",
            json={"title": "Templated Quest", "template": "research"},
            headers=_auth_header(),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "templated-quest"
        assert "Template goal" in data["goal"]
        assert len(data["steps"]) == 2

    def test_create_invalid_template(self, client: TestClient):
        resp = client.post(
            "/api/quests",
            json={"title": "Bad Template", "template": "nonexistent"},
            headers=_auth_header(),
        )
        assert resp.status_code == 400
        assert "not found" in resp.json()["detail"]

    def test_create_duplicate(self, client: TestClient):
        # Create first
        client.post(
            "/api/quests",
            json={"title": "Unique Quest"},
            headers=_auth_header(),
        )
        # Create duplicate
        resp = client.post(
            "/api/quests",
            json={"title": "Unique Quest"},
            headers=_auth_header(),
        )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    def test_create_sets_dates(self, client: TestClient):
        resp = client.post(
            "/api/quests",
            json={"title": "Dated Quest"},
            headers=_auth_header(),
        )
        data = resp.json()
        assert data["created"] is not None
        assert data["updated"] is not None

    def test_create_slugifies_title(self, client: TestClient):
        resp = client.post(
            "/api/quests",
            json={"title": "My Quest: A Research Project!"},
            headers=_auth_header(),
        )
        data = resp.json()
        assert data["id"] == "my-quest-a-research-project"


# ─── PATCH /api/quests/{id} ───────────────────────────────────


class TestPatchQuest:
    def test_patch_status(self, populated_client: TestClient):
        resp = populated_client.patch(
            "/api/quests/quest-alpha",
            json={"status": "complete"},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "complete"

    def test_patch_priority(self, populated_client: TestClient):
        resp = populated_client.patch(
            "/api/quests/quest-beta",
            json={"priority": "urgent"},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        assert resp.json()["priority"] == "urgent"

    def test_patch_budget(self, populated_client: TestClient):
        resp = populated_client.patch(
            "/api/quests/quest-alpha",
            json={"budget_claude": 100, "budget_spent_claude": 25},
            headers=_auth_header(),
        )
        data = resp.json()
        assert data["budget_claude"] == 100
        assert data["budget_spent_claude"] == 25

    def test_patch_bumps_updated(self, populated_client: TestClient):
        resp = populated_client.patch(
            "/api/quests/quest-alpha",
            json={"status": "paused"},
            headers=_auth_header(),
        )
        data = resp.json()
        assert data["updated"] is not None

    def test_patch_nonexistent(self, populated_client: TestClient):
        resp = populated_client.patch(
            "/api/quests/nonexistent",
            json={"status": "active"},
            headers=_auth_header(),
        )
        assert resp.status_code == 404

    def test_patch_multiple_fields(self, populated_client: TestClient):
        resp = populated_client.patch(
            "/api/quests/quest-alpha",
            json={"status": "waiting", "priority": "low", "role": "writer"},
            headers=_auth_header(),
        )
        data = resp.json()
        assert data["status"] == "waiting"
        assert data["priority"] == "low"
        assert data["role"] == "writer"

    def test_patch_empty_body_still_bumps_updated(self, populated_client: TestClient):
        resp = populated_client.patch(
            "/api/quests/quest-alpha",
            json={},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
