"""Tests for GET /api/gardener/status and GET /api/gardener/health endpoints."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from trellis.senses.web import create_app


@pytest.fixture()
def vault_tmp(tmp_path: Path) -> Path:
    """Create a temporary vault with _ivy/reports/ directory."""
    reports_dir = tmp_path / "_ivy" / "reports"
    reports_dir.mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def client(vault_tmp: Path) -> TestClient:
    """FastAPI test client with vault_path pointing at tmp vault."""
    app = create_app(config={"vault_path": vault_tmp})
    return TestClient(app)


@pytest.fixture()
def client_no_vault() -> TestClient:
    """FastAPI test client with no vault_path."""
    app = create_app(config={"vault_path": None})
    return TestClient(app)


class TestGardenerStatusEndpoint:
    """Tests for GET /api/gardener/status."""

    def test_empty_reports_directory(self, client: TestClient) -> None:
        """Empty reports dir returns empty list."""
        resp = client.get("/api/gardener/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"reports": []}

    def test_single_status_file(self, client: TestClient, vault_tmp: Path) -> None:
        """A status-root file is parsed correctly."""
        report = vault_tmp / "_ivy" / "reports" / "status-root-2026-03-22.md"
        report.write_text(
            "# Root Status Report — 2026-03-22\n\n"
            "## Task\n"
            "Write missing test coverage for core modules.\n\n"
            "## Details\nMore stuff here.\n",
            encoding="utf-8",
        )
        resp = client.get("/api/gardener/status")
        data = resp.json()
        assert len(data["reports"]) == 1
        r = data["reports"][0]
        assert r["agent"] == "root"
        assert r["type"] == "status"
        assert r["date"] == "2026-03-22"
        assert r["title"] == "Root Status Report — 2026-03-22"
        assert r["summary"] == "Write missing test coverage for core modules."
        assert r["file_path"] == "_ivy/reports/status-root-2026-03-22.md"

    def test_single_garden_report(self, client: TestClient, vault_tmp: Path) -> None:
        """A garden-report file is parsed correctly."""
        report = vault_tmp / "_ivy" / "reports" / "garden-report-2026-03-22.md"
        report.write_text(
            "# Garden Report — 2026-03-22\n\n"
            "## Summary\n"
            "Sprint kickoff. Gardener Activity page planned.\n",
            encoding="utf-8",
        )
        resp = client.get("/api/gardener/status")
        data = resp.json()
        assert len(data["reports"]) == 1
        r = data["reports"][0]
        assert r["agent"] == "thorn"
        assert r["type"] == "garden-report"
        assert r["date"] == "2026-03-22"
        assert r["title"] == "Garden Report — 2026-03-22"
        assert r["summary"] == "Sprint kickoff. Gardener Activity page planned."
        assert r["file_path"] == "_ivy/reports/garden-report-2026-03-22.md"

    def test_bloom_status_file(self, client: TestClient, vault_tmp: Path) -> None:
        """A status-bloom file gets agent='bloom'."""
        report = vault_tmp / "_ivy" / "reports" / "status-bloom-2026-03-22.md"
        report.write_text(
            "# Bloom Status Report — 2026-03-22\n\n"
            "## Task\n"
            "Build garden page.\n",
            encoding="utf-8",
        )
        resp = client.get("/api/gardener/status")
        data = resp.json()
        assert len(data["reports"]) == 1
        assert data["reports"][0]["agent"] == "bloom"
        assert data["reports"][0]["type"] == "status"

    def test_multiple_files_sorted_by_date_descending(
        self, client: TestClient, vault_tmp: Path
    ) -> None:
        """Multiple reports sort newest-first, then alphabetical by agent."""
        reports_dir = vault_tmp / "_ivy" / "reports"

        (reports_dir / "status-root-2026-03-20.md").write_text(
            "# Root Status — 2026-03-20\n\n## Task\nOlder task.\n",
            encoding="utf-8",
        )
        (reports_dir / "status-bloom-2026-03-22.md").write_text(
            "# Bloom Status — 2026-03-22\n\n## Task\nNew task.\n",
            encoding="utf-8",
        )
        (reports_dir / "status-root-2026-03-22.md").write_text(
            "# Root Status — 2026-03-22\n\n## Task\nAlso new.\n",
            encoding="utf-8",
        )

        resp = client.get("/api/gardener/status")
        data = resp.json()
        reports = data["reports"]
        assert len(reports) == 3
        # Newest first
        assert reports[0]["date"] == "2026-03-22"
        assert reports[1]["date"] == "2026-03-22"
        assert reports[2]["date"] == "2026-03-20"
        # Same date: alphabetical by agent
        assert reports[0]["agent"] == "bloom"
        assert reports[1]["agent"] == "root"

    def test_malformed_filename_skipped(
        self, client: TestClient, vault_tmp: Path
    ) -> None:
        """Files that don't match the naming convention are skipped."""
        reports_dir = vault_tmp / "_ivy" / "reports"
        # Valid file
        (reports_dir / "status-root-2026-03-22.md").write_text(
            "# Root Status\n\n## Task\nWork.\n", encoding="utf-8"
        )
        # Malformed files
        (reports_dir / "random-notes.md").write_text("# Notes\n", encoding="utf-8")
        (reports_dir / "status-.md").write_text("# Bad\n", encoding="utf-8")
        (reports_dir / "sprint-current.md").write_text("# Sprint\n", encoding="utf-8")

        resp = client.get("/api/gardener/status")
        data = resp.json()
        assert len(data["reports"]) == 1
        assert data["reports"][0]["agent"] == "root"

    def test_file_with_no_headings_uses_fallback(
        self, client: TestClient, vault_tmp: Path
    ) -> None:
        """File with no ## heading uses first 120 chars as summary."""
        report = vault_tmp / "_ivy" / "reports" / "status-root-2026-03-22.md"
        report.write_text(
            "# Root Status\n\nThis is body text without any sub-headings.\n"
            "It just keeps going and going to make the content longer than expected.\n",
            encoding="utf-8",
        )
        resp = client.get("/api/gardener/status")
        data = resp.json()
        r = data["reports"][0]
        assert r["title"] == "Root Status"
        assert len(r["summary"]) > 0
        assert len(r["summary"]) <= 120

    def test_missing_vault_path_returns_empty(
        self, client_no_vault: TestClient
    ) -> None:
        """When vault_path is None, return empty list."""
        resp = client_no_vault.get("/api/gardener/status")
        assert resp.status_code == 200
        assert resp.json() == {"reports": []}

    def test_nonexistent_reports_dir(self, tmp_path: Path) -> None:
        """When _ivy/reports/ doesn't exist, return empty list."""
        app = create_app(config={"vault_path": tmp_path})
        client = TestClient(app)
        resp = client.get("/api/gardener/status")
        assert resp.status_code == 200
        assert resp.json() == {"reports": []}

    def test_thorn_status_file(self, client: TestClient, vault_tmp: Path) -> None:
        """A status-thorn file gets agent='thorn', type='status'."""
        report = vault_tmp / "_ivy" / "reports" / "status-thorn-2026-03-22.md"
        report.write_text(
            "# Thorn Status\n\n## Review\nReviewed all PRs.\n", encoding="utf-8"
        )
        resp = client.get("/api/gardener/status")
        data = resp.json()
        assert data["reports"][0]["agent"] == "thorn"
        assert data["reports"][0]["type"] == "status"

    def test_empty_file_handled(self, client: TestClient, vault_tmp: Path) -> None:
        """An empty markdown file doesn't crash; gets empty title/summary."""
        report = vault_tmp / "_ivy" / "reports" / "status-root-2026-03-22.md"
        report.write_text("", encoding="utf-8")
        resp = client.get("/api/gardener/status")
        data = resp.json()
        assert len(data["reports"]) == 1
        r = data["reports"][0]
        assert r["agent"] == "root"
        assert r["title"] == ""
        assert r["summary"] == ""


class TestGardenerHealthEndpoint:
    """Tests for GET /api/gardener/health."""

    def test_returns_503_without_knowledge_manager(self, vault_tmp: Path) -> None:
        """Without knowledge_manager, endpoint returns 503."""
        app = create_app(config={"vault_path": vault_tmp})
        client = TestClient(app)
        resp = client.get("/api/gardener/health")
        assert resp.status_code == 503

    def test_returns_health_stats(self, vault_tmp: Path) -> None:
        """With knowledge_manager, returns health stats dict."""
        mock_km = MagicMock()
        mock_km.vault_health = AsyncMock(return_value={
            "total_files": 142,
            "indexed_files": 138,
            "stale_files": 3,
            "orphan_files": 7,
            "last_indexed": "2026-03-22T14:30:00",
            "index_coverage_pct": 97.2,
        })
        app = create_app(
            config={"vault_path": vault_tmp},
            knowledge_manager=mock_km,
        )
        client = TestClient(app)
        resp = client.get("/api/gardener/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_files"] == 142
        assert data["indexed_files"] == 138
        assert data["stale_files"] == 3
        assert data["orphan_files"] == 7
        assert data["last_indexed"] == "2026-03-22T14:30:00"
        assert data["index_coverage_pct"] == 97.2

    def test_health_response_matches_contract(self, vault_tmp: Path) -> None:
        """Response has all expected keys from the API contract."""
        mock_km = MagicMock()
        mock_km.vault_health = AsyncMock(return_value={
            "total_files": 0,
            "indexed_files": 0,
            "stale_files": 0,
            "orphan_files": 0,
            "last_indexed": None,
            "index_coverage_pct": 0.0,
        })
        app = create_app(
            config={"vault_path": vault_tmp},
            knowledge_manager=mock_km,
        )
        client = TestClient(app)
        resp = client.get("/api/gardener/health")
        data = resp.json()
        expected_keys = {
            "total_files", "indexed_files", "stale_files",
            "orphan_files", "last_indexed", "index_coverage_pct",
        }
        assert set(data.keys()) == expected_keys
