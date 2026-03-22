"""
trellis.mind.router — Model Routing

Routes inference requests to local (Ollama) or cloud (Anthropic) models
based on task complexity, user overrides, and budget.

Routing logic:
    /local prefix   → Force local (Ollama qwen3:14b)
    /claude prefix  → Force cloud (Claude Sonnet via Anthropic)
    Simple messages  → Local (under 50 words, greetings, quick questions)
    Complex messages → Cloud (long questions, reasoning, writing, analysis)
"""

import logging
import re
from dataclasses import dataclass, field

import anthropic
import httpx

logger = logging.getLogger(__name__)

CLOUD_MODEL = "claude-sonnet-4-20250514"
LOCAL_MODEL = "qwen3:14b"
LOCAL_INDICATOR = "\U0001f33f"  # 🌿
CLOUD_INDICATOR = "\u2601\ufe0f"  # ☁️

# Cost estimates for Claude Sonnet (per 1M tokens)
COST_INPUT_PER_M = 3.00
COST_OUTPUT_PER_M = 15.00

# Keywords that signal complexity
COMPLEX_KEYWORDS = re.compile(
    r"\b(draft|write|analyze|analysis|strategy|strategize|explain|compare|review|"
    r"summarize|plan|design|architect|refactor|debug|research|evaluate|assess|"
    r"critique|outline|brainstorm|pros\s+and\s+cons)\b",
    re.IGNORECASE,
)


@dataclass
class RouteResult:
    """Result of routing a message to a model."""

    response: str
    model_used: str
    is_local: bool
    cost_usd: float = 0.0
    indicator: str = ""


@dataclass
class ModelRouter:
    """Routes messages to local or cloud models."""

    anthropic_client: anthropic.Anthropic
    ollama_url: str = "http://localhost:11434"
    _session_cost: float = field(default=0.0, init=False)

    def classify(self, message: str) -> str:
        """Classify a message as 'local' or 'cloud'.

        Returns 'force_local', 'force_cloud', 'local', or 'cloud'.
        """
        stripped = message.strip()

        # Explicit overrides
        if stripped.lower().startswith("/local"):
            return "force_local"
        if stripped.lower().startswith("/claude"):
            return "force_cloud"

        # Complexity heuristics
        word_count = len(stripped.split())

        # Complex keywords → cloud
        if COMPLEX_KEYWORDS.search(stripped):
            return "cloud"

        # Long messages → cloud
        if word_count > 50:
            return "cloud"

        # Multi-paragraph → cloud
        if stripped.count("\n\n") >= 2:
            return "cloud"

        # Everything else → local
        return "local"

    def strip_prefix(self, message: str) -> str:
        """Remove /local or /claude prefix from message."""
        stripped = message.strip()
        if stripped.lower().startswith("/local"):
            return stripped[6:].lstrip()
        if stripped.lower().startswith("/claude"):
            return stripped[7:].lstrip()
        return stripped

    async def route(
        self,
        message: str,
        system_prompt: str,
        history: list[dict],
        classify_from: str | None = None,
        local_system_prompt: str | None = None,
    ) -> RouteResult:
        """Route a message to the appropriate model and return the response.

        Args:
            message: The full message to send to the model.
            system_prompt: System prompt for cloud models.
            history: Conversation history.
            classify_from: If provided, use this string (instead of message)
                for routing classification. Useful when `message` has been
                enriched with vault context.
            local_system_prompt: Condensed system prompt for local models.
                Falls back to system_prompt if not provided.
        """
        route = self.classify(classify_from or message)
        clean_message = self.strip_prefix(message)
        is_local = route in ("local", "force_local")

        if is_local:
            try:
                prompt = local_system_prompt or system_prompt
                response = await self._call_ollama(clean_message, prompt, history)
                return RouteResult(
                    response=response,
                    model_used=LOCAL_MODEL,
                    is_local=True,
                    cost_usd=0.0,
                    indicator=LOCAL_INDICATOR,
                )
            except Exception as e:
                # If forced local, don't fall back
                if route == "force_local":
                    raise
                logger.warning(f"Local model failed, falling back to cloud: {e}")
                # Fall through to cloud

        return await self._call_cloud(clean_message, system_prompt, history)

    async def _call_ollama(
        self,
        message: str,
        system_prompt: str,
        history: list[dict],
    ) -> str:
        """Call Ollama local model."""
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": message})

        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                f"{self.ollama_url}/api/chat",
                json={
                    "model": LOCAL_MODEL,
                    "messages": messages,
                    "stream": False,
                    "options": {"num_predict": 1024},
                },
            )
            resp.raise_for_status()
            data = resp.json()

        content = data.get("message", {}).get("content", "")
        if not content:
            raise ValueError("Empty response from Ollama")

        logger.info(f"Ollama ({LOCAL_MODEL}) responded ({len(content)} chars)")
        return content

    async def _call_cloud(
        self,
        message: str,
        system_prompt: str,
        history: list[dict],
    ) -> RouteResult:
        """Call Claude via Anthropic API."""
        messages = list(history)
        messages.append({"role": "user", "content": message})

        response = self.anthropic_client.messages.create(
            model=CLOUD_MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )

        if not response.content:
            raise ValueError("Empty response from Claude API")
        assistant_reply = response.content[0].text

        # Calculate cost
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = (input_tokens / 1_000_000 * COST_INPUT_PER_M) + (
            output_tokens / 1_000_000 * COST_OUTPUT_PER_M
        )
        self._session_cost += cost

        logger.info(
            f"Claude ({CLOUD_MODEL}) responded ({len(assistant_reply)} chars, "
            f"${cost:.4f}, session total: ${self._session_cost:.4f})"
        )

        return RouteResult(
            response=assistant_reply,
            model_used=CLOUD_MODEL,
            is_local=False,
            cost_usd=cost,
            indicator=CLOUD_INDICATOR,
        )

    @property
    def session_cost(self) -> float:
        return self._session_cost
