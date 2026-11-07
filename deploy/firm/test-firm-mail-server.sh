#!/usr/bin/env bash
# Tests firm-mail-server.sh for real, as root, on a throwaway database that has ea_audit_timesheet.
#
#   test-firm-mail-server.sh --db ci_xxx --conf /path/to/odoo.conf
#
# Never on a firm's or staging's database: the name must start with ci_. The server it sets is
# smtp.example.invalid, which does not resolve: nothing is ever sent, and the test of the
# connection must fail, leaving sending off. Checks that the password reaches Odoo and never the
# output, that a loose file or a bad value is refused, and that a test environment is refused.
set -euo pipefail

DB=''
CONF=''
while [ $# -gt 0 ]; do
  case "$1" in
    --db) DB=$2; shift 2 ;;
    --conf) CONF=$2; shift 2 ;;
    *) echo "usage: $0 --db ci_xxx --conf odoo.conf" >&2; exit 2 ;;
  esac
done
[[ $DB =~ ^ci_[a-z0-9_]+$ ]] || { echo "the database must be a throwaway ci_ one" >&2; exit 2; }
[ -r "$CONF" ] || { echo "no odoo.conf" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 2; }

HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
chmod 711 "$WORK"
export FIRM_PREFIX=$WORK/root ODOO_CONF=$CONF
mkdir -p "$FIRM_PREFIX/etc/auditisa-firm/secrets" "$FIRM_PREFIX/var/log/auditisa-firm"
printf 'FIRM_SLUG=ci\nFIRM_HOST=ci.example.invalid\nFIRM_DB=%s\n' "$DB" > "$FIRM_PREFIX/etc/auditisa-firm/firm.env"
MAIL=$FIRM_PREFIX/etc/auditisa-firm/secrets/mail.env
PW="Pw-$(openssl rand -hex 12)=x"
SCRIPT=$HERE/firm-mail-server.sh

fail() { printf 'FAILED: %s\n' "$*" >&2; exit 1; }
q() { runuser -u postgres -- psql -XAt -d "$DB" -c "$1"; }
write_mail() { # $1 = extra lines
  rm -f "$MAIL"
  printf 'MAIL_HOST=smtp.example.invalid\nMAIL_PORT=587\nMAIL_ENCRYPTION=starttls\nMAIL_USER=cabinet@example.invalid\nMAIL_PASSWORD=%s\nMAIL_FROM=cabinet@example.invalid\n%s' "$PW" "${1:-}" > "$MAIL"
  chmod 600 "$MAIL"
}
# runs the script; its output (both streams) goes to $WORK/out, never holding the password
run() { set +e; bash "$SCRIPT" "$@" > "$WORK/out" 2>&1; local rc=$?; set -e; if grep -qF -- "$PW" "$WORK/out"; then fail "the password was printed"; fi; return $rc; }
refused() { local why=$1; shift; if run "$@"; then fail "accepted: $why"; fi; grep -q "refused\|ERROR" "$WORK/out" || fail "no reason given: $why"; echo "ok: refused $why"; }

echo "== the file itself"
write_mail; chmod 644 "$MAIL"; refused "a file others can read"
write_mail; chown nobody "$MAIL"; refused "a file of another user"
write_mail "MAIL_DEBUG=1"$'\n'; refused "an unknown setting"
write_mail "MAIL_PASSWORD=again"$'\n'; refused "a setting given twice"
for bad in "MAIL_HOST=10.0.0.5" "MAIL_HOST=localhost" "MAIL_HOST=169.254.169.254" "MAIL_PORT=22" "MAIL_ENCRYPTION=none" "MAIL_FROM=not an address"; do
  write_mail; sed -i "s|^${bad%%=*}=.*|$bad|" "$MAIL"; refused "$bad"
done
write_mail; sed -i "s|^MAIL_HOST=.*|MAIL_HOST$PW|" "$MAIL"; refused "a line without = holding the password"
ln -s "$MAIL" "$WORK/link.env"; write_mail; refused "a symbolic link" "$WORK/link.env"

echo "== dry run"
write_mail
run --dry-run || fail "the dry run failed: $(cat "$WORK/out")"
grep -q "DRY RUN.*smtp.example.invalid:587 STARTTLS" "$WORK/out" || fail "the dry run does not say what it would do"
[ -z "$(q "SELECT id FROM ir_mail_server")" ] || fail "the dry run wrote a server"
echo "ok: dry run, nothing written"

echo "== real run: saved, tested (fails: the host does not resolve), sending stays off"
if run; then fail "sending went on with a host that does not exist"; fi
grep -q "sending stays off" "$WORK/out" || fail "unexpected: $(cat "$WORK/out")"
row=$(q "SELECT smtp_host, smtp_port, smtp_encryption, smtp_user, from_filter, active FROM ir_mail_server WHERE name = 'Firm server'")
[ "$row" = "smtp.example.invalid|587|starttls|cabinet@example.invalid|cabinet@example.invalid|f" ] || fail "server row: $row"
[ "$(q "SELECT md5(smtp_pass) FROM ir_mail_server WHERE name = 'Firm server'")" = "$(printf '%s' "$PW" | md5sum | cut -d' ' -f1)" ] \
  || fail "the password did not reach Odoo intact"
grep -q "mail-server-set" "$FIRM_PREFIX/var/log/auditisa-firm/break-glass.log" || fail "no line in the access log"
[ "$(q "SELECT count(*) FROM ea_audit_firm_log WHERE kind IN ('mail_saved', 'mail_tested')")" -ge 2 ] || fail "not in the firm's log"
if q "SELECT detail FROM ea_audit_firm_log" | grep -qF -- "$PW"; then fail "the password is in the firm's log"; fi
echo "ok: saved and off, password stored and never printed"

echo "== a test environment is refused"
q "INSERT INTO ir_config_parameter (key, value) VALUES ('ea_audit.staging_band', '1') ON CONFLICT (key) DO UPDATE SET value = '1'" >/dev/null
write_mail; sed -i "s|^MAIL_HOST=.*|MAIL_HOST=smtp2.example.invalid|" "$MAIL"
if run; then fail "ran on a test environment"; fi
grep -q "test environment" "$WORK/out" || fail "unexpected: $(cat "$WORK/out")"
[ "$(q "SELECT smtp_host FROM ir_mail_server WHERE name = 'Firm server'")" = smtp.example.invalid ] || fail "a test environment's server changed"
echo "ok: test environment refused"

echo "All firm-mail-server tests passed"
