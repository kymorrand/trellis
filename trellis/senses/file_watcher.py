"""
trellis.senses.file_watcher — Watched Folder Intake

Monitors _ivy/inbox/ for new files and processes them.
Runs as an async background task alongside the heartbeat.

Watch target: {vault_path}/_ivy/inbox/
Subdirectories:
    drops/    — Quick captures, voice transcripts, screenshots
    links/    — URLs to process
    tasks/    — Items that need action

Processing:
    1. Detect new files via polling (watchdog optional, polling is simpler)
    2. Log to journal
    3. Move processed files to _ivy/inbox/processed/
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import datetime
from pathlib import Path

from trellis.memory.journal import log_entry

logger = logging.getLogger(__name__)

# Poll interval in seconds
POLL_INTERVAL = 30

# File extensions to watch
WATCHED_EXTENSIONS = {".md", ".txt", ".url", ".json", ".yaml", ".yml"}


class FileWatcher:
    """Watches _ivy/inbox/ for new files and processes them."""

    def __init__(self, vault_path: Path, on_file_callback=None):
        self.vault_path = vault_path
        self.inbox_path = vault_path / "_ivy" / "inbox"
        self.processed_path = vault_path / "_ivy" / "inbox" / "processed"
        self.on_file_callback = on_file_callback
        self._known_files: set[str] = set()
        self._running = False

    async def start(self):
        """Start the file watcher polling loop."""
        self._running = True
        self.inbox_path.mkdir(parents=True, exist_ok=True)
        self.processed_path.mkdir(parents=True, exist_ok=True)

        # Snapshot existing files on startup (don't reprocess)
        self._known_files = self._scan_files()
        logger.info(
            f"File watcher started — monitoring {self.inbox_path} "
            f"({len(self._known_files)} existing files)"
        )

        while self._running:
            try:
                await self._check_inbox()
            except Exception as e:
                logger.error(f"File watcher error: {e}", exc_info=True)

            await asyncio.sleep(POLL_INTERVAL)

    async def stop(self):
        """Stop the file watcher."""
        self._running = False
        logger.info("File watcher stopped")

    def _scan_files(self) -> set[str]:
        """Scan inbox for all current files."""
        files = set()
        if not self.inbox_path.is_dir():
            return files

        for f in self.inbox_path.rglob("*"):
            if f.is_file() and f.suffix in WATCHED_EXTENSIONS:
                # Skip processed directory
                try:
                    f.relative_to(self.processed_path)
                    continue
                except ValueError:
                    pass
                files.add(str(f))
        return files

    async def _check_inbox(self):
        """Check for new files in the inbox."""
        current_files = self._scan_files()
        new_files = current_files - self._known_files

        if not new_files:
            return

        logger.info(f"File watcher: {len(new_files)} new file(s) detected")

        for file_path_str in sorted(new_files):
            file_path = Path(file_path_str)
            await self._process_file(file_path)

        self._known_files = current_files

    async def _process_file(self, file_path: Path):
        """Process a single new file from the inbox."""
        rel_path = file_path.relative_to(self.vault_path)
        logger.info(f"Processing inbox file: {rel_path}")

        # Read file content
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.error(f"Failed to read {rel_path}: {e}")
            return

        # Determine category from subdirectory
        parts = rel_path.parts
        category = "unknown"
        if len(parts) > 3:
            category = parts[2]  # _ivy/inbox/<category>/filename

        # Log to journal
        log_entry(
            self.vault_path,
            "FILE_INTAKE",
            f"New file in inbox: {rel_path}",
            f"Category: {category}, Size: {len(content)} chars",
        )

        # Call the callback if one is registered
        if self.on_file_callback:
            try:
                await self.on_file_callback(file_path, content, category)
            except Exception as e:
                logger.error(f"File callback error for {rel_path}: {e}", exc_info=True)

        # Move to processed
        dest = self.processed_path / file_path.name
        counter = 1
        while dest.exists():
            dest = self.processed_path / f"{file_path.stem}-{counter}{file_path.suffix}"
            counter += 1

        try:
            shutil.move(str(file_path), str(dest))
            logger.info(f"Moved to processed: {dest.relative_to(self.vault_path)}")
        except OSError as e:
            logger.error(f"Failed to move {rel_path} to processed: {e}")
