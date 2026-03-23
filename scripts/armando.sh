#!/bin/bash
# Launch Armando — The Gardener
# Let's go do it, dude.

SESSION="armando"
DIR="$HOME/projects/trellis"
ACTIVATE="source $DIR/.venv/bin/activate"
FLAGS="--dangerously-skip-permissions"

tmux kill-session -t $SESSION 2>/dev/null

# Thorn (left pane)
tmux new-session -d -s $SESSION -n "gardener" -c "$DIR"
tmux send-keys -t $SESSION "$ACTIVATE && claude $FLAGS --worktree trellis-pm --agent thorn" Enter

# Bloom (top-right)
tmux split-window -h -t $SESSION -c "$DIR"
tmux send-keys -t $SESSION "$ACTIVATE && claude $FLAGS --worktree trellis-frontend --agent bloom" Enter

# Root (bottom-right)
tmux split-window -v -t $SESSION -c "$DIR"
tmux send-keys -t $SESSION "$ACTIVATE && claude $FLAGS --worktree trellis-backend --agent root" Enter

tmux select-pane -t $SESSION:0.0
tmux attach -t $SESSION
