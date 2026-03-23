"""
trellis.core.loop — The ReAct Event Loop

This is the agent brain. It receives events from any sense (Discord, CLI,
file watcher, heartbeat), assembles context, calls the model with tool
definitions, executes tool calls, and returns the final response.

Architecture:
    LISTEN  -> Receive event from any input channel
    THINK   -> Assemble context, call model with tools
    ACT     -> Execute tool calls, send results back to model
    PERSIST -> Log to journal, update state, save conversations

The loop supports multi-step tool calling via the Anthropic API's native
tool use. Local models (Ollama) get the simple chat-only path — no tools.
"""

from __future__ import annotations

import logging
import shlex
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import anthropic

from trellis.hands.vault import (
    format_search_results,
    read_vault_file,
    save_to_vault,
    search_vault,
)
from trellis.memory.compactor import compact_history
from trellis.mind.context import auto_context
from trellis.mind.router import (
    CLOUD_INDICATOR,
    CLOUD_MODEL,
    COSTS,
    ModelRouter,
    RouteResult,
)
from trellis.mind.roles import load_role
from trellis.security.audit import log_action
from trellis.security.permissions import Permission, check_permission

if TYPE_CHECKING:
    from trellis.core.agent_state import AgentState
    from trellis.core.queue import ApprovalQueue
    from trellis.memory.knowledge import KnowledgeManager

logger = logging.getLogger(__name__)

# Maximum tool call rounds before forcing a text response
MAX_TOOL_ROUNDS = 8


# --- Event ---------------------------------------------------------

@dataclass
class Event:
    """An input event from any sense."""

    source: str  # "discord", "cli", "file_watcher", "heartbeat"
    content: str
    channel_id: str | int = ""
    channel_name: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)


# --- Tool Definitions (Anthropic format) ---------------------------

TOOL_DEFINITIONS = [
    {
        "name": "vault_search",
        "description": (
            "Search the Obsidian vault for knowledge relevant to a query. "
            "Returns matching file paths and excerpts. Use this to find "
            "information Kyle has stored about people, projects, or concepts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query — keywords or phrases to look for in vault files",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 5)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "vault_read",
        "description": (
            "Read the full contents of a specific file in the vault by its "
            "relative path. Use after vault_search to read a file in detail."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file within the vault (e.g., 'knowledge/project-alpha.md')",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "vault_save",
        "description": (
            "Save new content to the Obsidian vault. Use for capturing "
            "knowledge, notes, or items Kyle asks you to remember."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The content to save (Markdown format)",
                },
                "title": {
                    "type": "string",
                    "description": "Title for the saved file",
                },
                "category": {
                    "type": "string",
                    "enum": ["knowledge", "drop"],
                    "description": "Category: 'knowledge' for reference material, 'drop' for quick captures",
                },
            },
            "required": ["content", "title"],
        },
    },
    {
        "name": "shell_execute",
        "description": (
            "Execute a whitelisted shell command. Only safe, read-oriented "
            "commands are allowed: git, ls, cat, grep, find, wc, date, echo, "
            "head, tail, df, du, uptime, python (scripts only). "
            "No sudo, no rm, no package installs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "armando_dispatch",
        "description": (
            "Dispatch Armando (The Gardener) — the multi-agent dev team — to "
            "execute a development task. Armando is led by Thorn (PM) who "
            "dispatches Bloom (frontend) and Root (backend). This launches a "
            "Claude Code session with --agent thorn. WARNING: This runs for "
            "15-30 minutes and costs API budget. Only use when Kyle asks for "
            "development work."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The task description for Armando. Be specific about what to build, fix, or change.",
                },
                "project_dir": {
                    "type": "string",
                    "description": "Absolute path to the project directory (e.g., '/home/kyle/projects/trellis').",
                },
            },
            "required": ["message", "project_dir"],
        },
    },
    {
        "name": "journal_read",
        "description": (
            "Read recent entries from Ivy's daily journal. Useful for "
            "recalling what happened today or reviewing recent activity."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of recent entries to return (default 10)",
                },
                "date": {
                    "type": "string",
                    "description": "Specific date to read (YYYY-MM-DD format, default today)",
                },
            },
        },
    },
]


# --- Tool Executor -------------------------------------------------

class ToolExecutor:
    """Executes tools with permission checks and audit logging."""

    def __init__(
        self,
        vault_path: Path,
        agent_state: AgentState | None = None,
        knowledge_manager: KnowledgeManager | None = None,
        approval_queue: ApprovalQueue | None = None,
    ):
        self.vault_path = vault_path
        self.agent_state = agent_state
        self.knowledge_manager = knowledge_manager
        self.approval_queue = approval_queue

    async def execute(self, tool_name: str, tool_input: dict) -> str:
        """Execute a tool and return the result as a string."""
        # Check permissions
        perm_key = self._permission_key(tool_name, tool_input)
        perm = check_permission(perm_key)

        if perm == Permission.DENY:
            return f"Permission denied: {tool_name} is not allowed."

        if perm == Permission.ASK:
            return self._queue_approval(tool_name, tool_input)

        # Update agent state
        if self.agent_state:
            self.agent_state.set("acting", f"using {tool_name}")

        try:
            result = await self._run(tool_name, tool_input)
        except Exception as e:
            logger.error(f"Tool execution failed: {tool_name}: {e}", exc_info=True)
            result = f"Error executing {tool_name}: {e}"

        # Audit
        log_action(
            vault_path=self.vault_path,
            action_type=f"tool_{tool_name}",
            target=str(tool_input),
            input_summary=str(tool_input)[:200],
            output_summary=result[:200],
        )

        return result

    def _queue_approval(self, tool_name: str, tool_input: dict) -> str:
        """Queue an ASK-level action for Kyle's approval."""
        input_summary = str(tool_input)[:200]

        if self.approval_queue is not None:
            summary = f"{tool_name}: {input_summary[:60]}"
            body = (
                f"**Tool:** `{tool_name}`\n"
                f"**Input:** `{input_summary}`\n\n"
                f"Ivy attempted this action but it requires approval."
            )
            item_id = self.approval_queue.add_item(
                item_type="tool_approval",
                summary=summary,
                body=body,
                context=f"Tool: {tool_name}",
                source="ivy",
                tool_name=tool_name,
                tool_input=tool_input,
            )
            return (
                f"This action ({tool_name}) requires Kyle's approval. "
                f"I've added it to the queue (#{item_id})."
            )

        # No queue available — soft deny
        return (
            f"This action ({tool_name}) requires Kyle's approval. "
            f"I've noted it but cannot execute autonomously."
        )

    async def _run(self, tool_name: str, tool_input: dict) -> str:
        """Dispatch to the appropriate tool handler."""
        match tool_name:
            case "vault_search":
                return await self._vault_search(tool_input)
            case "vault_read":
                return self._vault_read(tool_input)
            case "vault_save":
                return self._vault_save(tool_input)
            case "shell_execute":
                return await self._shell_execute(tool_input)
            case "armando_dispatch":
                return await self._armando_dispatch(tool_input)
            case "journal_read":
                return self._journal_read(tool_input)
            case _:
                return f"Unknown tool: {tool_name}"

    def _permission_key(self, tool_name: str, tool_input: dict) -> str:
        """Map a tool call to a permission key."""
        match tool_name:
            case "vault_search" | "vault_read":
                return "vault_read"
            case "vault_save":
                return "vault_write"
            case "shell_execute":
                return "shell_whitelisted"
            case "armando_dispatch":
                return "armando_dispatch"
            case "journal_read":
                return "vault_read"
            case _:
                return tool_name

    async def _vault_search(self, tool_input: dict) -> str:
        """Search the vault using hybrid search when available."""
        query = tool_input.get("query", "")
        max_results = tool_input.get("max_results", 5)

        # Use hybrid search if knowledge manager is available
        if self.knowledge_manager is not None:
            try:
                results = await self.knowledge_manager.search(query, limit=max_results)
                if results:
                    return format_search_results(results)
            except Exception:
                logger.warning(
                    "Hybrid search failed in vault_search tool, falling back to keyword",
                    exc_info=True,
                )

        # Fallback: keyword-only search
        results = search_vault(self.vault_path, query, max_results=max_results)
        if not results:
            return f"No vault items found matching '{query}'."
        return format_search_results(results)

    def _vault_read(self, tool_input: dict) -> str:
        path = tool_input.get("path", "")
        content = read_vault_file(self.vault_path, path)
        if content is None:
            return f"File not found: {path}"
        # Truncate very large files
        if len(content) > 8000:
            return content[:8000] + "\n\n[... truncated — file is very large]"
        return content

    def _vault_save(self, tool_input: dict) -> str:
        content = tool_input.get("content", "")
        title = tool_input.get("title", "untitled")
        category = tool_input.get("category", "drop")
        saved_path = save_to_vault(
            vault_path=self.vault_path,
            content=content,
            title=title,
            category=category,
        )
        rel = saved_path.relative_to(self.vault_path)
        return f"Saved to vault: {rel}"

    async def _shell_execute(self, tool_input: dict) -> str:
        from trellis.hands.shell import execute_command

        command = tool_input.get("command", "")
        return await execute_command(command, cwd=str(self.vault_path))

    async def _armando_dispatch(self, tool_input: dict) -> str:
        """Dispatch Armando (The Gardener) to execute a development task."""
        from trellis.hands.shell import execute_command

        message = tool_input.get("message", "")
        project_dir = tool_input.get("project_dir", "")

        if not message:
            return "Error: message is required for Armando dispatch."
        if not project_dir:
            return "Error: project_dir is required."
        if not Path(project_dir).is_dir():
            return f"Error: project directory does not exist: {project_dir}"

        # Resolve full path to claude CLI — bare 'claude' fails under systemd
        claude_path = shutil.which("claude")
        if claude_path is None:
            fallback = Path("/home/kyle/.local/bin/claude")
            if fallback.is_file():
                claude_path = str(fallback)
            else:
                return "Error: claude CLI not found. Install it or check PATH."

        cmd = (
            f"{claude_path} --dangerously-skip-permissions --agent thorn "
            f"-p {shlex.quote(message)} "
            f"--max-budget-usd 5 --no-session-persistence"
        )

        result = await execute_command(cmd, cwd=project_dir, timeout=1800)
        return result

    def _journal_read(self, tool_input: dict) -> str:
        limit = tool_input.get("limit", 10)
        date_str = tool_input.get("date", datetime.now().strftime("%Y-%m-%d"))
        journal_path = self.vault_path / "_ivy" / "journal" / f"{date_str}.md"

        if not journal_path.exists():
            return f"No journal entries for {date_str}."

        try:
            content = journal_path.read_text(encoding="utf-8")
        except OSError as e:
            return f"Failed to read journal: {e}"

        # Parse entries and return most recent
        entries = []
        current = []
        for line in content.splitlines():
            if line.startswith("## ") and current:
                entries.append("\n".join(current))
                current = [line]
            else:
                current.append(line)
        if current:
            entries.append("\n".join(current))

        # Return last N entries
        recent = entries[-limit:] if limit < len(entries) else entries
        return "\n---\n".join(recent) if recent else f"Journal for {date_str} is empty."


# --- Agent Brain ---------------------------------------------------

class AgentBrain:
    """The ReAct loop — Ivy's thinking engine.

    Receives events, assembles context, calls the model with tools,
    executes tool calls, and returns the final response.
    """

    def __init__(
        self,
        anthropic_client: anthropic.Anthropic,
        router: ModelRouter,
        vault_path: Path,
        system_prompt: str,
        local_system_prompt: str = "",
        agent_state: AgentState | None = None,
        role_name: str = "_default",
        knowledge_manager: KnowledgeManager | None = None,
        approval_queue: ApprovalQueue | None = None,
    ):
        self.anthropic_client = anthropic_client
        self.router = router
        self.vault_path = vault_path
        self.system_prompt = system_prompt
        self.local_system_prompt = local_system_prompt or system_prompt
        self.agent_state = agent_state
        self.knowledge_manager = knowledge_manager
        self.approval_queue = approval_queue
        self.tool_executor = ToolExecutor(
            vault_path,
            agent_state,
            knowledge_manager=knowledge_manager,
            approval_queue=approval_queue,
        )
        self.set_role(role_name)

    def set_role(self, role_name: str):
        """Load and activate a role configuration."""
        try:
            self._role = load_role(role_name)
        except Exception:
            self._role = {"name": "default", "tone": "professional_warm", "autonomy_level": "medium"}
        self._role_name = role_name
        logger.info(f"Role set: {self._role.get('name', role_name)}")

    def _build_system_prompt(self) -> str:
        """Build the full system prompt with role context."""
        prompt = self.system_prompt

        # Add role context if not default
        role_name = self._role.get("name", "default")
        if role_name != "default":
            tone = self._role.get("tone", "professional_warm")
            autonomy = self._role.get("autonomy_level", "medium")
            description = self._role.get("description", "")
            prompt += (
                f"\n\n[Active Role: {role_name}]\n"
                f"Tone: {tone}\n"
                f"Autonomy: {autonomy}\n"
                f"{description}\n"
            )

        return prompt

    async def process(
        self,
        event: Event,
        history: list[dict],
    ) -> RouteResult:
        """Process an event through the full ReAct cycle.

        Returns a RouteResult with the final text response.
        """
        message = event.content
        classify_from = message

        # Auto-context: search vault for relevant knowledge (hybrid when available)
        vault_context = await auto_context(
            self.vault_path, message, knowledge_manager=self.knowledge_manager
        )

        # Build the effective message with context
        context_parts = []
        if event.channel_name:
            context_parts.append(
                f"[You are chatting with Kyle in {event.source} "
                f"channel #{event.channel_name}. "
                f"Use this context if relevant to the conversation.]"
            )
        if vault_context:
            context_parts.append(
                "[Vault search results for context — "
                "use these to inform your answer]\n" + vault_context
            )

        effective_message = message
        if context_parts:
            effective_message = "\n\n".join(context_parts) + "\n\n" + message

        # Compact history if it's getting long
        compacted_history = compact_history(history)

        # Route classification
        route = self.router.classify(classify_from)

        # Override routing if force_cloud requested (post-tool follow-up)
        if event.metadata.get("force_cloud") and route not in ("force_local", "force_cloud"):
            route = "cloud"

        is_local = route in ("local", "force_local")

        if is_local:
            # Local models: simple chat, no tools
            try:
                return await self.router.route(
                    message=effective_message,
                    system_prompt=self._build_system_prompt(),
                    history=compacted_history,
                    classify_from=classify_from,
                    local_system_prompt=self.local_system_prompt,
                )
            except Exception:
                if route == "force_local":
                    raise
                logger.warning("Local model failed, falling through to cloud with tools")

        # Light cloud (Haiku): chat without tools — fast and cheap
        if route == "light":
            if self.agent_state:
                self.agent_state.set("thinking", "processing message")
            return await self.router.route(
                message=effective_message,
                system_prompt=self._build_system_prompt(),
                history=compacted_history,
                classify_from=classify_from,
            )

        # Full cloud (Sonnet): ReAct loop with tool calling
        if self.agent_state:
            self.agent_state.set("thinking", "processing message")

        return await self._react_loop(effective_message, compacted_history)

    async def _react_loop(
        self,
        message: str,
        history: list[dict],
    ) -> RouteResult:
        """Run the ReAct loop with tool calling via the Anthropic API."""
        messages = list(history)
        messages.append({"role": "user", "content": message})

        total_cost = 0.0
        rounds = 0
        any_tools_used = False

        while rounds < MAX_TOOL_ROUNDS:
            rounds += 1

            # Call Claude with tools + prompt caching
            system_with_cache = [
                {
                    "type": "text",
                    "text": self._build_system_prompt(),
                    "cache_control": {"type": "ephemeral"},
                }
            ]

            response = self.anthropic_client.messages.create(
                model=CLOUD_MODEL,
                max_tokens=2048,
                system=system_with_cache,
                messages=messages,
                tools=TOOL_DEFINITIONS,
            )

            # Calculate cost with cache awareness
            usage = response.usage
            input_tokens = usage.input_tokens
            output_tokens = usage.output_tokens
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0

            costs = COSTS[CLOUD_MODEL]
            regular_input = input_tokens - cache_read
            cost = (
                (regular_input / 1_000_000 * costs["input"])
                + (cache_read / 1_000_000 * costs["cache_read"])
                + (cache_creation / 1_000_000 * costs["input"] * 1.25)
                + (output_tokens / 1_000_000 * costs["output"])
            )
            total_cost += cost
            self.router._session_cost += cost

            # Check if we need to execute tools
            tool_uses = [b for b in response.content if b.type == "tool_use"]

            if not tool_uses:
                # No tool calls — extract text and return
                text_parts = [b.text for b in response.content if b.type == "text"]
                final_text = "\n".join(text_parts) if text_parts else ""

                logger.info(
                    f"ReAct complete — {rounds} round(s), "
                    f"${total_cost:.4f} total cost"
                )

                return RouteResult(
                    response=final_text,
                    model_used=CLOUD_MODEL,
                    is_local=False,
                    cost_usd=total_cost,
                    indicator=CLOUD_INDICATOR,
                    used_tools=any_tools_used,
                )

            # Execute tool calls
            any_tools_used = True
            # Add the assistant's response to messages
            messages.append({"role": "assistant", "content": response.content})

            # Build tool results
            tool_results = []
            for tool_use in tool_uses:
                logger.info(f"Tool call: {tool_use.name}({tool_use.input})")
                result = await self.tool_executor.execute(
                    tool_use.name, tool_use.input
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result,
                })

            messages.append({"role": "user", "content": tool_results})

        # Exceeded max rounds — return what we have
        logger.warning(f"ReAct loop exceeded {MAX_TOOL_ROUNDS} rounds")
        return RouteResult(
            response="I've been working through several steps but need to stop here. Let me know if you'd like me to continue.",
            model_used=CLOUD_MODEL,
            is_local=False,
            cost_usd=total_cost,
            indicator=CLOUD_INDICATOR,
            used_tools=any_tools_used,
        )
