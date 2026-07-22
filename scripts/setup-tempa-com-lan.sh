#!/usr/bin/env bash
# Prepares local dashboard proxy + starts LAN-wide tempa.com override (no phone settings).
set -euo pipefail
cd "$(dirname "$0")/.."
exec ./scripts/tempa-lan-hijack.sh start
