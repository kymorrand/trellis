"""Tests for trellis.core.quest — Quest file schema, parsing, and serialization."""

from datetime import date
from pathlib import Path

import pytest

from trellis.core.quest import (
    Quest,
    QuestStep,
    _extract_body_sections,
    _parse_steps,
    _serialize_steps,
    _split_frontmatter_and_body,
    list_quests,
    load_quest,
    save_quest,
)


# ─── Fixtures ────────────────────────────────────────────────

SAMPLE_QUEST = """\
---
id: mm-research
title: M&M Business Model Research
status: active
type: research
priority: high
role: researcher
created: 2026-03-28
updated: 2026-03-28
tick_interval: 5m
tick_window: 8am-11pm
budget_claude: 50
budget_spent_claude: 12
steps_completed: 3
goal_hash: abc123
drift_check_interval: 5
---

## Goal

Research viable business models for M&M.

## Success criteria

- At least 3 validated options
- Competitive landscape analysis

## Steps

- [x] Define scope
- [x] Survey competitors
- [ ] Analyze pricing <!-- blocked_by: survey-competitors -->
- [ ] Write recommendation

## Questions

- **[urgent]** Focus on dev tools or end-user?

## Artifacts

- `research/landscape.md`

## Log

- 2026-03-28 10:00 — Quest created

## Blockers

- Waiting on Kyle's direction
"""


@pytest.fixture
def quest_file(tmp_path: Path) -> Path:
    """Create a sample quest file."""
    f = tmp_path / "mm-research.md"
    f.write_text(SAMPLE_QUEST, encoding="utf-8")
    return f


@pytest.fixture
def quests_dir(tmp_path: Path) -> Path:
    """Create a quests directory with multiple quest files."""
    qdir = tmp_path / "quests"
    qdir.mkdir()
    (qdir / "_templates").mkdir()
    (qdir / "_archive").mkdir()

    # Active quest — high priority
    (qdir / "quest-a.md").write_text(
        "---\nid: quest-a\ntitle: Quest A\nstatus: active\npriority: high\n"
        "updated: 2026-03-28\n---\n\n## Goal\n\nDo A.\n",
        encoding="utf-8",
    )
    # Draft quest — low priority
    (qdir / "quest-b.md").write_text(
        "---\nid: quest-b\ntitle: Quest B\nstatus: draft\npriority: low\n"
        "updated: 2026-03-27\n---\n\n## Goal\n\nDo B.\n",
        encoding="utf-8",
    )
    # Urgent quest
    (qdir / "quest-c.md").write_text(
        "---\nid: quest-c\ntitle: Quest C\nstatus: active\npriority: urgent\n"
        "updated: 2026-03-29\n---\n\n## Goal\n\nDo C.\n",
        encoding="utf-8",
    )
    # Template (should be skipped by list_quests since it's in _templates/)
    (qdir / "_templates" / "template.md").write_text(
        "---\nid: template\ntitle: Template\n---\n\n## Goal\n\nTemplate.\n",
        encoding="utf-8",
    )
    return qdir


# ─── Frontmatter parsing ─────────────────────────────────────

class TestSplitFrontmatter:
    def test_basic_split(self):
        fm, body = _split_frontmatter_and_body("---\ntitle: Test\n---\n\nBody here.")
        assert fm == {"title": "Test"}
        assert "Body here" in body

    def test_no_frontmatter(self):
        fm, body = _split_frontmatter_and_body("Just body text.")
        assert fm == {}
        assert "Just body text" in body

    def test_invalid_yaml(self):
        fm, body = _split_frontmatter_and_body("---\n: : bad\n---\n\nBody.")
        # Should fall back gracefully
        assert isinstance(fm, dict)

    def test_non_dict_yaml(self):
        fm, body = _split_frontmatter_and_body("---\n- item1\n- item2\n---\n\nBody.")
        assert fm == {}

    def test_unclosed_frontmatter(self):
        fm, body = _split_frontmatter_and_body("---\ntitle: Test\nNo closing.")
        assert fm == {}


# ─── Body section extraction ─────────────────────────────────

class TestExtractBodySections:
    def test_basic_sections(self):
        body = "## Goal\n\nDo the thing.\n\n## Steps\n\n- [x] Done"
        sections = _extract_body_sections(body)
        assert "goal" in sections
        assert "steps" in sections
        assert "Do the thing" in sections["goal"]

    def test_empty_body(self):
        assert _extract_body_sections("") == {}

    def test_no_sections(self):
        assert _extract_body_sections("just text, no headings") == {}

    def test_case_insensitive_keys(self):
        body = "## Success Criteria\n\nMust work."
        sections = _extract_body_sections(body)
        assert "success criteria" in sections


# ─── Step parsing ─────────────────────────────────────────────

class TestParseSteps:
    def test_basic_steps(self):
        text = "- [ ] Step one\n- [x] Step two\n- [ ] Step three"
        steps = _parse_steps(text)
        assert len(steps) == 3
        assert steps[0].text == "Step one"
        assert steps[0].done is False
        assert steps[1].done is True

    def test_blocked_by(self):
        text = "- [ ] Build thing <!-- blocked_by: design-phase -->"
        steps = _parse_steps(text)
        assert len(steps) == 1
        assert steps[0].blocked_by == "design-phase"
        assert "blocked_by" not in steps[0].text

    def test_empty_text(self):
        assert _parse_steps("") == []

    def test_non_checkbox_lines_skipped(self):
        text = "Some preamble\n- [ ] Real step\nAnother line"
        steps = _parse_steps(text)
        assert len(steps) == 1

    def test_uppercase_x(self):
        text = "- [X] Done step"
        steps = _parse_steps(text)
        assert steps[0].done is True


class TestSerializeSteps:
    def test_roundtrip(self):
        steps = [
            QuestStep(text="Step one", done=False),
            QuestStep(text="Step two", done=True),
            QuestStep(text="Step three", done=False, blocked_by="step-two"),
        ]
        serialized = _serialize_steps(steps)
        reparsed = _parse_steps(serialized)
        assert len(reparsed) == 3
        assert reparsed[0].text == "Step one"
        assert reparsed[1].done is True
        assert reparsed[2].blocked_by == "step-two"


# ─── Quest loading ────────────────────────────────────────────

class TestLoadQuest:
    def test_loads_basic_fields(self, quest_file: Path):
        q = load_quest(quest_file)
        assert q.id == "mm-research"
        assert q.title == "M&M Business Model Research"
        assert q.status == "active"
        assert q.type == "research"
        assert q.priority == "high"
        assert q.role == "researcher"

    def test_loads_dates(self, quest_file: Path):
        q = load_quest(quest_file)
        assert q.created == date(2026, 3, 28)
        assert q.updated == date(2026, 3, 28)

    def test_loads_budget(self, quest_file: Path):
        q = load_quest(quest_file)
        assert q.budget_claude == 50
        assert q.budget_spent_claude == 12

    def test_loads_tick_config(self, quest_file: Path):
        q = load_quest(quest_file)
        assert q.tick_interval == "5m"
        assert q.tick_window == "8am-11pm"

    def test_loads_goal_section(self, quest_file: Path):
        q = load_quest(quest_file)
        assert "viable business models" in q.goal

    def test_loads_success_criteria(self, quest_file: Path):
        q = load_quest(quest_file)
        assert "3 validated options" in q.success_criteria

    def test_loads_steps(self, quest_file: Path):
        q = load_quest(quest_file)
        assert len(q.steps) == 4
        assert q.steps[0].done is True
        assert q.steps[2].blocked_by == "survey-competitors"

    def test_loads_questions(self, quest_file: Path):
        q = load_quest(quest_file)
        assert "urgent" in q.questions

    def test_loads_artifacts(self, quest_file: Path):
        q = load_quest(quest_file)
        assert "landscape.md" in q.artifacts

    def test_loads_log(self, quest_file: Path):
        q = load_quest(quest_file)
        assert "Quest created" in q.log

    def test_loads_blockers(self, quest_file: Path):
        q = load_quest(quest_file)
        assert "Kyle's direction" in q.blockers

    def test_total_steps_property(self, quest_file: Path):
        q = load_quest(quest_file)
        assert q.total_steps == 4

    def test_compute_goal_hash(self, quest_file: Path):
        q = load_quest(quest_file)
        h = q.compute_goal_hash()
        assert len(h) == 12
        # Deterministic
        assert q.compute_goal_hash() == h

    def test_file_not_found(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_quest(tmp_path / "nonexistent.md")

    def test_missing_frontmatter_uses_defaults(self, tmp_path: Path):
        f = tmp_path / "minimal.md"
        f.write_text("## Goal\n\nJust a goal.\n", encoding="utf-8")
        q = load_quest(f)
        assert q.id == "minimal"
        assert q.status == "draft"
        assert q.type == "research"
        assert q.priority == "standard"

    def test_invalid_status_uses_default(self, tmp_path: Path):
        f = tmp_path / "bad-status.md"
        f.write_text("---\nstatus: invalid_status\n---\n\n## Goal\n\nTest.\n", encoding="utf-8")
        q = load_quest(f)
        assert q.status == "draft"

    def test_invalid_type_uses_default(self, tmp_path: Path):
        f = tmp_path / "bad-type.md"
        f.write_text("---\ntype: invalid_type\n---\n\n## Goal\n\nTest.\n", encoding="utf-8")
        q = load_quest(f)
        assert q.type == "research"

    def test_invalid_priority_uses_default(self, tmp_path: Path):
        f = tmp_path / "bad-priority.md"
        f.write_text("---\npriority: critical\n---\n\n## Goal\n\nTest.\n", encoding="utf-8")
        q = load_quest(f)
        assert q.priority == "standard"

    def test_extra_frontmatter_preserved(self, tmp_path: Path):
        f = tmp_path / "extra-fm.md"
        f.write_text(
            "---\nid: test\ncustom_field: custom_value\n---\n\n## Goal\n\nTest.\n",
            encoding="utf-8",
        )
        q = load_quest(f)
        assert q.extra.get("custom_field") == "custom_value"

    def test_empty_sections(self, tmp_path: Path):
        """Quest with no body sections at all."""
        f = tmp_path / "empty-body.md"
        f.write_text("---\nid: empty\ntitle: Empty Quest\n---\n", encoding="utf-8")
        q = load_quest(f)
        assert q.goal == ""
        assert q.steps == []
        assert q.log == ""

    def test_id_from_filename(self, tmp_path: Path):
        """When frontmatter has no id, use filename stem."""
        f = tmp_path / "my-quest-name.md"
        f.write_text("---\ntitle: My Quest\n---\n\n## Goal\n\nTest.\n", encoding="utf-8")
        q = load_quest(f)
        assert q.id == "my-quest-name"

    def test_title_from_id(self, tmp_path: Path):
        """When frontmatter has no title, derive from id."""
        f = tmp_path / "auto-title-test.md"
        f.write_text("---\nid: auto-title-test\n---\n\n## Goal\n\nTest.\n", encoding="utf-8")
        q = load_quest(f)
        assert q.title == "Auto Title Test"


# ─── Quest saving ─────────────────────────────────────────────

class TestSaveQuest:
    def test_creates_file(self, tmp_path: Path):
        q = Quest(id="test", title="Test Quest")
        out = tmp_path / "test.md"
        save_quest(q, out)
        assert out.exists()

    def test_saved_file_has_frontmatter(self, tmp_path: Path):
        q = Quest(id="test", title="Test Quest", status="active")
        out = tmp_path / "test.md"
        save_quest(q, out)
        content = out.read_text(encoding="utf-8")
        assert content.startswith("---\n")
        assert "status: active" in content

    def test_saved_file_has_sections(self, tmp_path: Path):
        q = Quest(
            id="test",
            title="Test Quest",
            goal="Do the thing.",
            success_criteria="Thing is done.",
        )
        out = tmp_path / "test.md"
        save_quest(q, out)
        content = out.read_text(encoding="utf-8")
        assert "## Goal" in content
        assert "Do the thing" in content
        assert "## Success criteria" in content

    def test_creates_parent_dirs(self, tmp_path: Path):
        q = Quest(id="test", title="Test Quest")
        out = tmp_path / "nested" / "dir" / "test.md"
        save_quest(q, out)
        assert out.exists()

    def test_saves_steps(self, tmp_path: Path):
        q = Quest(
            id="test",
            title="Test",
            steps=[
                QuestStep(text="First", done=True),
                QuestStep(text="Second", done=False, blocked_by="first"),
            ],
        )
        out = tmp_path / "test.md"
        save_quest(q, out)
        content = out.read_text(encoding="utf-8")
        assert "- [x] First" in content
        assert "- [ ] Second <!-- blocked_by: first -->" in content

    def test_saves_dates_as_iso(self, tmp_path: Path):
        q = Quest(id="test", title="Test", created=date(2026, 3, 28))
        out = tmp_path / "test.md"
        save_quest(q, out)
        content = out.read_text(encoding="utf-8")
        assert "'2026-03-28'" in content or "2026-03-28" in content


# ─── Round-trip fidelity ──────────────────────────────────────

class TestRoundTrip:
    def test_load_save_load(self, quest_file: Path, tmp_path: Path):
        """load → save → load should produce identical state."""
        q1 = load_quest(quest_file)
        out = tmp_path / "roundtrip.md"
        save_quest(q1, out)
        q2 = load_quest(out)

        assert q1.id == q2.id
        assert q1.title == q2.title
        assert q1.status == q2.status
        assert q1.type == q2.type
        assert q1.priority == q2.priority
        assert q1.role == q2.role
        assert q1.created == q2.created
        assert q1.updated == q2.updated
        assert q1.tick_interval == q2.tick_interval
        assert q1.tick_window == q2.tick_window
        assert q1.budget_claude == q2.budget_claude
        assert q1.budget_spent_claude == q2.budget_spent_claude
        assert q1.steps_completed == q2.steps_completed
        assert q1.goal_hash == q2.goal_hash
        assert q1.drift_check_interval == q2.drift_check_interval
        assert q1.goal == q2.goal
        assert q1.success_criteria == q2.success_criteria
        assert len(q1.steps) == len(q2.steps)
        for s1, s2 in zip(q1.steps, q2.steps):
            assert s1.text == s2.text
            assert s1.done == s2.done
            assert s1.blocked_by == s2.blocked_by
        assert q1.questions == q2.questions
        assert q1.artifacts == q2.artifacts
        assert q1.log == q2.log
        assert q1.blockers == q2.blockers

    def test_roundtrip_minimal(self, tmp_path: Path):
        """Round-trip a minimal quest with only defaults."""
        q1 = Quest(id="minimal", title="Minimal Quest")
        out = tmp_path / "minimal.md"
        save_quest(q1, out)
        q2 = load_quest(out)
        assert q1.id == q2.id
        assert q1.title == q2.title
        assert q1.status == q2.status

    def test_roundtrip_extra_frontmatter(self, tmp_path: Path):
        """Extra frontmatter fields survive round-trip."""
        q1 = Quest(id="extra", title="Extra", extra={"custom_key": "custom_value"})
        out = tmp_path / "extra.md"
        save_quest(q1, out)
        q2 = load_quest(out)
        assert q2.extra.get("custom_key") == "custom_value"


# ─── List quests ──────────────────────────────────────────────

class TestListQuests:
    def test_lists_all_quests(self, quests_dir: Path):
        quests = list_quests(quests_dir)
        ids = [q.id for q in quests]
        assert "quest-a" in ids
        assert "quest-b" in ids
        assert "quest-c" in ids

    def test_skips_templates(self, quests_dir: Path):
        """Templates in _templates/ should not appear in list."""
        quests = list_quests(quests_dir)
        ids = [q.id for q in quests]
        assert "template" not in ids

    def test_sorted_by_priority(self, quests_dir: Path):
        quests = list_quests(quests_dir)
        assert quests[0].priority == "urgent"
        assert quests[1].priority == "high"
        assert quests[2].priority == "low"

    def test_empty_directory(self, tmp_path: Path):
        empty = tmp_path / "empty_quests"
        empty.mkdir()
        assert list_quests(empty) == []

    def test_nonexistent_directory(self, tmp_path: Path):
        assert list_quests(tmp_path / "nope") == []

    def test_bad_file_skipped(self, tmp_path: Path):
        """A malformed file should be skipped, not crash the listing."""
        qdir = tmp_path / "quests"
        qdir.mkdir()
        # Good quest
        (qdir / "good.md").write_text(
            "---\nid: good\ntitle: Good\n---\n\n## Goal\n\nGood.\n",
            encoding="utf-8",
        )
        # Binary garbage (will fail YAML parse but shouldn't crash)
        (qdir / "bad.md").write_bytes(b"\x00\x01\x02\x03")
        quests = list_quests(qdir)
        # At least the good one loads
        assert len(quests) >= 1
        assert quests[0].id == "good"
