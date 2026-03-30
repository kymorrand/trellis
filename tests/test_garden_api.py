"""
tests.test_garden_api — Tests for garden content API endpoints.

Tests cover:
    - Listing artifacts from markdown files with YAML frontmatter
    - Sorting by published_at descending, nulls last
    - Content preview generation (~200 chars)
    - Single artifact detail with full content
    - Missing garden directory returns empty list
    - 404 for nonexistent slug
    - Frontmatter edge cases (no frontmatter, invalid YAML, missing fields)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from trellis.core.garden_api import (
    GardenArtifact,
    GardenArtifactDetail,
    GardenResponse,
    create_garden_router,
)


# ─── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def garden_dir(tmp_path: Path) -> Path:
    """Create a temporary garden directory."""
    d = tmp_path / "garden"
    d.mkdir()
    return d


@pytest.fixture
def app(garden_dir: Path) -> FastAPI:
    """Create a FastAPI app with the garden router."""
    app = FastAPI()
    app.include_router(create_garden_router(garden_dir))
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _write_artifact(
    garden_dir: Path,
    slug: str,
    title: str = "Test Article",
    description: str = "A test article",
    tags: list[str] | None = None,
    published_at: str | None = None,
    content: str = "This is the body content of the article.",
) -> Path:
    """Write a markdown artifact file with YAML frontmatter."""
    if tags is None:
        tags = ["test"]

    frontmatter_parts = [
        f"title: {title}",
        f"description: {description}",
        f"tags: [{', '.join(tags)}]",
    ]
    if published_at is not None:
        frontmatter_parts.append(f"published_at: \"{published_at}\"")

    frontmatter = "\n".join(frontmatter_parts)
    file_content = f"---\n{frontmatter}\n---\n\n{content}"

    path = garden_dir / f"{slug}.md"
    path.write_text(file_content, encoding="utf-8")
    return path


# ─── List artifacts ─────────────────────────────────────────


class TestListArtifacts:
    def test_empty_garden(self, client: TestClient, garden_dir: Path) -> None:
        resp = client.get("/api/garden/artifacts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["artifacts"] == []
        assert data["count"] == 0

    def test_missing_garden_directory(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "nonexistent"
        app = FastAPI()
        app.include_router(create_garden_router(nonexistent))
        client = TestClient(app)

        resp = client.get("/api/garden/artifacts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["artifacts"] == []
        assert data["count"] == 0

    def test_single_artifact(self, client: TestClient, garden_dir: Path) -> None:
        _write_artifact(
            garden_dir,
            slug="hello-world",
            title="Hello World",
            description="My first post",
            tags=["intro", "hello"],
            published_at="2026-03-15",
            content="Welcome to the garden.",
        )

        resp = client.get("/api/garden/artifacts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1

        artifact = data["artifacts"][0]
        assert artifact["slug"] == "hello-world"
        assert artifact["title"] == "Hello World"
        assert artifact["description"] == "My first post"
        assert artifact["tags"] == ["intro", "hello"]
        assert artifact["published_at"] == "2026-03-15"
        assert artifact["content_preview"] == "Welcome to the garden."
        # List endpoint should NOT have full content
        assert "content" not in artifact or artifact.get("content") is None

    def test_multiple_artifacts_sorted_by_date(
        self, client: TestClient, garden_dir: Path,
    ) -> None:
        _write_artifact(garden_dir, "old-post", published_at="2026-01-01", title="Old")
        _write_artifact(garden_dir, "new-post", published_at="2026-03-15", title="New")
        _write_artifact(garden_dir, "mid-post", published_at="2026-02-01", title="Mid")

        resp = client.get("/api/garden/artifacts")
        data = resp.json()
        assert data["count"] == 3
        slugs = [a["slug"] for a in data["artifacts"]]
        assert slugs == ["new-post", "mid-post", "old-post"]

    def test_nulls_sort_last(
        self, client: TestClient, garden_dir: Path,
    ) -> None:
        _write_artifact(garden_dir, "published", published_at="2026-01-01", title="Published")
        _write_artifact(garden_dir, "draft", title="Draft")  # no published_at

        resp = client.get("/api/garden/artifacts")
        data = resp.json()
        assert data["count"] == 2
        assert data["artifacts"][0]["slug"] == "published"
        assert data["artifacts"][1]["slug"] == "draft"
        assert data["artifacts"][1]["published_at"] is None

    def test_content_preview_truncated(
        self, client: TestClient, garden_dir: Path,
    ) -> None:
        long_content = "A" * 500
        _write_artifact(garden_dir, "long-post", content=long_content, published_at="2026-01-01")

        resp = client.get("/api/garden/artifacts")
        data = resp.json()
        preview = data["artifacts"][0]["content_preview"]
        assert len(preview) <= 200

    def test_no_frontmatter_still_works(
        self, client: TestClient, garden_dir: Path,
    ) -> None:
        path = garden_dir / "raw-post.md"
        path.write_text("Just some raw markdown content.", encoding="utf-8")

        resp = client.get("/api/garden/artifacts")
        data = resp.json()
        assert data["count"] == 1
        artifact = data["artifacts"][0]
        assert artifact["slug"] == "raw-post"
        assert artifact["title"] == "Raw Post"  # derived from filename
        assert artifact["tags"] == []
        assert artifact["published_at"] is None

    def test_invalid_yaml_frontmatter_handled(
        self, client: TestClient, garden_dir: Path,
    ) -> None:
        path = garden_dir / "bad-yaml.md"
        path.write_text("---\n: invalid: yaml: [[\n---\n\nSome content.", encoding="utf-8")

        resp = client.get("/api/garden/artifacts")
        data = resp.json()
        # Should still return the file, just without parsed frontmatter
        assert data["count"] == 1

    def test_non_md_files_ignored(
        self, client: TestClient, garden_dir: Path,
    ) -> None:
        (garden_dir / "readme.txt").write_text("not markdown")
        (garden_dir / "image.png").write_bytes(b"\x89PNG")
        _write_artifact(garden_dir, "real-post", published_at="2026-01-01")

        resp = client.get("/api/garden/artifacts")
        data = resp.json()
        assert data["count"] == 1


# ─── Single artifact detail ─────────────────────────────────


class TestGetArtifact:
    def test_get_existing_artifact(
        self, client: TestClient, garden_dir: Path,
    ) -> None:
        body = "# Full Article\n\nThis is the **full** markdown content."
        _write_artifact(
            garden_dir,
            slug="my-article",
            title="My Article",
            description="A detailed article",
            tags=["research"],
            published_at="2026-03-20",
            content=body,
        )

        resp = client.get("/api/garden/artifacts/my-article")
        assert resp.status_code == 200
        data = resp.json()
        assert data["slug"] == "my-article"
        assert data["title"] == "My Article"
        assert data["content"] == body
        assert data["content_preview"] == body[:200].strip()

    def test_404_for_nonexistent_slug(self, client: TestClient) -> None:
        resp = client.get("/api/garden/artifacts/nonexistent")
        assert resp.status_code == 404

    def test_detail_has_all_fields(
        self, client: TestClient, garden_dir: Path,
    ) -> None:
        _write_artifact(
            garden_dir,
            slug="complete",
            title="Complete",
            description="All fields",
            tags=["a", "b"],
            published_at="2026-01-15",
            content="Body text here.",
        )

        resp = client.get("/api/garden/artifacts/complete")
        data = resp.json()
        # Verify all GardenArtifactDetail fields are present
        assert "slug" in data
        assert "title" in data
        assert "description" in data
        assert "tags" in data
        assert "published_at" in data
        assert "content_preview" in data
        assert "content" in data


# ─── Pydantic model tests ───────────────────────────────────


class TestModels:
    def test_garden_artifact_fields(self) -> None:
        artifact = GardenArtifact(
            slug="test",
            title="Test",
            description="Desc",
            tags=["a"],
            published_at="2026-01-01",
            content_preview="Preview",
        )
        assert artifact.slug == "test"
        assert artifact.published_at == "2026-01-01"

    def test_garden_artifact_null_published(self) -> None:
        artifact = GardenArtifact(
            slug="test",
            title="Test",
            description="",
            tags=[],
            published_at=None,
            content_preview="",
        )
        assert artifact.published_at is None

    def test_garden_artifact_detail_extends_artifact(self) -> None:
        detail = GardenArtifactDetail(
            slug="test",
            title="Test",
            description="Desc",
            tags=[],
            published_at=None,
            content_preview="Preview",
            content="Full content",
        )
        assert detail.content == "Full content"
        assert isinstance(detail, GardenArtifact)

    def test_garden_response_model(self) -> None:
        resp = GardenResponse(
            artifacts=[
                GardenArtifact(
                    slug="a", title="A", description="", tags=[],
                    published_at=None, content_preview="",
                ),
            ],
            count=1,
        )
        assert resp.count == 1
        assert len(resp.artifacts) == 1
