#!/usr/bin/env bash
# firm-apply-desired.sh: acts on what the control plane's last heartbeat answer asked.
#
#   firm-apply-desired [--dry-run]
#
# The agent, running as the odoo user, leaves the answer in the spool folder. That makes the file
# untrusted here: every value is checked again. All it can ask for is a release (which must still
# carry a signature made outside the control plane), an export, the operator's addresses on
# port 22 (which still need this firm's SSH key), and which optional add-ons to switch on (which
# firm-addons checks against the manifests of the signed release in use). It cannot run anything.

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
import base64
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
# Absent means no request, which changes nothing; an empty list means every add-on off.
addons = data.get("addons")
addons_good = (
    isinstance(addons, list) and len(addons) <= 24
    and all(isinstance(c, str) and re.fullmatch(r"[a-z][a-z0-9_]{2,39}", c) for c in addons)
)
print(" ".join(addons) if addons_good else "")
visit = data.get("support_visit")
visit_good = (
    isinstance(visit, dict) and set(visit) == {"id", "minutes", "token_sha256", "operator", "reason"}
    and type(visit["id"]) is int and 0 < visit["id"] < 10 ** 9
    and type(visit["minutes"]) is int and 1 <= visit["minutes"] <= 240
    and isinstance(visit["token_sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", visit["token_sha256"])
    and isinstance(visit["operator"], str) and re.fullmatch(r"[\w .'-]{1,64}", visit["operator"])
    and isinstance(visit["reason"], str) and 0 < len(visit["reason"]) <= 500
)
# Handed on as base64 of JSON: the operator's name and the reason are text, never code.
print(base64.b64encode(json.dumps(visit, sort_keys=True).encode()).decode() if visit_good else "")
ended = data.get("support_visit_end")
print(ended if type(ended) is int and 0 < ended < 10 ** 9 else "")
# Last, and never empty: $(...) drops trailing newlines, and `read` fails on a missing line.
print("none" if addons is None else "asked" if addons_good else "bad")
PY
) || fl_die "the spool file cannot be read"
{ read -r RELEASE; read -r DIGEST; read -r EXPORT; read -r ALLOW; read -r ADDONS; read -r VISIT; read -r VISIT_END; read -r ADDONS_STATE; } <<<"$parsed"

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

if [ -n "$VISIT" ]; then
  if [ "$DRY_RUN" = 1 ]; then
    fl_log "DRY RUN: would open the support visit asked"
  else
    "$HERE/firm-support-visit.sh" open "$VISIT" || fl_warn "the support visit was not opened"
  fi
fi
if [ -n "$VISIT_END" ]; then
  if [ "$DRY_RUN" = 1 ]; then
    fl_log "DRY RUN: would end support visit $VISIT_END"
  else
    "$HERE/firm-support-visit.sh" end "$VISIT_END" || fl_warn "the support visit was not ended"
  fi
fi

case "$ADDONS_STATE" in
  asked)
    read -r -a ADDON_LIST <<<"$ADDONS"
    addon_args=(apply)
    [ "$DRY_RUN" = 0 ] || addon_args+=(--dry-run)
    "$HERE/firm-addons.sh" "${addon_args[@]}" -- ${ADDON_LIST[@]+"${ADDON_LIST[@]}"} || fl_warn "the add-ons asked were not applied"
    ;;
  bad)
    fl_warn "refused the add-ons asked: not a list of add-on codes"
    [ "$DRY_RUN" = 1 ] || set_status addons_refused 1
    ;;
esac
