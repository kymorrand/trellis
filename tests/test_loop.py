"""Tests for trellis.core.loop — ReAct event loop, Event, ToolExecutor, AgentBrain."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trellis.core.loop import (
    AgentBrain,
    Event,
    MAX_TOOL_ROUNDS,
    TOOL_DEFINITIONS,
    ToolExecutor,
)


def _mock_usage(input_tokens=100, output_tokens=50):
    """Create a mock usage object with cache fields."""
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.cache_read_input_tokens = 0
    usage.cache_creation_input_tokens = 0
    return usage

from trellis.security.permissions import Permission  # noqa: E402


# --- Event ---------------------------------------------------------


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


# --- TOOL_DEFINITIONS ----------------------------------------------


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
        assert "armando_dispatch" in names

    def test_armando_dispatch_schema(self):
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "armando_dispatch")
        schema = tool["input_schema"]
        assert "message" in schema["properties"]
        assert "project_dir" in schema["properties"]
        assert schema["required"] == ["message", "project_dir"]


# --- ToolExecutor ---------------------------------------------------


class TestToolExecutor:
    @pytest.fixture()
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

    @pytest.fixture()
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
    async def test_ask_permission_no_queue(self, executor):
        """ASK permission without queue — soft deny with message."""
        with patch("trellis.core.loop.check_permission", return_value=Permission.ASK):
            result = await executor.execute("vault_search", {"query": "test"})
            assert "approval" in result.lower()
            assert "noted" in result.lower()

    @pytest.mark.asyncio
    async def test_ask_permission_with_queue(self, vault):
        """ASK permission with queue — creates queue item with tool context."""
        mock_queue = MagicMock()
        mock_queue.add_item.return_value = "20260322-140000"
        executor = ToolExecutor(vault_path=vault, approval_queue=mock_queue)
        with patch("trellis.core.loop.check_permission", return_value=Permission.ASK):
            result = await executor.execute("vault_search", {"query": "test"})
            assert "approval" in result.lower()
            assert "queue" in result.lower()
            assert "20260322-140000" in result
            mock_queue.add_item.assert_called_once()
            call_kwargs = mock_queue.add_item.call_args
            assert call_kwargs[1]["item_type"] == "tool_approval"
            assert call_kwargs[1]["tool_name"] == "vault_search"
            assert call_kwargs[1]["tool_input"] == {"query": "test"}

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
        assert executor._permission_key("armando_dispatch", {}) == "armando_dispatch"
        assert executor._permission_key("journal_read", {}) == "vault_read"
        assert executor._permission_key("unknown", {}) == "unknown"

    def test_armando_dispatch_permission_is_ask(self):
        from trellis.security.permissions import check_permission
        perm = check_permission("armando_dispatch")
        assert perm == Permission.ASK

    @pytest.mark.asyncio
    async def test_armando_dispatch_empty_message(self, executor):
        # Bypass the permission check (ASK would queue it)
        result = await executor._armando_dispatch({"message": "", "project_dir": "/tmp"})
        assert "message is required" in result

    @pytest.mark.asyncio
    async def test_armando_dispatch_empty_project_dir(self, executor):
        result = await executor._armando_dispatch({"message": "do stuff", "project_dir": ""})
        assert "project_dir is required" in result

    @pytest.mark.asyncio
    async def test_armando_dispatch_nonexistent_dir(self, executor):
        result = await executor._armando_dispatch({
            "message": "do stuff",
            "project_dir": "/nonexistent/path/xyz",
        })
        assert "does not exist" in result

    @pytest.mark.asyncio
    async def test_armando_dispatch_builds_correct_command(self, executor, tmp_path):
        with patch("trellis.hands.shell.execute_command", new_callable=AsyncMock) as mock_exec, \
             patch("shutil.which", return_value="/usr/local/bin/claude"):
            mock_exec.return_value = "Sprint completed."
            result = await executor._armando_dispatch({
                "message": "Fix the bug in loop.py",
                "project_dir": str(tmp_path),
            })
            mock_exec.assert_awaited_once()
            call_args = mock_exec.call_args
            cmd = call_args[0][0]
            assert cmd.startswith("/usr/local/bin/claude")
            assert "--dangerously-skip-permissions" in cmd
            assert "--agent thorn" in cmd
            assert "-p" in cmd
            assert "Fix the bug in loop.py" in cmd
            assert "--max-budget-usd 5" in cmd
            assert "--no-session-persistence" in cmd
            assert call_args[1]["cwd"] == str(tmp_path)
            assert call_args[1]["timeout"] == 1800
            assert result == "Sprint completed."

    @pytest.mark.asyncio
    async def test_armando_dispatch_uses_shutil_which(self, executor, tmp_path):
        """When shutil.which finds claude, the full resolved path is used."""
        with patch("trellis.hands.shell.execute_command", new_callable=AsyncMock) as mock_exec, \
             patch("shutil.which", return_value="/home/kyle/.local/bin/claude"):
            mock_exec.return_value = "Done."
            await executor._armando_dispatch({
                "message": "test task",
                "project_dir": str(tmp_path),
            })
            cmd = mock_exec.call_args[0][0]
            assert cmd.startswith("/home/kyle/.local/bin/claude ")

    @pytest.mark.asyncio
    async def test_armando_dispatch_fallback_path(self, executor, tmp_path):
        """When shutil.which returns None but fallback path exists, uses fallback."""
        fallback = "/home/kyle/.local/bin/claude"
        with patch("trellis.hands.shell.execute_command", new_callable=AsyncMock) as mock_exec, \
             patch("shutil.which", return_value=None), \
             patch("pathlib.Path.is_file", return_value=True):
            mock_exec.return_value = "Done."
            await executor._armando_dispatch({
                "message": "test task",
                "project_dir": str(tmp_path),
            })
            cmd = mock_exec.call_args[0][0]
            assert cmd.startswith(fallback)

    @pytest.mark.asyncio
    async def test_armando_dispatch_claude_not_found(self, executor, tmp_path):
        """When neither shutil.which nor fallback finds claude, returns error."""
        with patch("shutil.which", return_value=None), \
             patch("pathlib.Path.is_file", return_value=False), \
             patch("pathlib.Path.is_dir", return_value=True):
            result = await executor._armando_dispatch({
                "message": "test task",
                "project_dir": str(tmp_path),
            })
            assert "claude CLI not found" in result
            assert "Install it or check PATH" in result

    @pytest.mark.asyncio
    async def test_vault_read_truncates_large_file(self, vault):
        """Files over 8000 chars should be truncated."""
        big_file = vault / "knowledge" / "big.md"
        big_file.write_text("x" * 10000)
        executor = ToolExecutor(vault_path=vault)
        result = await executor.execute("vault_read", {"path": "knowledge/big.md"})
        assert "truncated" in result

    @pytest.mark.asyncio
    async def test_vault_search_uses_knowledge_manager(self, vault):
        """When knowledge_manager is provided, vault_search uses hybrid search."""
        mock_km = MagicMock()
        mock_km.search = AsyncMock(
            return_value=[
                {"path": "knowledge/test-note.md", "matches": ["hybrid result"], "score": 0.9}
            ]
        )
        executor = ToolExecutor(vault_path=vault, knowledge_manager=mock_km)
        result = await executor.execute("vault_search", {"query": "testing"})
        mock_km.search.assert_awaited_once()
        assert "test-note.md" in result

    @pytest.mark.asyncio
    async def test_vault_search_fallback_when_hybrid_fails(self, vault):
        """If hybrid search fails, falls back to keyword search."""
        mock_km = MagicMock()
        mock_km.search = AsyncMock(side_effect=RuntimeError("Ollama down"))
        executor = ToolExecutor(vault_path=vault, knowledge_manager=mock_km)
        result = await executor.execute("vault_search", {"query": "testing"})
        # Should still work via keyword fallback
        assert "test-note.md" in result

    @pytest.mark.asyncio
    async def test_vault_search_without_knowledge_manager(self, vault):
        """Without knowledge_manager, vault_search uses keyword search only."""
        executor = ToolExecutor(vault_path=vault, knowledge_manager=None)
        result = await executor.execute("vault_search", {"query": "testing"})
        assert "test-note.md" in result


# --- AgentBrain ----------------------------------------------------


class TestAgentBrain:
    @pytest.fixture()
    def vault(self, tmp_path):
        knowledge = tmp_path / "knowledge"
        knowledge.mkdir()
        (knowledge / "note.md").write_text("# Note\nSome knowledge.\n")
        journal_dir = tmp_path / "_ivy" / "journal"
        journal_dir.mkdir(parents=True)
        return tmp_path

    @pytest.fixture()
    def mock_anthropic(self):
        return MagicMock()

    @pytest.fixture()
    def mock_router(self):
        router = MagicMock()
        router._session_cost = 0.0
        router.classify = MagicMock(return_value="cloud")
        return router

    @pytest.fixture()
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

    def test_construction_with_knowledge_manager(self, mock_anthropic, mock_router, vault):
        """AgentBrain accepts and stores knowledge_manager."""
        mock_km = MagicMock()
        with patch("trellis.core.loop.load_role", return_value={"name": "default", "tone": "warm", "autonomy_level": "medium"}):
            brain = AgentBrain(
                anthropic_client=mock_anthropic,
                router=mock_router,
                vault_path=vault,
                system_prompt="Test",
                knowledge_manager=mock_km,
            )
        assert brain.knowledge_manager is mock_km
        assert brain.tool_executor.knowledge_manager is mock_km

    def test_construction_with_approval_queue(self, mock_anthropic, mock_router, vault):
        """AgentBrain accepts and stores approval_queue."""
        mock_queue = MagicMock()
        with patch("trellis.core.loop.load_role", return_value={"name": "default", "tone": "warm", "autonomy_level": "medium"}):
            brain = AgentBrain(
                anthropic_client=mock_anthropic,
                router=mock_router,
                vault_path=vault,
                system_prompt="Test",
                approval_queue=mock_queue,
            )
        assert brain.approval_queue is mock_queue
        assert brain.tool_executor.approval_queue is mock_queue

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
        from trellis.mind.router import LOCAL_INDICATOR, RouteResult
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
        mock_response.usage = _mock_usage(100, 50)

        mock_anthropic.messages.create.return_value = mock_response

        event = Event(source="cli", content="architect something complex")
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
        mock_response_1.usage = _mock_usage(100, 50)

        # Second response: text
        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Command output was: test"

        mock_response_2 = MagicMock()
        mock_response_2.content = [mock_text_block]
        mock_response_2.usage = _mock_usage(200, 80)

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
        mock_response.usage = _mock_usage(100, 50)

        # Always return tool_use — never text
        mock_anthropic.messages.create.return_value = mock_response

        event = Event(source="cli", content="architect something complex")
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
        mock_response.usage = _mock_usage(100, 50)

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

    @pytest.mark.asyncio
    async def test_used_tools_flag_set_when_tools_called(self, brain, mock_anthropic):
        """used_tools should be True when the ReAct loop executes tool calls."""
        # First response: tool_use
        mock_tool_block = MagicMock()
        mock_tool_block.type = "tool_use"
        mock_tool_block.name = "shell_execute"
        mock_tool_block.input = {"command": "echo test"}
        mock_tool_block.id = "tool_456"

        mock_response_1 = MagicMock()
        mock_response_1.content = [mock_tool_block]
        mock_response_1.usage = _mock_usage(100, 50)

        # Second response: text (no tools)
        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Done."

        mock_response_2 = MagicMock()
        mock_response_2.content = [mock_text_block]
        mock_response_2.usage = _mock_usage(200, 80)

        mock_anthropic.messages.create.side_effect = [mock_response_1, mock_response_2]

        event = Event(source="cli", content="run echo test")
        result = await brain.process(event, [])

        assert result.used_tools is True

    @pytest.mark.asyncio
    async def test_used_tools_flag_false_when_no_tools(self, brain, mock_anthropic):
        """used_tools should be False when model responds without tool calls."""
        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Hello!"

        mock_response = MagicMock()
        mock_response.content = [mock_text_block]
        mock_response.usage = _mock_usage(100, 50)

        mock_anthropic.messages.create.return_value = mock_response

        event = Event(source="cli", content="architect something complex")
        result = await brain.process(event, [])

        assert result.used_tools is False

    @pytest.mark.asyncio
    async def test_used_tools_flag_set_on_max_rounds(self, brain, mock_anthropic):
        """used_tools should be True even when max rounds exceeded."""
        mock_tool_block = MagicMock()
        mock_tool_block.type = "tool_use"
        mock_tool_block.name = "shell_execute"
        mock_tool_block.input = {"command": "echo loop"}
        mock_tool_block.id = "tool_loop"

        mock_response = MagicMock()
        mock_response.content = [mock_tool_block]
        mock_response.usage = _mock_usage(100, 50)

        mock_anthropic.messages.create.return_value = mock_response

        event = Event(source="cli", content="architect something complex")
        result = await brain.process(event, [])

        assert result.used_tools is True

    @pytest.mark.asyncio
    async def test_force_cloud_overrides_local_routing(self, brain, mock_router, mock_anthropic):
        """force_cloud metadata should override local routing to cloud."""
        mock_router.classify.return_value = "local"

        # Set up cloud response (will go through _react_loop)
        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Cloud response"
        mock_response = MagicMock()
        mock_response.content = [mock_text_block]
        mock_response.usage = _mock_usage(100, 50)
        mock_anthropic.messages.create.return_value = mock_response

        event = Event(source="cli", content="yes", metadata={"force_cloud": True})
        result = await brain.process(event, [])

        # Should have gone to cloud despite "local" classification
        assert result.is_local is False
        assert result.response == "Cloud response"
        # router.route should NOT have been called (skipped local path)
        mock_router.route.assert_not_called()

    @pytest.mark.asyncio
    async def test_force_cloud_overrides_light_routing(self, brain, mock_router, mock_anthropic):
        """force_cloud metadata should override light routing to full cloud with tools."""
        mock_router.classify.return_value = "light"

        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Full cloud response"
        mock_response = MagicMock()
        mock_response.content = [mock_text_block]
        mock_response.usage = _mock_usage(100, 50)
        mock_anthropic.messages.create.return_value = mock_response

        event = Event(source="cli", content="do it", metadata={"force_cloud": True})
        result = await brain.process(event, [])

        assert result.is_local is False
        assert result.response == "Full cloud response"
        # Should go through _react_loop (Anthropic API), not router.route
        mock_anthropic.messages.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_force_cloud_does_not_override_force_local(self, brain, mock_router):
        """force_cloud should NOT override explicit /local prefix."""
        mock_router.classify.return_value = "force_local"
        from trellis.mind.router import RouteResult
        mock_router.route = AsyncMock(return_value=RouteResult(
            response="local response", model_used="qwen3:14b", is_local=True, indicator="🌿"
        ))

        event = Event(source="cli", content="/local yes", metadata={"force_cloud": True})
        result = await brain.process(event, [])
        assert result.is_local is True

    @pytest.mark.asyncio
    async def test_force_cloud_does_not_override_force_cloud(self, brain, mock_router, mock_anthropic):
        """force_cloud metadata should not interfere with explicit /claude prefix."""
        mock_router.classify.return_value = "force_cloud"

        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Cloud response"
        mock_response = MagicMock()
        mock_response.content = [mock_text_block]
        mock_response.usage = _mock_usage(100, 50)
        mock_anthropic.messages.create.return_value = mock_response

        event = Event(source="cli", content="/claude hello", metadata={"force_cloud": True})
        result = await brain.process(event, [])
        assert result.is_local is False
