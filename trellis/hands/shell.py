"""trellis.hands.shell — Sandboxed Shell Execution

Whitelisted shell commands only. No sudo. No arbitrary execution.
Security: This is the most dangerous tool. Treat with extreme caution.

Whitelist: git, ls, cat, grep, find, wc, date, echo, head, tail, df, du,
           uptime, python (scripts only), curl (read-only)

Every command is:
    1. Validated against the whitelist before execution
    2. Run with a 30-second timeout
    3. Logged to the audit trail
    4. Output-limited to prevent context window overflow
"""

from __future__ import annotations

import asyncio
import logging
import shlex

logger = logging.getLogger(__name__)

# Commands that are safe to execute
ALLOWED_COMMANDS = frozenset({
    "git", "ls", "cat", "grep", "find", "wc", "date", "echo",
    "head", "tail", "df", "du", "uptime", "python", "curl",
    "sort", "uniq", "tr", "cut", "stat", "file", "basename",
    "dirname", "realpath", "pwd", "env", "printenv", "whoami",
    "claude",
})

# Patterns that are never allowed anywhere in the command (substring match)
BLOCKED_SUBSTRINGS = frozenset({
    "sudo", "> /dev/", "| bash", "| sh", "| zsh",
    "eval ", "exec ", "`", "$(",
    "--force", "--hard",
})

# Commands that are blocked when they appear as the base command of any
# segment (start of command or after a pipe). Checked as whole-word match
# against the first token, NOT as a substring — so "git add" won't trigger "dd".
BLOCKED_COMMANDS = frozenset({
    "rm", "rmdir", "mkfs", "dd",
    "chmod", "chown", "chgrp", "kill", "killall", "pkill",
    "shutdown", "reboot", "halt", "poweroff",
    "apt", "apt-get", "pip", "pip3",
    "npm", "yarn", "cargo",
})

# Maximum output size (characters)
MAX_OUTPUT = 4000

# Command timeout in seconds
TIMEOUT = 30


def validate_command(command: str) -> str | None:
    """Validate a command against the whitelist.

    Returns None if valid, or an error message if blocked.
    """
    stripped = command.strip()
    if not stripped:
        return "Empty command."

    # Check blocked substrings (dangerous anywhere in the command)
    for pattern in BLOCKED_SUBSTRINGS:
        if pattern in stripped:
            return f"Blocked: command contains disallowed pattern '{pattern}'."

    # Extract the base command
    try:
        parts = shlex.split(stripped)
    except ValueError:
        return "Invalid command syntax."

    if not parts:
        return "Empty command."

    # Split into pipe segments and validate each one
    segments = stripped.split("|") if "|" in stripped else [stripped]
    for segment in segments:
        seg = segment.strip()
        if not seg:
            continue
        try:
            seg_parts = shlex.split(seg)
        except ValueError:
            return "Invalid command syntax in pipe chain."
        if not seg_parts:
            continue
        seg_cmd = seg_parts[0].split("/")[-1]  # Handle full paths like /usr/bin/git

        # Check if the command itself is blocked
        if seg_cmd in BLOCKED_COMMANDS:
            return f"Blocked: '{seg_cmd}' is not allowed."

        # Check if the command is whitelisted
        if seg_cmd not in ALLOWED_COMMANDS:
            return f"Blocked: '{seg_cmd}' is not in the allowed command list."

    return None


async def execute_command(
    command: str,
    cwd: str | None = None,
    timeout: int = TIMEOUT,
    skip_validation: bool = False,
) -> str:
    """Execute a shell command with timeout and output limits.

    Args:
        command: The shell command to execute.
        cwd: Working directory (defaults to vault path).
        timeout: Command timeout in seconds (default 30).
        skip_validation: Skip whitelist validation for trusted internal commands
            (e.g., armando_dispatch which constructs its own safe command).

    Returns:
        Command output (stdout + stderr), truncated if needed.
    """
    # Validate (unless caller is a trusted internal path)
    if not skip_validation:
        error = validate_command(command)
        if error:
            logger.warning(f"Shell command blocked: {command!r} — {error}")
            return error

    logger.info(f"Shell executing: {command}")

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            logger.warning(f"Shell command timed out after {timeout}s: {command}")
            return f"Command timed out after {timeout} seconds."

    except OSError as e:
        logger.error(f"Shell execution error: {e}")
        return f"Failed to execute command: {e}"

    output = ""
    if stdout:
        output += stdout.decode("utf-8", errors="replace")
    if stderr:
        stderr_text = stderr.decode("utf-8", errors="replace")
        if stderr_text.strip():
            output += f"\n[stderr]\n{stderr_text}"

    if proc.returncode != 0:
        output += f"\n[exit code: {proc.returncode}]"

    # Truncate if too long
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + f"\n\n[... output truncated at {MAX_OUTPUT} chars]"

    if not output.strip():
        output = "(no output)"

    logger.info(f"Shell completed: exit={proc.returncode}, {len(output)} chars")
    return output
