"""Tests for trellis.memory.journal — Daily journal logging."""

import pytest
from datetime import datetime

from trellis.memory.journal import get_today_journal_path, log_entry


class TestGetTodayJournalPath:
    def test_creates_directory_structure(self, tmp_path):
        path = get_today_journal_path(tmp_path)
        assert path.parent.exists()
        assert path.parent.name == "journal"
        assert path.parent.parent.name == "_ivy"

    def test_creates_file_with_header(self, tmp_path):
        path = get_today_journal_path(tmp_path)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        today = datetime.now().strftime("%Y-%m-%d")
        assert f"# Ivy Journal — {today}" in content

    def test_idempotent(self, tmp_path):
        path1 = get_today_journal_path(tmp_path)
        path1.write_text("existing content\n", encoding="utf-8")
        path2 = get_today_journal_path(tmp_path)
        assert path1 == path2
        # Should not overwrite existing content
        assert path2.read_text(encoding="utf-8") == "existing content\n"


class TestLogEntry:
    def test_appends_entry(self, tmp_path):
        log_entry(tmp_path, "TEST", "test summary")
        path = get_today_journal_path(tmp_path)
        content = path.read_text(encoding="utf-8")
        assert "TEST" in content
        assert "test summary" in content

    def test_includes_details(self, tmp_path):
        log_entry(tmp_path, "TEST", "summary", details="detailed info here")
        path = get_today_journal_path(tmp_path)
        content = path.read_text(encoding="utf-8")
        assert "detailed info here" in content

    def test_multiple_entries_append(self, tmp_path):
        log_entry(tmp_path, "FIRST", "entry one")
        log_entry(tmp_path, "SECOND", "entry two")
        path = get_today_journal_path(tmp_path)
        content = path.read_text(encoding="utf-8")
        assert "entry one" in content
        assert "entry two" in content
        # Both should be in the same file
        assert content.count("---") >= 2
