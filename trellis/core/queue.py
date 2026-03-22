"""
trellis.core.queue — File-Based Approval Queue

Ivy proposes actions; Kyle approves, dismisses, or redirects via the web UI.
Each item is a .md file with YAML frontmatter in _ivy/queue/.

Approved/dismissed items are moved to subdirectories (not deleted) for audit.
"""

import logging
import re
from datetime import datetime
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class ApprovalQueue:
    """File-based approval queue using _ivy/queue/ in the vault."""

    def __init__(self, vault_path: Path):
        self.queue_dir = Path(vault_path) / "_ivy" / "queue"
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        (self.queue_dir / "approved").mkdir(exist_ok=True)
        (self.queue_dir / "dismissed").mkdir(exist_ok=True)

    def list_items(self) -> list[dict]:
        """List all pending queue items, sorted oldest first."""
        items = []
        for f in sorted(self.queue_dir.glob("*.md")):
            if not f.is_file():
                continue
            item = self._parse_item(f)
            if item:
                items.append(item)
        return items

    def get_item(self, item_id: str) -> dict | None:
        """Get a single queue item by ID."""
        for f in self.queue_dir.glob("*.md"):
            item = self._parse_item(f)
            if item and item["id"] == item_id:
                return item
        return None

    def add_item(
        self,
        item_type: str,
        summary: str,
        body: str,
        context: str = "",
        source: str = "ivy",
    ) -> str:
        """Create a new queue item. Returns the item ID."""
        now = datetime.now()
        item_id = now.strftime("%Y%m%d-%H%M%S")

        # Slugify summary for filename
        slug = re.sub(r"[^a-z0-9]+", "-", summary.lower())[:40].strip("-")
        filename = f"{item_id}-{slug}.md"

        frontmatter = {
            "id": item_id,
            "type": item_type,
            "source": source,
            "created": now.strftime("%Y-%m-%d %H:%M"),
            "summary": summary,
        }

        content = "---\n"
        content += yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
        content += "---\n\n"
        content += body
        if context:
            content += f"\n\n**Context:** {context}"

        filepath = self.queue_dir / filename
        filepath.write_text(content, encoding="utf-8")
        logger.info(f"Queue item added: {item_id} — {summary}")
        return item_id

    def approve_item(self, item_id: str) -> bool:
        """Move item to approved/ subdirectory. Returns True if found."""
        return self._resolve_item(item_id, "approved")

    def dismiss_item(self, item_id: str) -> bool:
        """Move item to dismissed/ subdirectory. Returns True if found."""
        return self._resolve_item(item_id, "dismissed")

    def _resolve_item(self, item_id: str, destination: str) -> bool:
        """Move an item to a resolution subdirectory."""
        for f in self.queue_dir.glob("*.md"):
            if not f.is_file():
                continue
            item = self._parse_item(f)
            if item and item["id"] == item_id:
                dest = self.queue_dir / destination / f.name
                f.rename(dest)
                logger.info(f"Queue item {destination}: {item_id}")
                return True
        return False

    def _parse_item(self, filepath: Path) -> dict | None:
        """Parse a queue item file. Returns dict or None on parse failure."""
        try:
            text = filepath.read_text(encoding="utf-8")
        except OSError:
            return None

        # Split frontmatter from body
        if not text.startswith("---"):
            return None

        parts = text.split("---", 2)
        if len(parts) < 3:
            return None

        try:
            meta = yaml.safe_load(parts[1])
        except yaml.YAMLError:
            return None

        if not isinstance(meta, dict) or "id" not in meta:
            return None

        body = parts[2].strip()

        return {
            "id": meta["id"],
            "type": meta.get("type", "suggestion"),
            "source": meta.get("source", "ivy"),
            "created": meta.get("created", ""),
            "summary": meta.get("summary", ""),
            "body": body,
            "filename": filepath.name,
        }
