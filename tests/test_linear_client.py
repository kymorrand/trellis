"""Tests for trellis.hands.linear_client — Linear API client."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

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
