# Questions for the owner and the technical desk

Behaviour found while porting `lib/report.ts`, `letters.ts`, `legal.ts`, `alerte.ts`, `completion.ts`, `deficiencies.ts`, `archive-checklist.ts` and `pbc.ts` at commit 371a0b2. "Kept" means the source's behaviour stands in the port; "changed" means the port departs from it, and why. Nothing here is decided.

## For the firm's jurist

1. **Article numbers.** Every article number printed in a generated document, a deadline basis, a stage basis or a screen carries "(à valider)". The source marked only some. The switch `ea_articles_validated` on the company lifts all of them at once when the workbook is validated; numbers in a document already generated stay as printed. To confirm: is one switch enough, or must each number be validated separately?
2. **First reply to the alert letter.** 30 days (2014 reading of arts. 150 and 153, F051), versus 15 days in the 1997 text. Kept at 30 and marked.
3. **Art. 525 certification.** The source holds C5.10 as a paper only, with no generated document. The port generates one, worded from the form the source's header records from two signed attestations (Togo 2019, Côte d'Ivoire 2025). The wording is mine and needs the jurist's reading before anyone signs it.
4. **Art. 525 threshold.** Ten persons above 200 employees, five at or below (F058). Kept and marked.
5. **Equity breach deadline.** Four months after the latest lawful meeting when the meeting date is unknown (`equityCheck`). Kept; is that reading right for a SARL as well as an SA?
6. **« Nous certifions » on an adverse opinion.** F049's wording reads "nous certifions que … ne sont pas réguliers". Kept as decided on 2026-10-27; it reads oddly and the jurist may want to look at it again.

## Changed from the source

7. **Criminal facts: the letter is now partner-only too.** The source restricts `fait_delictueux` to partners but files the letter as an ordinary document on C5.6, which any team member could open and which the export carried. Here the document and its bytes follow the partner rule, and the export leaves it out below partner. The manifest lists its title for everyone on the team: should it?
8. **Dates on the report.** The source printed "Fait le 2026-03-31"; the port prints DD/MM/YYYY. Other legal documents keep the source's prose date ("31 mars 2026").
9. **French articles before organ names.** The source built "à l'gérant", "l'conseil d'administration" and "Au administrateur général" by plain concatenation. The port uses the papers' article resolver: "au gérant", "au conseil d'administration", "à l'administrateur général". Note the board's SARL vocabulary still reads "gérant (la SARL n'a pas de conseil)".
10. **EQR's answers: "last written by" reads the answer history**, not `write_uid`, which moves with any later flush of the row.
11. **Document bytes after archive.** A generated document's attachment and the manifest's attachment refuse write and delete once the file is archived, sudo included. The source's bytes were in a row under the same triggers.

## Kept, but questionable

12. **Invalidated signatures count for the archive paper gates.** `paperGapsTx` tests `voided_at` only, so a signature invalidated by a changed input still counts as prepared or reviewed, while the EQR gate excludes both. Should an invalidated signature block the archive?
13. **`deficiencies_communicated` looks only at grade `significant_deficiency`.** A material weakness graded otherwise never blocks; and any date with a recipient passes, including a date after the archive deadline.
14. **Four completion keys test existence, not content.** `disclosure_checklist` needs a tick, but `partner_conclusion` accepts an empty text and `points_forward` too. A partner could pass the gate with a blank conclusion.
15. **`subsequent_events` needs a date after the period end and the report date**, with no limit on how far past it. A reviewed-to date years ahead passes.
16. **Report date.** No check that it follows the period end, or that it is not in the future: only that the reviewed-to date reaches it.
17. **`set_legal_dates` can set `report_date` on a file** (`coalesce` in the source) outside `issueReport`. The screen here offers no such field; the method keeps the parameter. A report date set that way makes `report_issued` green with no opinion and skips the gates. Should the parameter go?
18. **Retention report is firm-wide for manager and above**, whatever the team: the only read here that crosses F008. It shows client, year and dates. To confirm.
19. **Retention year arithmetic.** The SQL interval is used, as in the source's stamp: 29 February plus 10 years gives 28 February, whereas the unused `retentionDate` in the source gives 1 March. Only the stamp matters.
20. **A file with no retention policy** falls back to ten years.
21. **Mid-file report generation.** `generate_audit_report` runs after `issue_report`, under the same guard, so a refusal there leaves nothing because Odoo rolls back the request. In the source they were two transactions, and a failure in the second left the file issued with no report.
22. **Alert: a discontinuation writes no letter**, and a resume files none either. Kept. The resume also resets the deadline from today with no event date.
23. **Alert variant.** A SAS follows the SA flow; `board_invited` text names "le président du conseil d'administration" even on a SAS or an SA_AG, which have none. Kept as the source's wording; the jurist should reword it per form.
24. **Stage `reply_recorded` has no letter on the SA path**, and `board_deliberated`, `ag_communicated`, `closed` none on either: the letters exist for four stages only. Kept.
25. **Regulated agreements have no edit or delete**, in the source as here: a mistaken entry stays and prints in the special report.
26. **PBC upload replaces the previous upload silently** while the status is not accepted; the earlier bytes stay as an attachment but nothing points to them. Trail only.
27. **A portal contact sees requests of every engagement of the client**, including an archived one, and may still upload until it is accepted in the source; here an archived file refuses (`archived`).
28. **PBC file downloads.** A contact's upload is readable by every contact of the same client. To confirm.
29. **Portal contacts have no way of being removed or disabled** in the source. Kept: an ex-employee of the client stays in until a firm administrator archives the user.
30. **Contact form in the source was shown to every role, `addPortalContact` refused below senior** (I-9 row). Followed the recommendation: the buttons are hidden below senior.

## Depends on work elsewhere

31. **`controls_concluded` reads nothing yet.** The controls register (SCOT, control tests) is not on `dev`. `_ea_open_control_rows` returns no row, so this gate is green until `feat/tools2` extends it. The file can archive without it: wire it before pilot.
32. **FS tie-out is reduced.** `run_fs_tieout` checks the balance and the equilibrium of the closings only. The SIG cascade and the comparison with the client's statements (`clientDiffs` of `lib/fs-tieout.ts`) are not ported. If `feat/tools2` brings them, override `_ea_fs_tieout`.
33. **Final analytical review is reduced.** The record stores the 30 largest closings; `lib/analytics.ts` lines are not ported.
34. **`_ea_paper_is_complete` for C4.1 and C6.2** uses the papers' completeness on the resolved definition, the same call as signing.
35. **I-4 is still open.** The port installs database triggers on the evidence tables (`ea_audit_archive_lock`) in addition to the Python guards, as the specification recommends. A test elsewhere that writes to a row of a file it has archived by hand now fails at the database; `ea_audit_core`'s archived-file test does not, because Python refuses first.
36. **The notice model.** `ea.audit.notice` carries the source's notification kinds that the bell's fixed selection cannot hold; a bell line is added when `ea_audit_ui` is installed. Portal contacts see notices nowhere yet: requests show on `/my/pbc`.
37. **Staging has no `python-docx`**, and the port needs none: the `.docx` is written with the standard library. It carries paragraphs and three styles, no tables and no image, so the logo prints on the PDF only.
38. **Export bundle.** Written to a temporary file then streamed, one artefact at a time. The source's `README.txt` is not reproduced, and answer history is not in the bundle.
