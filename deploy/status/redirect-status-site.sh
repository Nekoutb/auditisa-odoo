#!/usr/bin/env bash
# redirect-status-site.sh: status.auditisa.com sends people to the control room. For the owner, on the production
# VPS, when the owner chooses. The admin Odoo has its own computer since 2026-11-08 (console.auditisa.com).
#
#   bash redirect-status-site.sh check                   what would change; changes nothing (the default)
#   bash redirect-status-site.sh apply  [TARGET_URL]      backs up, redirects, tests, undoes itself on failure
#   bash redirect-status-site.sh rollback                 the vhost as it was
#
# TARGET_URL is where people go: by default the console's Status tab, https://console.auditisa.com/odoo/status.
# It must answer before anything changes.
#
# What changes: the Apache vhost(s) of status.auditisa.com get one RedirectMatch, for every address but one.
# /status.json keeps being served, unchanged, because the control room reads the current tool's figures from it
# (deploy/control-plane/pipeline-collect.py keeps figures only). The generator gen-status.js and its timer stay,
# for that reason: retiring them would stop those figures. Nothing else on the server is touched.
# Backup: /root/status-redirect-backup-<stamp>/, root only.

set -euo pipefail
umask 077

: "${STATUS_PREFIX:=}"
SITES=$STATUS_PREFIX/etc/apache2/sites-available
BACKUPS=$STATUS_PREFIX/root
APACHECTL=${APACHECTL:-apachectl}
MARK='# ea-status-redirect'

log() { printf '[status-redirect] %s\n' "$*"; }
die() { printf '[status-redirect] ERROR: %s\n' "$*" >&2; exit 1; }

COMMAND=${1:-check}
DEFAULT_TARGET=https://console.auditisa.com/odoo/status
TARGET=${2:-$DEFAULT_TARGET}

restore() {
  local copy original
  while IFS=$'	' read -r copy original; do
    [ -n "$copy" ] && cp -p "$copy" "$original"
  done < "$BACKUPS/.status-redirect-last"
}

vhosts() { grep -l -E '^\s*ServerName\s+status\.auditisa\.com\s*$' "$SITES"/*.conf 2>/dev/null || true; }

case "$COMMAND" in
  check)
    files=$(vhosts)
    [ -n "$files" ] || die "no vhost with ServerName status.auditisa.com in $SITES"
    log "nothing is changed by this command"
    for f in $files; do
      if grep -qF "$MARK" "$f"; then log "already redirected: $f"; else log "would add a redirect to: $f"; fi
    done
    ;;
  apply)
    [[ $TARGET =~ ^https://[a-z0-9.-]+\.[a-z]{2,}(/[A-Za-z0-9._/-]*)?$ ]] || die "TARGET_URL must be a plain https address"
    [ -z "$STATUS_PREFIX" ] && [ "$(id -u)" != 0 ] && die "run as root"
    files=$(vhosts)
    [ -n "$files" ] || die "no vhost with ServerName status.auditisa.com in $SITES"
    if [ -z "${SKIP_TARGET_CHECK:-}" ]; then
      code=$(curl -s -o /dev/null -m 20 -w '%{http_code}' "$TARGET" || true)
      case "$code" in 2??|3??|401|403) ;; *) die "$TARGET does not answer (HTTP ${code:-none}): the control room is not there yet" ;; esac
    fi
    todo=0
    for f in $files; do grep -qF "$MARK" "$f" || todo=1; done
    if [ "$todo" = 0 ]; then
      log "already redirected: nothing to do"
      exit 0
    fi
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    mkdir -p "$BACKUPS/status-redirect-backup-$stamp"
    chmod 700 "$BACKUPS/status-redirect-backup-$stamp"
    : > "$BACKUPS/.status-redirect-last"
    n=0
    for f in $files; do
      n=$((n + 1))
      cp -p "$f" "$BACKUPS/status-redirect-backup-$stamp/$n.conf"
      printf '%s	%s
' "$BACKUPS/status-redirect-backup-$stamp/$n.conf" "$f" >> "$BACKUPS/.status-redirect-last"
    done
    log "backup: $BACKUPS/status-redirect-backup-$stamp"
    undo() {
      log "undoing"
      restore
      $APACHECTL configtest >/dev/null 2>&1 && $APACHECTL graceful >/dev/null 2>&1 || true
    }
    for f in $files; do
      grep -qF "$MARK" "$f" && continue
      # Right after ServerName: everything but the figures file goes to the control room.
      sed -i -E "/^\s*ServerName\s+status\.auditisa\.com\s*$/a\\
    $MARK\\
    RedirectMatch 302 ^/(?!status\\\\.json\$) $TARGET" "$f"
    done
    if ! $APACHECTL configtest >/dev/null 2>&1; then undo; die "Apache refused the configuration: put back as it was"; fi
    $APACHECTL graceful >/dev/null 2>&1 || { undo; die "Apache did not reload: put back as it was"; }
    log "status.auditisa.com now redirects to $TARGET; /status.json is still served. To go back: bash $0 rollback"
    ;;
  rollback)
    [ -z "$STATUS_PREFIX" ] && [ "$(id -u)" != 0 ] && die "run as root"
    [ -r "$BACKUPS/.status-redirect-last" ] || die "no backup recorded"
    restore
    $APACHECTL configtest >/dev/null 2>&1 || die "Apache refuses the restored configuration: check by hand"
    $APACHECTL graceful >/dev/null 2>&1
    log "the vhost is as it was, from $(head -n 1 "$BACKUPS/.status-redirect-last" | cut -f1 | xargs dirname)"
    ;;
  *) sed -n '2,10p' "$0"; exit 64 ;;
esac
