"""
trellis.core.config — Runtime Configuration

Loads configuration from .env and YAML files.
Single source of truth for all runtime settings.
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def _parse_float(value: str, name: str, default: float) -> float:
    """Parse a float from env, falling back to default on bad input."""
    try:
        return float(value)
    except (ValueError, TypeError):
        logger.warning(f"Invalid value for {name}: {value!r} — using default {default}")
        return default


def load_config(env_path: str = ".env") -> dict:
    """Load configuration from .env file and return as dict."""
    load_dotenv(env_path)

    config = {
        # Model providers
        "anthropic_key": os.getenv("IVY_ANTHROPIC_KEY"),
        "ollama_url": os.getenv("IVY_OLLAMA_URL", "http://localhost:11434"),
        "litellm_url": os.getenv("IVY_LITELLM_URL", "http://localhost:4000"),
        # Communication
        "discord_token": os.getenv("IVY_DISCORD_TOKEN"),
        "discord_guild_id": os.getenv("IVY_DISCORD_GUILD_ID"),
        "discord_allowed_user": os.getenv("IVY_DISCORD_ALLOWED_USER_ID"),
        # Integrations
        "google_credentials_path": os.getenv("IVY_GOOGLE_CREDENTIALS_PATH"),
        "linear_key_morrandmore": os.getenv("IVY_LINEAR_API_KEY_MORRANDMORE"),
        "linear_key_mf": os.getenv("IVY_LINEAR_API_KEY_MF"),
        "github_token": os.getenv("IVY_GITHUB_TOKEN"),
        # Runtime
        "vault_path": Path(os.getenv("IVY_VAULT_PATH", "./ivy-vault")),
        "budget_monthly": _parse_float(os.getenv("IVY_BUDGET_MONTHLY", "100.0"), "IVY_BUDGET_MONTHLY", 100.0),
        "log_level": os.getenv("IVY_LOG_LEVEL", "INFO"),
    }

    # Validate critical config
    missing = []
    if not config["anthropic_key"]:
        missing.append("IVY_ANTHROPIC_KEY")
    if not config["discord_token"]:
        missing.append("IVY_DISCORD_TOKEN")

    if missing:
        logger.warning(f"Missing config keys (some features will be unavailable): {missing}")

    return config
