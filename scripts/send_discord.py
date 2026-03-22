"""
One-shot Discord message sender via REST API (no bot gateway connection).
Usage: python scripts/send_discord.py <channel_name> <message>

Safe to use while the bot is running — uses HTTP API only.
"""
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

repo_root = Path(__file__).resolve().parent.parent
load_dotenv(repo_root / ".env")

TOKEN = os.getenv("IVY_DISCORD_TOKEN")
GUILD_ID = os.getenv("IVY_DISCORD_GUILD_ID")
HEADERS = {"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json"}
BASE = "https://discord.com/api/v10"


def find_channel(name: str) -> str | None:
    """Find a channel ID by name in the configured guild."""
    r = httpx.get(f"{BASE}/guilds/{GUILD_ID}/channels", headers=HEADERS)
    r.raise_for_status()
    for ch in r.json():
        if ch["name"] == name and ch["type"] == 0:  # text channel
            return ch["id"]
    return None


def send_message(channel_id: str, content: str):
    """Send a message to a Discord channel."""
    r = httpx.post(
        f"{BASE}/channels/{channel_id}/messages",
        headers=HEADERS,
        json={"content": content},
    )
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/send_discord.py <channel_name> <message>")
        sys.exit(1)

    channel_name = sys.argv[1]
    message = sys.argv[2]

    channel_id = find_channel(channel_name)
    if not channel_id:
        print(f"Channel '{channel_name}' not found in guild {GUILD_ID}")
        sys.exit(1)

    result = send_message(channel_id, message)
    print(f"Message sent to #{channel_name} (id: {result['id']})")
