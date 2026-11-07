# Decision log

Decisions of the firm owner on the AuditISA rebuild on Odoo 19 Community. Numbers follow section I.2 of `Screen-transfer-specification.md`. Only the owner decides; a recommendation below is advice and binds nothing.

## Decided

| # | Decision | Consequences |
| --- | --- | --- |
| I-1 Tenancy | **One dedicated server per firm (2026-11-05), replacing one database per firm on a shared server.** Each firm has its own Odoo, PostgreSQL, filestore, secrets and address. | The migration script runs once per `tenant` row and loads into that firm's server (F.1). Backups, restores and updates are per firm. Record rules do not need to separate firms. Costs more per firm and needs a control plane: see the row below and `docs/runbook/`. |
| Control plane | **A separate Odoo 19 Community instance, with addon `ea_platform_admin`, shows every firm** (2026-11-05). It holds health figures only and has no way into a firm's server. Each firm's server only sends it a signed heartbeat. | Provisioning, rollouts (canary, then batches) and offboarding run from it, with Vultr and DNS behind interfaces. Security model and what stays shared: `docs/runbook/SECURITY-MODEL.md`. All of it has run in simulation only so far: `docs/runbook/PREREQUISITES.md`. |
| I-13 Production host | **Each firm on its own Vultr server, in the region chosen at onboarding** (follows from I-1). | Size and estimated cost per firm: `docs/runbook/PREREQUISITES.md`, prices to be confirmed. The rule that no client dump goes to staging stands. |
| Languages | **The whole tool works in French and English** (2026-11-05). Source strings in English, French in `fr.po`. | The onboarding wizard's language sets the firm's default; each user then chooses. |
| I-6 Grids | **Lists plus Excel import and export first.** Custom grids come later, only where needed. | The specification recommended OWL components. Its phase 4 range (36–53 pw) assumes those grids, so it should come down once the first tool has been built and timed. Risk R2 changes from build effort to user acceptance of the console-style tools. |
| I-12 Governing plan | **`Screen-transfer-specification.md` governs over `Migration-plan-Odoo19.md`**, with a budget of **129–190 person-weeks**. | Six addons (`ea_audit_core`, `_papers`, `_tools`, `_reports`, `_portal`, `_legal`, and optional `_uat`) and the `ea.audit.*` model prefix. The `ea_audit` module installed on staging follows the other plan: see O-3. |

- **One prior year for a file (F012, 2026-11-06).** Lead schedules, analytical review and financial analysis read the same N-1: a prior-year trial balance uploaded on the file, else the closing trial balance of the client's prior file, else the current openings, and the screen says which. On a prior file, equity reads before last year's result is carried (Négoce 2025: -58M in class 1, 22M still in classes 6-7), which the financial analysis adds back to read 80M.

## Provisional: working papers, owner to confirm

Applied in `ea_audit_papers` so that the build can proceed. Each is provisional, owner to confirm. Q numbers are those of `addons/ea_audit_papers/DESIGN.md`, section 8.

| # | Decision | Consequence |
| --- | --- | --- |
| Q1 Definition pinned on a signature | Store `definition_hash` on each signature; do not void on a wording change. | A new text adds a row in `ea.audit.paper.def` and retires the old one, so a signed paper can show what it was signed on. The screen flags a signature whose wording has since moved. |
| Q3 Migrated signatures | Verify on the platform before cutover (`paperContentHashTx` per active signature), then store a new-scheme hash. | Where the check passes the loader stores `content_scheme = 2` computed in Odoo. Where it fails the row keeps `content_scheme = 1`: never voided by comparison, reported instead. |
| Q4 Blank answers in the hash | Leave blank answers out of the new hash. | A save that adds an empty key voids nothing, in line with the history rule. |
| Q5 `value` type | `Text`. | Departs from spec D.12's `Json`; the tool families (`sad`, `itapps`, `psp:`, `dsp`) become real models in `ea_audit_tools`. |
| Q6 Names | Follow D.12: `ea.audit.paper.def`, `ea.audit.paper`, `ea.audit.paper.answer`. | Spec C.6.7's `ea.audit.paper.response` is not used. |
| Q8 Shadowed C6.2 | Use the `gam.ts` C6.2 text. | The `conclusion.ts` version stays in `data/papers_shadowed/` as source material; it is not loaded. I-9's row on C6.2 still awaits the technical desk's comparison. |

## Open decisions from the specification

Each is open until the owner rules. The specification itself recommends only on I-4 and I-5; the other recommendations were added when this log was written.

| # | Question | Recommendation | Why |
| --- | --- | --- | --- |
| I-2 Clients | Link `ea.audit.client` to `res.partner`, or keep it standalone? | Link it. | Contacts, portal users (I-7) and any later invoicing depend on partners; F.2 step 4 already assumes the link. |
| I-3 DOCX round-trip | Keep Word check-out and check-in with in-browser preview (needs LibreOffice headless for PDF preview), or move narrative papers fully into the paper component with PDF output only? | Keep check-out and check-in, without in-browser DOCX preview. Decide on LibreOffice separately after staging is resized. | Auditors keep their Word workflow and E.6 already drops the in-browser renderer. LibreOffice is heavy for the current 1.6 GB server. Moves effort in phase 3. |
| I-4 Immutability | Python guards only, or Python guards plus the existing Postgres triggers? | Both (specification's recommendation). | Audit evidence must hold against direct SQL and bugs in Python (R3). |
| I-5 Audit log | OCA `auditlog`, or a bespoke `ea.audit.activity` port with before and after JSON? | OCA `auditlog` (specification's recommendation). | `auditlog` exists on the OCA `server-tools` 19.0 branch (checked 2026-11-04). It has not been installed or tried here. Compare it with the F.1 rule that `activity_log` is loaded as-is before relying on it. |
| I-7 Portal | Odoo portal on the same host, or PBC uploads by email only? | Odoo portal. | Uploads stay on the engagement with their trail. `/api/email/inbound` is effectively a no-op today (R10), so email is not a working path to fall back on. |
| I-8 MFA and passwords | Enable `auth_totp` for partners and firm admins? The 2026-07-09 decision descoped mandatory 2FA. | Install `auth_totp` and require it for partners and firm admins. | They sign off and administer the firm, and TOTP is standard in Community. Secrets are not migrated, so users enrol again at cutover in any case (F.2 step 3). |
| I-9 Rule inconsistencies | Which side is right in each case listed in R10? | See the table below. | Otherwise bugs get ported as features. |
| I-10 Scope cuts | Drop the UAT workbook, the marketing landing page, GL analytics entries 25–28 marked unavailable, the retired independence campaign, and the unused SadBoard component? | Drop all, keeping independence campaign data as read-only history (E.6, F.2). Keep the UAT scenarios as the acceptance script outside the product. | None of these serves a live audit file. The UAT list is still needed for G.3. |
| I-11 Parallel run | How long do Next.js and Odoo run side by side, and which firm and engagements pilot first? | Pilot one firm on new engagements only. Run in parallel until that firm has taken one engagement through issuance and archive on Odoo; fix the date when M4 is near. | An engagement should not change systems mid-file; archive is the last gate to prove. |

### I-9 in detail

Each row is a separate ruling for the owner.

| Inconsistency (R10) | Recommendation |
| --- | --- |
| `/resources` page requires firm admin, `teamWorkload` requires manager | Follow the lib: manager and above. Workload is a manager's tool. |
| Portal-contact form shown to every role, `addPortalContact` refuses below senior | Follow the lib: hide the form below senior. |
| `/uat` verdicts, `restoreVersion`, `addComment`, `addRisk`, `dismissPotentialRisk`, `completeStep`, `respondToEngagement`, SAD `save`/`saveMeta`, `createDataset` check tenant only, so a read-only member reaches them | Require write access on all, except verdicts if the UAT workbook is dropped (I-10). A read-only member must not change a file. |
| EQR not blocked on SAD and SAP saves | Block it. The EQR reviews and does not prepare; the owner should confirm against the firm's reading of ISQM 2. |
| `/api/steps/[id]/evidence` is outside the proxy's team gate (tenant RLS only) | Apply the team rule, as for every other engagement record. |
| `assertMutable` missing on ap-comments, significance, tb, subledgers, planning-ras, task-notes (triggers still refuse) | Port the check everywhere, so the user gets a proper refusal and the trigger remains the backstop. |
| Lead-schedule, SAD and sign-off-matrix exports not logged, errors collapsed to 401 or 500 | Log every export and return real errors. |
| `/api/email/inbound` effectively a no-op since F008 | Do not port it. Add inbound filing only if I-7 asks for it. |
| `advanceToPlanning` and `closePlanning` have no rank check beyond `requireWrite` | Needs the owner's judgement: gates 1 and 2 already demand partner signatures, so a rank check adds control but may change who can press the button. Recommend manager and above. |
| Two ToC sample-size tables (`lib/toc-sampling.ts` for the tool, `lib/sampling-params.ts` for task-level sampling) | Technical desk compares them with the firm's methodology and keeps one. Port only that one. |
| C6.2 defined twice (`gam.ts` wins) | Port the `gam.ts` version after the technical desk has compared the two. |
| E5.1–E5.5 conditional but no trigger activates them | Technical desk defines the triggers, or they become always available. Do not port as permanently inactive. |

## Operational questions raised in phase 0

Not in the specification's list. Found while writing the scripts, and also open.

| # | Question | Recommendation |
| --- | --- | --- |
| L-1 Languages | **Complete in English and French.** English is the source of every string, `i18n/fr.po` holds the French (`_t` in OWL, `_`/`env._` in Python, translatable XML); a definition or a pure service may carry its own en/fr pair. | Each user picks a language in the top bar, saved on the user. A firm's default is its company partner's language, set at onboarding (`new_firm.sh --lang`). Letters, reports, legal documents and exports follow `report_language` on the engagement, default the firm's. New English legal wording stays marked "(to validate)" until the jurist flips `ea_articles_validated`. Rebuild fr.po with `scripts/i18n_merge.py` from an export and `i18n/fr_glossary.json`; deploy with `--i18n-overwrite` once so existing databases read the new msgids. `ea_audit_ui/tests/french_scan.py` refuses hard-coded French. |
| O-2 Server access to the private repository | `deploy-staging.sh` clones over SSH. | Create a read-only deploy key for `Nekoutb/auditisa-odoo`, stored at `/root/.ssh/auditisa_odoo_deploy` on staging. |
| O-3 The `ea_audit` module on staging | `ea_audit_odoo_staging` holds the sketch module from the superseded plan, with fictional demo data. Keep it alongside the new addons, or start a clean staging database? | Clean database when `ea_audit_core` first deploys. Until then keep `/opt/ea-odoo-addons` in `addons_path`, because Odoo needs an installed module's code. |
| O-4 Odoo build on staging | Staging runs nightly tarball 19.0-20261103 (installed by the other session). CI runs a pinned commit of branch 19.0. | Move staging to the same pinned commit when convenient, and bump both together. |
| O-6 Protecting firms from the operator | Must firms be protected from the operator? The owner holds every key for now. | Owner's decision. Options, including firm-held keys: `docs/runbook/SECURITY-MODEL.md`. A per-firm break-glass log exists either way. |
| O-5 Specification correction | F.3 and G.2 say gate results are in `/api/engagements/[id]/status`. That route returns phase progress and tasks only, with no gate keys. | Correct the specification. `scripts/parity/README.md` obtains gate results another way. |
