"""Tests for trellis.core.heartbeat — Heartbeat scheduler and journal parsing."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from trellis.core.heartbeat import HeartbeatScheduler, parse_journal_stats


@pytest.fixture
def vault(tmp_path):
    """Create a minimal vault structure for heartbeat tests."""
    # Journal directory
    journal_dir = tmp_path / "_ivy" / "journal"
    journal_dir.mkdir(parents=True)

    # Inbox with some items
    inbox_dir = tmp_path / "_ivy" / "inbox" / "drops"
    inbox_dir.mkdir(parents=True)
    (inbox_dir / "2026-03-21-test-note.md").write_text("# Test note\nSome content\n")

    # Queue directory with an item
    queue_dir = tmp_path / "_ivy" / "queue"
    queue_dir.mkdir(parents=True)
    (queue_dir / "pending-review.md").write_text("# Review needed\n")

    # Knowledge files
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "ai-agents.md").write_text("# AI Agents\n")
    (knowledge / "solarpunk.md").write_text("# Solarpunk\n")

    return tmp_path


@pytest.fixture
def heartbeat(vault):
    """Create a heartbeat scheduler with a mock Discord callback."""
    discord_post = AsyncMock()
    hb = HeartbeatScheduler(
        vault_path=vault,
        budget_monthly=100.0,
        discord_post_callback=discord_post,
    )
    return hb


class TestParseJournalStats:
    def test_empty_journal(self, vault):
        stats = parse_journal_stats(vault, "2026-01-01")
        assert stats["messages_in"] == 0
        assert stats["messages_out"] == 0
        assert stats["vault_saves"] == 0
        assert stats["cost_usd"] == 0.0

    def test_nonexistent_journal(self, tmp_path):
        stats = parse_journal_stats(tmp_path, "9999-01-01")
        assert stats["messages_in"] == 0

    def test_parses_message_counts(self, vault):
        journal_path = vault / "_ivy" / "journal" / "2026-03-21.md"
        journal_path.write_text(
            "# Ivy Journal — 2026-03-21\n\n"
            "## 10:00:00 | MESSAGE_IN\nKyle in #general\nHello\n\n---\n\n"
            "## 10:00:05 | MESSAGE_OUT\nIvy → #general via qwen3:14b\nHi Kyle!\n\n---\n\n"
            "## 10:05:00 | MESSAGE_IN\nKyle in #general\nSave this: test\n\n---\n\n"
            "## 10:05:01 | VAULT_SAVE\nSave request from Kyle\n\n---\n\n"
            "## 10:05:02 | MESSAGE_OUT\nIvy → #general via claude\nSaved!\n\n---\n\n",
            encoding="utf-8",
        )
        stats = parse_journal_stats(vault, "2026-03-21")
        assert stats["messages_in"] == 2
        assert stats["messages_out"] == 2
        assert stats["vault_saves"] == 1

    def test_parses_cost(self, vault):
        journal_path = vault / "_ivy" / "journal" / "2026-03-21.md"
        journal_path.write_text(
            "# Ivy Journal\n\n"
            "### 10:00:00 | AUDIT | discord_reply\n"
            "- **Target:** #general\n"
            "- **Input:** hello\n"
            "- **Output:** hi\n"
            "- **Model:** claude-sonnet-4-20250514\n"
            "- **Cost:** $0.0042\n\n"
            "### 11:00:00 | AUDIT | discord_reply\n"
            "- **Cost:** $0.0058\n\n",
            encoding="utf-8",
        )
        stats = parse_journal_stats(vault, "2026-03-21")
        assert abs(stats["cost_usd"] - 0.01) < 0.0001


class TestHeartbeatScheduler:
    def test_initial_state(self, heartbeat):
        assert heartbeat.is_running is False
        assert heartbeat.started_at is None
        assert heartbeat.tick_count == 0

    @pytest.mark.asyncio
    async def test_inbox_check_finds_files(self, heartbeat, vault):
        await heartbeat._check_inbox(datetime.now())
        # Should have logged to journal
        journal_dir = vault / "_ivy" / "journal"
        journals = list(journal_dir.glob("*.md"))
        assert len(journals) >= 1
        content = journals[0].read_text(encoding="utf-8")
        assert "HEARTBEAT_INBOX" in content
        assert "1 items detected" in content

    @pytest.mark.asyncio
    async def test_inbox_check_empty(self, tmp_path):
        """Inbox check on vault with no inbox dir doesn't crash."""
        hb = HeartbeatScheduler(vault_path=tmp_path)
        await hb._check_inbox(datetime.now())  # Should not raise

    @pytest.mark.asyncio
    async def test_journal_rollover_creates_tomorrow(self, heartbeat, vault):
        now = datetime.now()
        await heartbeat._journal_rollover(now)
        tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        tomorrow_path = vault / "_ivy" / "journal" / f"{tomorrow_str}.md"
        assert tomorrow_path.exists()
        assert f"# Ivy Journal — {tomorrow_str}" in tomorrow_path.read_text()

    @pytest.mark.asyncio
    async def test_cost_report_under_budget(self, heartbeat):
        """Cost report under 75% should not post to Discord."""
        await heartbeat._cost_report(datetime.now())
        heartbeat._discord_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_cost_report_over_budget(self, vault):
        """Cost report over 75% should post a warning to Discord."""
        discord_post = AsyncMock()
        hb = HeartbeatScheduler(
            vault_path=vault,
            budget_monthly=0.01,  # Very low budget
            discord_post_callback=discord_post,
        )
        # Write a journal with some cost
        journal_path = vault / "_ivy" / "journal" / (datetime.now().strftime("%Y-%m-%d") + ".md")
        Path(journal_path).write_text(
            "# Journal\n### 10:00 | AUDIT | reply\n- **Cost:** $0.05\n\n",
            encoding="utf-8",
        )
        await hb._cost_report(datetime.now())
        discord_post.assert_called_once()
        call_arg = discord_post.call_args[0][0]
        assert "Budget alert" in call_arg

    @pytest.mark.asyncio
    async def test_morning_brief(self, heartbeat, vault):
        """Morning brief should post to Discord."""
        await heartbeat._morning_brief(datetime.now())
        heartbeat._discord_post.assert_called_once()
        call_arg = heartbeat._discord_post.call_args[0][0]
        assert "Morning Brief" in call_arg
        assert "1 item" in call_arg
        assert "Vault:" in call_arg

    @pytest.mark.asyncio
    async def test_end_of_day(self, heartbeat, vault):
        """EOD summary should post to Discord."""
        await heartbeat._end_of_day(datetime.now())
        heartbeat._discord_post.assert_called_once()
        call_arg = heartbeat._discord_post.call_args[0][0]
        assert "End of Day" in call_arg
        assert "API cost today" in call_arg

    @pytest.mark.asyncio
    async def test_status_report(self, heartbeat, vault):
        """Status report should include key metrics."""
        heartbeat._started_at = datetime.now() - timedelta(hours=2, minutes=30)
        heartbeat._tick_count = 150
        report = await heartbeat.get_status_report()
        assert "Ivy Status Report" in report
        assert "2h 30m" in report
        assert "150" in report
        assert "Vault:" in report

    def test_count_queue_items(self, heartbeat, vault):
        assert heartbeat._count_queue_items() == 1

    def test_count_vault_files(self, heartbeat, vault):
        # 2 knowledge files, internal files should be excluded
        assert heartbeat._count_vault_files() == 2

    @pytest.mark.asyncio
    async def test_nightly_backup_logs_on_error(self, vault):
        """Backup should log failure and alert Discord when git fails."""
        discord_post = AsyncMock()
        hb = HeartbeatScheduler(
            vault_path=vault / "nonexistent",
            discord_post_callback=discord_post,
        )
        await hb._nightly_backup()
        discord_post.assert_called_once()
        call_arg = discord_post.call_args[0][0]
        assert "🚨" in call_arg

    @pytest.mark.asyncio
    async def test_tick_increments_counter(self, heartbeat):
        assert heartbeat.tick_count == 0
        await heartbeat._tick()
        assert heartbeat.tick_count == 1
        await heartbeat._tick()
        assert heartbeat.tick_count == 2

    @pytest.mark.asyncio
    async def test_start_and_stop(self, heartbeat):
        """Heartbeat should start, tick, and stop cleanly."""
        async def stop_after_delay():
            await asyncio.sleep(0.2)
            await heartbeat.stop()

        # Run heartbeat with a very short sleep override
        task = asyncio.create_task(heartbeat.start())
        stop_task = asyncio.create_task(stop_after_delay())

        await asyncio.gather(task, stop_task)
        assert heartbeat.started_at is not None
        assert heartbeat.tick_count >= 1
