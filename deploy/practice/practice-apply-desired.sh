#!/usr/bin/env bash
# practice-apply-desired.sh: does what the control room's last heartbeat answer asked.
#
#   practice-apply-desired [--dry-run]
#
# practice-heartbeat keeps the answer only if its HMAC holds under this computer's token, and every
# value is still checked again here, by closed patterns. What the control room can ask, and nothing else:
#   - a release (Promote to Staging): installed only if its SHA-256 is the digest given with it
#     (practice-update checks it);
#   - for each firm's space: its name, its first administrator's login, its language, its optional
#     add-ons (checked against the release), a reset number (a reset when it grows), and the hash of
#     a one-time link for the first administrator;
#   - spaces to remove, by slug.
# It cannot name a database, a file or a command: each action goes through practice-space, whose
# name gate refuses anything but practice_<slug>.

set -euo pipefail
umask 077
SCRIPT_NAME=practice-apply-desired
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
# shellcheck source=deploy/practice/practice-lib.sh
. "$HERE/practice-lib.sh"
DRY_RUN=0
[ "${1:-}" != "--dry-run" ] || DRY_RUN=1
load_practice_env
: "${PRACTICE_RELEASE_BASE_URL:=}"
SPOOL=$PRACTICE_VAR/spool/desired.json
[ -s "$SPOOL" ] || exit 0
[ "$DRY_RUN" = 1 ] || [ "$(id -u)" = 0 ] || pl_die "run as root"
exec 6>/run/lock/practice-apply.lock
flock -n 6 || exit 0
# One action per line, tab-separated, every value checked; anything unexpected is left out.
parsed=$(python3 -I - "$SPOOL" <<'PY'
import base64
import json
import re
import sys

SLUG = re.compile(r"^[a-z][a-z0-9-]{1,30}[a-z0-9]$")
SHA = re.compile(r"^[0-9a-f]{12,40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
LOGIN = re.compile(r"^[A-Za-z0-9._+-]{1,64}(@[A-Za-z0-9.-]{1,190})?$")
LANG = re.compile(r"^[a-z]{2,3}_[A-Z]{2}$")
ADDON = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
URL = re.compile(r"^https://[a-z0-9.-]{3,253}(:[0-9]{2,5})?/[A-Za-z0-9._~%/-]{1,512}(\?[A-Za-z0-9._~%&=-]{1,1500})?$")

with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
if not isinstance(data, dict):
    sys.exit(0)
release = data.get("release")
if isinstance(release, dict) and SHA.match(str(release.get("sha", ""))) and DIGEST.match(str(release.get("bundle_sha256", ""))):
    # A time-limited download address into the private releases bucket, if the control room gave one.
    url = release.get("bundle_url", "")
    if not (isinstance(url, str) and URL.match(url)):
        url = "-"
    print("RELEASE\t%s\t%s\t%s" % (release["sha"], release["bundle_sha256"], url))
for space in data.get("spaces", [])[:500] if isinstance(data.get("spaces"), list) else []:
    if not isinstance(space, dict):
        continue
    slug, login, lang = space.get("slug", ""), space.get("admin_login", ""), space.get("lang", "fr_FR")
    name_b64 = space.get("name_b64", "")
    addons = space.get("addons", [])
    generation = space.get("reset_generation", 0)
    link, expires = space.get("first_admin_hash") or "-", space.get("first_admin_expires") or "-"
    try:
        name = base64.b64decode(name_b64, validate=True).decode("utf-8")
    except (ValueError, TypeError):
        continue
    if not (isinstance(slug, str) and SLUG.match(slug) and "--" not in slug and isinstance(login, str) and LOGIN.match(login)
            and isinstance(lang, str) and LANG.match(lang) and 0 < len(name) <= 80 and "\n" not in name and "\t" not in name
            and isinstance(addons, list) and len(addons) <= 24 and all(isinstance(a, str) and ADDON.match(a) for a in addons)
            and type(generation) is int and 0 <= generation < 10 ** 9):
        continue
    if not (link == "-" or (isinstance(link, str) and DIGEST.match(link) and isinstance(expires, str) and INSTANT.match(expires))):
        link, expires = "-", "-"
    print("SPACE\t%s\t%s\t%s\t%s\t%s\t%d\t%s\t%s" % (slug, name_b64, login, lang, ",".join(sorted(set(addons))) or "-", generation, link, expires))
for slug in data.get("remove", [])[:500] if isinstance(data.get("remove"), list) else []:
    if isinstance(slug, str) and SLUG.match(slug):
        print("REMOVE\t%s" % slug)
PY
) || pl_die "the spool file cannot be read"

act() {
  if [ "$DRY_RUN" = 1 ]; then pl_log "DRY RUN: $*"; return 0; fi
  "$@" || pl_warn "did not succeed: ${*:1:3}"
}

apply_release() {
  local sha=$1 digest=$2 bundle_url=${3:--} work
  [ "$sha" != "$(current_release)" ] && [ "${sha:0:12}" != "$(current_release)" ] || return 0
  if grep -qxF "$sha" "$PRACTICE_VAR/refused-releases" 2>/dev/null; then return 0; fi
  if [ "$bundle_url" = - ] && [ -n "$PRACTICE_RELEASE_BASE_URL" ]; then
    bundle_url=$PRACTICE_RELEASE_BASE_URL/$sha.tar.gz
  fi
  # The preview on staging installs a bundle too, the same way, when the control room gives an address.
  if [ "$bundle_url" = - ]; then
    pl_log "release $sha asked, but no download address: install it by hand (practice-update)"
    return 0
  fi
  if [ "$DRY_RUN" = 1 ]; then pl_log "DRY RUN: fetch, check the SHA-256 and install release $sha"; return 0; fi
  work=$(mktemp -d /var/tmp/practice-release.XXXXXX)
  if curl -fsSL --retry 3 --max-time 600 -o "$work/${sha:0:12}.tar.gz" "$bundle_url" \
     && "$HERE/practice-update.sh" --bundle "$work/${sha:0:12}.tar.gz" --digest "$digest"; then
    pl_log "now on release $sha"
  else
    printf '%s\n' "$sha" >> "$PRACTICE_VAR/refused-releases"
    pl_warn "release $sha not installed: it is not tried again"
  fi
  rm -rf "$work"
}

apply_space() {
  local slug=$1 name_b64=$2 login=$3 lang=$4 addons=$5 generation=$6 link=$7 expires=$8
  [ "$addons" != "-" ] || addons=""
  if [ ! -e "$(space_file "$slug")" ]; then
    act "$HERE/practice-space.sh" create --slug "$slug" --name "$(printf '%s' "$name_b64" | base64 -d)" \
      --admin-login "$login" --lang "$lang" --addons "$addons" --generation "$generation"
  else
    load_space "$slug"
    if [ "$generation" -gt "$SPACE_RESET_GEN" ]; then
      act "$HERE/practice-space.sh" reset --slug "$slug" --generation "$generation"
      load_space "$slug"
    fi
    if [ "$addons" != "$SPACE_ADDONS" ]; then
      act "$HERE/practice-space.sh" addons --slug "$slug" --set "$addons"
    fi
  fi
  [ -e "$(space_file "$slug")" ] || return 0
  load_space "$slug"
  if [ "$link" != "-" ] && [ "$link" != "$SPACE_FIRST_ADMIN_HASH" ]; then
    act "$HERE/practice-space.sh" first-admin --slug "$slug" --hash "$link" --expires "$expires"
  fi
}

while IFS=$'\t' read -r kind a b c d e f g h; do
  case "$kind" in
    RELEASE) apply_release "$a" "$b" "$c" ;;
    SPACE) ( apply_space "$a" "$b" "$c" "$d" "$e" "$f" "$g" "$h" ) || pl_warn "space $a: not applied" ;;
    REMOVE) [ ! -e "$(space_file "$a")" ] || act "$HERE/practice-space.sh" delete --slug "$a" --yes ;;
  esac
done <<<"$parsed"
