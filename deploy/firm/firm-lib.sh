#!/usr/bin/env bash
# firm-lib.sh: what the firm server's scripts share. Sourced, never run.
#
# FIRM_PREFIX is empty on a real server. The dry runs set it to a folder, so that nothing outside
# that folder is ever written.
#
# Layout on the server:
#   /etc/auditisa-firm/firm.env            who this server is (no secret)
#   /etc/auditisa-firm/secrets/            heartbeat.token (root:odoo 640), restic.key, s3.env (root 600)
#   /etc/auditisa-firm/release-signing.pub the key that release bundles must be signed with
#   /var/lib/auditisa-firm/status/<name>   one health figure per file, read by ea_audit_firm_agent
#   /var/lib/auditisa-firm/spool/          what the control plane asked (written by odoo, read by root)
#   /var/log/auditisa-firm/                logs, and break-glass.log (append-only)

: "${FIRM_PREFIX:=}"
FIRM_ETC=$FIRM_PREFIX/etc/auditisa-firm
FIRM_SECRETS=$FIRM_ETC/secrets
FIRM_VAR=$FIRM_PREFIX/var/lib/auditisa-firm
FIRM_STATUS=$FIRM_VAR/status
FIRM_SPOOL=$FIRM_VAR/spool
FIRM_LOGS=$FIRM_PREFIX/var/log/auditisa-firm
BREAK_GLASS_LOG=$FIRM_LOGS/break-glass.log
BIN_DIR=$FIRM_PREFIX/opt/auditisa-firm/bin
PROVISION_DIR=$FIRM_PREFIX/opt/auditisa-firm/provision
RELEASES_DIR=$FIRM_PREFIX/opt/auditisa-odoo/releases
CURRENT_LINK=$FIRM_PREFIX/opt/auditisa-odoo/current
ODOO_CONF=${ODOO_CONF:-$FIRM_PREFIX/etc/odoo/odoo.conf}
ODOO_PY=${ODOO_PY:-/opt/odoo19/venv/bin/python}
ODOO_BIN=${ODOO_BIN:-/opt/odoo19/src/odoo-bin}
export ODOO_CONF ODOO_PY ODOO_BIN

fl_log() { printf '[%s] %s\n' "${SCRIPT_NAME:-firm}" "$*"; }
fl_warn() { printf '[%s] WARNING: %s\n' "${SCRIPT_NAME:-firm}" "$*" >&2; }
fl_die() { printf '[%s] ERROR: %s\n' "${SCRIPT_NAME:-firm}" "$*" >&2; exit 1; }

now_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# Atomic, so the agent never reads half a figure.
set_status() {
  local name=$1 value=$2 tmp
  tmp=$(mktemp "$FIRM_STATUS/.$name.XXXXXX")
  printf '%s\n' "$value" > "$tmp"
  chmod 644 "$tmp"
  mv -f "$tmp" "$FIRM_STATUS/$name"
}

get_status() { cat "$FIRM_STATUS/$1" 2>/dev/null || true; }

load_firm_env() {
  [ -r "$FIRM_ETC/firm.env" ] || fl_die "$FIRM_ETC/firm.env is missing: is this a firm server?"
  # shellcheck disable=SC1091
  . "$FIRM_ETC/firm.env"
  : "${FIRM_SLUG:?}" "${FIRM_HOST:?}" "${FIRM_DB:?}"
}

load_backup_env() {
  [ -r "$FIRM_SECRETS/s3.env" ] || fl_die "$FIRM_SECRETS/s3.env is missing"
  set -a
  # shellcheck disable=SC1091
  . "$FIRM_SECRETS/s3.env"
  set +a
  export RESTIC_PASSWORD_FILE=$FIRM_SECRETS/restic.key
}

psql_q() { runuser -u postgres -- psql -X -v ON_ERROR_STOP=1 -At -d "${2:-postgres}" -c "$1"; }
db_exists() { [ -n "$(psql_q "SELECT 1 FROM pg_database WHERE datname = '$1'")" ]; }

valid_release() { [[ $1 =~ ^[0-9a-f]{12,40}$ ]]; }
valid_digest() { [[ $1 =~ ^[0-9a-f]{64}$ ]]; }

# Checked again here though the control plane checked it: the spool file is writable by odoo.
valid_cidr() {
  local address=${1%/*} size=${1##*/}
  [[ $1 == */* && $size =~ ^[0-9]{1,3}$ ]] || return 1
  if [[ $address =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$ ]]; then
    [ "$size" -ge 16 ] && [ "$size" -le 32 ] || return 1
    local octet
    for octet in "${BASH_REMATCH[@]:1}"; do [ "$octet" -le 255 ] || return 1; done
    case ${BASH_REMATCH[1]} in 0|10|127) return 1 ;; esac
    return 0
  fi
  [[ $address =~ ^[0-9a-fA-F:]+$ && $address == *:* ]] && [ "$size" -ge 48 ] && [ "$size" -le 128 ]
}

# Verifies a bundle against its digest and the signing key. Prints nothing on success.
verify_bundle() {
  local bundle=$1 signature=$2 digest=$3
  printf '%s  %s\n' "$digest" "$bundle" | sha256sum -c --status - || { fl_warn "bundle digest differs"; return 1; }
  openssl pkeyutl -verify -pubin -inkey "$FIRM_ETC/release-signing.pub" -rawin -in "$bundle" -sigfile "$signature" >/dev/null 2>&1 \
    || { fl_warn "bundle signature refused"; return 1; }
}
