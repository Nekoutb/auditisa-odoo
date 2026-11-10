#!/usr/bin/env bash
# publish-release.sh: on the console server, as root. The developer's one command after build_release.sh.
#
#   publish-release.sh DIR "label"
#
# 1. upload-release.sh DIR      checks the bundle (no control-plane addon, the catalogue names it) and puts
#                               <sha>.tar.gz and <sha>.catalogue.json in the private releases bucket
# 2. register-release.sh DIR    registers it on the console with its SHA-256, and loads its catalogue
#
# The owner then sees "New version ready" on the Status page, and clicks Promote to Staging, then Promote to
# Production. Nothing is signed: the console's sign-in is the security, and each server installs the bundle
# only if its SHA-256 is the one registered here (sent with the heartbeat answer, which is authenticated).
set -euo pipefail
DIR=${1:?usage: publish-release.sh DIR [label]}
HERE=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
bash "$HERE/upload-release.sh" "$DIR"
bash "$HERE/register-release.sh" "$DIR" "${2:-}"
