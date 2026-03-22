"""Tests for trellis.core.loop — ReAct event loop, Event, ToolExecutor, AgentBrain."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trellis.core.loop import (
    Event,
    MAX_TOOL_ROUNDS,
    TOOL_DEFINITIONS,
    ToolExecutor,
    AgentBrain,
)
from trellis.security.permissions import Permission


# ─── Event ───────────────────────────────────────────────


class TestEvent:
    def test_defaults(self):
        e = Event(source="cli", content="hello")
        assert e.source == "cli"
        assert e.content == "hello"
        assert e.channel_id == ""
        assert e.channel_name == ""
        assert isinstance(e.timestamp, datetime)
        assert e.metadata == {}

    def test_full_construction(self):
        e = Event(
            source="discord",
            content="test",
            channel_id=123,
            channel_name="general",
            metadata={"key": "value"},
        )
        assert e.channel_id == 123
        assert e.channel_name == "general"
        assert e.metadata["key"] == "value"


# ─── TOOL_DEFINITIONS ────────────────────────────────────


class TestToolDefinitions:
    def test_all_tools_have_required_fields(self):
        for tool in TOOL_DEFINITIONS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool

    def test_expected_tools_present(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "vault_search" in names
        assert "vault_read" in names
        assert "vault_save" in names
        assert "shell_execute" in names
        assert "journal_read" in names


# ─── ToolExecutor ────────────────────────────────────────


class TestToolExecutor:
    @pytest.fixture
    def vault(self, tmp_path):
        """Minimal vault with journal for testing."""
        # Create vault structure
        knowledge = tmp_path / "knowledge"
        knowledge.mkdir()
        (knowledge / "test-note.md").write_text(
            "# Test Note\n\nSome content about testing.\n"
        )

        # Journal
        journal_dir = tmp_path / "_ivy" / "journal"
        journal_dir.mkdir(parents=True)
        today = datetime.now().strftime("%Y-%m-%d")
        (journal_dir / f"{today}.md").write_text(
            "## 10:00 Entry one\nDid some stuff.\n\n## 11:00 Entry two\nDid more stuff.\n"
        )

        # Audit trail dir (needed by log_action)
        return tmp_path

    @pytest.fixture
    def executor(self, vault):
        return ToolExecutor(vault_path=vault)

    @pytest.mark.asyncio
    async def test_vault_search(self, executor):
        result = await executor.execute("vault_search", {"query": "testing"})
        assert "test-note.md" in result

    @pytest.mark.asyncio
    async def test_vault_search_no_results(self, executor):
        result = await executor.execute("vault_search", {"query": "zzzznonexistent"})
        assert "No vault items found" in result

    @pytest.mark.asyncio
    async def test_vault_read(self, executor):
        result = await executor.execute("vault_read", {"path": "knowledge/test-note.md"})
        assert "Some content about testing" in result

    @pytest.mark.asyncio
    async def test_vault_read_not_found(self, executor):
        result = await executor.execute("vault_read", {"path": "nope.md"})
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_vault_save(self, executor, vault):
        result = await executor.execute("vault_save", {
            "content": "Test content",
            "title": "test-save",
            "category": "drop",
        })
        assert "Saved to vault" in result

    @pytest.mark.asyncio
    async def test_shell_execute(self, executor):
        result = await executor.execute("shell_execute", {"command": "echo hello"})
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_shell_execute_blocked(self, executor):
        result = await executor.execute("shell_execute", {"command": "rm -rf /"})
        assert "Blocked" in result

    @pytest.mark.asyncio
    async def test_journal_read(self, executor):
        result = await executor.execute("journal_read", {})
        assert "Entry" in result

    @pytest.mark.asyncio
    async def test_journal_read_no_entries(self, executor):
        result = await executor.execute("journal_read", {"date": "1999-01-01"})
        assert "No journal entries" in result

    @pytest.mark.asyncio
    async def test_unknown_tool(self, executor):
        result = await executor.execute("nonexistent_tool", {})
        # Permission system defaults unknown to ASK
        assert "approval" in result.lower() or "unknown" in result.lower()

    @pytest.mark.asyncio
    async def test_denied_permission(self, executor):
        with patch("trellis.core.loop.check_permission", return_value=Permission.DENY):
            result = await executor.execute("vault_search", {"query": "test"})
            assert "Permission denied" in result

    @pytest.mark.asyncio
    async def test_ask_permission(self, executor):
        with patch("trellis.core.loop.check_permission", return_value=Permission.ASK):
            result = await executor.execute("vault_search", {"query": "test"})
            assert "approval" in result.lower()

    @pytest.mark.asyncio
    async def test_agent_state_updated(self, vault):
        mock_state = MagicMock()
        executor = ToolExecutor(vault_path=vault, agent_state=mock_state)
        await executor.execute("shell_execute", {"command": "echo hi"})
        mock_state.set.assert_called()

    @pytest.mark.asyncio
    async def test_tool_error_handled(self, executor):
        """Tool execution errors should be caught and returned as strings."""
        with patch.object(executor, "_run", side_effect=RuntimeError("boom")):
            result = await executor.execute("vault_search", {"query": "test"})
            assert "Error" in result
            assert "boom" in result

    def test_permission_key_mapping(self, executor):
        assert executor._permission_key("vault_search", {}) == "vault_read"
        assert executor._permission_key("vault_read", {}) == "vault_read"
        assert executor._permission_key("vault_save", {}) == "vault_write"
        assert executor._permission_key("shell_execute", {}) == "shell_whitelisted"
        assert executor._permission_key("journal_read", {}) == "vault_read"
        assert executor._permission_key("unknown", {}) == "unknown"

    @pytest.mark.asyncio
    async def test_vault_read_truncates_large_file(self, vault):
        """Files over 8000 chars should be truncated."""
        big_file = vault / "knowledge" / "big.md"
        big_file.write_text("x" * 10000)
        executor = ToolExecutor(vault_path=vault)
        result = await executor.execute("vault_read", {"path": "knowledge/big.md"})
        assert "truncated" in result


# ─── AgentBrain ──────────────────────────────────────────


class TestAgentBrain:
    @pytest.fixture
    def vault(self, tmp_path):
        knowledge = tmp_path / "knowledge"
        knowledge.mkdir()
        (knowledge / "note.md").write_text("# Note\nSome knowledge.\n")
        journal_dir = tmp_path / "_ivy" / "journal"
        journal_dir.mkdir(parents=True)
        return tmp_path

    @pytest.fixture
    def mock_anthropic(self):
        return MagicMock()

    @pytest.fixture
    def mock_router(self):
        router = MagicMock()
        router._session_cost = 0.0
        router.classify = MagicMock(return_value="cloud")
        return router

    @pytest.fixture
    def brain(self, mock_anthropic, mock_router, vault):
        with patch("trellis.core.loop.load_role", return_value={"name": "default", "tone": "warm", "autonomy_level": "medium"}):
            return AgentBrain(
                anthropic_client=mock_anthropic,
                router=mock_router,
                vault_path=vault,
                system_prompt="You are a test assistant.",
            )

    def test_construction(self, brain):
        assert brain.system_prompt == "You are a test assistant."
        assert brain._role_name == "_default"

    def test_set_role_fallback(self, brain):
        """Invalid role should fall back gracefully."""
        with patch("trellis.core.loop.load_role", side_effect=FileNotFoundError):
            brain.set_role("nonexistent")
        assert brain._role["name"] == "default"

    def test_build_system_prompt_default(self, brain):
        """Default role should not add role context."""
        prompt = brain._build_system_prompt()
        assert prompt == "You are a test assistant."

    def test_build_system_prompt_with_role(self, brain):
        """Non-default role should add role context."""
        brain._role = {"name": "analyst", "tone": "formal", "autonomy_level": "high", "description": "Analyze things."}
        prompt = brain._build_system_prompt()
        assert "[Active Role: analyst]" in prompt
        assert "Tone: formal" in prompt

    @pytest.mark.asyncio
    async def test_process_routes_to_local(self, brain, mock_router):
        """When router classifies as local, should call router.route."""
        mock_router.classify.return_value = "local"
        from trellis.mind.router import RouteResult, LOCAL_INDICATOR
        mock_router.route = AsyncMock(return_value=RouteResult(
            response="local response",
            model_used="qwen3:14b",
            is_local=True,
            indicator=LOCAL_INDICATOR,
        ))

        event = Event(source="cli", content="hi")
        result = await brain.process(event, [])
        assert result.response == "local response"
        assert result.is_local is True
        mock_router.route.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_cloud_react_loop(self, brain, mock_anthropic):
        """Cloud path: model returns text with no tool_use — single round."""
        # Mock the Anthropic API response
        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Hello from Claude!"

        mock_response = MagicMock()
        mock_response.content = [mock_text_block]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50

        mock_anthropic.messages.create.return_value = mock_response

        event = Event(source="cli", content="analyze something complex")
        result = await brain.process(event, [])

        assert result.response == "Hello from Claude!"
        assert result.is_local is False
        assert result.cost_usd > 0

    @pytest.mark.asyncio
    async def test_react_loop_with_tool_call(self, brain, mock_anthropic, vault):
        """Cloud path with one tool call round then text response."""
        # First response: tool_use
        mock_tool_block = MagicMock()
        mock_tool_block.type = "tool_use"
        mock_tool_block.name = "shell_execute"
        mock_tool_block.input = {"command": "echo test"}
        mock_tool_block.id = "tool_123"

        mock_response_1 = MagicMock()
        mock_response_1.content = [mock_tool_block]
        mock_response_1.usage.input_tokens = 100
        mock_response_1.usage.output_tokens = 50

        # Second response: text
        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Command output was: test"

        mock_response_2 = MagicMock()
        mock_response_2.content = [mock_text_block]
        mock_response_2.usage.input_tokens = 200
        mock_response_2.usage.output_tokens = 80

        mock_anthropic.messages.create.side_effect = [mock_response_1, mock_response_2]

        event = Event(source="cli", content="run echo test")
        result = await brain.process(event, [])

        assert result.response == "Command output was: test"
        assert mock_anthropic.messages.create.call_count == 2

    @pytest.mark.asyncio
    async def test_react_loop_max_rounds(self, brain, mock_anthropic):
        """Should stop after MAX_TOOL_ROUNDS even if model keeps calling tools."""
        mock_tool_block = MagicMock()
        mock_tool_block.type = "tool_use"
        mock_tool_block.name = "shell_execute"
        mock_tool_block.input = {"command": "echo loop"}
        mock_tool_block.id = "tool_loop"

        mock_response = MagicMock()
        mock_response.content = [mock_tool_block]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50

        # Always return tool_use — never text
        mock_anthropic.messages.create.return_value = mock_response

        event = Event(source="cli", content="do something complex")
        result = await brain.process(event, [])

        assert "stop here" in result.response.lower() or "need to stop" in result.response.lower()
        assert mock_anthropic.messages.create.call_count == MAX_TOOL_ROUNDS

    @pytest.mark.asyncio
    async def test_local_fallback_to_cloud(self, brain, mock_router, mock_anthropic):
        """If local model fails (non-forced), should fall back to cloud."""
        mock_router.classify.return_value = "local"
        mock_router.route = AsyncMock(side_effect=ConnectionError("Ollama down"))

        # Cloud fallback
        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Cloud fallback response"

        mock_response = MagicMock()
        mock_response.content = [mock_text_block]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50

        mock_anthropic.messages.create.return_value = mock_response

        event = Event(source="cli", content="hello")
        result = await brain.process(event, [])

        assert result.response == "Cloud fallback response"
        assert result.is_local is False

    @pytest.mark.asyncio
    async def test_force_local_does_not_fallback(self, brain, mock_router):
        """force_local should raise, not fall back to cloud."""
        mock_router.classify.return_value = "force_local"
        mock_router.route = AsyncMock(side_effect=ConnectionError("Ollama down"))

        event = Event(source="cli", content="/local hello")
        with pytest.raises(ConnectionError):
            await brain.process(event, [])
