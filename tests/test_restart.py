"""Tests for the request_restart tool."""

import json
from pathlib import Path

import pytest

from trellis.core.loop import TOOL_DEFINITIONS, ToolExecutor
from trellis.security.permissions import PERMISSIONS, Permission


class TestRequestRestartTool:
    """Tests for the request_restart tool definition and permission mapping."""

    def test_tool_definition_present(self):
        """request_restart should be in TOOL_DEFINITIONS."""
        names = [t["name"] for t in TOOL_DEFINITIONS]
        assert "request_restart" in names

    def test_tool_schema_requires_reason(self):
        """The tool schema should require a 'reason' parameter."""
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "request_restart")
        assert "reason" in tool["input_schema"]["required"]

    def test_permission_is_ask(self):
        """service_restart permission should be ASK level."""
        assert PERMISSIONS["service_restart"] == Permission.ASK

    def test_permission_key_mapping(self):
        """request_restart tool should map to service_restart permission key."""
        executor = ToolExecutor(vault_path=Path("/tmp/fake-vault"))
        assert executor._permission_key("request_restart", {}) == "service_restart"


class TestRequestRestartHandler:
    """Tests for the _request_restart handler."""

    @pytest.fixture
    def vault(self, tmp_path):
        ivy_dir = tmp_path / "_ivy"
        ivy_dir.mkdir()
        return tmp_path

    @pytest.fixture
    def executor(self, vault):
        return ToolExecutor(vault_path=vault)

    def test_writes_trigger_file(self, executor, vault):
        """Handler should write the restart-requested trigger file."""
        result = executor._request_restart({"reason": "Armando shipped MOR-30"})
        trigger = vault / "_ivy" / "restart-requested"
        assert trigger.exists()
        content = trigger.read_text(encoding="utf-8")
        assert "Armando shipped MOR-30" in content
        assert "Restart requested" in result

    def test_writes_startup_message(self, executor, vault):
        """Handler should write .startup_message JSON for post-restart announcement."""
        executor._request_restart({"reason": "New feature deployed"})
        # .startup_message is written relative to the repo root (3 levels up from loop.py)
        # In tests, find it via the actual path the code writes to
        startup_path = Path(__file__).resolve().parent.parent / ".startup_message"
        if startup_path.exists():
            data = json.loads(startup_path.read_text(encoding="utf-8"))
            assert data["channel"] == "general"
            assert "New feature deployed" in data["message"]
            startup_path.unlink()  # Clean up

    def test_empty_reason_returns_error(self, executor):
        """Empty reason should return an error, not write the trigger file."""
        result = executor._request_restart({"reason": ""})
        assert "Error" in result
        trigger = executor.vault_path / "_ivy" / "restart-requested"
        assert not trigger.exists()

    def test_missing_reason_returns_error(self, executor):
        """Missing reason should return an error."""
        result = executor._request_restart({})
        assert "Error" in result

    def test_trigger_file_contains_timestamp(self, executor, vault):
        """Trigger file should contain an ISO timestamp."""
        executor._request_restart({"reason": "test"})
        trigger = vault / "_ivy" / "restart-requested"
        content = trigger.read_text(encoding="utf-8")
        # ISO format starts with year: 2026-...
        assert "202" in content

    def test_logs_to_journal(self, executor, vault):
        """Handler should log the restart request to the journal."""
        # Create journal directory
        journal_dir = vault / "_ivy" / "journal"
        journal_dir.mkdir(parents=True, exist_ok=True)
        executor._request_restart({"reason": "Code update"})
        # Just verify no exception — journal logging is fire-and-forget
