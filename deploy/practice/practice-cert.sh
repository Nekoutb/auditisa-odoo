#!/usr/bin/env bash
# practice-cert.sh: the wildcard certificate *.<practice domain>, by DNS challenge. A LATER STEP.
#
#   practice-cert --cloudflare-credentials FILE [--dry-run]
#
# Every firm's practice address (demo-akwa.practice.auditisa.com, ...) is covered by one wildcard
# certificate. Let's Encrypt gives a wildcard only through a DNS challenge: certbot writes a TXT
# record in the auditisa.com zone. That needs, from the owner (not available yet):
#   1. a DNS record: *.practice.auditisa.com -> the practice computer's address (A record)
#   2. a Cloudflare API token limited to "Zone:DNS:Edit" on auditisa.com only, in FILE:
#        dns_cloudflare_api_token = <token>
#      FILE is moved to /etc/auditisa-practice/secrets/cloudflare.ini (root, 600). It is never printed.
# Renewal is certbot's own timer, with the same credentials. Until this has run, the practice
# computer answers on port 80 only and serves no space (install-practice-server.sh).

set -euo pipefail
umask 077
SCRIPT_NAME=practice-cert
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
# shellcheck source=deploy/practice/practice-lib.sh
. "$HERE/practice-lib.sh"

CREDENTIALS="" DRY_RUN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --cloudflare-credentials) CREDENTIALS=${2:?}; shift ;;
    --dry-run) DRY_RUN=1 ;;
    *) sed -n '2,16p' "$0"; exit 64 ;;
  esac
  shift
done
load_practice_env
[ "$PRACTICE_PREVIEW" = 0 ] || pl_die "the preview uses the existing certificate of its host: nothing to do"
KEPT=$PRACTICE_SECRETS/cloudflare.ini

if [ -n "$CREDENTIALS" ]; then
  grep -Eq '^dns_cloudflare_api_token *= *[A-Za-z0-9_-]{20,}$' "$CREDENTIALS" || pl_die "$CREDENTIALS does not hold one dns_cloudflare_api_token line"
  [ "$DRY_RUN" = 1 ] || { install -m 600 "$CREDENTIALS" "$KEPT"; shred -u "$CREDENTIALS" 2>/dev/null || rm -f "$CREDENTIALS"; }
fi
if [ "$DRY_RUN" = 1 ]; then
  pl_log "DRY RUN: certbot certonly --dns-cloudflare -d '*.$PRACTICE_DOMAIN' -d $PRACTICE_DOMAIN; then the HTTPS site"
  exit 0
fi
[ -r "$KEPT" ] || pl_die "no Cloudflare credentials yet: --cloudflare-credentials FILE (see the header)"

certbot certonly --dns-cloudflare --dns-cloudflare-credentials "$KEPT" --dns-cloudflare-propagation-seconds 30 \
  --cert-name "$PRACTICE_DOMAIN" -d "*.$PRACTICE_DOMAIN" -d "$PRACTICE_DOMAIN" \
  --agree-tos --no-eff-email --register-unsafely-without-email --non-interactive --quiet \
  --deploy-hook "systemctl reload nginx"
ln -sfn /etc/nginx/sites-available/practice.conf /etc/nginx/sites-enabled/practice.conf
nginx -t -q
systemctl reload nginx
audit_line "wildcard certificate for $PRACTICE_DOMAIN"
pl_log "HTTPS is on for *.$PRACTICE_DOMAIN"
