#!/data/data/com.termux/files/usr/bin/bash
# Run the bot on an Android phone with Termux (for testing; a real server is
# recommended for permanent use).
set -e
DIR="$HOME/atron"
SRC="$(cd "$(dirname "$0")/.." && pwd)"

pkg update -y && pkg install -y python curl
pkg install -y matplotlib python-pillow || echo "matplotlib failed; image charts will be disabled."
pip install --upgrade pyTelegramBotAPI requests arabic-reshaper

mkdir -p "$DIR/data"
cp "$SRC/bot.py" "$DIR/"
bash "$SRC/scripts/download-fonts.sh" "$DIR/assets" || true

if [ ! -f "$DIR/.env" ]; then
  read -rp "Bot token: " BOT_TOKEN
  read -rp "Your numeric Telegram ID: " ADMIN_ID
  umask 077
  printf 'BOT_TOKEN=%s\nADMIN_ID=%s\n' "$BOT_TOKEN" "$ADMIN_ID" > "$DIR/.env"
fi

cat > "$DIR/run.sh" <<'RUN'
#!/data/data/com.termux/files/usr/bin/bash
cd "$(dirname "$0")"
set -a; . ./.env; set +a
exec python bot.py
RUN
chmod +x "$DIR/run.sh"

termux-wake-lock 2>/dev/null || true
pkill -f "atron/bot.py" 2>/dev/null || true
nohup "$DIR/run.sh" > "$DIR/bot.log" 2>&1 &
echo "Started. Logs: tail -f ~/atron/bot.log"
