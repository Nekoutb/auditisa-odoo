"""The adjustment of a misstatement (owner's mock-ups of 2026-11-16 and 2026-11-17, "wp-finding-sad").

At the bottom of its working paper a misstatement carries the entry that corrects it: lines of
heading (one of seven headings of the statements, no trial-balance account any more), label,
debit and credit, its nature, and what it does to profit, assets, liabilities and equity.
Saving a balanced entry sends it to the summary of audit differences by itself: the summary's
lines (ea.audit.sad.entry, one debit heading against one credit heading each) and the C1.1
misstatement are written from it, and the line waits there "To review". There is no "Book"
step any more. Once a reviewer has posted the line, the adjustment is read-only until the line
is unposted (logged).

Lines typed before 2026-11-17 named an account: the account stays, shown as information, and
the line's heading is empty ("to classify") until the team picks one.
"""
from odoo import fields, models

from ..rules import rule_error
from ..services.finding_adjustment import (
    ADJUSTMENT_NATURES,
    HEADING_CAPTION,
    HEADINGS,
    AdjustmentError,
    accounts_text,
    adjustment_effect,
    adjustment_pairs,
    booking_error,
    clean_lines,
    heading_label,
    totals,
)
from .tool_record import french_date, grouped, is_french

HEADING_SELECTION = [(heading, heading_label(heading)) for heading in HEADINGS]


class FindingAdjustmentLine(models.Model):
    _name = "ea.audit.finding.adjustment"
    _inherit = ["ea.audit.tool.record"]
    _description = "Finding adjustment line"
    _order = "finding_id, sequence, id"

    finding_id = fields.Many2one("ea.audit.finding", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    heading = fields.Selection(HEADING_SELECTION, string="Heading")
    #: before 2026-11-17 a line named an account; kept as information only
    account = fields.Char(size=64)
    label = fields.Char()
    debit = fields.Float(digits=(18, 2))
    credit = fields.Float(digits=(18, 2))
    # the "Book" step of 2026-11-16, gone since 2026-11-17: kept so the history stays readable
    booked = fields.Boolean(readonly=True)
    booked_by_id = fields.Many2one("res.users", string="Booked by", ondelete="restrict", readonly=True)
    booked_at = fields.Datetime(string="Booked on", readonly=True)


class FindingAdjustment(models.Model):
    _inherit = "ea.audit.finding"

    adjustment_ids = fields.One2many("ea.audit.finding.adjustment", "finding_id", string="Adjustment")

    def _ea_sad_entries(self):
        self.ensure_one()
        item = self.sudo().misstatement_id
        if not item:
            return self.env["ea.audit.sad.entry"].sudo()
        return self.env["ea.audit.sad.entry"].sudo().search([("misstatement_id", "=", item.id)], order="id")

    def _ea_adjustment_posted(self):
        self.ensure_one()
        return any(entry.review_state == "posted" for entry in self._ea_sad_entries())

    def _ea_adjustment_lines(self):
        """The lines as dicts: those saved, else a first draft from what the misstatement was
        raised with (nothing is saved until the team saves it). Accounts, when the misstatement
        named them, are information only: the heading is the team's to pick."""
        self.ensure_one()
        root = self.sudo()
        if root.adjustment_ids:
            return [
                {
                    "heading": line.heading or "", "account": line.account or "", "label": line.label or "",
                    "debit": line.debit, "credit": line.credit,
                }
                for line in root.adjustment_ids
            ]
        lines = []
        for entry in root._ea_sad_entries():
            if entry.dr_account and entry.dr_amount:
                lines.append({"heading": "", "account": entry.dr_account, "label": root.title or "", "debit": entry.dr_amount, "credit": 0.0})
            if entry.cr_account and entry.cr_amount:
                lines.append({"heading": "", "account": entry.cr_account, "label": root.title or "", "debit": 0.0, "credit": entry.cr_amount})
        if not lines and root.misstatement_id.amount:
            amount = abs(root.misstatement_id.amount)
            lines = [
                {"heading": "", "account": "", "label": root.title or "", "debit": amount, "credit": 0.0},
                {"heading": "", "account": "", "label": "", "debit": 0.0, "credit": amount},
            ]
        return lines

    def _ea_adjustment_check(self):
        self.ensure_one()
        self._ea_guard()
        root = self.sudo()
        if root.route != "b5" or not root.misstatement_id:
            raise rule_error(self.env, "adjustment-misstatement")
        if root._ea_adjustment_posted():
            raise rule_error(self.env, "adjustment-posted")
        return root

    def _ea_write_lines(self, lines):
        root = self.sudo()
        root.adjustment_ids.unlink()
        Line = self.env["ea.audit.finding.adjustment"].sudo()
        for sequence, line in enumerate(lines, 1):
            Line.create({
                "engagement_id": root.engagement_id.id, "finding_id": root.id, "sequence": sequence,
                "heading": line["heading"] or False, "account": line["account"] or False,
                "label": line["label"] or False, "debit": line["debit"], "credit": line["credit"],
            })

    def ea_save_adjustment(self, lines=None, nature=None):
        """Save the adjustment: balanced lines, each with its heading, and its nature (the
        misstatement's type, which the summary line reads too). The summary of audit
        differences and the C1.1 misstatement follow by themselves; the line waits there
        "To review". Refused once a reviewer has posted it."""
        root = self._ea_adjustment_check()
        if nature is not None and nature not in ADJUSTMENT_NATURES:
            raise rule_error(self.env, "invalid-type")
        if nature is not None:
            root.misstatement_id.write({"mtype": nature})
            root._ea_sad_entries().write({"mtype": nature})
        if lines is None:
            return True
        try:
            cleaned = clean_lines(lines)
        except AdjustmentError as error:
            raise rule_error(self.env, error.code) from error
        code = booking_error(cleaned)
        if code:
            raise rule_error(self.env, code)
        self._ea_write_lines(cleaned)
        self._ea_send_to_sad(cleaned)
        return True

    def _ea_send_to_sad(self, lines):
        """The summary's lines and the C1.1 misstatement, written from the saved entry."""
        root = self.sudo()
        item = root.misstatement_id
        engagement = root.engagement_id
        Entry = self.env["ea.audit.sad.entry"].sudo()
        entries = root._ea_sad_entries()
        carried = {
            "review_note_id": entries[:1].review_note_id.id or False,
        }
        pairs = adjustment_pairs(lines)
        user = self.env.user
        for index, pair in enumerate(pairs):
            values = {
                "finding": root.title, "mtype": item.mtype,
                "dr_account": False, "dr_amount": pair["amount"], "dr_caption": HEADING_CAPTION[pair["dr"]],
                "cr_account": False, "cr_amount": pair["amount"], "cr_caption": HEADING_CAPTION[pair["cr"]],
                "prepared_by_id": user.id,
            }
            if index < len(entries):
                entries[index].write(values)
            else:
                Entry.create({
                    **values, **carried, "engagement_id": engagement.id, "file_item_id": root.file_item_id.id,
                    "misstatement_id": item.id, "register_only": True, "posted": True,
                    "corrected": item.corrected,
                })
        entries[len(pairs):].unlink()
        total = totals(lines)["debit"]
        text = accounts_text(lines, "fr" if is_french(self.env) else "en")
        materiality = engagement._ea_materiality_dict()
        item.write({
            "amount": total, "accounts": text,
            "trivial": bool(materiality) and total < materiality["trivial"],
        })
        engagement.with_env(self.env)._ea_log(
            "finding_adjustment_saved",
            "Adjustment of finding %s saved and sent to the summary of audit differences, to review: %s for %s" % (
                root.reference, accounts_text(lines), grouped(total, "en_US"),
            ),
        )

    def _ea_adjustment_view(self, lang, figure):
        """What the Adjustment section shows, on the working paper and on the findings page."""
        self.ensure_one()
        root = self.sudo()
        locale = "fr" if lang == "fr_FR" else "en"
        lines = root._ea_adjustment_lines()
        try:
            cleaned = clean_lines(lines)
        except AdjustmentError:
            cleaned = []
        sums = totals(cleaned)
        effect = adjustment_effect(cleaned)
        _ = self.env._
        shown = {key: figure(value, lang) for key, value in effect.items()}
        entries = root._ea_sad_entries()
        entry = entries[:1]
        number = root.engagement_id._ea_sad_numbers().get(entry.id, "") if entry else ""
        status = entry._ea_review_status() if entry else False
        posted = status == "posted"
        status_words = {"to_review": _("To review"), "note": _("Review note open"), "posted": _("Posted")}
        if posted:
            status_text = _(
                "%(number)s posted by %(name)s on %(date)s: unpost it on the summary to change it",
                number=number, name=entry.reviewed_by_id.name or "", date=french_date(entry.reviewed_at),
            )
        elif entry:
            status_text = _("On the summary of audit differences as %(number)s · %(status)s", number=number, status=status_words[status])
        else:
            status_text = ""
        note = entry.review_note_id if entry and status == "note" else False
        return {
            "effectText": _(
                "Profit %(profit)s · Assets %(assets)s · Liabilities %(liabilities)s · Equity %(equity)s",
                **shown,
            ),
            "lines": [dict(
                line, headingLabel=heading_label(line["heading"], locale),
                debitText=figure(line["debit"], lang) if line["debit"] else "",
                creditText=figure(line["credit"], lang) if line["credit"] else "",
            ) for line in lines],
            "headings": [{"value": heading, "label": heading_label(heading, locale)} for heading in HEADINGS],
            "nature": root.misstatement_id.mtype,
            "totalDebit": figure(sums["debit"], lang), "totalCredit": figure(sums["credit"], lang),
            "balanced": sums["balanced"],
            "effect": shown,
            "sad": number, "status": status or "", "statusText": status_text,
            "note": {
                "body": note.body, "author": note.author_id.name or "",
            } if note else False,
            "posted": posted,
            "canSend": not posted and booking_error(cleaned) is None,
        }

