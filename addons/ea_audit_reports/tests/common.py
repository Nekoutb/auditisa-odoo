from datetime import date

from odoo.addons.ea_audit_tools.tests.common import ToolsCase

from ..services.archive_seal import ARCHIVE_CONFIRMS, QUESTIONS, answer_key, note_key
from ..services.docx_builder import docx_text

MATERIALITY = {"overall": 10_000_000.0, "performance": 7_000_000.0, "trivial": 500_000.0}


class ReportsCase(ToolsCase):
    """ToolsCase's file and team, and what it takes to turn the completion gates green."""

    def setUp(self):
        # A French firm: the documents below read in the engagement's report language, its default.
        self.env.company.sudo().partner_id.lang = "fr_FR"
        super().setUp()
        self.as_partner = self.engagement.with_user(self.partner)
        self.as_manager = self.engagement.with_user(self.manager)
        self.as_senior = self.engagement.with_user(self.senior)
        self.as_staff = self.engagement.with_user(self.staff)

    def text_of(self, document):
        return docx_text(document.sudo().current_version_id.attachment_id.raw)

    def answer(self, code, key, value, user=None, engagement=None):
        engagement = engagement or self.engagement
        paper = self.env["ea.audit.paper"].sudo().search([("engagement_id", "=", engagement.id), ("code", "=", code)], limit=1)
        if not paper:
            self.item(engagement, code)._ea_ensure_papers()
            paper = self.env["ea.audit.paper"].sudo().search([("engagement_id", "=", engagement.id), ("code", "=", code)], limit=1)
        writer = user or self.env.user
        Answer = self.env["ea.audit.paper.answer"].sudo().with_context(ea_audit_answer_door=True)
        row = Answer.search([("paper_id", "=", paper.id), ("field_key", "=", key)], limit=1)
        if row:
            row.value = value
        else:
            row = Answer.create({"paper_id": paper.id, "field_key": key, "value": value})
        self.env["ea.audit.paper.answer.history"].sudo().create({
            "paper_id": paper.id, "field_key": key, "after": value, "user_id": writer.id,
        })
        return row

    def signoff(self, code, role, user=None, engagement=None):
        item = self.item(engagement or self.engagement, code)
        return self.env["ea.audit.signoff"].sudo().create({
            "file_item_id": item.id, "kind": "workpaper", "role": role, "user_id": (user or self.staff).id,
        })

    def with_materiality(self, value=MATERIALITY):
        self.patch(type(self.env["ea.audit.engagement"]), "_ea_materiality_dict", lambda _self: value)

    def conclude_risks_and_steps(self, engagement=None):
        engagement = engagement or self.engagement
        self.env["ea.audit.risk"].sudo().search([("engagement_id", "=", engagement.id)]).write({"status": "concluded"})
        self.env["ea.audit.program.step"].sudo().search([("engagement_id", "=", engagement.id)]).write({"status": "done"})

    def record(self, key, data=None, engagement=None):
        return self.env["ea.audit.completion.record"].sudo().create({
            "engagement_id": (engagement or self.engagement).id, "key": key, "data": data or {}, "done_by_id": self.partner.id,
        })

    def eqr_review(self, engagement=None):
        """The appointed reviewer's own record of the review on C4.2."""
        engagement = engagement or self.engagement
        engagement.sudo()._ea_ensure_task("C4.2")
        self.answer("C4.2", "q_complete", "yes", self.eqr, engagement)
        self.answer("C4.2", "q_resolved", "yes", self.eqr, engagement)
        self.signoff("C4.2", "eqr", self.eqr, engagement)

    def green_completion(self, engagement=None, reviewed_to="2026-03-31", eqr=True):
        """Every completion gate met, the way each is met on a real file."""
        engagement = engagement or self.engagement
        self.with_materiality()
        self.set_phase(engagement, "execution")
        self.conclude_risks_and_steps(engagement)
        for key in ("final_analytical_review", "fs_tieout", "disclosure_checklist", "partner_conclusion"):
            self.record(key, engagement=engagement)
        self.record("subsequent_events", {"reviewedTo": reviewed_to}, engagement=engagement)
        as_partner = engagement.with_user(self.partner)
        as_partner.generate_letter("rep_affirmation", "fr")
        as_partner.generate_letter("rep_complementary", "fr")
        self.answer("C4.3", "q_none_open", "yes", engagement=engagement)
        if eqr and engagement.sudo()._ea_eqr_required():
            self.eqr_review(engagement)

    def failed(self, gates):
        return [gate["key"] for gate in gates if not gate["ok"]]

    def green_archive(self, engagement=None):
        """What the archive gates add: every task addressed, every worked task prepared and reviewed."""
        engagement = engagement or self.engagement
        self.patch(type(self.env["ea.audit.engagement"]), "_ea_paper_is_complete", lambda _self, _code: True)
        self.answer_confirmations("C6.2", ARCHIVE_CONFIRMS, engagement)
        items = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", engagement.id)])
        self.env.flush_all()
        self.env.cr.execute("UPDATE ea_audit_file_item SET na_reason = 'Not used', not_applicable = TRUE WHERE id IN %s", [tuple(items.ids)])
        self.env.invalidate_all()
        for row in engagement.sudo()._ea_item_activity():
            if row["worked"] and not row["prepared"]:
                self.signoff(row["item"].code, "preparer", self.staff, engagement)
            if row["worked"] and not row["reviewed"]:
                self.signoff(row["item"].code, "reviewer", self.senior, engagement)

    def answer_confirmations(self, code, questions, engagement=None, value="yes", note="Seen and filed."):
        engagement = engagement or self.engagement
        for question in questions:
            self.answer(code, answer_key(question["key"]), value, engagement=engagement)
            self.answer(code, note_key(question["key"]), note, engagement=engagement)

    def conclude_procedures(self, engagement=None):
        engagement = engagement or self.engagement
        self.env["ea.audit.designed.procedure"].sudo().search([("engagement_id", "=", engagement.id)]).write(
            {"state": "done", "conclusion": "satisfactory"},
        )

    def ready(self, engagement=None, reviewed_to="2026-03-31", eqr=True):
        """Everything the C6.1 checklist asks, then the partner's "ready to issue"."""
        engagement = engagement or self.engagement
        self.green_completion(engagement, reviewed_to=reviewed_to, eqr=eqr)
        self.conclude_procedures(engagement)
        self.answer_confirmations("C6.1", QUESTIONS, engagement)
        self.green_archive(engagement)
        engagement.with_user(self.partner).ea_sign_ready()
        return engagement

    def issued(self, engagement=None, report_date=date(2026, 3, 31)):
        """A file with its report issued."""
        engagement = engagement or self.engagement
        self.ready(engagement)
        engagement.with_user(self.partner).issue_report_from_form(report_date=report_date)
        return engagement

    def archive(self, engagement=None):
        """The engagement partner archives; the test files are past their 60 days."""
        return (engagement or self.engagement).with_user(self.partner).archive_engagement(late_reason="Test file archived late.")
