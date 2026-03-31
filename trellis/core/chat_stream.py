"""
trellis.core.chat_stream — UI Message Stream Protocol v1 (Vercel AI SDK v6)

Implements the SSE streaming protocol expected by the Vercel AI SDK v6
`useChat` hook with `DefaultChatTransport`. The frontend POST /api/chat
proxy forwards requests here, and we stream SSE events back.

Protocol reference (UI Message Stream Protocol v1):
    data: {"type":"start"}
    data: {"type":"text-start","id":"<unique-id>"}
    data: {"type":"text-delta","id":"<unique-id>","delta":"token"}
    data: {"type":"text-end","id":"<unique-id>"}
    data: {"type":"finish","finishReason":"stop"}
    data: {"type":"error","errorText":"message"}

Each line is prefixed with `data: ` and followed by `\\n\\n` (standard SSE).

Endpoints:
    POST /api/chat — Accepts messages array, streams Ivy's response as SSE.

All endpoints require Authorization: Bearer {TRELLIS_API_KEY} header.

Tool calling (MOR-83):
    The chat endpoint supports server-side tool execution via a ReAct loop.
    Tools are defined in trellis.core.loop.TOOL_DEFINITIONS and executed via
    ToolExecutor. The client does not need to handle tool_use blocks — all tool
    execution happens server-side, and only the final text response is streamed.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from trellis.core.loop import MAX_TOOL_ROUNDS, TOOL_DEFINITIONS, ToolExecutor
from trellis.core.quest_api import verify_api_key
from trellis.mind.router import CLOUD_MODEL
from trellis.security.permissions import Permission, check_permission

if TYPE_CHECKING:
    from trellis.memory.knowledge import KnowledgeManager

logger = logging.getLogger(__name__)

# ─── Default configuration ───────────────────────────────────

DEFAULT_MAX_TOKENS = 2048

# Tools that require the Discord approval flow (ASK-level permissions).
# These are excluded from the web chat tool set.
_ASK_TOOLS = {"armando_dispatch", "request_restart"}

# Build the web-safe tool set: exclude tools that require approval flow
WEB_TOOL_DEFINITIONS = [t for t in TOOL_DEFINITIONS if t["name"] not in _ASK_TOOLS]

# ─── Chat interface tool notice ──────────────────────────────
# Appended to the system prompt so Ivy knows what tools are available
# in the web chat interface. Updated from MOR-82 disclaimer now that
# tools ARE wired up (MOR-83).

CHAT_TOOL_DISCLAIMER = """

## Web Chat Tool Access

This conversation is through the Trellis web chat interface. You have access to the following tools in this conversation:
- **vault_search** — Search the Obsidian vault for knowledge
- **vault_read** — Read specific vault files
- **vault_save** — Save content to the vault
- **shell_execute** — Run whitelisted shell commands (git, ls, cat, grep, etc.)
- **journal_read** — Read Ivy's daily journal entries
- **linear_read** — Read issues from the Linear board
- **linear_search** — Search Linear issues

The following tools are NOT available in web chat (they require Discord where the approval flow is available):
- **armando_dispatch** — Dispatch the dev team (requires Kyle's approval)
- **request_restart** — Restart Ivy's service (requires Kyle's approval)

If Kyle asks for something that requires armando_dispatch or request_restart, tell him to use Discord where the approval flow is available.
"""

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


def encode_start_part() -> dict[str, Any]:
    """Create a stream start event."""
    return {"type": "start"}


def encode_text_start(text_id: str) -> dict[str, Any]:
    """Create a text-start event for a new text part."""
    return {"type": "text-start", "id": text_id}


def encode_text_delta(text_id: str, delta: str) -> dict[str, Any]:
    """Create a text-delta event with a token chunk."""
    return {"type": "text-delta", "id": text_id, "delta": delta}


def encode_text_end(text_id: str) -> dict[str, Any]:
    """Create a text-end event to close a text part."""
    return {"type": "text-end", "id": text_id}


def encode_finish_part(finish_reason: str) -> dict[str, Any]:
    """Create a finish event. No usage field — the strict schema rejects extras."""
    return {"type": "finish", "finishReason": finish_reason}


def encode_error_part(error: str) -> dict[str, Any]:
    """Create an error event with errorText (not error) per protocol v1."""
    return {"type": "error", "errorText": error}


def encode_sse_event(data: dict[str, Any]) -> str:
    """Encode a dict as an SSE data line.

    Returns a string in the format: ``data: {json}\\n\\n``
    """
    return f"data: {json.dumps(data)}\n\n"


async def stream_sse_events(
    tokens: AsyncIterator[str],
) -> AsyncIterator[str]:
    """Wrap an async token iterator into SSE-formatted events.

    Emits the full UI Message Stream Protocol v1 sequence:
        start -> text-start -> text-delta* -> text-end -> finish

    If the iterator raises, yields an error event instead of finish.
    """
    text_id = str(uuid.uuid4())
    yield encode_sse_event(encode_start_part())
    yield encode_sse_event(encode_text_start(text_id))
    try:
        async for token in tokens:
            yield encode_sse_event(encode_text_delta(text_id, token))
        yield encode_sse_event(encode_text_end(text_id))
        yield encode_sse_event(encode_finish_part("stop"))
    except Exception as exc:
        logger.error("Stream error: %s", exc)
        yield encode_sse_event(encode_error_part(str(exc)))


# ─── SSE status event helper ───────────────────────────────


def encode_status_event(tool_name: str, status: str) -> dict[str, Any]:
    """Create a status event for tool execution progress.

    These are optional SSE events emitted during tool execution.
    The frontend will ignore event types it doesn't recognize, so
    this is safe to add without client changes.
    """
    return {"type": "status", "tool": tool_name, "status": status}


# ─── Router factory ─────────────────────────────────────────


def create_chat_router(
    anthropic_client: object | None = None,
    soul: str = "",
    ollama_url: str = "http://localhost:11434",
    vault_path: Path | None = None,
    knowledge_manager: KnowledgeManager | None = None,
) -> APIRouter:
    """Create an APIRouter with the chat streaming endpoint.

    Args:
        anthropic_client: An ``anthropic.Anthropic`` client instance
            (or mock for testing). Used to call the LLM.
        soul: System prompt (Ivy's SOUL.md content) to prepend.
        ollama_url: Ollama base URL (reserved for future local routing).
        vault_path: Path to the Obsidian vault (required for tool execution).
        knowledge_manager: Optional KnowledgeManager for hybrid vault search.

    Returns:
        FastAPI APIRouter with ``POST /api/chat``.
    """
    router = APIRouter(prefix="/api/chat", tags=["chat"])

    # Build a ToolExecutor if vault_path is available
    tool_executor: ToolExecutor | None = None
    if vault_path is not None:
        tool_executor = ToolExecutor(
            vault_path=vault_path,
            knowledge_manager=knowledge_manager,
        )

    @router.post("")
    async def chat(
        body: ChatRequest,
        _: None = Depends(verify_api_key),
    ) -> StreamingResponse:
        """Stream Ivy's response as SSE events.

        Accepts a conversation history and streams the assistant's reply
        token-by-token using the UI Message Stream Protocol v1.

        If tools are available (vault_path configured), runs a server-side
        ReAct loop: Claude can call tools, results are fed back, and the
        final text response is streamed. The client sees only text events.
        """
        # Build the messages list for the Anthropic API
        messages = [{"role": m.role, "content": m.content} for m in body.messages]

        # Use the provided system prompt, with optional override from request.
        # Append CHAT_TOOL_DISCLAIMER so Ivy knows what tools are available
        # in the web chat interface (MOR-83, updated from MOR-82).
        base_prompt = body.system or soul or "You are Ivy, a helpful assistant."
        system_prompt = base_prompt + CHAT_TOOL_DISCLAIMER

        # System prompt with prompt caching
        system_with_cache = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        async def generate() -> AsyncIterator[str]:
            """Run the ReAct loop and stream the final response as SSE."""
            try:
                if anthropic_client is None:
                    raise RuntimeError("No LLM client configured")

                # If no tool executor, fall back to simple streaming (no tools)
                if tool_executor is None:
                    async with anthropic_client.messages.stream(
                        model=CLOUD_MODEL,
                        max_tokens=DEFAULT_MAX_TOKENS,
                        system=system_with_cache,
                        messages=messages,
                    ) as stream:
                        async for event in stream_sse_events(stream.text_stream):
                            yield event
                    return

                # ReAct loop: call model with tools, execute tools server-side
                react_messages = list(messages)

                for _round in range(MAX_TOOL_ROUNDS):
                    response = await anthropic_client.messages.create(
                        model=CLOUD_MODEL,
                        max_tokens=DEFAULT_MAX_TOKENS,
                        system=system_with_cache,
                        messages=react_messages,
                        tools=WEB_TOOL_DEFINITIONS,
                    )

                    # Check for tool_use blocks
                    tool_uses = [
                        b for b in response.content if b.type == "tool_use"
                    ]

                    if not tool_uses:
                        # No tool calls — stream the text response
                        text_parts = [
                            b.text for b in response.content
                            if b.type == "text"
                        ]
                        final_text = "\n".join(text_parts) if text_parts else ""

                        async def _text_iter(text: str) -> AsyncIterator[str]:
                            yield text

                        async for event in stream_sse_events(_text_iter(final_text)):
                            yield event
                        return

                    # Execute tools server-side
                    tool_results = []
                    for tool_use in tool_uses:
                        # NOTE: Status events removed — AI SDK v6 useChat
                        # does strict validation and rejects unknown event
                        # types. See CLAUDE.md rule about SSE protocol.
                        logger.info(
                            "Chat tool call: %s", tool_use.name,
                        )

                        # Check permission — refuse ASK-level tools in web chat
                        perm_key = tool_executor._permission_key(
                            tool_use.name, tool_use.input,
                        )
                        perm = check_permission(perm_key)

                        if perm == Permission.DENY:
                            result = (
                                f"Permission denied: {tool_use.name} is not allowed."
                            )
                        elif perm == Permission.ASK:
                            result = (
                                f"This action ({tool_use.name}) requires approval. "
                                f"Use Discord where the approval flow is available."
                            )
                        else:
                            result = await tool_executor.execute(
                                tool_use.name, tool_use.input,
                            )

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": result,
                        })

                    # Add assistant response + tool results to messages
                    react_messages.append({
                        "role": "assistant",
                        "content": response.content,
                    })
                    react_messages.append({
                        "role": "user",
                        "content": tool_results,
                    })

                # Exceeded max rounds — return a fallback message
                logger.warning(
                    "Chat ReAct loop exceeded %d rounds", MAX_TOOL_ROUNDS,
                )
                fallback = (
                    "I've been working through several steps but need to "
                    "stop here. Let me know if you'd like me to continue."
                )

                async def _fallback_iter() -> AsyncIterator[str]:
                    yield fallback

                async for event in stream_sse_events(_fallback_iter()):
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
