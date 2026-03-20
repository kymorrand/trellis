"""
trellis.mind.roles — Role Management (Ditto Roles Prototype)

Roles configure how Ivy operates for different types of work.
Each role defines context priorities, tone, available tools,
autonomy level, and model preferences.
"""

import logging
import yaml
from pathlib import Path

logger = logging.getLogger(__name__)


def load_role(role_name: str = "_default", agent_name: str = "ivy") -> dict:
    """Load a role configuration from YAML."""
    role_path = Path("agents") / agent_name / "roles" / f"{role_name}.yaml"
    if not role_path.exists():
        role_path = Path("agents") / agent_name / "roles" / "_default.yaml"
        logger.info(f"Role '{role_name}' not found, falling back to _default")

    with open(role_path) as f:
        role = yaml.safe_load(f)

    logger.info(f"Loaded role: {role.get('name', role_name)}")
    return role
