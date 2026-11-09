#!/usr/bin/env bash
# upload-release.sh: on the console server, as root. Checks a signed release against the trusted signers the
# console holds (Platform > Updates > Signers), then puts it in the Wasabi releases bucket with the console's
# own Wasabi key. Before the list of signers (console older than feat/signers): the one key of the settings.
#
# Simpler since feat/signers: Platform > Updates > Waiting for signature does the same from the screens.
#
#   upload-release.sh --check            only lists the releases bucket (proves the key and the bucket)
#   upload-release.sh DIR                checks, then uploads the four files of the release in DIR
#   upload-release.sh DIR --verify-only  checks only, uploads nothing
#
# DIR holds <sha>.tar.gz, <sha>.tar.gz.sig, <sha>.catalogue.json, <sha>.catalogue.json.sig (one release).
# The key and secret are read from /etc/auditisa-platform and given to curl through a pipe: they are
# never on a command line, never printed, never written anywhere else.

set -euo pipefail
umask 077

ETC=${PLATFORM_ETC:-/etc/auditisa-platform}
DB=${PLATFORM_DB:-auditisa_platform}
log() { printf '[upload-release] %s\n' "$*"; }
die() { printf '[upload-release] ERROR: %s\n' "$*" >&2; exit 1; }

param() {
  (cd /tmp && runuser -u postgres -- psql -XAt "$DB" -v k="$1" <<'SQL'
SELECT value FROM ir_config_parameter WHERE key = :'k';
SQL
  )
}

REGION=$(param ea_platform.wasabi_region)
BUCKET=$(param ea_platform.releases_bucket)
ENDPOINT=$(param ea_platform.wasabi_endpoint)
[ -n "$REGION" ] || die "Platform > Settings: Wasabi region is empty"
[ -n "$BUCKET" ] || die "Platform > Settings: releases bucket is empty"
[[ $REGION =~ ^[a-z]{2}-[a-z]+-[0-9]$ ]] || die "unexpected region"
[[ $BUCKET =~ ^auditisa-releases-[a-z0-9]{8,}$ ]] || die "unexpected bucket name"
HOST=${ENDPOINT:-s3.$REGION.wasabisys.com}
for f in wasabi.key wasabi.secret; do [ -s "$ETC/$f" ] || die "$ETC/$f is missing or empty"; done

# curl reads its user option from a pipe (process substitution): not visible in the process list.
s3() {
  curl -sS --fail-with-body --aws-sigv4 "aws:amz:$REGION:s3" \
    -K <(printf 'user = "%s:%s"\n' "$(tr -d ' \r\n' < "$ETC/wasabi.key")" "$(tr -d ' \r\n' < "$ETC/wasabi.secret")") \
    "$@"
}

if [ "${1:-}" = "--check" ]; then
  out=$(s3 -H "x-amz-content-sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" \
    "https://$HOST/$BUCKET?list-type=2&max-keys=1000") || die "Wasabi refused the listing: $out"
  count=$(printf '%s' "$out" | { grep -o '<Key>' || true; } | wc -l)
  log "bucket $BUCKET at $HOST answers; objects in it: $count"
  printf '%s' "$out" | grep -o '<Key>[^<]*</Key>' | sed 's/<\/*Key>//g; s/^/  /' || true
  exit 0
fi

DIR=${1:?usage: upload-release.sh DIR [--verify-only] | --check}
MODE=${2:-}
mapfile -t BUNDLES < <(cd "$DIR" && ls | grep -E '^[0-9a-f]{40}\.tar\.gz$' || true)
[ "${#BUNDLES[@]}" -eq 1 ] || die "DIR must hold exactly one <sha>.tar.gz"
SHA=${BUNDLES[0]%.tar.gz}
FILES=("$SHA.tar.gz" "$SHA.tar.gz.sig" "$SHA.catalogue.json" "$SHA.catalogue.json.sig")
for f in "${FILES[@]}"; do [ -s "$DIR/$f" ] || die "missing: $DIR/$f"; done

KEYS=$(mktemp -d)
trap 'rm -rf "$KEYS"' EXIT
# One file per ACTIVE trusted signer, named by the signer's name for the log.
signers() {
  (cd /tmp && runuser -u postgres -- psql -XAt "$DB" -F $'\t' -c \
    "SELECT id, regexp_replace(name, '[^A-Za-z0-9 ._-]', '', 'g') FROM platform_signer WHERE active ORDER BY id" 2>/dev/null)
}
signer_pem() {
  (cd /tmp && runuser -u postgres -- psql -XAt "$DB" -v id="$1" <<'SQL'
SELECT public_pem FROM platform_signer WHERE id = :'id' AND active;
SQL
  )
}
declare -A NAMES=()
while IFS=$'\t' read -r id name; do
  [ -n "$id" ] || continue
  signer_pem "$id" > "$KEYS/$id.pub"
  NAMES[$id]=$name
done < <(signers)
if [ "${#NAMES[@]}" = 0 ]; then
  param ea_platform.release_signing_public_key > "$KEYS/legacy.pub"
  NAMES[legacy]="the one key of Platform > Settings"
fi
SIGNER=""
for id in "${!NAMES[@]}"; do
  grep -q 'BEGIN PUBLIC KEY' "$KEYS/$id.pub" || continue
  openssl pkeyutl -verify -pubin -inkey "$KEYS/$id.pub" -rawin -in "$DIR/$SHA.tar.gz" -sigfile "$DIR/$SHA.tar.gz.sig" >/dev/null 2>&1 || continue
  SIGNER=$id; break
done
[ -n "$SIGNER" ] || die "signature refused for $SHA.tar.gz: not signed by a trusted signer (Platform > Updates > Signers). Nothing uploaded."
for f in "$SHA.tar.gz" "$SHA.catalogue.json"; do
  openssl pkeyutl -verify -pubin -inkey "$KEYS/$SIGNER.pub" -rawin -in "$DIR/$f" -sigfile "$DIR/$f.sig" >/dev/null 2>&1 \
    || die "signature refused for $f: not the same trusted signer. Nothing uploaded."
  log "signature good, signed by ${NAMES[$SIGNER]}: $f"
done
if tar -tzf "$DIR/$SHA.tar.gz" | grep -q '^addons/ea_platform_'; then die "the bundle holds the control plane's addon"; fi
grep -q "\"release\": \"$SHA\"" "$DIR/$SHA.catalogue.json" || die "the catalogue names another release"
log "commit $SHA"
log "sha256 $(sha256sum "$DIR/$SHA.tar.gz" | cut -d' ' -f1)"
[ "$MODE" = "--verify-only" ] && { log "checks passed; nothing uploaded (--verify-only)"; exit 0; }

for f in "${FILES[@]}"; do
  digest=$(sha256sum "$DIR/$f" | cut -d' ' -f1)
  out=$(s3 -T "$DIR/$f" -H "x-amz-content-sha256: $digest" -H "Content-Type: application/octet-stream" \
    "https://$HOST/$BUCKET/$f") || die "upload refused for $f: $out"
  log "uploaded: $f"
done
for f in "${FILES[@]}"; do
  size=$(s3 -I -H "x-amz-content-sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" \
    "https://$HOST/$BUCKET/$f" | tr -d '\r' | sed -n 's/^[Cc]ontent-[Ll]ength: //p')
  [ "$size" = "$(stat -c %s "$DIR/$f")" ] || die "the bucket copy of $f has a different size"
  log "in the bucket, same size: $f"
done
log "done: $BUCKET holds release $SHA"
