# ea_audit_papers: model design

Status: design only. No model and no OWL component exists yet, and the addon has no
`__manifest__.py`, so Odoo ignores the directory. Both wait on `ea_audit_core`, whose
`ea.audit.engagement`, `ea.audit.file.item` and `ea.audit.signoff` this design assumes.

What exists: `data/` (definitions and token tables), `services/` (pure rules),
`tests_pure/` (parity with baseline `bd3af7e`). Regenerate with
`scripts/papers/run_baseline.sh`; never edit `data/` by hand while the TypeScript is
still the source.

## 1. Definitions

| File | Content |
| --- | --- |
| `data/papers/<code>.json` | `{code, source, definition}`, unresolved: tokens, `forms`, marks as written |
| `data/papers/index.json` | baseline commit, counts, `definition_hash` per code, lint results |
| `data/papers_shadowed/` | C6.2 of `lib/papers/conclusion.ts`, defined again in `gam.ts`, which wins in `ALL_PAPERS` |
| `data/group_defaults.json` | the default paper of the 24 tasks with no definition of their own |
| `data/standards_refs.json` | `REFS`: token, edition, `[en, fr]` |
| `data/legal_forms.json` | organ vocabulary per form, task exclusions (C5.7 on SARL and GIE) |

95 definitions make 94 codes. The 95th is not reachable in the platform today.

**`ea.audit.paper.def`** holds definitions in the database, loaded from these files by a
`<function>` in `data/` on install and upgrade. It is read-only for every group.

| Field | Note |
| --- | --- |
| `code` | unique among current rows |
| `definition` | `Json`, unresolved |
| `definition_hash` | `services.digest(definition)`, unique |
| `is_current` | false once a later load replaced the text |

An upgrade that changes a text adds a row and retires the old one; it never overwrites.
This is what makes question Q1 answerable. The resolver stays `services.paper_for`, and
models only choose which definition and which edition and form to feed it.

`standards_refs.json` covers the `ea.audit.isa.ref` table of spec D.7. If the technical
desk needs to correct paragraph numbers in the interface, that JSON becomes the seed of
the table and `services/tokens.py` takes the table as a parameter.

## 2. Paper and answers

**`ea.audit.paper`** is the task's paper, one per file item; it takes over `document` of
the platform (spec D.12 and F). It inherits `mail.thread`.

| Field | Note |
| --- | --- |
| `file_item_id` | required, unique, `ondelete='restrict'` |
| `engagement_id`, `code` | related, stored, indexed |
| `state` | draft, signed |
| `answer_version` | integer, see section 4 |
| `signoff_ids` | from `ea.audit.signoff` |

Edition and legal form are not stored here: they are read from the engagement and its
client each time, as `paperFor` does.

**`ea.audit.paper.answer`** is one row per key, unique on `(paper_id, field_key)`.

| Field | Note |
| --- | --- |
| `paper_id`, `field_key` | required |
| `value` | `Text`. Paper answers are strings on every path (`loadPaper` stringifies) |
| `carried_forward` | true when roll-forward wrote it; such a write leaves no history |
| `write_uid`, `write_date` | stand for `updated_by`, `updated_at` |

Spec D.12 says `value Json` because `form_response` also holds tool data (`sad`, `itapps`,
`psp:`, `dsp`). Those families should become real models (spec D.12), so `wp:` answers
need no JSON, and blank stays one simple test. See Q5.

One door for writes, **`ea.audit.paper.save_answers(values, base_version, base_digests)`**,
in this order, each step a port of `savePaper`:

1. `assertMutable`, role, EQR filter (`filterPaperWrite`, C4.2 keys).
2. Allow-list: `paper_keys(paper_for(code, edition, engagement_form))`. Not the bare
   `paperFor(code)` of the platform, see Q2.
3. Per-code refusals and side effects, section 6.
4. Lock, then merge against concurrent edits, section 4.
5. Write the rows.
6. Void stale signatures in the same transaction, section 5.
7. After commit: activity entry, notifications (`cr.postcommit`), so that they cannot roll
   back the edit.

`create`, `write` and `unlink` of the answer model refuse a caller outside this door,
through a context flag that only `save_answers` sets. Roll-forward and migration use
named methods of their own.

## 3. Answer history

**`ea.audit.paper.answer.history`** is append-only: `paper_id`, `field_key`, `before`,
`after`, `user_id`, `changed_at`, plus `create` only ACLs and an `unlink` that refuses. The
`answer_changed` rows of `activity_log` migrate into it as they stand (spec F, rule 6).

The platform writes this from a deferred database trigger. The rules to keep:

- One row per field per transaction, with the state at commit.
- NULL, `''` and a blank string are the same thing, "nobody said anything": a change
  between them is no change (migration `20261103000002`).
- Clearing an answer is recorded with `after` empty. Clearing a blank is not recorded.
- A carried-forward write is not recorded.

`save_answers` compares once per key after applying all values, which gives the first rule
without a trigger or a transaction-local marker. The cost is that a raw SQL write is not
traced, whereas the trigger catches everything. The trigger is kept out because the
single door exists, and because the migration loads history as-is and would otherwise have
to disable it. `btrim` in the trigger strips spaces only, whereas `js_trim` strips all
ECMAScript whitespace; the Python port uses one test, `js_trim`, for both.

## 4. Concurrent edits

The platform takes an advisory lock and compares `max(updated_at)`. In Odoo,
`SELECT ... FOR UPDATE` on the paper row and the integer `answer_version` replace both: the
row lock serialises saves on the paper and the integer has no clock precision to worry
about. Per-field digests stay as they are (`sha256(text with CRLF as LF)[:16]`):

- A field stored differently from the form's base digest has "moved".
- Moved and untouched by this user: the colleague's text stands.
- Moved and changed by this user to something else: held back, the rest saved, the user
  gets their text back. Held-back text goes in the RPC response instead of a cookie.

## 5. Sign-off invalidation

The hash attests to the answers, not to the definition.

**Platform.** `paperContentHashTx` is
`sha256(JSON.stringify({fields: [[key, value], ...sorted], sectionConclusion}) + "|" + extra)`,
where `fields` is every `wp:<code>` row including blanks, `sectionConclusion` is
`{conclusion, objectivesAchieved}` or null, and `extra` joins md5 digests in SQL over the
records the paper fronts: the legacy form of the same code, `psp:`, program steps, live
attachments, and per code S3.1 CRA, S4.3 and E6.2 related parties, S4.4 estimates, S1.4
FSCP, S1.3 walkthroughs, S2.3 and S2.5 IT apps, S5.5 design, S1.1, S1.2, S2.1, S2.2, E1.2.

**Odoo.**

- `ea.audit.paper._content_parts()` returns an ordered dict of named parts. The base method
  gives `fields` and `section_conclusion`. Addons extend it per code: `ea_audit_tools` adds
  CRA, SCOT and the rest, as `ea_audit_papers` cannot depend on it.
- `_content_hash()` is `services.digest({"scheme": 2, "parts": parts})`: same canonical
  form as the definitions, no SQL md5, testable without a database once the parts are read.
- Signing stores it in `ea.audit.signoff.content_hash`, with `content_scheme` (Q3) and
  `definition_hash` (Q1).
- `_void_stale_signoffs()` ports `invalidateStaleSignoffs`: active signatures with a hash
  that differs get `invalidated_at`, `voided_at` and the bilingual reason; if one was
  reviewer or partner, the section conclusion's reviews clear; with no valid reviewer or
  partner left, the paper returns to draft. A signature with a null hash is never voided.
- Writers outside `save_answers` that feed a part (attachments, program steps, SCOT boards)
  call `_void_stale_signoffs()` themselves, as `voidStaleSignoffsOfItem` does. The risk is
  a writer that forgets; a test per part asserts that a change there voids a signature.

Fields that sign-off needs from `ea_audit_core`: `content_hash`, `content_scheme`,
`definition_hash`, `invalidated_at`, `invalidated_reason`, `voided_at`, `void_reason`, and
a link to the paper. Spec D.3 has `document_id`, but `ea.audit.paper` lives in this addon
and core cannot point at it: either a Many2one added here by inheritance, or a
`file_item_id` in core, which the paper is unique on. The second is simpler.

## 6. Behaviour the JSON does not carry

A definition is data; these stay as code keyed by `code`, with a registry in Python so
the renderer stays generic:

| Code | Behaviour | Source |
| --- | --- | --- |
| C5.10 | `persons` follows `headcount` (ten above 200, otherwise five) unless chosen | `statutory-525.ts` |
| E6.10 | `q_n_agrees = yes` refused while the tie-out has unexplained differences | `savePaper` |
| C5.8 | `q_above = yes` refused while live figures show the breach | `savePaper` |
| E3.1 | conclusions complete or reopen the seeded management-override step | `syncSeededResponseStep` |
| P1.5 | any EQR criterion answered yes creates C4.2 | `savePaper` |
| C4.2 | EQR keys writable by the appointed reviewer only | `eqr.ts` |
| P6.1, P6.2, C1.1, E4.1-34 | sign-off refused until tool output exists | `tool-fed-papers.ts` |
| E4.x, P7.2, S1.2, S1.3, S2.1, S2.2, no bespoke paper | exempt from `paper_missing` at signing | `services.completeness_exempt` |
| auto fields | filled from tools, never saved; empty text per source in `AUTO_SOURCES` | `papers/types.ts` |

`AUTO_SOURCES` (bilingual empty-state text) is not exported yet: it is presentation text
and belongs with the renderer's catalogue.

Period to edition (`editionForPeriod`) is not in `services/`: spec D.7 places it on
`ea.audit.engagement`, in core.

## 7. The OWL renderer

One component for all papers, reading one payload from
`ea.audit.paper.get_payload(paper_id)`:

```
definition    services.paper_for(code, edition, form), both languages
values        {field_key: text}
digests       {field_key: digest}, version: answer_version
progress      paper_progress; missing: paper_missing
readonly      archived, read-only role, EQR on team work
locked_keys   per EQR rules
auto_values   {field_key: text} from tools
signoffs, embed, tool_links
```

Language is chosen on the client from the `En`/`Fr` property pairs of the resolved
definition, so switching does not refetch. `std` and `tools` have no pair: as on the
platform, `std` reads in English.

Pages, as in `PaperWizard`: status page, embed page where a board exists (alone for
S1.2, S1.3, S2.1, S2.2), questionnaire, conclusions with `key_findings` last.

| Definition | Renders as | Stores |
| --- | --- | --- |
| `fields[]` kind input | auto-growing textarea | `key` |
| kind select | one clickable option per `options[]` | `key` |
| kind auto | read-only, from `auto_values` | nothing |
| `proc` | numbered procedure, source, result, N/A toggle, reason box | `p_k`, `p_k_na`, `p_k_x` |
| `yn` | Yes, No, N/A on every item; box on No or N/A (`na` flag ignored since F040) | `q_k`, `q_k_x` |
| `conclEn[i]` | Yes, No; box on No | `c_i`, `c_i_x` |
| `tipEn`/`tipFr`, `reqEn`/`reqFr` | practical tips, standards narrative | |

Boards (SCOT, CRA, deficiencies and the rest) register by code in an OWL registry and
`ea_audit_tools` fills it, so this component does not import them. The client never decides
completeness or signing: it shows `missing` and the server recomputes. Build order per
spec R1: P1.1, S3.1, E4.1, C4.2, C6.1, then generalise.

## 8. Open questions

**Q1. Does a signature pin the text it was given over?** Today a redeploy silently changes
the wording under signed and archived files, and the hash does not see it. Some 276 marks
(`[Projet]`, `[Draft]`, `(à valider)`) say wordings will change, and every `revised_2026`
paragraph number is "to verify". Proposal: keep `definition_hash` on each signature and
retired rows in `ea.audit.paper.def`, so a signed paper can show the text it was signed
on; do not void on a definition change. Needs a firm ruling, as it is new behaviour.

**Q2. Platform defect: SA-only answers do not save.** `savePaper` takes its allow-list from
`paperFor(code)` with no form, which reads as OTHER, and the `forms` filter then drops
anything not naming OTHER. Affected: C5.3 (20 keys, SA, SA_AG,
SARL, SAS items) and C5.5 (3 keys, SA and SA_AG). Reading the code, on an SA file the answers
are skipped silently, `paperMissing` then demands them, and the paper cannot be signed. This
contradicts the comment on `paperFor`, and `resolveLegalFormPaper`'s comment "nothing
removed" also does not match the code. Found by reading and by computing the keys, not by
running a save; no platform test covers these keys. Odoo uses the engagement's form (section 2); the platform needs a decision.
`index.json` lists the keys under `keys_refused_by_save_allow_list`.

**Q3. Migrated signatures.** Spec F rule 6 loads sign-offs as-is, but the legacy hash cannot
be recomputed in Odoo: it covers row UUIDs and SQL md5 over `jsonb::text`. Comparing old to
new would void every migrated signature on first save. Proposal: before cutover the
platform computes `paperContentHashTx` for each active signature; where it matches, the
loader stores the new scheme-2 hash computed in Odoo, `content_scheme = 2`; where not, it
keeps the row with `content_scheme = 1`, reported rather than voided. Needs the migration
owner's agreement.

**Q4. Blank answers in the hash.** The legacy hash includes blank rows, so a save that adds
an empty key after signing changes the hash though nobody said anything, while the history
rule calls that no change. Proposal: scheme 2 leaves blanks out. To confirm, as it narrows
what voids a signature.

**Q5. `value` Text or Json** (section 2): Text departs from spec D.12. It depends on tool
families becoming real models.

**Q6. Names.** The spec uses `ea.audit.paper` for the definition in C.6.7 and for the
task's paper in D.12, and `ea.audit.paper.response` beside `ea.audit.paper.answer`. This
follows D.12 and F: `ea.audit.paper.def`, `ea.audit.paper`, `ea.audit.paper.answer`.

**Q7. Overlap.** A `feat/services` branch is open and spec E.2 lists standards edition
among the `services/` ports. `services/tokens.py` should be the one implementation of
`resolve_text`; to be reconciled at merge.

**Q8. Shadowed C6.2.** The `conclusion.ts` version is dead code and differs from the live
one (its `std` also cites ISA 220 ¶31). Keep it in `papers_shadowed/` until the firm says
which text is right; the live one is the only one the platform has ever shown.
