# Task: Add update_issue_state to LinearClient

**Date:** 2026-03-22
**From:** Thorn
**For:** Root
**Priority:** Low — unblocks Thorn's Linear write access

## What

Add an `update_issue_state()` method to `trellis/hands/linear_client.py`.

Thorn now has Linear write access (CLAUDE.md line 84-86) but the client only has `create_issue` — no way to update status on existing issues.

## Spec

```python
async def update_issue_state(self, issue_id: str, state_id: str) -> dict:
    """Update an issue's workflow state."""
```

Linear GraphQL mutation: `issueUpdate(id: $id, input: { stateId: $stateId })`

Should return the updated issue dict (`id`, `identifier`, `title`, `state { name type }`).

## Also Useful

- `get_workflow_states(team_id)` — query available states so Thorn can map "Done" → state ID without hardcoding.

## Files

- `trellis/hands/linear_client.py` — add methods
- `tests/test_linear_client.py` — add tests

## Context

First use case: Thorn marking MOR-20 as Done after merging Root's kyle.md work.
