# AuditISA on Odoo 19 Community

Rebuild of the AuditISA audit platform as Odoo 19 Community addons.

- Tenancy: one database per firm.
- Grid-heavy tools: standard lists plus Excel import and export first; custom grids later only where needed.
- Specification: `docs/Screen-transfer-specification.md`, inventory: `docs/Screen-inventory.xlsx`.
- Branches: `dev` (staging, test.auditisa.com), `main` (production). Feature branches merge into `dev`.

## Working in this repository

- Decisions: `docs/decisions.md`.
- CI (`.github/workflows/ci.yml`): pure tests in `addons/<addon>/services/tests/`, which must run without Odoo, then Odoo tests in `addons/<addon>/tests/`. Odoo is pinned in `.github/actions/setup-odoo/action.yml`.
- Scripts: `scripts/provision/` (new firm database, backup), `deploy/deploy-staging.sh` (staging deployment), `scripts/parity/README.md` (parity fixtures plan). `.github/workflows/ops-smoke.yml` rehearses the provisioning and deployment scripts on a throwaway runner when they change.
