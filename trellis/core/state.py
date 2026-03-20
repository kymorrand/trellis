"""
trellis.core.state — State Persistence

Simple JSON-on-disk state management. No database needed.
Saves and loads the runtime state between restarts.
"""

import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

DEFAULT_STATE = {
    "agent": "ivy",
    "started_at": None,
    "last_active": None,
    "total_events_processed": 0,
    "budget_spent_this_month": 0.0,
    "current_mode": "autonomous",  # co-op | autonomous | report-back
}

STATE_FILE = Path("state.json")


def load_state(path: Path = STATE_FILE) -> dict:
    """Load state from disk, or create default state."""
    if path.exists():
        with open(path) as f:
            state = json.load(f)
        logger.info(f"State loaded from {path}")
        return state

    logger.info("No existing state found — creating fresh state")
    state = DEFAULT_STATE.copy()
    state["started_at"] = datetime.now().isoformat()
    save_state(state, path)
    return state


def save_state(state: dict, path: Path = STATE_FILE) -> None:
    """Persist state to disk."""
    state["last_active"] = datetime.now().isoformat()
    with open(path, "w") as f:
        json.dump(state, f, indent=2)
