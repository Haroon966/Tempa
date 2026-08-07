#!/usr/bin/env bash
# Launch Tempa daemon; Meet Chromium expects Xvfb on DISPLAY (tempa-xvfb.service).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p data/logs

export DISPLAY="${DISPLAY:-:99}"
if [[ "${DISPLAY}" == :0 || "${DISPLAY}" == :0.* ]]; then
  export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"
else
  unset XAUTHORITY || true
fi

if ! xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
  echo "start-tempa-daemon: DISPLAY=$DISPLAY is not ready (Meet joins need Xvfb)" >&2
  exit 1
fi

if [[ -d "$ROOT/vendor/rumixtempa/skills" ]]; then
  if [[ -d /repos ]] && [[ ! -e /repos/rumixtempa ]]; then
    ln -sfn "$ROOT/vendor/rumixtempa" /repos/rumixtempa 2>/dev/null || true
  fi
fi

export PATH="$ROOT/.venv/bin:${PATH:-/usr/bin}"
exec "$ROOT/.venv/bin/tempa" start
