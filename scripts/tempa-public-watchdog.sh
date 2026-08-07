#!/usr/bin/env bash
# Restart Cloudflare tunnel if public HTTPS health check fails.
set -euo pipefail

URL="${TEMPA_WATCHDOG_URL:-https://tempa.codenest.fun/api/health}"
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$URL" || true)"

if [[ "$CODE" == "200" ]]; then
  exit 0
fi

logger -t tempa-public-watchdog "tempa public health returned '${CODE}', restarting cloudflared-tempa"
systemctl --user restart cloudflared-tempa.service
sleep 8
CODE2="$(curl -s -o /dev/null -w '%{http_code}' --max-time 25 "$URL" || true)"
logger -t tempa-public-watchdog "after restart health='${CODE2}'"
[[ "$CODE2" == "200" ]]
