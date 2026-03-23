"""Tests for trellis.core.inbox -- InboxProcessor, storage, and API endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from trellis.core.inbox import (
    InboxItem,
    InboxProcessor,
    RoutingProposal,
    _confidence_tier,
    _deserialize_item,
    _serialize_item,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """Minimal vault structure for inbox tests."""
    (tmp_path / "_ivy" / "inbox" / "drops").mkdir(parents=True)
    (tmp_path / "_ivy" / "inbox" / "items").mkdir(parents=True)
    (tmp_path / "_ivy" / "inbox" / "archived").mkdir(parents=True)
    # Some vault knowledge files for match_vault to find
    knowledge = tmp_path / "knowledge" / "projects"
    knowledge.mkdir(parents=True)
    (knowledge / "trellis.md").write_text(
        "# Trellis\nAn experimental personal agent runtime.\nBuilt by Kyle."
    )
    (knowledge / "design-system.md").write_text(
        "# Design System\nSolarpunk aesthetic with warm cream palette.\nFraunces typography."
    )
    return tmp_path


@pytest.fixture
def processor(vault: Path) -> InboxProcessor:
    """InboxProcessor with no model router (heuristic-only)."""
    return InboxProcessor(vault_path=vault, router=None, config={})


@pytest.fixture
def processor_with_router(vault: Path) -> InboxProcessor:
    """InboxProcessor with a mocked model router."""
    mock_router = MagicMock()
    # Mock the route method to return a classification JSON
    mock_result = MagicMock()
    mock_result.response = json.dumps({
        "type": "task",
        "tags": ["development", "trellis"],
        "summary": "Build inbox interface for Ivy",
    })
    mock_router.route = AsyncMock(return_value=mock_result)
    return InboxProcessor(vault_path=vault, router=mock_router, config={})


# ---------------------------------------------------------------------------
# Confidence tier
# ---------------------------------------------------------------------------

class TestConfidenceTier:
    def test_green_at_90(self) -> None:
        assert _confidence_tier(0.90) == "green"

    def test_green_above_90(self) -> None:
        assert _confidence_tier(0.95) == "green"

    def test_amber_at_70(self) -> None:
        assert _confidence_tier(0.70) == "amber"

    def test_amber_at_89(self) -> None:
        assert _confidence_tier(0.89) == "amber"

    def test_red_below_70(self) -> None:
        assert _confidence_tier(0.69) == "red"

    def test_red_at_zero(self) -> None:
        assert _confidence_tier(0.0) == "red"


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_round_trip_with_routing(self) -> None:
        routing = RoutingProposal(
            vault_path="knowledge/projects/test.md",
            confidence=0.85,
            confidence_tier="amber",
            urgency="today",
            role="organizer",
            vault_matches=[{"path": "knowledge/x.md", "relevance_score": 0.7, "snippet": "..."}],
            reasoning="Moderate vault match",
        )
        item = InboxItem(
            id="abc123",
            content="Test content body",
            content_type="text",
            summary="Test item",
            planted="2026-03-23T14:00:00Z",
            tended=None,
            status="pending",
            routing=routing,
            metadata={"source": "test"},
        )
        text = _serialize_item(item)
        restored = _deserialize_item(text)

        assert restored is not None
        assert restored.id == "abc123"
        assert restored.content == "Test content body"
        assert restored.status == "pending"
        assert restored.routing is not None
        assert restored.routing.confidence == 0.85
        assert restored.routing.confidence_tier == "amber"
        assert restored.routing.urgency == "today"
        assert restored.routing.role == "organizer"
        assert len(restored.routing.vault_matches) == 1

    def test_round_trip_no_routing(self) -> None:
        item = InboxItem(
            id="def456",
            content="No routing",
            content_type="text",
            summary="Plain item",
            planted="2026-03-23T15:00:00Z",
            tended=None,
            status="pending",
            routing=None,
            metadata={},
        )
        text = _serialize_item(item)
        restored = _deserialize_item(text)
        assert restored is not None
        assert restored.routing is None

    def test_deserialize_bad_input(self) -> None:
        assert _deserialize_item("no frontmatter") is None
        assert _deserialize_item("---\nbad yaml: [") is None
        assert _deserialize_item("---\nfoo: bar\n---\nbody") is None  # no id


# ---------------------------------------------------------------------------
# Classification (heuristic)
# ---------------------------------------------------------------------------

class TestClassifyContent:
    @pytest.mark.asyncio
    async def test_detects_task(self, processor: InboxProcessor) -> None:
        result = await processor.classify_content("I need to finish the inbox feature today")
        assert result["type"] == "task"

    @pytest.mark.asyncio
    async def test_detects_question(self, processor: InboxProcessor) -> None:
        result = await processor.classify_content("How does the heartbeat scheduler work?")
        assert result["type"] == "question"

    @pytest.mark.asyncio
    async def test_detects_idea(self, processor: InboxProcessor) -> None:
        result = await processor.classify_content("What if we added brainstorm sessions?")
        assert result["type"] == "idea"

    @pytest.mark.asyncio
    async def test_detects_link(self, processor: InboxProcessor) -> None:
        result = await processor.classify_content("Check this out https://example.com/article")
        assert result["type"] == "link"

    @pytest.mark.asyncio
    async def test_fallback_note(self, processor: InboxProcessor) -> None:
        result = await processor.classify_content("Just a plain note about something")
        assert result["type"] == "note"

    @pytest.mark.asyncio
    async def test_summary_from_first_line(self, processor: InboxProcessor) -> None:
        result = await processor.classify_content("First line summary\nSecond line detail")
        assert result["summary"] == "First line summary"

    @pytest.mark.asyncio
    async def test_tags_extracted(self, processor: InboxProcessor) -> None:
        result = await processor.classify_content("Working on #trellis and #inbox today")
        assert "trellis" in result["tags"]
        assert "inbox" in result["tags"]


# ---------------------------------------------------------------------------
# Classification with model router
# ---------------------------------------------------------------------------

class TestClassifyWithModel:
    @pytest.mark.asyncio
    async def test_model_classification(self, processor_with_router: InboxProcessor) -> None:
        result = await processor_with_router.classify_content("Build inbox interface")
        assert result["type"] == "task"
        assert "trellis" in result["tags"]

    @pytest.mark.asyncio
    async def test_model_failure_falls_back(self, vault: Path) -> None:
        mock_router = MagicMock()
        mock_router.route = AsyncMock(side_effect=Exception("API down"))
        proc = InboxProcessor(vault_path=vault, router=mock_router, config={})
        result = await proc.classify_content("How does this work?")
        # Falls back to heuristic
        assert result["type"] == "question"


# ---------------------------------------------------------------------------
# Urgency detection
# ---------------------------------------------------------------------------

class TestDetectUrgency:
    @pytest.mark.asyncio
    async def test_immediate_urgent(self, processor: InboxProcessor) -> None:
        result = await processor.detect_urgency("This is urgent, fix now")
        assert result["level"] == "immediate"

    @pytest.mark.asyncio
    async def test_immediate_asap(self, processor: InboxProcessor) -> None:
        result = await processor.detect_urgency("Need this ASAP please")
        assert result["level"] == "immediate"

    @pytest.mark.asyncio
    async def test_immediate_blocking(self, processor: InboxProcessor) -> None:
        result = await processor.detect_urgency("This is blocking the release")
        assert result["level"] == "immediate"

    @pytest.mark.asyncio
    async def test_today_eod(self, processor: InboxProcessor) -> None:
        result = await processor.detect_urgency("Need this by eod")
        assert result["level"] == "today"

    @pytest.mark.asyncio
    async def test_today_afternoon(self, processor: InboxProcessor) -> None:
        result = await processor.detect_urgency("Finish this afternoon")
        assert result["level"] == "today"

    @pytest.mark.asyncio
    async def test_queue_default(self, processor: InboxProcessor) -> None:
        result = await processor.detect_urgency("Just a regular note about stuff")
        assert result["level"] == "queue"

    @pytest.mark.asyncio
    async def test_reason_included(self, processor: InboxProcessor) -> None:
        result = await processor.detect_urgency("This is urgent")
        assert "reason" in result
        assert len(result["reason"]) > 0


# ---------------------------------------------------------------------------
# Role detection
# ---------------------------------------------------------------------------

class TestDetectRole:
    @pytest.mark.asyncio
    async def test_researcher(self, processor: InboxProcessor) -> None:
        result = await processor.detect_role("Research the latest AI agent frameworks and compare them")
        assert result["role"] == "researcher"

    @pytest.mark.asyncio
    async def test_strategist(self, processor: InboxProcessor) -> None:
        result = await processor.detect_role("We need a strategy and roadmap for the next quarter")
        assert result["role"] == "strategist"

    @pytest.mark.asyncio
    async def test_writer(self, processor: InboxProcessor) -> None:
        result = await processor.detect_role("Draft a blog post about solarpunk design")
        assert result["role"] == "writer"

    @pytest.mark.asyncio
    async def test_organizer(self, processor: InboxProcessor) -> None:
        result = await processor.detect_role("Organize the project files and schedule a meeting")
        assert result["role"] == "organizer"

    @pytest.mark.asyncio
    async def test_default_organizer(self, processor: InboxProcessor) -> None:
        result = await processor.detect_role("Hello there general kenobi")
        assert result["role"] == "organizer"
        assert result["confidence"] == 0.5

    @pytest.mark.asyncio
    async def test_confidence_present(self, processor: InboxProcessor) -> None:
        result = await processor.detect_role("Research and investigate this topic deeply")
        assert 0.0 <= result["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# Vault matching
# ---------------------------------------------------------------------------

class TestMatchVault:
    @pytest.mark.asyncio
    async def test_returns_matches(self, processor: InboxProcessor) -> None:
        results = await processor.match_vault("Trellis agent runtime")
        assert len(results) > 0
        assert "path" in results[0]
        assert "relevance_score" in results[0]
        assert "snippet" in results[0]

    @pytest.mark.asyncio
    async def test_max_three(self, processor: InboxProcessor) -> None:
        results = await processor.match_vault("design system")
        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_no_match(self, processor: InboxProcessor) -> None:
        results = await processor.match_vault("xyzzyplugh")
        assert results == []


# ---------------------------------------------------------------------------
# Full process_drop pipeline
# ---------------------------------------------------------------------------

class TestProcessDrop:
    @pytest.mark.asyncio
    async def test_creates_item(self, processor: InboxProcessor) -> None:
        item = await processor.process_drop("Build the inbox UI today")
        assert item.id
        assert item.status == "pending"
        assert item.content == "Build the inbox UI today"
        assert item.planted

    @pytest.mark.asyncio
    async def test_routing_attached(self, processor: InboxProcessor) -> None:
        item = await processor.process_drop("Research AI frameworks")
        assert item.routing is not None
        assert item.routing.vault_path
        assert item.routing.confidence > 0
        assert item.routing.confidence_tier in ("green", "amber", "red")
        assert item.routing.urgency in ("immediate", "today", "queue")
        assert item.routing.role

    @pytest.mark.asyncio
    async def test_saved_to_disk(self, processor: InboxProcessor) -> None:
        item = await processor.process_drop("Save me to disk")
        path = processor._items_dir / f"{item.id}.md"
        assert path.exists()

    @pytest.mark.asyncio
    async def test_metadata_preserved(self, processor: InboxProcessor) -> None:
        item = await processor.process_drop(
            "With metadata",
            content_type="url",
            metadata={"source": "discord"},
        )
        assert item.content_type == "url"
        assert item.metadata["source"] == "discord"


# ---------------------------------------------------------------------------
# File-based storage operations
# ---------------------------------------------------------------------------

class TestStorage:
    @pytest.mark.asyncio
    async def test_save_and_load(self, processor: InboxProcessor) -> None:
        item = await processor.process_drop("Storable content")
        loaded = processor.load_item(item.id)
        assert loaded is not None
        assert loaded.id == item.id
        assert loaded.content == "Storable content"

    @pytest.mark.asyncio
    async def test_list_pending(self, processor: InboxProcessor) -> None:
        await processor.process_drop("Item one")
        await processor.process_drop("Item two")
        items = processor.list_items(status="pending")
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_approve_saves_to_vault(self, processor: InboxProcessor) -> None:
        item = await processor.process_drop("Approve me please")
        result = processor.approve_item(item.id)
        assert result is not None
        assert result.status == "approved"
        assert result.tended is not None
        # Check that the file was written to the vault
        assert (processor.vault_path / result.routing.vault_path).exists()

    @pytest.mark.asyncio
    async def test_redirect_saves_to_custom_path(self, processor: InboxProcessor) -> None:
        item = await processor.process_drop("Redirect me")
        result = processor.approve_item(item.id, vault_path_override="knowledge/custom/redirected.md")
        assert result is not None
        assert result.status == "redirected"
        assert (processor.vault_path / "knowledge/custom/redirected.md").exists()

    @pytest.mark.asyncio
    async def test_archive_moves_file(self, processor: InboxProcessor) -> None:
        item = await processor.process_drop("Archive me")
        result = processor.archive_item(item.id)
        assert result is not None
        assert result.status == "archived"
        # Moved out of items/
        assert not (processor._items_dir / f"{item.id}.md").exists()
        # Now in archived/
        assert (processor._archived_dir / f"{item.id}.md").exists()

    @pytest.mark.asyncio
    async def test_approve_missing_item(self, processor: InboxProcessor) -> None:
        result = processor.approve_item("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_archive_missing_item(self, processor: InboxProcessor) -> None:
        result = processor.archive_item("nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# Urgency sort ordering
# ---------------------------------------------------------------------------

class TestSortOrdering:
    @pytest.mark.asyncio
    async def test_immediate_before_queue(self, processor: InboxProcessor) -> None:
        q_item = await processor.process_drop("Just a regular thing")
        u_item = await processor.process_drop("This is urgent fix now")
        items = processor.list_items()
        # Urgent (immediate) should come before queue
        ids = [i.id for i in items]
        assert ids.index(u_item.id) < ids.index(q_item.id)


# ---------------------------------------------------------------------------
# API endpoints (via TestClient)
# ---------------------------------------------------------------------------

class TestAPIEndpoints:
    @pytest.fixture
    def client(self, vault: Path) -> TestClient:
        """Create a TestClient with inbox processor wired in."""
        from trellis.senses.web import create_app

        config = {"vault_path": vault}
        app = create_app(config=config)
        return TestClient(app)

    def test_drop_creates_item(self, client: TestClient) -> None:
        resp = client.post("/api/inbox/drop", json={
            "content": "Test drop via API",
            "content_type": "text",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "item" in data
        assert data["item"]["status"] == "pending"
        assert data["item"]["content"] == "Test drop via API"

    def test_list_items(self, client: TestClient) -> None:
        # Drop two items first
        client.post("/api/inbox/drop", json={"content": "Item A", "content_type": "text"})
        client.post("/api/inbox/drop", json={"content": "Item B", "content_type": "text"})
        resp = client.get("/api/inbox/items")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert "counts" in data

    def test_get_item_detail(self, client: TestClient) -> None:
        drop_resp = client.post("/api/inbox/drop", json={"content": "Detail test", "content_type": "text"})
        item_id = drop_resp.json()["item"]["id"]
        resp = client.get(f"/api/inbox/{item_id}")
        assert resp.status_code == 200
        assert resp.json()["item"]["id"] == item_id

    def test_get_item_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/inbox/nonexistent")
        assert resp.status_code == 404

    def test_approve_item(self, client: TestClient) -> None:
        drop_resp = client.post("/api/inbox/drop", json={"content": "Approve me via API", "content_type": "text"})
        item_id = drop_resp.json()["item"]["id"]
        resp = client.post(f"/api/inbox/{item_id}/approve")
        assert resp.status_code == 200
        data = resp.json()
        assert data["item"]["status"] == "approved"
        assert "saved_to" in data

    def test_redirect_item(self, client: TestClient) -> None:
        drop_resp = client.post("/api/inbox/drop", json={"content": "Redirect me via API", "content_type": "text"})
        item_id = drop_resp.json()["item"]["id"]
        resp = client.post(f"/api/inbox/{item_id}/redirect", json={"vault_path": "knowledge/custom/test.md"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["item"]["status"] == "redirected"
        assert data["saved_to"] == "knowledge/custom/test.md"

    def test_archive_item(self, client: TestClient) -> None:
        drop_resp = client.post("/api/inbox/drop", json={"content": "Archive me via API", "content_type": "text"})
        item_id = drop_resp.json()["item"]["id"]
        resp = client.post(f"/api/inbox/{item_id}/archive")
        assert resp.status_code == 200
        data = resp.json()
        assert data["item"]["status"] == "archived"
        assert "archived_to" in data

    def test_approve_not_found(self, client: TestClient) -> None:
        resp = client.post("/api/inbox/nonexistent/approve")
        assert resp.status_code == 404

    def test_redirect_not_found(self, client: TestClient) -> None:
        resp = client.post("/api/inbox/nonexistent/redirect", json={"vault_path": "x.md"})
        assert resp.status_code == 404

    def test_archive_not_found(self, client: TestClient) -> None:
        resp = client.post("/api/inbox/nonexistent/archive")
        assert resp.status_code == 404
