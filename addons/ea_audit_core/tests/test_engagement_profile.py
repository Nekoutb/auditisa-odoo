"""The engagement profile questionnaire on a real file (owner's rulings of 2026-11-15)."""
import importlib.util
import os
from datetime import date

from odoo.tests import tagged

from .common import EaAuditCase

PLAIN = {
    "q1_listed": "no", "q2_pie": "none", "q3_controls_law": "no", "q4_group": "standalone",
    "q5_activities": "one", "q6_sites": "one", "q7_major_change": "no",
    **{"q8_%d" % n: "low" for n in range(1, 9)},
    "q9_specialists": "none", "q10_regulator": "no",
    "q11_fraud": "no",
    "q12_owners_known": "yes", "q13_automated": "no", "q14_keeper": "entity",
    "q15_monitoring": "no", "q15_eqr": "no", "q16_risks": "no", "q17_going_concern": "no",
    "q18_related_parties": "no", "q19_approach": "substantive", "q20_first_year": "no",
}


@tagged("post_install", "-at_install")
class TestEngagementProfile(EaAuditCase):
    def open_new(self, user=None, **vals):
        """The creation screen, as the owner approved it: no profiling, then the questionnaire."""
        user = user or self.partner
        wizard = self.env["ea.audit.engagement.create.wizard"].with_user(user).create({
            "client_id": self.client.id, "name": "Statutory audit 2026", "nature": "statutory_audit",
            "fiscal_year": 2026, "period_start": date(2026, 1, 1), "period_end": date(2026, 12, 31),
            "engagement_partner_id": self.partner.id, **vals,
        })
        action = wizard.action_create()
        engagement = self.Engagement.sudo().search([("name", "=", "Statutory audit 2026")], order="id desc", limit=1)
        return engagement, action

    def profile(self, engagement, user=None):
        return engagement.sudo()._ea_profile().with_user(user or self.partner)

    def active_codes(self, engagement):
        return set(engagement.sudo().file_item_ids.filtered(lambda i: not i.conditional).mapped("code"))

    def conclude(self, engagement, **changes):
        profile = self.profile(engagement)
        profile.write({**PLAIN, **changes})
        profile.action_conclude()
        return profile

    # ---------------------------------------------------------------- creation

    def test_creation_makes_no_task_and_opens_the_questionnaire(self):
        engagement, action = self.open_new()
        self.assertEqual(action["res_model"], "ea.audit.engagement.profile")
        self.assertEqual(action["res_id"], engagement._ea_profile().id)
        self.assertEqual((action["type"], action["tag"]), ("ir.actions.client", "ea_audit_core.profile"))
        self.assertEqual(action["params"]["profile_id"], engagement._ea_profile().id)
        self.assertFalse(engagement.file_item_ids)
        self.assertFalse(engagement.complexity)
        self.assertEqual((engagement.nature, engagement.nature_kind), ("statutory_audit", "statutory"))
        self.assertEqual(engagement.period_start, date(2026, 1, 1))
        self.assertEqual(engagement.duration_months, 12)
        self.assertEqual(engagement.report_language, self.Engagement._ea_firm_language())
        self.assertTrue(engagement.profile_pending)
        self.assertEqual(engagement.profile_state, "draft")

    def test_a_period_ending_before_it_starts_is_refused(self):
        wizard = self.env["ea.audit.engagement.create.wizard"].with_user(self.partner).create({
            "client_id": self.client.id, "fiscal_year": 2026, "period_start": date(2027, 1, 1),
            "period_end": date(2026, 12, 31), "engagement_partner_id": self.partner.id,
        })
        self.assertCode("period-order", wizard.action_create)

    def test_a_creator_off_the_team_is_told_and_the_partner_finds_the_banner(self):
        # Owner ruling 2026-11-15: the firm administrator looks at every file but changes none.
        engagement, action = self.open_new(user=self.admin)
        self.assertEqual((action["type"], action.get("res_id")), ("ir.actions.act_window", engagement.id))
        self.assertTrue(engagement.with_user(self.partner).profile_pending)

    # ---------------------------------------------------------------- save for later

    def test_save_for_later_keeps_the_answers_and_makes_no_task(self):
        engagement, _action = self.open_new()
        profile = self.profile(engagement)
        profile.write({"q1_listed": "no", "q2_pie": "none"})
        back = profile.action_save_for_later()
        self.assertTrue(back)
        self.assertEqual(profile.state, "draft")
        self.assertFalse(engagement.file_item_ids)
        self.assertTrue(engagement.profile_pending)
        self.assertIn("Q3", profile.missing_text)
        self.assertNotIn("Q1,", profile.missing_text)

    def test_concluding_with_a_question_open_is_refused(self):
        engagement, _action = self.open_new()
        profile = self.profile(engagement)
        profile.write({k: v for k, v in PLAIN.items() if k != "q17_going_concern"})
        self.assertCode("profile-incomplete", profile.action_conclude)
        self.assertFalse(engagement.file_item_ids)

    # ---------------------------------------------------------------- the three levels

    def test_very_simple_gets_the_core_tasks(self):
        engagement, _action = self.open_new()
        profile = self.conclude(engagement)
        self.assertEqual((profile.state, profile.level, engagement.complexity), ("concluded", "very_simple", "very_simple"))
        core = self.env["ea.audit.task.template"].search([("tier", "=", "core"), ("conditional", "=", False)])
        self.assertEqual(self.active_codes(engagement), set(core.mapped("code")))
        self.assertFalse(engagement.profile_pending)
        self.assertIn("ISA for LCE", profile.lce_note)
        self.assertIn("may be documented", profile.lce_note)

    def test_non_complex_says_why_it_is_not_very_simple(self):
        engagement, _action = self.open_new()
        profile = self.conclude(engagement, q11_fraud="yes", q17_going_concern="yes")
        self.assertEqual(engagement.complexity, "non_complex")
        self.assertIn("Q11 known or suspected fraud", profile.reasons_text)
        self.assertLessEqual({"P5.1", "E3.1", "E6.1"}, self.active_codes(engagement))
        self.assertIn("Q17", profile.reasons_text)
        self.assertNotIn("extended", engagement.file_item_ids.template_id.mapped("tier"))

    def test_complex_lists_every_reason(self):
        engagement, _action = self.open_new()
        profile = self.conclude(engagement, q2_pie="bank", q8_3="high")
        self.assertEqual(engagement.complexity, "complex")
        self.assertEqual(profile.conclusion_title, "Complex because:")
        self.assertIn("Q2 public-interest entity: Bank", profile.reasons_text)
        self.assertIn("Q8 IT point 3 high", profile.reasons_text)
        self.assertFalse(profile.lce_note)
        self.assertEqual(
            len(engagement.file_item_ids), self.env["ea.audit.task.template"].search_count([]),
        )

    def test_a_period_before_the_isa_for_lce_says_so(self):
        engagement, _action = self.open_new(period_start=date(2025, 1, 1), period_end=date(2025, 12, 31), fiscal_year=2025)
        profile = self.conclude(engagement)
        self.assertIn("begins earlier", profile.lce_note)

    # ---------------------------------------------------------------- nature of the service

    def test_a_non_statutory_audit_leaves_out_the_ohada_statutory_tasks(self):
        statutory_only = {"C5.%d" % n for n in range(2, 11)}
        engagement, _action = self.open_new()
        self.conclude(engagement, q2_pie="bank")
        self.assertLessEqual(statutory_only - {"C5.7"}, self.active_codes(engagement))
        self.Engagement.sudo().search([("name", "=", "Statutory audit 2026")]).write({"name": "done"})
        other, _action = self.open_new(nature="contractual_audit")
        self.conclude(other, q2_pie="bank")
        self.assertEqual(other.nature_kind, "non_statutory")
        self.assertFalse(statutory_only & self.active_codes(other))

    def test_an_older_file_s_nature_reads_in_the_two_words_and_keeps_its_value(self):
        kinds = {}
        for year, nature in enumerate(("statutory_audit", "contractual_audit", "limited_review",
                                       "commissariat_apports", "agreed_procedures", "other", False), start=2010):
            old = self.make_engagement(year, nature=nature).sudo()
            kinds[nature] = (old.nature, old.nature_kind)
        self.assertEqual(kinds, {
            "statutory_audit": ("statutory_audit", "statutory"),
            "contractual_audit": ("contractual_audit", "non_statutory"),
            "limited_review": ("limited_review", "non_statutory"),
            "commissariat_apports": ("commissariat_apports", "statutory"),
            "agreed_procedures": ("agreed_procedures", "non_statutory"),
            "other": ("other", "non_statutory"),
            False: (False, "statutory"),
        })

    # ---------------------------------------------------------------- tasks from the answers

    def test_answers_switch_their_conditional_tasks_on(self):
        engagement, _action = self.open_new()
        self.conclude(
            engagement, q20_first_year="yes", q8_4="high", q9_specialists="tax", q14_keeper="accountant",
            q14_rely_report="no", q19_approach="other", q19_internal_audit=True,
        )
        codes = self.active_codes(engagement)
        self.assertLessEqual({"P1.2", "P4.3", "S5.1", "S5.2", "S5.3"}, codes)
        self.assertNotIn("P4.2", codes)
        self.assertTrue(engagement.first_year)

    def test_a_quality_review_brings_c42_to_a_non_complex_file(self):
        engagement, _action = self.open_new()
        self.conclude(engagement, q15_eqr="yes")
        self.assertEqual(engagement.complexity, "non_complex")
        self.assertIn("C4.2", self.active_codes(engagement))

    def test_s61_saying_no_does_not_switch_off_what_the_profile_switched_on(self):
        engagement, _action = self.open_new()
        self.conclude(engagement, q8_1="high")
        engagement._ea_set_task_active("P4.3", False)
        self.assertIn("P4.3", self.active_codes(engagement))

    # ---------------------------------------------------------------- answers changed later

    def test_a_changed_answer_only_adds_tasks(self):
        engagement, _action = self.open_new()
        profile = self.conclude(engagement, q2_pie="bank", q20_first_year="yes")
        before = set(engagement.file_item_ids.ids)
        active_before = self.active_codes(engagement)
        profile.write({"q2_pie": "none", "q20_first_year": "no"})
        self.assertEqual(profile.level, "very_simple")
        self.assertEqual(engagement.complexity, "very_simple")
        self.assertLessEqual(before, set(engagement.file_item_ids.ids))
        self.assertLessEqual(active_before, self.active_codes(engagement))

    def test_a_change_upwards_adds_the_new_level_s_tasks(self):
        engagement, _action = self.open_new()
        profile = self.conclude(engagement)
        count = len(engagement.file_item_ids)
        profile.write({"q16_risks": "yes"})
        self.assertEqual(engagement.complexity, "non_complex")
        self.assertGreater(len(engagement.file_item_ids), count)

    def test_a_concluded_profile_cannot_lose_an_answer(self):
        engagement, _action = self.open_new()
        profile = self.conclude(engagement)
        self.assertCode("profile-incomplete", profile.write, {"q5_activities": False})

    def test_the_level_cannot_be_set_by_hand(self):
        engagement, _action = self.open_new()
        profile = self.conclude(engagement)
        self.assertCode("forbidden", profile.write, {"level": "complex"})
        self.assertCode("forbidden", engagement.with_user(self.partner).write, {"complexity": "complex"})

    # ---------------------------------------------------------------- who answers

    def test_only_the_team_answers_and_the_quality_reviewer_only_reads(self):
        engagement, _action = self.open_new()
        self.seat(engagement, self.eqr, "eqr_reviewer")
        profile = engagement.sudo()._ea_profile()
        self.assertEqual(self.attempt(profile.with_user(self.eqr).write, {"q1_listed": "no"}), "eqr-read-only")
        with self.assertRaises(Exception), self.cr.savepoint():
            profile.with_user(self.outsider).write({"q1_listed": "no"})

    # ---------------------------------------------------------------- files opened before

    def test_an_older_file_keeps_its_level_and_tasks_and_is_not_held_up(self):
        old = self.make_engagement(2024, complexity="non_complex", first_year=True)
        items = set(old.sudo().file_item_ids.ids)
        self.assertTrue(items)
        self.assertEqual(old.with_user(self.partner).profile_state, "none")
        self.assertFalse(old.with_user(self.partner).profile_pending)
        action = old.with_user(self.partner).action_open_profile()
        self.assertEqual(action["res_model"], "ea.audit.engagement.profile")
        self.assertFalse(old.with_user(self.partner).profile_pending)
        self.assertEqual((old.sudo().complexity, old.sudo().first_year), ("non_complex", True))
        self.assertEqual(set(old.sudo().file_item_ids.ids), items)

    def test_an_archived_older_file_gets_no_questionnaire(self):
        old = self.make_engagement(2023)
        old.sudo().archived_at = "2026-01-01 00:00:00"
        self.assertFalse(old.with_user(self.partner).profile_pending)
        self.assertCode("archived", old.with_user(self.partner).action_open_profile)

    def test_the_migration_adds_its_columns_without_touching_a_row(self):
        old = self.make_engagement(2022, complexity="very_simple")
        old.sudo().archived_at = "2026-01-01 00:00:00"
        self.env.flush_all()
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations", "19.0.1.1.0", "pre-migrate.py")
        spec = importlib.util.spec_from_file_location("ea_core_profile_premigrate", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.cr.execute("SELECT write_date FROM ea_audit_engagement WHERE id = %s", [old.id])
        written = self.cr.fetchone()[0]
        module.migrate(self.cr, "19.0.1.0.0")
        module.migrate(self.cr, "19.0.1.0.0")
        self.cr.execute("SELECT write_date, complexity, period_start FROM ea_audit_engagement WHERE id = %s", [old.id])
        self.assertEqual(self.cr.fetchone(), (written, "very_simple", None))
        self.cr.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'ea_audit_engagement' AND column_name = 'nature_text'")
        self.assertFalse(self.cr.fetchone())

    # ---------------------------------------------------------------- next year

    def test_rollforward_starts_from_last_year_s_answers_as_a_recurring_client(self):
        engagement, _action = self.open_new()
        self.conclude(engagement, q20_first_year="yes", q16_risks="yes")
        target = engagement.with_user(self.partner).rollforward(2027).sudo()
        profile = target._ea_profile()
        self.assertEqual((profile.state, profile.q20_first_year, profile.q16_risks), ("draft", "no", "yes"))
        self.assertFalse(target.file_item_ids)
        self.assertTrue(target.profile_pending)
        self.assertEqual(target.period_start, date(2027, 1, 1))
        self.assertEqual(target.nature, "statutory_audit")

    # ---------------------------------------------------------------- the screen (mock-up of 2026-11-15)

    def screen(self, engagement, user=None):
        return self.profile(engagement, user).ea_profile_screen()

    def test_the_screen_has_seven_sections_and_twenty_questions(self):
        engagement, _action = self.open_new()
        screen = self.screen(engagement)
        self.assertEqual(
            [s["title"] for s in screen["sections"]],
            ["The entity", "The business", "IT", "Specialists, people and ownership",
             "How the evidence will be obtained", "Risk", "Approach and history"],
        )
        numbers = [q["number"] for s in screen["sections"] for q in s["questions"]]
        self.assertEqual(numbers, ["Q%d" % n for n in range(1, 21)])
        self.assertEqual(screen["progress"], {"answered": 0, "total": 20})
        it = screen["sections"][2]["questions"][0]
        self.assertEqual(len(it["parts"]), 8)
        self.assertEqual([o["value"] for o in it["parts"][0]["options"]], ["low", "high"])
        self.assertTrue(all(q["help"] for s in screen["sections"] for q in s["questions"]))
        self.assertFalse(screen["readonly"])

    def test_nothing_answered_leaves_the_level_open_and_conclude_greyed(self):
        engagement, _action = self.open_new()
        screen = self.screen(engagement)
        self.assertFalse(screen["panel"]["level"])
        self.assertTrue(screen["panel"]["provisional"])
        self.assertEqual(screen["panel"]["level_label"], "Not settled yet")
        self.assertIn("Very simple is still possible", screen["panel"]["intro"])
        self.assertFalse(screen["conclude"]["can"])
        self.assertEqual(screen["conclude"]["hint"], "Available once all 20 questions are answered.")

    def test_the_level_so_far_follows_each_answer(self):
        engagement, _action = self.open_new()
        profile = self.profile(engagement)
        screen = profile.ea_profile_save({"q1_listed": "no", "q2_pie": "none"})
        self.assertEqual(screen["progress"]["answered"], 2)
        self.assertFalse(screen["panel"]["level"])
        self.assertEqual(profile.q2_pie, "none")
        # Very simple ruled out, not yet settled between Non-complex and Complex
        screen = profile.ea_profile_save({"q16_risks": "yes"})
        self.assertEqual(screen["panel"]["level"], "non_complex")
        self.assertTrue(screen["panel"]["provisional"])
        self.assertIn("Q16 significant risks or complex estimates expected", screen["panel"]["reasons"])
        # Low is not a sign of complexity (owner, 2026-11-15: Low or High only)
        screen = profile.ea_profile_save({"q8_1": "low"})
        self.assertEqual(screen["panel"]["level"], "non_complex")
        screen = profile.ea_profile_save({"q8_3": "high"})
        self.assertEqual(screen["panel"]["level"], "complex")
        self.assertEqual(screen["panel"]["reasons"], ["Q8 IT point 3 high"])
        self.assertIn("P4.3", [t["code"] for t in screen["panel"]["tasks"]])
        self.assertEqual(profile.state, "draft")
        self.assertFalse(engagement.file_item_ids)

    def test_conclude_is_refused_until_all_twenty_are_answered(self):
        engagement, _action = self.open_new()
        profile = self.profile(engagement)
        screen = profile.ea_profile_save({k: v for k, v in PLAIN.items() if k != "q20_first_year"})
        self.assertEqual(screen["progress"]["answered"], 19)
        self.assertFalse(screen["conclude"]["can"])
        self.assertIn("1 question", screen["panel"]["still_open"])
        self.assertCode("profile-incomplete", profile.ea_profile_conclude)
        self.assertFalse(engagement.file_item_ids)
        screen = profile.ea_profile_save({"q20_first_year": "no"})
        self.assertTrue(screen["conclude"]["can"])
        self.assertFalse(screen["panel"]["provisional"])
        self.assertEqual(screen["panel"]["level"], "very_simple")
        screen = profile.ea_profile_conclude()
        self.assertEqual((screen["state"], profile.level), ("concluded", "very_simple"))
        self.assertFalse(screen["conclude"]["show"])
        self.assertTrue(screen["concluded_note"])
        self.assertEqual(screen["panel"]["task_count"], len(self.active_codes(engagement)))

    def test_a_sub_question_shows_only_in_its_case(self):
        engagement, _action = self.open_new()
        profile = self.profile(engagement)

        def visible(screen, field):
            return next(
                p["visible"] for s in screen["sections"] for q in s["questions"] for p in q["parts"] if p["field"] == field
            )

        screen = profile.ea_profile_save({"q4_group": "standalone", "q14_keeper": "entity", "q19_approach": "substantive"})
        self.assertFalse(visible(screen, "q4_consolidates"))
        self.assertFalse(visible(screen, "q14_rely_report"))
        self.assertFalse(visible(screen, "q19_controls"))
        screen = profile.ea_profile_save({"q4_group": "parent", "q14_keeper": "payroll", "q19_approach": "other"})
        self.assertTrue(visible(screen, "q4_consolidates"))
        self.assertTrue(visible(screen, "q4_other_auditors"))
        self.assertTrue(visible(screen, "q14_rely_report"))
        self.assertTrue(visible(screen, "q19_controls"))

    def test_a_concluded_profile_holds_a_change_until_its_sub_question_is_answered(self):
        engagement, _action = self.open_new()
        profile = self.conclude(engagement)
        screen = profile.ea_profile_save({"q4_group": "parent"})
        self.assertTrue(screen["held"])
        self.assertEqual(profile.q4_group, "standalone")
        self.assertEqual(screen["answers"]["q4_group"], "parent")
        screen = profile.ea_profile_save({"q4_group": "parent", "q4_consolidates": "yes", "q4_other_auditors": "no"})
        self.assertFalse(screen["held"])
        self.assertEqual((profile.q4_group, profile.level), ("parent", "non_complex"))
        self.assertIn("P2.3", self.active_codes(engagement))

    def test_the_screen_saves_answers_only(self):
        engagement, _action = self.open_new()
        profile = self.profile(engagement)
        self.assertCode("forbidden", profile.ea_profile_save, {"level": "complex"})
        self.assertCode("forbidden", profile.ea_profile_save, {"q1_listed": "maybe"})

    def test_the_quality_reviewer_and_an_archived_file_read_only(self):
        engagement, _action = self.open_new()
        self.seat(engagement, self.eqr, "eqr_reviewer")
        screen = self.screen(engagement, self.eqr)
        self.assertTrue(screen["readonly"])
        self.assertIn("quality reviewer", screen["readonly_note"])
        self.assertCode("eqr-read-only", self.profile(engagement, self.eqr).ea_profile_save, {"q1_listed": "no"})
        engagement.sudo().archived_at = "2026-01-01 00:00:00"
        screen = self.screen(engagement)
        self.assertTrue(screen["readonly"])
        self.assertIn("archived", screen["readonly_note"])
        self.assertFalse(screen["conclude"]["can"])
        self.assertCode("archived", self.profile(engagement).ea_profile_save, {"q1_listed": "no"})
