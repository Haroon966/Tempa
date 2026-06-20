#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${TEMPA_DATA_DIR:-$ROOT/data}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${TEMPA_BACKUP_DIR:-$DATA/backups}/$STAMP"

mkdir -p "$DEST"

if [[ -d "$DATA/vector" ]]; then
  cp -a "$DATA/vector" "$DEST/vector"
fi
if [[ -d "$DATA/meetings" ]]; then
  cp -a "$DATA/meetings" "$DEST/meetings"
fi

echo "Backup written to $DEST"
