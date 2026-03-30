"""Tests for trellis.core.chat_stream — UI Message Stream Protocol endpoint."""

from __future__ import annotations

import json
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from trellis.core.chat_stream import (
    create_chat_router,
    encode_sse_event,
    encode_text_part,
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

    def test_encode_text_part(self) -> None:
        part = encode_text_part("Hello")
        assert part == {"type": "text", "text": "Hello"}

    def test_encode_finish_part(self) -> None:
        part = encode_finish_part("stop", prompt_tokens=100, completion_tokens=50)
        assert part == {
            "type": "finish",
            "finishReason": "stop",
            "usage": {"promptTokens": 100, "completionTokens": 50},
        }

    def test_encode_finish_part_defaults(self) -> None:
        part = encode_finish_part("stop")
        assert part["usage"]["promptTokens"] == 0
        assert part["usage"]["completionTokens"] == 0

    def test_encode_error_part(self) -> None:
        part = encode_error_part("Something went wrong")
        assert part == {"type": "error", "error": "Something went wrong"}

    def test_encode_sse_event(self) -> None:
        data = {"type": "text", "text": "hello"}
        line = encode_sse_event(data)
        assert line == f"data: {json.dumps(data)}\n\n"

    def test_encode_sse_event_no_extra_newlines(self) -> None:
        """SSE events must end with exactly \\n\\n."""
        line = encode_sse_event({"type": "text", "text": "x"})
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

        # Should have 3 text events + 1 finish event
        assert len(events) == 4

        # Check text events
        for i, token in enumerate(["Hello", ", ", "Kyle!"]):
            parsed = json.loads(events[i].removeprefix("data: ").strip())
            assert parsed["type"] == "text"
            assert parsed["text"] == token

        # Check finish event
        finish = json.loads(events[-1].removeprefix("data: ").strip())
        assert finish["type"] == "finish"
        assert finish["finishReason"] == "stop"

    @pytest.mark.asyncio
    async def test_streams_error_on_exception(self) -> None:
        async def failing_tokens() -> AsyncIterator[str]:
            yield "Start"
            raise RuntimeError("LLM exploded")

        events: list[str] = []
        async for event in stream_sse_events(failing_tokens()):
            events.append(event)

        # Should have 1 text event + 1 error event
        assert len(events) == 2

        error = json.loads(events[-1].removeprefix("data: ").strip())
        assert error["type"] == "error"
        assert "LLM exploded" in error["error"]

    @pytest.mark.asyncio
    async def test_empty_stream_sends_finish(self) -> None:
        async def empty_tokens() -> AsyncIterator[str]:
            return
            yield  # noqa: F811 — unreachable yield makes this an async generator

        events: list[str] = []
        async for event in stream_sse_events(empty_tokens()):
            events.append(event)

        assert len(events) == 1
        finish = json.loads(events[0].removeprefix("data: ").strip())
        assert finish["type"] == "finish"


# ─── Endpoint integration tests ──────────────────────────────


def _make_app(
    anthropic_client: object | None = None,
    soul: str = "You are Ivy.",
    ollama_url: str = "http://localhost:11434",
) -> FastAPI:
    """Create a test app with the chat router."""
    app = FastAPI()
    router = create_chat_router(
        anthropic_client=anthropic_client,
        soul=soul,
        ollama_url=ollama_url,
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

        # 3 text events + 1 finish
        assert len(events) == 4

        assert events[0] == {"type": "text", "text": "Hello"}
        assert events[1] == {"type": "text", "text": ", "}
        assert events[2] == {"type": "text", "text": "Kyle!"}
        assert events[3]["type"] == "finish"
        assert events[3]["finishReason"] == "stop"

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
        assert "Model unavailable" in error_event["error"]

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
