#!/usr/bin/env bash
# build_release.sh: builds and signs the bundle a firm server installs. On the owner's machine.
#
#   build_release.sh <git ref> --key PRIVATE.pem --out DIR
#   build_release.sh --new-key PRIVATE.pem      makes the signing key, once, and prints the public one
#   build_release.sh --verify BUNDLE --pub PUBLIC.pem
#
# Beside the bundle it writes <sha>.catalogue.json and its signature: the list of what the release
# carries, read from the manifests of that commit, for Platform > Updates > Releases.
#
# The bundle holds what a firm needs and nothing of the control plane: every addon except
# ea_platform_*, deploy/firm, new_firm.sh and backup_firm.sh. It is a `git archive` of a commit, so
# no local file can slip in. The signature is ed25519 over the file. The private key stays with the
# owner: never on a server, never in the repository, never on the control plane.
#
# Prints the two values that Plateforme > Versions asks for. Upload <sha>.tar.gz and
# <sha>.tar.gz.sig to the releases location: see docs/runbook/UPDATING.md.

set -euo pipefail
umask 077

log() { printf '[build_release] %s\n' "$*"; }
die() { printf '[build_release] ERROR: %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,15p' "$0"; exit 64; }

verify() {
  local bundle=$1 pub=$2
  openssl pkeyutl -verify -pubin -inkey "$pub" -rawin -in "$bundle" -sigfile "$bundle.sig" >/dev/null 2>&1 \
    || die "signature refused: $bundle"
  if tar -tzf "$bundle" | grep -q '^addons/ea_platform_'; then die "the bundle holds the control plane's addon"; fi
  log "signature good: $bundle"
}

REF="" KEY="" OUT="" PUB="" NEW_KEY="" VERIFY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --key) KEY=${2:?}; shift ;;
    --out) OUT=${2:?}; shift ;;
    --pub) PUB=${2:?}; shift ;;
    --new-key) NEW_KEY=${2:?}; shift ;;
    --verify) VERIFY=${2:?}; shift ;;
    -h|--help) usage ;;
    -*) die "unknown option $1" ;;
    *) [ -z "$REF" ] || die "one ref only"; REF=$1 ;;
  esac
  shift
done

if [ -n "$NEW_KEY" ]; then
  [ ! -e "$NEW_KEY" ] || die "$NEW_KEY exists: a new key would orphan every firm's copy of the public one"
  openssl genpkey -algorithm ed25519 -out "$NEW_KEY"
  chmod 600 "$NEW_KEY"
  log "private key: $NEW_KEY (keep it offline, with a copy in your safe). The public key, for Plateforme > Réglages:"
  openssl pkey -in "$NEW_KEY" -pubout
  exit 0
fi

if [ -n "$VERIFY" ]; then
  [ -n "$PUB" ] || usage
  verify "$VERIFY" "$PUB"
  exit 0
fi

[ -n "$REF" ] && [ -n "$KEY" ] && [ -n "$OUT" ] || usage
[ -r "$KEY" ] || die "cannot read the signing key $KEY"
git rev-parse --is-inside-work-tree >/dev/null || die "run this inside the repository"
[[ $REF != -* ]] || die "invalid ref"
SHA=$(git rev-parse --verify --quiet "${REF}^{commit}") || die "ref '$REF' not found"
BUNDLE_NAME=$SHA.tar.gz

mapfile -t ADDONS < <(git ls-tree -d --name-only "$SHA" addons/ | grep -v '^addons/ea_platform_')
[ "${#ADDONS[@]}" -ge 1 ] || die "no addon at $SHA"
PATHS=("${ADDONS[@]}" deploy/firm deploy/practice scripts/provision/new_firm.sh scripts/provision/backup_firm.sh)
if git cat-file -e "$SHA:requirements.txt" 2>/dev/null; then PATHS+=(requirements.txt); fi

mkdir -p "$OUT"
git archive --format=tar "$SHA" "${PATHS[@]}" | gzip -n -9 > "$OUT/$BUNDLE_NAME"
openssl pkeyutl -sign -inkey "$KEY" -rawin -in "$OUT/$BUNDLE_NAME" -out "$OUT/$BUNDLE_NAME.sig"
DIGEST=$(sha256sum "$OUT/$BUNDLE_NAME" | cut -d' ' -f1)
if tar -tzf "$OUT/$BUNDLE_NAME" | grep -q '^addons/ea_platform_'; then die "the bundle holds the control plane's addon"; fi

WORK=$(mktemp -d)
tar -xzf "$OUT/$BUNDLE_NAME" -C "$WORK" addons
PYTHON=$(command -v python3 || command -v python) || die "python is needed to read the manifests"
HERE=$(cd "$(dirname "$0")" && pwd)
"$PYTHON" -I "$HERE/build_catalogue.py" "$WORK/addons" "$SHA" > "$OUT/$SHA.catalogue.json" \
  || { rm -rf "$WORK"; die "a manifest of this commit cannot be read"; }
rm -rf "$WORK"
openssl pkeyutl -sign -inkey "$KEY" -rawin -in "$OUT/$SHA.catalogue.json" -out "$OUT/$SHA.catalogue.json.sig"

log "bundle: $OUT/$BUNDLE_NAME"
log "signature: $OUT/$BUNDLE_NAME.sig"
log "catalogue: $OUT/$SHA.catalogue.json, signature: $OUT/$SHA.catalogue.json.sig"
printf 'commit  %s\n' "$SHA"
printf 'sha256  %s\n' "$DIGEST"
