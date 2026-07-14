#!/usr/bin/env bash
# Uninstall logx.   ./logx/uninstall.sh [--prefix DIR]   (default: ~/.local)
set -euo pipefail

PREFIX="${PREFIX:-$HOME/.local}"
[[ "${1:-}" == "--prefix" ]] && PREFIX="$2"
LOGX_HOME="$PREFIX/lib/logx"

if [[ -e "$LOGX_HOME" && ! -e "$LOGX_HOME/src/logx_cli.py" ]]; then
  echo "error: $LOGX_HOME doesn't look like a logx install — not touching it" >&2
  exit 1
fi
rm -rf "$LOGX_HOME"
rm -f "$PREFIX/bin/logx" "$PREFIX/share/man/man1/logx.1"
echo "logx removed from $PREFIX"
