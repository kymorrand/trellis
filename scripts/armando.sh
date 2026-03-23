#!/bin/bash
# Launch Armando — The Gardener
# Thorn is the lead. Bloom and Root are dispatched as subagents.
# Let's go do it, dude.

# Activate venv if it exists in current project
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

claude --dangerously-skip-permissions --agent thorn
