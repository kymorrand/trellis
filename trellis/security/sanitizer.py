"""
trellis.security.sanitizer — Input Sanitization

Cleans and validates all inputs before they reach the model or tools.
Defends against prompt injection via Discord messages, file drops, etc.
"""

import logging
import re

logger = logging.getLogger(__name__)

# Patterns that suggest prompt injection attempts
SUSPICIOUS_PATTERNS = [
    r"ignore previous instructions",
    r"ignore all previous",
    r"you are now",
    r"new instructions:",
    r"system prompt:",
    r"<\|.*?\|>",           # Common injection delimiters
    r"ADMIN OVERRIDE",
]


def sanitize_input(text: str, source: str = "unknown") -> str:
    """Sanitize input text. Log suspicious content but don't block it — flag for review."""
    if not text:
        return ""

    # Check for suspicious patterns
    for pattern in SUSPICIOUS_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            logger.warning(
                f"⚠️ Suspicious input detected from {source}: "
                f"matched pattern '{pattern}' in: {text[:100]}..."
            )
            # Don't block — log and flag. Kyle can review in the audit trail.
            break

    # Basic cleanup
    text = text.strip()

    return text


def validate_discord_user(user_id: str, allowed_user_id: str) -> bool:
    """Only process messages from Kyle's Discord account."""
    if user_id != allowed_user_id:
        logger.warning(f"Rejected message from unauthorized Discord user: {user_id}")
        return False
    return True
