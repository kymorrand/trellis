"""Tests for trellis.hands.linear_client — Linear API client and loop integration."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trellis.core.loop import TOOL_DEFINITIONS, ToolExecutor
from trellis.hands.linear_client import LinearClient, format_issues


@pytest.fixture
def client() -> LinearClient:
    """Create a LinearClient with a fake API key."""
    return LinearClient(api_key="lin_test_fake_key", workspace_name="test")


class TestUpdateIssueState:
    """Tests for LinearClient.update_issue_state()."""

    @pytest.mark.asyncio
    async def test_returns_updated_issue(self, client: LinearClient) -> None:
        """Successful update returns issue dict with new state."""
        mock_response = {
            "data": {
                "issueUpdate": {
                    "success": True,
                    "issue": {
                        "id": "issue-123",
                        "identifier": "MOR-20",
                        "title": "Load kyle.md into system prompt",
                        "state": {"name": "Done", "type": "completed"},
                    },
                }
            }
        }
        with patch.object(client, "_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = mock_response["data"]
            result = await client.update_issue_state("issue-123", "state-done-id")

        assert result["id"] == "issue-123"
        assert result["identifier"] == "MOR-20"
        assert result["state"]["name"] == "Done"
        mock_query.assert_awaited_once()
        call_args = mock_query.call_args
        assert "issueUpdate" in call_args[0][0]
        assert call_args[1]["variables"]["issueId"] == "issue-123"
        assert call_args[1]["variables"]["stateId"] == "state-done-id"

    @pytest.mark.asyncio
    async def test_raises_on_failure(self, client: LinearClient) -> None:
        """Raises RuntimeError when Linear reports success=false."""
        mock_response = {"issueUpdate": {"success": False, "issue": None}}
        with patch.object(client, "_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = mock_response
            with pytest.raises(RuntimeError, match="Failed to update"):
                await client.update_issue_state("bad-id", "state-id")

    @pytest.mark.asyncio
    async def test_propagates_api_errors(self, client: LinearClient) -> None:
        """GraphQL errors from _query propagate as RuntimeError."""
        with patch.object(client, "_query", new_callable=AsyncMock) as mock_query:
            mock_query.side_effect = RuntimeError("Linear API error: not found")
            with pytest.raises(RuntimeError, match="not found"):
                await client.update_issue_state("missing-id", "state-id")


class TestGetWorkflowStates:
    """Tests for LinearClient.get_workflow_states()."""

    @pytest.mark.asyncio
    async def test_returns_states_list(self, client: LinearClient) -> None:
        """Returns list of workflow state dicts for a team."""
        mock_response = {
            "team": {
                "states": {
                    "nodes": [
                        {"id": "s1", "name": "Backlog", "type": "backlog", "position": 0},
                        {"id": "s2", "name": "In Progress", "type": "started", "position": 1},
                        {"id": "s3", "name": "Done", "type": "completed", "position": 2},
                        {"id": "s4", "name": "Canceled", "type": "canceled", "position": 3},
                    ]
                }
            }
        }
        with patch.object(client, "_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = mock_response
            states = await client.get_workflow_states("team-abc")

        assert len(states) == 4
        assert states[0]["name"] == "Backlog"
        assert states[2]["name"] == "Done"
        assert states[2]["type"] == "completed"
        call_args = mock_query.call_args
        assert call_args[1]["variables"]["teamId"] == "team-abc"

    @pytest.mark.asyncio
    async def test_empty_team_returns_empty(self, client: LinearClient) -> None:
        """Team with no states returns empty list."""
        mock_response = {"team": {"states": {"nodes": []}}}
        with patch.object(client, "_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = mock_response
            states = await client.get_workflow_states("team-empty")
        assert states == []

    @pytest.mark.asyncio
    async def test_missing_team_returns_empty(self, client: LinearClient) -> None:
        """If team query returns no data, returns empty list gracefully."""
        mock_response = {"team": None}
        with patch.object(client, "_query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = mock_response
            states = await client.get_workflow_states("nonexistent")
        assert states == []


class TestFormatIssues:
    """Tests for the format_issues helper."""

    def test_empty_list(self) -> None:
        assert format_issues([]) == "No issues found."

    def test_formats_basic_issue(self) -> None:
        issues = [
            {
                "identifier": "MOR-1",
                "title": "Test issue",
                "state": {"name": "Todo", "type": "unstarted"},
                "priority": 2,
            }
        ]
        result = format_issues(issues)
        assert "MOR-1" in result
        assert "Test issue" in result
        assert "Todo" in result

    def test_formats_with_project_and_assignee(self) -> None:
        issues = [
            {
                "identifier": "MOR-5",
                "title": "With extras",
                "state": {"name": "In Progress"},
                "priority": 1,
                "project": {"name": "Trellis"},
                "assignee": {"name": "Kyle"},
            }
        ]
        result = format_issues(issues)
        assert "[Trellis]" in result
        assert "Kyle" in result


# --- Loop Integration Tests: linear_read and linear_search ----------------


class TestLinearToolDefinitions:
    """Verify linear_read and linear_search are in TOOL_DEFINITIONS."""

    def test_linear_read_in_tool_definitions(self) -> None:
        names = [t["name"] for t in TOOL_DEFINITIONS]
        assert "linear_read" in names

    def test_linear_search_in_tool_definitions(self) -> None:
        names = [t["name"] for t in TOOL_DEFINITIONS]
        assert "linear_search" in names

    def test_linear_read_has_required_fields(self) -> None:
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "linear_read")
        assert "description" in tool
        assert "input_schema" in tool
        assert tool["input_schema"]["type"] == "object"

    def test_linear_search_has_required_fields(self) -> None:
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "linear_search")
        assert "description" in tool
        assert "input_schema" in tool
        assert "query" in tool["input_schema"].get("required", [])


class TestLinearPermissionMapping:
    """Verify permission keys map correctly for Linear tools."""

    @pytest.fixture()
    def executor(self, tmp_path: Path) -> ToolExecutor:
        return ToolExecutor(vault_path=tmp_path)

    def test_linear_read_permission_key(self, executor: ToolExecutor) -> None:
        assert executor._permission_key("linear_read", {}) == "linear_morrandmore_read"

    def test_linear_search_permission_key(self, executor: ToolExecutor) -> None:
        assert executor._permission_key("linear_search", {}) == "linear_morrandmore_read"


class TestLinearReadHandler:
    """Tests for ToolExecutor._linear_read handler."""

    @pytest.fixture()
    def executor_with_linear(self, tmp_path: Path) -> ToolExecutor:
        """Create a ToolExecutor with a mocked LinearClient."""
        executor = ToolExecutor(vault_path=tmp_path)
        executor.linear_client = MagicMock()
        return executor

    @pytest.mark.asyncio
    async def test_linear_read_returns_formatted_issues(
        self, executor_with_linear: ToolExecutor
    ) -> None:
        """linear_read calls get_team_issues and returns formatted output."""
        mock_issues = [
            {
                "identifier": "MOR-10",
                "title": "Wire Linear into loop",
                "state": {"name": "In Progress", "type": "started"},
                "priority": 2,
                "project": {"name": "Trellis"},
                "assignee": {"name": "Root"},
            }
        ]
        executor_with_linear.linear_client.get_team_issues = AsyncMock(
            return_value=mock_issues
        )
        result = await executor_with_linear._linear_read({"limit": 5})
        assert "MOR-10" in result
        assert "Wire Linear into loop" in result
        executor_with_linear.linear_client.get_team_issues.assert_awaited_once_with(
            "MOR", limit=5
        )

    @pytest.mark.asyncio
    async def test_linear_read_default_limit(
        self, executor_with_linear: ToolExecutor
    ) -> None:
        """linear_read uses default limit of 20 when not specified."""
        executor_with_linear.linear_client.get_team_issues = AsyncMock(
            return_value=[]
        )
        await executor_with_linear._linear_read({})
        executor_with_linear.linear_client.get_team_issues.assert_awaited_once_with(
            "MOR", limit=20
        )

    @pytest.mark.asyncio
    async def test_linear_read_no_client(self, tmp_path: Path) -> None:
        """Returns helpful message when Linear is not configured."""
        env_without_key = {
            k: v for k, v in os.environ.items()
            if k != "IVY_LINEAR_API_KEY_MORRANDMORE"
        }
        with patch.dict(os.environ, env_without_key, clear=True):
            executor = ToolExecutor(vault_path=tmp_path)
        result = await executor._linear_read({})
        assert "not configured" in result.lower()


class TestLinearSearchHandler:
    """Tests for ToolExecutor._linear_search handler."""

    @pytest.fixture()
    def executor_with_linear(self, tmp_path: Path) -> ToolExecutor:
        """Create a ToolExecutor with a mocked LinearClient."""
        executor = ToolExecutor(vault_path=tmp_path)
        executor.linear_client = MagicMock()
        return executor

    @pytest.mark.asyncio
    async def test_linear_search_returns_formatted_issues(
        self, executor_with_linear: ToolExecutor
    ) -> None:
        """linear_search calls search_issues and returns formatted output."""
        mock_issues = [
            {
                "identifier": "MOR-28",
                "title": "Wire Linear client into loop",
                "state": {"name": "Todo", "type": "unstarted"},
                "priority": 3,
                "project": None,
                "assignee": None,
            }
        ]
        executor_with_linear.linear_client.search_issues = AsyncMock(
            return_value=mock_issues
        )
        result = await executor_with_linear._linear_search(
            {"query": "Linear", "limit": 5}
        )
        assert "MOR-28" in result
        assert "Wire Linear client into loop" in result
        executor_with_linear.linear_client.search_issues.assert_awaited_once_with(
            "Linear", limit=5
        )

    @pytest.mark.asyncio
    async def test_linear_search_default_limit(
        self, executor_with_linear: ToolExecutor
    ) -> None:
        """linear_search uses default limit of 10 when not specified."""
        executor_with_linear.linear_client.search_issues = AsyncMock(
            return_value=[]
        )
        await executor_with_linear._linear_search({"query": "test"})
        executor_with_linear.linear_client.search_issues.assert_awaited_once_with(
            "test", limit=10
        )

    @pytest.mark.asyncio
    async def test_linear_search_no_client(self, tmp_path: Path) -> None:
        """Returns helpful message when Linear is not configured."""
        env_without_key = {
            k: v for k, v in os.environ.items()
            if k != "IVY_LINEAR_API_KEY_MORRANDMORE"
        }
        with patch.dict(os.environ, env_without_key, clear=True):
            executor = ToolExecutor(vault_path=tmp_path)
        result = await executor._linear_search({"query": "test"})
        assert "not configured" in result.lower()
