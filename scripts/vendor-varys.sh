#!/usr/bin/env bash
# Vendor codebyshoaib/varys as a local upstream reference (vendor/ is gitignored).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="$ROOT/vendor/varys"
LOCK_FILE="$ROOT/vendor/varys.lock"
UPSTREAM="https://github.com/codebyshoaib/varys.git"

strip_personal_data() {
  local dir="$1"
  rm -rf \
    "$dir/vault" \
    "$dir/.beads" \
    "$dir/excalidraw.log" \
    "$dir/mempalace/chroma.sqlite3" \
    "$dir/mempalace"/[0-9a-f][0-9a-f][0-9a-f][0-9a-f]* 2>/dev/null || true
}

if [[ "${1:-}" == "update" ]]; then
  if [[ ! -d "$VENDOR_DIR/.git" ]]; then
    echo "No existing clone at $VENDOR_DIR — run without 'update' first." >&2
    exit 1
  fi
  git -C "$VENDOR_DIR" pull --ff-only origin master
  strip_personal_data "$VENDOR_DIR"
  git -C "$VENDOR_DIR" rev-parse HEAD >"$LOCK_FILE"
  echo "Updated varys @ $(cat "$LOCK_FILE")"
  exit 0
fi

mkdir -p "$ROOT/vendor"
if [[ -d "$VENDOR_DIR/.git" ]]; then
  echo "vendor/varys already exists — use: $0 update"
  exit 0
fi

git clone --depth 1 "$UPSTREAM" "$VENDOR_DIR"
strip_personal_data "$VENDOR_DIR"
git -C "$VENDOR_DIR" rev-parse HEAD >"$LOCK_FILE"
echo "Vendored varys @ $(cat "$LOCK_FILE")"
