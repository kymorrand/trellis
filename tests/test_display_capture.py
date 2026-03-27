"""Tests for trellis.hands.display_capture and POST /api/screenshot endpoint."""

from __future__ import annotations

from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# display_capture module tests
# ---------------------------------------------------------------------------


class _FakeScreenShot:
    """Mimics mss.ScreenShot with .rgb and .size."""

    def __init__(self, width: int = 1920, height: int = 1080):
        self.size = (width, height)
        # 3 bytes per pixel (RGB)
        self.rgb = b"\x00\x80\xff" * (width * height)


class _FakeSct:
    """Mimics the object returned by mss.mss() context manager."""

    def __init__(self, monitors: list[dict] | None = None):
        self.monitors = monitors or [
            {"left": 0, "top": 0, "width": 3840, "height": 1080},  # all monitors
            {"left": 0, "top": 0, "width": 1920, "height": 1080},  # primary
        ]

    def grab(self, mon: dict) -> _FakeScreenShot:
        return _FakeScreenShot(mon["width"], mon["height"])

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def _mock_mss():
    return _FakeSct()


class TestListMonitors:
    """Tests for list_monitors()."""

    @patch("trellis.hands.display_capture.mss.mss", side_effect=lambda: _FakeSct())
    def test_returns_at_least_one_monitor(self, mock_mss):
        from trellis.hands.display_capture import list_monitors

        monitors = list_monitors()
        assert len(monitors) >= 1

    @patch("trellis.hands.display_capture.mss.mss", side_effect=lambda: _FakeSct())
    def test_monitor_has_required_fields(self, mock_mss):
        from trellis.hands.display_capture import list_monitors

        monitors = list_monitors()
        for mon in monitors:
            assert "index" in mon
            assert "width" in mon
            assert "height" in mon
            assert "left" in mon
            assert "top" in mon

    @patch("trellis.hands.display_capture.mss.mss", side_effect=lambda: _FakeSct())
    def test_primary_monitor_is_index_1(self, mock_mss):
        from trellis.hands.display_capture import list_monitors

        monitors = list_monitors()
        assert monitors[1]["index"] == 1
        assert monitors[1]["width"] == 1920


class TestCaptureDisplay:
    """Tests for capture_display()."""

    @patch("trellis.hands.display_capture.mss.mss", side_effect=lambda: _FakeSct())
    def test_returns_display_capture(self, mock_mss):
        from trellis.hands.display_capture import DisplayCapture, capture_display

        result = capture_display()
        assert isinstance(result, DisplayCapture)

    @patch("trellis.hands.display_capture.mss.mss", side_effect=lambda: _FakeSct())
    def test_capture_has_correct_dimensions(self, mock_mss):
        from trellis.hands.display_capture import capture_display

        result = capture_display()
        assert result.width == 1920
        assert result.height == 1080

    @patch("trellis.hands.display_capture.mss.mss", side_effect=lambda: _FakeSct())
    def test_capture_has_png_bytes(self, mock_mss):
        from trellis.hands.display_capture import capture_display

        result = capture_display()
        assert isinstance(result.image_bytes, bytes)
        # PNG magic number
        assert result.image_bytes[:4] == b"\x89PNG"

    @patch("trellis.hands.display_capture.mss.mss", side_effect=lambda: _FakeSct())
    def test_capture_has_monitor_info(self, mock_mss):
        from trellis.hands.display_capture import capture_display

        result = capture_display()
        assert result.monitor_info["index"] == 1
        assert result.monitor_info["width"] == 1920

    @patch("trellis.hands.display_capture.mss.mss", side_effect=lambda: _FakeSct())
    def test_capture_has_timestamp(self, mock_mss):
        from trellis.hands.display_capture import capture_display

        result = capture_display()
        assert result.timestamp.endswith("Z")
        assert "T" in result.timestamp

    @patch("trellis.hands.display_capture.mss.mss", side_effect=lambda: _FakeSct())
    def test_capture_defaults_to_primary(self, mock_mss):
        from trellis.hands.display_capture import capture_display

        result = capture_display(monitor=None)
        assert result.monitor_info["index"] == 1

    @patch("trellis.hands.display_capture.mss.mss", side_effect=lambda: _FakeSct())
    def test_capture_invalid_monitor_raises(self, mock_mss):
        from trellis.hands.display_capture import capture_display

        with pytest.raises(ValueError, match="out of range"):
            capture_display(monitor=99)

    @patch("trellis.hands.display_capture.mss.mss", side_effect=Exception("No display"))
    def test_capture_failure_raises_runtime_error(self, mock_mss):
        from trellis.hands.display_capture import capture_display

        with pytest.raises(RuntimeError, match="Display capture failed"):
            capture_display()


class TestCleanupTempScreenshots:
    """Tests for cleanup_temp_screenshots()."""

    def test_deletes_oldest_when_over_limit(self, tmp_path):
        from trellis.hands.display_capture import cleanup_temp_screenshots

        # Create 5 files
        for i in range(5):
            (tmp_path / f"shot-{i:03d}.png").write_bytes(b"PNG")

        cleanup_temp_screenshots(tmp_path, max_files=3)

        remaining = list(tmp_path.glob("*.png"))
        assert len(remaining) == 3

    def test_keeps_all_when_under_limit(self, tmp_path):
        from trellis.hands.display_capture import cleanup_temp_screenshots

        for i in range(3):
            (tmp_path / f"shot-{i:03d}.png").write_bytes(b"PNG")

        cleanup_temp_screenshots(tmp_path, max_files=5)

        remaining = list(tmp_path.glob("*.png"))
        assert len(remaining) == 3


class TestSaveTempScreenshot:
    """Tests for save_temp_screenshot()."""

    def test_creates_file(self, tmp_path):
        from trellis.hands.display_capture import save_temp_screenshot

        png_data = b"\x89PNG\r\n\x1a\nfakedata"
        path = save_temp_screenshot(png_data, tmp_path)

        assert path.exists()
        assert path.read_bytes() == png_data
        assert path.parent.name == "screenshots"

    def test_runs_cleanup(self, tmp_path):
        from trellis.hands.display_capture import save_temp_screenshot

        # Pre-populate with files over the limit
        screenshots_dir = tmp_path / "screenshots"
        screenshots_dir.mkdir(parents=True)
        for i in range(55):
            (screenshots_dir / f"old-{i:03d}.png").write_bytes(b"PNG")

        save_temp_screenshot(b"\x89PNGdata", tmp_path)

        remaining = list(screenshots_dir.glob("*.png"))
        assert len(remaining) <= 50


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestScreenshotEndpoint:
    """Tests for POST /api/screenshot."""

    def _make_app(self):
        """Create a test app with mocked dependencies."""
        from trellis.senses.web import create_app

        return create_app(
            config={},
            agent_state=None,
            knowledge_manager=None,
        )

    @patch("trellis.senses.web.capture_display")
    def test_endpoint_returns_correct_structure(self, mock_capture):
        from starlette.testclient import TestClient

        from trellis.hands.display_capture import DisplayCapture

        mock_capture.return_value = DisplayCapture(
            image_bytes=b"\x89PNG\r\n\x1a\nfakedata",
            width=1920,
            height=1080,
            monitor_info={"index": 1, "left": 0, "top": 0, "width": 1920, "height": 1080},
            timestamp="2026-03-27T12:00:00Z",
        )

        with patch("trellis.senses.web.list_monitors", return_value=[
            {"index": 0, "left": 0, "top": 0, "width": 3840, "height": 1080},
            {"index": 1, "left": 0, "top": 0, "width": 1920, "height": 1080},
        ]):
            app = self._make_app()
            client = TestClient(app)
            resp = client.post("/api/screenshot", json={})

        assert resp.status_code == 200
        data = resp.json()
        assert "image" in data
        assert "metadata" in data
        assert "timestamp" in data["metadata"]
        assert "display" in data["metadata"]
        assert data["metadata"]["display"]["width"] == 1920
        assert data["metadata"]["display"]["height"] == 1080
        assert data["metadata"]["monitors_available"] == 2

    @patch("trellis.senses.web.capture_display", side_effect=RuntimeError("No display"))
    def test_endpoint_handles_failure(self, mock_capture):
        from starlette.testclient import TestClient

        with patch("trellis.senses.web.list_monitors", return_value=[]):
            app = self._make_app()
            client = TestClient(app)
            resp = client.post("/api/screenshot", json={})

        assert resp.status_code == 500
        data = resp.json()
        assert "error" in data
