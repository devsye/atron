#!/usr/bin/env bash
# Update an existing systemd install from the current git checkout.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Run as root"; exit 1; }
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cp "$SRC/bot.py" "$SRC/requirements.txt" /opt/atron/
/opt/atron/venv/bin/pip install -r /opt/atron/requirements.txt
chown atron:atron /opt/atron/bot.py
systemctl restart atron
echo "Updated and restarted."
