"""
trellis.memory.journal — Daily Interaction Logs

One Markdown file per day in _ivy/journal/YYYY-MM-DD.md
Logs every action Ivy takes with timestamp, type, input, output, cost.
This is both the audit trail and Ivy's short-term memory.
"""

import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def get_today_journal_path(vault_path: Path) -> Path:
    """Return path to today's journal file, creating it if needed."""
    today = datetime.now().strftime("%Y-%m-%d")
    journal_dir = vault_path / "_ivy" / "journal"

    try:
        journal_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error(f"Failed to create journal directory {journal_dir}: {e}")
        raise

    journal_path = journal_dir / f"{today}.md"
    if not journal_path.exists():
        try:
            journal_path.write_text(f"# Ivy Journal — {today}\n\n", encoding="utf-8")
            logger.info(f"Created new journal: {journal_path}")
        except OSError as e:
            logger.error(f"Failed to create journal file {journal_path}: {e}")
            raise

    return journal_path


def log_entry(vault_path: Path, entry_type: str, summary: str, details: str = "") -> None:
    """Append an entry to today's journal.

    Never raises — a logging failure must not crash the bot.
    Falls back to stderr logging if file write fails.
    """
    try:
        journal = get_today_journal_path(vault_path)
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"## {timestamp} | {entry_type}\n{summary}\n"
        if details:
            entry += f"\n{details}\n"
        entry += "\n---\n\n"

        with open(journal, "a", encoding="utf-8") as f:
            f.write(entry)
    except OSError as e:
        # Fallback: log to stderr so systemd journal still captures it
        logger.error(f"Journal write failed ({entry_type}: {summary}): {e}")
