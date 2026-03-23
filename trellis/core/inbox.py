"""
trellis.core.inbox -- Intelligent Input Triage

The InboxProcessor classifies incoming content, matches it against the vault,
detects urgency and role fit, and proposes a routing path.  Kyle approves,
redirects, or archives each item through the web API.

Storage layout (all under the vault):
    _ivy/inbox/drops/     Raw unprocessed drops (text files, links)
    _ivy/inbox/items/     Classified items with routing proposals (YAML-frontmatter MD)
    _ivy/inbox/archived/  Items Kyle dismissed
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from trellis.mind.router import ModelRouter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Urgency keywords used in heuristic fallback (no model needed)
# ---------------------------------------------------------------------------

_IMMEDIATE_PATTERNS: list[str] = [
    "urgent", "asap", "emergency", "right now", "immediately", "critical",
    "deadline today", "due today", "blocking",
]

_TODAY_PATTERNS: list[str] = [
    "today", "this afternoon", "this morning", "by eod", "end of day",
    "tonight", "soon", "before",
]

# Role keyword maps
_ROLE_KEYWORDS: dict[str, list[str]] = {
    "researcher": [
        "research", "investigate", "find out", "look into", "study",
        "explore", "learn about", "compare", "analyze data",
    ],
    "strategist": [
        "strategy", "plan", "roadmap", "decide", "trade-off", "priority",
        "architecture", "direction", "goal",
    ],
    "writer": [
        "write", "draft", "blog", "essay", "copy", "article", "prose",
        "narrative", "document", "describe",
    ],
    "organizer": [
        "organize", "sort", "file", "categorize", "clean up", "tidy",
        "schedule", "calendar", "task", "todo", "reminder",
    ],
}

# Content type keyword maps — order matters: more specific types checked first.
# "idea" before "question" because "?" is too broad and would catch "what if...?" ideas.
_TYPE_KEYWORDS: dict[str, list[str]] = {
    "task": ["todo", "task", "action item", "need to", "must", "should"],
    "idea": ["idea", "what if", "maybe", "could we", "brainstorm", "concept"],
    "link": ["http://", "https://", "www."],
    "reference": ["reference", "documentation", "spec", "guide", "manual"],
    "question": ["?", "how do", "what is", "why", "when", "who", "where"],
    "note": [],  # fallback
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RoutingProposal:
    vault_path: str  # suggested save location
    confidence: float  # 0.0 -- 1.0
    confidence_tier: str  # green / amber / red
    urgency: str  # immediate / today / queue
    role: str  # researcher / strategist / writer / organizer
    vault_matches: list[dict] = field(default_factory=list)
    reasoning: str = ""


@dataclass
class InboxItem:
    id: str
    content: str
    content_type: str  # text / url / file
    summary: str
    planted: str  # ISO timestamp
    tended: str | None  # ISO timestamp of last action
    status: str  # pending / approved / redirected / archived
    routing: RoutingProposal | None = None
    metadata: dict = field(default_factory=dict)


def _confidence_tier(score: float) -> str:
    if score >= 0.90:
        return "green"
    if score >= 0.70:
        return "amber"
    return "red"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Serialisation helpers (YAML-frontmatter Markdown, same pattern as queue.py)
# ---------------------------------------------------------------------------

def _serialize_item(item: InboxItem) -> str:
    """Serialize an InboxItem to YAML-frontmatter Markdown."""
    meta: dict = {
        "id": item.id,
        "content_type": item.content_type,
        "summary": item.summary,
        "planted": item.planted,
        "tended": item.tended,
        "status": item.status,
        "metadata": item.metadata or {},
    }
    if item.routing:
        meta["routing"] = asdict(item.routing)

    out = "---\n"
    out += yaml.dump(meta, default_flow_style=False, sort_keys=False)
    out += "---\n\n"
    out += item.content
    return out


def _deserialize_item(text: str) -> InboxItem | None:
    """Parse a YAML-frontmatter Markdown string into an InboxItem."""
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

    routing_data = meta.get("routing")
    routing: RoutingProposal | None = None
    if isinstance(routing_data, dict):
        routing = RoutingProposal(
            vault_path=routing_data.get("vault_path", ""),
            confidence=float(routing_data.get("confidence", 0.0)),
            confidence_tier=routing_data.get("confidence_tier", "red"),
            urgency=routing_data.get("urgency", "queue"),
            role=routing_data.get("role", "organizer"),
            vault_matches=routing_data.get("vault_matches", []),
            reasoning=routing_data.get("reasoning", ""),
        )

    body = parts[2].strip()

    return InboxItem(
        id=meta["id"],
        content=body,
        content_type=meta.get("content_type", "text"),
        summary=meta.get("summary", ""),
        planted=meta.get("planted", ""),
        tended=meta.get("tended"),
        status=meta.get("status", "pending"),
        routing=routing,
        metadata=meta.get("metadata", {}),
    )


# ---------------------------------------------------------------------------
# InboxProcessor
# ---------------------------------------------------------------------------

class InboxProcessor:
    """Intelligence engine for classifying and routing inbox content."""

    def __init__(
        self,
        vault_path: Path,
        router: ModelRouter | None = None,
        config: dict | None = None,
    ):
        self.vault_path = Path(vault_path)
        self.router = router
        self.config = config or {}
        self._items_dir = self.vault_path / "_ivy" / "inbox" / "items"
        self._archived_dir = self.vault_path / "_ivy" / "inbox" / "archived"
        self._drops_dir = self.vault_path / "_ivy" / "inbox" / "drops"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        for d in (self._items_dir, self._archived_dir, self._drops_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def process_drop(
        self,
        content: str,
        content_type: str = "text",
        metadata: dict | None = None,
    ) -> InboxItem:
        """Process raw input into a classified inbox item with routing proposal."""
        item_id = uuid.uuid4().hex[:12]
        planted = _now_iso()

        classification = await self.classify_content(content)
        urgency = await self.detect_urgency(content)
        role_info = await self.detect_role(content)
        vault_matches = await self.match_vault(content)

        summary = classification.get("summary", content[:80])
        routing = await self.propose_routing_from_signals(
            content=content,
            classification=classification,
            urgency=urgency,
            role_info=role_info,
            vault_matches=vault_matches,
        )

        item = InboxItem(
            id=item_id,
            content=content,
            content_type=content_type,
            summary=summary,
            planted=planted,
            tended=None,
            status="pending",
            routing=routing,
            metadata=metadata or {},
        )

        self._save_item(item)
        logger.info("Inbox item created: %s — %s", item.id, summary)
        return item

    async def classify_content(self, content: str) -> dict:
        """Classify content into {type, tags, summary}.

        Uses the model router when available; falls back to keyword heuristics.
        """
        if self.router:
            try:
                return await self._classify_with_model(content)
            except Exception:
                logger.warning("Model classification failed, falling back to heuristics", exc_info=True)

        return self._classify_heuristic(content)

    async def match_vault(self, content: str) -> list[dict]:
        """Return top 3 vault matches with relevance scores."""
        from trellis.hands.vault import search_vault as _search_vault

        results = _search_vault(self.vault_path, content, max_results=3)
        return [
            {
                "path": r["path"],
                "relevance_score": round(r.get("relevance", 0.0), 2),
                "snippet": (r.get("matches", [""])[0])[:120] if r.get("matches") else "",
            }
            for r in results
        ]

    async def detect_urgency(self, content: str) -> dict:
        """Detect urgency level from content. Pure heuristic -- no model call."""
        content_lower = content.lower()

        for pattern in _IMMEDIATE_PATTERNS:
            if pattern in content_lower:
                return {"level": "immediate", "reason": f"Contains '{pattern}'"}

        for pattern in _TODAY_PATTERNS:
            if pattern in content_lower:
                return {"level": "today", "reason": f"Contains '{pattern}'"}

        return {"level": "queue", "reason": "No urgency signals detected"}

    async def detect_role(self, content: str) -> dict:
        """Detect which Ivy role fits best. Keyword-scored heuristic."""
        content_lower = content.lower()
        scores: dict[str, int] = {}

        for role, keywords in _ROLE_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in content_lower)
            if score > 0:
                scores[role] = score

        if not scores:
            return {"role": "organizer", "confidence": 0.5, "reason": "Default role (no strong signals)"}

        best_role = max(scores, key=scores.get)  # type: ignore[arg-type]
        max_possible = len(_ROLE_KEYWORDS[best_role])
        confidence = min(1.0, scores[best_role] / max(max_possible, 1))
        # Floor confidence at 0.4 so heuristic never looks absurdly sure
        confidence = max(0.4, confidence)

        return {
            "role": best_role,
            "confidence": round(confidence, 2),
            "reason": f"Matched {scores[best_role]} keyword(s) for {best_role}",
        }

    async def propose_routing(self, item: InboxItem) -> RoutingProposal:
        """Build a RoutingProposal from an already-populated InboxItem."""
        classification = await self.classify_content(item.content)
        urgency = await self.detect_urgency(item.content)
        role_info = await self.detect_role(item.content)
        vault_matches = await self.match_vault(item.content)

        return await self.propose_routing_from_signals(
            content=item.content,
            classification=classification,
            urgency=urgency,
            role_info=role_info,
            vault_matches=vault_matches,
        )

    async def propose_routing_from_signals(
        self,
        *,
        content: str,
        classification: dict,
        urgency: dict,
        role_info: dict,
        vault_matches: list[dict],
    ) -> RoutingProposal:
        """Combine classification signals into a RoutingProposal."""
        content_type = classification.get("type", "note")
        tags = classification.get("tags", [])

        # Build a vault path suggestion based on type and tags
        vault_path = self._suggest_vault_path(content_type, tags, content)

        # Confidence scoring: starts at 0.6 and adjusts
        confidence = 0.6
        reasoning_parts: list[str] = []

        # Boost if vault matches are strong
        if vault_matches:
            best_relevance = vault_matches[0].get("relevance_score", 0.0)
            if best_relevance >= 0.8:
                confidence += 0.20
                reasoning_parts.append(f"Strong vault match ({best_relevance})")
            elif best_relevance >= 0.5:
                confidence += 0.10
                reasoning_parts.append(f"Moderate vault match ({best_relevance})")

        # Boost if role detection is confident
        if role_info.get("confidence", 0) >= 0.7:
            confidence += 0.10
            reasoning_parts.append(f"Clear role fit: {role_info['role']}")

        # Penalize if classification type is the fallback 'note'
        if content_type == "note":
            confidence -= 0.05
            reasoning_parts.append("Generic note type")

        confidence = round(min(1.0, max(0.0, confidence)), 2)

        if not reasoning_parts:
            reasoning_parts.append(f"Classified as {content_type}")

        return RoutingProposal(
            vault_path=vault_path,
            confidence=confidence,
            confidence_tier=_confidence_tier(confidence),
            urgency=urgency.get("level", "queue"),
            role=role_info.get("role", "organizer"),
            vault_matches=vault_matches,
            reasoning="; ".join(reasoning_parts),
        )

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def _save_item(self, item: InboxItem) -> Path:
        """Write an InboxItem to _ivy/inbox/items/ as YAML-frontmatter Markdown."""
        self._items_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{item.id}.md"
        path = self._items_dir / filename
        path.write_text(_serialize_item(item), encoding="utf-8")
        return path

    def load_item(self, item_id: str) -> InboxItem | None:
        """Load a single item by ID."""
        path = self._items_dir / f"{item_id}.md"
        if not path.exists():
            return None
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        return _deserialize_item(text)

    def list_items(self, status: str = "pending") -> list[InboxItem]:
        """List items filtered by status. Sorted by urgency then planted date."""
        items: list[InboxItem] = []
        if not self._items_dir.is_dir():
            return items
        for f in self._items_dir.glob("*.md"):
            if not f.is_file():
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                continue
            item = _deserialize_item(text)
            if item and item.status == status:
                items.append(item)

        urgency_order = {"immediate": 0, "today": 1, "queue": 2}
        items.sort(key=lambda i: (
            urgency_order.get(i.routing.urgency if i.routing else "queue", 2),
            i.planted,
        ))
        return items

    def approve_item(self, item_id: str, vault_path_override: str | None = None) -> InboxItem | None:
        """Approve an item: update status, write content to vault, return updated item."""
        item = self.load_item(item_id)
        if not item:
            return None

        save_path = vault_path_override
        if not save_path and item.routing:
            save_path = item.routing.vault_path
        if not save_path:
            save_path = f"knowledge/inbox/{item.id}.md"

        # Write to vault
        dest = self.vault_path / save_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(item.content, encoding="utf-8")

        # Update item status
        item.status = "approved" if not vault_path_override else "redirected"
        item.tended = _now_iso()
        if vault_path_override and item.routing:
            item.routing.vault_path = vault_path_override
        self._save_item(item)

        logger.info("Inbox item %s %s -> %s", item.id, item.status, save_path)
        return item

    def archive_item(self, item_id: str) -> InboxItem | None:
        """Move item to archived directory."""
        item = self.load_item(item_id)
        if not item:
            return None

        item.status = "archived"
        item.tended = _now_iso()

        # Move file to archived/
        src = self._items_dir / f"{item_id}.md"
        dst = self._archived_dir / f"{item_id}.md"
        self._archived_dir.mkdir(parents=True, exist_ok=True)
        dst.write_text(_serialize_item(item), encoding="utf-8")
        if src.exists():
            src.unlink()

        logger.info("Inbox item archived: %s", item.id)
        return item

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _suggest_vault_path(self, content_type: str, tags: list[str], content: str) -> str:
        """Build a vault path suggestion based on classification signals."""
        # Use the first meaningful tag as a subdirectory
        sub = tags[0] if tags else content_type
        # Slugify the first 40 chars of content for the filename
        slug = re.sub(r"[^a-z0-9]+", "-", content[:60].lower()).strip("-")[:40]
        if not slug:
            slug = "untitled"
        return f"knowledge/{sub}/{slug}.md"

    def _classify_heuristic(self, content: str) -> dict:
        """Keyword-based classification fallback."""
        content_lower = content.lower()
        detected_type = "note"

        for ctype, keywords in _TYPE_KEYWORDS.items():
            if ctype == "note":
                continue
            if any(kw in content_lower for kw in keywords):
                detected_type = ctype
                break

        tags = self._extract_tags(content)
        summary = content.split("\n")[0][:80].strip()
        if not summary:
            summary = content[:80].strip()

        return {"type": detected_type, "tags": tags, "summary": summary}

    def _extract_tags(self, content: str) -> list[str]:
        """Pull basic tags from content."""
        # Hashtags in content
        hashtags = re.findall(r"#([a-zA-Z][a-zA-Z0-9_-]+)", content)
        tags = list(dict.fromkeys(hashtags))[:5]  # dedupe, max 5
        return tags

    async def _classify_with_model(self, content: str) -> dict:
        """Use the model router to classify content."""
        import json as _json

        if not self.router:
            return self._classify_heuristic(content)

        prompt = (
            "Classify this content. Respond ONLY with valid JSON, no markdown fences.\n"
            "Format: {\"type\": \"note|task|reference|question|idea|link|file\", "
            "\"tags\": [\"tag1\", \"tag2\"], \"summary\": \"one line summary\"}\n\n"
            f"Content:\n{content[:2000]}"
        )

        result = await self.router.route(
            message=prompt,
            system_prompt="You are a content classification assistant. Respond only with JSON.",
            history=[],
        )

        try:
            data = _json.loads(result.response.strip())
        except _json.JSONDecodeError:
            # Try extracting JSON from the response
            match = re.search(r"\{.*\}", result.response, re.DOTALL)
            if match:
                data = _json.loads(match.group())
            else:
                raise ValueError(f"Could not parse model response as JSON: {result.response[:200]}")

        return {
            "type": data.get("type", "note"),
            "tags": data.get("tags", []),
            "summary": data.get("summary", content[:80]),
        }
