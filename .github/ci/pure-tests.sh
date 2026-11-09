#!/usr/bin/env bash
# Runs the pure tests in an environment with pytest and requirements.txt only.
# Odoo is not importable there, so a service that imports Odoo fails here.
# Each directory gets its own pytest process: two addons both import a top-level
# package named `services`, which clash in one process.
set -euo pipefail
shopt -s nullglob

dirs=(addons/*/services/tests addons/*/tests_pure addons/*/tests/pure deploy/practice/tests deploy/firm/tests)
if [ ${#dirs[@]} = 0 ]; then
  echo "No pure tests yet."
  exit 0
fi

failed=0
for dir in "${dirs[@]}"; do
  echo "::group::$dir"
  rc=0
  uv run --isolated --no-project --python "${CI_PYTHON:-3.12}" \
    --with-requirements requirements-dev.txt --with-requirements requirements.txt \
    pytest -q "$dir" || rc=$?
  echo "::endgroup::"
  # Exit code 5 means pytest collected nothing.
  if [ "$rc" != 0 ] && [ "$rc" != 5 ]; then
    echo "::error::$dir failed (pytest exit $rc)"
    failed=1
  fi
done
exit "$failed"
