"""Screenshot comparison module for visual regression testing.

Compares current screenshots against saved baselines using pixel-level
diff analysis. Generates visual diff images highlighting changed pixels.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass
class CompareResult:
    """Result of comparing a screenshot against its baseline."""

    name: str
    passed: bool
    diff_ratio: float
    diff_pixels: int
    total_pixels: int
    diff_image: Path | None
    baseline: Path
    current: Path


class ScreenshotComparer:
    """Compares screenshots against baselines with configurable threshold.

    Args:
        baseline_dir: Directory containing baseline reference images.
        output_dir: Directory for diff images and current screenshots.
        threshold: Max allowed pixel diff ratio (0.01 = 1% pixels can differ).
    """

    def __init__(
        self,
        baseline_dir: Path,
        output_dir: Path,
        threshold: float = 0.01,
    ) -> None:
        self.baseline_dir = baseline_dir
        self.output_dir = output_dir
        self.threshold = threshold
        self.diff_dir = output_dir / "diffs"

    def compare(self, name: str, current: Path) -> CompareResult:
        """Compare current screenshot against baseline.

        Args:
            name: Test name (used to find baseline file as {name}.png).
            current: Path to the current screenshot image.

        Returns:
            CompareResult with pass/fail status and diff metrics.

        Raises:
            FileNotFoundError: If no baseline exists for this name.
        """
        baseline = self.baseline_dir / f"{name}.png"
        if not baseline.exists():
            raise FileNotFoundError(
                f"No baseline found for '{name}' at {baseline}. "
                f"Run with --baseline to capture reference images."
            )

        baseline_img = Image.open(baseline).convert("RGBA")
        current_img = Image.open(current).convert("RGBA")

        # Resize current to match baseline if dimensions differ
        if current_img.size != baseline_img.size:
            current_img = current_img.resize(baseline_img.size, Image.LANCZOS)

        baseline_pixels = list(baseline_img.getdata())
        current_pixels = list(current_img.getdata())
        total_pixels = len(baseline_pixels)

        diff_pixels = 0
        for bp, cp in zip(baseline_pixels, current_pixels):
            if bp != cp:
                diff_pixels += 1

        diff_ratio = diff_pixels / total_pixels if total_pixels > 0 else 0.0
        passed = diff_ratio <= self.threshold

        diff_image: Path | None = None
        if not passed:
            diff_image = self.generate_diff_image(baseline, current)
            # Rename to include the test name
            named_diff = self.diff_dir / f"{name}-diff.png"
            if diff_image != named_diff:
                shutil.move(str(diff_image), str(named_diff))
                diff_image = named_diff

        return CompareResult(
            name=name,
            passed=passed,
            diff_ratio=diff_ratio,
            diff_pixels=diff_pixels,
            total_pixels=total_pixels,
            diff_image=diff_image,
            baseline=baseline,
            current=current,
        )

    def save_baseline(self, name: str, image: Path) -> Path:
        """Save image as new baseline.

        Args:
            name: Test name (saved as {name}.png).
            image: Path to the image to save as baseline.

        Returns:
            Path to the saved baseline file.
        """
        self.baseline_dir.mkdir(parents=True, exist_ok=True)
        dest = self.baseline_dir / f"{name}.png"
        shutil.copy2(str(image), str(dest))
        return dest

    def generate_diff_image(self, baseline: Path, current: Path) -> Path:
        """Generate visual diff highlighting changed pixels in red.

        Creates a dimmed version of the baseline with differing pixels
        highlighted in bright red for easy visual identification.

        Args:
            baseline: Path to the baseline image.
            current: Path to the current image.

        Returns:
            Path to the generated diff image.
        """
        self.diff_dir.mkdir(parents=True, exist_ok=True)

        baseline_img = Image.open(baseline).convert("RGBA")
        current_img = Image.open(current).convert("RGBA")

        if current_img.size != baseline_img.size:
            current_img = current_img.resize(baseline_img.size, Image.LANCZOS)

        # Create dimmed version of baseline as the diff background
        width, height = baseline_img.size
        diff_img = Image.new("RGBA", (width, height))

        baseline_pixels = list(baseline_img.getdata())
        current_pixels = list(current_img.getdata())

        diff_data: list[tuple[int, int, int, int]] = []
        for bp, cp in zip(baseline_pixels, current_pixels):
            if bp != cp:
                # Highlight differing pixels in red
                diff_data.append((255, 0, 0, 255))
            else:
                # Dim unchanged pixels (50% opacity blend with gray)
                r = bp[0] // 2 + 64
                g = bp[1] // 2 + 64
                b = bp[2] // 2 + 64
                diff_data.append((r, g, b, 255))

        diff_img.putdata(diff_data)

        # Use baseline filename as basis for diff filename
        diff_path = self.diff_dir / f"diff-{baseline.name}"
        diff_img.save(str(diff_path), "PNG")
        return diff_path
