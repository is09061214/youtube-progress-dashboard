#!/usr/bin/env bash
# Tailwind CSS をビルドする。
# - macOS / Linux 両対応
# - bin/tailwindcss が無ければ公式リリースから取得
# - 入力: app/static/src.css
# - 出力: app/static/tailwind.css

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BIN="$ROOT_DIR/bin/tailwindcss"

if [[ ! -x "$BIN" ]]; then
  mkdir -p "$ROOT_DIR/bin"
  uname_s="$(uname -s)"
  uname_m="$(uname -m)"
  case "$uname_s/$uname_m" in
    Darwin/arm64)  asset="tailwindcss-macos-arm64" ;;
    Darwin/x86_64) asset="tailwindcss-macos-x64" ;;
    Linux/aarch64) asset="tailwindcss-linux-arm64" ;;
    Linux/x86_64)  asset="tailwindcss-linux-x64" ;;
    *) echo "Unsupported platform: $uname_s/$uname_m" >&2; exit 1 ;;
  esac
  url="https://github.com/tailwindlabs/tailwindcss/releases/latest/download/$asset"
  echo "Downloading $url ..."
  curl -sLo "$BIN" "$url"
  chmod +x "$BIN"
fi

mode="${1:-build}"

case "$mode" in
  watch)
    exec "$BIN" -i "$ROOT_DIR/app/static/src.css" -o "$ROOT_DIR/app/static/tailwind.css" --watch
    ;;
  build|*)
    exec "$BIN" -i "$ROOT_DIR/app/static/src.css" -o "$ROOT_DIR/app/static/tailwind.css" --minify
    ;;
esac
