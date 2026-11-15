from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from ..services import EQR_C42_KEYS, base_digests, paper_for, paper_keys, required_keys
from .common import PaperCase


@tagged("post_install", "-at_install")
class TestDefinitions(PaperCase):
    def test_every_task_code_has_one_current_definition(self):
        Def = self.env["ea.audit.paper.def"].sudo()
        self.assertEqual(Def.search_count([("is_current", "=", True), ("is_default", "=", False)]), 94)
        self.assertEqual(Def.search_count([("is_current", "=", True)]), 118)

    def test_nobody_edits_a_definition(self):
        row = self.env["ea.audit.paper.def"]._ea_current("P1.1")
        for user in (self.admin, self.partner, self.staff):
            with self.assertRaises(AccessError):
                row.with_user(user).write({"is_current": False})
            with self.assertRaises(AccessError):
                row.with_user(user).unlink()

    def test_a_changed_text_adds_a_row_and_retires_the_old_one(self):
        Def = self.env["ea.audit.paper.def"]
        old = Def._ea_current("P3.1")
        changed = dict(old.definition, ownsEn="a new wording")
        new = Def._ea_load_one("P3.1", changed)
        self.assertNotEqual(new, old)
        self.assertFalse(old.is_current)
        self.assertEqual(Def._ea_current("P3.1"), new)
        # the same load again changes nothing, and a text coming back reuses its row
        self.assertEqual(Def._ea_load_one("P3.1", changed), new)
        self.assertEqual(Def._ea_load_one("P3.1", old.definition), old)
        self.assertTrue(old.is_current)

    def test_shared_texts_load_under_each_code(self):
        rows = self.env["ea.audit.paper.def"].sudo().search([("is_current", "=", True), ("is_default", "=", True)])
        self.assertGreater(len(rows), len(set(rows.mapped("definition_hash"))))

    def test_every_task_has_its_paper_from_the_start(self):
        items = self.engagement.sudo().file_item_ids
        self.assertEqual(len(items.paper_ids), len(items))


@tagged("post_install", "-at_install")
class TestAllowList(PaperCase):
    def test_a_key_the_paper_does_not_hold_is_dropped(self):
        result = self.save(self.staff, "P3.1", {"key_findings": "Noted.", "made_up": "x", "password": "y"})
        self.assertEqual(result["written"], ["key_findings"])
        self.assertEqual(self.stored("P3.1"), {"key_findings": "Noted."})

    def test_form_restricted_answers_save_on_their_form(self):
        # the defect of paperFor(code) without a form: on an SA, C5.3 answers were
        # skipped while paperMissing still demanded them
        key = next(k for k in paper_keys(paper_for("C5.3", "current", "SA")) if k not in paper_keys(paper_for("C5.3")))
        self.save(self.manager, "C5.3", {key: "Done."})
        self.assertEqual(self.stored("C5.3")[key], "Done.")

    def test_an_sa_file_can_complete_c53(self):
        self.complete(self.staff, "C5.3")
        self.assertEqual(self.paper("C5.3").with_user(self.staff).get_payload()["missing"], [])


@tagged("post_install", "-at_install")
class TestWhoMaySave(PaperCase):
    def test_refusals_of_the_guards(self):
        self.assertCode("not-on-this-engagement", self.save, self.outsider, "P3.1", {"key_findings": "x"})
        self.assertCode("not-on-this-engagement", self.save, self.admin, "P3.1", {"key_findings": "x"})
        self.seat(self.engagement, self.reader, "staff")
        self.assertCode("read-only-role", self.save, self.reader, "P3.1", {"key_findings": "x"})
        self.engagement.sudo().phase = "archived"
        self.assertCode("archived", self.save, self.staff, "P3.1", {"key_findings": "x"})

    def test_the_team_role_eqr_is_read_only_on_the_teams_work(self):
        # uat3 B03
        self.seat(self.engagement, self.eqr, "eqr_reviewer")
        self.assertCode("eqr-read-only", self.save, self.eqr, "P3.1", {"key_findings": "x"})
        other = self.make_engagement()
        self.seat(other, self.senior, "eqr_reviewer")
        self.assertCode("eqr-read-only", self.save, self.senior, "P3.1", {"key_findings": "x"}, engagement=other)

    def test_each_side_keeps_to_its_part_of_c42(self):
        # uat3 B02
        engagement = self.make_engagement()
        self.seat(engagement, self.manager, "manager")
        self.seat(engagement, self.senior, "eqr_reviewer")
        engagement.sudo()._ea_ensure_task("C4.2")
        self.set_phase(engagement, "execution")
        required = required_keys(paper_for("C4.2"))
        values = {k: "yes" if k[:2] in ("q_", "c_") else "Done, see file." for k in required}
        team = {k: v for k, v in values.items() if k not in EQR_C42_KEYS}
        reviewer = {k: v for k, v in values.items() if k in EQR_C42_KEYS}
        self.assertCode("eqr-own-paper", self.save, self.manager, "C4.2", {"q_complete": "yes"}, engagement=engagement)
        self.save(self.manager, "C4.2", team, engagement=engagement)
        self.assertCode("eqr-read-only", self.save, self.senior, "C4.2", {"p_scope": "Provided."}, engagement=engagement)
        self.save(self.senior, "C4.2", reviewer, engagement=engagement)
        # a field posted back unchanged by whoever does not own it is simply not written
        self.save(self.manager, "C4.2", {**team, **reviewer}, engagement=engagement)
        self.assertEqual(self.stored("C4.2", engagement)["q_complete"], "yes")
        locked = self.paper("C4.2", engagement).with_user(self.manager)._ea_locked_keys()
        self.assertIn("q_complete", locked)
        self.assertNotIn("p_scope", locked)

    def test_the_team_writes_all_of_c42_where_no_review_is_required(self):
        self.engagement.sudo()._ea_ensure_task("C4.2")
        self.save(self.manager, "C4.2", {"q_complete": "yes"})
        self.assertEqual(self.stored("C4.2")["q_complete"], "yes")


@tagged("post_install", "-at_install")
class TestConcurrentEdits(PaperCase):
    def _key_pair(self):
        keys = sorted(k for k in paper_keys(paper_for("P3.1")) if k.startswith("p_") and not k.endswith(("_na", "_x")))
        self.assertGreaterEqual(len(keys), 2)
        return keys[:2]

    def test_refuses_the_second_of_two_saves_from_one_version(self):
        # uat2 B05
        base = self.paper("C5.2").answer_version
        self.save(self.manager, "C5.2", {"key_findings": "Manager's findings"}, base)
        self.assertCode("stale-edit", self.save, self.staff, "C5.2", {"key_findings": ""}, base)
        self.assertEqual(self.stored("C5.2")["key_findings"], "Manager's findings")

    def test_accepts_a_save_from_the_current_version(self):
        self.save(self.manager, "C5.2", {"key_findings": "One"})
        base = self.paper("C5.2").answer_version
        self.save(self.manager, "C5.2", {"key_findings": "Two"}, base)
        self.assertGreater(self.paper("C5.2").answer_version, base)

    def test_saves_disjoint_edits_and_holds_back_a_field_both_changed(self):
        # uat3 firm.perf-concurrent
        k1, k2 = self._key_pair()
        base = self.paper("P3.1").answer_version
        loaded = self.stored("P3.1")
        digests = base_digests(loaded)

        def posted(**changes):
            return {**{k: loaded.get(k, "") for k in paper_keys(paper_for("P3.1"))}, **changes}

        self.save(self.manager, "P3.1", posted(key_findings="Manager findings"), base, digests)
        self.save(self.staff, "P3.1", posted(**{k1: "Staff model"}), base, digests)
        clash = self.save(self.senior, "P3.1", posted(key_findings="Senior rewrite", **{k2: "Senior structure"}), base, digests)
        self.assertEqual(clash["conflicts"], {"key_findings": {"mine": "Senior rewrite", "theirs": "Manager findings"}})
        now = self.stored("P3.1")
        self.assertEqual(now["key_findings"], "Manager findings")
        self.assertEqual(now[k1], "Staff model")
        self.assertEqual(now[k2], "Senior structure")
        # without the digests the whole-paper refusal still applies
        self.assertCode("stale-edit", self.save, self.staff, "P3.1", {k2: "x"}, base)

    def test_the_same_text_from_both_is_no_clash(self):
        base = self.paper("P3.1").answer_version
        digests = base_digests({})
        self.save(self.manager, "P3.1", {"key_findings": "Same"}, base, digests)
        result = self.save(self.staff, "P3.1", {"key_findings": "Same"}, base, digests)
        self.assertEqual(result["conflicts"], {})

    def test_crlf_is_not_a_change(self):
        self.save(self.staff, "P3.1", {"key_findings": "a\nb"})
        version = self.paper("P3.1").answer_version
        result = self.save(self.staff, "P3.1", {"key_findings": "a\r\nb"})
        self.assertEqual(result["written"], [])
        self.assertEqual(self.paper("P3.1").answer_version, version)


@tagged("post_install", "-at_install")
class TestAnswerHistory(PaperCase):
    def history(self, code, key):
        return self.paper(code).history_ids.filtered(lambda h: h.field_key == key)

    def test_records_each_change_with_old_and_new_value_and_the_writer(self):
        # f027
        self.save(self.manager, "P3.1", {"key_findings": "Family-owned SA"})
        self.save(self.manager, "P3.1", {"key_findings": "Listed SA"})
        self.save(self.manager, "P3.1", {"key_findings": "Listed SA"})  # not a change
        rows = self.history("P3.1", "key_findings").sorted("id")
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[1].before, rows[1].after, rows[1].user_id), ("Family-owned SA", "Listed SA", self.manager))
        self.assertFalse(rows[0].before)
        self.assertEqual(rows[0].after, "Family-owned SA")

    def test_records_a_cleared_answer_but_not_clearing_a_blank(self):
        self.save(self.staff, "P3.1", {"key_findings": "Text"})
        self.save(self.staff, "P3.1", {"key_findings": ""})
        self.save(self.staff, "P3.1", {"key_findings": "   "})
        rows = self.history("P3.1", "key_findings").sorted("id")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1].before, "Text")
        self.assertFalse(rows[1].after)

    def test_a_carried_forward_value_leaves_no_history(self):
        self.paper("P3.1")._ea_carry_forward_answers({"key_findings": "Rolled"})
        self.assertFalse(self.history("P3.1", "key_findings"))
        answer = self.paper("P3.1").answer_ids.filtered(lambda a: a.field_key == "key_findings")
        self.assertTrue(answer.carried_forward)
        # saving it back unchanged makes it this year's answer, still with no history row
        self.save(self.staff, "P3.1", {"key_findings": "Rolled"})
        self.assertFalse(answer.carried_forward)
        self.assertFalse(self.history("P3.1", "key_findings"))

    def test_is_for_the_engagements_team_only(self):
        self.save(self.staff, "P3.1", {"key_findings": "Text"})
        self.assertEqual(len(self.paper("P3.1").with_user(self.staff).get_answer_history()), 1)
        with self.assertRaises(AccessError):
            self.paper("P3.1").with_user(self.outsider).get_answer_history()

    def test_is_append_only_and_answers_have_one_door(self):
        self.save(self.staff, "P3.1", {"key_findings": "Text"})
        row = self.history("P3.1", "key_findings")
        answer = self.paper("P3.1").answer_ids
        self.assertCode("forbidden", row.sudo().write, {"after": "forged"})
        self.assertCode("forbidden", row.sudo().unlink)
        self.assertCode("forbidden", answer.sudo().write, {"value": "forged"})
        self.assertCode("forbidden", answer.sudo().unlink)
        self.assertCode("forbidden", self.env["ea.audit.paper.answer"].sudo().create, {
            "paper_id": self.paper("P3.1").id, "field_key": "x",
        })
        with self.assertRaises(UserError):
            answer.with_user(self.staff).write({"value": "forged"})


@tagged("post_install", "-at_install")
class TestPerCodeBehaviour(PaperCase):
    def test_c58_cannot_contradict_the_equity_monitor(self):
        # uat3 firm.stat.c5-8
        cls = type(self.env["ea.audit.paper"])
        self.patch(cls, "_ea_equity_breach", lambda _self: True)
        self.assertCode("c58-equity-contradicts", self.save, self.manager, "C5.8", {"q_above": "yes"})
        self.assertNotIn("q_above", self.stored("C5.8"))
        self.save(self.manager, "C5.8", {"q_above": "no"})
        self.patch(cls, "_ea_equity_breach", lambda _self: False)
        self.save(self.manager, "C5.8", {"q_above": "yes"})
        self.assertEqual(self.stored("C5.8")["q_above"], "yes")

    def test_e610_refuses_yes_over_unexplained_differences(self):
        self.patch(type(self.env["ea.audit.paper"]), "_ea_tieout_failed", lambda _self: True)
        self.assertCode("tieout-unexplained", self.save, self.staff, "E6.10", {"q_n_agrees": "yes"})
        self.assertCode("tieout-unexplained", self.save, self.staff, "E6.10", {"q_n_agrees": "yes", "p_tie_n": "  "})
        self.save(self.staff, "E6.10", {"p_tie_n": "Rounding, see file."})
        self.save(self.staff, "E6.10", {"q_n_agrees": "yes"})

    def test_c510_persons_follow_the_headcount_unless_chosen(self):
        self.save(self.staff, "C5.10", {"headcount": "212 salariés au 31/12"})
        self.assertEqual(self.stored("C5.10")["persons"], "ten")
        self.save(self.staff, "C5.10", {"headcount": "150", "persons": "ten"})
        self.assertEqual(self.stored("C5.10")["persons"], "five")
        # a number chosen on the same save stands
        self.save(self.staff, "C5.10", {"headcount": "300", "persons": "five"})
        self.assertEqual(self.stored("C5.10")["persons"], "ten")
        self.save(self.staff, "C5.10", {"persons": "five"})
        self.assertEqual(self.stored("C5.10")["persons"], "five")

    def test_p15_any_criterion_yes_puts_c42_on_the_file(self):
        engagement = self.make_engagement()
        self.seat(engagement, self.staff, "staff")
        item = self.item(engagement, "C4.2")
        if item:
            item.conditional = True
        self.save(self.staff, "P1.5", {"q_pie": "no"}, engagement=engagement)
        self.assertFalse(self.item(engagement, "C4.2") and not self.item(engagement, "C4.2").conditional)
        self.save(self.staff, "P1.5", {"q_pie": "yes"}, engagement=engagement)
        item = self.item(engagement, "C4.2")
        self.assertTrue(item)
        self.assertFalse(item.conditional)
        self.assertTrue(engagement.sudo()._ea_eqr_required())

    def test_p11_shows_the_profile_answers_read_only(self):
        """Owner's ruling of 2026-11-15: P1.1 no longer asks new/recurring or change of
        auditor; it shows the questionnaire's answers, which nobody can type over."""
        engagement = self.engagement.sudo()
        self.save(self.staff, "P1.1", {"rating": "moderate"})
        paper = self.env["ea.audit.paper"].sudo().search([("engagement_id", "=", engagement.id), ("code", "=", "P1.1")])
        profile = engagement._ea_profile() or self.env["ea.audit.engagement.profile"].sudo().create(
            {"engagement_id": engagement.id}
        )
        profile.q20_first_year = "yes"
        values = paper._ea_auto_values()
        self.assertIn("P1.2", values["profile_first_year"])
        self.assertEqual(values["profile_level"], "The questionnaire is not finished yet.")
        profile.q20_first_year = "no"
        self.assertEqual(paper._ea_auto_values()["profile_first_year"], "No")
        self.save(self.staff, "P1.1", {"profile_first_year": "typed over"})
        self.assertNotIn("profile_first_year", self.stored("P1.1"))

    def test_acceptance_needs_p12_only_when_it_is_on_the_file(self):
        engagement = self.engagement.sudo()
        self.assertFalse(engagement._ea_predecessor_required())
        engagement._ea_ensure_task("P1.2")
        self.assertTrue(engagement._ea_predecessor_required())
        self.item(self.engagement, "P1.2").not_applicable = True
        self.assertFalse(engagement._ea_predecessor_required())

    def test_auto_fields_are_never_saved(self):
        definition = paper_for("P6.1")
        auto = [f["key"] for s in definition.get("sections", []) if s["kind"] == "fields" for f in s["fields"] if f["kind"] == "auto"]
        self.assertTrue(auto)
        self.save(self.manager, "P6.1", {auto[0]: "typed over"})
        self.assertNotIn(auto[0], self.stored("P6.1"))
