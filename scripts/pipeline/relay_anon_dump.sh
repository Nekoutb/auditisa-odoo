#!/usr/bin/env bash
# relay_anon_dump.sh: carries an anonymised copy from a firm's server to staging. On the owner's computer.
#
#   scripts/pipeline/relay_anon_dump.sh FIRM_ADDRESS REF DIGEST [STAGING] [--apply]
#
#   FIRM_ADDRESS  root@<the firm's server>; use that firm's own SSH key, through your ~/.ssh/config
#   REF DIGEST    as the Pipeline screen shows them
#   STAGING       default root@108.61.209.30
#
# Dry run by default. With --apply it pipes the file through this computer, without storing it here, and
# checks the digest at the far end: a file with another digest is removed. It logs in to the firm's server,
# which the firm sees in Settings > Operator access: enter it in the Break-glass log first.

set -euo pipefail

die() { printf '[relay] ERROR: %s\n' "$*" >&2; exit 1; }

APPLY=0 ARGS=()
for arg in "$@"; do
  if [ "$arg" = --apply ]; then APPLY=1; else ARGS+=("$arg"); fi
done
[ "${#ARGS[@]}" -ge 3 ] || { sed -n '2,11p' "$0"; exit 64; }
FIRM=${ARGS[0]} REF=${ARGS[1]} DIGEST=${ARGS[2]} STAGING=${ARGS[3]:-root@108.61.209.30}
[[ $REF =~ ^[0-9a-f]{16}$ ]] || die "invalid reference"
[[ $DIGEST =~ ^[0-9a-f]{64}$ ]] || die "invalid digest"
[[ $FIRM =~ ^[a-zA-Z0-9_.@-]+$ ]] && [[ $STAGING =~ ^[a-zA-Z0-9_.@-]+$ ]] || die "invalid address"
SOURCE=/var/lib/auditisa-firm/anon-exports/anon-$REF.tar
TARGET=/var/lib/auditisa-staging/incoming/anon-$REF.tar

if [ "$APPLY" != 1 ]; then
  printf '[relay] DRY RUN: would copy %s:%s to %s:%s and check sha256 %s. Add --apply.\n' "$FIRM" "$SOURCE" "$STAGING" "$TARGET" "$DIGEST"
  exit 0
fi

# shellcheck disable=SC2029  # REF and DIGEST were checked above, on purpose expanded here.
ssh "$FIRM" "cat '$SOURCE'" | ssh "$STAGING" "umask 077; install -d -m 700 /var/lib/auditisa-staging/incoming; cat > '$TARGET.part' \
  && [ \"\$(sha256sum '$TARGET.part' | cut -d' ' -f1)\" = '$DIGEST' ] && mv -T '$TARGET.part' '$TARGET' \
  || { rm -f '$TARGET.part'; echo 'digest differs: nothing kept' >&2; exit 1; }"
printf '[relay] on staging: %s\n[relay] now, on staging: staging-rebuild --dump %s --sha256 %s\n' "$TARGET" "$TARGET" "$DIGEST"
