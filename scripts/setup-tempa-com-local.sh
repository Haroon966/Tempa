#!/usr/bin/env bash
# Map tempa.com → local Tempa dashboard (:8787) with trusted local HTTPS.
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  exec sudo -E "$0" "$@"
fi

HOSTS_LINE="127.0.0.1 tempa.com www.tempa.com"
sed -i -E '/(^|[[:space:]])tempa\.com([[:space:]]|$)/d' /etc/hosts
echo "${HOSTS_LINE}" >> /etc/hosts
echo "Updated /etc/hosts"

CERT_DIR=/etc/ssl/tempa-local
mkdir -p "${CERT_DIR}"

if [[ ! -f "${CERT_DIR}/ca.key" ]]; then
  openssl genrsa -out "${CERT_DIR}/ca.key" 2048
  openssl req -x509 -new -nodes -key "${CERT_DIR}/ca.key" -sha256 -days 3650 \
    -out "${CERT_DIR}/ca.crt" \
    -subj "/CN=Tempa Local CA"
fi

if [[ ! -f "${CERT_DIR}/tempa.com.crt" ]]; then
  openssl genrsa -out "${CERT_DIR}/tempa.com.key" 2048
  openssl req -new -key "${CERT_DIR}/tempa.com.key" -out "${CERT_DIR}/tempa.com.csr" \
    -subj "/CN=tempa.com"
  cat > "${CERT_DIR}/tempa.com.ext" <<'EOF'
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names
[alt_names]
DNS.1 = tempa.com
DNS.2 = www.tempa.com
EOF
  openssl x509 -req -in "${CERT_DIR}/tempa.com.csr" -CA "${CERT_DIR}/ca.crt" \
    -CAkey "${CERT_DIR}/ca.key" -CAcreateserial -out "${CERT_DIR}/tempa.com.crt" \
    -days 825 -sha256 -extfile "${CERT_DIR}/tempa.com.ext"
fi

# Trust local CA system-wide (curl/OpenSSL) + Chrome policy + NSS
cp "${CERT_DIR}/ca.crt" /usr/local/share/ca-certificates/tempa-local-ca.crt
update-ca-certificates >/dev/null

# Google Chrome reads this managed policy (base64 DER roots)
CA_B64=$(openssl x509 -in "${CERT_DIR}/ca.crt" -outform DER | base64 -w0)
mkdir -p /etc/opt/chrome/policies/managed
cat > /etc/opt/chrome/policies/managed/tempa_local_ca.json <<EOF
{"CACertificates":["${CA_B64}"]}
EOF
echo "Installed Chrome policy /etc/opt/chrome/policies/managed/tempa_local_ca.json"

apt-get install -y libnss3-tools >/dev/null
REAL_USER="${SUDO_USER:-$USER}"
REAL_HOME=$(getent passwd "${REAL_USER}" | cut -d: -f6)
mkdir -p "${REAL_HOME}/.pki/nssdb"
chown -R "${REAL_USER}:${REAL_USER}" "${REAL_HOME}/.pki"
NSSDB="sql:${REAL_HOME}/.pki/nssdb"
sudo -u "${REAL_USER}" certutil -d "${NSSDB}" -N --empty-password >/dev/null 2>&1 || true
sudo -u "${REAL_USER}" certutil -d "${NSSDB}" -D -n "Tempa Local CA" >/dev/null 2>&1 || true
sudo -u "${REAL_USER}" certutil -d "${NSSDB}" -A -t "C,," -n "Tempa Local CA" -i "${CERT_DIR}/ca.crt"
echo "Trusted CA in ${REAL_HOME}/.pki/nssdb"

a2enmod ssl proxy proxy_http proxy_wstunnel headers rewrite >/dev/null

cat > /etc/apache2/sites-available/tempa.conf <<EOF
<VirtualHost *:80>
	ServerName tempa.com
	ServerAlias www.tempa.com
	RewriteEngine On
	RewriteRule ^ https://%{HTTP_HOST}%{REQUEST_URI} [L,R=301]
</VirtualHost>

<VirtualHost *:443>
	ServerName tempa.com
	ServerAlias www.tempa.com

	SSLEngine on
	SSLCertificateFile ${CERT_DIR}/tempa.com.crt
	SSLCertificateKeyFile ${CERT_DIR}/tempa.com.key

	ProxyPreserveHost On
	ProxyRequests Off

	# WebSocket (dashboard live activity)
	RewriteEngine On
	RewriteCond %{HTTP:Upgrade} =websocket [NC]
	RewriteRule /(.*)           ws://127.0.0.1:8787/\$1 [P,L]

	ProxyPass        / http://127.0.0.1:8787/
	ProxyPassReverse / http://127.0.0.1:8787/

	ErrorLog \${APACHE_LOG_DIR}/tempa-error.log
	CustomLog \${APACHE_LOG_DIR}/tempa-access.log combined
</VirtualHost>
EOF

a2ensite tempa.conf >/dev/null
# Ensure SSL is listening (default ssl site may be disabled)
if [[ -f /etc/apache2/ports.conf ]] && ! grep -qE '^\s*Listen\s+443' /etc/apache2/ports.conf; then
  echo 'Listen 443' >> /etc/apache2/ports.conf
fi

apache2ctl configtest
systemctl reload apache2

echo
echo "Done. Fully quit Chrome (not just the tab), then open https://tempa.com"
curl -sk -o /dev/null -w "Local HTTPS check: HTTP %{http_code}\n" --resolve tempa.com:443:127.0.0.1 https://tempa.com/
