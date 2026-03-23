"""Tests for trellis.mind.soul — SOUL.md and kyle.md loading and parsing."""

import pytest

from trellis.mind.soul import (
    _extract_sections,
    load_kyle,
    load_kyle_local,
    load_soul,
    load_soul_local,
)


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


@pytest.fixture
def vault_with_kyle(tmp_path):
    """Create a vault with _ivy/kyle.md for testing."""
    ivy_dir = tmp_path / "_ivy"
    ivy_dir.mkdir()
    kyle_md = (
        "# Kyle — Professional Context Model\n\n"
        "## 1. Who Kyle Is\n\n"
        "Kyle is the CEO of Mirror Factory.\n\n"
        "## 4. Energy Architecture\n\n"
        "Morning block (8–12) is sacred focus time.\n"
        "Afternoon is meetings and admin.\n\n"
        "## 5. Weekly Operating Framework\n\n"
        "Monday: Planning. Tuesday–Thursday: Deep work.\n"
        "Friday: Review and reflection.\n\n"
        "## 9. Communication Preferences\n\n"
        "- Be direct. No preamble.\n"
        "- Recommendations over options.\n"
        "- Say what you'd do, then why.\n\n"
        "## 15. Current Projects & Priorities (March 2026)\n\n"
        "Trellis, Layers, Tennis Social.\n\n"
        "## 17. What Ivy Should Know About the Relationship\n\n"
        "Progressive delegation model.\n\n"
        "### What \"Good\" Looks Like\n\n"
        "- Ivy proposes, Kyle approves.\n"
        "- Concrete recommendations with tradeoffs.\n\n"
        "### What \"Bad\" Looks Like\n\n"
        "- Generic output without context.\n\n"
        "### What \"Great\" Looks Like\n\n"
        "Kyle forgets he's working with an agent.\n"
    )
    (ivy_dir / "kyle.md").write_text(kyle_md, encoding="utf-8")
    return tmp_path


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


class TestLoadKyle:
    def test_loads_full_kyle(self, vault_with_kyle):
        content = load_kyle(vault_with_kyle)
        assert "Kyle — Professional Context Model" in content
        assert "Energy Architecture" in content
        assert "Communication Preferences" in content
        assert "Current Projects" in content
        assert "Who Kyle Is" in content

    def test_missing_kyle_returns_empty(self, tmp_path):
        """When kyle.md doesn't exist, return empty string gracefully."""
        assert load_kyle(tmp_path) == ""

    def test_missing_vault_returns_empty(self, tmp_path):
        """When vault path doesn't have _ivy/ at all, return empty string."""
        assert load_kyle(tmp_path / "nonexistent") == ""

    def test_accepts_string_path(self, vault_with_kyle):
        """vault_path can be a string, not just a Path."""
        content = load_kyle(str(vault_with_kyle))
        assert "Energy Architecture" in content


class TestLoadKyleLocal:
    def test_condensed_includes_energy_architecture(self, vault_with_kyle):
        local = load_kyle_local(vault_with_kyle)
        assert "Energy Architecture" in local
        assert "Morning block" in local

    def test_condensed_includes_weekly_framework(self, vault_with_kyle):
        local = load_kyle_local(vault_with_kyle)
        assert "Weekly Operating Framework" in local
        assert "Deep work" in local

    def test_condensed_includes_communication_preferences(self, vault_with_kyle):
        local = load_kyle_local(vault_with_kyle)
        assert "Communication Preferences" in local
        assert "Be direct" in local

    def test_condensed_includes_relationship_section(self, vault_with_kyle):
        """Extracts the relationship section containing Good/Bad/Great."""
        local = load_kyle_local(vault_with_kyle)
        assert "What Ivy Should Know About the Relationship" in local
        assert "Good" in local
        assert "Bad" in local
        assert "Great" in local

    def test_condensed_excludes_who_kyle_is(self, vault_with_kyle):
        """Full bio section is excluded from condensed version."""
        local = load_kyle_local(vault_with_kyle)
        assert "CEO of Mirror Factory" not in local

    def test_condensed_excludes_current_projects(self, vault_with_kyle):
        """Current projects section is excluded (too prone to hallucination)."""
        local = load_kyle_local(vault_with_kyle)
        assert "Tennis Social" not in local

    def test_condensed_has_grounding_rule(self, vault_with_kyle):
        local = load_kyle_local(vault_with_kyle)
        assert "Never invent" in local

    def test_condensed_has_title(self, vault_with_kyle):
        local = load_kyle_local(vault_with_kyle)
        assert local.startswith("# Kyle — Working Context")

    def test_missing_kyle_returns_empty(self, tmp_path):
        assert load_kyle_local(tmp_path) == ""

    def test_kyle_with_no_matching_sections(self, tmp_path):
        """kyle.md exists but has no matching sections — returns empty."""
        ivy_dir = tmp_path / "_ivy"
        ivy_dir.mkdir()
        (ivy_dir / "kyle.md").write_text(
            "# Kyle\n\n## Random Section\n\nNo useful headings.\n",
            encoding="utf-8",
        )
        assert load_kyle_local(tmp_path) == ""


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
