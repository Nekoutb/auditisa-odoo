#!/usr/bin/env bash
# test-redirect.sh: redirect-status-site.sh against a local copy of a vhost. Nothing outside a temporary folder.
# The vhost below follows the layout of the server's other vhosts; the real one was not readable when this was
# written, so run `check` on the server first.

set -uo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SANDBOX=$(mktemp -d)
trap 'rm -rf "$SANDBOX"' EXIT
PASS=0 FAIL=0
ok() { PASS=$((PASS + 1)); printf 'ok    %s\n' "$*"; }
bad() { FAIL=$((FAIL + 1)); printf 'FAIL  %s\n' "$*"; }

export STATUS_PREFIX=$SANDBOX/fs SKIP_TARGET_CHECK=1
SITES=$STATUS_PREFIX/etc/apache2/sites-available
mkdir -p "$SITES" "$STATUS_PREFIX/root" "$SANDBOX/bin"
cat > "$SITES/status.auditisa.com.conf" <<'EOF'
<VirtualHost *:80>
    ServerName status.auditisa.com
    DocumentRoot /var/www/status.auditisa.com
    Header always set X-Robots-Tag "noindex, nofollow"
    Header always set Cache-Control "no-store"
</VirtualHost>
EOF
cp "$SITES/status.auditisa.com.conf" "$SANDBOX/original.conf"
cat > "$SANDBOX/bin/apachectl" <<EOF
#!/usr/bin/env bash
echo "apachectl \$*" >> "$SANDBOX/apachectl.log"
[ -e "$SANDBOX/refuse" ] && [ "\$1" = configtest ] && exit 1
exit 0
EOF
chmod +x "$SANDBOX/bin/apachectl"
export APACHECTL=$SANDBOX/bin/apachectl
S=$HERE/redirect-status-site.sh

bash "$S" check > "$SANDBOX/out" 2>&1 && grep -q "would add" "$SANDBOX/out" && ok "check names the vhost" || bad "check"
cmp -s "$SITES/status.auditisa.com.conf" "$SANDBOX/original.conf" && ok "check changes nothing" || bad "check changed the vhost"
if bash "$S" apply http://example.com > /dev/null 2>&1; then bad "a plain-http target was accepted"; else ok "a plain-http target is refused"; fi
if bash "$S" apply 'https://x.com/a b' > /dev/null 2>&1; then bad "a target with a space was accepted"; else ok "an odd target is refused"; fi

bash "$S" apply https://www.auditisa.com/admin > "$SANDBOX/out" 2>&1 && ok "apply runs" || { bad "apply"; cat "$SANDBOX/out"; }
grep -q 'RedirectMatch 302 \^/(?!status\\\.json\$) https://www.auditisa.com/admin' "$SITES/status.auditisa.com.conf" && ok "the redirect spares /status.json" || { bad "redirect line"; cat "$SITES/status.auditisa.com.conf"; }
grep -q 'ServerName status.auditisa.com' "$SITES/status.auditisa.com.conf" && grep -q 'X-Robots-Tag' "$SITES/status.auditisa.com.conf" && ok "the rest of the vhost is kept" || bad "vhost damaged"
ls -d "$STATUS_PREFIX"/root/status-redirect-backup-* >/dev/null 2>&1 && ok "a backup was made" || bad "no backup"
grep -q graceful "$SANDBOX/apachectl.log" && ok "Apache was tested and reloaded" || bad "no reload"
bash "$S" apply https://www.auditisa.com/admin > /dev/null 2>&1
[ "$(grep -c RedirectMatch "$SITES/status.auditisa.com.conf")" = 1 ] && ok "running it twice adds nothing" || bad "redirect added twice"

bash "$S" rollback > "$SANDBOX/out" 2>&1 && ok "rollback runs" || { bad "rollback"; cat "$SANDBOX/out"; }
cmp -s "$SITES/status.auditisa.com.conf" "$SANDBOX/original.conf" && ok "the vhost is as it was" || bad "not restored"

touch "$SANDBOX/refuse"
if bash "$S" apply https://www.auditisa.com/admin > /dev/null 2>&1; then bad "went on though Apache refused"; else ok "stops when Apache refuses the configuration"; fi
cmp -s "$SITES/status.auditisa.com.conf" "$SANDBOX/original.conf" && ok "and the vhost is as it was" || bad "left changed"

printf 'TOTAL: %s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" = 0 ]
