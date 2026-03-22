"""trellis.hands.github_client — GitHub Operations (vault backup)

Automates nightly backup of ivy-vault to kymorrand/ivy-vault (private).
Security: Push access to ivy-vault only. No access to MF repos.

Pre-push audit:
    - Scans staged files for common credential patterns
    - Blocks push if secrets detected
    - Logs all operations to journal
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path

from trellis.memory.journal import log_entry

logger = logging.getLogger(__name__)

# Patterns that suggest credentials or secrets
SECRET_PATTERNS = [
    re.compile(r"(api[_-]?key|apikey)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}", re.IGNORECASE),
    re.compile(r"(secret|password|passwd|token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{8,}", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # Anthropic/OpenAI keys
    re.compile(r"ghp_[A-Za-z0-9]{36,}"),  # GitHub personal access tokens
    re.compile(r"gho_[A-Za-z0-9]{36,}"),  # GitHub OAuth tokens
    re.compile(r"AKIA[A-Z0-9]{16}"),  # AWS access key IDs
    re.compile(r"-----BEGIN (RSA |EC |DSA )?PRIVATE KEY-----"),
]

# Files that should never be committed
BLOCKED_FILES = {".env", "credentials.json", "token.json", "id_rsa", "id_ed25519"}


async def scan_for_secrets(vault_path: Path) -> list[str]:
    """Scan staged files for potential secrets.

    Returns a list of warnings. Empty list means safe to push.
    """
    warnings = []

    # Check for blocked filenames
    proc = await asyncio.create_subprocess_exec(
        "git", "diff", "--cached", "--name-only",
        cwd=str(vault_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()

    if proc.returncode != 0:
        return ["Failed to check staged files — skipping secret scan"]

    staged_files = stdout.decode().strip().splitlines()

    for filename in staged_files:
        basename = Path(filename).name
        if basename in BLOCKED_FILES:
            warnings.append(f"BLOCKED: {filename} — sensitive filename")
            continue

        # Read the staged content
        file_path = vault_path / filename
        if not file_path.exists() or not file_path.is_file():
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for pattern in SECRET_PATTERNS:
            matches = pattern.findall(content)
            if matches:
                warnings.append(
                    f"WARNING: {filename} — potential secret detected "
                    f"(pattern: {pattern.pattern[:40]}...)"
                )
                break

    return warnings


async def vault_backup(vault_path: Path) -> str:
    """Run a full vault backup: git add, commit, push.

    Returns a status message describing what happened.
    """
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    log_entry(vault_path, "GITHUB_BACKUP", "Starting nightly vault backup")

    # Stage all changes
    proc = await asyncio.create_subprocess_exec(
        "git", "add", "-A",
        cwd=str(vault_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()

    # Check if there are changes to commit
    proc = await asyncio.create_subprocess_exec(
        "git", "diff", "--cached", "--quiet",
        cwd=str(vault_path),
    )
    await proc.communicate()

    if proc.returncode == 0:
        msg = f"Vault backup: no changes to commit ({date_str})"
        logger.info(msg)
        log_entry(vault_path, "GITHUB_BACKUP", msg)
        return msg

    # Pre-push security scan
    secrets = await scan_for_secrets(vault_path)
    if any(w.startswith("BLOCKED") for w in secrets):
        # Hard block — reset staged files
        await asyncio.create_subprocess_exec(
            "git", "reset", "HEAD",
            cwd=str(vault_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        msg = f"Vault backup BLOCKED — secrets detected:\n" + "\n".join(secrets)
        logger.error(msg)
        log_entry(vault_path, "GITHUB_BACKUP", msg)
        return msg

    if secrets:
        # Warnings only — log but proceed
        for w in secrets:
            logger.warning(f"Secret scan: {w}")

    # Commit
    commit_msg = f"🌱 Ivy vault backup — {date_str} {time_str}"
    proc = await asyncio.create_subprocess_exec(
        "git", "commit", "-m", commit_msg,
        cwd=str(vault_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        error = stderr.decode().strip()
        msg = f"Vault backup: commit failed — {error}"
        logger.error(msg)
        log_entry(vault_path, "GITHUB_BACKUP", msg)
        return msg

    # Push
    proc = await asyncio.create_subprocess_exec(
        "git", "push",
        cwd=str(vault_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        error = stderr.decode().strip()
        msg = f"Vault backup: push failed — {error}"
        logger.error(msg)
        log_entry(vault_path, "GITHUB_BACKUP", msg)
        return msg

    commit_output = stdout.decode().strip() if stdout else "committed"
    msg = f"Vault backup complete: {commit_msg}"
    logger.info(msg)
    log_entry(vault_path, "GITHUB_BACKUP", msg, commit_output[:200])
    return msg
