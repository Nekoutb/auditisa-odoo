#!/usr/bin/env bash
# build_release.sh: builds and signs the bundle a firm server installs. On the owner's machine.
#
#   build_release.sh <git ref> --key PRIVATE.pem --out DIR   builds and signs, in one go
#   build_release.sh <git ref> --unsigned --out DIR          builds only: no key needed, nothing signed
#   build_release.sh --sign DIR/<sha>.tar.gz --key PRIVATE.pem [--pub PUBLIC.pem]
#                                                            signs what --unsigned built, then checks it
#   build_release.sh --new-key PRIVATE.pem      makes the signing key, once, and prints the public one
#   build_release.sh --verify BUNDLE --pub PUBLIC.pem
#   build_release.sh --verify BUNDLE --signers deploy/trust/signers.json   any trusted signer
#
# --unsigned also writes <sha>.changes.txt, the list of changes the signer reads before signing:
# the commits since --since REF (the release now in service), or the last 20 when not given.
#
# The bundle carries deploy/trust/signers.json, the list of trusted signers: a firm takes it once the
# bundle's signature holds for a signer it already trusts (deploy/firm/release_trust.py). Put the
# console's list there before building (Platform > Updates > Signers > Download the list).
#
# Beside the bundle it writes <sha>.catalogue.json and its signature: the list of what the release
# carries, read from the manifests of that commit, for Platform > Updates > Releases. --sign also
# writes <sha>.attestation, the offline attestation the Pipeline screen checks (as sign_promotion.sh).
#
# A key locked with a passphrase is asked for it once, by this script, whatever the number of files
# to sign: the passphrase goes to openssl on a pipe, never on a command line, never in a file.
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
usage() { sed -n '2,33p' "$0"; exit 64; }

# With --signers: the public key, among the list's active signers, that signed the bundle.
pub_from_signers() {
  local bundle=$1 list=$2 python work key
  python=$(find_python) || die "python is needed to read $list"
  work=$(mktemp -d)
  "$python" -I - "$list" "$work" <<'PY' || { rm -rf "$work"; die "the list of signers cannot be read: $list"; }
import json, sys
data = json.load(open(sys.argv[1], encoding="ascii"))
assert data["schema"] == "auditisa-signers-v1"
for row in data["signers"]:
    open(f"{sys.argv[2]}/{row['fingerprint']}.pub", "w", encoding="ascii").write(row["public_key"])
PY
  for key in "$work"/*.pub; do
    if openssl pkeyutl -verify -pubin -inkey "$key" -rawin -in "$bundle" -sigfile "$bundle.sig" >/dev/null 2>&1; then
      cp "$key" "$work.pub"; rm -rf "$work"; printf '%s' "$work.pub"; return 0
    fi
  done
  rm -rf "$work"
  die "signature refused: $bundle is not signed by any signer of $list"
}

verify() {
  local bundle=$1 pub=$2 catalogue
  openssl pkeyutl -verify -pubin -inkey "$pub" -rawin -in "$bundle" -sigfile "$bundle.sig" >/dev/null 2>&1 \
    || die "signature refused: $bundle"
  if tar -tzf "$bundle" | grep '^addons/ea_platform_' >/dev/null; then die "the bundle holds the control plane's addon"; fi
  log "signature good: $bundle"
  catalogue="${bundle%.tar.gz}.catalogue.json"
  if [ -e "$catalogue.sig" ]; then
    openssl pkeyutl -verify -pubin -inkey "$pub" -rawin -in "$catalogue" -sigfile "$catalogue.sig" >/dev/null 2>&1 \
      || die "signature refused: $catalogue"
    log "signature good: $catalogue"
  fi
}

# The passphrase, asked once. Empty when the key is not locked.
PASS="" LOCKED=""
unlock() {
  if openssl pkey -in "$KEY" -passin pass: -noout >/dev/null 2>&1; then return 0; fi
  LOCKED=1
  local try
  for try in 1 2 3; do
    IFS= read -rs -p "Passphrase of the signing key (nothing shows while you type): " PASS </dev/tty
    printf '\n' >&2
    if printf '%s\n' "$PASS" | openssl pkey -in "$KEY" -passin stdin -noout >/dev/null 2>&1; then return 0; fi
    printf '[build_release] wrong passphrase (%s of 3)\n' "$try" >&2
  done
  PASS=""
  die "the key did not open: nothing was signed"
}

sign_file() {
  if [ -n "$LOCKED" ]; then
    printf '%s\n' "$PASS" | openssl pkeyutl -sign -inkey "$KEY" -passin stdin -rawin -in "$1" -out "$2"
  else
    openssl pkeyutl -sign -inkey "$KEY" -rawin -in "$1" -out "$2"
  fi
}

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

REF="" KEY="" OUT="" PUB="" NEW_KEY="" VERIFY="" SIGN="" UNSIGNED="" SIGNERS="" SINCE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --key) KEY=${2:?}; shift ;;
    --out) OUT=${2:?}; shift ;;
    --pub) PUB=${2:?}; shift ;;
    --signers) SIGNERS=${2:?}; shift ;;
    --since) SINCE=${2:?}; shift ;;
    --new-key) NEW_KEY=${2:?}; shift ;;
    --verify) VERIFY=${2:?}; shift ;;
    --sign) SIGN=${2:?}; shift ;;
    --unsigned) UNSIGNED=1 ;;
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
  [ -n "$PUB" ] || [ -n "$SIGNERS" ] || usage
  if [ -z "$PUB" ]; then
    PUB=$(pub_from_signers "$VERIFY" "$SIGNERS")
    trap 'rm -f "$PUB"' EXIT
    log "signed by: $(openssl pkey -pubin -in "$PUB" -outform DER | sha256sum | cut -c1-16)"
  fi
  verify "$VERIFY" "$PUB"
  exit 0
fi

if [ -n "$SIGN" ]; then
  [ -n "$KEY" ] || usage
  [ -r "$KEY" ] || die "cannot read the signing key $KEY"
  [ -r "$SIGN" ] || die "cannot read the bundle $SIGN"
  NAME=$(basename "$SIGN")
  [[ $NAME =~ ^([0-9a-f]{40})\.tar\.gz$ ]] || die "a bundle is named <40-character commit>.tar.gz: $NAME"
  SHA=${BASH_REMATCH[1]}
  DIR=$(dirname "$SIGN")
  CATALOGUE=$DIR/$SHA.catalogue.json
  [ -r "$CATALOGUE" ] || die "the catalogue $CATALOGUE is missing: build again with --unsigned"
  DIGEST=$(sha256sum "$SIGN" | cut -d' ' -f1)
  unlock
  sign_file "$SIGN" "$SIGN.sig"
  sign_file "$CATALOGUE" "$CATALOGUE.sig"
  LINE=$(mktemp)
  printf 'ea-promotion-v1\n%s\n%s\n' "$SHA" "$DIGEST" > "$LINE"
  sign_file "$LINE" "$LINE.sig"
  openssl base64 -A -in "$LINE.sig" > "$DIR/$SHA.attestation"
  printf '\n' >> "$DIR/$SHA.attestation"
  rm -f "$LINE" "$LINE.sig"
  PASS=""
  if [ -n "$PUB" ]; then verify "$SIGN" "$PUB"; fi
  log "signed: $SIGN.sig, $CATALOGUE.sig, $DIR/$SHA.attestation"
  printf 'commit  %s\n' "$SHA"
  printf 'sha256  %s\n' "$DIGEST"
  exit 0
fi

[ -n "$REF" ] && [ -n "$OUT" ] || usage
[ -n "$KEY" ] || [ -n "$UNSIGNED" ] || usage
[ -z "$KEY" ] || [ -z "$UNSIGNED" ] || die "--key and --unsigned do not go together"
[ -z "$KEY" ] || [ -r "$KEY" ] || die "cannot read the signing key $KEY"
git rev-parse --is-inside-work-tree >/dev/null || die "run this inside the repository"
[[ $REF != -* ]] || die "invalid ref"
SHA=$(git rev-parse --verify --quiet "${REF}^{commit}") || die "ref '$REF' not found"
BUNDLE_NAME=$SHA.tar.gz
PYTHON=$(find_python) || die "python is needed to read the manifests"

mapfile -t ADDONS < <(git ls-tree -d --name-only "$SHA" addons/ | grep -v '^addons/ea_platform_')
[ "${#ADDONS[@]}" -ge 1 ] || die "no addon at $SHA"
PATHS=("${ADDONS[@]}" deploy/firm deploy/practice scripts/provision/new_firm.sh scripts/provision/backup_firm.sh)
if git cat-file -e "$SHA:requirements.txt" 2>/dev/null; then PATHS+=(requirements.txt); fi
# The list of trusted signers that firms take from this release once its signature holds.
if git cat-file -e "$SHA:deploy/trust/signers.json" 2>/dev/null; then
  PATHS+=(deploy/trust/signers.json)
else
  log "WARNING: no deploy/trust/signers.json at $SHA: firms keep the list of signers they have"
fi

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

# What the signer reads before signing: the commits this release brings, in plain subjects.
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
if [ -n "$KEY" ]; then
  unlock
  sign_file "$OUT/$BUNDLE_NAME" "$OUT/$BUNDLE_NAME.sig"
  sign_file "$OUT/$SHA.catalogue.json" "$OUT/$SHA.catalogue.json.sig"
  PASS=""
  log "signature: $OUT/$BUNDLE_NAME.sig"
  log "catalogue signature: $OUT/$SHA.catalogue.json.sig"
else
  log "not signed (--unsigned): sign with  build_release.sh --sign $OUT/$BUNDLE_NAME --key PRIVATE.pem"
fi
printf 'commit  %s\n' "$SHA"
printf 'sha256  %s\n' "$DIGEST"
