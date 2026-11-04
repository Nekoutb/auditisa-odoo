from odoo.tests import tagged

from odoo.addons.ea_audit_core.services.errors import AuditRuleError

from ..services import paper_for, required_keys
from .common import PaperCase


@tagged("post_install", "-at_install")
class TestPaperIncomplete(PaperCase):
    def test_refuses_to_sign_an_unanswered_paper_naming_the_part(self):
        # documents.test paper-incomplete
        self.assertCode("paper-incomplete", self.sign, self.senior, self.engagement, "P3.1", "preparer")
        first = required_keys(paper_for("P3.1"))[0]
        self.save(self.senior, "P3.1", {first: "Done."})
        with self.assertRaises(AuditRuleError) as caught:
            self.sign(self.senior, self.engagement, "P3.1", "preparer")
        self.assertEqual(caught.exception.code, "paper-incomplete")
        message = caught.exception.args[0]
        self.assertIn("Part B", message)
        self.assertIn("Conclusion", message)
        self.assertTrue(message.endswith("[paper-incomplete]"))

    def test_a_no_or_an_na_nobody_explained_stops_the_signature(self):
        answers = self.full_answers("P3.1")
        factor = next(k for k in answers if k.startswith("q_"))
        self.save(self.senior, "P3.1", {**answers, factor: "no"})
        self.assertCode("paper-incomplete", self.sign, self.senior, self.engagement, "P3.1", "preparer")
        self.save(self.senior, "P3.1", {factor: "na"})
        self.assertCode("paper-incomplete", self.sign, self.senior, self.engagement, "P3.1", "preparer")
        self.save(self.senior, "P3.1", {"%s_x" % factor: "No such transactions."})
        self.assertEqual(self.sign(self.senior, self.engagement, "P3.1", "preparer"), "preparer")

    def test_exempt_papers_sign_without_the_questionnaire(self):
        self.outputs_exist()
        self.assertEqual(self.sign(self.staff, self.engagement, "E4.1", "preparer"), "preparer")

    def test_papers_with_a_board_refuse_until_the_tools_addon_reads_it(self):
        for code, refusal in (("S1.2", "wcgw-missing"), ("S1.3", "walkthrough-incomplete")):
            self.assertCode(refusal, self.sign, self.senior, self.engagement, code, "preparer")
        self.patch(type(self.env["ea.audit.file.item"]), "_ea_tool_gap", lambda _self: None)
        self.assertEqual(self.sign(self.senior, self.engagement, "S1.2", "preparer"), "preparer")


@tagged("post_install", "-at_install")
class TestSigningOverReviewNotes(PaperCase):
    def test_preparer_first_open_notes_then_locks(self):
        # documents.test: P1.1 is reviewed by the partner in the default matrix
        self.set_phase(self.engagement, "acceptance")
        self.assertCode("preparer-first", self.sign, self.partner, self.engagement, "P1.1", "reviewer")
        self.complete(self.manager, "P1.1")
        self.assertEqual(self.sign(self.manager, self.engagement, "P1.1", "preparer"), "preparer")
        self.assertCode("role-below-task-minimum-partner", self.sign, self.manager, self.engagement, "P1.1", "reviewer")
        item = self.item(self.engagement, "P1.1")
        note = self.Note.browse(item.with_user(self.manager).add_review_note("Please tighten the conclusion."))
        self.assertCode("open-notes", self.sign, self.partner, self.engagement, "P1.1", "reviewer")
        note.with_user(self.manager).clear("Conclusion expanded.")
        self.assertEqual(self.sign(self.partner, self.engagement, "P1.1", "reviewer"), "partner")
        self.assertEqual(item.state, "signed")
        self.assertEqual(self.paper("P1.1").state, "signed")

    def test_the_hash_and_the_text_are_stored(self):
        paper = self.signed_paper()
        row = self.active()[0]
        self.assertEqual(row.content_hash, paper._content_hash())
        self.assertEqual(row.content_scheme, 2)
        self.assertEqual(row.definition_hash, self.env["ea.audit.paper.def"]._ea_current("P3.1").definition_hash)
        self.assertEqual(row.version_no, paper.answer_version)


@tagged("post_install", "-at_install")
class TestVoiding(PaperCase):
    def test_an_edit_after_p_and_r_voids_both_and_returns_the_paper_to_draft(self):
        # uat2 B10
        paper = self.signed_paper()
        self.assertEqual(paper.state, "signed")
        result = self.save(self.staff, "P3.1", {"key_findings": "A late finding"})
        self.assertEqual(sorted(result["voided"]), ["preparer", "reviewer"])
        self.assertFalse(self.active())
        self.assertEqual(paper.state, "draft")
        self.assertEqual(paper.file_item_id.state, "in_progress")
        voided = paper.signoff_ids.filtered("voided_at")
        self.assertEqual(len(voided), 2)
        self.assertIn("contenu de la feuille modifié", voided[0].void_reason)
        self.assertEqual(voided[0].invalidated_reason, voided[0].void_reason)
        # the row stays: history is never rewritten, and it can be signed again
        self.assertEqual(self.sign(self.senior, self.engagement, "P3.1", "preparer"), "preparer")

    def test_the_trail_and_the_signers_are_told(self):
        self.signed_paper()
        before = self.engagement.sudo().message_ids.mapped("body")
        self.save(self.staff, "P3.1", {"key_findings": "A late finding"})
        new = [b for b in self.engagement.sudo().message_ids.mapped("body") if b not in before]
        self.assertTrue(any("signoff_invalidated" in b for b in new))
        activities = self.paper("P3.1").activity_ids
        self.assertEqual(activities.user_id, self.senior | self.manager)  # staff made the change

    def test_a_save_that_changes_nothing_voids_nothing(self):
        self.signed_paper()
        self.save(self.staff, "P3.1", self.full_answers("P3.1"))
        self.assertEqual(len(self.active()), 2)

    def test_adding_a_blank_key_voids_nothing(self):
        # Q4: the history rule calls that no change, and so does the hash
        self.signed_paper()
        self.save(self.staff, "P3.1", {"key_findings": ""})
        self.save(self.staff, "P3.1", {"key_findings": "   "})
        self.assertEqual(len(self.active()), 2)

    def test_a_changed_wording_does_not_void_and_the_text_stays_readable(self):
        # Q1
        self.signed_paper()
        Def = self.env["ea.audit.paper.def"]
        old = Def._ea_current("P3.1")
        Def._ea_load_one("P3.1", dict(old.definition, ownsEn="a new wording"))
        self.save(self.staff, "P3.1", self.full_answers("P3.1"))
        rows = self.active()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].definition_hash, old.definition_hash)
        chips = self.paper("P3.1").with_user(self.senior).get_payload()["signing"]["chips"]
        self.assertTrue(chips[0]["definition_changed"])

    def test_a_null_hash_and_a_legacy_scheme_are_never_voided(self):
        # Q3: a migrated signature whose legacy hash Odoo cannot recompute
        self.signed_paper()
        preparer, reviewer = self.active().sorted("role")
        preparer.sudo().write({"content_hash": False})
        reviewer.sudo().write({"content_scheme": 1})
        self.save(self.staff, "P3.1", {"key_findings": "A late finding"})
        self.assertEqual(len(self.active()), 2)

    def test_a_voided_review_clears_the_conclusions_review(self):
        # uat3 B05 of run 3
        self.outputs_exist()
        item = self.item(self.engagement, "E4.1")
        item.with_user(self.staff).save_section_conclusion("Concluded.", False)
        item.with_user(self.senior).review_section_conclusion()
        self.sign(self.staff, self.engagement, "E4.1", "preparer")
        self.sign(self.senior, self.engagement, "E4.1", "reviewer")
        self.save(self.staff, "E4.1", {"key_findings": "Late."})
        self.assertFalse(self.Conclusion.sudo().search([("file_item_id", "=", item.id)]).reviewed_by_id)
        self.assertFalse(item._ea_paper()._ea_active_signoffs())


@tagged("post_install", "-at_install")
class TestChips(PaperCase):
    def chips(self, user, code="P3.1"):
        payload = self.paper(code).with_user(user).get_payload()
        return {chip["role"]: chip for chip in payload["signing"]["chips"]}

    def test_grey_with_the_reason_and_nothing_is_written(self):
        chips = self.chips(self.senior)
        self.assertEqual(chips["preparer"]["code"], "paper-incomplete")
        self.assertIn("Part A", chips["preparer"]["reason"])
        self.assertFalse(chips["preparer"]["reason"].endswith("]"))
        self.assertEqual(chips["reviewer"]["code"], "preparer-first")
        below = self.chips(self.staff)
        self.assertEqual(below["preparer"]["code"], "role-below-task-minimum-senior")
        self.assertEqual(below["reviewer"]["code"], "requires-senior")
        self.assertFalse(self.paper("P3.1").signoff_ids)

    def test_follows_the_chain_through_a_sign_off(self):
        self.complete(self.senior, "P3.1")
        self.assertEqual(self.chips(self.senior)["preparer"]["state"], "open")
        self.assertFalse(self.paper("P3.1").signoff_ids)
        self.sign(self.senior, self.engagement, "P3.1", "preparer")
        chips = self.chips(self.manager)
        self.assertEqual(chips["preparer"]["state"], "signed")
        self.assertEqual(chips["preparer"]["by"], self.senior.name)
        self.assertEqual(chips["reviewer"]["state"], "open")

    def test_the_preparer_is_told_why_they_cannot_review(self):
        self.complete(self.manager, "P3.1")
        self.sign(self.manager, self.engagement, "P3.1", "preparer")
        self.assertEqual(self.chips(self.manager)["reviewer"]["code"], "self-review")

    def test_tool_fed_chips_name_the_missing_output(self):
        self.assertEqual(self.chips(self.staff, "E4.1")["preparer"]["code"], "tool-output-missing-tb")

    def test_partner_chip_only_where_the_rule_wants_one(self):
        self.assertNotIn("partner", self.chips(self.staff))
        self.assertIn("partner", self.chips(self.staff, "P1.1"))

    def test_a_refused_payload_for_an_outsider(self):
        self.assertCode("not-on-this-engagement", self.paper("P3.1").with_user(self.outsider).get_payload)


@tagged("post_install", "-at_install")
class TestAcceptanceGateReadsThePaper(PaperCase):
    def test_form_state_follows_the_paper(self):
        engagement = self.engagement.sudo()
        self.assertEqual(
            engagement._ea_p11_form_state(), {"complete": False, "concluded_accept": False, "checks_passed": False},
        )
        answers = self.full_answers("P1.1")
        self.save(self.staff, "P1.1", answers)
        self.assertEqual(
            engagement._ea_p11_form_state(), {"complete": True, "concluded_accept": True, "checks_passed": True},
        )
        # any No in Part B precludes a Low rating, and the partner decides
        factor = next(k for k in answers if k.startswith("q_"))
        self.save(self.staff, "P1.1", {factor: "no", "%s_x" % factor: "Weighed.", "rating": "low"})
        state = engagement._ea_p11_form_state()
        self.assertTrue(state["complete"])
        self.assertFalse(state["checks_passed"])
