#!/usr/bin/env bash
# One-shot installer for Debian/Ubuntu servers: installs the bot as a systemd
# service so it runs permanently and restarts on crash/reboot.
#
# Usage:  sudo bash install.sh
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run as root: sudo bash install.sh"; exit 1
fi

APP_DIR=/opt/atron
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Installing system packages"
apt-get update -y
apt-get install -y python3 python3-venv python3-pip curl

echo "==> Creating user and directories"
id atron >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin atron
mkdir -p "$APP_DIR/data" "$APP_DIR/assets"
cp "$SRC_DIR/bot.py" "$SRC_DIR/requirements.txt" "$APP_DIR/"
cp -r "$SRC_DIR/scripts" "$APP_DIR/"

echo "==> Setting up virtualenv"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "==> Downloading fonts (optional)"
bash "$APP_DIR/scripts/download-fonts.sh" "$APP_DIR/assets" || true

if [ ! -f "$APP_DIR/.env" ]; then
  echo
  read -rp "Bot token (from @BotFather): " BOT_TOKEN
  read -rp "Your numeric Telegram ID:    " ADMIN_ID
  umask 077
  cat > "$APP_DIR/.env" <<ENV
BOT_TOKEN=${BOT_TOKEN}
ADMIN_ID=${ADMIN_ID}
CHART_LANG=en
ENV
else
  echo "==> Existing $APP_DIR/.env kept"
fi

chown -R atron:atron "$APP_DIR"
chmod 600 "$APP_DIR/.env"
chmod 700 "$APP_DIR/data"

echo "==> Installing systemd service"
cp "$SRC_DIR/deploy/atron.service" /etc/systemd/system/atron.service
systemctl daemon-reload
systemctl enable --now atron

echo
echo "Done. Send /start to your bot in Telegram."
echo "  Status : systemctl status atron"
echo "  Logs   : journalctl -u atron -f"
echo "  Restart: systemctl restart atron"
