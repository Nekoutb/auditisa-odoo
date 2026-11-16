"""The adjustment of a misstatement finding (owner's mock-up of 2026-11-16, "mock-finding-adj").

On the findings page a misstatement carries the entry that corrects it: lines of account, label,
debit and credit, its nature, and what it does to profit, assets, liabilities and equity. The
lines are the finding's own and stay editable until "Book to the summary of audit differences":
booking writes the summary's lines (ea.audit.sad.entry, one debit account against one credit
account each) and the C1.1 misstatement from them, then locks the lines. From then on the
summary is where the line is reviewed (corrected by management, rationale), as for any line.

The summary still takes no typed line: its lines come from the finding raised on a working
paper (route_finding / ea_raise_finding), and the finding keeps its own source paper.
"""
from odoo import api, fields, models

from ..rules import rule_error
from ..services.finding_adjustment import (
    ADJUSTMENT_NATURES,
    AdjustmentError,
    accounts_text,
    adjustment_effect,
    adjustment_pairs,
    booking_error,
    clean_lines,
    totals,
)
from .tool_record import french_date, grouped


class FindingAdjustmentLine(models.Model):
    _name = "ea.audit.finding.adjustment"
    _inherit = ["ea.audit.tool.record"]
    _description = "Finding adjustment line"
    _order = "finding_id, sequence, id"

    finding_id = fields.Many2one("ea.audit.finding", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    account = fields.Char(size=64)
    label = fields.Char()
    debit = fields.Float(digits=(18, 2))
    credit = fields.Float(digits=(18, 2))
    booked = fields.Boolean(readonly=True)
    booked_by_id = fields.Many2one("res.users", string="Booked by", ondelete="restrict", readonly=True)
    booked_at = fields.Datetime(string="Booked on", readonly=True)


class FindingAdjustment(models.Model):
    _inherit = "ea.audit.finding"

    adjustment_ids = fields.One2many("ea.audit.finding.adjustment", "finding_id", string="Adjustment")
    adjustment_booked = fields.Boolean(compute="_compute_adjustment_booked", compute_sudo=True)

    @api.depends("adjustment_ids.booked")
    def _compute_adjustment_booked(self):
        for finding in self:
            finding.adjustment_booked = bool(finding.adjustment_ids) and all(finding.adjustment_ids.mapped("booked"))

    def _ea_sad_entries(self):
        self.ensure_one()
        item = self.sudo().misstatement_id
        if not item:
            return self.env["ea.audit.sad.entry"].sudo()
        return self.env["ea.audit.sad.entry"].sudo().search([("misstatement_id", "=", item.id)], order="id")

    def _ea_adjustment_lines(self):
        """The lines as dicts: those saved, else the accounts the misstatement was raised with,
        as a first draft (nothing is saved until the team changes or books it)."""
        self.ensure_one()
        root = self.sudo()
        if root.adjustment_ids:
            return [
                {"account": line.account or "", "label": line.label or "", "debit": line.debit, "credit": line.credit}
                for line in root.adjustment_ids
            ]
        lines = []
        for entry in root._ea_sad_entries():
            if entry.dr_account and entry.dr_amount:
                lines.append({"account": entry.dr_account, "label": root.title or "", "debit": entry.dr_amount, "credit": 0.0})
            if entry.cr_account and entry.cr_amount:
                lines.append({"account": entry.cr_account, "label": root.title or "", "debit": 0.0, "credit": entry.cr_amount})
        return lines

    def _ea_adjustment_check(self):
        self.ensure_one()
        self._ea_guard()
        root = self.sudo()
        if root.route != "b5" or not root.misstatement_id:
            raise rule_error(self.env, "adjustment-misstatement")
        if root.adjustment_booked:
            raise rule_error(self.env, "adjustment-booked")
        return root

    def _ea_write_lines(self, lines):
        root = self.sudo()
        root.adjustment_ids.unlink()
        Line = self.env["ea.audit.finding.adjustment"].sudo()
        for sequence, line in enumerate(lines, 1):
            Line.create({"engagement_id": root.engagement_id.id, "finding_id": root.id, "sequence": sequence, **line})

    def ea_save_adjustment(self, lines=None, nature=None):
        """The draft: the lines replace those saved, the nature is the misstatement's type (the
        summary line reads the same field). Refused once booked."""
        root = self._ea_adjustment_check()
        if lines is not None:
            try:
                cleaned = clean_lines(lines)
            except AdjustmentError as error:
                raise rule_error(self.env, error.code) from error
            self._ea_write_lines(cleaned)
        if nature is not None:
            if nature not in ADJUSTMENT_NATURES:
                raise rule_error(self.env, "invalid-type")
            root.misstatement_id.write({"mtype": nature})
            root._ea_sad_entries().write({"mtype": nature})
        return True

    def ea_book_adjustment(self):
        """Book to the summary of audit differences: its lines and the C1.1 misstatement are
        written from the adjustment, which is locked from then on."""
        root = self._ea_adjustment_check()
        lines = clean_lines(root._ea_adjustment_lines())
        code = booking_error(lines)
        if code:
            raise rule_error(self.env, code)
        if not root.adjustment_ids:
            self._ea_write_lines(lines)
        item = root.misstatement_id
        engagement = root.engagement_id
        Entry = self.env["ea.audit.sad.entry"].sudo()
        entries = root._ea_sad_entries()
        pairs = adjustment_pairs(lines)
        for index, pair in enumerate(pairs):
            values = {
                "finding": root.title, "mtype": item.mtype,
                "dr_account": pair["dr_account"], "dr_amount": pair["amount"],
                "cr_account": pair["cr_account"], "cr_amount": pair["amount"],
            }
            if index < len(entries):
                entries[index].write(values)
            else:
                Entry.create({
                    **values, "engagement_id": engagement.id, "file_item_id": root.file_item_id.id,
                    "misstatement_id": item.id, "register_only": True, "posted": True,
                    "corrected": item.corrected,
                })
        entries[len(pairs):].unlink()
        total = totals(lines)["debit"]
        text = accounts_text(lines)
        materiality = engagement._ea_materiality_dict()
        item.write({
            "amount": total, "accounts": text,
            "trivial": bool(materiality) and total < materiality["trivial"],
        })
        root.adjustment_ids.write({"booked": True, "booked_by_id": self.env.user.id, "booked_at": fields.Datetime.now()})
        engagement.with_env(self.env)._ea_log(
            "finding_adjustment_booked",
            "Adjustment of finding %s booked on the summary of audit differences: %s for %s" % (
                root.reference, text, grouped(total, "en_US"),
            ),
        )
        return True

    def _ea_adjustment_view(self, lang, figure):
        """What the Adjustment section of the findings page shows."""
        self.ensure_one()
        root = self.sudo()
        lines = root._ea_adjustment_lines()
        try:
            cleaned = clean_lines(lines)
        except AdjustmentError:
            cleaned = []
        sums = totals(cleaned)
        effect = adjustment_effect(cleaned)
        booked = root.adjustment_booked
        first = root.adjustment_ids[:1]
        _ = self.env._
        shown = {key: figure(value, lang) for key, value in effect.items()}
        entry = root._ea_sad_entries()[:1]
        number = root.engagement_id._ea_sad_numbers().get(entry.id, "") if entry else ""
        source = root.source_label
        return {
            "effectText": _(
                "Profit %(profit)s · Assets %(assets)s · Liabilities %(liabilities)s · Equity %(equity)s",
                **shown,
            ),
            "bookedText": _(
                "Booked as %(number)s on %(date)s by %(name)s",
                number=number, date=french_date(first.booked_at), name=first.booked_by_id.name or "",
            ) if booked else "",
            "hint": (_(
                "Booked lines can be marked “corrected by management” on the summary. The line links back to this finding and to %s. Equity includes the effect on profit.",
                source,
            ) if source else _(
                "Booked lines can be marked “corrected by management” on the summary. The line links back to this finding. Equity includes the effect on profit.",
            )),
            "lines": [dict(
                line, debit=figure(line["debit"], lang) if line["debit"] else "",
                credit=figure(line["credit"], lang) if line["credit"] else "",
            ) for line in lines],
            "nature": root.misstatement_id.mtype,
            "totalDebit": figure(sums["debit"], lang), "totalCredit": figure(sums["credit"], lang),
            "balanced": sums["balanced"],
            "effect": shown,
            "booked": booked,
            "canBook": not booked and booking_error(cleaned) is None,
        }
