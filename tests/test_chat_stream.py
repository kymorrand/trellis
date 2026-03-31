"""Tests for trellis.core.chat_stream — UI Message Stream Protocol endpoint."""

from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from trellis.core.chat_stream import (
    CHAT_TOOL_DISCLAIMER,
    WEB_TOOL_DEFINITIONS,
    create_chat_router,
    encode_sse_event,
    encode_start_part,
    encode_status_event,
    encode_text_start,
    encode_text_delta,
    encode_text_end,
    encode_finish_part,
    encode_error_part,
    stream_sse_events,
)

# ─── Test API key ─────────────────────────────────────────────

TEST_API_KEY = "test-key-12345"


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set TRELLIS_API_KEY for all tests."""
    monkeypatch.setenv("TRELLIS_API_KEY", TEST_API_KEY)


def _auth_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_API_KEY}"}


def _bad_auth_header() -> dict[str, str]:
    return {"Authorization": "Bearer wrong-key"}


# ─── SSE encoding unit tests ─────────────────────────────────


class TestSSEEncoding:
    """Test individual SSE encoding functions."""

    def test_encode_start_part(self) -> None:
        part = encode_start_part()
        assert part == {"type": "start"}

    def test_encode_text_start(self) -> None:
        part = encode_text_start("abc-123")
        assert part == {"type": "text-start", "id": "abc-123"}

    def test_encode_text_delta(self) -> None:
        part = encode_text_delta("abc-123", "Hello")
        assert part == {"type": "text-delta", "id": "abc-123", "delta": "Hello"}

    def test_encode_text_end(self) -> None:
        part = encode_text_end("abc-123")
        assert part == {"type": "text-end", "id": "abc-123"}

    def test_encode_finish_part(self) -> None:
        part = encode_finish_part("stop")
        assert part == {"type": "finish", "finishReason": "stop"}
        assert "usage" not in part

    def test_encode_error_part(self) -> None:
        part = encode_error_part("Something went wrong")
        assert part == {"type": "error", "errorText": "Something went wrong"}
        assert "error" not in part  # must use "errorText", not bare "error" key

    def test_encode_sse_event(self) -> None:
        data = {"type": "start"}
        line = encode_sse_event(data)
        assert line == f"data: {json.dumps(data)}\n\n"

    def test_encode_sse_event_no_extra_newlines(self) -> None:
        """SSE events must end with exactly \\n\\n."""
        line = encode_sse_event({"type": "start"})
        assert line.endswith("\n\n")
        assert not line.endswith("\n\n\n")


class TestStreamSSEEvents:
    """Test the async generator that wraps token iterators into SSE."""

    @pytest.mark.asyncio
    async def test_streams_tokens_then_finish(self) -> None:
        async def fake_tokens() -> AsyncIterator[str]:
            yield "Hello"
            yield ", "
            yield "Kyle!"

        events: list[str] = []
        async for event in stream_sse_events(fake_tokens()):
            events.append(event)

        parsed = [json.loads(e.removeprefix("data: ").strip()) for e in events]

        # start + text-start + 3 text-delta + text-end + finish = 7
        assert len(parsed) == 7

        assert parsed[0]["type"] == "start"
        assert parsed[1]["type"] == "text-start"
        text_id = parsed[1]["id"]
        assert text_id  # non-empty

        # Check text-delta events
        for i, token in enumerate(["Hello", ", ", "Kyle!"]):
            assert parsed[2 + i]["type"] == "text-delta"
            assert parsed[2 + i]["id"] == text_id
            assert parsed[2 + i]["delta"] == token

        assert parsed[5]["type"] == "text-end"
        assert parsed[5]["id"] == text_id

        assert parsed[6]["type"] == "finish"
        assert parsed[6]["finishReason"] == "stop"

    @pytest.mark.asyncio
    async def test_streams_error_on_exception(self) -> None:
        async def failing_tokens() -> AsyncIterator[str]:
            yield "Start"
            raise RuntimeError("LLM exploded")

        events: list[str] = []
        async for event in stream_sse_events(failing_tokens()):
            events.append(event)

        parsed = [json.loads(e.removeprefix("data: ").strip()) for e in events]

        # start + text-start + 1 text-delta + 1 error = 4
        assert len(parsed) == 4

        assert parsed[0]["type"] == "start"
        assert parsed[1]["type"] == "text-start"
        assert parsed[2]["type"] == "text-delta"
        assert parsed[2]["delta"] == "Start"

        assert parsed[3]["type"] == "error"
        assert "LLM exploded" in parsed[3]["errorText"]

    @pytest.mark.asyncio
    async def test_empty_stream_sends_finish(self) -> None:
        async def empty_tokens() -> AsyncIterator[str]:
            return
            yield  # noqa: F811 — unreachable yield makes this an async generator

        events: list[str] = []
        async for event in stream_sse_events(empty_tokens()):
            events.append(event)

        parsed = [json.loads(e.removeprefix("data: ").strip()) for e in events]

        # start + text-start + text-end + finish = 4
        assert len(parsed) == 4
        assert parsed[0]["type"] == "start"
        assert parsed[1]["type"] == "text-start"
        assert parsed[2]["type"] == "text-end"
        assert parsed[3]["type"] == "finish"


# ─── Endpoint integration tests ──────────────────────────────


def _make_app(
    anthropic_client: object | None = None,
    soul: str = "You are Ivy.",
    ollama_url: str = "http://localhost:11434",
    vault_path: Path | None = None,
    knowledge_manager: object | None = None,
) -> FastAPI:
    """Create a test app with the chat router."""
    app = FastAPI()
    router = create_chat_router(
        anthropic_client=anthropic_client,
        soul=soul,
        ollama_url=ollama_url,
        vault_path=vault_path,
        knowledge_manager=knowledge_manager,
    )
    app.include_router(router)
    return app


class TestAuthEndpoint:
    """Test auth on POST /api/chat."""

    @pytest.mark.asyncio
    async def test_missing_auth_returns_401(self) -> None:
        app = _make_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "hi"}]},
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_bad_auth_returns_401(self) -> None:
        app = _make_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers=_bad_auth_header(),
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_auth_returns_200(self) -> None:
        """Valid auth with mocked LLM should stream a 200 response."""
        mock_client = MagicMock()

        # Mock the streaming response
        mock_stream = AsyncMock()

        async def fake_text_stream() -> AsyncIterator[str]:
            yield "Hello"
            yield "!"

        mock_stream.text_stream = fake_text_stream()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_client.messages = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=mock_stream)

        app = _make_app(anthropic_client=mock_client)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers=_auth_header(),
            )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")


class TestChatStreaming:
    """Test SSE streaming from the chat endpoint."""

    @pytest.mark.asyncio
    async def test_streams_text_events(self) -> None:
        """POST /api/chat should stream text parts then finish."""
        mock_client = MagicMock()

        async def fake_text_stream() -> AsyncIterator[str]:
            yield "Hello"
            yield ", "
            yield "Kyle!"

        mock_stream = AsyncMock()
        mock_stream.text_stream = fake_text_stream()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_client.messages = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=mock_stream)

        app = _make_app(anthropic_client=mock_client, soul="Test soul")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers=_auth_header(),
            )

        assert resp.status_code == 200

        # Parse SSE events from response body
        lines = resp.text.strip().split("\n\n")
        events = []
        for line in lines:
            if line.startswith("data: "):
                events.append(json.loads(line.removeprefix("data: ")))

        # start + text-start + 3 text-delta + text-end + finish = 7
        assert len(events) == 7

        assert events[0]["type"] == "start"
        assert events[1]["type"] == "text-start"
        text_id = events[1]["id"]

        assert events[2] == {"type": "text-delta", "id": text_id, "delta": "Hello"}
        assert events[3] == {"type": "text-delta", "id": text_id, "delta": ", "}
        assert events[4] == {"type": "text-delta", "id": text_id, "delta": "Kyle!"}
        assert events[5] == {"type": "text-end", "id": text_id}
        assert events[6]["type"] == "finish"
        assert events[6]["finishReason"] == "stop"

    @pytest.mark.asyncio
    async def test_streams_error_on_llm_failure(self) -> None:
        """If the LLM raises, we should get an error SSE event."""
        mock_client = MagicMock()

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(
            side_effect=RuntimeError("Model unavailable")
        )
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_client.messages = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=mock_stream)

        app = _make_app(anthropic_client=mock_client)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers=_auth_header(),
            )

        assert resp.status_code == 200  # SSE streams always start 200

        lines = resp.text.strip().split("\n\n")
        events = []
        for line in lines:
            if line.startswith("data: "):
                events.append(json.loads(line.removeprefix("data: ")))

        # Should have at least an error event
        assert any(e["type"] == "error" for e in events)
        error_event = next(e for e in events if e["type"] == "error")
        assert "Model unavailable" in error_event["errorText"]

    @pytest.mark.asyncio
    async def test_passes_messages_to_model(self) -> None:
        """Verify conversation history is forwarded to the model."""
        mock_client = MagicMock()

        async def fake_text_stream() -> AsyncIterator[str]:
            yield "Response"

        mock_stream = AsyncMock()
        mock_stream.text_stream = fake_text_stream()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_client.messages = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=mock_stream)

        messages = [
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "First reply"},
            {"role": "user", "content": "Follow up"},
        ]

        app = _make_app(anthropic_client=mock_client, soul="Test soul")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/chat",
                json={"messages": messages},
                headers=_auth_header(),
            )

        # Verify messages were passed to the stream call
        call_kwargs = mock_client.messages.stream.call_args
        assert call_kwargs.kwargs["messages"] == messages

    @pytest.mark.asyncio
    async def test_empty_messages_returns_422(self) -> None:
        """Request with empty messages array should be rejected."""
        app = _make_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"messages": []},
                headers=_auth_header(),
            )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_messages_returns_422(self) -> None:
        """Request without messages field should be rejected."""
        app = _make_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={},
                headers=_auth_header(),
            )
        assert resp.status_code == 422


class TestToolDisclaimer:
    """Test that the chat endpoint appends the tool notice to the system prompt (MOR-83)."""

    @pytest.mark.asyncio
    async def test_disclaimer_appended_to_soul(self) -> None:
        """System prompt sent to the model must include the tool notice after soul."""
        mock_client = MagicMock()

        async def fake_text_stream() -> AsyncIterator[str]:
            yield "Ok"

        mock_stream = AsyncMock()
        mock_stream.text_stream = fake_text_stream()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_client.messages = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=mock_stream)

        soul_text = "You are Ivy, a brilliant AI assistant with vault access."
        # No vault_path → uses simple streaming path (messages.stream)
        app = _make_app(anthropic_client=mock_client, soul=soul_text)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "take a note"}]},
                headers=_auth_header(),
            )

        call_kwargs = mock_client.messages.stream.call_args
        system_blocks = call_kwargs.kwargs["system"]
        # System is a list of blocks with prompt caching
        assert len(system_blocks) == 1
        system_text = system_blocks[0]["text"]

        # Soul content should be at the beginning
        assert system_text.startswith(soul_text)
        # Tool notice should be appended after (MOR-83 updated version)
        assert "Web Chat Tool Access" in system_text
        assert "vault_search" in system_text
        assert "armando_dispatch" in system_text
        assert "Discord" in system_text

    @pytest.mark.asyncio
    async def test_disclaimer_appended_to_default_prompt(self) -> None:
        """Even the fallback prompt should include the tool notice."""
        mock_client = MagicMock()

        async def fake_text_stream() -> AsyncIterator[str]:
            yield "Ok"

        mock_stream = AsyncMock()
        mock_stream.text_stream = fake_text_stream()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_client.messages = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=mock_stream)

        # No soul provided — should fall back to default + disclaimer
        app = _make_app(anthropic_client=mock_client, soul="")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers=_auth_header(),
            )

        call_kwargs = mock_client.messages.stream.call_args
        system_blocks = call_kwargs.kwargs["system"]
        system_text = system_blocks[0]["text"]

        assert "You are Ivy, a helpful assistant." in system_text
        assert "Web Chat Tool Access" in system_text

    def test_disclaimer_constant_mentions_tools(self) -> None:
        """Verify the disclaimer constant lists available tools and limitations."""
        assert "vault_search" in CHAT_TOOL_DISCLAIMER
        assert "vault_read" in CHAT_TOOL_DISCLAIMER
        assert "shell_execute" in CHAT_TOOL_DISCLAIMER
        assert "Discord" in CHAT_TOOL_DISCLAIMER
        assert "armando_dispatch" in CHAT_TOOL_DISCLAIMER
        assert "request_restart" in CHAT_TOOL_DISCLAIMER


class TestSSEFormatCompliance:
    """Verify strict SSE format compliance."""

    @pytest.mark.asyncio
    async def test_each_event_has_data_prefix(self) -> None:
        """Every non-empty line must start with 'data: '."""
        mock_client = MagicMock()

        async def fake_text_stream() -> AsyncIterator[str]:
            yield "token"

        mock_stream = AsyncMock()
        mock_stream.text_stream = fake_text_stream()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_client.messages = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=mock_stream)

        app = _make_app(anthropic_client=mock_client)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers=_auth_header(),
            )

        raw = resp.text
        for line in raw.strip().split("\n"):
            line = line.strip()
            if line:
                assert line.startswith("data: "), f"Bad SSE line: {line!r}"

    @pytest.mark.asyncio
    async def test_each_event_is_valid_json(self) -> None:
        """The payload after 'data: ' must be valid JSON."""
        mock_client = MagicMock()

        async def fake_text_stream() -> AsyncIterator[str]:
            yield "hi"

        mock_stream = AsyncMock()
        mock_stream.text_stream = fake_text_stream()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_client.messages = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=mock_stream)

        app = _make_app(anthropic_client=mock_client)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers=_auth_header(),
            )

        for line in resp.text.strip().split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                payload = line.removeprefix("data: ")
                parsed = json.loads(payload)  # Should not raise
                assert "type" in parsed


# ─── Tool execution tests (MOR-83) ──────────────────────────


def _make_text_block(text: str) -> MagicMock:
    """Create a mock ContentBlock with type='text'."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _make_tool_use_block(
    tool_id: str, name: str, input_data: dict,
) -> MagicMock:
    """Create a mock ContentBlock with type='tool_use'."""
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = name
    block.input = input_data
    return block


def _make_mock_response(content_blocks: list, stop_reason: str = "end_turn") -> MagicMock:
    """Create a mock Anthropic messages.create response."""
    response = MagicMock()
    response.content = content_blocks
    response.stop_reason = stop_reason
    response.usage = MagicMock()
    response.usage.input_tokens = 100
    response.usage.output_tokens = 50
    return response


def _parse_sse_events(response_text: str) -> list[dict]:
    """Parse SSE data lines from response text into dicts."""
    events = []
    for line in response_text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            events.append(json.loads(line.removeprefix("data: ")))
    return events


class TestWebToolDefinitions:
    """Test that WEB_TOOL_DEFINITIONS excludes ASK-level tools."""

    def test_excludes_armando_dispatch(self) -> None:
        names = {t["name"] for t in WEB_TOOL_DEFINITIONS}
        assert "armando_dispatch" not in names

    def test_excludes_request_restart(self) -> None:
        names = {t["name"] for t in WEB_TOOL_DEFINITIONS}
        assert "request_restart" not in names

    def test_includes_allow_tools(self) -> None:
        names = {t["name"] for t in WEB_TOOL_DEFINITIONS}
        assert "vault_search" in names
        assert "vault_read" in names
        assert "vault_save" in names
        assert "shell_execute" in names
        assert "journal_read" in names
        assert "linear_read" in names
        assert "linear_search" in names


class TestStatusEvent:
    """Test the status event helper."""

    def test_encode_status_event(self) -> None:
        event = encode_status_event("vault_search", "executing")
        assert event == {
            "type": "status",
            "tool": "vault_search",
            "status": "executing",
        }


class TestToolExecution:
    """Test tool execution through the chat endpoint ReAct loop (MOR-83)."""

    @pytest.mark.asyncio
    async def test_tools_passed_to_api_call(self, tmp_path: Path) -> None:
        """When vault_path is provided, tools should be passed to messages.create."""
        mock_client = MagicMock()

        # Model returns a pure text response (no tools called)
        text_response = _make_mock_response([_make_text_block("Hello!")])
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=text_response)

        app = _make_app(
            anthropic_client=mock_client, vault_path=tmp_path,
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        # Verify tools were passed to messages.create
        call_kwargs = mock_client.messages.create.call_args
        assert "tools" in call_kwargs.kwargs
        tool_names = {t["name"] for t in call_kwargs.kwargs["tools"]}
        assert "vault_search" in tool_names
        # ASK-level tools should NOT be in the tool set
        assert "armando_dispatch" not in tool_names

    @pytest.mark.asyncio
    async def test_tool_execution_round_trip(self, tmp_path: Path) -> None:
        """Test that tool_use response triggers execution and feeds result back."""
        mock_client = MagicMock()

        # Round 1: Model calls vault_search
        tool_use_block = _make_tool_use_block(
            "tool-1", "vault_search", {"query": "test"},
        )
        round1_response = _make_mock_response(
            [tool_use_block], stop_reason="tool_use",
        )

        # Round 2: Model returns text after receiving tool result
        round2_response = _make_mock_response(
            [_make_text_block("Found 3 results in the vault.")],
        )

        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(
            side_effect=[round1_response, round2_response],
        )

        # Patch the ToolExecutor.execute to return a known result
        with patch.object(
            __import__("trellis.core.loop", fromlist=["ToolExecutor"]).ToolExecutor,
            "execute",
            new_callable=AsyncMock,
            return_value="3 results found for 'test'",
        ):
            app = _make_app(
                anthropic_client=mock_client, vault_path=tmp_path,
            )
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/chat",
                    json={"messages": [{"role": "user", "content": "search vault for test"}]},
                    headers=_auth_header(),
                )

        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)

        # Status events removed — AI SDK v6 rejects unknown event types.
        # Tool execution is logged server-side instead.

        # Should have the final text response
        text_deltas = [e for e in events if e.get("type") == "text-delta"]
        assert len(text_deltas) >= 1
        full_text = "".join(e["delta"] for e in text_deltas)
        assert "Found 3 results" in full_text

        # Should have called messages.create twice (two rounds)
        assert mock_client.messages.create.call_count == 2

        # Second call should include tool results in messages
        second_call = mock_client.messages.create.call_args_list[1]
        second_messages = second_call.kwargs["messages"]
        # Should have: original user msg, assistant (tool_use), user (tool_result)
        assert len(second_messages) == 3
        assert second_messages[2]["role"] == "user"
        tool_results = second_messages[2]["content"]
        assert tool_results[0]["type"] == "tool_result"
        assert tool_results[0]["tool_use_id"] == "tool-1"

    @pytest.mark.asyncio
    async def test_ask_permission_tool_refused(self, tmp_path: Path) -> None:
        """ASK-level tools should be refused with a message pointing to Discord."""
        mock_client = MagicMock()

        # Model tries to call armando_dispatch (which is ASK-level)
        # But wait — armando_dispatch is not in WEB_TOOL_DEFINITIONS,
        # so Claude shouldn't call it. Test with a hypothetical scenario
        # where the permission check itself returns ASK.
        tool_use_block = _make_tool_use_block(
            "tool-1", "vault_search", {"query": "test"},
        )
        round1_response = _make_mock_response(
            [tool_use_block], stop_reason="tool_use",
        )
        round2_response = _make_mock_response(
            [_make_text_block("Got it.")],
        )

        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(
            side_effect=[round1_response, round2_response],
        )

        # Override check_permission to return ASK for any tool
        with patch(
            "trellis.core.chat_stream.check_permission",
            return_value=__import__("trellis.security.permissions", fromlist=["Permission"]).Permission.ASK,
        ):
            app = _make_app(
                anthropic_client=mock_client, vault_path=tmp_path,
            )
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/chat",
                    json={"messages": [{"role": "user", "content": "search"}]},
                    headers=_auth_header(),
                )

        assert resp.status_code == 200
        # The tool result sent back to Claude should contain the refusal message
        second_call = mock_client.messages.create.call_args_list[1]
        second_messages = second_call.kwargs["messages"]
        tool_results = second_messages[2]["content"]
        assert "requires approval" in tool_results[0]["content"]
        assert "Discord" in tool_results[0]["content"]

    @pytest.mark.asyncio
    async def test_deny_permission_tool_refused(self, tmp_path: Path) -> None:
        """DENY-level tools should be refused."""
        mock_client = MagicMock()

        tool_use_block = _make_tool_use_block(
            "tool-1", "vault_search", {"query": "test"},
        )
        round1_response = _make_mock_response(
            [tool_use_block], stop_reason="tool_use",
        )
        round2_response = _make_mock_response(
            [_make_text_block("Ok.")],
        )

        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(
            side_effect=[round1_response, round2_response],
        )

        with patch(
            "trellis.core.chat_stream.check_permission",
            return_value=__import__("trellis.security.permissions", fromlist=["Permission"]).Permission.DENY,
        ):
            app = _make_app(
                anthropic_client=mock_client, vault_path=tmp_path,
            )
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/chat",
                    json={"messages": [{"role": "user", "content": "do something"}]},
                    headers=_auth_header(),
                )

        assert resp.status_code == 200
        second_call = mock_client.messages.create.call_args_list[1]
        second_messages = second_call.kwargs["messages"]
        tool_results = second_messages[2]["content"]
        assert "Permission denied" in tool_results[0]["content"]

    @pytest.mark.asyncio
    async def test_max_rounds_limit(self, tmp_path: Path) -> None:
        """ReAct loop should stop after MAX_TOOL_ROUNDS and return fallback."""
        from trellis.core.loop import MAX_TOOL_ROUNDS

        mock_client = MagicMock()

        # Every round returns a tool_use — never stops
        tool_use_block = _make_tool_use_block(
            "tool-1", "vault_search", {"query": "endless"},
        )
        tool_response = _make_mock_response(
            [tool_use_block], stop_reason="tool_use",
        )

        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=tool_response)

        with patch.object(
            __import__("trellis.core.loop", fromlist=["ToolExecutor"]).ToolExecutor,
            "execute",
            new_callable=AsyncMock,
            return_value="some result",
        ):
            app = _make_app(
                anthropic_client=mock_client, vault_path=tmp_path,
            )
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/chat",
                    json={"messages": [{"role": "user", "content": "loop forever"}]},
                    headers=_auth_header(),
                )

        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)

        # Should hit the fallback message
        text_deltas = [e for e in events if e.get("type") == "text-delta"]
        full_text = "".join(e["delta"] for e in text_deltas)
        assert "stop here" in full_text

        # Should have called create exactly MAX_TOOL_ROUNDS times
        assert mock_client.messages.create.call_count == MAX_TOOL_ROUNDS

    @pytest.mark.asyncio
    async def test_no_vault_path_uses_simple_streaming(self) -> None:
        """Without vault_path, should fall back to simple streaming (no tools)."""
        mock_client = MagicMock()

        async def fake_text_stream() -> AsyncIterator[str]:
            yield "Hello"

        mock_stream = AsyncMock()
        mock_stream.text_stream = fake_text_stream()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_client.messages = MagicMock()
        mock_client.messages.stream = MagicMock(return_value=mock_stream)

        # No vault_path → no tools → uses messages.stream
        app = _make_app(anthropic_client=mock_client)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        # Should have used messages.stream, NOT messages.create
        mock_client.messages.stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_pure_text_response_streams_correctly(self, tmp_path: Path) -> None:
        """When model returns text only (no tools), it should stream as normal."""
        mock_client = MagicMock()

        text_response = _make_mock_response([_make_text_block("Just a chat response.")])
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=text_response)

        app = _make_app(
            anthropic_client=mock_client, vault_path=tmp_path,
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "just chat"}]},
                headers=_auth_header(),
            )

        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)

        # Should have the full SSE sequence: start, text-start, text-delta, text-end, finish
        types = [e["type"] for e in events]
        assert types == ["start", "text-start", "text-delta", "text-end", "finish"]

        text_deltas = [e for e in events if e["type"] == "text-delta"]
        assert text_deltas[0]["delta"] == "Just a chat response."

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_in_single_round(self, tmp_path: Path) -> None:
        """Model can call multiple tools in a single round."""
        mock_client = MagicMock()

        # Round 1: Model calls two tools at once
        tool1 = _make_tool_use_block("tool-1", "vault_search", {"query": "a"})
        tool2 = _make_tool_use_block("tool-2", "journal_read", {"limit": 5})
        round1_response = _make_mock_response(
            [tool1, tool2], stop_reason="tool_use",
        )

        # Round 2: Text response
        round2_response = _make_mock_response(
            [_make_text_block("Here's what I found.")],
        )

        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(
            side_effect=[round1_response, round2_response],
        )

        with patch.object(
            __import__("trellis.core.loop", fromlist=["ToolExecutor"]).ToolExecutor,
            "execute",
            new_callable=AsyncMock,
            return_value="tool result",
        ):
            app = _make_app(
                anthropic_client=mock_client, vault_path=tmp_path,
            )
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/chat",
                    json={"messages": [{"role": "user", "content": "search and read journal"}]},
                    headers=_auth_header(),
                )

        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)

        # Status events removed — AI SDK v6 rejects unknown types.

        # Second call should have 2 tool results
        second_call = mock_client.messages.create.call_args_list[1]
        second_messages = second_call.kwargs["messages"]
        tool_results = second_messages[2]["content"]
        assert len(tool_results) == 2
        assert {r["tool_use_id"] for r in tool_results} == {"tool-1", "tool-2"}
