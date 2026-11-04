from odoo.addons.ea_audit_core.tests.common import EaAuditCase

from ..services import paper_for, required_keys


class PaperCase(EaAuditCase):
    """One engagement with a seated team, in execution so that every phase is open."""

    ea_real_paper_hooks = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Note = cls.env["ea.audit.review.note"]
        cls.Attachment = cls.env["ea.audit.task.attachment"]
        cls.Conclusion = cls.env["ea.audit.section.conclusion"]

    def setUp(self):
        super().setUp()
        self.engagement = self.make_engagement()
        self.seat(self.engagement, self.manager, "manager")
        self.seat(self.engagement, self.senior, "senior")
        self.seat(self.engagement, self.staff, "staff")
        self.set_phase(self.engagement, "execution")

    def paper(self, code, engagement=None):
        return self.item(engagement or self.engagement, code)._ea_paper()

    def save(self, user, code, values, base_version=None, digests=None, engagement=None):
        return self.paper(code, engagement).with_user(user).save_answers(values, base_version, digests)

    def stored(self, code, engagement=None):
        return self.paper(code, engagement)._ea_values()

    def full_answers(self, code, form=None):
        """Every required key answered the plain way."""
        definition = paper_for(code, "current", form or self.client.legal_form)
        return {
            key: "yes" if key[:2] in ("q_", "c_") else "Done, see file."
            for key in required_keys(definition)
        }

    def complete(self, user, code, engagement=None):
        self.save(user, code, self.full_answers(code), engagement=engagement)

    def signed_paper(self, code="P3.1"):
        """The senior prepared it (P3.1's minimum), the manager reviewed it."""
        self.complete(self.senior, code)
        self.sign(self.senior, self.engagement, code, "preparer")
        self.sign(self.manager, self.engagement, code, "reviewer")
        return self.paper(code)

    def active(self, code="P3.1"):
        return self.paper(code)._ea_active_signoffs()

    def upload(self, user, code, name="evidence.txt", content=b"evidence"):
        import base64

        return self.item(self.engagement, code).with_user(user).upload_attachment(
            name, base64.b64encode(content).decode(),
        )
