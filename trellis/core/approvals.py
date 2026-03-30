"""
trellis.core.approvals — Approval model, storage, and CRUD.

Approvals are high-stakes actions that need Kyle's explicit OK before Ivy
proceeds (e.g., publish to garden, spend above budget threshold).

Storage: approvals live in ``_ivy/approvals/`` as individual JSON files.
One file per approval: ``{approval_id}.json``. This keeps them decoupled
from quest files and makes cross-quest listing trivial.

Design rationale: unlike questions (which are per-quest context), approvals
are a global queue. Storing them as separate files in a dedicated directory
makes the GET /api/approvals endpoint a simple directory scan rather than
parsing every quest file.

Provides:
    Approval           — Dataclass for a single approval
    ApprovalStore      — File-based CRUD for approvals
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_VALID_STATUSES = {"pending", "approved", "rejected"}


@dataclass
class Approval:
    """A single approval request from Ivy."""

    id: str
    quest_id: str
    quest_name: str
    title: str
    description: str
    status: str = "pending"
    cost_estimate: str | None = None
    created_at: str = ""
    resolved_at: str | None = None
    reject_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dict."""
        return asdict(self)


class ApprovalStore:
    """File-based CRUD for approval requests.

    Each approval is a JSON file at ``{approvals_dir}/{id}.json``.

    Args:
        approvals_dir: Path to the ``_ivy/approvals/`` directory.
    """

    def __init__(self, approvals_dir: Path) -> None:
        self._dir = approvals_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        quest_id: str,
        quest_name: str,
        title: str,
        description: str,
        cost_estimate: str | None = None,
    ) -> Approval:
        """Create a new pending approval.

        Returns:
            The created Approval object.
        """
        approval_id = f"APR-{uuid.uuid4().hex[:8]}"
        approval = Approval(
            id=approval_id,
            quest_id=quest_id,
            quest_name=quest_name,
            title=title,
            description=description,
            cost_estimate=cost_estimate,
            created_at=datetime.now().isoformat(),
        )
        self._save(approval)
        logger.info("Created approval %s for quest %s", approval_id, quest_id)
        return approval

    def get(self, approval_id: str) -> Approval | None:
        """Load a single approval by ID.

        Returns:
            Approval object, or None if not found.
        """
        path = self._dir / f"{approval_id}.json"
        if not path.exists():
            return None
        return self._load(path)

    def list_pending(self) -> list[Approval]:
        """List all pending approvals across all quests.

        Returns:
            List of Approval objects with status 'pending', sorted by
            creation time (oldest first).
        """
        approvals: list[Approval] = []
        for path in self._dir.glob("*.json"):
            approval = self._load(path)
            if approval and approval.status == "pending":
                approvals.append(approval)

        # Sort by creation time (oldest first)
        approvals.sort(key=lambda a: a.created_at)
        return approvals

    def list_all(self) -> list[Approval]:
        """List all approvals regardless of status.

        Returns:
            List of all Approval objects, sorted by creation time.
        """
        approvals: list[Approval] = []
        for path in self._dir.glob("*.json"):
            approval = self._load(path)
            if approval:
                approvals.append(approval)

        approvals.sort(key=lambda a: a.created_at)
        return approvals

    def approve(self, approval_id: str) -> Approval | None:
        """Mark an approval as approved.

        Returns:
            Updated Approval, or None if not found.
        """
        approval = self.get(approval_id)
        if not approval:
            return None

        approval.status = "approved"
        approval.resolved_at = datetime.now().isoformat()
        self._save(approval)
        logger.info("Approved: %s", approval_id)
        return approval

    def reject(self, approval_id: str, reason: str = "") -> Approval | None:
        """Mark an approval as rejected.

        Args:
            approval_id: The approval to reject.
            reason: Optional rejection reason.

        Returns:
            Updated Approval, or None if not found.
        """
        approval = self.get(approval_id)
        if not approval:
            return None

        approval.status = "rejected"
        approval.resolved_at = datetime.now().isoformat()
        approval.reject_reason = reason
        self._save(approval)
        logger.info("Rejected: %s (reason: %s)", approval_id, reason)
        return approval

    def _save(self, approval: Approval) -> None:
        """Write an approval to its JSON file."""
        path = self._dir / f"{approval.id}.json"
        path.write_text(
            json.dumps(approval.to_dict(), indent=2),
            encoding="utf-8",
        )

    def _load(self, path: Path) -> Approval | None:
        """Load an approval from a JSON file."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Approval(**data)
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.error("Failed to load approval from %s: %s", path, exc)
            return None
