"""Unit tests for the screenshot comparison module.

Tests ScreenshotComparer with synthetic Pillow images -- no browser
or web server required.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from trellis.testing.screenshot import CompareResult, ScreenshotComparer


@pytest.fixture
def tmp_dirs(tmp_path: Path) -> dict[str, Path]:
    """Create temporary baseline and output directories."""
    baseline = tmp_path / "baseline"
    output = tmp_path / "output"
    baseline.mkdir()
    output.mkdir()
    return {"baseline": baseline, "output": output}


@pytest.fixture
def comparer(tmp_dirs: dict[str, Path]) -> ScreenshotComparer:
    """Create a ScreenshotComparer with default threshold."""
    return ScreenshotComparer(
        baseline_dir=tmp_dirs["baseline"],
        output_dir=tmp_dirs["output"],
        threshold=0.01,
    )


def make_solid_image(path: Path, color: tuple[int, int, int, int], size: tuple[int, int] = (100, 100)) -> Path:
    """Create a solid-color RGBA image at the given path."""
    img = Image.new("RGBA", size, color)
    img.save(str(path), "PNG")
    return path


def make_partial_diff_image(
    path: Path,
    base_color: tuple[int, int, int, int],
    diff_color: tuple[int, int, int, int],
    diff_pixel_count: int,
    size: tuple[int, int] = (100, 100),
) -> Path:
    """Create an image with some pixels differing from base_color."""
    img = Image.new("RGBA", size, base_color)
    pixels = img.load()
    count = 0
    assert pixels is not None
    for y in range(size[1]):
        for x in range(size[0]):
            if count >= diff_pixel_count:
                break
            pixels[x, y] = diff_color
            count += 1
        if count >= diff_pixel_count:
            break
    img.save(str(path), "PNG")
    return path


class TestCompareIdenticalImages:
    """Identical images should always pass comparison."""

    def test_identical_images_pass(self, comparer: ScreenshotComparer, tmp_dirs: dict[str, Path]) -> None:
        color = (200, 180, 160, 255)
        make_solid_image(tmp_dirs["baseline"] / "test.png", color)
        current = make_solid_image(tmp_dirs["output"] / "current.png", color)

        result = comparer.compare("test", current)

        assert result.passed is True
        assert result.diff_ratio == 0.0
        assert result.diff_pixels == 0
        assert result.total_pixels == 100 * 100
        assert result.diff_image is None

    def test_identical_returns_correct_name(self, comparer: ScreenshotComparer, tmp_dirs: dict[str, Path]) -> None:
        color = (100, 100, 100, 255)
        make_solid_image(tmp_dirs["baseline"] / "dawn-mobile.png", color)
        current = make_solid_image(tmp_dirs["output"] / "c.png", color)

        result = comparer.compare("dawn-mobile", current)
        assert result.name == "dawn-mobile"

    def test_identical_returns_correct_paths(self, comparer: ScreenshotComparer, tmp_dirs: dict[str, Path]) -> None:
        color = (50, 50, 50, 255)
        baseline_path = tmp_dirs["baseline"] / "paths.png"
        make_solid_image(baseline_path, color)
        current = make_solid_image(tmp_dirs["output"] / "c.png", color)

        result = comparer.compare("paths", current)
        assert result.baseline == baseline_path
        assert result.current == current


class TestCompareDifferentImages:
    """Different images should fail when diff exceeds threshold."""

    def test_completely_different_images_fail(self, comparer: ScreenshotComparer, tmp_dirs: dict[str, Path]) -> None:
        make_solid_image(tmp_dirs["baseline"] / "test.png", (0, 0, 0, 255))
        current = make_solid_image(tmp_dirs["output"] / "current.png", (255, 255, 255, 255))

        result = comparer.compare("test", current)

        assert result.passed is False
        assert result.diff_ratio == 1.0
        assert result.diff_pixels == 10000
        assert result.diff_image is not None

    def test_diff_ratio_calculated_correctly(self, comparer: ScreenshotComparer, tmp_dirs: dict[str, Path]) -> None:
        """500 differing pixels out of 10000 = 5% diff."""
        base_color = (100, 100, 100, 255)
        diff_color = (200, 200, 200, 255)
        make_solid_image(tmp_dirs["baseline"] / "test.png", base_color)
        current = make_partial_diff_image(
            tmp_dirs["output"] / "current.png",
            base_color,
            diff_color,
            diff_pixel_count=500,
        )

        result = comparer.compare("test", current)

        assert result.diff_pixels == 500
        assert result.diff_ratio == pytest.approx(0.05)
        assert result.passed is False  # 5% > 1% threshold


class TestThresholdBehavior:
    """Threshold controls pass/fail boundary."""

    def test_diff_below_threshold_passes(self, tmp_dirs: dict[str, Path]) -> None:
        """50 pixels out of 10000 = 0.5%, threshold 1% -> pass."""
        comparer = ScreenshotComparer(
            baseline_dir=tmp_dirs["baseline"],
            output_dir=tmp_dirs["output"],
            threshold=0.01,
        )
        base_color = (100, 100, 100, 255)
        diff_color = (200, 200, 200, 255)
        make_solid_image(tmp_dirs["baseline"] / "test.png", base_color)
        current = make_partial_diff_image(
            tmp_dirs["output"] / "current.png",
            base_color,
            diff_color,
            diff_pixel_count=50,
        )

        result = comparer.compare("test", current)
        assert result.passed is True
        assert result.diff_ratio == pytest.approx(0.005)

    def test_diff_above_threshold_fails(self, tmp_dirs: dict[str, Path]) -> None:
        """200 pixels out of 10000 = 2%, threshold 1% -> fail."""
        comparer = ScreenshotComparer(
            baseline_dir=tmp_dirs["baseline"],
            output_dir=tmp_dirs["output"],
            threshold=0.01,
        )
        base_color = (100, 100, 100, 255)
        diff_color = (200, 200, 200, 255)
        make_solid_image(tmp_dirs["baseline"] / "test.png", base_color)
        current = make_partial_diff_image(
            tmp_dirs["output"] / "current.png",
            base_color,
            diff_color,
            diff_pixel_count=200,
        )

        result = comparer.compare("test", current)
        assert result.passed is False

    def test_diff_at_threshold_passes(self, tmp_dirs: dict[str, Path]) -> None:
        """Exactly at threshold should pass (<= comparison)."""
        comparer = ScreenshotComparer(
            baseline_dir=tmp_dirs["baseline"],
            output_dir=tmp_dirs["output"],
            threshold=0.05,  # 5%
        )
        base_color = (100, 100, 100, 255)
        diff_color = (200, 200, 200, 255)
        make_solid_image(tmp_dirs["baseline"] / "test.png", base_color)
        current = make_partial_diff_image(
            tmp_dirs["output"] / "current.png",
            base_color,
            diff_color,
            diff_pixel_count=500,  # exactly 5%
        )

        result = comparer.compare("test", current)
        assert result.passed is True

    def test_zero_threshold_requires_identical(self, tmp_dirs: dict[str, Path]) -> None:
        """With threshold=0, even 1 pixel difference fails."""
        comparer = ScreenshotComparer(
            baseline_dir=tmp_dirs["baseline"],
            output_dir=tmp_dirs["output"],
            threshold=0.0,
        )
        base_color = (100, 100, 100, 255)
        diff_color = (200, 200, 200, 255)
        make_solid_image(tmp_dirs["baseline"] / "test.png", base_color)
        current = make_partial_diff_image(
            tmp_dirs["output"] / "current.png",
            base_color,
            diff_color,
            diff_pixel_count=1,
        )

        result = comparer.compare("test", current)
        assert result.passed is False
        assert result.diff_pixels == 1

    def test_high_threshold_allows_large_diff(self, tmp_dirs: dict[str, Path]) -> None:
        """With threshold=0.5, 40% difference passes."""
        comparer = ScreenshotComparer(
            baseline_dir=tmp_dirs["baseline"],
            output_dir=tmp_dirs["output"],
            threshold=0.5,
        )
        base_color = (100, 100, 100, 255)
        diff_color = (200, 200, 200, 255)
        make_solid_image(tmp_dirs["baseline"] / "test.png", base_color)
        current = make_partial_diff_image(
            tmp_dirs["output"] / "current.png",
            base_color,
            diff_color,
            diff_pixel_count=4000,  # 40%
        )

        result = comparer.compare("test", current)
        assert result.passed is True


class TestDiffImageGeneration:
    """Diff image generation should produce valid PNG files."""

    def test_diff_image_is_valid_png(self, comparer: ScreenshotComparer, tmp_dirs: dict[str, Path]) -> None:
        make_solid_image(tmp_dirs["baseline"] / "test.png", (0, 0, 0, 255))
        current = make_solid_image(tmp_dirs["output"] / "current.png", (255, 255, 255, 255))

        result = comparer.compare("test", current)

        assert result.diff_image is not None
        assert result.diff_image.exists()
        # Verify it's a valid image
        img = Image.open(result.diff_image)
        assert img.size == (100, 100)
        assert img.format == "PNG"

    def test_diff_image_highlights_changes_in_red(self, tmp_dirs: dict[str, Path]) -> None:
        """Differing pixels should be red (255, 0, 0) in the diff image."""
        # Use threshold=0 so even 1 pixel diff triggers diff image generation
        strict = ScreenshotComparer(
            baseline_dir=tmp_dirs["baseline"],
            output_dir=tmp_dirs["output"],
            threshold=0.0,
        )
        make_solid_image(tmp_dirs["baseline"] / "test.png", (0, 0, 0, 255))
        current = make_partial_diff_image(
            tmp_dirs["output"] / "current.png",
            (0, 0, 0, 255),
            (255, 255, 255, 255),
            diff_pixel_count=1,
        )

        result = strict.compare("test", current)
        assert result.diff_image is not None

        diff_img = Image.open(result.diff_image).convert("RGBA")
        pixels = list(diff_img.getdata())
        # First pixel should be red (it differed)
        assert pixels[0] == (255, 0, 0, 255)

    def test_diff_image_dims_unchanged_pixels(self, tmp_dirs: dict[str, Path]) -> None:
        """Unchanged pixels should be dimmed, not red."""
        strict = ScreenshotComparer(
            baseline_dir=tmp_dirs["baseline"],
            output_dir=tmp_dirs["output"],
            threshold=0.0,
        )
        base_color = (100, 100, 100, 255)
        make_solid_image(tmp_dirs["baseline"] / "test.png", base_color)
        current = make_partial_diff_image(
            tmp_dirs["output"] / "current.png",
            base_color,
            (200, 200, 200, 255),
            diff_pixel_count=1,
        )

        result = strict.compare("test", current)
        assert result.diff_image is not None

        diff_img = Image.open(result.diff_image).convert("RGBA")
        pixels = list(diff_img.getdata())
        # Second pixel (unchanged) should NOT be red
        r, g, b, _a = pixels[1]
        assert r != 255 or g != 0 or b != 0  # Not pure red

    def test_diff_image_not_generated_when_passing(self, comparer: ScreenshotComparer, tmp_dirs: dict[str, Path]) -> None:
        """No diff image should be created when comparison passes."""
        color = (100, 100, 100, 255)
        make_solid_image(tmp_dirs["baseline"] / "test.png", color)
        current = make_solid_image(tmp_dirs["output"] / "current.png", color)

        result = comparer.compare("test", current)
        assert result.diff_image is None


class TestMissingBaseline:
    """Missing baseline should raise FileNotFoundError."""

    def test_missing_baseline_raises(self, comparer: ScreenshotComparer, tmp_dirs: dict[str, Path]) -> None:
        current = make_solid_image(tmp_dirs["output"] / "current.png", (0, 0, 0, 255))

        with pytest.raises(FileNotFoundError, match="No baseline found"):
            comparer.compare("nonexistent", current)

    def test_error_message_includes_name(self, comparer: ScreenshotComparer, tmp_dirs: dict[str, Path]) -> None:
        current = make_solid_image(tmp_dirs["output"] / "current.png", (0, 0, 0, 255))

        with pytest.raises(FileNotFoundError, match="evening-kiosk"):
            comparer.compare("evening-kiosk", current)


class TestSaveBaseline:
    """save_baseline should copy image to baseline directory."""

    def test_saves_to_correct_path(self, comparer: ScreenshotComparer, tmp_dirs: dict[str, Path]) -> None:
        source = make_solid_image(tmp_dirs["output"] / "source.png", (100, 100, 100, 255))

        result = comparer.save_baseline("dawn-mobile", source)

        assert result == tmp_dirs["baseline"] / "dawn-mobile.png"
        assert result.exists()

    def test_saved_baseline_matches_source(self, comparer: ScreenshotComparer, tmp_dirs: dict[str, Path]) -> None:
        source = make_solid_image(tmp_dirs["output"] / "source.png", (42, 84, 126, 255))

        dest = comparer.save_baseline("test", source)

        source_img = Image.open(source)
        dest_img = Image.open(dest)
        assert list(source_img.getdata()) == list(dest_img.getdata())

    def test_creates_baseline_dir_if_missing(self, tmp_dirs: dict[str, Path]) -> None:
        new_baseline = tmp_dirs["output"] / "new_baselines"
        comparer = ScreenshotComparer(
            baseline_dir=new_baseline,
            output_dir=tmp_dirs["output"],
        )
        source = make_solid_image(tmp_dirs["output"] / "source.png", (0, 0, 0, 255))

        result = comparer.save_baseline("test", source)

        assert new_baseline.exists()
        assert result.exists()


class TestCompareResult:
    """CompareResult dataclass should hold all expected fields."""

    def test_dataclass_fields(self) -> None:
        result = CompareResult(
            name="test",
            passed=True,
            diff_ratio=0.0,
            diff_pixels=0,
            total_pixels=10000,
            diff_image=None,
            baseline=Path("/tmp/baseline.png"),
            current=Path("/tmp/current.png"),
        )
        assert result.name == "test"
        assert result.passed is True
        assert result.diff_ratio == 0.0
        assert result.diff_pixels == 0
        assert result.total_pixels == 10000
        assert result.diff_image is None
