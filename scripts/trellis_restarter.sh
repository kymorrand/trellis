#!/usr/bin/env bash
# trellis_restarter.sh — Watches for restart trigger file and restarts trellis.service
#
# Runs as a companion systemd service. When Ivy writes _ivy/restart-requested
# (via the request_restart tool), this script picks it up and restarts the main
# trellis service. Decouples "request restart" from "perform restart" so the
# dying process never has to kill itself.

set -euo pipefail

VAULT_PATH="${IVY_VAULT_PATH:-/home/kyle/projects/ivy-vault}"
TRIGGER_FILE="${VAULT_PATH}/_ivy/restart-requested"
POLL_INTERVAL=2

echo "trellis-restarter: watching for ${TRIGGER_FILE} (poll every ${POLL_INTERVAL}s)"

while true; do
    if [ -f "$TRIGGER_FILE" ]; then
        echo "trellis-restarter: restart requested — $(cat "$TRIGGER_FILE")"
        rm -f "$TRIGGER_FILE"
        echo "trellis-restarter: restarting trellis.service..."
        sudo systemctl restart trellis.service
        echo "trellis-restarter: trellis.service restarted"
    fi
    sleep "$POLL_INTERVAL"
done
