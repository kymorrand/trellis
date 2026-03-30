"""
tests.core.test_approvals — Tests for approval CRUD and API.

Tests cover:
    - ApprovalStore create, get, list, approve, reject
    - API endpoints: list pending, approve, reject
    - Event emission on approve/reject
    - Auth on all endpoints
    - Edge cases: not found, invalid action
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trellis.core.approval_api import create_approval_router
from trellis.core.approvals import Approval, ApprovalStore
from trellis.core.events import EventBus, EventType

# ─── ApprovalStore unit tests ────────────────────────────────


@pytest.fixture
def approvals_dir(tmp_path: Path) -> Path:
    d = tmp_path / "approvals"
    d.mkdir()
    return d


@pytest.fixture
def store(approvals_dir: Path) -> ApprovalStore:
    return ApprovalStore(approvals_dir)


class TestApprovalStore:
    def test_create(self, store: ApprovalStore) -> None:
        a = store.create(
            quest_id="q-1",
            quest_name="Quest One",
            title="Publish article",
            description="Publish research findings to garden",
        )
        assert a.id.startswith("APR-")
        assert a.status == "pending"
        assert a.quest_id == "q-1"

    def test_get(self, store: ApprovalStore) -> None:
        created = store.create("q-1", "Quest", "Title", "Desc")
        loaded = store.get(created.id)
        assert loaded is not None
        assert loaded.id == created.id
        assert loaded.title == "Title"

    def test_get_not_found(self, store: ApprovalStore) -> None:
        assert store.get("nonexistent") is None

    def test_list_pending(self, store: ApprovalStore) -> None:
        store.create("q-1", "Q1", "A", "Desc A")
        store.create("q-2", "Q2", "B", "Desc B")
        store.create("q-1", "Q1", "C", "Desc C")

        pending = store.list_pending()
        assert len(pending) == 3

    def test_list_pending_excludes_resolved(self, store: ApprovalStore) -> None:
        a1 = store.create("q-1", "Q1", "A", "Desc A")
        store.create("q-2", "Q2", "B", "Desc B")
        store.approve(a1.id)

        pending = store.list_pending()
        assert len(pending) == 1

    def test_approve(self, store: ApprovalStore) -> None:
        a = store.create("q-1", "Q1", "Title", "Desc")
        result = store.approve(a.id)
        assert result is not None
        assert result.status == "approved"
        assert result.resolved_at is not None

    def test_reject(self, store: ApprovalStore) -> None:
        a = store.create("q-1", "Q1", "Title", "Desc")
        result = store.reject(a.id, reason="Too expensive")
        assert result is not None
        assert result.status == "rejected"
        assert result.reject_reason == "Too expensive"

    def test_approve_not_found(self, store: ApprovalStore) -> None:
        assert store.approve("nonexistent") is None

    def test_reject_not_found(self, store: ApprovalStore) -> None:
        assert store.reject("nonexistent") is None

    def test_cost_estimate(self, store: ApprovalStore) -> None:
        a = store.create("q-1", "Q1", "T", "D", cost_estimate="$50")
        loaded = store.get(a.id)
        assert loaded is not None
        assert loaded.cost_estimate == "$50"

    def test_list_all(self, store: ApprovalStore) -> None:
        a1 = store.create("q-1", "Q1", "A", "DA")
        store.create("q-2", "Q2", "B", "DB")
        store.approve(a1.id)

        all_approvals = store.list_all()
        assert len(all_approvals) == 2

    def test_persistence(self, approvals_dir: Path) -> None:
        """Verify data persists across store instances."""
        store1 = ApprovalStore(approvals_dir)
        a = store1.create("q-1", "Q1", "Title", "Desc")

        store2 = ApprovalStore(approvals_dir)
        loaded = store2.get(a.id)
        assert loaded is not None
        assert loaded.title == "Title"


# ─── API tests ──────────────────────────────────────────────


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def api_key() -> str:
    key = "test-api-key-456"
    os.environ["TRELLIS_API_KEY"] = key
    yield key
    os.environ.pop("TRELLIS_API_KEY", None)


@pytest.fixture
def client(
    approvals_dir: Path,
    event_bus: EventBus,
    api_key: str,
) -> TestClient:
    app = FastAPI()
    app.include_router(create_approval_router(approvals_dir, event_bus))
    return TestClient(app)


def _auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture
def seeded_approvals(approvals_dir: Path) -> list[Approval]:
    """Pre-seed some approvals for API tests."""
    store = ApprovalStore(approvals_dir)
    a1 = store.create("q-1", "Quest One", "Publish article", "Publish to garden")
    a2 = store.create("q-2", "Quest Two", "Spend $100", "Cloud API budget", cost_estimate="$100")
    return [a1, a2]


class TestApprovalApiList:
    def test_list_pending(
        self,
        client: TestClient,
        api_key: str,
        seeded_approvals: list[Approval],
    ) -> None:
        resp = client.get("/api/approvals", headers=_auth(api_key))
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2

    def test_list_empty(
        self,
        client: TestClient,
        api_key: str,
    ) -> None:
        resp = client.get("/api/approvals", headers=_auth(api_key))
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_list_no_auth(self, client: TestClient) -> None:
        resp = client.get("/api/approvals")
        assert resp.status_code == 401


class TestApprovalApiAction:
    def test_approve(
        self,
        client: TestClient,
        api_key: str,
        seeded_approvals: list[Approval],
    ) -> None:
        aid = seeded_approvals[0].id
        resp = client.post(
            f"/api/approvals/{aid}",
            json={"action": "approve"},
            headers=_auth(api_key),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_reject(
        self,
        client: TestClient,
        api_key: str,
        seeded_approvals: list[Approval],
    ) -> None:
        aid = seeded_approvals[0].id
        resp = client.post(
            f"/api/approvals/{aid}",
            json={"action": "reject", "reason": "Too risky"},
            headers=_auth(api_key),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "rejected"
        assert data["reject_reason"] == "Too risky"

    def test_approve_emits_event(
        self,
        client: TestClient,
        api_key: str,
        seeded_approvals: list[Approval],
        event_bus: EventBus,
    ) -> None:
        queue = event_bus.subscribe()
        aid = seeded_approvals[0].id
        client.post(
            f"/api/approvals/{aid}",
            json={"action": "approve"},
            headers=_auth(api_key),
        )
        event = asyncio.run(asyncio.wait_for(queue.get(), timeout=2.0))
        assert event.event_type == EventType.QUEST_STATUS_CHANGED
        assert event.data["approval_id"] == aid
        assert event.data["action"] == "approve"

    def test_reject_emits_event(
        self,
        client: TestClient,
        api_key: str,
        seeded_approvals: list[Approval],
        event_bus: EventBus,
    ) -> None:
        queue = event_bus.subscribe()
        aid = seeded_approvals[0].id
        client.post(
            f"/api/approvals/{aid}",
            json={"action": "reject", "reason": "nope"},
            headers=_auth(api_key),
        )
        event = asyncio.run(asyncio.wait_for(queue.get(), timeout=2.0))
        assert event.data["action"] == "reject"

    def test_not_found(
        self,
        client: TestClient,
        api_key: str,
    ) -> None:
        resp = client.post(
            "/api/approvals/nonexistent",
            json={"action": "approve"},
            headers=_auth(api_key),
        )
        assert resp.status_code == 404

    def test_invalid_action(
        self,
        client: TestClient,
        api_key: str,
        seeded_approvals: list[Approval],
    ) -> None:
        aid = seeded_approvals[0].id
        resp = client.post(
            f"/api/approvals/{aid}",
            json={"action": "delete"},
            headers=_auth(api_key),
        )
        assert resp.status_code == 400

    def test_no_auth(
        self,
        client: TestClient,
        seeded_approvals: list[Approval],
    ) -> None:
        aid = seeded_approvals[0].id
        resp = client.post(
            f"/api/approvals/{aid}",
            json={"action": "approve"},
        )
        assert resp.status_code == 401

    def test_approved_no_longer_in_pending_list(
        self,
        client: TestClient,
        api_key: str,
        seeded_approvals: list[Approval],
    ) -> None:
        aid = seeded_approvals[0].id
        client.post(
            f"/api/approvals/{aid}",
            json={"action": "approve"},
            headers=_auth(api_key),
        )
        resp = client.get("/api/approvals", headers=_auth(api_key))
        assert resp.json()["count"] == 1
