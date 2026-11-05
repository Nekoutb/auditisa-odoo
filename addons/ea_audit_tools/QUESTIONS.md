# Questionable behaviours found while porting the tools

Source: platform at commit 8725e6a; rows from A16 and B22 on, at 371a0b2. Only the owner rules (`docs/decisions.md`). "Ported" means the odd behaviour is kept as it is. "Changed" means the port differs, and the reason is given.

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
| A16 | Drill: an overlay panel, one page of 100 at a time, capped at 500 a page | `gl_drill_down` keeps that shape and cap; the screen opens Odoo's list on a domain made of the same filter (`drill_filter`, a search-only field running the same WHERE), 100 lines a page, with its search and pivot | Native screens only. The list can page through everything the filter matches, as the panel could. |
| A17 | Every figure on screen is a clickable cell | Results are server-rendered tables; a cell is drilled by typing its account and month into the fields under the table, then Open the lines | No OWL. Same filters as the source's cells. |
| A18 | A lead-schedule figure arrives selected and already drilled (UAT B140) | It arrives selected with the reconciliation on the page; one click on Lines behind the figure opens the list | A wizard cannot open two screens at once. The reconciliation (B68) is shown without that click. |
| A19 | Entry, correlation, drill and picker only check the dataset's team (`requireChildRead`) | All answer `no-dataset` unless it is a ledger of this file | Same reads, one rule. A file's non-ledger dataset gave empty tables there. |
| A20 | An impossible date in the drill (31/02) passes the JS check, then fails in Postgres: `analytics-failed` | `invalid-date` | The cause is the user's input, and the code exists. |
| A21 | Insights live on the analyzer page (GlInsightsBoard) and always read the CY ledger | They are the console's fourth tab, and still read the CY ledger whichever ledger the console has open | The brief's tabs. The source's choice of ledger is kept. |
| A22 | Weekday, lag and matrix load every raw row into memory, in no stated order | Read in batches of 2 000 by row number | RAM. "First readable pair of a journal" is therefore in file order. |
| A23 | No Excel export of an analytic | Extract to Excel on the analytics tab, logged like every export | The brief. |
| A24 | Walkthrough and close-process answers are key-value rows; `invalid-key` guards the keys | Real fields on the SCOT and on `ea.audit.fscp`, the same 14 and 18 questions; a stray field is `invalid-field` | Native forms. Blank clears, as in the source. |
| A25 | Control coverage also reads `control_test` rows until E1.2 concludes | Same, since the second integration: `ea.audit.control.test` with `record_test`, a deviation carrying its decision and its consequence | A control with no test and no conclusion counts as neither effective nor failed. |
| A26 | The S2.5 conclusion is an answer on the paper | The answer on the paper and `itgc_state` on the engagement are one: each writes the other, once | The CRA reads the field; the paper's history and hash read the answer. |
| A27 | `todPreview` and `musPreview` return `{ok: false, error}` | They raise the same codes | One way of refusing. |
| A28 | Engine worksheets are filed as a versioned document on the paper | Kept on the run and downloadable from it | The document model belongs to the papers addon. |
| A29 | Reconcile is disabled when the E4 paper is not on the file | The method also refuses `recon-task-missing` | A disabled button is not a control. |
| A30 | PBC upload exists only on the portal | The firm can also record a document received, through the same method, and its bytes land where a contact's do | Paper originals still reach the firm. Please confirm, now the portal exists. |
| A31 | An accepted PBC becomes a document and version | The same when `ea_audit_portal` is installed; an `ir.attachment` on the task when only the tools are | The document model is in the reports addon. |
| A32 | Portal contacts are user accounts with an invitation | The same with `ea_audit_portal`, which extends the tools' model. The link is shown to whoever created the contact, who passes it on | No mail on staging. |
| A33 | The firm's SAP percentages are on the tenant, with a settings screen | `ir.config_parameter` through `set_thresholds`, firm administrators only; screen under Firm settings and on the SAP board | One database per firm. |
| A34 | The template download is a CSV of headers | An `.xlsx` of the same headers | Lists and Excel. |
| A35 | The E3.1, ToD and ToC workbooks have a long fixed layout | Same tabs and data, condensed text and layout. E1.1 ITGC and the full E1.2 workbook are not ported: the register and samples export instead | Economy. The firm should check the condensed papers before relying on them. |
| A36 | Eight templates, OHADA checklist and E1.1 included | The E1 and E3 blanks, the four shipped E4 papers, and a generic paper per other E4 task. The checklist and E1.1 are not offered | The checklist's 36 notes need their own port. |
| A37 | A hub of tiles for these tools did not list SCOTs, ITGC, the close, design, programs, overrides or potential risks | Tiles added; the analyzers are a second page of tiles | They had no way in without the papers addon. |
| A38 | PBC "red after 14 days" applies to any row with an age | Only to a request still unanswered | An accepted document is not late. Confirm. |

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
| B22 | Analytic 16's exception text says class 5 is a debit account; its SQL leaves class 5 out (UAT B69) | The catalogue contradicts the note beside it. Text and SQL both kept. |
| B23 | `pairMax` is a knob of analytic 17, but the route's `readParams` drops it and no screen offers it | Always 3. Kept: the port drops it at the same place. |
| B24 | The spec says analytic 24 tests preparer = reviewer; the code tests preparer = approver | Code followed. |
| B25 | Analytic 22's exception reads "value posted by a preparer with no identity", but `exceptions` counts lines | The count is not the value the text announces. |
| B26 | Analytic 18's exceptions count field gaps over a population of lines, and no-account or no-JE can never fire: the projection rejected those rows | The share can pass 100 %, and two columns are always nil. |
| B27 | Analytic 25 needs `jeDate` though it can never run: unmapped, it blames the mapping | Mapping the column only changes the reason. |
| B28 | Insights have their own date reader: dd/mm always, and 31/02 or 03/25/2025 roll over; the projection refuses those and reads mm/dd. Excel serials become year 45000 | On such files the weekday and lag insights disagree with analytics 7 and 8. |
| B29 | Insights read the raw rows, rejected lines included, and count a negative lag in the same-day bucket; analytic 8 flags it as an exception | Two answers to one question on one screen. |
| B30 | Two Pearson functions: analytics need 3 points, insights 2 | Two months correlate at ±1 in one place and not at all in the other. |
| B31 | Lead-figure links keep digit-only accounts and the first 50, silently; a selection above 25 is then refused by the entry analysis | An alphanumeric account or a wide schedule shows a gap that is not in the ledger. |
| B32 | `linkScotIndex` accepts any `[A-Z0-9]{1,4}`, so an unknown index is stored; `saveDsp` uses another pattern (A8 covers risks and CRA only) | A SCOT can feed an index that does not exist. |
| B33 | ToC minimums come from `tocSuggested`, while `ATTRIBUTE_SAMPLE_SIZES` is a second table with other figures | Daily 25 or 60 against 30, monthly 2 against 4. |
| B34 | `musPreview` sizes at TE/3, `planTod` from the audit-risk table | Two sizes for one population. |
| B35 | `todPreview` needs a single amount column; `todSideView` also takes a debit/credit pair (UAT B30 fixed one of them) | The preview refuses a ledger the workbook reads. |
| B36 | ToD reads the raw rows, rejected lines included; JE selection and the analytics read the projection | The populations can differ on one ledger. |
| B37 | **`stableStartFraction` hashes the engagement id. Ids change at migration (UUID to integer), so a migrated file draws a different ToD sample from the same ledger** | **Pending the owner's ruling.** Until then today's behaviour stays, and the migration rule is recorded below: a migrated file keeps the samples it drew. Only a new draw after migration differs. |
| B38 | Redraw after testing goes by team rank; deletions by firm role | A firm senior seated as staff can delete a control but not redraw. |
| B39 | A CRA not assessed is the tightest for SAP (high), and moderate for ToD | One gap, two defaults. |
| B40 | A reconciliation difference reads red above 0.5 but raises a finding only above clearly trivial, and through route b4, not b5 | A small visible difference with no record. |
| B41 | The preliminary review reads the prior engagement's TB, ignoring a prior-year upload; the lead schedule prefers the upload | Adds to B13. |
| B42 | JE selection never offers out-of-hours testing, as the import has no time of day | ISA 240 users may ask for it. Stated honestly on the screen in the source only. |
| B43 | A firm-wide holiday can be added by any writer | A firm setting without a firm role. |
| B44 | Editing a walkthrough or control always voids S1.x and S2.x signatures here; the source compares content hashes | Stricter, until the papers addon brings hashes (see section C). |

## Migration rule on drawn samples (B37, pending the owner's ruling)

The start point of a ToD plan stays `stable_start_fraction(str(engagement id), index, ledger sha)`. The migration script must carry each file's drawn ToD and ToC samples across as data and must not redraw them, so what was tested on a migrated file stays what was tested. A plan worked out again on that file after migration starts elsewhere, because its id changed. If the owner rules that it must reproduce, the old UUID has to be stored on the engagement and read here instead of the id.

## Second integration: what changed behind the ported rules

- **E4 scope (F010).** `_ea_e4_out_of_scope` reads S5.5: an E4 task is left out while it holds an account nothing was designed on, is not started and has no step. Nothing is written, so a design brings it back. Lists, the Forms tile and `tasks_addressed` all read it. **Stricter than the source on the lists, looser on the gate:** the source still counted such a task as untouched at the archive, though no list showed it. Please confirm.
- **`tasks_addressed`.** A paper its preparer signed is not untouched, even with no answer stored: P7.2 keeps its answers on its summary.
- **Steps.** `complete` and `uncomplete` (completeStep) were missing from the first port, so a programme could never close from the screens. They are on the Programs list now. Field work is not refused before execution for `mark_na`, as in the source.
- **No separate "close execution".** As in the source, `issue_report` moves execution to conclusion, under the completion gates, and `archive_engagement` moves conclusion to archived. A step between them would open C6.x before the report, which `phase_still_open` holds back. Both are on the engagement's form and the conclusion board.
- **`controls_concluded`.** Open is design not evaluated, or no test recorded. An imported E1.2 grid with tested rows counts as the record of the test, which the source's rows did not, since the grid is how results arrive here (I-6).

## C. Reduced, or not built

- Notifications: revisions, risk additions, SCOT assignment and PBC requests go on the chatter only. No mail from this addon.
- SAD entries are entered on the tool, not fed from step results.
- GL volume on P6.2, adjusting journals, `_ea_carry_forward_from`: not built.
- S3.1 and the SCOT papers void live signatures on any saved change; the platform compares content hashes, which arrive with the papers addon.
- The E1.2 test grid is imported from Excel, not edited on screen (decision I-6).
- The hub's last three tiles are live. The review-notes tile is a list with no reply box: a note is answered on its paper.
