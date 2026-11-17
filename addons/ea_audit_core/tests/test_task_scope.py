"""The task scope of 2026-11-17 on real files: facts decide whether a task applies, the complexity how
deep it goes; a live file changes only when its partner applies the current scope."""
from odoo.tests import tagged

from odoo.addons.ea_audit_core.services.file_scope import CONTROLS_CODES, SCOPE_CURRENT, SCOPE_LEGACY

from .common import EaAuditCase


@tagged("post_install", "-at_install")
class TestTaskScope(EaAuditCase):
    def active(self, engagement):
        return set(engagement.sudo().file_item_ids.filtered(lambda i: not i.conditional).mapped("code"))

    def on_file(self, engagement):
        return set(engagement.sudo().file_item_ids.mapped("code"))

    def trail(self, engagement, action):
        return self.env["ea.audit.activity"].sudo().search([("engagement_id", "=", engagement.id), ("action", "=", action)])

    def work_on(self, engagement, code):
        """A sign-off: the task holds work."""
        item = self.item(engagement, code)
        self.env["ea.audit.signoff"].sudo().create({
            "file_item_id": item.id, "kind": "workpaper", "role": "preparer", "user_id": self.senior.id,
        })
        return item

    # ------------------------------------------------------------------ a new file

    def test_a_new_file_gets_the_current_scope(self):
        engagement = self.make_engagement(complexity="very_simple")
        self.assertEqual(engagement.sudo().scope_version, SCOPE_CURRENT)
        active = self.active(engagement)
        self.assertLessEqual({"P2.2", "P4.1", "P4.3", "S1.1", "S1.2", "S1.4", "S4.1", "S5.4", "S5.5", "C5.3"}, active)
        self.assertLessEqual({"C5.4", "C5.7", "C5.10"}, active)
        # facts decide: on the file, waiting
        for code in ("P1.2", "P2.3", "S5.1", "C1.3", "C4.2", "C5.5", "C5.6", "C5.9") + CONTROLS_CODES:
            self.assertTrue(self.item(engagement, code).conditional, code)
        self.assertFalse({"P4.2", "C5.8", "C4.3"} & self.on_file(engagement))

    def test_the_sa_papers_follow_the_legal_form(self):
        sarl = self.env["ea.audit.client"].create({"name": "Petite SARL", "legal_form": "SARL"})
        engagement = self.make_engagement(client=sarl, complexity="complex")
        self.assertFalse({"C5.4", "C5.7", "C5.10"} & self.on_file(engagement))
        self.assertIn("C5.3", self.active(engagement))

    def test_a_merged_task_never_comes_back(self):
        engagement = self.make_engagement()
        for code in ("P4.2", "C5.8", "C4.3", "P7.1"):
            self.assertFalse(engagement.sudo()._ea_ensure_task(code), code)
        self.assertFalse({"P4.2", "C5.8", "C4.3", "P7.1"} & self.on_file(engagement))
        older = self.make_engagement(scope_version=SCOPE_LEGACY)
        self.assertIn("C4.3", self.active(older))
        self.assertTrue(older.sudo()._ea_ensure_task("P4.2"))

    def test_the_consultation_question_brings_c13(self):
        engagement = self.make_engagement(complexity="non_complex")
        as_partner = engagement.with_user(self.partner)
        as_partner.write({"consultation_needed": "yes"})
        self.assertIn("C1.3", self.active(engagement))
        self.assertTrue(self.trail(engagement, "tasks_from_facts"))
        self.assertTrue(self.trail(engagement, "scope_fact"))
        as_partner.write({"consultation_needed": "no"})
        self.assertNotIn("C1.3", self.active(engagement))
        as_partner.write({"joint_auditors": "yes"})
        self.assertIn("C5.9", self.active(engagement))

    def test_a_task_holding_work_stays_when_the_answer_turns_no(self):
        engagement = self.make_engagement(complexity="non_complex")
        engagement.with_user(self.partner).write({"consultation_needed": "yes"})
        self.work_on(engagement, "C1.3")
        engagement.with_user(self.partner).write({"consultation_needed": "no"})
        self.assertIn("C1.3", self.active(engagement))

    def test_an_answer_on_an_older_file_changes_no_task(self):
        older = self.make_engagement(complexity="very_simple", scope_version=SCOPE_LEGACY)
        before = self.active(older)
        older.with_user(self.partner).write({"consultation_needed": "yes", "joint_auditors": "yes"})
        self.assertEqual(self.active(older), before)

    def test_a_first_year_file_has_p12_at_every_complexity(self):
        engagement = self.make_engagement(complexity="very_simple", first_year=True)
        self.assertIn("P1.2", self.active(engagement))

    def test_an_it_answer_does_not_take_off_a_task_every_file_has(self):
        engagement = self.make_engagement(complexity="non_complex")
        engagement.sudo()._ea_set_task_active("P4.3", False)
        self.assertIn("P4.3", self.active(engagement))

    # ------------------------------------------------------------------ a live file: the partner decides

    def test_the_partner_applies_the_current_scope(self):
        older = self.make_engagement(complexity="very_simple", scope_version=SCOPE_LEGACY)
        self.assertNotIn("P2.2", self.active(older))
        self.assertIn("C4.3", self.active(older))
        self.seat(older, self.manager, "manager")
        self.assertCode("forbidden", older.with_user(self.manager).action_rescope)
        older.with_user(self.partner).action_rescope()
        self.assertEqual(older.sudo().scope_version, SCOPE_CURRENT)
        active = self.active(older)
        self.assertLessEqual({"P2.2", "P4.1", "P4.3", "S1.1", "C5.3"}, active)
        self.assertNotIn("C4.3", active)
        self.assertTrue(self.item(older, "C4.3").conditional)
        self.assertTrue(self.item(older, "C4.3").merged_note)
        self.assertTrue(self.item(older, "C1.3").conditional)
        line = self.trail(older, "scope_applied")
        self.assertEqual(len(line), 1)
        self.assertIn("C4.3", line.summary)

    def test_rescoping_keeps_every_task_holding_work(self):
        older = self.make_engagement(complexity="complex", scope_version=SCOPE_LEGACY)
        self.assertLessEqual({"S2.1", "S2.2", "C4.3", "C5.8"}, self.active(older))
        self.work_on(older, "S2.1")
        self.work_on(older, "C5.8")
        older.with_user(self.partner).action_rescope()
        active = self.active(older)
        self.assertLessEqual({"S2.1", "C5.8"}, active)
        self.assertFalse({"S2.2", "C4.3"} & active)
        self.assertIn("Kept, holding work: C5.8, S2.1", self.trail(older, "scope_applied").summary)
        self.assertTrue(self.item(older, "C5.8").merged_note)

    def test_an_archived_file_is_not_rescoped(self):
        older = self.make_engagement(complexity="non_complex", scope_version=SCOPE_LEGACY)
        older.sudo().write({"phase": "archived", "archived_at": "2026-01-01 00:00:00"})
        self.assertCode("archived", older.with_user(self.partner).action_rescope)
        self.assertEqual(older.sudo().scope_version, SCOPE_LEGACY)

    def test_the_scope_is_written_by_its_method_only(self):
        engagement = self.make_engagement()
        self.assertCode("forbidden", engagement.with_user(self.partner).write, {"scope_version": SCOPE_LEGACY})
        made = self.Engagement.with_user(self.partner).create({
            "client_id": self.client.id, "fiscal_year": 2030, "period_end": "2030-12-31",
            "engagement_partner_id": self.partner.id, "scope_version": SCOPE_LEGACY,
        })
        self.assertEqual(made.sudo().scope_version, SCOPE_CURRENT)
