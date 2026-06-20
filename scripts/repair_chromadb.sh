#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${TEMPA_DATA_DIR:-$ROOT/data}"
VECTOR="$DATA/vector"

if [[ ! -d "$VECTOR" ]]; then
  echo "No vector store at $VECTOR"
  exit 0
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="${DATA}/backups/chroma-repair-$STAMP"
mkdir -p "$BACKUP"
cp -a "$VECTOR" "$BACKUP/"

echo "Chroma backup at $BACKUP — re-run ingest or restore from backup if needed."
