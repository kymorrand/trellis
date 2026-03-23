"""Tests for trellis.core.queue — File-based approval queue."""

import pytest
import yaml

from trellis.core.queue import ApprovalQueue


@pytest.fixture
def queue(tmp_path):
    """Create an ApprovalQueue backed by a tmp vault."""
    vault = tmp_path / "vault"
    vault.mkdir()
    return ApprovalQueue(vault)


class TestAddItem:
    def test_basic_add(self, queue):
        item_id = queue.add_item(
            item_type="suggestion",
            summary="Test item",
            body="Some body text",
        )
        assert item_id  # non-empty
        items = queue.list_items()
        assert len(items) == 1
        assert items[0]["id"] == item_id
        assert items[0]["summary"] == "Test item"

    def test_add_with_tool_name_and_input(self, queue):
        tool_input = {"command": "echo hello"}
        item_id = queue.add_item(
            item_type="tool_approval",
            summary="shell_execute: echo hello",
            body="Pending tool call",
            tool_name="shell_execute",
            tool_input=tool_input,
        )
        item = queue.get_item(item_id)
        assert item is not None
        assert item["tool_name"] == "shell_execute"
        assert item["tool_input"] == {"command": "echo hello"}

    def test_add_without_tool_fields_backward_compat(self, queue):
        """Items without tool_name/tool_input still work (backward compat)."""
        item_id = queue.add_item(
            item_type="suggestion",
            summary="No tool",
            body="Just a suggestion",
        )
        item = queue.get_item(item_id)
        assert item is not None
        assert item["tool_name"] == ""
        assert item["tool_input"] is None

    def test_tool_fields_in_frontmatter(self, queue):
        """Verify tool_name and tool_input are serialized to YAML frontmatter."""
        tool_input = {"query": "test search"}
        queue.add_item(
            item_type="tool_approval",
            summary="vault_search: test",
            body="Pending search",
            tool_name="vault_search",
            tool_input=tool_input,
        )
        # Read the raw file to check frontmatter
        files = list(queue.queue_dir.glob("*.md"))
        assert len(files) == 1
        text = files[0].read_text(encoding="utf-8")
        assert text.startswith("---")
        parts = text.split("---", 2)
        meta = yaml.safe_load(parts[1])
        assert meta["tool_name"] == "vault_search"
        assert meta["tool_input"] == {"query": "test search"}

    def test_tool_name_only_no_input(self, queue):
        """tool_name without tool_input — tool_name stored, tool_input absent."""
        item_id = queue.add_item(
            item_type="tool_approval",
            summary="manual approval",
            body="body",
            tool_name="custom_action",
        )
        item = queue.get_item(item_id)
        assert item["tool_name"] == "custom_action"
        assert item["tool_input"] is None


class TestGetItem:
    def test_get_existing(self, queue):
        item_id = queue.add_item(
            item_type="suggestion",
            summary="Findable",
            body="body",
            tool_name="vault_save",
            tool_input={"content": "data", "title": "t"},
        )
        item = queue.get_item(item_id)
        assert item is not None
        assert item["tool_name"] == "vault_save"
        assert item["tool_input"]["content"] == "data"

    def test_get_nonexistent(self, queue):
        assert queue.get_item("99999999-999999") is None


class TestApproveAndDismiss:
    def test_approve_moves_file(self, queue):
        item_id = queue.add_item(
            item_type="tool_approval",
            summary="Approve me",
            body="body",
        )
        assert queue.approve_item(item_id) is True
        assert queue.get_item(item_id) is None  # no longer pending
        approved_files = list((queue.queue_dir / "approved").glob("*.md"))
        assert len(approved_files) == 1

    def test_dismiss_moves_file(self, queue):
        item_id = queue.add_item(
            item_type="tool_approval",
            summary="Deny me",
            body="body",
        )
        assert queue.dismiss_item(item_id) is True
        assert queue.get_item(item_id) is None
        dismissed_files = list((queue.queue_dir / "dismissed").glob("*.md"))
        assert len(dismissed_files) == 1

    def test_approve_nonexistent(self, queue):
        assert queue.approve_item("nope") is False

    def test_dismiss_nonexistent(self, queue):
        assert queue.dismiss_item("nope") is False


class TestListItems:
    def test_empty_queue(self, queue):
        assert queue.list_items() == []

    def test_multiple_items(self, queue):
        queue.add_item(item_type="a", summary="First", body="b1")
        queue.add_item(item_type="b", summary="Second", body="b2")
        items = queue.list_items()
        assert len(items) == 2
