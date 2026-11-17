"""Journal entry testing (ISA 240), one screen (owner's mock-up approved 18/11).

The ledger is read once per entry by one GROUP BY (set-based, 100 000 lines in one pass); the
criteria are plain functions of those facts (services/je_testing.py). The selection is never
stored: it follows the ledger in use and the engagement's settings, set once for the engagement.

What the auditor concludes on an entry is its review (ea.audit.je.review, since 2026-11-16): the
four answers and the work done are new columns; a review recorded before reads its status
(Cleared = No exception, Problem = Exception) and its note as the work done. Nothing is rewritten.
Findings and adjustments go through the existing paths (ea_raise_finding, ea_save_adjustment), so
they reach the Findings tool and the summary of audit differences by themselves.
"""
import re

from odoo import fields, models

from ..rules import rule_error
from ..services.je_testing import (
    ANSWERS, ATTRIBUTES, CRITERIA, GROUPS, STATUS_LABELS, TESTS, accounts_summary, build_context, criterion_name, dmy,
    entry_key, export_rows, filter_selection, finish_facts, pick, resolve_settings, run_criteria, settings_text, spaced,
    stored_status, entry_conclusion, selection_totals, weekday_name, year_holidays,
)
from .tool_record import french_date, is_french
from .worksheet_pages import FINDING_KINDS

ATTRIBUTE_SELECTION = [("yes", "Yes"), ("no", "No"), ("na", "Not applicable")]
#: The rows the page lists at most; the counts are always over the whole selection.
PAGE_ROWS = 5000
_CLIENT_KIND = re.compile(r"^je_client_([0-9a-f]{1,8})$")
JE_PAPER = "E3.1"
REVIEW_MODEL = "ea.audit.je.review"

FACTS_SQL = """
SELECT l.je_number,
       to_char(min(l.journal_date), 'YYYY-MM-DD'),
       min(nullif(trim(l.journal_code), '')),
       max(nullif(trim(l.je_description), '')),
       max(nullif(trim(l.line_description), '')),
       max(nullif(trim(l.preparer), '')),
       max(nullif(trim(l.approver), '')),
       max(nullif(trim(l.reviewer), '')),
       coalesce(sum(l.debit - l.credit) FILTER (WHERE l.debit - l.credit > 0), 0)::float8,
       coalesce(sum(l.credit - l.debit) FILTER (WHERE l.debit - l.credit < 0), 0)::float8,
       coalesce(array_agg(DISTINCT trim(l.account)) FILTER (WHERE l.debit - l.credit > 0), ARRAY[]::text[]),
       coalesce(array_agg(DISTINCT trim(l.account)) FILTER (WHERE l.debit - l.credit < 0), ARRAY[]::text[]),
       count(*)::int
  FROM ea_audit_gl_line l
 WHERE l.dataset_id = %s AND l.engagement_id = %s {after}
 GROUP BY l.je_number
"""


class JeReviewTest(models.Model):
    _inherit = "ea.audit.je.review"

    attr_document = fields.Selection(ATTRIBUTE_SELECTION, string="Supporting document obtained and agreed to the entry")
    attr_approval = fields.Selection(ATTRIBUTE_SELECTION, string="Entry approved by an appropriate person, other than its preparer")
    attr_reason = fields.Selection(ATTRIBUTE_SELECTION, string="Business reason understood and consistent with our knowledge of the entity")
    attr_recording = fields.Selection(ATTRIBUTE_SELECTION, string="Recorded in the right accounts, period and amount")
    adjustment_finding_id = fields.Many2one("ea.audit.finding", string="Misstatement carrying the adjustment", ondelete="set null")


class EngagementJeTesting(models.Model):
    _inherit = "ea.audit.engagement"

    je_test_settings = fields.Json(string="Journal entry testing settings")

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def _ea_jet_locale(self):
        return "fr" if is_french(self.env) else "en"

    def _ea_jet_ledger(self):
        """The general ledger in use: the post-audit one, else the pre-audit one, else the latest."""
        self.ensure_one()
        found = self.env["ea.audit.dataset"].sudo().search([
            ("engagement_id", "=", self.id), ("kind", "=", "journal_entries"), ("superseded_at", "=", False),
            ("timing", "in", ("pre_audit", "post_audit")),
        ])
        return (found.filtered(lambda d: d.timing == "post_audit")[:1] or found[:1]
                or self._ea_current_dataset("journal_entries"))

    def _ea_jet_facts(self, dataset, after=None):
        """One row per entry of a ledger, as services/je_testing.entry_facts builds them."""
        sql = FACTS_SQL.format(after="AND l.journal_date > %s" if after else "")
        params = [dataset.id, self.id] + ([after] if after else [])
        self.env.cr.execute(sql, params)
        out = []
        for row in self.env.cr.fetchall():
            out.append(finish_facts({
                "je": row[0], "date": row[1], "journal": row[2] or "", "description": row[3] or "",
                "line_description": row[4] or "", "preparer": row[5] or "", "approver": row[6] or "",
                "reviewer": row[7] or "", "amount": row[8], "credit_total": row[9], "debits": list(row[10] or []),
                "credits": list(row[11] or []), "lines": row[12], "next": bool(after),
            }))
        return out

    def _ea_jet_settings(self):
        return resolve_settings(self.sudo().je_test_settings or {})

    def _ea_jet_holidays(self, settings):
        """The engagement's list once edited, else the Cameroon calendar of the year audited."""
        if settings["holidays"] is not None:
            return settings["holidays"]
        root = self.sudo()
        calendar = root._ea_load_holidays("CM")
        locale = self._ea_jet_locale()
        labels = {date: row["labelFr"] if locale == "fr" else row["labelEn"] for date, row in calendar.items()}
        return year_holidays(
            labels, fields.Date.to_string(root.period_start) if root.period_start else None, fields.Date.to_string(root.period_end),
        )

    def _ea_jet_compute(self):
        """The ledger, the settings, every entry found and the counts of each criterion."""
        self.ensure_one()
        root = self.sudo()
        dataset = self._ea_jet_ledger()
        settings = self._ea_jet_settings()
        holidays = self._ea_jet_holidays(settings)
        out = {"dataset": dataset, "settings": settings, "holidays": holidays, "facts": {}, "found": {},
               "counts": {c["key"]: 0 for c in CRITERIA}, "population": {"lines": 0, "entries": 0}, "next": False}
        if not dataset or not dataset.gl_line_count:
            return out
        period_end = fields.Date.to_string(root.period_end)
        entries = self._ea_jet_facts(dataset)
        out["population"] = {"lines": 0, "entries": len(entries)}
        for entry in entries:
            out["population"]["lines"] += entry["lines"]
        subsequent = self._ea_subsequent_dataset("journal_entries")
        if subsequent and subsequent.gl_line_count:
            entries += self._ea_jet_facts(subsequent, after=period_end)
            out["next"] = subsequent
        ctx = build_context(entries, settings, period_end, holidays)
        found, counts = run_criteria(entries, ctx)
        out.update(found=found, counts=counts, facts={entry_key(e): e for e in entries if entry_key(e) in found})
        return out

    def _ea_jet_reviews(self, data):
        """{entry key: review} of the entries found, on their ledgers."""
        datasets = [d.id for d in (data["dataset"], data["next"]) if d]
        if not datasets:
            return {}
        out = {}
        next_id = data["next"].id if data["next"] else None
        for review in self.env[REVIEW_MODEL].sudo().search([("engagement_id", "=", self.id), ("dataset_id", "in", datasets)]):
            out[("next:" if review.dataset_id.id == next_id else "") + review.je_number] = review
        return out

    @staticmethod
    def _ea_jet_review_dict(review):
        if not review:
            return {}
        values = {a["key"]: review[a["key"]] or None for a in ATTRIBUTES}
        values["status"] = review.status
        return values

    def _ea_jet_rows(self, data, reviews, locale):
        names = {c["key"]: criterion_name(c, data["settings"], locale) for c in CRITERIA}
        rows = []
        for key in sorted(data["found"], key=lambda k: (data["facts"][k]["date"] or "9999", data["facts"][k]["je"])):
            entry = data["facts"][key]
            review = reviews.get(key)
            reasons = data["found"][key]
            rows.append({
                "key": key, "je": entry["je"], "date": entry["date"] or "", "next": entry["next"],
                "dateText": dmy(entry["date"]), "weekday": weekday_name(entry["date"], locale),
                "journal": entry["journal"], "description": entry["description"], "accounts": accounts_summary(entry),
                "amount": entry["amount"], "amountText": spaced(entry["amount"]),
                "preparer": entry["preparer"], "approver": entry["approver"],
                "reasons": reasons, "reasonNames": [names[r] for r in reasons],
                "test": entry_conclusion(self._ea_jet_review_dict(review)),
                "reviewId": review.id if review else False,
            })
        return rows

    def _ea_jet_state(self):
        """The short state the paper hooks of E3.1 and S5.4 read (paper_hooks_je.py)."""
        self.ensure_one()
        locale = self._ea_jet_locale()
        data = self._ea_jet_compute()
        rows = self._ea_jet_rows(data, self._ea_jet_reviews(data), locale)
        totals = selection_totals(rows)
        reviews = self.env[REVIEW_MODEL].sudo().search([("engagement_id", "=", self.id)])
        findings = (reviews.mapped("finding_id") | reviews.mapped("adjustment_finding_id"))
        population = data["population"]
        return {
            "lines": population["lines"], "entries": population["entries"],
            "ledgerText": pick(locale, "%s lines, %s entries", "%s lignes, %s écritures") % (
                spaced(population["lines"]), spaced(population["entries"])),
            "selected": totals["selected"], "selectedText": spaced(totals["selected"]),
            "tested": totals["tested"], "exceptions": totals["exceptions"], "findings": len(findings),
            "yearEnd": data["counts"]["year-end"],
            "settingsSaved": bool(self.sudo().je_test_settings),
            "settingsText": settings_text(data["settings"], len(data["holidays"]), locale),
        }

    def _ea_jet_findings(self, reviews):
        """The two panels at the bottom: findings raised from an entry, and the adjustments."""
        page = {row["id"]: row for row in self.ea_findings_page()["findings"]}
        by_finding = {}
        for review in reviews:
            for finding in (review.finding_id, review.adjustment_finding_id):
                if finding:
                    by_finding.setdefault(finding.id, review)
        raised = self.env["ea.audit.finding"].sudo().search([
            ("engagement_id", "=", self.id), ("source_model", "=", REVIEW_MODEL),
        ])
        for finding in raised:
            review = self.env[REVIEW_MODEL].sudo().browse(finding.source_id).exists()
            if review:
                by_finding.setdefault(finding.id, review)
        findings, adjustments = [], []
        for finding in self.env["ea.audit.finding"].sudo().browse(sorted(by_finding)).exists().sorted("number"):
            row = page.get(finding.id)
            review = by_finding[finding.id]
            if not row:
                continue
            findings.append({
                "id": finding.id, "ref": row["ref"], "title": row["title"], "entry": review.je_number,
                "kind": row["routeLabel"], "stage": row["stageLabel"], "tone": row["stageTone"],
            })
            adj = row.get("adjustment")
            if adj and adj.get("status"):
                debit = [line["headingLabel"] for line in adj["lines"] if line.get("debit") and line.get("heading")]
                credit = [line["headingLabel"] for line in adj["lines"] if line.get("credit") and line.get("heading")]
                adjustments.append({
                    "id": finding.id, "entry": review.je_number, "sad": adj["sad"],
                    "heading": "%s → %s" % (", ".join(debit) or "—", ", ".join(credit) or "—"),
                    "proposed": finding.title or "", "amount": spaced(_total_debit(adj["lines"])),
                    "status": adj["statusText"] or adj["status"],
                })
        return findings, adjustments

    def _ea_jet_paper(self):
        return self.env["ea.audit.paper"].sudo().search([("engagement_id", "=", self.id), ("code", "=", JE_PAPER)], limit=1)

    def _ea_jet_signing(self):
        """Sign as preparer / Sign as reviewer on E3.1: the paper's own chips, so the screen and
        the server cannot disagree."""
        paper = self._ea_jet_paper()
        if not paper:
            return []
        chips = paper.with_env(self.env)._ea_signing_payload()["chips"]
        return [chip for chip in chips if chip["role"] in ("preparer", "reviewer")]

    def ea_jet_page(self):
        """What the Journal entry testing screen shows."""
        self.ensure_one()
        self._ea_require_access()
        root = self.sudo()
        locale = self._ea_jet_locale()
        reason = self._ea_ws_readonly()
        data = self._ea_jet_compute()
        reviews = self._ea_jet_reviews(data)
        rows = self._ea_jet_rows(data, reviews, locale)
        totals = selection_totals(rows)
        dataset = data["dataset"]
        timing = dict(dataset._fields["timing"]._description_selection(self.env)).get(dataset.timing, "") if dataset else ""
        review_records = self.env[REVIEW_MODEL].sudo().search([("engagement_id", "=", self.id)])
        findings, adjustments = self._ea_jet_findings(review_records)
        files = self._ea_ws_files(REVIEW_MODEL, [r.id for r in reviews.values()])
        lang = "fr_FR" if locale == "fr" else "en_US"
        tests = {}
        for row in rows[:PAGE_ROWS]:
            review = reviews.get(row["key"])
            if not review:
                continue
            adjustment = review.adjustment_finding_id or (review.finding_id if review.finding_id.route == "b5" else False)
            tests[row["key"]] = {
                **{a["key"]: review[a["key"]] or "" for a in ATTRIBUTES},
                "work": review.note or "",
                "finding": review.finding_id.reference if review.finding_id else "",
                "adjustment": adjustment._ea_adjustment_view(lang, self._ea_figure)
                if adjustment and adjustment.sudo().misstatement_id else False,
                "fileList": files.get(review.id, []),
            }
        settings = data["settings"]
        return {
            "engagement": root.display_name,
            "readonly": bool(reason), "archived": reason == "archived",
            "ledger": {
                "name": (dataset.source_filename or dataset.display_name) if dataset else "",
                "lines": spaced(data["population"]["lines"]), "entries": spaced(data["population"]["entries"]),
                "timing": timing, "ready": bool(dataset and dataset.gl_line_count),
                "missing": not dataset and "ledger" or (dataset and not dataset.gl_line_count and "lines") or False,
                "next": bool(data["next"]),
            },
            "groups": [{
                "key": g["key"], "name": g[locale],
                "criteria": [{
                    "key": c["key"], "no": c["no"], "name": criterion_name(c, settings, locale), "count": data["counts"][c["key"]],
                } for c in CRITERIA if c["group"] == g["key"]],
            } for g in GROUPS],
            "settings": {k: v for k, v in settings.items() if k != "holidays"},
            "holidays": [dict(h, text=dmy(h["date"])) for h in data["holidays"]],
            "settingsText": settings_text(settings, len(data["holidays"]), locale),
            "rows": rows[:PAGE_ROWS], "truncated": len(rows) > PAGE_ROWS,
            "totals": totals, "tests": tests,
            "attributes": [{"key": a["key"], "label": a[locale]} for a in ATTRIBUTES],
            "statusLabels": {k: v[locale] for k, v in STATUS_LABELS.items()},
            "findings": findings, "adjustments": adjustments,
            "signing": self._ea_jet_signing(),
        }

    # ------------------------------------------------------------------
    # Changing
    # ------------------------------------------------------------------

    def ea_jet_save_settings(self, values):
        """The engagement's settings, set once for the engagement. Changing them changes the
        selection, so the E3.1 and S5.4 signatures are given again."""
        self.ensure_one()
        self._ea_tool_guard()
        current = dict(self.sudo().je_test_settings or {})
        allowed = set(resolve_settings({})) - {"holidays"}
        for key, value in (values or {}).items():
            if key in allowed or key == "holidays":
                current[key] = value
        clean = resolve_settings(current)
        stored = {k: v for k, v in clean.items() if k != "holidays"}
        if clean["holidays"] is not None:
            stored["holidays"] = clean["holidays"]
        self.sudo().write({"je_test_settings": stored})
        self._ea_log("je_settings_saved", "Journal entry testing settings saved")
        self._ea_invalidate_signoffs(JE_PAPER)
        self._ea_invalidate_signoffs("S5.4")
        return self.ea_jet_page()

    def _ea_jet_review(self, key):
        """The review of one entry of the ledger in use (or of the subsequent-period ledger),
        created when first touched."""
        self.ensure_one()
        key = str(key or "")
        number = key[5:] if key.startswith("next:") else key
        dataset = self._ea_subsequent_dataset("journal_entries") if key.startswith("next:") else self._ea_jet_ledger()
        number = number.strip()
        if not dataset or not number:
            raise rule_error(self.env, "not-found")
        self.env.cr.execute(
            "SELECT 1 FROM ea_audit_gl_line WHERE dataset_id = %s AND engagement_id = %s AND je_number = %s LIMIT 1",
            [dataset.id, self.id, number],
        )
        if not self.env.cr.fetchone():
            raise rule_error(self.env, "not-found")
        Review = self.env[REVIEW_MODEL].sudo()
        review = Review.search([("engagement_id", "=", self.id), ("dataset_id", "=", dataset.id), ("je_number", "=", number)], limit=1)
        return review or Review.create({"engagement_id": self.id, "dataset_id": dataset.id, "je_number": number})

    def ea_jet_save_test(self, key, answers, work=None):
        """The four answers and the work done on one entry; the conclusion follows from them."""
        self.ensure_one()
        self._ea_tool_guard()
        review = self._ea_jet_review(key)
        values = {}
        for attribute in ATTRIBUTES:
            if attribute["key"] in (answers or {}):
                answer = (answers or {})[attribute["key"]] or False
                if answer and answer not in ANSWERS:
                    raise rule_error(self.env, "invalid-value")
                values[attribute["key"]] = answer
        if work is not None:
            values["note"] = (work or "").strip() or False
        merged = {**self._ea_jet_review_dict(review), **{k: v or None for k, v in values.items() if k.startswith("attr_")}}
        conclusion = entry_conclusion(merged)
        values.update({"status": stored_status(conclusion), "reviewed_by_id": self.env.user.id, "reviewed_at": fields.Datetime.now()})
        review.write(values)
        self._ea_log("je_entry_reviewed", "Journal entry %s tested: %s" % (review.je_number, STATUS_LABELS[conclusion]["en"]))
        self._ea_invalidate_signoffs(JE_PAPER)
        return self.ea_jet_page()

    def ea_jet_finding(self, key, description, finding_type="misstatement", amount=None, trivial_confirmed=False):
        """Raise a finding from one entry, in the Findings tool, linked to the entry and to E3.1."""
        self.ensure_one()
        self._ea_tool_guard()
        review = self._ea_jet_review(key)
        text = (description or "").strip()
        if not text:
            raise rule_error(self.env, "title-required")
        if finding_type not in FINDING_KINDS:
            raise rule_error(self.env, "invalid-value")
        finding = self.ea_raise_finding(
            REVIEW_MODEL, review.id, text[:200], detail=text if len(text) > 200 else None,
            amount=amount if finding_type == "misstatement" else None, finding_type=finding_type, mtype="factual",
            trivial_confirmed=bool(trivial_confirmed),
        )
        values = {"finding_id": finding.id}
        if finding_type == "misstatement" and not review.adjustment_finding_id:
            values["adjustment_finding_id"] = finding.id
        review.write(values)
        self._ea_log("je_entry_reviewed", "Finding %s raised from journal entry %s" % (finding.reference, review.je_number))
        return self.ea_jet_page()

    def ea_jet_adjustment_start(self, key):
        """"Add an adjustment": the misstatement that will carry it, raised from the entry when it
        has none yet. Its adjustment is then typed and saved through ea_jet_adjust."""
        self.ensure_one()
        self._ea_tool_guard()
        review = self._ea_jet_review(key)
        if not review.adjustment_finding_id:
            if review.finding_id and review.finding_id.route == "b5":
                review.write({"adjustment_finding_id": review.finding_id.id})
            else:
                amount = self._ea_jet_amount(review)
                title = self.env._("Adjustment proposed on journal entry %s", review.je_number)
                finding = self.ea_raise_finding(
                    REVIEW_MODEL, review.id, title, amount=amount or None, finding_type="misstatement", mtype="factual",
                    trivial_confirmed=True,
                )
                review.write({"adjustment_finding_id": finding.id})
                self._ea_log("je_entry_reviewed", "Adjustment started on journal entry %s (%s)" % (review.je_number, finding.reference))
        return self.ea_jet_page()

    def _ea_jet_amount(self, review):
        self.env.cr.execute(
            "SELECT coalesce(sum(debit - credit) FILTER (WHERE debit - credit > 0), 0)::float8 FROM ea_audit_gl_line "
            "WHERE dataset_id = %s AND engagement_id = %s AND je_number = %s",
            [review.dataset_id.id, self.id, review.je_number],
        )
        return self.env.cr.fetchone()[0]

    def ea_jet_adjust(self, key, lines=None, nature=None):
        """Save the adjustment: the existing flow sends it to the summary of audit differences,
        where it waits for the reviewer."""
        self.ensure_one()
        self._ea_tool_guard()
        review = self._ea_jet_review(key)
        if not review.adjustment_finding_id:
            raise rule_error(self.env, "adjustment-misstatement")
        review.adjustment_finding_id.with_env(self.env).ea_save_adjustment(lines=lines, nature=nature)
        return self.ea_jet_page()

    def ea_jet_attach(self, key, filename, content_b64):
        self.ensure_one()
        self._ea_tool_guard()
        review = self._ea_jet_review(key)
        self.ea_ws_attach(REVIEW_MODEL, review.id, filename, content_b64)
        return self.ea_jet_page()

    def ea_jet_attach_existing(self, key, row_ids):
        self.ensure_one()
        self._ea_tool_guard()
        review = self._ea_jet_review(key)
        self.ea_ws_attach_existing(REVIEW_MODEL, review.id, row_ids)
        return self.ea_jet_page()

    def ea_jet_sign(self, role):
        """Sign E3.1 from the screen, through the paper's own rules."""
        self.ensure_one()
        if role not in ("preparer", "reviewer"):
            raise rule_error(self.env, "forbidden")
        paper = self._ea_jet_paper()
        if not paper:
            raise rule_error(self.env, "not-found")
        paper.file_item_id.with_env(self.env).action_sign(role)
        return self.ea_jet_page()

    # ------------------------------------------------------------------
    # The selection for the client
    # ------------------------------------------------------------------

    def ea_jet_export_action(self, ticked=None):
        """"Export the selection for the client (Excel)": the entries shown, with their reasons."""
        self.ensure_one()
        mask = 0
        for index, criterion in enumerate(CRITERIA):
            if criterion["key"] in (ticked or []):
                mask |= 1 << index
        return self._ea_export_action("je_client_%x" % mask)

    def _ea_export_dynamic_method(self, kind):
        found = super()._ea_export_dynamic_method(kind)
        if found:
            return found
        match = _CLIENT_KIND.match(kind or "")
        if match:
            mask = int(match[1], 16)
            ticked = [c["key"] for index, c in enumerate(CRITERIA) if mask & (1 << index)]
            return lambda fr: self._ea_export_je_client(fr, ticked)
        return None

    def _ea_export_je_client(self, fr, ticked):
        from ..workbooks import je_client_workbook

        locale = "fr" if fr else "en"
        data = self._ea_jet_compute()
        rows = filter_selection(self._ea_jet_rows(data, {}, locale), [k for k in ticked if k in TESTS])
        head, body = export_rows(rows, locale)
        root = self.sudo()
        client = re.sub(r"[^\w-]+", "_", root.client_id.name or "client")
        names = [criterion_name(c, data["settings"], locale) for c in CRITERIA if c["key"] in ticked]
        filename = ("Selection-ecritures-%s-%s.xlsx" if fr else "Journal-entry-selection-%s-%s.xlsx") % (client, root.fiscal_year)
        return filename, je_client_workbook({
            "clientName": root.client_id.name, "fiscalYear": root.fiscal_year, "periodEnd": french_date(root.period_end),
            "criteria": names, "head": head, "rows": body,
        }, fr)


def _total_debit(lines):
    total = 0.0
    for line in lines:
        total += float(line.get("debit") or 0)
    return total
