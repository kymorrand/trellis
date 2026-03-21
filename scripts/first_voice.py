"""
Ivy's First Voice — minimal CLI chat to prove the stack works.
Loads SOUL.md as system prompt, calls Claude, lets Kyle talk to Ivy.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

soul_path = Path("agents/ivy/SOUL.md")
if not soul_path.exists():
    print("❌ SOUL.md not found. Run from the trellis repo root.")
    exit(1)

soul = soul_path.read_text()

api_key = os.getenv("IVY_ANTHROPIC_KEY")
if not api_key:
    print("❌ IVY_ANTHROPIC_KEY not set in .env")
    exit(1)

client = Anthropic(api_key=api_key)
messages = []

print("=" * 60)
print("🌱 Ivy is awake.")
print("   Model: claude-sonnet-4-20250514")
print("   Soul: agents/ivy/SOUL.md")
print("   Type 'quit' to exit.")
print("=" * 60)
print()

while True:
    user_input = input("Kyle: ").strip()
    if not user_input:
        continue
    if user_input.lower() in ("quit", "exit", "q"):
        print("\n🌱 Ivy going quiet. See you soon, Kyle.")
        break

    messages.append({"role": "user", "content": user_input})

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=soul,
        messages=messages,
    )

    ivy_reply = response.content[0].text
    messages.append({"role": "assistant", "content": ivy_reply})

    print(f"\nIvy: {ivy_reply}\n")
