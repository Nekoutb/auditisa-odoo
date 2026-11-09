#!/usr/bin/env bash
# shellcheck disable=SC2034  # used by the scripts that source this file
# firm-lib.sh: what the firm server's scripts share. Sourced, never run.
#
# FIRM_PREFIX is empty on a real server. The dry runs set it to a folder, so that nothing outside
# that folder is ever written.
#
# Layout on the server:
#   /etc/auditisa-firm/firm.env            who this server is (no secret)
#   /etc/auditisa-firm/secrets/            heartbeat.token (root:odoo 640), restic.key, s3.env (root 600)
#   /etc/auditisa-firm/trusted-signers/    the signers a release bundle must be signed by (release_trust.py)
#   /etc/auditisa-firm/release-signing.pub the first of them, for older scripts; the only key before the list
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
# The signers this server trusts for new releases: see release_trust.py and adopt_trust below.
FIRM_TRUST=$FIRM_ETC/trusted-signers
TRUST_PY=${TRUST_PY:-$ODOO_PY}

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
valid_anon_ref() { [[ $1 =~ ^[0-9a-f]{16}$ ]]; }

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

# The keys that may vouch for a bundle with this digest: every signer this server trusts, and a REMOVED
# signer only for a bundle it signed while trusted (its .only file). With no list yet (a server set up
# before the list existed), the one key of before. The list changes only through adopt_trust.
trusted_keys() {
  local digest=$1 key only found=0
  for key in "$FIRM_TRUST"/*.pub; do
    [ -f "$key" ] || continue
    found=1
    only=${key%.pub}.only
    if [ -e "$only" ] && ! grep -qxF "$digest" "$only"; then continue; fi
    printf '%s\n' "$key"
  done
  [ "$found" = 1 ] || printf '%s\n' "$FIRM_ETC/release-signing.pub"
}

# Verifies a bundle against its digest and the trusted signers. Prints nothing on success; sets
# SIGNED_BY to the fingerprint of the signer whose key matched (or "release-signing").
verify_bundle() {
  local bundle=$1 signature=$2 digest=$3 key
  SIGNED_BY=""
  printf '%s  %s\n' "$digest" "$bundle" | sha256sum -c --status - || { fl_warn "bundle digest differs"; return 1; }
  while IFS= read -r key; do
    [ -n "$key" ] || continue
    if openssl pkeyutl -verify -pubin -inkey "$key" -rawin -in "$bundle" -sigfile "$signature" >/dev/null 2>&1; then
      SIGNED_BY=$(basename "$key" .pub)
      return 0
    fi
  done < <(trusted_keys "$digest")
  fl_warn "bundle signature refused: not signed by a signer this server trusts"
  return 1
}

# Takes the list of signers that a release carries (deploy/trust/signers.json) if it is newer than the
# one in use. ONLY for a release this server has verified: the one in use, or the one firm-update has
# just checked. Never fails the caller: a refused list leaves the list in use as it was.
adopt_trust() {
  local release=$1 out
  [ -f "$release/deploy/trust/signers.json" ] && [ -f "$release/deploy/firm/release_trust.py" ] || return 0
  if ! out=$("$TRUST_PY" -I "$release/deploy/firm/release_trust.py" adopt "$release/deploy/trust/signers.json" \
      "$FIRM_TRUST" --legacy "$FIRM_ETC/release-signing.pub"); then
    fl_warn "the signer list carried by $(basename "$release") was refused; the list in use stays"
    return 0
  fi
  set_status signers_serial "${out##* }"
  case $out in
    adopted*) fl_log "trusted signers: list number ${out##* } taken from release $(basename "$release")" ;;
  esac
  return 0
}
