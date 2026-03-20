"""
trellis.mind.router — Model Routing

Routes inference requests to local (Ollama) or cloud (Anthropic) models
based on task complexity, privacy requirements, and budget.

Routing logic:
    Simple tasks    → Local small model (Llama 3.3 8B)     — free, fast, private
    Medium tasks    → Local large model (Qwen 3 14B)       — free, moderate speed
    Complex tasks   → Claude Sonnet 4.6 via Anthropic API  — paid, highest quality
    Coding tasks    → Local coder (Qwen 2.5 Coder 14B)     — free, specialized
    Sensitive data  → ALWAYS local, regardless of complexity
"""

import logging

logger = logging.getLogger(__name__)

# TODO: Implement model router
# - Integration with LiteLLM proxy for unified API
# - Complexity classification (simple / medium / complex / coding / sensitive)
# - Budget tracking and enforcement ($100/month cap)
# - Warn at 75% budget, stop non-essential cloud calls at 90%
# - Fallback chains (if local fails, escalate to cloud)
# - Cost logging per request
