"""
trellis.core.garden_api — Garden content API for published artifacts.

Reads published markdown files from the vault's garden directory and
serves them via FastAPI endpoints. Response models match the TypeScript
types in trellis-app/lib/types.ts exactly.

Provides:
    GardenArtifact       — Summary model for artifact listings
    GardenArtifactDetail — Full model with markdown content
    GardenResponse       — List response with count
    create_garden_router() — Factory for the FastAPI router
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ─── Pydantic response models (match trellis-app TypeScript types) ──

class GardenArtifact(BaseModel):
    """Summary of a published garden artifact."""
    slug: str
    title: str
    description: str
    tags: list[str]
    published_at: str | None
    content_preview: str  # first ~200 chars


class GardenArtifactDetail(GardenArtifact):
    """Full garden artifact with markdown content."""
    content: str  # full markdown


class GardenResponse(BaseModel):
    """List response for garden artifacts."""
    artifacts: list[GardenArtifact]
    count: int


# ─── Frontmatter parsing ───────────────────────────────────────

def _parse_markdown_file(file_path: Path) -> tuple[dict, str] | None:
    """Parse a markdown file with YAML frontmatter.

    Returns (frontmatter_dict, body_content) or None if unparseable.
    """
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Failed to read garden file: %s", file_path)
        return None

    frontmatter: dict = {}
    body = text

    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                parsed = yaml.safe_load(parts[1])
                if isinstance(parsed, dict):
                    frontmatter = parsed
                body = parts[2].strip()
            except yaml.YAMLError:
                logger.warning("Invalid YAML frontmatter in %s", file_path)
                body = text

    return frontmatter, body


def _build_artifact(file_path: Path) -> GardenArtifact | None:
    """Build a GardenArtifact from a markdown file."""
    result = _parse_markdown_file(file_path)
    if result is None:
        return None

    frontmatter, body = result
    slug = file_path.stem

    title = frontmatter.get("title", slug.replace("-", " ").replace("_", " ").title())
    description = frontmatter.get("description", "")
    tags = frontmatter.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    tags = [str(t) for t in tags]

    published_at = frontmatter.get("published_at")
    if published_at is not None:
        published_at = str(published_at)

    content_preview = body[:200].strip() if body else ""

    return GardenArtifact(
        slug=slug,
        title=title,
        description=description,
        tags=tags,
        published_at=published_at,
        content_preview=content_preview,
    )


def _build_artifact_detail(file_path: Path) -> GardenArtifactDetail | None:
    """Build a GardenArtifactDetail from a markdown file."""
    result = _parse_markdown_file(file_path)
    if result is None:
        return None

    frontmatter, body = result
    slug = file_path.stem

    title = frontmatter.get("title", slug.replace("-", " ").replace("_", " ").title())
    description = frontmatter.get("description", "")
    tags = frontmatter.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    tags = [str(t) for t in tags]

    published_at = frontmatter.get("published_at")
    if published_at is not None:
        published_at = str(published_at)

    content_preview = body[:200].strip() if body else ""

    return GardenArtifactDetail(
        slug=slug,
        title=title,
        description=description,
        tags=tags,
        published_at=published_at,
        content_preview=content_preview,
        content=body,
    )


# ─── Sort helper ────────────────────────────────────────────────

def _sort_key(artifact: GardenArtifact) -> tuple[int, str]:
    """Sort by published_at descending, nulls last.

    Returns a tuple where:
    - First element: 0 if published, 1 if null (nulls sort last)
    - Second element: negatable string for descending sort
    """
    if artifact.published_at is not None:
        # Invert for descending: prepend with 0 so published come first
        return (0, artifact.published_at)
    return (1, "")


# ─── Router factory ─────────────────────────────────────────────

def create_garden_router(garden_dir: Path) -> APIRouter:
    """Create a FastAPI router for garden artifact endpoints.

    Args:
        garden_dir: Path to the garden directory containing markdown files.
    """
    router = APIRouter(prefix="/api/garden", tags=["garden"])

    @router.get("/artifacts", response_model=GardenResponse)
    async def list_artifacts() -> GardenResponse:
        """List all published garden artifacts."""
        if not garden_dir.is_dir():
            return GardenResponse(artifacts=[], count=0)

        artifacts: list[GardenArtifact] = []
        for file_path in garden_dir.glob("*.md"):
            if not file_path.is_file():
                continue
            artifact = _build_artifact(file_path)
            if artifact is not None:
                artifacts.append(artifact)

        # Sort: published_at descending, nulls last
        artifacts.sort(
            key=_sort_key,
            reverse=False,  # We handle direction in the key
        )
        # Within the "has published_at" group, we need descending order
        published = [a for a in artifacts if a.published_at is not None]
        unpublished = [a for a in artifacts if a.published_at is None]
        published.sort(key=lambda a: a.published_at or "", reverse=True)
        artifacts = published + unpublished

        return GardenResponse(artifacts=artifacts, count=len(artifacts))

    @router.get("/artifacts/{slug}", response_model=GardenArtifactDetail)
    async def get_artifact(slug: str) -> GardenArtifactDetail:
        """Get full content for a single garden artifact."""
        file_path = garden_dir / f"{slug}.md"

        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="Artifact not found")

        detail = _build_artifact_detail(file_path)
        if detail is None:
            raise HTTPException(status_code=500, detail="Failed to parse artifact")

        return detail

    return router
