# Parity fixtures for gates 1 and 2

Plan only: nothing has been extracted yet. This describes how AuditISA DEV data becomes the fixtures that phase 2 must pass ("Gates 1 and 2 pass on migrated UAT data", spec H, G.2, F.3).

## What a fixture must prove

For one engagement, the Odoo method `_gate_results(kind)` returns the same pass or fail per key as the current tool.

| Gate | Current function (`platform/lib/gates.ts`) | Keys |
| --- | --- | --- |
| 1, acceptance to planning | `acceptanceGatesTx` | `d31_form_complete`, `d31_checks_passed`, `d31_partner_signed`, `engagement_partner_designated`, `review_notes_cleared` |
| 2, planning to execution | `planningCloseGatesTx` | `materiality_approved`, `p22_partner_signed`, `p52_partner_signed`, `s31_partner_signed` (each only where the task is active on the file), `p72_partner_signed`, `cra_reliance_supported`, `significant_risks_linked`, `rebuttals_approved`, `material_sections_covered`, `tb_mapped`, `review_notes_cleared` |

**The status route does not hold this.** F.3 names `/api/engagements/[id]/status` as the source, but that route returns phase progress and tasks, and no gate keys. It also returns client and staff names. The gate functions themselves are therefore the source (see step 3).

A fixture is only useful if it covers failures as well as passes. Selection aims for at least one engagement failing each key, and one passing all keys. Any key with no failing example on DEV is reported, then covered by an edited copy of a fixture marked `"synthetic": true`.

## Rules

- **Read-only on DEV.** Reads go through a role with `default_transaction_read_only = on` or inside `BEGIN TRANSACTION READ ONLY ... ROLLBACK`. Nothing is written on DEV: no temporary tables, no calls to transition functions (`advanceToPlanning`, `closePlanning`).
- **DEV is treated as client data.** It was cloned from production at one point, so names on it can be real, whatever the engagement's label says.
- **Raw extracts never reach the repository or staging.** They stay on the DEV server under a root-only folder and are deleted once the sanitised output has been checked (E.7's rule for client data on hosts).
- **Only sanitised output is committed**, to `scripts/parity/fixtures/`, after passing the checks in step 5.
- **Not touched:** PROD and the production database. No binary payloads are extracted, because gates 1 and 2 only read their existence and sign-offs.

## Plan

Each step is run when the owner has approved the extraction.

1. **Freeze a baseline.** Record the DEV commit and migration count. The fixtures are valid for that commit, and re-extracted when `lib/gates.ts` or a table it reads changes (risk R11).
2. **List candidates, ids only.** Query engagements in phases acceptance, planning and later, with phase, complexity and tenant id. The owner confirms which tenants are the UAT firms; other tenants are out of scope.
3. **Capture the gate results.** A small script, kept with the current tool and never committed here, calls `acceptanceGatesTx` and `planningCloseGatesTx` for each engagement in a read-only transaction with `app.tenant_id` set for RLS, then rolls back. `acceptanceGates` and `planningCloseGates` cannot be used directly, because they need a logged-in session. `detail` is kept for review notes (task codes and a count) and `href` is dropped.
4. **Extract the inputs for each engagement**, limited to the tables those functions read (below), into raw JSON on the server.
5. **Sanitise, then check.** See below. The output is copied off the server only after the checks pass.

Tables read for the inputs, to be confirmed against `lib/gates.ts` and `lib/planning-ras` at the baseline commit:

- Engagement: `engagement`, `team_member`, `membership`, `app_user`, `file_item`, `firm_signoff_policy`, `firm_task_signoff_rule`.
- Gate 1: `form_response` (P1.1), `document`, `signoff`, `review_note`.
- Gate 2: `materiality`, `risk`, `risk_lead_index`, `program_step`, `risk_response`, `cra_assessment`, `scot`, `scot_index`, `scot_control`, `wcgw`, `wcgw_control`, `trial_balance`, `trial_balance_version`, `trial_balance_row`, `syscohada_grouping_rule`, `client_grouping_override`.

## Sanitising

Rules, applied per column by an allow-list: a column not listed is dropped, so a new column cannot leak by default.

| Data | Treatment |
| --- | --- |
| UUIDs | Replaced by stable pseudonyms such as `eng-001`, `user-003`, using one mapping per run. The mapping stays on the server and is deleted with the raw extract. |
| Firm, client, engagement, party names | Replaced: `Firm A`, `Client 001`, `Engagement 001`. |
| User names, e-mails, logins | Dropped. Users keep a pseudonym, role and rank only, because rules read those. |
| Free text (conclusions, justifications, `cr_basis`, `fsNote`, comments, notes) | Replaced by `"[text]"` when non-empty and `""` when empty. Gates test only whether text is present. |
| Answers in `form_response` | Choice values are kept when they come from the paper's option list (for example, the P1.1 conclusion). Every other value gets the free-text treatment. |
| Amounts | Multiplied by one random factor per engagement, then rounded. Zero stays zero and signs stay. Gate 2 tests mapping and approval status, not amounts; materiality and tool parity in phase 4 will need their own plan. |
| Trial balance accounts | Account numbers kept, because `tb_mapped` depends on them. Account labels replaced by `"[account]"`, since a label can name a client's bank or supplier. |
| Dates | Shifted by one offset per engagement, so order and intervals stay. Fiscal year is recomputed from the shifted date. |
| Hashes, tokens, secrets | Dropped. |

Checks before anything leaves the server, all of which must pass:

1. A list of every real name from `tenant`, `client`, `related_party`, `app_user` and `engagement` is searched for across the output, case and accent insensitive, and must give no hit.
2. No e-mail address pattern, phone number or NIU/RCCM-like identifier appears in the output.
3. Every string value is either in the allow-list of enums and codes, or a pseudonym or placeholder.
4. **The owner reads a sample before the first commit**, since automatic checks cannot see a name spelled differently.
5. After sanitising, the current gate logic is the reference: an expected result that depended on removed data stops the fixture, rather than being edited to pass.

## Sample format

One JSON file per engagement, `scripts/parity/fixtures/<baseline>/eng-NNN.json`. All values below are invented.

```json
{
  "format": 1,
  "source": { "system": "auditisa-dev", "commit": "<sha at baseline>", "extracted": "2026-11-XX" },
  "synthetic": false,
  "firm": { "ref": "firm-a", "name": "Firm A", "signoff_policy": { "self_review": false } },
  "users": [
    { "ref": "user-001", "role": "partner" },
    { "ref": "user-002", "role": "manager" }
  ],
  "engagement": {
    "ref": "eng-001",
    "name": "Engagement 001",
    "client": "Client 001",
    "phase": "planning",
    "complexity": "standard",
    "period_end": "2031-12-31"
  },
  "inputs": {
    "team_member": [
      { "user": "user-001", "team_role": "engagement_partner", "accepted": true }
    ],
    "file_item": [
      { "code": "P1.1", "active": true, "material": null }
    ],
    "form_response": [
      { "code": "wp:P1.1", "field_key": "conclusion", "value": "accept" },
      { "code": "wp:P1.1", "field_key": "basis", "value": "[text]" }
    ],
    "signoff": [
      { "code": "P1.1", "role": "partner", "user": "user-001", "status": "active", "signed_at": "2031-03-02T10:00:00Z" }
    ],
    "review_note": [
      { "code": "P1.2", "status": "closed" }
    ],
    "materiality": [
      { "version_no": 2, "status": "approved" }
    ],
    "trial_balance_row": [
      { "version": 1, "account": "411000", "label": "[account]", "balance": 1234567.0 }
    ]
  },
  "expected": {
    "gate1": [
      { "key": "d31_form_complete", "ok": true },
      { "key": "d31_checks_passed", "ok": true },
      { "key": "d31_partner_signed", "ok": true },
      { "key": "engagement_partner_designated", "ok": true },
      { "key": "review_notes_cleared", "ok": true }
    ],
    "gate2": [
      { "key": "materiality_approved", "ok": true },
      { "key": "p72_partner_signed", "ok": false },
      { "key": "tb_mapped", "ok": true },
      { "key": "review_notes_cleared", "ok": false, "detail": "1 · S3.1" }
    ]
  }
}
```

Column names under `inputs` are illustrative and follow the source tables at the baseline commit.

The Odoo test in phase 2 loads each file through the ORM as `TransactionCase` data, calls `_gate_results("acceptance")` and `_gate_results("planning")`, and compares the result per key. Comparison uses `key` and `ok` only, plus `detail` for review notes.
