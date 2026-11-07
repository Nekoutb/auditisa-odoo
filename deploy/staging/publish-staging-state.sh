#!/usr/bin/env bash
# publish-staging-state.sh: what status.auditisa.com may know about staging. On the staging server.
#
#   publish-staging-state              writes the file once
#   publish-staging-state --install    copies itself to /usr/local/sbin and adds a timer, every minute
#   publish-staging-state --uninstall  removes the timer and the file
#   publish-staging-state --print      prints what it would write, and changes nothing
#
# The file holds a commit, two yes-or-no answers read from the database and two dates. It is public, like
# the rest of the status page, so it holds nothing else.
#
# If /etc/auditisa-staging/heartbeat.env (HEARTBEAT_URL, SLUG) and heartbeat.token exist beside it, it also sends
# the control plane a signed heartbeat every 15 minutes, while Odoo answers. Done here and not by Odoo's own
# agent because staging's crons are off. The answer is ignored: staging takes no order from the control plane.

set -euo pipefail
: "${ODOO_CONF:=/etc/odoo/odoo.conf}"
: "${OUT_FILE:=/var/www/auditisa-public/manual/staging-state.json}"
UNIT=auditisa-staging-state

conf_value() { sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$ODOO_CONF" | tail -n 1; }
q() { runuser -u postgres -- psql -X -At -d "$(conf_value db_name)" -c "$1"; }

state() {
  local path release short mail band rebuilt
  path=$(conf_value addons_path | tr ',' '\n' | grep -E '^/opt/auditisa-odoo/' | head -n 1)
  path=$(readlink -f "$path")
  short=$(basename "$(dirname "$path")")
  release=$short
  # A full commit if this server's mirror knows the short one.
  if [ -d /opt/auditisa-odoo-src.git ]; then
    release=$(git -C /opt/auditisa-odoo-src.git rev-parse --verify --quiet "$short^{commit}" || printf '%s' "$short")
  fi
  [[ $release =~ ^[0-9a-f]{7,40}$ ]] || release=""
  mail=$(q "SELECT count(*) FROM ir_mail_server WHERE active")
  band=$(q "SELECT value FROM ir_config_parameter WHERE key = 'ea_audit.staging_band'")
  rebuilt=$(stat -c %y "$(ls -1t /var/backups/odoo/before-rebuild/*.dump 2>/dev/null | head -n 1)" 2>/dev/null | cut -c1-19 | tr ' ' T || true)
  printf '{"schema":1,"release":"%s","at":"%s","mail_off":%s,"band_on":%s,"rebuilt_at":%s}\n' \
    "$release" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$([ "$mail" = 0 ] && [ -z "$(conf_value smtp_server | grep -vE '^(False|false)?$')" ] && echo true || echo false)" \
    "$([ "$band" = 1 ] && echo true || echo false)" \
    "$([ -n "$rebuilt" ] && printf '"%sZ"' "$rebuilt" || echo null)"
}

case "${1:-}" in
  --print) state; exit 0 ;;
  --install)
    [ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
    install -m 755 "$0" /usr/local/sbin/publish-staging-state
    cat > "/etc/systemd/system/$UNIT.service" <<EOF
[Unit]
Description=AuditISA: publish staging's state for the status page
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/publish-staging-state
Nice=10
EOF
    cat > "/etc/systemd/system/$UNIT.timer" <<EOF
[Unit]
Description=AuditISA: publish staging's state each minute
[Timer]
OnBootSec=1min
OnUnitActiveSec=1min
AccuracySec=5s
[Install]
WantedBy=timers.target
EOF
    systemctl daemon-reload
    systemctl enable --now "$UNIT.timer"
    /usr/local/sbin/publish-staging-state
    cat "$OUT_FILE"
    exit 0 ;;
  --uninstall)
    systemctl disable --now "$UNIT.timer" || true
    rm -f "/etc/systemd/system/$UNIT.service" "/etc/systemd/system/$UNIT.timer" "$OUT_FILE" /usr/local/sbin/publish-staging-state
    systemctl daemon-reload
    exit 0 ;;
  "") ;;
  *) sed -n '2,10p' "$0"; exit 64 ;;
esac

tmp=$(mktemp "$OUT_FILE.XXXXXX")
state > "$tmp"
chmod 644 "$tmp"
mv -f "$tmp" "$OUT_FILE"

HB_ENV=/etc/auditisa-staging/heartbeat.env
HB_TOKEN=/etc/auditisa-staging/heartbeat.token
HB_STAMP=/var/lib/auditisa-staging/last-heartbeat
if [ -r "$HB_ENV" ] && [ -r "$HB_TOKEN" ]; then
  mkdir -p "$(dirname "$HB_STAMP")"
  if [ -z "$(find "$HB_STAMP" -mmin -14 2>/dev/null)" ] \
    && [ "$(curl -s --max-time 10 -o /dev/null -w '%{http_code}' http://127.0.0.1:8069/web/health)" = 200 ]; then
    # shellcheck disable=SC1090
    . "$HB_ENV"
    release=$(sed -n 's/.*"release":"\([0-9a-f]*\)".*/\1/p' "$OUT_FILE")
    mail=$(sed -n 's/.*"mail_off":\(true\|false\).*/\1/p' "$OUT_FILE")
    used=$(df --output=pcent / | tail -n 1 | tr -dc 0-9)
    total=$(awk '/^MemTotal:/ {print int($2 / 1024)}' /proc/meminfo)
    available=$(awk '/^MemAvailable:/ {print int($2 / 1024)}' /proc/meminfo)
    body=$(printf '{"schema":1,"odoo_version":"19.0","release":"%s","disk_used_pct":%s,"mem_total_mb":%s,"mem_available_mb":%s,"users_active":0,"engagements_active":0,"update_state":"idle","export_state":"none","mail_enabled":%s}' \
      "$release" "$used" "$total" "$available" "$([ "$mail" = true ] && echo false || echo true)")
    timestamp=$(date +%s)
    digest=$(printf '%s' "$body" | sha256sum | cut -d' ' -f1)
    # Python, because a key passed to openssl would sit on a command line, where `ps` shows it.
    signature=$(printf 'ea-heartbeat-v1\n%s\n%s\n%s' "$SLUG" "$timestamp" "$digest" | /opt/odoo19/venv/bin/python -I -c '
import hashlib, hmac, sys
token = open(sys.argv[1], encoding="ascii").read().strip().encode()
print(hmac.new(token, sys.stdin.buffer.read(), hashlib.sha256).hexdigest())' "$HB_TOKEN")
    if curl -fsS --max-time 20 -o /dev/null -H 'Content-Type: application/json' -H "X-EA-Firm: $SLUG" \
      -H "X-EA-Timestamp: $timestamp" -H "X-EA-Signature: $signature" --data-binary "$body" "$HEARTBEAT_URL"; then
      touch "$HB_STAMP"
    fi
  fi
fi
