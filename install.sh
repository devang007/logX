#!/usr/bin/env bash
# Install logx: query nginx logs in plain English, fully offline.
#
#   ./install.sh                      # install to ~/.local (fresh venv, downloads model)
#   ./install.sh --link               # dev install: symlink into this repo, reuse .venv
#   ./install.sh --prefix /usr/local           # system-wide (may need sudo)
#   ./install.sh --model-dir path/to/model     # bundle your own checkpoint
#   ./install.sh --model-url URL               # force-download a model zip
#
# The released model zip is downloaded from GitHub and its sha256 verified
# automatically unless a local checkpoint is provided.
#
# Layout:  $PREFIX/lib/logx/{src,schema,model,man,venv}
#          $PREFIX/bin/logx
#          $PREFIX/share/man/man1/logx.1
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
MODE="copy"
MODEL_DIR="$REPO/runs/poc/best"
MODEL_URL=""
MODEL_VERSION="v0.1.0"
MODEL_URL_DEFAULT="https://github.com/devang007/logX/releases/download/$MODEL_VERSION/logx-model-$MODEL_VERSION.zip"
PYTHON="${PYTHON:-python3}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --link) MODE="link"; shift ;;
    --prefix) PREFIX="$2"; shift 2 ;;
    --model-dir) MODEL_DIR="$(cd "$2" && pwd)"; shift 2 ;;
    --model-url) MODEL_URL="$2"; shift 2 ;;
    --python) PYTHON="$2"; shift 2 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "install.sh: unknown option $1 (see --help)" >&2; exit 1 ;;
  esac
done

LOGX_HOME="$PREFIX/lib/logx"

# model source: explicit URL > local checkpoint > released zip
if [[ -z "$MODEL_URL" && ! -f "$MODEL_DIR/config.json" ]]; then
  echo "-> no local model — will download the released model"
  MODEL_URL="$MODEL_URL_DEFAULT"
fi

fetch_model() {  # $1 = url, $2 = dest dir
  local tmp zipname
  tmp="$(mktemp -d)"
  zipname="$(basename "$1")"
  echo "-> downloading model: $1"
  curl -fSL --progress-bar "$1" -o "$tmp/$zipname"
  if curl -fsSL "$1.sha256" -o "$tmp/$zipname.sha256" 2>/dev/null; then
    echo "-> verifying sha256"
    if command -v shasum >/dev/null; then
      (cd "$tmp" && shasum -a 256 -c "$zipname.sha256" >/dev/null)
    else
      (cd "$tmp" && sha256sum -c "$zipname.sha256" >/dev/null)
    fi || { echo "error: checksum verification FAILED — refusing to install" >&2; rm -rf "$tmp"; exit 1; }
  else
    echo "warning: no .sha256 published next to the zip — skipping verification" >&2
  fi
  mkdir -p "$2"
  unzip -q "$tmp/$zipname" -d "$2"
  rm -rf "$tmp"
  [[ -f "$2/config.json" ]] || { echo "error: downloaded zip has no config.json at its root" >&2; exit 1; }
}

# refuse to clobber a directory that isn't a previous logx install
if [[ -e "$LOGX_HOME" && ! -e "$LOGX_HOME/src/logx_cli.py" ]]; then
  echo "error: $LOGX_HOME exists but doesn't look like a logx install — remove it manually" >&2
  exit 1
fi
rm -rf "$LOGX_HOME"
mkdir -p "$LOGX_HOME" "$PREFIX/bin" "$PREFIX/share/man/man1"

if [[ "$MODE" == "link" ]]; then
  echo "-> dev install (symlinks into $REPO, reusing its .venv)"
  [[ -x "$REPO/.venv/bin/python" ]] || { echo "error: --link needs $REPO/.venv (python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)" >&2; exit 1; }
  ln -sfn "$REPO/src"      "$LOGX_HOME/src"
  ln -sfn "$REPO/schema"   "$LOGX_HOME/schema"
  ln -sfn "$REPO/.venv"    "$LOGX_HOME/venv"
  ln -sfn "$REPO/man"      "$LOGX_HOME/man"
  if [[ -n "$MODEL_URL" ]]; then
    fetch_model "$MODEL_URL" "$LOGX_HOME/model"
  else
    ln -sfn "$MODEL_DIR" "$LOGX_HOME/model"
  fi
else
  echo "-> copying code, schema, model to $LOGX_HOME"
  mkdir -p "$LOGX_HOME/src" "$LOGX_HOME/schema" "$LOGX_HOME/man"
  cp "$REPO/src/logx_cli.py" "$REPO/src/dsl_common.py" "$REPO/src/executor.py" "$LOGX_HOME/src/"
  cp "$REPO/schema/dsl_v0.1.json" "$REPO/schema/fields.py" "$LOGX_HOME/schema/"
  if [[ -n "$MODEL_URL" ]]; then
    fetch_model "$MODEL_URL" "$LOGX_HOME/model"
  else
    cp -R "$MODEL_DIR" "$LOGX_HOME/model"
  fi
  cp "$REPO/man/logx.1" "$LOGX_HOME/man/"
  echo "-> creating venv (downloads torch — a few GB, one time)"
  "$PYTHON" -m venv "$LOGX_HOME/venv"
  "$LOGX_HOME/venv/bin/pip" install --quiet --upgrade pip
  "$LOGX_HOME/venv/bin/pip" install --quiet torch transformers sentencepiece jsonschema
fi

sed "s|@LOGX_HOME@|$LOGX_HOME|" "$REPO/bin/logx.in" > "$PREFIX/bin/logx"
chmod +x "$PREFIX/bin/logx"
cp "$REPO/man/logx.1" "$PREFIX/share/man/man1/logx.1"

echo "-> smoke test"
"$PREFIX/bin/logx" --version

echo
echo "installed: $PREFIX/bin/logx   (home: $LOGX_HOME, mode: $MODE)"
echo "manual   : man logx   (or: logx --manual)"
case ":$PATH:" in
  *":$PREFIX/bin:"*) ;;
  *) echo "NOTE: $PREFIX/bin is not in PATH — add:  export PATH=\"$PREFIX/bin:\$PATH\"" ;;
esac
