#!/usr/bin/env bash
# verify_firm_isolation.sh: proves firm A's server has no credentials, routes or firewall path to B.
#
#   verify_firm_isolation.sh --a root@A --key-a KEY --b root@B --key-b KEY    on two real servers
#   verify_firm_isolation.sh --rehearse DIR_A DIR_B                           on two rendered servers
#
# Real mode needs two firms' keys, so it runs from the owner's machine, where they are. It logs in
# to both, which counts as a break-glass access on both: record them on the control plane first.
# It checks both directions. Only digests of B's secrets travel, never the secrets.
#
# Rehearsal mode uses folders rendered by `install-firm-server.sh --dry-run` and proves the check
# itself: it passes on two clean firms and must fail on each planted fault. Routes and ports cannot
# be checked there, and the output says so.

set -euo pipefail
umask 077
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ISOLATION=$HERE/../../deploy/firm/firm-isolation.sh

die() { printf '[isolation] ERROR: %s\n' "$*" >&2; exit 1; }

in_folder() {
  local folder=$1
  shift
  FIRM_PREFIX=$folder bash "$ISOLATION" "$@"
}

must_fail() {
  local what=$1 folder=$2 peer=$3
  if in_folder "$folder" check --peer "$peer" --no-network >/dev/null; then
    die "the check did not notice: $what"
  fi
  printf 'caught  %s\n' "$what"
}

rehearse() {
  local a=$1 b=$2 work
  work=$(mktemp -d)
  trap 'rm -rf "$work"' EXIT
  in_folder "$a" fingerprints > "$work/a.peer"
  in_folder "$b" fingerprints > "$work/b.peer"
  in_folder "$a" check --peer "$work/b.peer" --no-network
  in_folder "$b" check --peer "$work/a.peer" --no-network

  printf '\nThe check must catch each planted fault:\n'
  local copy=$work/a
  reset_copy() { rm -rf "$copy"; cp -a "$a" "$copy"; }

  reset_copy
  cp "$b/etc/auditisa-firm/secrets/heartbeat.token" "$copy/etc/auditisa-firm/secrets/restic.key"
  must_fail "B's heartbeat token used as A's backup key" "$copy" "$work/b.peer"

  reset_copy
  mkdir -p "$copy/root/notes"
  cat "$b/etc/auditisa-firm/secrets/db.password" > "$copy/root/notes/forgotten.txt"
  must_fail "B's database password left in a file on A" "$copy" "$work/b.peer"

  reset_copy
  cat "$b/root/.ssh/authorized_keys" >> "$copy/root/.ssh/authorized_keys"
  must_fail "B's key added to A's authorized keys" "$copy" "$work/b.peer"

  reset_copy
  printf 'proxy_pass https://%s;\n' "$(sed -n 's/^host //p' "$work/b.peer")" >> "$copy/etc/nginx/sites-available/firm-http.conf"
  must_fail "B's address in A's nginx" "$copy" "$work/b.peer"

  reset_copy
  mkdir -p "$copy/root/.ssh"
  printf -- '-----BEGIN OPENSSH PRIVATE KEY-----\nx\n' > "$copy/root/.ssh/id_ed25519"
  must_fail "a private key left on A" "$copy" "$work/b.peer"

  reset_copy
  sed -i 's/^listen_addresses.*/listen_addresses = '"'"'*'"'"'/' "$(find "$copy/etc/postgresql" -name auditisa.conf)"
  must_fail "PostgreSQL opened to the network" "$copy" "$work/b.peer"

  reset_copy
  printf 'allow 22/tcp from 0.0.0.0/0\n' >> "$copy/etc/auditisa-firm/firewall.rules"
  must_fail "port 22 opened to everyone" "$copy" "$work/b.peer"

  printf '\nREHEARSAL PASSED. Routes and real firewall paths were NOT tested: that needs two real servers.\n'
}

real() {
  local a="" key_a="" b="" key_b=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --a) a=${2:?}; shift ;;
      --key-a) key_a=${2:?}; shift ;;
      --b) b=${2:?}; shift ;;
      --key-b) key_b=${2:?}; shift ;;
      *) die "unknown option $1" ;;
    esac
    shift
  done
  [ -n "$a" ] && [ -n "$key_a" ] && [ -n "$b" ] && [ -n "$key_b" ] || die "--a, --key-a, --b and --key-b are required"
  local work rc=0
  work=$(mktemp -d)
  trap 'rm -rf "$work"' EXIT
  on() { local target=$1 key=$2; shift 2; ssh -i "$key" -o IdentitiesOnly=yes -o BatchMode=yes "$target" "$@"; }

  on "$a" "$key_a" firm-isolation fingerprints > "$work/a.peer"
  on "$b" "$key_b" firm-isolation fingerprints > "$work/b.peer"
  # shellcheck disable=SC2016  # expanded on the remote side
  on "$a" "$key_a" 'cat > /run/firm-peer && firm-isolation check --peer /run/firm-peer; rc=$?; rm -f /run/firm-peer; exit $rc' < "$work/b.peer" || rc=1
  # shellcheck disable=SC2016  # expanded on the remote side
  on "$b" "$key_b" 'cat > /run/firm-peer && firm-isolation check --peer /run/firm-peer; rc=$?; rm -f /run/firm-peer; exit $rc' < "$work/a.peer" || rc=1
  exit "$rc"
}

case "${1:-}" in
  --rehearse) [ $# = 3 ] || die "--rehearse DIR_A DIR_B"; rehearse "$2" "$3" ;;
  --a) real "$@" ;;
  *) sed -n '2,13p' "$0"; exit 64 ;;
esac
