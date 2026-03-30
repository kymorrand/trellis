"""
trellis.core.chat_stream — UI Message Stream Protocol (Vercel AI SDK v6)

Implements the SSE streaming protocol expected by the Vercel AI SDK v6
`useChat` hook with `DefaultChatTransport`. The frontend POST /api/chat
proxy forwards requests here, and we stream SSE events back.

Protocol reference (UI Message Stream Protocol v1):
    data: {"type":"text","text":"token"}
    data: {"type":"finish","finishReason":"stop","usage":{...}}
    data: {"type":"error","error":"message"}

Each line is prefixed with `data: ` and followed by `\\n\\n` (standard SSE).

Endpoints:
    POST /api/chat — Accepts messages array, streams Ivy's response as SSE.

All endpoints require Authorization: Bearer {TRELLIS_API_KEY} header.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from trellis.core.quest_api import verify_api_key
from trellis.mind.router import CLOUD_MODEL

logger = logging.getLogger(__name__)

# ─── Default configuration ───────────────────────────────────

DEFAULT_MAX_TOKENS = 2048

# ─── Pydantic models ────────────────────────────────────────


class ChatMessage(BaseModel):
    """A single message in the conversation."""

    role: str
    content: str


class ChatRequest(BaseModel):
    """Request body for POST /api/chat."""

    messages: list[ChatMessage] = Field(..., min_length=1)
    system: str | None = None

    @field_validator("messages")
    @classmethod
    def validate_messages_not_empty(
        cls, v: list[ChatMessage],
    ) -> list[ChatMessage]:
        if not v:
            raise ValueError("messages must contain at least one message")
        return v


# ─── SSE encoding helpers ───────────────────────────────────


def encode_text_part(text: str) -> dict[str, Any]:
    """Create a text message part."""
    return {"type": "text", "text": text}


def encode_finish_part(
    finish_reason: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> dict[str, Any]:
    """Create a finish message part."""
    return {
        "type": "finish",
        "finishReason": finish_reason,
        "usage": {
            "promptTokens": prompt_tokens,
            "completionTokens": completion_tokens,
        },
    }


def encode_error_part(error: str) -> dict[str, Any]:
    """Create an error message part."""
    return {"type": "error", "error": error}


def encode_sse_event(data: dict[str, Any]) -> str:
    """Encode a dict as an SSE data line.

    Returns a string in the format: ``data: {json}\\n\\n``
    """
    return f"data: {json.dumps(data)}\n\n"


async def stream_sse_events(
    tokens: AsyncIterator[str],
) -> AsyncIterator[str]:
    """Wrap an async token iterator into SSE-formatted events.

    Yields ``data: {"type":"text","text":"..."}\\n\\n`` for each token,
    then a finish event. If the iterator raises, yields an error event.
    """
    try:
        async for token in tokens:
            yield encode_sse_event(encode_text_part(token))
        yield encode_sse_event(encode_finish_part("stop"))
    except Exception as exc:
        logger.error("Stream error: %s", exc)
        yield encode_sse_event(encode_error_part(str(exc)))


# ─── Router factory ─────────────────────────────────────────


def create_chat_router(
    anthropic_client: object | None = None,
    soul: str = "",
    ollama_url: str = "http://localhost:11434",
) -> APIRouter:
    """Create an APIRouter with the chat streaming endpoint.

    Args:
        anthropic_client: An ``anthropic.Anthropic`` client instance
            (or mock for testing). Used to call the LLM.
        soul: System prompt (Ivy's SOUL.md content) to prepend.
        ollama_url: Ollama base URL (reserved for future local routing).

    Returns:
        FastAPI APIRouter with ``POST /api/chat``.
    """
    router = APIRouter(prefix="/api/chat", tags=["chat"])

    @router.post("")
    async def chat(
        body: ChatRequest,
        _: None = Depends(verify_api_key),
    ) -> StreamingResponse:
        """Stream Ivy's response as SSE events.

        Accepts a conversation history and streams the assistant's reply
        token-by-token using the UI Message Stream Protocol v1.
        """
        # Build the messages list for the Anthropic API
        messages = [{"role": m.role, "content": m.content} for m in body.messages]

        # Use the provided system prompt, with optional override from request
        system_prompt = body.system or soul or "You are Ivy, a helpful assistant."

        # System prompt with prompt caching
        system_with_cache = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        async def generate() -> AsyncIterator[str]:
            """Stream tokens from the LLM, yielding SSE events."""
            try:
                if anthropic_client is None:
                    raise RuntimeError("No LLM client configured")

                async with anthropic_client.messages.stream(
                    model=CLOUD_MODEL,
                    max_tokens=DEFAULT_MAX_TOKENS,
                    system=system_with_cache,
                    messages=messages,
                ) as stream:
                    async for event in stream_sse_events(stream.text_stream):
                        yield event

            except Exception as exc:
                logger.error("Chat stream failed: %s", exc)
                yield encode_sse_event(encode_error_part(str(exc)))

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router
