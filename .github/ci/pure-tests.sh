#!/usr/bin/env bash
# Runs the tests of addons/*/services in an environment with pytest and requirements.txt only.
# Odoo is not importable there, so a service that imports Odoo fails here.
set -euo pipefail
shopt -s nullglob

dirs=(addons/*/services)
if [ ${#dirs[@]} = 0 ]; then
  echo "No addons/*/services yet: no pure tests to run."
  exit 0
fi

rc=0
uv run --isolated --no-project --python "${CI_PYTHON:-3.12}" \
  --with-requirements requirements-dev.txt --with-requirements requirements.txt \
  pytest "${dirs[@]}" || rc=$?

# Exit code 5 means pytest collected nothing.
if [ "$rc" = 5 ]; then
  echo "::notice::addons/*/services exist but hold no test yet"
  exit 0
fi
exit "$rc"
