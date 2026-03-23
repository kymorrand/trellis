"""
trellis.core.heartbeat — Proactive Scheduler

The heartbeat is the second half of the dual-loop architecture.
While the main loop (loop.py) is reactive — processing events as they arrive —
the heartbeat is proactive — injecting scheduled tasks into the event queue.

Think of it like a game's background AI tick: even when the player isn't doing
anything, the world keeps running.

Schedule:
    Every 30 min  — Check inbox for new items (silent)
    Every 6 hours — Reindex vault for semantic search (silent)
    Midnight      — Nightly backup, journal rollover, cost report (silent)
    8:00 AM       — Morning brief (-> Discord)
    6:00 PM       — End of day summary (-> Discord)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from trellis.hands.github_client import vault_backup
from trellis.memory.journal import log_entry

if TYPE_CHECKING:
    from trellis.hands.linear_client import LinearClient
    from trellis.memory.knowledge import KnowledgeManager

logger = logging.getLogger(__name__)


class HeartbeatScheduler:
    """Async scheduler that runs background tasks alongside the Discord bot."""

    def __init__(
        self,
        vault_path: Path,
        budget_monthly: float = 100.0,
        discord_post_callback=None,
        knowledge_manager: KnowledgeManager | None = None,
        linear_client: LinearClient | None = None,
    ):
        self.vault_path = Path(vault_path)
        self.budget_monthly = budget_monthly
        self._discord_post = discord_post_callback
        self.knowledge_manager = knowledge_manager
        self.linear_client = linear_client
        self._running = False
        self._started_at: datetime | None = None
        self._tick_count = 0
        self._last_inbox_check: datetime | None = None
        self._last_reindex: datetime | None = None
        self._last_midnight: str | None = None  # date string of last midnight run
        self._last_morning: str | None = None
        self._last_eod: str | None = None

    @property
    def started_at(self) -> datetime | None:
        return self._started_at

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self):
        """Main heartbeat loop. Runs every 60 seconds, checks what's due."""
        self._running = True
        self._started_at = datetime.now()
        logger.info("Heartbeat started")
        log_entry(self.vault_path, "HEARTBEAT", "Heartbeat scheduler started")

        try:
            while self._running:
                await self._tick()
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            logger.info("Heartbeat cancelled")
        finally:
            self._running = False
            logger.info("Heartbeat stopped")

    async def stop(self):
        self._running = False

    async def _tick(self):
        """One heartbeat tick — check what tasks are due and run them.

        Each task is wrapped individually so a failure in one (e.g. disk full
        during inbox check) doesn't kill the entire heartbeat loop.
        """
        self._tick_count += 1
        now = datetime.now()

        # --- Every 30 minutes: inbox check ---
        if self._last_inbox_check is None or (now - self._last_inbox_check) >= timedelta(minutes=30):
            await self._run_task("inbox_check", self._check_inbox(now))
            self._last_inbox_check = now

        # --- Every 6 hours: vault reindex for semantic search ---
        if self.knowledge_manager is not None:
            if self._last_reindex is None or (now - self._last_reindex) >= timedelta(hours=6):
                await self._run_task("vault_reindex", self._reindex_vault())
                self._last_reindex = now

        today_str = now.strftime("%Y-%m-%d")

        # --- Midnight tasks (run once per day, after midnight) ---
        if now.hour == 0 and self._last_midnight != today_str:
            self._last_midnight = today_str
            await self._run_task("midnight_tasks", self._midnight_tasks(now))

        # --- 8:00 AM Morning Brief ---
        if now.hour == 8 and now.minute < 2 and self._last_morning != today_str:
            self._last_morning = today_str
            await self._run_task("morning_brief", self._morning_brief(now))

        # --- 6:00 PM End of Day ---
        if now.hour == 18 and now.minute < 2 and self._last_eod != today_str:
            self._last_eod = today_str
            await self._run_task("end_of_day", self._end_of_day(now))

    async def _run_task(self, name: str, coro):
        """Run a heartbeat task with exception isolation."""
        try:
            await coro
        except Exception as e:
            logger.error(f"Heartbeat task '{name}' failed: {e}", exc_info=True)

    # --- Silent background tasks -----------------------------------------

    async def _check_inbox(self, now: datetime):
        """Check _ivy/inbox/ directories for new files."""
        inbox_path = self.vault_path / "_ivy" / "inbox"
        if not inbox_path.is_dir():
            return

        new_files = []
        for child in inbox_path.rglob("*"):
            if child.is_file() and child.suffix == ".md":
                new_files.append(str(child.relative_to(self.vault_path)))

        if new_files:
            log_entry(
                self.vault_path,
                "HEARTBEAT_INBOX",
                f"Inbox check: {len(new_files)} items detected",
                "\n".join(new_files[:20]),
            )
            logger.info(f"Heartbeat: {len(new_files)} items in inbox")
        else:
            logger.debug("Heartbeat: inbox empty")

    async def _reindex_vault(self):
        """Reindex vault for semantic search — picks up new/changed files."""
        if self.knowledge_manager is None:
            return

        logger.info("Heartbeat: reindexing vault for semantic search")
        stats = await self.knowledge_manager.index_vault()
        log_entry(
            self.vault_path,
            "HEARTBEAT_REINDEX",
            f"Vault reindex: {stats['indexed']} indexed, {stats['skipped']} skipped, {stats['errors']} errors",
        )
        logger.info(
            "Heartbeat: vault reindex complete — %d indexed, %d skipped, %d errors",
            stats["indexed"],
            stats["skipped"],
            stats["errors"],
        )

    async def _midnight_tasks(self, now: datetime):
        """Run all midnight tasks: backup, journal rollover, cost report."""
        logger.info("Heartbeat: running midnight tasks")
        await self._nightly_backup()
        await self._journal_rollover(now)
        await self._cost_report(now)

    async def _nightly_backup(self):
        """Git add/commit/push the vault via async github_client."""
        try:
            result = await vault_backup(self.vault_path)
            log_entry(self.vault_path, "HEARTBEAT_BACKUP", result)
            logger.info(f"Nightly backup: {result}")

            # Alert Discord on failures
            if "failed" in result.lower() or "BLOCKED" in result:
                if self._discord_post:
                    await self._discord_post(f"\U0001f6a8 **{result}**")

        except Exception as e:
            error_msg = f"Nightly backup error: {e}"
            log_entry(self.vault_path, "HEARTBEAT_BACKUP_FAIL", error_msg)
            logger.error(error_msg)
            if self._discord_post:
                await self._discord_post(f"\U0001f6a8 **{error_msg}**")

    async def _journal_rollover(self, now: datetime):
        """Create tomorrow's journal file and summarize today."""
        tomorrow = now + timedelta(days=1)
        tomorrow_str = tomorrow.strftime("%Y-%m-%d")
        journal_dir = self.vault_path / "_ivy" / "journal"

        try:
            journal_dir.mkdir(parents=True, exist_ok=True)
            tomorrow_path = journal_dir / f"{tomorrow_str}.md"
            if not tomorrow_path.exists():
                tomorrow_path.write_text(
                    f"# Ivy Journal — {tomorrow_str}\n\n", encoding="utf-8"
                )
                logger.info(f"Created tomorrow's journal: {tomorrow_str}")
        except OSError as e:
            logger.error(f"Journal rollover failed: {e}")
            return

        # Summarize today's activity
        today_stats = parse_journal_stats(self.vault_path, now.strftime("%Y-%m-%d"))
        summary = (
            f"## End of Day Summary\n"
            f"- Messages processed: {today_stats['messages_in']}\n"
            f"- Responses sent: {today_stats['messages_out']}\n"
            f"- Vault saves: {today_stats['vault_saves']}\n"
            f"- API cost: ${today_stats['cost_usd']:.4f}\n"
        )
        log_entry(self.vault_path, "HEARTBEAT_ROLLOVER", "Journal rollover", summary)

    async def _cost_report(self, now: datetime):
        """Calculate today's API spend and check against monthly budget."""
        today_stats = parse_journal_stats(self.vault_path, now.strftime("%Y-%m-%d"))
        daily_cost = today_stats["cost_usd"]

        # Estimate monthly spend by summing available journal files this month
        monthly_cost = self._get_monthly_cost(now)

        log_entry(
            self.vault_path,
            "HEARTBEAT_COST",
            f"Daily cost: ${daily_cost:.4f} | Monthly total: ${monthly_cost:.4f}",
        )

        budget_pct = (monthly_cost / self.budget_monthly * 100) if self.budget_monthly > 0 else 0
        if budget_pct > 75:
            warning = (
                f"\u26a0\ufe0f **Budget alert:** ${monthly_cost:.2f} / ${self.budget_monthly:.2f} "
                f"({budget_pct:.0f}% of monthly budget)"
            )
            log_entry(self.vault_path, "HEARTBEAT_BUDGET_WARN", warning)
            if self._discord_post:
                await self._discord_post(warning)

    def _get_monthly_cost(self, now: datetime) -> float:
        """Sum API costs from all journal files this month."""
        journal_dir = self.vault_path / "_ivy" / "journal"
        if not journal_dir.is_dir():
            return 0.0

        month_prefix = now.strftime("%Y-%m-")
        total = 0.0
        for journal_file in journal_dir.glob(f"{month_prefix}*.md"):
            stats = parse_journal_stats(self.vault_path, journal_file.stem)
            total += stats["cost_usd"]
        return total

    # --- Scheduled briefs (post to Discord) --------------------------------

    async def _morning_brief(self, now: datetime):
        """8:00 AM — Morning brief posted to Discord."""
        logger.info("Heartbeat: generating morning brief")

        # Count queue items
        queue_count = self._count_queue_items()

        # Vault stats
        vault_file_count = self._count_vault_files()

        # Check for overnight activity
        overnight_summary = self._get_overnight_summary(now)

        brief = (
            f"\U0001f331 **Morning Brief — {now.strftime('%A, %B %d')}**\n\n"
        )

        if overnight_summary:
            brief += f"**Overnight:**\n{overnight_summary}\n\n"

        if queue_count > 0:
            brief += f"**Queue:** {queue_count} item{'s' if queue_count != 1 else ''} waiting for your input\n\n"

        # Linear tasks
        brief += await self._get_linear_brief_section()

        # Vault health stats (if knowledge manager available)
        if self.knowledge_manager is not None:
            try:
                health = await self.knowledge_manager.vault_health()
                brief += (
                    f"**Vault:** {health['total_files']} files "
                    f"({health['indexed_files']} indexed, "
                    f"{health['stale_files']} stale, "
                    f"{health['orphan_files']} orphans)\n"
                )
            except Exception:
                logger.warning("Failed to get vault health for morning brief", exc_info=True)
                brief += f"**Vault:** {vault_file_count} files\n"
        else:
            brief += f"**Vault:** {vault_file_count} files\n"

        log_entry(self.vault_path, "HEARTBEAT_MORNING", "Morning brief generated", brief)

        if self._discord_post:
            await self._discord_post(brief)

    async def _get_linear_brief_section(self) -> str:
        """Fetch active Linear tasks and format a brief section.

        Returns an empty string if no linear_client is configured.
        Catches and logs errors to avoid crashing the morning brief.
        """
        if self.linear_client is None:
            return ""

        try:
            from trellis.hands.linear_client import format_issues

            issues = await self.linear_client.get_team_issues("MOR", limit=10)

            # Filter to non-completed/non-canceled issues
            active_issues = [
                issue for issue in issues
                if issue.get("state", {}).get("type", "") not in {"completed", "canceled"}
            ]

            if not active_issues:
                return "**Linear:** No active tasks\n\n"

            # Sort by priority: 1=Urgent, 2=High, 3=Normal, 4=Low, 0=No priority (treat 0 as lowest)
            def priority_sort_key(issue: dict) -> int:
                pri = issue.get("priority", 0)
                return pri if pri > 0 else 5  # Push 0 (no priority) after 4 (low)

            active_issues.sort(key=priority_sort_key)

            # Find blocked items
            blocked = [
                issue for issue in active_issues
                if issue.get("state", {}).get("type", "") == "blocked"
                or "block" in issue.get("state", {}).get("name", "").lower()
            ]

            # Top 3 priority items
            top_3 = active_issues[:3]
            top_3_formatted = format_issues(top_3)

            section = f"**Linear:** {len(active_issues)} active task{'s' if len(active_issues) != 1 else ''}\n"
            section += f"{top_3_formatted}\n"

            if blocked:
                section += f"*{len(blocked)} blocked item{'s' if len(blocked) != 1 else ''}*\n"

            section += "\n"
            return section

        except Exception:
            logger.error("Failed to fetch Linear tasks for morning brief", exc_info=True)
            return ""

    async def _end_of_day(self, now: datetime):
        """6:00 PM — End of day summary posted to Discord."""
        logger.info("Heartbeat: generating end-of-day summary")

        today_stats = parse_journal_stats(self.vault_path, now.strftime("%Y-%m-%d"))
        queue_count = self._count_queue_items()
        vault_file_count = self._count_vault_files()

        summary = (
            f"\U0001f33f **End of Day — {now.strftime('%A, %B %d')}**\n\n"
            f"**Today's activity:**\n"
            f"- Messages processed: {today_stats['messages_in']}\n"
            f"- Responses sent: {today_stats['messages_out']}\n"
            f"- Vault saves: {today_stats['vault_saves']}\n"
            f"- New files detected: {today_stats['new_files']}\n\n"
            f"**API cost today:** ${today_stats['cost_usd']:.4f}\n"
            f"**Vault:** {vault_file_count} files\n"
        )

        if queue_count > 0:
            summary += f"\n**Open items in queue:** {queue_count}\n"

        log_entry(self.vault_path, "HEARTBEAT_EOD", "End of day summary", summary)

        if self._discord_post:
            await self._discord_post(summary)

    # --- Status report (on-demand via /status) --------------------------------

    async def get_status_report(self) -> str:
        """Generate an immediate status report for the /status command."""
        now = datetime.now()
        today_stats = parse_journal_stats(self.vault_path, now.strftime("%Y-%m-%d"))
        monthly_cost = self._get_monthly_cost(now)
        vault_file_count = self._count_vault_files()

        uptime = "not started"
        if self._started_at:
            delta = now - self._started_at
            hours, remainder = divmod(int(delta.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            uptime = f"{hours}h {minutes}m"

        budget_pct = (monthly_cost / self.budget_monthly * 100) if self.budget_monthly > 0 else 0

        return (
            f"\U0001f331 **Ivy Status Report**\n\n"
            f"**Uptime:** {uptime}\n"
            f"**Heartbeat ticks:** {self._tick_count}\n"
            f"**Vault:** {vault_file_count} files\n\n"
            f"**API spend today:** ${today_stats['cost_usd']:.4f}\n"
            f"**API spend this month:** ${monthly_cost:.2f} / ${self.budget_monthly:.2f} "
            f"({budget_pct:.0f}%)\n\n"
            f"**Today's activity:**\n"
            f"- Messages in: {today_stats['messages_in']}\n"
            f"- Responses out: {today_stats['messages_out']}\n"
            f"- Vault saves: {today_stats['vault_saves']}\n"
        )

    # --- Helpers ---------------------------------------------------------------

    def _count_queue_items(self) -> int:
        """Count items in _ivy/queue/ needing Kyle's input."""
        queue_dir = self.vault_path / "_ivy" / "queue"
        if not queue_dir.is_dir():
            return 0
        return sum(1 for f in queue_dir.rglob("*.md") if f.is_file())

    def _count_vault_files(self) -> int:
        """Count total .md files in the vault (excluding internal dirs)."""
        if not self.vault_path.is_dir():
            return 0
        count = 0
        internal = {"_ivy", ".git", ".obsidian", ".trash"}
        for f in self.vault_path.rglob("*.md"):
            rel = f.relative_to(self.vault_path)
            if not any(part in internal for part in rel.parts):
                count += 1
        return count

    def _get_overnight_summary(self, now: datetime) -> str:
        """Check yesterday's journal for activity after 6 PM."""
        yesterday = now - timedelta(days=1)
        yesterday_str = yesterday.strftime("%Y-%m-%d")
        journal_path = self.vault_path / "_ivy" / "journal" / f"{yesterday_str}.md"
        if not journal_path.exists():
            return ""

        try:
            content = journal_path.read_text(encoding="utf-8")
        except OSError:
            return ""

        # Count late-night entries (after 18:00)
        late_entries = 0
        for line in content.splitlines():
            if line.startswith("## ") and "|" in line:
                try:
                    time_str = line.split("## ")[1].split(" |")[0].strip()
                    hour = int(time_str.split(":")[0])
                    if hour >= 18:
                        late_entries += 1
                except (IndexError, ValueError):
                    continue

        if late_entries > 0:
            return f"- {late_entries} overnight journal entries from yesterday"
        return ""


def parse_journal_stats(vault_path: Path, date_str: str) -> dict:
    """Parse a journal file and extract activity stats.

    Returns dict with: messages_in, messages_out, vault_saves, cost_usd, new_files
    """
    stats = {
        "messages_in": 0,
        "messages_out": 0,
        "vault_saves": 0,
        "cost_usd": 0.0,
        "new_files": 0,
    }

    journal_path = Path(vault_path) / "_ivy" / "journal" / f"{date_str}.md"
    if not journal_path.exists():
        return stats

    try:
        content = journal_path.read_text(encoding="utf-8")
    except OSError:
        return stats

    for line in content.splitlines():
        if "| MESSAGE_IN" in line:
            stats["messages_in"] += 1
        elif "| MESSAGE_OUT" in line:
            stats["messages_out"] += 1
        elif "| VAULT_SAVE" in line:
            stats["vault_saves"] += 1
        elif "| HEARTBEAT_INBOX" in line:
            stats["new_files"] += 1
        elif "**Cost:** $" in line:
            # Parse cost from audit entries like "- **Cost:** $0.0042"
            try:
                cost_str = line.split("**Cost:** $")[1].strip()
                stats["cost_usd"] += float(cost_str)
            except (IndexError, ValueError):
                continue

    return stats
