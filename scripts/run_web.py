"""
Standalone web server for development (no Discord, no heartbeat).
API endpoints return defaults. Use scripts/run_discord.py for full stack.

Run from the trellis repo root: python scripts/run_web.py
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

import uvicorn  # noqa: E402
from trellis.core.agent_state import AgentState  # noqa: E402
from trellis.core.config import load_config  # noqa: E402
from trellis.core.queue import ApprovalQueue  # noqa: E402
from trellis.senses.web import create_app  # noqa: E402

config = load_config(str(repo_root / ".env"))
app = create_app(
    agent_state=AgentState(),
    queue=ApprovalQueue(vault_path=config["vault_path"]),
    config=config,
)

if __name__ == "__main__":
    uvicorn.run(
        "run_web:app",
        host="0.0.0.0",
        port=8420,
        reload=True,
        reload_dirs=[str(repo_root / "trellis")],
    )
