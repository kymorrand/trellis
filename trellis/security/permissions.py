"""
trellis.security.permissions — Action Permission System

Controls what Ivy is allowed to do. Every action checks against
the permission system before executing.

Permission levels:
    ALLOW    — Execute without asking
    ASK      — Request Kyle's approval before executing
    DENY     — Never execute, even if asked
"""

import logging
from enum import Enum

logger = logging.getLogger(__name__)


class Permission(Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


# Default permission table — conservative by default
PERMISSIONS = {
    # Vault operations
    "vault_read": Permission.ALLOW,
    "vault_write": Permission.ALLOW,
    "vault_delete": Permission.ASK,

    # Communication
    "discord_send_private": Permission.ALLOW,       # Private Greenhouse server
    "discord_send_external": Permission.DENY,       # Other servers — never without approval

    # Linear
    "linear_morrandmore_read": Permission.ALLOW,
    "linear_morrandmore_write": Permission.ALLOW,
    "linear_mf_read": Permission.ALLOW,
    "linear_mf_write": Permission.ASK,              # MF writes need approval

    # Calendar
    "calendar_read": Permission.ALLOW,
    "calendar_write": Permission.DENY,              # Read-only, always

    # GitHub
    "github_vault_push": Permission.ALLOW,          # Automated backup
    "github_trellis_push": Permission.DENY,         # Kyle pushes code manually

    # Shell
    "shell_whitelisted": Permission.ALLOW,          # git, ls, cat, grep, etc.
    "shell_arbitrary": Permission.DENY,             # Never

    # Cloud API
    "api_call_under_5usd": Permission.ALLOW,
    "api_call_over_5usd": Permission.ASK,

    # External communication (email, Slack, Beeper, public posts)
    "external_communication": Permission.DENY,       # Always needs Kyle

    # Armando (dev team dispatch)
    "armando_dispatch": Permission.ASK,              # Every dispatch needs Kyle's approval
}


def check_permission(action: str) -> Permission:
    """Check whether an action is allowed, needs approval, or is denied."""
    perm = PERMISSIONS.get(action, Permission.ASK)  # Default to ASK if unknown
    if perm == Permission.DENY:
        logger.warning(f"DENIED action: {action}")
    elif perm == Permission.ASK:
        logger.info(f"Action requires approval: {action}")
    return perm
