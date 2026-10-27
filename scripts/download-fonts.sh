#!/usr/bin/env bash
# Downloads the Vazirmatn font (OFL license) used for Persian chart labels.
set -e
DEST="${1:-$(dirname "$0")/../assets}"
mkdir -p "$DEST"
BASE_URL="https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/fonts/ttf"
for W in Regular Bold; do
  OUT="$DEST/Vazirmatn-$W.ttf"
  [ "$W" = "Regular" ] && OUT="$DEST/Vazirmatn.ttf"
  if [ ! -s "$OUT" ]; then
    curl -fsSL -m 60 -o "$OUT" "$BASE_URL/Vazirmatn-$W.ttf" || rm -f "$OUT"
    [ -f "$OUT" ] && [ "$(wc -c < "$OUT")" -lt 50000 ] && rm -f "$OUT"
  fi
done
echo "Fonts ready in $DEST"
