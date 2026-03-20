"""
trellis.security.audit — Action Logging / Audit Trail

Every action Ivy takes gets logged. This is non-negotiable.
The audit trail lives in the daily journal and can be reviewed at any time.
"""

import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def log_action(
    vault_path: Path,
    action_type: str,
    target: str,
    input_summary: str,
    output_summary: str,
    model_used: str = "none",
    cost_usd: float = 0.0,
) -> None:
    """Log an action to the audit trail in today's journal."""
    from trellis.memory.journal import get_today_journal_path

    journal = get_today_journal_path(vault_path)
    timestamp = datetime.now().strftime("%H:%M:%S")

    entry = (
        f"### {timestamp} | AUDIT | {action_type}\n"
        f"- **Target:** {target}\n"
        f"- **Input:** {input_summary[:200]}\n"
        f"- **Output:** {output_summary[:200]}\n"
        f"- **Model:** {model_used}\n"
        f"- **Cost:** ${cost_usd:.4f}\n\n"
    )

    with open(journal, "a") as f:
        f.write(entry)

    logger.debug(f"Audit: {action_type} → {target} (${cost_usd:.4f})")
