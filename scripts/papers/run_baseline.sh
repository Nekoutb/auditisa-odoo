#!/usr/bin/env bash
# Regenerates addons/ea_audit_papers/data and its parity fixtures from one commit of
# the AuditISA repo, in a throwaway checkout. The running platform/ is only read.
#
#   scripts/papers/run_baseline.sh <EA AUDIT TOOL repo> <commit> <scratch dir>
#
# node_modules is linked beside the checkout, not inside it, so removing the worktree
# can never walk into the real one. Then: pytest addons/ea_audit_papers/tests/pure
set -euo pipefail

repo=$1; commit=$2; scratch=$3
here=$(cd "$(dirname "$0")/../.." && pwd)
base="$scratch/platform-baseline"
link="$scratch/node_modules"

windows() { [[ "$(uname -s)" == MINGW* || "$(uname -s)" == MSYS* ]]; }

cleanup() {
  if windows; then
    powershell -NoProfile -Command "if (Test-Path -LiteralPath '$(cygpath -w "$link")') { (Get-Item -LiteralPath '$(cygpath -w "$link")').Delete() }" || true
  else
    rm -f "$link"
  fi
  git -C "$repo" worktree remove --force "$base" 2>/dev/null || true
}
trap cleanup EXIT

mkdir -p "$scratch"
git -C "$repo" worktree add --detach "$base" "$commit" >/dev/null
if windows; then
  powershell -NoProfile -Command "New-Item -ItemType Junction -Path '$(cygpath -w "$link")' -Target '$(cygpath -w "$repo/platform/node_modules")' | Out-Null"
else
  ln -s "$repo/platform/node_modules" "$link"
fi

cd "$here"
tsx=(node "$link/tsx/dist/cli.mjs" --tsconfig "$base/platform/tsconfig.json")
export NODE_OPTIONS=--max-old-space-size=512
"${tsx[@]}" scripts/papers/export_papers.ts --platform "$base/platform"
"${tsx[@]}" scripts/papers/record_parity.ts --platform "$base/platform"
