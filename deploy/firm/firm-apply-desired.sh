#!/usr/bin/env bash
# firm-apply-desired.sh: acts on what the control plane's last heartbeat answer asked.
#
#   firm-apply-desired [--dry-run]
#
# The agent, running as the odoo user, leaves the answer in the spool folder. That makes the file
# untrusted here: every value is checked again. All it can ask for is a release (which must still
# carry a signature made outside the control plane), an export, an anonymised copy (which stays on this
# server, and only if this firm allows it), and the operator's addresses on port 22 (which still need
# this firm's SSH key). It cannot run anything.

set -euo pipefail
SCRIPT_NAME=firm-apply-desired
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
# shellcheck source=deploy/firm/firm-lib.sh
. "$HERE/firm-lib.sh"
DRY_RUN=0
[ "${1:-}" != "--dry-run" ] || DRY_RUN=1
load_firm_env

SPOOL=$FIRM_SPOOL/desired.json
[ -s "$SPOOL" ] || exit 0

# One value per line, in a fixed order; anything unexpected comes out empty.
parsed=$("$ODOO_PY" -I - "$SPOOL" <<'PY'
import json
import re
import sys

with open(sys.argv[1], encoding="ascii") as handle:
    data = json.load(handle)
release = data.get("release", "")
digest = data.get("bundle_sha256", "")
allow = data.get("ssh_allowlist", [])
good = (
    isinstance(release, str) and re.fullmatch(r"[0-9a-f]{12,40}", release)
    and isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)
)
print(release if good else "")
print(digest if good else "")
print("1" if data.get("export_requested") is True else "0")
print(" ".join(allow) if isinstance(allow, list) and all(isinstance(c, str) and re.fullmatch(r"[0-9a-fA-F:./]+", c) for c in allow) else "")
ref = data.get("anon_export_ref", "")
print(ref if isinstance(ref, str) and re.fullmatch(r"[0-9a-f]{16}", ref) else "")
PY
) || fl_die "the spool file cannot be read"
{ read -r RELEASE; read -r DIGEST; read -r EXPORT; read -r ALLOW; read -r ANON_REF; } <<<"$parsed"

apply_allowlist() {
  [ -n "$ALLOW" ] || return 0
  local cidr current new
  for cidr in $ALLOW; do
    valid_cidr "$cidr" || { fl_warn "refused address for port 22: $cidr"; return 0; }
  done
  new=$(tr ' ' '\n' <<<"$ALLOW" | sort)
  current=$(sort "$FIRM_ETC/ssh_allowlist" 2>/dev/null || true)
  [ "$new" != "$current" ] || return 0
  if [ "$DRY_RUN" = 1 ]; then
    fl_log "DRY RUN: port 22 would open to: $ALLOW"
    return 0
  fi
  for cidr in $ALLOW; do ufw allow from "$cidr" to any port 22 proto tcp comment operator >/dev/null; done
  # New addresses first, so nobody is locked out half-way.
  while read -r cidr; do
    [ -n "$cidr" ] || continue
    grep -qxF "$cidr" <<<"$new" || ufw delete allow from "$cidr" to any port 22 proto tcp >/dev/null || true
  done < "$FIRM_ETC/ssh_allowlist"
  printf '%s\n' "$new" > "$FIRM_ETC/ssh_allowlist"
  printf '%s allowlist-change %s -\n' "$(now_utc)" "$(id -un)" >> "$BREAK_GLASS_LOG"
  fl_log "port 22 now opens to: $ALLOW"
}

apply_allowlist

if [ "$EXPORT" = 1 ]; then
  case "$(get_status export_state)" in
    done|running) ;;
    *)
      if [ "$DRY_RUN" = 1 ]; then
        fl_log "DRY RUN: would run firm-export"
      else
        "$BIN_DIR/firm-export.sh" || fl_warn "export failed"
      fi ;;
  esac
fi

# Once per reference, whatever the result: asking again takes a new request on the control plane.
if [ -n "$ANON_REF" ] && [ "$ANON_REF" != "$(get_status anon_export_ref)" ]; then
  if [ "$DRY_RUN" = 1 ]; then
    fl_log "DRY RUN: would run firm-anon-export $ANON_REF"
  else
    "$BIN_DIR/firm-anon-export.sh" "$ANON_REF" || fl_warn "anonymised export did not finish"
  fi
fi

if [ -n "$RELEASE" ] && [ "$RELEASE" != "$(get_status release)" ]; then
  if grep -qxF "$RELEASE" "$FIRM_VAR/refused-releases" 2>/dev/null; then
    exit 0  # Already failed here: the operator decides what comes next.
  fi
  if [ "$DRY_RUN" = 1 ]; then
    fl_log "DRY RUN: would run firm-update $RELEASE"
  else
    "$BIN_DIR/firm-update.sh" "$RELEASE" "$DIGEST" || fl_warn "update of $RELEASE did not succeed"
  fi
fi
