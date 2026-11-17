#!/usr/bin/env bash
# set-mail-token.sh: gives the console one of the two tokens of the sending service for firms. As root.
#
#   set-mail-token.sh mailersend      the MailerSend API token
#   set-mail-token.sh cloudflare      the Cloudflare API token for the parent domain's zone (cm-ea.com)
#
# The token is typed (or pasted) at a prompt that does not show it, or read from stdin when it is not a
# terminal. It goes to a file only root can read (/etc/auditisa-platform/<name>.token, 600), never on a
# command line, never echoed, never in a log. systemd hands the console a private copy (LoadCredential),
# like the Vultr, Cloudflare and Wasabi tokens: Odoo stores no token. The console then restarts (a few
# seconds). See docs/runbook/PLATFORM-EMAIL.md.

set -euo pipefail
umask 077
ETC=/etc/auditisa-platform
DROPIN=/etc/systemd/system/odoo.service.d/platform-mail.conf
die() { printf 'ERROR: %s\n' "$*" >&2; exit 64; }
case "${1:-}" in
  mailersend) FILE=$ETC/mailersend.token ;;
  cloudflare) FILE=$ETC/cloudflare-mail.token ;;
  -h|--help|"") sed -n '2,11p' "$0"; exit 0 ;;
  *) die "mailersend or cloudflare" ;;
esac
[ "$(id -u)" = 0 ] || die "run as root"
[ -d "$ETC" ] || die "$ETC is missing: is this the console?"
if [ -t 0 ]; then
  printf 'Paste the token, then press Enter (it is not shown): ' >&2
  IFS= read -rs TOKEN
  printf '\n' >&2
else
  IFS= read -r TOKEN || true
fi
TOKEN=${TOKEN//[[:space:]]/}
[ -n "$TOKEN" ] || die "no token given: nothing changed"
[ ${#TOKEN} -le 512 ] || die "this is too long for a token: nothing changed"
[[ $TOKEN =~ ^[A-Za-z0-9._~+/=-]+$ ]] || die "a token has letters, digits and . _ - ~ + / = only: nothing changed"
tmp=$(mktemp "$ETC/.token.XXXXXX")
printf '%s\n' "$TOKEN" > "$tmp"
unset TOKEN
chown root:root "$tmp"
chmod 600 "$tmp"
mv -f "$tmp" "$FILE"
# Both files exist (an empty one until given): LoadCredential refuses to start the service without them.
for name in mailersend.token cloudflare-mail.token; do
  [ -e "$ETC/$name" ] || install -m 600 -o root -g root /dev/null "$ETC/$name"
done
# A console installed before 2026-11-18 does not hand these two to Odoo yet: a drop-in adds them.
if ! systemctl cat odoo 2>/dev/null | grep -q '^LoadCredential=mailersend-token:'; then
  mkdir -p "$(dirname "$DROPIN")"
  printf '[Service]\nLoadCredential=mailersend-token:%s/mailersend.token\nLoadCredential=cloudflare-mail-token:%s/cloudflare-mail.token\n' \
    "$ETC" "$ETC" > "$DROPIN"
  chmod 644 "$DROPIN"
fi
systemctl daemon-reload
systemctl restart odoo
printf 'Saved. The console restarted: open Platform > Settings and click "Test the connection".\n'
