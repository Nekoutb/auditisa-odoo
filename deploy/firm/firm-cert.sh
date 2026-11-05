#!/usr/bin/env bash
# firm-cert.sh: gets the HTTPS certificate for this firm's names and writes nginx's HTTPS block.
#
#   firm-cert [--dry-run]
#
# Run by a timer until it works, because the DNS record may come after the first boot. Later runs
# change nothing unless /etc/auditisa-firm/domains changed. Renewal is certbot's own timer.

set -euo pipefail
SCRIPT_NAME=firm-cert
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
# shellcheck source=deploy/firm/firm-lib.sh
. "$HERE/firm-lib.sh"
DRY_RUN=0
[ "${1:-}" != "--dry-run" ] || DRY_RUN=1
load_firm_env

mapfile -t NAMES < "$FIRM_ETC/domains"
[ "${#NAMES[@]}" -ge 1 ] || fl_die "no domain"
LIVE=/etc/letsencrypt/live/$FIRM_HOST
SITE=$FIRM_PREFIX/etc/nginx/sites-available/firm-https.conf

write_site() {
  mkdir -p "$(dirname "$SITE")"
  cat > "$SITE" <<EOF
upstream odoo_http { server 127.0.0.1:8069; }
upstream odoo_ws { server 127.0.0.1:8072; }

server {
    listen 443 ssl;
    http2 on;
    server_name ${NAMES[*]};

    ssl_certificate $LIVE/fullchain.pem;
    ssl_certificate_key $LIVE/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Frame-Options SAMEORIGIN always;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;
    add_header X-Robots-Tag "noindex, nofollow" always;

    client_max_body_size 64m;
    proxy_read_timeout 720s;
    proxy_send_timeout 720s;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header X-Forwarded-Host \$host;

    # The database manager does not exist from the outside.
    location ~ ^/web/database { return 404; }

    # The link's token stays out of the access log.
    location /ea-firm/first-admin/ {
        access_log off;
        limit_req zone=odoo_login burst=10 nodelay;
        proxy_pass http://odoo_http;
    }

    location = /web/login {
        limit_req zone=odoo_login burst=20 nodelay;
        proxy_pass http://odoo_http;
    }

    location /websocket {
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_pass http://odoo_ws;
    }

    location / { proxy_pass http://odoo_http; }
}
EOF
}

if [ "$DRY_RUN" = 1 ]; then
  fl_log "DRY RUN: certbot certonly --webroot for ${NAMES[*]}"
  write_site
  exit 0
fi

args=()
for name in "${NAMES[@]}"; do args+=(-d "$name"); done
if [ ! -f "$LIVE/fullchain.pem" ] || [ "$(openssl x509 -in "$LIVE/fullchain.pem" -noout -ext subjectAltName 2>/dev/null | grep -c 'DNS:')" != "${#NAMES[@]}" ]; then
  # Without an e-mail: expiry is watched by the control plane, through the heartbeat.
  certbot certonly --webroot -w /var/www/certbot --cert-name "$FIRM_HOST" --expand "${args[@]}" \
    --agree-tos --no-eff-email --register-unsafely-without-email --non-interactive --quiet \
    --deploy-hook "systemctl reload nginx" \
    || { fl_warn "no certificate yet: is the DNS record for ${NAMES[*]} in place?"; exit 1; }
fi

write_site
ln -sfn "$SITE" /etc/nginx/sites-enabled/firm-https.conf
nginx -t -q
systemctl reload nginx
fl_log "HTTPS is on for ${NAMES[*]}"
