from odoo import api, fields, models

from ..rules import rule_error
from ..services.lead_classes import LEAD_INDEX_BY_CODE, lead_index_label
from ..services.sad_model import SAD_CAPTION_LABELS, SAD_CAPTIONS, suggest_caption
from ..services.sad_view import effective_income_after_tax, fs_caption_amounts
from .finding import MTYPE_SELECTION
from .tool_record import fcfa, is_french

CAPTION_SELECTION = [(code, SAD_CAPTION_LABELS[code]["en"]) for code in SAD_CAPTIONS]
ANSWER_SELECTION = [("yes", "Yes"), ("no", "No"), ("na", "N/A")]
#: What the summary still changes on a line (owner's ruling of 2026-11-16): whether management
#: corrected it, the team's rationale, and the caption a line is shown under. The difference
#: itself (description, accounts, amounts, type) is the working paper's, never typed here.
REVIEW_FIELDS = {"corrected", "rationale", "dr_caption", "cr_caption"}
PROC_MODEL = "ea.audit.designed.procedure"


class SadEntry(models.Model):
    """One proposed adjustment on the SAD. Since 2026-11-17 (owner's ruling of 2026-11-16) a
    line arrives only from a working paper: a misstatement raised in the conclusion of a
    substantive procedure (or on a sample, a journal entry...) goes through
    engagement.ea_raise_finding / route_finding("b5"), which writes the C1.1 misstatement, the
    finding and this line together (``register_only``). Nobody types a line here any more.
    Lines typed before that day stay as they were, shown as "entered before 2026-11-17"."""

    _name = "ea.audit.sad.entry"
    _inherit = ["ea.audit.tool.record"]
    _description = "Summary of audit differences entry"
    _order = "id"
    _rec_name = "finding"

    file_item_id = fields.Many2one("ea.audit.file.item", string="Paper", ondelete="set null", index=True)
    task_code = fields.Char(string="Task", compute="_compute_refs", compute_sudo=True)
    ref = fields.Char(string="W/P ref.")
    finding = fields.Char(string="Description")
    dr_account = fields.Char(string="Dr account")
    dr_amount = fields.Float(string="Dr amount", digits=(18, 2))
    cr_account = fields.Char(string="Cr account")
    cr_amount = fields.Float(string="Cr amount", digits=(18, 2))
    dr_caption = fields.Selection(CAPTION_SELECTION, string="Dr caption (override)")
    cr_caption = fields.Selection(CAPTION_SELECTION, string="Cr caption (override)")
    dr_caption_effective = fields.Selection(CAPTION_SELECTION, string="Dr caption", compute="_compute_captions", compute_sudo=True)
    cr_caption_effective = fields.Selection(CAPTION_SELECTION, string="Cr caption", compute="_compute_captions", compute_sudo=True)
    mtype = fields.Selection(MTYPE_SELECTION, string="Type", default="factual", required=True)
    corrected = fields.Boolean()
    rationale = fields.Text()
    register_only = fields.Boolean(readonly=True)
    posted = fields.Boolean(readonly=True)
    misstatement_id = fields.Many2one("ea.audit.misstatement", ondelete="set null", readonly=True)
    amount = fields.Float(digits=(18, 2), compute="_compute_amount", compute_sudo=True)
    is_trivial = fields.Boolean(string="Clearly trivial", compute="_compute_amount", compute_sudo=True)
    stale = fields.Boolean(compute="_compute_amount", compute_sudo=True)
    source_finding_id = fields.Many2one("ea.audit.finding", string="Finding", compute="_compute_source", compute_sudo=True)
    source_procedure_id = fields.Many2one(PROC_MODEL, string="Procedure", compute="_compute_source", compute_sudo=True)
    source_label = fields.Char(string="Source", compute="_compute_source", compute_sudo=True)
    entered_by_hand = fields.Boolean(string="Entered before 2026-11-17", compute="_compute_source", compute_sudo=True)

    @api.depends("misstatement_id", "file_item_id")
    @api.depends_context("lang")
    def _compute_source(self):
        Finding = self.env["ea.audit.finding"].sudo()
        items = self.misstatement_id
        findings = Finding.search([("misstatement_id", "in", items.ids)]) if items else Finding
        by_item = {finding.misstatement_id.id: finding for finding in findings}
        for entry in self:
            finding = by_item.get(entry.misstatement_id.id) if entry.misstatement_id else None
            record = entry._ea_source_record(finding)
            proc = None
            if record is not None and record._name == PROC_MODEL:
                proc = record
            elif record is not None and "designed_procedure_id" in record._fields:
                proc = record.designed_procedure_id or None
            entry.source_finding_id = finding or False
            entry.source_procedure_id = proc or False
            entry.entered_by_hand = record is None
            entry.source_label = entry._ea_source_text(record, proc, finding)

    def _ea_source_record(self, finding):
        if not finding or not finding.source_model or finding.source_model not in self.env or not finding.source_id:
            return None
        return self.env[finding.source_model].sudo().browse(finding.source_id).exists() or None

    def _ea_source_text(self, record, proc, finding):
        """Procedure code · account · paper; for a line with no paper behind it, its age."""
        fr = is_french(self.env)
        if proc:
            definition = LEAD_INDEX_BY_CODE.get(proc.index_code)
            account = lead_index_label(definition, "fr" if fr else "en") if definition else (proc.index_code or "")
            return " · ".join(p for p in (proc.code or "", account, proc.file_item_id.code or "") if p)
        if record is not None:
            if record._name == "ea.audit.file.item":
                return record.code or ""
            name = ("purpose" in record._fields and record.purpose) or record.display_name or ""
            return " · ".join(p for p in (name, self.file_item_id.code or "") if p)
        before = self.env._("Entered before 2026-11-17")
        return " · ".join(p for p in (finding.reference if finding else "", before) if p)

    @api.depends("file_item_id", "ref")
    def _compute_refs(self):
        for entry in self:
            entry.task_code = entry.file_item_id.code or "C1.1"

    @api.depends("dr_account", "cr_account", "dr_caption", "cr_caption", "register_only")
    def _compute_captions(self):
        for entry in self:
            # a register line without accounts (a finding of before 2026-11-17) reads as an expense
            fallback = "expense" if entry.register_only else None
            entry.dr_caption_effective = entry.dr_caption or (
                suggest_caption(entry.dr_account) if entry.dr_account else fallback or suggest_caption("")
            )
            entry.cr_caption_effective = entry.cr_caption or (
                suggest_caption(entry.cr_account) if entry.cr_account else fallback or suggest_caption("")
            )

    @api.depends("dr_amount", "cr_amount", "misstatement_id.amount", "misstatement_id.mtype", "misstatement_id.corrected", "mtype", "corrected")
    def _compute_amount(self):
        for entry in self:
            amount = max(abs(entry.dr_amount), abs(entry.cr_amount))
            materiality = entry.engagement_id._ea_materiality_dict()
            nominal = materiality["trivial"] if materiality else None
            entry.amount = amount
            entry.is_trivial = nominal is not None and amount < nominal
            item = entry.misstatement_id
            entry.stale = bool(item) and not entry.register_only and (
                item.amount != amount or item.mtype != entry.mtype or item.corrected != entry.corrected
                or not (item.accounts or "").startswith("Dr %s (" % (entry.dr_account or "—"))
                or " / Cr %s (" % (entry.cr_account or "—") not in (item.accounts or "")
            )

    def _ea_accounts_text(self):
        """As the source: captions as labels in the poster's language (UAT B152)."""
        locale = "fr" if is_french(self.env) else "en"
        return "Dr %s (%s) / Cr %s (%s)" % (
            self.dr_account or "—", SAD_CAPTION_LABELS[self.dr_caption_effective][locale],
            self.cr_account or "—", SAD_CAPTION_LABELS[self.cr_caption_effective][locale],
        )

    @api.model_create_multi
    def create(self, vals_list):
        """Even as superuser a line needs its source: a misstatement whose finding names the
        working-paper record it was raised from (route_finding writes those two first)."""
        if self.env.su:
            Misstatement = self.env["ea.audit.misstatement"].sudo()
            Finding = self.env["ea.audit.finding"].sudo()
            for vals in vals_list:
                item = Misstatement.browse(vals.get("misstatement_id") or [])
                if not item or not Finding.search_count([
                    ("misstatement_id", "=", item.id), ("source_model", "!=", False),
                ]):
                    raise rule_error(self.env, "sad-from-papers")
        return super().create(vals_list)

    def _ea_user_create(self, vals_list):
        """No line is typed on the summary: it comes from the working papers."""
        raise rule_error(self.env, "sad-from-papers")

    def _ea_user_write(self, vals):
        """saveSad: only the review of a line (corrected, rationale, caption). A row already
        posted re-posts so the C1.1 schedule follows (UAT run 2 B11)."""
        self._ea_guard()
        self._ea_only(vals, REVIEW_FIELDS)
        for entry in self.sudo():
            entry.write(vals)
            if entry.posted:
                entry.with_env(self.env)._ea_post()
        return True

    def _ea_user_unlink(self):
        self._ea_guard()
        for entry in self.sudo():
            if entry.posted or entry.register_only:
                raise rule_error(self.env, "forbidden")
        self.sudo().unlink()
        return True

    def _ea_post(self):
        self.ensure_one()
        as_root = self.sudo()
        Misstatement = self.env["ea.audit.misstatement"].sudo()
        if as_root.register_only:
            as_root.misstatement_id.write({"mtype": as_root.mtype, "corrected": as_root.corrected})
            return True
        materiality = as_root.engagement_id._ea_materiality_dict()
        amount = max(abs(as_root.dr_amount), abs(as_root.cr_amount))
        values = {
            "description": as_root.finding or "%s adjustment" % (as_root.ref or as_root.task_code),
            "accounts": self._ea_accounts_text(),
            "amount": amount,
            "mtype": as_root.mtype,
            "corrected": as_root.corrected,
            "trivial": amount < materiality["trivial"] if materiality else False,
        }
        if as_root.misstatement_id:
            as_root.misstatement_id.write(values)
        else:
            as_root.write({"misstatement_id": Misstatement.create({
                "engagement_id": as_root.engagement_id.id,
                "file_item_id": as_root.file_item_id.id,
                "created_by_id": self.env.user.id,
                **values,
            }).id, "posted": True})
        return True

    def action_post(self):
        """postSadEntry: onto the schedule C1.1 evaluates."""
        for entry in self:
            entry._ea_guard()
            entry._ea_post()
        return True


class SadMeta(models.Model):
    """The workbook's tab meta. ``concl_text`` is what proves the tool ran (F004)."""

    _name = "ea.audit.sad.meta"
    _inherit = ["ea.audit.tool.record"]
    _description = "Summary of audit differences conclusion"
    _rec_name = "engagement_id"

    concl_text = fields.Text(string="Team conclusion")
    tax_rate = fields.Float(string="Tax rate %", default=33, digits=(5, 2))
    turnaround_factual = fields.Float(string="Prior-period turnaround: factual and projected", digits=(18, 2))
    turnaround_judgmental = fields.Float(string="Prior-period turnaround: judgmental", digits=(18, 2))
    income_after_tax = fields.Float(
        string="Income after tax (override)", digits=(18, 2),
        help="Leave at 0 to use the result of the trial balance. Enter a figure only when the file's result differs.",
    )
    income_after_tax_tb = fields.Float(string="Income after tax, from the trial balance", digits=(18, 2), compute="_compute_income_after_tax_tb", compute_sudo=True)
    tq_1 = fields.Selection(ANSWER_SELECTION, string="1. Misstatements sensitive in the entity's circumstances")
    tq_1c = fields.Char(string="Comment 1")
    tq_2 = fields.Selection(ANSWER_SELECTION, string="2. Misstatements masking a change in earnings or other trends")
    tq_2c = fields.Char(string="Comment 2")
    tq_3 = fields.Selection(ANSWER_SELECTION, string="3. Possible management bias")
    tq_3c = fields.Char(string="Comment 3")
    tq_4 = fields.Selection(ANSWER_SELECTION, string="4. Intentional misstatements (possible fraud)")
    tq_4c = fields.Char(string="Comment 4")
    tq_5 = fields.Selection(ANSWER_SELECTION, string="5. Material effect of prior-period uncorrected misstatements")
    tq_5c = fields.Char(string="Comment 5")
    cf_row_ids = fields.One2many("ea.audit.sad.cf.row", "meta_id", string="Cash-flow misstatements")
    disc_row_ids = fields.One2many("ea.audit.sad.disc.row", "meta_id", string="Disclosure misstatements")

    _uniq = models.Constraint("UNIQUE(engagement_id)", "An engagement has one SAD conclusion.")

    def _compute_income_after_tax_tb(self):
        for meta in self:
            fs = fs_caption_amounts(meta.engagement_id._ea_tb_balances())
            meta.income_after_tax_tb = fs["netResultAfterTax"] if fs else 0

    def _ea_user_write(self, vals):
        """saveSadMeta. The child lists save themselves, through their own guard."""
        self._ea_guard()
        allowed = {
            "concl_text", "tax_rate", "turnaround_factual", "turnaround_judgmental", "income_after_tax",
            "cf_row_ids", "disc_row_ids",
        } | {"tq_%d" % i for i in range(1, 6)} | {"tq_%dc" % i for i in range(1, 6)}
        self._ea_only(vals, allowed)
        if "tax_rate" in vals and not 0 <= (vals["tax_rate"] or 0) <= 100:
            raise rule_error(self.env, "invalid-value")
        for meta in self.sudo():
            values = dict(vals)
            for key in ("cf_row_ids", "disc_row_ids"):
                if key in values:
                    values[key] = [
                        (c[0], c[1], {**c[2], "engagement_id": meta.engagement_id.id}) if c[0] == 0 else c
                        for c in values[key]
                    ]
            meta.write(values)
        return True


class SadCfRow(models.Model):
    _name = "ea.audit.sad.cf.row"
    _inherit = ["ea.audit.tool.record"]
    _description = "SAD cash-flow misstatement"
    _order = "id"

    meta_id = fields.Many2one("ea.audit.sad.meta", required=True, ondelete="cascade", index=True)
    no = fields.Char(string="No.")
    ref = fields.Char(string="W/P ref.")
    line = fields.Char(string="Statement of cash flows line")
    operating = fields.Float(digits=(18, 2))
    investing = fields.Float(digits=(18, 2))
    financing = fields.Float(digits=(18, 2))
    evaluation = fields.Text(string="Evaluation and conclusion")


class SadDiscRow(models.Model):
    _name = "ea.audit.sad.disc.row"
    _inherit = ["ea.audit.tool.record"]
    _description = "SAD disclosure misstatement"
    _order = "id"

    meta_id = fields.Many2one("ea.audit.sad.meta", required=True, ondelete="cascade", index=True)
    no = fields.Char(string="No.")
    fn = fields.Char(string="FN reference")
    description = fields.Char(string="Description of misstatement")
    guidance = fields.Char(string="Authoritative guidance")
    evaluation = fields.Text(string="Evaluation and conclusion")
    corrected = fields.Boolean()


class EngagementSad(models.Model):
    _inherit = "ea.audit.engagement"

    sad_entry_ids = fields.One2many("ea.audit.sad.entry", "engagement_id", string="Audit differences")
    sad_meta_id = fields.Many2one("ea.audit.sad.meta", string="SAD conclusion", compute="_compute_sad_meta", compute_sudo=True)
    sad_concl_text = fields.Text(string="Team conclusion", related="sad_meta_id.concl_text")
    sad_income_label = fields.Char(string="Income after tax", compute="_compute_sad_income", compute_sudo=True)
    sad_income_note = fields.Char(compute="_compute_sad_income", compute_sudo=True)

    @api.depends_context("lang")
    def _compute_sad_income(self):
        for engagement in self:
            fs = fs_caption_amounts(engagement._ea_tb_balances())
            from_tb = fs["netResultAfterTax"] if fs else None
            override = engagement._ea_sad_meta(create=False).income_after_tax
            value = effective_income_after_tax(override, from_tb)
            engagement.sad_income_label = fcfa(value)
            if override:
                engagement.sad_income_note = self.env._("Entered by the team; the trial balance reads %(amount)s", amount=fcfa(from_tb))
            elif fs:
                engagement.sad_income_note = self.env._("From the trial balance, income tax (89) deducted")
            else:
                engagement.sad_income_note = self.env._("No trial balance imported yet")

    def _compute_sad_meta(self):
        for engagement in self:
            engagement.sad_meta_id = engagement._ea_sad_meta(create=False)

    def _ea_sad_meta(self, create=True):
        self.ensure_one()
        Meta = self.env["ea.audit.sad.meta"].sudo()
        meta = Meta.search([("engagement_id", "=", self.id)], limit=1)
        if not meta and create:
            meta = Meta.create({"engagement_id": self.id})
        return meta

    def save_sad_conclusion(self, text):
        """saveSadMeta, concl_text."""
        self.ensure_one()
        self._ea_tool_guard()
        self._ea_sad_meta().write({"concl_text": text or False})
        return True

    def _ea_sad_view(self):
        """sadView: what the workbook's six tabs need."""
        self.ensure_one()
        as_root = self.sudo()
        materiality = as_root._ea_materiality_dict()
        fs = fs_caption_amounts(as_root._ea_tb_balances())
        meta = as_root._ea_sad_meta(create=False)
        tb = as_root._ea_tb()
        entries = []
        for entry in self.env["ea.audit.sad.entry"].sudo().search([("engagement_id", "=", self.id)]):
            # every line, a clearly trivial one included: the workbook sets those apart (ISA 450 para 5)
            entries.append({
                "taskCode": entry.task_code, "taskTitle": entry.file_item_id.title or "",
                "ref": entry.ref or entry.source_procedure_id.code or entry.task_code, "finding": entry.finding or "",
                "drAccount": entry.dr_account or "", "drAmount": entry.dr_amount,
                "crAccount": entry.cr_account or "", "crAmount": entry.cr_amount,
                "drCaption": entry.dr_caption_effective, "crCaption": entry.cr_caption_effective,
                "mtype": entry.mtype, "corrected": entry.corrected, "rationale": entry.rationale or "",
            })
        return {
            "entries": entries,
            "materiality": materiality,
            "entityName": as_root.client_id.name or "",
            "periodEnd": str(as_root.period_end or ""),
            "currency": tb.currency or "XAF",
            "fsCaptions": fs["columns"] if fs else None,
            "incomeBeforeTax": fs["incomeBeforeTax"] if fs else None,
            "netResultAfterTax": fs["netResultAfterTax"] if fs else None,
            "meta": {
                "tax_rate": meta.tax_rate if meta else 33,
                "turnaround_factual": meta.turnaround_factual if meta else 0,
                "turnaround_judgmental": meta.turnaround_judgmental if meta else 0,
                "income_after_tax": effective_income_after_tax(meta.income_after_tax if meta else 0, fs["netResultAfterTax"] if fs else 0),
                "concl_text": meta.concl_text or "" if meta else "",
                **{"tq_%d" % i: (meta["tq_%d" % i] or "") if meta else "" for i in range(1, 6)},
                **{"tq_%dc" % i: (meta["tq_%dc" % i] or "") if meta else "" for i in range(1, 6)},
            },
            "cfRows": [{
                "no": r.no or "", "ref": r.ref or "", "line": r.line or "", "operating": r.operating,
                "investing": r.investing, "financing": r.financing, "evaluation": r.evaluation or "",
            } for r in meta.cf_row_ids] if meta else [],
            "discRows": [{
                "no": r.no or "", "fn": r.fn or "", "description": r.description or "", "guidance": r.guidance or "",
                "evaluation": r.evaluation or "", "corrected": r.corrected,
            } for r in meta.disc_row_ids] if meta else [],
        }

    def action_open_sad_conclusion(self):
        self.ensure_one()
        self._ea_require_access()
        meta = self.sudo()._ea_sad_meta()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("SAD conclusion"),
            "res_model": "ea.audit.sad.meta",
            "res_id": meta.id,
            "view_mode": "form",
            "views": [(self.env.ref("ea_audit_tools.view_sad_meta_form").id, "form")],
            "target": "current",
            "context": {"ea_engagement_id": self.id},
        }

    def action_export_sad(self):
        return self._ea_export_action("sad")

