#!/usr/bin/env bash
# One-time Cloudflare Tunnel setup for tempa.codenest.fun (free, works while traveling).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DOMAIN="${TEMPA_PUBLIC_BASE_URL:-https://tempa.codenest.fun}"
DOMAIN_HOST="${DOMAIN#https://}"
DOMAIN_HOST="${DOMAIN_HOST#http://}"
DOMAIN_HOST="${DOMAIN_HOST%%/*}"

cat <<EOF
╔══════════════════════════════════════════════════════════╗
║  Tempa public domain — Cloudflare Tunnel (free)         ║
╚══════════════════════════════════════════════════════════╝

Why tunnel: this is a laptop that moves. Port-forward + static
IP will break on hotel/café Wi‑Fi. Tunnel is outbound-only.

── Steps (≈10 minutes, one-time) ──────────────────────────

1) Create a free Cloudflare account
   https://dash.cloudflare.com/sign-up

2) Add site: codenest.fun  (Free plan)
   Cloudflare will show 2 nameservers.

3) At Hostinger → Domains → codenest.fun → Nameservers
   Replace Hostinger NS with Cloudflare's 2 nameservers.
   Wait until Cloudflare shows the zone as Active (can take minutes–hours).

4) Cloudflare Zero Trust → Networks → Tunnels → Create a tunnel
   https://one.dash.cloudflare.com/
   · Name: tempa
   · Install connector: choose Docker — copy the token
     (looks like: eyJ... long string)

5) Paste the token into .env:
     CLOUDFLARE_TUNNEL_TOKEN=eyJ...

6) In the same tunnel → Public Hostname → Add:
     Subdomain : tempa
     Domain    : codenest.fun
     Type      : HTTP
     URL       : tempa-daemon:8787
   (no http:// prefix in some UIs — use exactly: tempa-daemon:8787
    or http://tempa-daemon:8787 depending on the form)

7) Delete the old Hostinger A record for "tempa" if Cloudflare
   did not already create the CNAME (Cloudflare usually manages it).

8) Start the tunnel:
     docker compose --profile tunnel up -d

9) Google Cloud Console → OAuth client → Authorized redirect URIs
   add:
     ${DOMAIN}/api/connections/google/callback

── After that ─────────────────────────────────────────────
Open:  ${DOMAIN}
Laptop must be on + Docker running for the site to answer.

EOF

if grep -q '^CLOUDFLARE_TUNNEL_TOKEN=.\+' .env 2>/dev/null; then
  echo "✓ CLOUDFLARE_TUNNEL_TOKEN is set in .env"
  echo "  Starting tunnel profile…"
  docker compose --profile tunnel up -d cloudflared
  echo
  echo "Check: docker compose --profile tunnel logs -f cloudflared"
  echo "Then open: $DOMAIN"
else
  echo "○ CLOUDFLARE_TUNNEL_TOKEN is empty — finish steps 1–6, then re-run:"
  echo "  ./scripts/setup-cloudflare-tunnel.sh"
fi
