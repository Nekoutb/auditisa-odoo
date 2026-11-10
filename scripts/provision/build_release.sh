#!/usr/bin/env bash
# build_release.sh: builds the bundle a firm server and the practice computer install. No key, no signature.
#
#   build_release.sh <git ref> --out DIR [--since REF]
#
# Writes into DIR:
#   <sha>.tar.gz          the bundle
#   <sha>.catalogue.json  the list of what it carries, read from the manifests of that commit (for the console)
#   <sha>.changes.txt     the commits it brings since --since REF (the release now in service), or the last 20
#
# Then, on the console, as root: deploy/control-plane/release-tools/publish-release.sh DIR "label" puts the
# bundle in the private releases bucket and registers it with its SHA-256. The owner sees "New version ready"
# on the Status page and clicks Promote to Staging, then Promote to Production. See docs/runbook/UPDATING.md.
#
# The bundle holds what a firm needs and nothing of the control plane: every addon except ea_platform_*,
# deploy/firm, deploy/practice, new_firm.sh and backup_firm.sh. It is a `git archive` of a commit, so no local
# file can slip in, and building the same commit twice gives the same file (gzip -n). A server installs it
# only if its SHA-256 is the one the console registered and sends over the authenticated heartbeat.
#
# --unsigned is accepted and ignored (it was needed before 2026-11-10, when releases were signed).

set -euo pipefail
umask 077

log() { printf '[build_release] %s\n' "$*"; }
die() { printf '[build_release] ERROR: %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,20p' "$0"; exit 64; }

# python3 can be the Microsoft Store's empty alias on Windows: take the first one that really runs.
find_python() {
  local candidate
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys' >/dev/null 2>&1; then
      printf '%s' "$candidate"; return 0
    fi
  done
  return 1
}

REF="" OUT="" SINCE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT=${2:?}; shift ;;
    --since) SINCE=${2:?}; shift ;;
    --unsigned) ;;
    --key|--sign|--verify|--pub|--signers|--new-key)
      die "$1: releases are no longer signed (2026-11-10). Build with: build_release.sh <ref> --out DIR" ;;
    -h|--help) usage ;;
    -*) die "unknown option $1" ;;
    *) [ -z "$REF" ] || die "one ref only"; REF=$1 ;;
  esac
  shift
done

[ -n "$REF" ] && [ -n "$OUT" ] || usage
git rev-parse --is-inside-work-tree >/dev/null || die "run this inside the repository"
[[ $REF != -* ]] || die "invalid ref"
SHA=$(git rev-parse --verify --quiet "${REF}^{commit}") || die "ref '$REF' not found"
BUNDLE_NAME=$SHA.tar.gz
PYTHON=$(find_python) || die "python is needed to read the manifests"

mapfile -t ADDONS < <(git ls-tree -d --name-only "$SHA" addons/ | grep -v '^addons/ea_platform_')
[ "${#ADDONS[@]}" -ge 1 ] || die "no addon at $SHA"
PATHS=("${ADDONS[@]}" deploy/firm deploy/practice scripts/provision/new_firm.sh scripts/provision/backup_firm.sh)
if git cat-file -e "$SHA:requirements.txt" 2>/dev/null; then PATHS+=(requirements.txt); fi

mkdir -p "$OUT"
git archive --format=tar "$SHA" "${PATHS[@]}" | gzip -n -9 > "$OUT/$BUNDLE_NAME"
DIGEST=$(sha256sum "$OUT/$BUNDLE_NAME" | cut -d' ' -f1)
# Not grep -q: it would stop tar early, and under pipefail the check would then pass unseen.
if tar -tzf "$OUT/$BUNDLE_NAME" | grep '^addons/ea_platform_' >/dev/null; then die "the bundle holds the control plane's addon"; fi

WORK=$(mktemp -d)
tar -xzf "$OUT/$BUNDLE_NAME" -C "$WORK" addons
HERE=$(cd "$(dirname "$0")" && pwd)
"$PYTHON" -I "$HERE/build_catalogue.py" "$WORK/addons" "$SHA" > "$OUT/$SHA.catalogue.json" \
  || { rm -rf "$WORK"; die "a manifest of this commit cannot be read"; }
rm -rf "$WORK"

# What this release brings, in plain commit subjects.
{
  printf 'Version %s, made on %s\n' "${SHA:0:12}" "$(git log -1 --format=%cs "$SHA")"
  if [ -n "$SINCE" ]; then
    printf 'Changes since %s:\n' "$(git rev-parse --short=12 "$SINCE")"
    git log --no-merges --format='- %s' "$SINCE..$SHA" | head -n 200
  else
    printf 'Last changes:\n'
    git log --no-merges --format='- %s' -n 20 "$SHA"
  fi
} > "$OUT/$SHA.changes.txt"

log "bundle: $OUT/$BUNDLE_NAME"
log "catalogue: $OUT/$SHA.catalogue.json"
log "changes: $OUT/$SHA.changes.txt"
printf 'commit  %s\n' "$SHA"
printf 'sha256  %s\n' "$DIGEST"
