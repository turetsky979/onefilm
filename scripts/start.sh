#!/usr/bin/env sh
# Start ONEFILM on a generic Linux host (or WSL). For OpenWrt use init.d/onefilm instead.
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

# Optional overrides — adjust to taste.
export ONEFILM_CONF="${ONEFILM_CONF:-$DIR/config.json}"
export ONEFILM_COOKIE="${ONEFILM_COOKIE:-$DIR/baidu_cookie.txt}"
export ONEFILM_DATA_DIR="${ONEFILM_DATA_DIR:-$DIR/data}"
export ONEFILM_INDEX="${ONEFILM_INDEX:-$DIR/web/index.html}"
export ONEFILM_CURL="${ONEFILM_CURL:-$(command -v curl)}"

echo "ONEFILM starting from $DIR"
exec "$PYTHON" "$DIR/movie_panel.py"
