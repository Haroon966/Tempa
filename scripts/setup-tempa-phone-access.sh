#!/usr/bin/env bash
# Make http://<laptop-wifi-ip>/ serve the Tempa dashboard for phones on the same Wi‑Fi.
# ARP/DNS hijack is unreliable on modern Wi‑Fi — IP access always works.
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  exec sudo -E "$0" "$@"
fi

WIFI_IP=$(ip -4 route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')
CERT_DIR=/etc/ssl/tempa-local

if [[ -z "${WIFI_IP}" ]]; then
  echo "No Wi‑Fi IP" >&2
  exit 1
fi

# Stop previous hijack if running (it does not work on this AP and can confuse the LAN)
if [[ -x /home/olufsen/tempa/scripts/tempa-lan-hijack.sh ]]; then
  /home/olufsen/tempa/scripts/tempa-lan-hijack.sh stop >/dev/null 2>&1 || true
fi

a2enmod proxy proxy_http proxy_wstunnel headers rewrite ssl >/dev/null

# Default site → dashboard (phones open by IP, no Host: tempa.com)
cat > /etc/apache2/sites-available/tempa.conf <<EOF
<VirtualHost *:80>
	ServerName tempa.com
	ServerAlias www.tempa.com ${WIFI_IP} localhost

	ProxyPreserveHost On
	ProxyRequests Off

	RewriteEngine On
	RewriteCond %{HTTP:Upgrade} =websocket [NC]
	RewriteRule /(.*)           ws://127.0.0.1:8787/\$1 [P,L]

	ProxyPass        / http://127.0.0.1:8787/
	ProxyPassReverse / http://127.0.0.1:8787/
</VirtualHost>
EOF

if [[ -f "${CERT_DIR}/tempa.com.crt" ]]; then
  cat >> /etc/apache2/sites-available/tempa.conf <<EOF

<VirtualHost *:443>
	ServerName tempa.com
	ServerAlias www.tempa.com ${WIFI_IP}

	SSLEngine on
	SSLCertificateFile ${CERT_DIR}/tempa.com.crt
	SSLCertificateKeyFile ${CERT_DIR}/tempa.com.key

	ProxyPreserveHost On
	ProxyRequests Off

	RewriteEngine On
	RewriteCond %{HTTP:Upgrade} =websocket [NC]
	RewriteRule /(.*)           ws://127.0.0.1:8787/\$1 [P,L]

	ProxyPass        / http://127.0.0.1:8787/
	ProxyPassReverse / http://127.0.0.1:8787/
</VirtualHost>
EOF
fi

a2dissite 000-default >/dev/null 2>&1 || true
a2ensite tempa.conf >/dev/null
apache2ctl configtest
systemctl reload apache2

# Keep /etc/hosts for this laptop only
sed -i -E '/(^|[[:space:]])tempa\.com([[:space:]]|$)/d' /etc/hosts
echo "127.0.0.1 tempa.com www.tempa.com" >> /etc/hosts

echo
echo "Phone (same Wi‑Fi) — open this exact URL:"
echo "  http://${WIFI_IP}"
echo
echo "Checking..."
curl -s -o /dev/null -w "  http://${WIFI_IP}/ → HTTP %{http_code}\n" "http://${WIFI_IP}/"
curl -s "http://${WIFI_IP}/" | head -c 120
echo
