#!/usr/bin/env bash
# Install and enable the Trellis systemd service.
# Run as: sudo bash scripts/install-service.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_FILE="$SCRIPT_DIR/trellis.service"
DEST="/etc/systemd/system/trellis.service"

if [ ! -f "$SERVICE_FILE" ]; then
    echo "Error: trellis.service not found at $SERVICE_FILE"
    exit 1
fi

# Security: warn if .env is world-readable
ENV_FILE="$SCRIPT_DIR/../.env"
if [ -f "$ENV_FILE" ]; then
    PERMS=$(stat -c "%a" "$ENV_FILE")
    if [ "$PERMS" != "600" ]; then
        echo "WARNING: .env has permissions $PERMS (should be 600). Fixing..."
        chmod 600 "$ENV_FILE"
    fi
fi

echo "=== Installing Trellis service ==="

echo "1. Copying service file to $DEST"
cp "$SERVICE_FILE" "$DEST"

echo "2. Reloading systemd daemon"
systemctl daemon-reload

echo "3. Enabling trellis.service (start on boot)"
systemctl enable trellis.service

echo "4. Starting trellis.service"
systemctl start trellis.service

echo "5. Checking status"
systemctl status trellis.service --no-pager

echo ""
echo "=== Done! Ivy is running as a system service. ==="
echo ""
echo "Useful commands:"
echo "  sudo systemctl status trellis    # Check status"
echo "  sudo systemctl restart trellis   # Restart"
echo "  sudo systemctl stop trellis      # Stop"
echo "  sudo journalctl -u trellis -f    # Follow logs"
