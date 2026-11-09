#!/usr/bin/env bash
# firm-isolation.sh: this server's half of the isolation test. The operator's side is
# scripts/provision/verify_firm_isolation.sh.
#
#   firm-isolation fingerprints                         on firm B: digests of B's secrets, and B's names
#   firm-isolation check --peer FILE [--no-network]     on firm A: proves A has no way to B
#
# FIRM_PREFIX points at a rendered server folder for the rehearsal in CI (`--no-network` there).
# Digests only: this never prints a secret, and a digest of a 256-bit random value gives nothing away.
#
# `check` fails if A holds any of B's secrets, knows B's names or address, trusts B's key or
# anything but its own one key, has a tunnel or private network interface, or can open B's closed
# ports. B's ports 80 and 443 are public by design and are reported as such.

set -uo pipefail
SCRIPT_NAME=firm-isolation
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
# shellcheck source=deploy/firm/firm-lib.sh
. "$HERE/firm-lib.sh"
load_firm_env

R=$FIRM_PREFIX
SECRET_FILES=(heartbeat.token restic.key db.password master.password s3.env)
SEARCH_DIRS=("$R/etc/auditisa-firm" "$R/etc/odoo" "$R/etc/nginx" "$R/etc/ssh" "$R/root" "$R/home" "$R/opt/auditisa-firm" "$R/var/lib/auditisa-firm")

digest_values() {
  # A value file: its whole content; s3.env: its key and its secret, each on its own (the region
  # is the same for every firm and is no secret).
  local file=$1
  [ -r "$file" ] || return 0
  case "$file" in
    *.env) sed -n 's/^AWS_\(ACCESS_KEY_ID\|SECRET_ACCESS_KEY\)=//p' "$file" | while read -r value; do printf '%s' "$value" | sha256sum | cut -d' ' -f1; done ;;
    *) tr -d '\n' < "$file" | sha256sum | cut -d' ' -f1 ;;
  esac
}

cmd_fingerprints() {
  local name
  printf 'slug %s\n' "$FIRM_SLUG"
  printf 'host %s\n' "$FIRM_HOST"
  printf 'db %s\n' "$FIRM_DB"
  if [ -z "$R" ]; then printf 'ip %s\n' "$(curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null || true)"; fi
  for name in "${SECRET_FILES[@]}"; do
    digest_values "$FIRM_SECRETS/$name" | sed 's/^/secret /'
  done
  sed -n 's/^ssh-ed25519 \([^ ]*\).*/key \1/p' "$R/root/.ssh/authorized_keys"
}

FAILED=0
pass() { printf 'ok      %s\n' "$*"; }
fail() { printf 'FAILED  %s\n' "$*"; FAILED=$((FAILED + 1)); }

check_credentials() {
  local peer=$1 digest name own hit=0
  own=$(mktemp)
  for name in "${SECRET_FILES[@]}"; do digest_values "$FIRM_SECRETS/$name" >> "$own"; done
  while read -r digest; do
    if grep -qxF "$digest" "$own"; then fail "this server holds a secret of the peer"; hit=1; fi
  done < <(sed -n 's/^secret //p' "$peer")
  rm -f "$own"
  [ "$hit" = 1 ] || pass "none of the peer's secrets is among this server's"

  local secret_copy
  secret_copy=$(mktemp)
  find "${SEARCH_DIRS[@]}" -type f -size -256k 2>/dev/null | while read -r file; do
    tr -cs 'A-Za-z0-9_+/=-' '\n' < "$file" 2>/dev/null | grep -E '^.{20,}$' | while read -r word; do
      printf '%s' "$word" | sha256sum | cut -d' ' -f1
    done
  done | sort -u > "$secret_copy"
  hit=0
  while read -r digest; do
    if grep -qxF "$digest" "$secret_copy"; then fail "a file on this server holds a secret of the peer"; hit=1; fi
  done < <(sed -n 's/^secret //p' "$peer")
  rm -f "$secret_copy"
  [ "$hit" = 1 ] || pass "no file here holds any of the peer's secrets"
}

check_names() {
  local peer=$1 kind word found=0
  while read -r kind word; do
    case "$kind" in
      slug|host|db|ip) ;;
      *) continue ;;
    esac
    [ -n "$word" ] || continue
    # A folder that does not exist makes grep exit 2 even after a match: its output decides.
    if [ -n "$(grep -RIlwF -- "$word" "${SEARCH_DIRS[@]}" 2>/dev/null || true)" ]; then
      fail "this server's files mention the peer's $kind ($word)"
      found=1
    fi
  done < "$peer"
  [ "$found" = 1 ] || pass "nothing here names the peer"
}

check_keys() {
  local peer=$1 auth=$R/root/.ssh/authorized_keys count key
  count=$(grep -c '^[^#]' "$auth" 2>/dev/null || true)
  if [ "$count" = 1 ]; then pass "root trusts exactly one SSH key"; else fail "root trusts $count SSH keys, expected 1"; fi
  key=$(sed -n 's/^key //p' "$peer" | head -n 1)
  if [ -n "$key" ] && grep -qF -- "$key" "$auth" 2>/dev/null; then
    fail "root trusts the peer's SSH key"
  else
    pass "the peer's key opens nothing here"
  fi
  local private
  private=$(grep -RIl -- 'PRIVATE KEY-----' "$R/root" "$R/home" "$R/etc/auditisa-firm" 2>/dev/null | head -n 3)
  if [ -z "$private" ]; then pass "no private SSH key on this server"; else fail "private key found: $private"; fi
}

check_database_exposure() {
  local conf
  conf=$(find "$R/etc/postgresql" -name auditisa.conf 2>/dev/null | head -n 1)
  if [ -n "$conf" ] && grep -q "^listen_addresses = 'localhost'" "$conf"; then
    pass "PostgreSQL listens on this machine only"
  else
    fail "PostgreSQL's listen address is not restricted"
  fi
  if grep -q '^http_interface = 127.0.0.1' "$R/etc/odoo/odoo.conf" 2>/dev/null \
    && grep -q '^list_db = False' "$R/etc/odoo/odoo.conf" 2>/dev/null; then
    pass "Odoo listens on this machine only, with no database list"
  else
    fail "Odoo's configuration is not restricted"
  fi
  if grep -E '^allow 22/tcp( from (0\.0\.0\.0/0|::/0|any))?$' "$R/etc/auditisa-firm/firewall.rules" >/dev/null 2>&1; then
    fail "port 22 is open to everyone"
  else
    pass "port 22 is restricted to the allow-list"
  fi
}

check_routes() {
  local peer=$1 links ip
  links=$(ip -o link show 2>/dev/null | awk -F': ' '{print $2}' | grep -E '^(wg|tun|tap|vpc|vxlan|gre|ipip)' || true)
  if [ -z "$links" ]; then pass "no tunnel or private network interface"; else fail "tunnel or private interface: $links"; fi
  ip=$(sed -n 's/^ip //p' "$peer" | head -n 1)
  if [ -z "$ip" ]; then
    printf 'NOTE    the peer address is unknown: route not checked\n'
    return
  fi
  if ip route get "$ip" 2>/dev/null | grep -q ' via '; then
    pass "the peer is reached only through the public gateway"
  else
    fail "a direct route leads to the peer"
  fi
}

check_ports() {
  local peer=$1 ip port
  ip=$(sed -n 's/^ip //p' "$peer" | head -n 1)
  [ -n "$ip" ] || { fail "the peer address is unknown: ports not checked"; return; }
  for port in 22 5432 8069 8072; do
    if timeout 5 bash -c ": > /dev/tcp/$ip/$port" 2>/dev/null; then
      fail "port $port of the peer answers from here"
    else
      pass "port $port of the peer is closed from here"
    fi
  done
  printf 'NOTE    ports 80 and 443 of the peer are public by design: they lead to a login page\n'
}

cmd_check() {
  local peer="" network=1
  while [ $# -gt 0 ]; do
    case "$1" in
      --peer) peer=${2:?}; shift ;;
      --no-network) network=0 ;;
      *) fl_die "unknown option $1" ;;
    esac
    shift
  done
  [ -r "$peer" ] || fl_die "--peer FILE is required"
  [ "$(sed -n 's/^slug //p' "$peer")" != "$FIRM_SLUG" ] || fl_die "the peer is this firm"
  check_credentials "$peer"
  check_names "$peer"
  check_keys "$peer"
  check_database_exposure
  if [ "$network" = 1 ]; then
    check_routes "$peer"
    check_ports "$peer"
  else
    printf 'NOT CHECKED  routes and ports (--no-network): a rehearsal on rendered files\n'
  fi
  if [ "$FAILED" = 0 ]; then
    printf 'ISOLATED: %s has no credential, name or path to the peer\n' "$FIRM_SLUG"
  else
    printf 'NOT ISOLATED: %s problem(s)\n' "$FAILED"
    exit 1
  fi
}

case "${1:-}" in
  fingerprints) cmd_fingerprints ;;
  check) shift; cmd_check "$@" ;;
  *) sed -n '2,12p' "$0"; exit 64 ;;
esac
