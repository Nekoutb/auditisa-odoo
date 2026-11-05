#!/usr/bin/env bash
# Shellcheck on every script, then the dry-run mode of the provisioning scripts.
set -euo pipefail

mapfile -t scripts < <(git ls-files '*.sh')
uvx --python "${CI_PYTHON:-3.12}" --from shellcheck-py==0.11.0.1 shellcheck -x "${scripts[@]}"

bash scripts/provision/new_firm.sh --dry-run --db firm_lint --name "Cabinet Lint" --admin-email admin@example.invalid
bash scripts/provision/backup_firm.sh --dry-run --db firm_lint

# The guard must refuse the staging database, in dry-run as well.
if bash scripts/provision/new_firm.sh --dry-run --db ea_audit_odoo_staging --name x --admin-email a@example.invalid 2>/dev/null; then
  echo "new_firm.sh accepted the staging database" >&2
  exit 1
fi

# The firm server's recipe, the isolation test and the release signature, without a server.
bash .github/ci/firm-dry-run.sh
