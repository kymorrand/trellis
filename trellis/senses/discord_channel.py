"""
trellis.senses.discord_channel — Discord Communication Channel

Ivy's primary communication interface. Listens for messages in the
private "Greenhouse" Discord server and sends responses back.

Features:
    - Hybrid model routing (local Ollama / cloud Claude)
    - Journal logging of every interaction
    - Vault search and save operations
    - Per-channel conversation history
    - /status command for on-demand status reports
    - Heartbeat integration for background tasks

Security: Only processes messages from Kyle's Discord user ID.
"""

import asyncio
import json
import logging
import re
from collections import defaultdict
from pathlib import Path

import anthropic
import discord
import httpx

from trellis.hands.vault import (
    format_search_results,
    save_to_vault,
    search_vault,
)
from trellis.memory.journal import log_entry
from trellis.mind.context import auto_context
from trellis.mind.router import ModelRouter, RouteResult
from trellis.mind.soul import load_soul, load_soul_local
from trellis.security.audit import log_action

logger = logging.getLogger(__name__)

# Max conversation history per channel (message pairs)
MAX_HISTORY = 50

# Patterns that trigger vault save
SAVE_PATTERNS = re.compile(
    r"^(remember\s+this|save\s+this|note\s+this|capture\s+this|store\s+this|"
    r"remember\s+that|save\s+that|note\s+that)[:\s.!,—–-]*",
    re.IGNORECASE,
)

# Patterns that trigger vault search
SEARCH_TRIGGERS = re.compile(
    r"(what\s+do\s+(i|we|you)\s+have\s+(on|about)|"
    r"search\s+(the\s+)?vault|check\s+(the\s+)?vault|"
    r"find\s+in\s+(the\s+)?vault|look\s+up|"
    r"what\s+do\s+(i|we)\s+know\s+about|"
    r"what('s|\s+is)\s+in\s+(the\s+)?vault\s+about)",
    re.IGNORECASE,
)


class IvyDiscordBot(discord.Client):
    """Discord bot that routes messages through hybrid model routing."""

    def __init__(
        self,
        anthropic_key: str,
        guild_id: str,
        allowed_user_id: str,
        vault_path: Path,
        ollama_url: str = "http://localhost:11434",
        agents_dir: str = "agents",
    ):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)

        self.anthropic_client = anthropic.Anthropic(api_key=anthropic_key)
        self.guild_id = int(guild_id)
        self.allowed_user_id = int(allowed_user_id)
        self.vault_path = vault_path
        self.ollama_url = ollama_url

        # Load Ivy's soul — full for Claude, condensed for local models
        self.system_prompt = load_soul(agents_dir=agents_dir)
        if not self.system_prompt:
            raise ValueError("Failed to load SOUL.md — cannot start without personality")
        self.local_system_prompt = load_soul_local(agents_dir=agents_dir)

        # Model router
        self.router = ModelRouter(
            anthropic_client=self.anthropic_client,
            ollama_url=self.ollama_url,
        )

        # Per-channel conversation history: {channel_id: [{"role": ..., "content": ...}]}
        self.conversations: dict[int, list[dict]] = defaultdict(list)
        self._conversations_path = vault_path / "_ivy" / "state" / "conversations.json"
        self._load_conversations()

        # Heartbeat scheduler (set after construction via set_heartbeat)
        self.heartbeat = None
        # Agent state tracker (set after construction or via constructor)
        self.agent_state = None
        # Primary channel for posting briefs (set on_ready)
        self._primary_channel = None
        # Queued startup messages: list of (channel_name, message) to send on_ready
        self._startup_messages: list[tuple[str, str]] = []

    def set_heartbeat(self, heartbeat):
        """Attach the heartbeat scheduler to the bot."""
        self.heartbeat = heartbeat

    def queue_startup_message(self, channel_name: str, message: str):
        """Queue a message to be sent to a specific channel once the bot is ready."""
        self._startup_messages.append((channel_name, message))

    def _load_conversations(self):
        """Load persisted conversation history from disk."""
        if not self._conversations_path.exists():
            return
        try:
            data = json.loads(self._conversations_path.read_text(encoding="utf-8"))
            for channel_id_str, history in data.items():
                self.conversations[int(channel_id_str)] = history
            logger.info(f"Loaded conversations for {len(data)} channels")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load conversations: {e}")

    def _save_conversations(self):
        """Persist conversation history to disk."""
        try:
            self._conversations_path.parent.mkdir(parents=True, exist_ok=True)
            data = {str(k): v for k, v in self.conversations.items() if v}
            self._conversations_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except OSError as e:
            logger.warning(f"Failed to save conversations: {e}")

    async def post_to_discord(self, message: str):
        """Post a message to the primary channel (used by heartbeat for briefs/alerts)."""
        if self._primary_channel:
            for chunk in _split_message(message):
                await self._primary_channel.send(chunk)

    async def post_to_channel(self, channel_name: str, message: str):
        """Post a message to a specific channel by name."""
        guild = self.get_guild(self.guild_id)
        if not guild:
            logger.warning(f"Guild {self.guild_id} not found — cannot post to #{channel_name}")
            return
        for channel in guild.text_channels:
            if channel.name == channel_name and channel.permissions_for(guild.me).send_messages:
                for chunk in _split_message(message):
                    await channel.send(chunk)
                return
        logger.warning(f"Channel #{channel_name} not found or not writable")

    async def on_ready(self):
        logger.info(f"Ivy connected as {self.user} (id: {self.user.id})")

        guild = self.get_guild(self.guild_id)
        if guild:
            logger.info(f"Found guild: {guild.name}")
            # Use the first text channel as primary posting channel
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    self._primary_channel = channel
                    logger.info(f"Primary channel: #{channel.name}")
                    break
        else:
            logger.warning(f"Guild {self.guild_id} not found — check IVY_DISCORD_GUILD_ID")

        log_entry(self.vault_path, "SYSTEM", "Ivy Discord bot connected", f"Guild: {self.guild_id}")

        # Flush any queued startup messages
        for ch_name, msg in self._startup_messages:
            await self.post_to_channel(ch_name, msg)
        self._startup_messages.clear()

    async def on_message(self, message: discord.Message):
        # Never respond to ourselves
        if message.author.id == self.user.id:
            return

        # Security: only process messages from Kyle
        if message.author.id != self.allowed_user_id:
            logger.debug(f"Ignoring message from unauthorized user {message.author.id}")
            return

        # Only respond in the configured guild
        if message.guild and message.guild.id != self.guild_id:
            return

        # Ignore empty messages
        content = message.content.strip()
        if not content:
            return

        logger.info(f"Message from Kyle in #{message.channel.name}: {content[:80]}")

        # Journal: log Kyle's message
        log_entry(
            self.vault_path,
            "MESSAGE_IN",
            f"Kyle in #{message.channel.name}",
            content,
        )

        # Special commands
        if content.lower() == "!clear":
            self.conversations[message.channel.id] = []
            self._save_conversations()
            await message.reply("Conversation cleared. Fresh start.")
            log_entry(self.vault_path, "COMMAND", f"Cleared history in #{message.channel.name}")
            return

        # /status command — immediate status report
        if content.lower().strip() == "/status":
            async with message.channel.typing():
                if self.heartbeat:
                    report = await self.heartbeat.get_status_report()
                else:
                    report = "🌱 Heartbeat not running — status unavailable."
            await message.reply(report)
            log_entry(self.vault_path, "COMMAND", "Status report requested")
            return

        # Check for vault save requests
        if SAVE_PATTERNS.match(content):
            if self.agent_state:
                self.agent_state.set("acting", "saving to vault")
            async with message.channel.typing():
                reply = await self._handle_vault_save(message.channel.id, content)
            for chunk in _split_message(reply):
                await message.reply(chunk)
            log_entry(self.vault_path, "VAULT_SAVE", "Save request from Kyle", content)
            if self.agent_state:
                self.agent_state.set("idle")
            return

        # Build conversation and get response
        if self.agent_state:
            self.agent_state.set("thinking", "processing message")
        async with message.channel.typing():
            try:
                # Auto-context: search vault for relevant knowledge on every message
                vault_context = auto_context(self.vault_path, content)

                # Explicit vault search triggers get a deeper, targeted search
                if SEARCH_TRIGGERS.search(content):
                    explicit_context = self._search_vault_for_context(content)
                    if explicit_context:
                        vault_context = explicit_context

                async with asyncio.timeout(90):
                    result = await self._get_response(
                        message.channel.id,
                        content,
                        vault_context,
                        channel_name=getattr(message.channel, "name", None) or "direct-message",
                    )
            except TimeoutError:
                logger.error("Model call timed out (90s)")
                await message.reply(
                    "Timed out waiting for a response — the model might be overloaded. "
                    "Try again, or use `/local` to force local routing."
                )
                log_entry(self.vault_path, "ERROR", "Model call timed out (90s)")
                if self.agent_state:
                    self.agent_state.set("idle")
                return
            except httpx.ConnectError as e:
                logger.error(f"Connection error: {e}")
                await message.reply("Can't reach the model right now — Ollama may be down.")
                log_entry(self.vault_path, "ERROR", f"Connection error: {e}")
                if self.agent_state:
                    self.agent_state.set("idle")
                return
            except Exception as e:
                logger.error(f"Model error: {e}", exc_info=True)
                error_type = type(e).__name__
                await message.reply(f"Hit an error ({error_type}) — check the logs.")
                log_entry(self.vault_path, "ERROR", f"Model error ({error_type}): {e}")
                if self.agent_state:
                    self.agent_state.set("idle")
                return

        # Append model indicator
        reply_with_indicator = f"{result.response}\n\n-# {result.indicator}"

        # Discord has a 2000 char limit — split if needed
        for chunk in _split_message(reply_with_indicator):
            await message.reply(chunk)

        # Journal: log Ivy's response
        cost_note = f" (${result.cost_usd:.4f})" if result.cost_usd > 0 else ""
        log_entry(
            self.vault_path,
            "MESSAGE_OUT",
            f"Ivy → #{message.channel.name} via {result.model_used}{cost_note}",
            result.response[:500],
        )

        # Audit
        log_action(
            vault_path=self.vault_path,
            action_type="discord_reply",
            target=f"#{message.channel.name}",
            input_summary=content,
            output_summary=result.response,
            model_used=result.model_used,
            cost_usd=result.cost_usd,
        )

        # Return to idle
        if self.agent_state:
            self.agent_state.set("idle")

    async def _get_response(
        self,
        channel_id: int,
        user_message: str,
        vault_context: str = "",
        channel_name: str = "",
    ) -> RouteResult:
        """Route message to the appropriate model and return response."""
        history = self.conversations[channel_id]

        # Situational context so the model knows where the conversation is
        context_prefix = ""
        if channel_name:
            context_prefix = (
                f"[You are chatting with Kyle in Discord channel #{channel_name}. "
                f"Use this context if relevant to the conversation.]\n\n"
            )

        # Build the effective message — include situational + vault context
        effective_message = context_prefix + user_message
        if vault_context:
            effective_message += (
                "\n\n[Vault search results for context — use these to inform your answer]\n"
                + vault_context
            )

        # Route to appropriate model (classify on original, send enriched)
        result = await self.router.route(
            message=effective_message,
            system_prompt=self.system_prompt,
            history=history,
            classify_from=user_message,
            local_system_prompt=self.local_system_prompt,
        )

        # Update conversation history with the original message (not vault-enriched)
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": result.response})

        # Trim history if too long
        if len(history) > MAX_HISTORY * 2:
            history[:] = history[-(MAX_HISTORY * 2):]

        # Persist to disk so history survives restarts
        self._save_conversations()

        return result

    async def _handle_vault_save(self, channel_id: int, content: str) -> str:
        """Handle a vault save request from Kyle."""
        # Strip the trigger phrase to get the actual content to save
        # e.g., "remember this: X" → "X"
        # e.g., "save this — some note" → "some note"
        cleaned = SAVE_PATTERNS.sub("", content).strip()
        cleaned = cleaned.lstrip(":—–-").strip()

        if not cleaned:
            return "What would you like me to save? Give me the content after 'remember this'."

        # Determine category — if it looks like reference material, use knowledge
        knowledge_signals = re.compile(
            r"(definition|reference|how\s+to|process|checklist|framework|principle)",
            re.IGNORECASE,
        )
        category = "knowledge" if knowledge_signals.search(cleaned) else "drop"

        # Generate a title from the first line or first few words
        first_line = cleaned.split("\n")[0]
        title = first_line[:60] if len(first_line) > 60 else first_line

        saved_path = save_to_vault(
            vault_path=self.vault_path,
            content=cleaned,
            title=title,
            category=category,
        )

        rel_path = saved_path.relative_to(self.vault_path)
        location = "knowledge/" if category == "knowledge" else "_ivy/inbox/drops/"
        return f"Saved to **{rel_path}**\n\nFiled in `{location}` — I can move it if you'd prefer somewhere else."

    def _search_vault_for_context(self, message: str) -> str:
        """Search the vault for content relevant to the message."""
        # Extract the likely search topic from the message
        # Remove common question words to get the core topic
        topic = re.sub(
            r"(what\s+do\s+(i|we|you)\s+(have|know)\s+(on|about)\s*|"
            r"search\s+(the\s+)?vault\s+(for\s+)?|"
            r"check\s+(the\s+)?vault\s+(for\s+)?|"
            r"find\s+in\s+(the\s+)?vault\s*|"
            r"look\s+up\s*|"
            r"what('s|\s+is)\s+in\s+(the\s+)?vault\s+about\s*)",
            "",
            message,
            flags=re.IGNORECASE,
        ).strip().rstrip("?")

        if not topic:
            topic = message  # Fall back to full message

        results = search_vault(self.vault_path, topic)
        if not results:
            return ""

        return format_search_results(results)


def _split_message(text: str, limit: int = 2000) -> list[str]:
    """Split a message into chunks that fit Discord's character limit."""
    if len(text) <= limit:
        return [text]

    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        # Try to split at a newline
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            # Fall back to splitting at a space
            split_at = text.rfind(" ", 0, limit)
        if split_at == -1:
            # Hard split
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


def create_bot(config: dict) -> IvyDiscordBot:
    """Create an IvyDiscordBot from a config dict (from core.config.load_config)."""
    required = ["anthropic_key", "discord_guild_id", "discord_allowed_user"]
    for key in required:
        if not config.get(key):
            raise ValueError(f"Missing required config: {key}")

    return IvyDiscordBot(
        anthropic_key=config["anthropic_key"],
        guild_id=config["discord_guild_id"],
        allowed_user_id=config["discord_allowed_user"],
        vault_path=config["vault_path"],
        ollama_url=config.get("ollama_url", "http://localhost:11434"),
    )
