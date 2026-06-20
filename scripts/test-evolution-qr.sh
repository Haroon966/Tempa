#!/usr/bin/env bash
set -euo pipefail
KEY="${EVOLUTION_API_KEY:-tempa-evolution-key}"
BASE="http://127.0.0.1:8080"
HDR=(-H "apikey: ${KEY}")

echo "=== delete ==="
curl -s -m 10 -X DELETE "${HDR[@]}" "${BASE}/instance/delete/tempa" || true
sleep 2

echo "=== create (no qrcode wait) ==="
curl -s -m 15 -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  "${BASE}/instance/create" \
  -d '{"instanceName":"tempa","integration":"WHATSAPP-BAILEYS","qrcode":false}'
echo

echo "=== disable webhook ==="
curl -s -m 5 -X POST "${HDR[@]}" -H "Content-Type: application/json" \
  "${BASE}/webhook/set/tempa" \
  -d '{"webhook":{"enabled":false,"url":"http://tempa-daemon:8787/webhooks/whatsapp","events":[]}}' >/dev/null

echo "=== connect (trigger) ==="
curl -s -m 15 "${HDR[@]}" "${BASE}/instance/connect/tempa" || echo "connect timeout"
echo

for i in $(seq 1 15); do
  sleep 3
  state=$(curl -s -m 3 "${HDR[@]}" "${BASE}/instance/connectionState/tempa" | python3 -c "import sys,json; print(json.load(sys.stdin)['instance']['state'])" 2>/dev/null || echo "?")
  qr=$(curl -s -m 8 "${HDR[@]}" "${BASE}/instance/connect/tempa" 2>/dev/null || echo "{}")
  info=$(echo "$qr" | python3 -c "import sys,json; d=json.load(sys.stdin); print('b64',len(d.get('base64')or''),'code',len(d.get('code')or''),'count',d.get('count'))" 2>/dev/null || echo "parse_fail")
  echo "poll $i state=$state $info"
  if echo "$qr" | python3 -c "import sys,json; d=json.load(sys.stdin); import sys; sys.exit(0 if len(d.get('base64') or d.get('code') or '')>10 else 1)" 2>/dev/null; then
    echo "QR FOUND"
    exit 0
  fi
done
echo "NO QR after 45s"
docker logs tempa-evolution-api-1 2>&1 | grep -i qrcodeCount | tail -5 || true
exit 1
