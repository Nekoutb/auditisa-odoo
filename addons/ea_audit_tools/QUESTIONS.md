# Questionable behaviours found while porting the tools

Source: platform at commit 8725e6a. Only the owner rules (`docs/decisions.md`). "Ported" means the odd behaviour is kept as it is. "Changed" means the port differs, and the reason is given.

## A. Changed in the port: please confirm

| # | Platform | Port | Why |
| --- | --- | --- | --- |
| A1 | EQR passes `requireWrite` on TB, materiality, risks, CRA and SAD; only some actions refuse it (I-9, open) | Every tool write refuses `eqr-read-only` | Independence, and core already refuses it on the engagement. The owner should confirm against ISQM 2. |
| A2 | Tool writes check tenant and role; team membership is only in `proxy.ts` | Every write checks the role, then accepted team membership, then archive | The brief. Same codes. |
| A3 | `assertMutable` missing on significance, TB, AP comments; triggers refuse (I-9, open) | Checked everywhere, code `archived` | I-9 recommendation. Postgres triggers are not ported (I-4 open), so this Python guard is the only barrier against direct SQL. |
| A4 | The form fills `justification` with "Documented in P6.1" when empty, so the check never fires from the screen | No default: `justification-required` | The brief asks for a justification. |
| A5 | Clearly trivial range: spec C.7.11 says 0.5–10; code and D.8 say 3–5 | 3–5 | Owner's instruction. C.7.11 should be corrected. |
| A6 | `dismissPotentialRisk` and `clearFinding` silently do nothing on a decided row | `not-found` | A silent success on a refused write misleads the user. |
| A7 | Lead, SAD and sign-off exports not logged; errors collapsed to 401 or 500 (I-9, open) | Every export on the chatter; a refusal returns its own code with 403 | I-9 recommendation. |
| A8 | `linkRiskToIndex` accepts any `[A-Z0-9]{1,4}`, `addRisk` `{1,6}`, CRA `[A-Z][A-Z0-9]{0,2}`; an unknown index is stored | Only an index of the lead map, else `invalid-index` | Three regexes for one code; an unknown index lands on nothing. |
| A9 | `saveSignificance` strips with `/[^\d.]/`: "1,5" becomes 15 | A numeric field | The source's own comment on the shared parser says this bug inflated SAD figures. |
| A10 | CSV decoded as UTF-8 only: a French Excel CP1252 export loses its accents | UTF-8 with BOM, else CP1252 | Real exports. |
| A11 | `invalid-assertion` message lists five assertions | Lists six, with RO | Text drift since F041. |
| A12 | Client overrides: any firm writer, on any client | Must be on a team of that client, for reading and writing | The record rules cover every record. Stricter than the platform: confirm. |
| A13 | A b5 finding exists only as a misstatement | Also a line in the findings register, with the misstatement linked | m14 lists both in one table. Gates read by route, so nothing moves. |
| A14 | Hub: 14 tiles | m7's 16, plus Significant accounts and Findings as tiles: 18. Feeds follow m7 where they differ (Sampling E4.1, E1.2 against E4.1, E4.2, E4.4) | Mock-up. P6.2 and the findings had no tile. Unbuilt tools are greyed. |
| A15 | Program steps belong to the paper screens | A minimal `ea.audit.program.step` lives here | The presumed risks, `significant_risks_linked` and `material_sections_covered` need it. The papers addon should reuse it, not add its own. |

## B. Ported as they are: please rule

| # | Behaviour | Risk |
| --- | --- | --- |
| B1 | Materiality PBT = class 7 − class 6. SAD income before tax (`incomeFromTb`) also takes class 8 | Two "results before tax" on one file. |
| B2 | 56 (bank overdrafts) sits on the passif of the bilan and under lead index C, typed Assets. It is the one prefix where `bilan_totals` and the lead classes disagree (`test_the_one_known_exception_to_the_lead_classes_is_56`) | P6.2 sums C net, so an overdraft hides inside cash. 490 and 499 were aligned by F059, 56 was not. |
| B3 | Class 4 and 5 follow each account's sign on the bilan and the prefix on the lead schedule | The two totals do not reconcile line by line, by design; only the grand total does. |
| B4 | `evaluateB5` sums signed amounts, so opposite misstatements net before the UMT test | ISA 450 evaluates individually and in aggregate; offsetting can hide a breach. |
| B5 | m14's card compares uncorrected misstatements with performance materiality; the platform (UAT B50) with UMT = overall − performance | The port follows UMT. The mock-up should change, or the rule. |
| B6 | Materiality approval needs firm role partner and team membership, not this file's engagement partner. Rebuttal needs the engagement partner or delegate (F003) | A partner seated as manager can approve the figure the file depends on. |
| B7 | No self-review on materiality: a partner may generate and approve the same version | Other reviews refuse `self-review`. |
| B8 | Any writer may record the SAD conclusion, which alone satisfies C1.1's `sad` output; any writer may also grade or downgrade an ISA 265 deficiency | A staff member can move a significant deficiency to observation, which lifts the archive gate. |
| B9 | P6.1 needs any approved version, the planning gate the latest one (`test_a_late_revision_reopens_the_gate_but_not_the_paper`) | After a revision P6.1 still signs on the superseded figure while the gate is shut. |
| B10 | An invalid re-import marks the previous live version superseded though it stays current | The history shows a superseded version driving the file. |
| B11 | Version numbers are shared by pre-audit, post-audit and prior-year uploads | "Balance v3" can be the second working TB. |
| B12 | A prior-year upload is itself tested against the previous engagement's closing, for opening ties | The check compares the wrong periods for that timing. |
| B13 | Two comparatives: `leadSchedules` (prior engagement), `apLeadSchedules` (prior-year TB, else opening). The tool uses the second; the opening check uses `priorClosingsMap` | The prior year can read differently between screens. |
| B14 | The seed has no prefix 20, 74, 76, 80, while lead classes map several of these or the chart uses them | A 20x balance is on schedule L yet blocks `tb_mapped`, and F060 says class 20 must be reported, not blocked. |
| B15 | `cra_reliance_supported` ignores ITGC; `saveCraCell` applies it | A reliance saved before S2.5 concludes "not support" passes the gate. |
| B16 | RO is relevant by default on every row, income statement indexes included | m13 shows S.O. on revenue, so the preparer must clear it by hand. |
| B17 | Only an IR or CR change is journaled in CRA history; a changed basis is not | The written reason for reliance can change with no trace. |
| B18 | Materiality reflag marks items trivial with no "not pervasive" confirmation, which the route demands | A revision can set items aside that no one confirmed. |
| B19 | The deviation reason is appended to `performance_justification` with " — " | Two judgements in one field. Kept for F.1 data parity. |
| B20 | If E3.1 or E4.20 is out of scope for the complexity, the presumed risk has no section and no step | `significant_risks_linked` can then never pass on that file. Only through the step tools. |
| B21 | Comment says revenue fraud maps to E4.1; code uses E4.20 | Comment drift. Code followed. |

## C. Not in this milestone, so reduced

- Notifications: revisions and risk additions go on the chatter only. No mail from this addon.
- SCOT coverage and the S2.5 conclusion: `_ea_control_coverage` answers none and `_ea_itgc_state` none until those tools exist, so every "rely" needs a written basis.
- SAD entries are entered on the tool until the papers addon feeds them from step results.
- GL volume on P6.2, adjusting journals, `_ea_carry_forward_from`, the SAP tool: not built.
- S3.1 invalidation voids live signatures on any saved cell; the platform compares content hashes, which arrive with the papers addon.
