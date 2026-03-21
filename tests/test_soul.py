"""Tests for trellis.mind.soul — SOUL.md loading and parsing."""

import pytest
from pathlib import Path

from trellis.mind.soul import load_soul, load_soul_local, _extract_sections


@pytest.fixture
def agents_dir(tmp_path):
    """Create a minimal agents/ivy/SOUL.md for testing."""
    ivy_dir = tmp_path / "ivy"
    ivy_dir.mkdir()
    soul = (
        "# Ivy — Agent Soul\n\n"
        "## Identity\n\n"
        "You are Ivy, a test assistant.\n\n"
        "## Personality\n\n"
        "- Direct and concise.\n"
        "- Uses garden metaphors.\n\n"
        "## Operating Modes\n\n"
        "### Co-op Mode\n"
        "- Collaborate in real-time\n\n"
        "## Roles\n\n"
        "### Researcher\n"
        "- Explore broadly\n\n"
        "## Constraints\n\n"
        "- Never fabricate information.\n"
    )
    (ivy_dir / "SOUL.md").write_text(soul, encoding="utf-8")
    return str(tmp_path)


class TestLoadSoul:
    def test_loads_full_soul(self, agents_dir):
        soul = load_soul(agents_dir=agents_dir)
        assert "Ivy" in soul
        assert "Operating Modes" in soul
        assert "Roles" in soul

    def test_missing_soul_returns_empty(self, tmp_path):
        assert load_soul(agents_dir=str(tmp_path)) == ""


class TestLoadSoulLocal:
    def test_condensed_includes_identity(self, agents_dir):
        local = load_soul_local(agents_dir=agents_dir)
        assert "You are Ivy" in local

    def test_condensed_includes_personality(self, agents_dir):
        local = load_soul_local(agents_dir=agents_dir)
        assert "garden metaphors" in local

    def test_condensed_includes_constraints(self, agents_dir):
        local = load_soul_local(agents_dir=agents_dir)
        assert "Never fabricate" in local

    def test_condensed_excludes_roles(self, agents_dir):
        local = load_soul_local(agents_dir=agents_dir)
        assert "Researcher" not in local

    def test_condensed_excludes_operating_modes(self, agents_dir):
        local = load_soul_local(agents_dir=agents_dir)
        assert "Co-op Mode" not in local

    def test_condensed_has_grounding_rule(self, agents_dir):
        local = load_soul_local(agents_dir=agents_dir)
        assert "Never invent" in local

    def test_missing_soul_returns_empty(self, tmp_path):
        assert load_soul_local(agents_dir=str(tmp_path)) == ""


class TestExtractSections:
    def test_basic_extraction(self):
        md = "## Foo\n\nfoo content\n\n## Bar\n\nbar content\n"
        sections = _extract_sections(md)
        assert "Foo" in sections
        assert "Bar" in sections
        assert "foo content" in sections["Foo"]
        assert "bar content" in sections["Bar"]

    def test_empty_document(self):
        assert _extract_sections("") == {}

    def test_no_headings(self):
        assert _extract_sections("just some text\nno headings") == {}

    def test_heading_with_extra_whitespace(self):
        sections = _extract_sections("## Spaced  \n\ncontent here\n")
        assert "Spaced" in sections
