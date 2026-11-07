#!/usr/bin/env bash
# sign_promotion.sh: what the owner runs, on their own computer, to make a commit promotable.
#
#   scripts/pipeline/sign_promotion.sh <commit> --key PRIVATE.pem --out DIR
#
# Builds and signs the bundle with build_release.sh, then signs one line naming that commit and that
# digest with the same offline key. The Pipeline screen checks that line against the public key: so
# only what you signed here can be started there, and the firm's server checks the bundle's own signature
# again before it installs anything. The control plane never sees the private key.
#
# Plug the key in (or mount it) only for this command. Nothing is pushed, and nothing leaves your computer.

set -euo pipefail
umask 077

die() { printf '[sign_promotion] ERROR: %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,11p' "$0"; exit 64; }

REF="" KEY="" OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --key) KEY=${2:?}; shift ;;
    --out) OUT=${2:?}; shift ;;
    -h|--help) usage ;;
    -*) die "unknown option $1" ;;
    *) [ -z "$REF" ] || die "one commit only"; REF=$1 ;;
  esac
  shift
done
[ -n "$REF" ] && [ -n "$KEY" ] && [ -n "$OUT" ] || usage
[ -r "$KEY" ] || die "cannot read the signing key"
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

SHA=$(git rev-parse --verify --quiet "${REF}^{commit}") || die "commit '$REF' not found"
BUILD=$(bash "$HERE/../provision/build_release.sh" "$SHA" --key "$KEY" --out "$OUT")
DIGEST=$(printf '%s\n' "$BUILD" | sed -n 's/^sha256  //p')
[[ $DIGEST =~ ^[0-9a-f]{64}$ ]] || die "the build did not give a digest"

LINE=$OUT/$SHA.attestation.txt
printf 'ea-promotion-v1\n%s\n%s\n' "$SHA" "$DIGEST" > "$LINE"
openssl pkeyutl -sign -inkey "$KEY" -rawin -in "$LINE" -out "$LINE.sig"
ATTESTATION=$(openssl base64 -A -in "$LINE.sig")
rm -f "$LINE" "$LINE.sig"

cat <<EOF

Upload to the releases location:
  $OUT/$SHA.tar.gz
  $OUT/$SHA.tar.gz.sig

Paste into Platform > Updates > Releases > New:
commit       $SHA
sha256       $DIGEST
attestation  $ATTESTATION
EOF
