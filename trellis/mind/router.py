"""
trellis.mind.router — Model Routing

Routes inference requests to local (Ollama), light cloud (Haiku), or
full cloud (Sonnet) based on task complexity, user overrides, and budget.

Three-tier routing:
    /local prefix    → Force local (Ollama qwen3.5:9b)
    /claude prefix   → Force cloud (Claude Sonnet via Anthropic)
    Simple messages  → Local (greetings, short questions, casual chat)
    Medium messages  → Light cloud (Haiku — conversational, moderate complexity)
    Complex messages → Full cloud (Sonnet — reasoning, analysis, long-form writing)

Prompt caching:
    System prompts are sent with cache_control to get 90% input cost
    savings on repeated calls. The Anthropic API caches prompts for 5 min.
"""

import logging
import re
from dataclasses import dataclass, field

import anthropic
import httpx

logger = logging.getLogger(__name__)

# ─── Models ───────────────────────────────────────────────

CLOUD_MODEL = "claude-sonnet-4-20250514"
LIGHT_MODEL = "claude-haiku-4-5-20251001"
LOCAL_MODEL = "qwen3.5:9b"  # Dense model — local chat quality
LOCAL_MODEL_FAST = "qwen3.5:35b-a3b"  # MoE model — tick scheduler / fast eval (~112 tok/s)

LOCAL_INDICATOR = "\U0001f33f"  # 🌿
LIGHT_INDICATOR = "\u2601\ufe0f"  # ☁️ (light cloud — same icon, cheaper)
CLOUD_INDICATOR = "\u2601\ufe0f\U0001f4ab"  # ☁️💫 (full cloud)

# ─── Cost estimates (per 1M tokens) ───────────────────────

COSTS = {
    CLOUD_MODEL: {"input": 3.00, "output": 15.00, "cache_read": 0.30},
    LIGHT_MODEL: {"input": 0.80, "output": 4.00, "cache_read": 0.08},
}

# ─── Routing heuristics ──────────────────────────────────

# Keywords that demand Sonnet-level reasoning
SONNET_KEYWORDS = re.compile(
    r"\b(architect|refactor|debug|strategy|strategize|"
    r"pros\s+and\s+cons|trade.?offs?|compare\s+and\s+contrast|"
    r"code\s+review|security\s+audit|design\s+system|"
    r"armando|dispatch|launch\s+armando|"
    r"search\s+the\s+vault|save\s+to\s+vault|"
    r"run\s+command|execute|shell|"
    r"approve|approved|deny|denied|confirm|confirmed)\b",
    re.IGNORECASE,
)

# Keywords that are fine for Haiku (conversational complexity)
HAIKU_KEYWORDS = re.compile(
    r"\b(draft|write|explain|summarize|plan|outline|brainstorm|"
    r"analyze|analysis|review|evaluate|assess|critique|research|describe)\b",
    re.IGNORECASE,
)

# Signals that a message is simple enough for local
LOCAL_SIGNALS = re.compile(
    r"^(hey|hi|hello|thanks|thank you|ok|okay|sure|yes|no|yeah|yep|nah|"
    r"good morning|good night|gm|gn|sounds good|got it|nice|cool|"
    r"how are you|what's up|sup|yo)\s*[.!?]?$",
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
    used_tools: bool = False


@dataclass
class ModelRouter:
    """Routes messages to local, light cloud, or full cloud models."""

    anthropic_client: anthropic.Anthropic
    ollama_url: str = "http://localhost:11434"
    _session_cost: float = field(default=0.0, init=False)

    def classify(self, message: str) -> str:
        """Classify a message into a routing tier.

        Returns: 'force_local', 'force_cloud', 'local', 'light', or 'cloud'.
        """
        stripped = message.strip()

        # Explicit overrides
        if stripped.lower().startswith("/local"):
            return "force_local"
        if stripped.lower().startswith("/claude"):
            return "force_cloud"

        word_count = len(stripped.split())

        # Greeting patterns → always local (even if they contain keywords)
        if LOCAL_SIGNALS.match(stripped):
            return "local"

        # Sonnet-level keywords → full cloud (check before word count)
        if SONNET_KEYWORDS.search(stripped):
            return "cloud"

        # Haiku-level keywords → light cloud (check before word count)
        if HAIKU_KEYWORDS.search(stripped):
            return "light"

        # Very long or multi-paragraph → full cloud
        if word_count > 100 or stripped.count("\n\n") >= 3:
            return "cloud"

        # Moderate length → Haiku
        if word_count > 30:
            return "light"

        # Multi-paragraph but short → Haiku
        if stripped.count("\n\n") >= 1:
            return "light"

        # Default: local for short, simple messages
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
        """Route a message to the appropriate model and return the response."""
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
                if route == "force_local":
                    raise
                logger.warning(f"Local model failed, falling back to light cloud: {e}")
                # Fall through to light cloud

        # Light cloud (Haiku) for medium complexity
        if route in ("local", "light"):
            try:
                return await self._call_cloud(
                    clean_message, system_prompt, history, model=LIGHT_MODEL
                )
            except Exception as e:
                logger.warning(f"Haiku failed, falling back to Sonnet: {e}")

        # Full cloud (Sonnet) for complex tasks or as final fallback
        return await self._call_cloud(
            clean_message, system_prompt, history, model=CLOUD_MODEL
        )

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
        model: str = CLOUD_MODEL,
    ) -> RouteResult:
        """Call Claude via Anthropic API with prompt caching."""
        messages = list(history)
        messages.append({"role": "user", "content": message})

        # Use prompt caching on the system prompt — this is the big win.
        # The system prompt (SOUL.md + role context) is ~2K tokens and
        # identical across calls. Cache read costs 10% of input price.
        system_with_cache = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        costs = COSTS.get(model, COSTS[CLOUD_MODEL])
        indicator = LIGHT_INDICATOR if model == LIGHT_MODEL else CLOUD_INDICATOR

        response = self.anthropic_client.messages.create(
            model=model,
            max_tokens=1024,
            system=system_with_cache,
            messages=messages,
        )

        if not response.content:
            raise ValueError(f"Empty response from {model}")
        assistant_reply = response.content[0].text

        # Calculate cost with cache awareness
        usage = response.usage
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0

        # Non-cached input tokens = total - cache_read - cache_creation
        regular_input = input_tokens - cache_read
        cost = (
            (regular_input / 1_000_000 * costs["input"])
            + (cache_read / 1_000_000 * costs["cache_read"])
            + (cache_creation / 1_000_000 * costs["input"] * 1.25)  # cache write = 125% of input
            + (output_tokens / 1_000_000 * costs["output"])
        )
        self._session_cost += cost

        cache_info = ""
        if cache_read > 0:
            savings = cache_read / 1_000_000 * (costs["input"] - costs["cache_read"])
            cache_info = f", cache saved ${savings:.4f}"

        logger.info(
            f"{model} responded ({len(assistant_reply)} chars, "
            f"${cost:.4f}{cache_info}, session: ${self._session_cost:.4f})"
        )

        return RouteResult(
            response=assistant_reply,
            model_used=model,
            is_local=False,
            cost_usd=cost,
            indicator=indicator,
        )

    @property
    def session_cost(self) -> float:
        return self._session_cost
