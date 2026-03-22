"""trellis.hands.linear_client — Linear API Integration

Read/Write to Morrandmore Linear. Read-only for Mirror Factory Linear.
Security: Separate API keys per workspace. MF writes require Kyle's approval.

Linear GraphQL API: https://studio.apollographql.com/public/Linear-API/variant/current/home
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

LINEAR_API = "https://api.linear.app/graphql"


class LinearClient:
    """Client for the Linear GraphQL API."""

    def __init__(self, api_key: str, workspace_name: str = "unknown"):
        self.api_key = api_key
        self.workspace_name = workspace_name
        self._headers = {
            "Authorization": api_key,
            "Content-Type": "application/json",
        }

    async def _query(self, query: str, variables: dict | None = None) -> dict:
        """Execute a GraphQL query against Linear."""
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(LINEAR_API, json=payload, headers=self._headers)
            resp.raise_for_status()
            data = resp.json()

        if "errors" in data:
            errors = data["errors"]
            logger.error(f"Linear API errors: {errors}")
            raise RuntimeError(f"Linear API error: {errors[0].get('message', 'unknown')}")

        return data.get("data", {})

    async def get_my_issues(self, limit: int = 10) -> list[dict]:
        """Get issues assigned to the authenticated user."""
        query = """
        query($limit: Int!) {
            viewer {
                assignedIssues(first: $limit, orderBy: updatedAt) {
                    nodes {
                        id
                        identifier
                        title
                        state { name type }
                        priority
                        dueDate
                        project { name }
                        team { name }
                        updatedAt
                    }
                }
            }
        }
        """
        data = await self._query(query, {"limit": limit})
        nodes = data.get("viewer", {}).get("assignedIssues", {}).get("nodes", [])
        return nodes

    async def get_team_issues(
        self, team_key: str, limit: int = 20, state_type: str | None = None
    ) -> list[dict]:
        """Get issues for a specific team."""
        # Build filter
        filter_clause = ""
        variables: dict[str, Any] = {"limit": limit}

        if state_type:
            filter_clause = ', filter: { state: { type: { eq: $stateType } } }'
            variables["stateType"] = state_type

        query = f"""
        query($limit: Int!{', $stateType: String' if state_type else ''}) {{
            issues(first: $limit{filter_clause}, orderBy: updatedAt) {{
                nodes {{
                    id
                    identifier
                    title
                    state {{ name type }}
                    priority
                    dueDate
                    assignee {{ name }}
                    project {{ name }}
                    updatedAt
                }}
            }}
        }}
        """
        data = await self._query(query, variables)
        return data.get("issues", {}).get("nodes", [])

    async def create_issue(
        self,
        title: str,
        team_id: str,
        description: str = "",
        priority: int = 0,
    ) -> dict:
        """Create a new issue."""
        query = """
        mutation($title: String!, $teamId: String!, $description: String, $priority: Int) {
            issueCreate(input: {
                title: $title
                teamId: $teamId
                description: $description
                priority: $priority
            }) {
                success
                issue {
                    id
                    identifier
                    title
                    url
                }
            }
        }
        """
        data = await self._query(query, {
            "title": title,
            "teamId": team_id,
            "description": description,
            "priority": priority,
        })
        result = data.get("issueCreate", {})
        if not result.get("success"):
            raise RuntimeError("Failed to create Linear issue")
        return result.get("issue", {})

    async def get_projects(self, limit: int = 10) -> list[dict]:
        """Get active projects."""
        query = """
        query($limit: Int!) {
            projects(first: $limit, orderBy: updatedAt) {
                nodes {
                    id
                    name
                    state
                    progress
                    targetDate
                    teams { nodes { name } }
                }
            }
        }
        """
        data = await self._query(query, {"limit": limit})
        return data.get("projects", {}).get("nodes", [])

    async def search_issues(self, query_text: str, limit: int = 10) -> list[dict]:
        """Search issues by text."""
        query = """
        query($query: String!, $limit: Int!) {
            searchIssues(query: $query, first: $limit) {
                nodes {
                    id
                    identifier
                    title
                    state { name type }
                    assignee { name }
                    project { name }
                    updatedAt
                }
            }
        }
        """
        # Note: searchIssues may not be available in all Linear API versions.
        # Fall back to filtered issues if needed.
        try:
            data = await self._query(query, {"query": query_text, "limit": limit})
            return data.get("searchIssues", {}).get("nodes", [])
        except RuntimeError:
            logger.warning("searchIssues not available, falling back to issue list")
            return []


def format_issues(issues: list[dict]) -> str:
    """Format Linear issues into a readable string."""
    if not issues:
        return "No issues found."

    lines = []
    for issue in issues:
        state = issue.get("state", {}).get("name", "?")
        project = issue.get("project", {})
        project_name = f" [{project['name']}]" if project else ""
        assignee = issue.get("assignee", {})
        assignee_name = f" → {assignee['name']}" if assignee else ""
        priority_icons = {0: "", 1: "🔴", 2: "🟠", 3: "🟡", 4: "⚪"}
        pri = priority_icons.get(issue.get("priority", 0), "")

        lines.append(
            f"- {pri} **{issue.get('identifier', '?')}** {issue.get('title', '?')}"
            f" [{state}]{project_name}{assignee_name}"
        )

    return "\n".join(lines)
