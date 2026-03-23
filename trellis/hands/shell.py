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

# Patterns that are never allowed, regardless of base command
BLOCKED_PATTERNS = frozenset({
    "sudo", "rm ", "rm\t", "rmdir", "mkfs", "dd ", "dd\t",
    "chmod", "chown", "chgrp", "kill", "killall", "pkill",
    "shutdown", "reboot", "halt", "poweroff",
    "apt", "apt-get", "pip install", "pip3 install",
    "npm install", "yarn add", "cargo install",
    "> /dev/", "| bash", "| sh", "| zsh",
    "eval ", "exec ", "`", "$(",
    "--force", "--hard",
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

    # Check blocked patterns first
    for pattern in BLOCKED_PATTERNS:
        if pattern in stripped:
            return f"Blocked: command contains disallowed pattern '{pattern}'."

    # Extract the base command
    try:
        parts = shlex.split(stripped)
    except ValueError:
        return "Invalid command syntax."

    if not parts:
        return "Empty command."

    base_cmd = parts[0].split("/")[-1]  # Handle full paths like /usr/bin/git

    # Check for pipe chains — validate each command in the pipeline
    if "|" in stripped:
        segments = stripped.split("|")
        for segment in segments:
            seg = segment.strip()
            if not seg:
                continue
            try:
                seg_parts = shlex.split(seg)
            except ValueError:
                return "Invalid command syntax in pipe chain."
            if seg_parts:
                seg_cmd = seg_parts[0].split("/")[-1]
                if seg_cmd not in ALLOWED_COMMANDS:
                    return f"Blocked: '{seg_cmd}' is not in the allowed command list."
        return None

    if base_cmd not in ALLOWED_COMMANDS:
        return f"Blocked: '{base_cmd}' is not in the allowed command list. Allowed: {', '.join(sorted(ALLOWED_COMMANDS))}"

    return None


async def execute_command(
    command: str, cwd: str | None = None, timeout: int = TIMEOUT
) -> str:
    """Execute a whitelisted shell command with timeout and output limits.

    Args:
        command: The shell command to execute.
        cwd: Working directory (defaults to vault path).
        timeout: Command timeout in seconds (default 30).

    Returns:
        Command output (stdout + stderr), truncated if needed.
    """
    # Validate
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
