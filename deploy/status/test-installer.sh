#!/usr/bin/env bash
# test-installer.sh: runs install-status-pipeline.sh against a local copy of the server's layout.
#
#   deploy/status/test-installer.sh [STATUS_JSON] [INDEX_HTML] [GEN_STATUS_JS]
#
# Nothing outside a temporary folder is written. systemctl is a stand-in that runs what the drop-ins say, in
# the order systemd would: the existing generator, then the new one. A fake git remote keeps it offline.

set -uo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SANDBOX=$(mktemp -d)
PASS=0 FAIL=0
ok() { PASS=$((PASS + 1)); printf 'ok    %s\n' "$*"; }
bad() { FAIL=$((FAIL + 1)); printf 'FAIL  %s\n' "$*"; }
trap 'rm -rf "$SANDBOX"' EXIT

export STATUS_PREFIX=$SANDBOX/fs
ROOT=$STATUS_PREFIX/opt/ea-audit-status
WWW=$STATUS_PREFIX/var/www/status.auditisa.com
UNITS=$STATUS_PREFIX/etc/systemd/system
mkdir -p "$ROOT" "$WWW" "$UNITS" "$STATUS_PREFIX/root" "$SANDBOX/bin"

# A stand-in for the existing generator: writes the two files the real one writes, and leaves the rest alone.
GEN_OLD=${3:-}
if [ -n "$GEN_OLD" ] && [ -f "$GEN_OLD" ]; then cp "$GEN_OLD" "$ROOT/gen-status.js"; else echo '// stand-in' > "$ROOT/gen-status.js"; fi
printf '%s\n' "${1:-}" > "$SANDBOX/status-source"
printf '%s\n' "${2:-}" > "$SANDBOX/index-source"
cat > "$SANDBOX/fake-old-gen.sh" <<EOF
#!/usr/bin/env bash
if [ -s "\$(cat "$SANDBOX/status-source")" ]; then cp "\$(cat "$SANDBOX/status-source")" "$WWW/status.json"; else echo '{"envs":[]}' > "$WWW/status.json"; fi
if [ -s "\$(cat "$SANDBOX/index-source")" ]; then cp "\$(cat "$SANDBOX/index-source")" "$WWW/index.html"; else echo '<html>the old page</html>' > "$WWW/index.html"; fi
EOF
cp "$WWW/index.html" "$SANDBOX/x" 2>/dev/null || true
cat > "$SANDBOX/bin/systemctl" <<EOF
#!/usr/bin/env bash
echo "systemctl \$*" >> "$SANDBOX/systemctl.log"
if [ "\$1" = start ] && [ "\$2" = ea-audit-status.service ]; then
  bash "$SANDBOX/fake-old-gen.sh" || exit 1
  conf="$UNITS/ea-audit-status.service.d/pipeline.conf"
  if [ -f "\$conf" ]; then
    command=\$(sed -n 's/^ExecStartPost=-//p' "\$conf")
    # Quoted for the spaces of a test folder: the real path has none.
    node_bin=\${command%% *}; script=\${command#* }
    STATUS_WWW="$WWW" STATUS_STATE="$ROOT/pipeline" NEXT_REMOTE="$SANDBOX/next-remote.git" ODOO_DEPLOY_KEY="$STATUS_PREFIX/root/.ssh/absent" \
      STAGING_STATE_URL="file:///nonexistent" STAGING_HEALTH_URL="file:///nonexistent" "\$node_bin" "\$script" || true
  fi
fi
EOF
chmod +x "$SANDBOX/bin/systemctl"
export PATH=$SANDBOX/bin:$PATH

# An offline stand-in for GitHub.
git init -q --bare "$SANDBOX/next-remote.git"
git clone -q "$SANDBOX/next-remote.git" "$SANDBOX/next-work" 2>/dev/null
(cd "$SANDBOX/next-work" && git config user.email t@example.com && git config user.name Tester && git checkout -q -b dev && git commit -q --allow-empty -m one && git push -q origin dev && git branch main && git push -q origin main)

python3 "$HERE/build-installer.py" >/dev/null 2>&1 || python "$HERE/build-installer.py" >/dev/null
INSTALLER=$HERE/install-status-pipeline.sh
bash "$SANDBOX/fake-old-gen.sh"
BEFORE=$(cat "$WWW/index.html" | sha256sum)
GEN_BEFORE=$(sha256sum < "$ROOT/gen-status.js")

bash "$INSTALLER" check > "$SANDBOX/out" 2>&1 && ok "check runs" || { bad "check"; cat "$SANDBOX/out"; }
[ ! -e "$ROOT/gen-pipeline.js" ] && ok "check changes nothing" || bad "check changed something"

bash "$INSTALLER" install > "$SANDBOX/out" 2>&1 && ok "install runs" || { bad "install"; cat "$SANDBOX/out"; }
ls "$STATUS_PREFIX"/root/status-pipeline-backup-*.tar.gz >/dev/null 2>&1 && ok "a backup was made" || bad "no backup"
tar -tzf "$STATUS_PREFIX"/root/status-pipeline-backup-*.tar.gz | grep -q 'gen-status.js' && ok "the backup holds gen-status.js" || bad "backup content"
tar -tzf "$STATUS_PREFIX"/root/status-pipeline-backup-*.tar.gz | grep -q 'var/www/status.auditisa.com/index.html' && ok "the backup holds the old page" || bad "backup content"
grep -q 'ea-pipeline-page' "$WWW/index.html" && ok "index.html is the new page" || bad "index.html"
grep -q 'Staging' "$WWW/index.html" && ok "it shows the stages" || bad "stages"
grep -q 'Odoo' "$WWW/index.html" && ok "it shows the Odoo tool" || bad "Odoo"
[ -s "$WWW/en.html" ] && ok "en.html" || bad "en.html"
[ -s "$WWW/pipeline.json" ] && ok "pipeline.json" || bad "pipeline.json"
[ "$(sha256sum < "$WWW/details.html")" = "$BEFORE" ] && ok "details.html is the old page, unchanged" || bad "details.html"
[ "$(sha256sum < "$ROOT/gen-status.js")" = "$GEN_BEFORE" ] && ok "gen-status.js is untouched" || bad "gen-status.js changed"
grep -q 'GitHub' "$WWW/en.html" && grep -q 'not set up' "$WWW/en.html" && ok "without the deploy key the Odoo column says so" || bad "no-key message"

"$SANDBOX/bin/systemctl" start ea-audit-status.service
grep -q 'ea-pipeline-page' "$WWW/index.html" && ok "the next run gives the new page again" || bad "second run"
[ "$(sha256sum < "$WWW/details.html")" = "$BEFORE" ] && ok "details.html stays the old page" || bad "details.html after the second run"

mv "$ROOT/gen-pipeline.js" "$SANDBOX/saved"; echo 'syntax error here(' > "$ROOT/gen-pipeline.js"
"$SANDBOX/bin/systemctl" start ea-audit-status.service 2>/dev/null
[ "$(sha256sum < "$WWW/index.html")" = "$BEFORE" ] && ok "a broken new script leaves the old page in place" || bad "broken script"
mv "$SANDBOX/saved" "$ROOT/gen-pipeline.js"

bash "$INSTALLER" rollback > "$SANDBOX/out" 2>&1 && ok "rollback runs" || { bad "rollback"; cat "$SANDBOX/out"; }
[ "$(sha256sum < "$WWW/index.html")" = "$BEFORE" ] && ok "index.html is the old page again" || bad "after rollback"
[ ! -e "$UNITS/ea-audit-status.service.d/pipeline.conf" ] && ok "the service drop-in is gone" || bad "drop-in stayed"
[ ! -e "$UNITS/ea-audit-status.timer.d/pipeline.conf" ] && ok "the timer drop-in is gone" || bad "drop-in stayed"
[ ! -e "$ROOT/gen-pipeline.js" ] && [ ! -e "$ROOT/pipeline" ] && ok "the new files are gone" || bad "files stayed"
[ ! -e "$WWW/details.html" ] && [ ! -e "$WWW/en.html" ] && [ ! -e "$WWW/pipeline.json" ] && ok "the new pages are gone" || bad "pages stayed"
[ "$(sha256sum < "$ROOT/gen-status.js")" = "$GEN_BEFORE" ] && ok "gen-status.js is still untouched" || bad "gen-status.js changed"

# A generator that never writes its page: install must undo itself.
cat > "$SANDBOX/fake-old-gen.sh" <<EOF
#!/usr/bin/env bash
echo '<html>the old page</html>' > "$WWW/index.html"
EOF
sed -i 's/"\\$node_bin" "\\$script" || true/false/' "$SANDBOX/bin/systemctl"
if bash "$INSTALLER" install > "$SANDBOX/out" 2>&1; then bad "install claimed success with no new page"; else ok "install refuses when the new page does not appear"; fi
[ ! -e "$ROOT/gen-pipeline.js" ] && ok "and undoes itself" || bad "it stayed"

printf 'TOTAL: %s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" = 0 ]
