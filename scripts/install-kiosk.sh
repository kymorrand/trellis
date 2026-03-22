#!/usr/bin/env bash
# Install Trellis kiosk mode — auto-launch Chromium at localhost:8420
# on Greenhouse's display. Runs as a systemd user service.
#
# Usage: bash scripts/install-kiosk.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_DIR="$HOME/.config/systemd/user"

mkdir -p "$SERVICE_DIR"

# ─── Kiosk Service ────────────────────────────────────────

cat > "$SERVICE_DIR/trellis-kiosk.service" << 'EOF'
[Unit]
Description=Trellis Kiosk — Always-On Display
After=graphical-session.target trellis.service
Wants=graphical-session.target

[Service]
Type=simple
Environment=DISPLAY=:1
Environment=XAUTHORITY=/run/user/1000/gdm/Xauthority
ExecStartPre=/bin/sleep 5
ExecStart=/usr/bin/google-chrome-stable \
    --kiosk \
    --noerrdialogs \
    --disable-session-crashed-bubble \
    --disable-infobars \
    --disable-translate \
    --no-first-run \
    --fast \
    --fast-start \
    --disable-features=TranslateUI \
    --disk-cache-dir=/dev/null \
    --password-store=basic \
    http://localhost:8420
Restart=on-failure
RestartSec=10

[Install]
WantedBy=graphical-session.target
EOF

# ─── Daily Restart Timer (stability) ─────────────────────

cat > "$SERVICE_DIR/trellis-kiosk-restart.service" << 'EOF'
[Unit]
Description=Restart Trellis Kiosk (daily stability)

[Service]
Type=oneshot
ExecStart=/usr/bin/systemctl --user restart trellis-kiosk.service
EOF

cat > "$SERVICE_DIR/trellis-kiosk-restart.timer" << 'EOF'
[Unit]
Description=Daily Trellis Kiosk restart at 4 AM

[Timer]
OnCalendar=*-*-* 04:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

# ─── Enable ──────────────────────────────────────────────

systemctl --user daemon-reload
systemctl --user enable trellis-kiosk.service
systemctl --user enable trellis-kiosk-restart.timer

echo ""
echo "=== Trellis Kiosk Installed ==="
echo ""
echo "Services created:"
echo "  trellis-kiosk.service        — Chromium in kiosk mode at localhost:8420"
echo "  trellis-kiosk-restart.timer  — Daily restart at 4 AM for stability"
echo ""
echo "To start now:   systemctl --user start trellis-kiosk"
echo "To check:       systemctl --user status trellis-kiosk"
echo "To stop:        systemctl --user stop trellis-kiosk"
echo ""
echo "NOTE: The trellis.service (Discord + web + heartbeat) must be"
echo "      running first. Start it with: sudo systemctl start trellis"
echo ""
