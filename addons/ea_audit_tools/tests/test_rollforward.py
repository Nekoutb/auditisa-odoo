"""Roll forward to next year (owner's mock-up and rulings of 2026-11-16): each box of "What to carry"
on and off, last year's evidence copied with its mark and the same bytes, the archived source left
as it was, the team invited again, and nothing concluded or signed in the new file."""
import base64
import re
from datetime import date

from odoo.tests import tagged

from odoo.addons.ea_audit_core.services.rollforward_plan import ROLLFORWARD_KEYS

from .common import ToolsCase


def b64(content):
    return base64.b64encode(content).decode()


def shown(name):
    """A SCOT's document carries its SCOT's tag in its name."""
    return re.sub(r"^SCOT \d+ - ", "", name)


@tagged("post_install", "-at_install")
class TestRollforward(ToolsCase):
    def setUp(self):
        super().setUp()
        source = self.engagement.sudo()
        self.env["ea.audit.engagement.profile"].sudo().create({"engagement_id": source.id, "q20_first_year": "yes"})
        self.approve(overall_pct=2)
        # SCOT, WCGW, control (tested and concluded last year), its walkthrough note
        self.scot = self.env["ea.audit.scot"].sudo().create({"engagement_id": source.id, "name": "Ventes"})
        self.wcgw = self.env["ea.audit.wcgw"].sudo().create({
            "engagement_id": source.id, "scot_id": self.scot.id, "description": "Ventes non enregistrées",
        })
        self.control = self.env["ea.audit.scot.control"].sudo().create({
            "engagement_id": source.id, "scot_id": self.scot.id, "name": "Rapprochement", "frequency_code": "monthly",
            "reliance": "heavy", "objective": "detect", "control_type": "manual", "wcgw_ids": [(6, 0, self.wcgw.ids)],
            "selected_for_testing": True, "test_design": "Revue mensuelle", "design_eval": "effective", "implemented": "yes",
            "operating_eval": "effective", "sample_size": 2,
        })
        # a risk with its lead index, and the presumed ones of ISA 240
        self.risk = self.env["ea.audit.risk"].sudo().create({
            "engagement_id": source.id, "description": "Coupure des ventes", "status": "concluded", "significant": True,
        })
        self.env["ea.audit.risk.index"].sudo().create({"engagement_id": source.id, "risk_id": self.risk.id, "index_code": "E"})
        # an ASP chosen and done last year, an MSP (not carried: it comes back by itself)
        Proc = self.env["ea.audit.designed.procedure"].sudo()
        self.asp = Proc.create({
            "engagement_id": source.id, "index_code": "E", "code": "E-A2", "kind": "ASP", "selected": True,
            "state": "done", "conclusion": next(iter(dict(Proc._fields["conclusion"].selection))), "conclusion_note": "OK",
            "done_by_id": self.staff.id,
        })
        Proc.create({"engagement_id": source.id, "index_code": "E", "code": "E-M1", "kind": "MSP", "selected": True})
        # a significance decision
        self.significance = self.env["ea.audit.significance"].sudo().search(
            [("engagement_id", "=", source.id), ("index_code", "!=", False)], limit=1,
        )
        self.significance.write({"decision": "significant", "justification": "Poste important"})
        # evidence: a permanent-file document in two versions, another file, one removed, a SCOT document
        self.upload("P3.1", "statuts.txt", b"statuts v1")
        self.upload("P3.1", "statuts.txt", b"statuts v2")
        self.upload("E4.1", "banque.txt", b"releve")
        removed = self.upload("E4.1", "ancien.txt", b"old")
        self.env["ea.audit.task.attachment"].browse(removed).with_user(self.manager).remove()
        self.scot.with_user(self.staff).upload_document("flux.txt", b64(b"flowchart"), "flowchart", self.control.id)
        # someone of last year's team who has since left the firm
        self.seat(self.engagement, self.outsider, "staff", state="declined")
        if self._testMethodName.startswith("test_paper_answers_"):
            # a working paper outside the old permanent file, answered, concluded and signed last year
            item = self.item(self.engagement, "E4.1")
            item._ea_ensure_papers()
            paper = self.env["ea.audit.paper"].sudo().search([("file_item_id", "=", item.id)])
            Answer = self.env["ea.audit.paper.answer"].sudo().with_context(ea_audit_answer_door=True)
            for key, value in (("exceptions", "Aucune exception"), ("q_walkthrough", "yes"), ("key_findings", "Ventes stables"),
                               ("p_flow", "done"), ("c_0", "agree")):
                Answer.create({"paper_id": paper.id, "field_key": key, "value": value})
            self.env["ea.audit.signoff"].sudo().create({
                "file_item_id": item.id, "kind": "workpaper", "role": "preparer", "user_id": self.staff.id,
            })
        if self._testMethodName == "test_only_from_a_closed_file":
            return
        # an issued, archived file: from here on no row of it may change (archive trigger)
        self.env.flush_all()
        self.cr.execute("UPDATE ea_audit_engagement SET archived_at = now(), phase = 'archived' WHERE id = %s", [source.id])
        self.env.invalidate_all()

    def upload(self, code, name, content):
        return self.item(self.engagement, code).with_user(self.staff).upload_attachment(name, b64(content))

    def roll(self, carry=ROLLFORWARD_KEYS, approach="same", members=()):
        return self.as_partner.rollforward(2026, {
            "carry": list(carry), "approach": approach, "period_end": date(2026, 12, 31),
            "partner_id": self.partner.id, "members": list(members),
        }).sudo()

    def without(self, key):
        return self.roll(carry=[k for k in ROLLFORWARD_KEYS if k != key])

    def rows(self, model, engagement):
        return self.env[model].sudo().search([("engagement_id", "=", engagement.id)])

    def carried_files(self, target):
        return self.env["ea.audit.task.attachment"].sudo().search([
            ("engagement_id", "=", target.id), ("carried_from_year", "=", 2025),
        ])

    # ------------------------------------------------------------------
    # The wizard
    # ------------------------------------------------------------------

    def test_the_wizard_lists_last_years_team_and_creates_the_file(self):
        Wizard = self.env["ea.audit.rollforward.wizard"].with_user(self.partner).with_context(default_source_id=self.engagement.id)
        wizard = Wizard.create({})
        self.assertEqual(wizard.period_end, date(2026, 12, 31))
        self.assertEqual(wizard.engagement_partner_id, self.partner)
        self.assertTrue(all(wizard[field] for field in (
            "carry_scope", "carry_materiality", "carry_scots", "carry_risks", "carry_procedures", "carry_significance",
            "carry_comparatives", "carry_answers", "carry_evidence",
        )))
        emails = {line.email: line for line in wizard.member_ids}
        self.assertNotIn(self.partner.login, emails)
        self.assertTrue(emails[self.senior.login].invite)
        emails[self.eqr.login].invite = False
        emails[self.reader.login].invite = False
        wizard.member_ids = [(0, 0, {"invite": True, "email": "newcomer@gov.example.com", "name": "Newcomer", "team_role": "staff"})]
        action = wizard.action_create()
        self.assertEqual(action["params"]["next"]["res_model"], "ea.audit.team.member")
        target = self.env["ea.audit.engagement"].sudo().search([("client_id", "=", self.client.id), ("fiscal_year", "=", 2026)])
        self.assertEqual(len(target), 1)
        team = {m.user_id.login: m for m in target.team_member_ids}
        self.assertEqual(set(team), {
            self.partner.login, self.manager.login, self.senior.login, self.staff.login, "newcomer@gov.example.com",
        })
        # every seat waits for its holder: accepting is confirming independence for the new year
        self.assertEqual(set(target.team_member_ids.mapped("state")), {"invited"})
        self.assertEqual(team[self.partner.login].team_role, "partner")
        self.assertEqual(team[self.senior.login].team_role, "senior")
        self.assertCode("not-on-this-engagement", target.with_user(self.senior)._ea_require_access)
        team[self.senior.login].with_user(self.senior).action_accept()
        target.with_user(self.senior)._ea_require_access()

    def test_who_left_the_firm_is_listed_unticked(self):
        self.outsider.active = False
        wizard = self.env["ea.audit.rollforward.wizard"].with_user(self.partner).with_context(
            default_source_id=self.engagement.id).create({})
        line = wizard.member_ids.filtered(lambda l: l.email == self.outsider.login)
        self.assertFalse(line.invite)
        self.assertEqual(line.note, "No longer in the firm: not carried")
        self.assertTrue(line.note)

    def test_only_from_a_closed_file(self):
        """This test's file is left open (setUp): no issued report, not archived."""
        self.assertFalse(self.engagement.sudo().archived_at)
        if "report_date" in self.engagement._fields:
            self.assertFalse(self.engagement.sudo().report_date)
        self.assertCode("rollforward-not-closed", self.as_partner.action_rollforward_next_year)
        self.assertCode("team-manager-only", self.as_staff.action_rollforward_next_year)

    # ------------------------------------------------------------------
    # What is carried
    # ------------------------------------------------------------------

    def test_nothing_is_concluded_or_signed_and_the_source_does_not_change(self):
        source = self.engagement.sudo()
        before = {
            model: [(r.id, r.write_date) for r in self.rows(model, source)]
            for model in ("ea.audit.task.attachment", "ea.audit.scot", "ea.audit.scot.control", "ea.audit.risk",
                          "ea.audit.designed.procedure", "ea.audit.significance", "ea.audit.tb.line", "ea.audit.team.member")
        }
        target = self.roll()
        self.env.invalidate_all()
        for model, rows in before.items():
            self.assertEqual([(r.id, r.write_date) for r in self.rows(model, source)], rows, model)
        self.assertTrue(source.archived_at)
        self.assertFalse(self.rows("ea.audit.signoff", target))
        self.assertFalse(self.rows("ea.audit.materiality", target))
        self.assertNotEqual(target._ea_profile().state, "concluded")
        control = self.rows("ea.audit.scot.control", target)
        self.assertFalse(control.operating_eval or control.design_eval or control.implemented or control.sample_size)
        proc = self.rows("ea.audit.designed.procedure", target).filtered(lambda p: p.code == "E-A2")
        self.assertEqual((proc.state, proc.conclusion, proc.done_by_id.id), ("draft", False, False))
        self.assertEqual(set(self.rows("ea.audit.risk", target).filtered("carried_from_year").mapped("status")), {"identified"})
        lines = [m.summary for m in self.env["ea.audit.activity"].sudo().search([("engagement_id", "=", target.id)])]
        self.assertTrue(any(line.startswith("Rolled forward from the 2025 file") for line in lines), lines)
        self.assertTrue(any(line.startswith("3 evidence file(s) carried forward from 2025") for line in lines), lines)

    def test_scope_same_as_last_year_brings_last_years_tasks_and_answers_to_reconfirm(self):
        target = self.roll()
        source_codes = set(self.engagement.sudo().file_item_ids.filtered(lambda i: not i.conditional).mapped("code"))
        target_codes = set(target.file_item_ids.filtered(lambda i: not i.conditional).mapped("code"))
        self.assertLessEqual(source_codes, target_codes)
        profile = target._ea_profile()
        self.assertTrue(profile)
        self.assertEqual((profile.state, profile.q20_first_year), ("draft", "no"))
        self.assertFalse(target.profile_pending)

    def test_scope_changed_reopens_the_questionnaire(self):
        target = self.roll(approach="change")
        self.assertFalse(target.complexity)
        self.assertFalse(target.file_item_ids.filtered(lambda i: not i.conditional))
        self.assertTrue(target._ea_profile())
        self.assertTrue(target.profile_pending)

    def test_scope_not_carried(self):
        target = self.without("scope")
        self.assertFalse(target._ea_profile())
        self.assertFalse(target.file_item_ids.filtered(lambda i: not i.conditional))

    def test_materiality_basis_without_amounts(self):
        basis = self.roll().ea_carried_basis["materiality"]
        self.assertEqual((basis["benchmark"], basis["percentage"]), ("total_assets", 2))
        self.assertFalse({"overall", "performance", "trivial", "benchmark_amount"} & set(basis))
        target = self.env["ea.audit.engagement"].sudo().search([("fiscal_year", "=", 2026), ("client_id", "=", self.client.id)])
        wizard = self.env["ea.audit.materiality.wizard"].with_context(default_engagement_id=target.id).new({})
        defaults = wizard.default_get(["benchmark", "percentage", "trivial_pct"])
        self.assertEqual((defaults["benchmark"], defaults["percentage"]), ("total_assets", 2))
        self.assertFalse(self.without("materiality").ea_carried_basis)

    def test_scots_controls_and_walkthrough_as_drafts(self):
        target = self.roll()
        scot = self.rows("ea.audit.scot", target)
        self.assertEqual((scot.name, scot.carried_from_year), ("Ventes", 2025))
        control = scot.control_ids
        self.assertEqual(
            (control.frequency_code, control.reliance, control.objective, control.test_design, control.carried_from_year),
            ("monthly", "heavy", "detect", "Revue mensuelle", 2025),
        )
        self.assertEqual(control.wcgw_ids, scot.wcgw_ids)
        self.assertEqual(scot.wcgw_ids.description, "Ventes non enregistrées")
        self.assertIn("2025", scot.ea_card["carried"])
        self.assertFalse(self.rows("ea.audit.scot", self.without("scots")))

    def test_risks_and_their_lead_indexes_to_reconfirm(self):
        target = self.roll()
        carried = self.rows("ea.audit.risk", target).filtered("carried_from_year")
        self.assertEqual(carried.mapped("description"), ["Coupure des ventes"])
        self.assertEqual((carried.status, carried.significant), ("identified", True))
        self.assertEqual(carried.index_link_ids.mapped("index_code"), ["E"])
        self.assertFalse(carried.presumed_type)
        self.assertFalse(self.rows("ea.audit.risk", self.without("risks")).filtered("carried_from_year"))

    def test_procedure_design_chosen_asps_only(self):
        procs = self.rows("ea.audit.designed.procedure", self.roll()).filtered("carried_from_year")
        self.assertEqual(procs.mapped("code"), ["E-A2"])
        self.assertTrue(procs.selected)
        self.assertFalse(self.rows("ea.audit.designed.procedure", self.without("procedures")).filtered("carried_from_year"))

    def test_significance_decisions_as_drafts(self):
        rows = self.rows("ea.audit.significance", self.roll())
        self.assertEqual(
            [(r.index_code, r.decision, r.justification, r.closing) for r in rows],
            [(self.significance.index_code, "significant", "Poste important", 0)],
        )
        self.assertFalse(self.rows("ea.audit.significance", self.without("significance")))

    def test_prior_year_balances_become_the_comparatives(self):
        target = self.roll()
        source_tb = self.engagement.sudo()._ea_current_tb_version()
        prior = self.rows("ea.audit.tb.version", target)
        self.assertEqual((prior.timing, prior.validation_status, len(prior.line_ids)), ("prior_year", "valid", len(source_tb.line_ids)))
        source, closings = target._ea_comparatives()
        self.assertEqual(source, "prior_year_tb")
        self.assertEqual(closings, {line.account_code: line.closing for line in source_tb.line_ids})
        self.assertFalse(self.rows("ea.audit.tb.version", self.without("comparatives")))

    # ------------------------------------------------------------------
    # Last year's evidence
    # ------------------------------------------------------------------

    def test_all_evidence_copied_with_its_mark_and_the_same_bytes(self):
        target = self.roll()
        copies = self.carried_files(target)
        self.assertEqual(sorted(shown(name) for name in copies.mapped("name")), ["banque.txt", "flux.txt", "statuts.txt"])
        source_rows = self.rows("ea.audit.task.attachment", self.engagement)
        for copy in copies:
            original = source_rows.filtered(lambda r: shown(r.name) == shown(copy.name) and not r.deleted_at).sorted("version")[-1]
            self.assertEqual(copy.code, original.code)
            self.assertEqual(copy.version, 1)
            self.assertNotEqual(copy.attachment_id, original.attachment_id)
            self.assertEqual(copy.attachment_id.checksum, original.attachment_id.checksum)
            self.assertEqual(copy.attachment_id.store_fname, original.attachment_id.store_fname)
            self.assertEqual(copy.attachment_id.res_id, copy.id)
        self.assertEqual(copies.filtered(lambda c: c.name == "statuts.txt").attachment_id.raw, b"statuts v2")
        flow = copies.filtered(lambda c: shown(c.name) == "flux.txt")
        self.assertEqual(flow.doc_type, "flowchart")
        self.assertEqual(flow.scot_id, self.rows("ea.audit.scot", target))
        self.assertEqual(flow.name, "SCOT %d - flux.txt" % flow.scot_id.id)
        self.assertEqual(flow.control_id, self.rows("ea.audit.scot.control", target))
        info = copies[0]._ea_carry_info()
        self.assertIn("2025", info["carried"])
        self.assertFalse(info["carriedReviewed"])
        item = copies.filtered(lambda c: c.name == "statuts.txt").file_item_id
        payload = self.env["ea.audit.task.attachment"]._ea_payload(item)
        self.assertIn("2025", payload["live"][0]["carried"])

    def test_a_carried_file_is_reviewed_or_removed_by_the_team(self):
        target = self.roll()
        member = target.team_member_ids.filtered(lambda m: m.user_id == self.partner)
        member.with_user(self.partner).action_accept()
        copy = self.carried_files(target).filtered(lambda c: c.name == "banque.txt")
        info = copy.with_user(self.partner).mark_carried_reviewed()
        self.assertTrue(info["carriedReviewed"])
        self.assertEqual(copy.carried_reviewed_by_id, self.partner)
        lines = self.env["ea.audit.activity"].sudo().search([("engagement_id", "=", target.id)]).mapped("summary")
        self.assertIn("E4.1: Prior-year document reviewed: banque.txt", lines)
        copy.with_user(self.partner).remove()
        self.assertTrue(copy.deleted_at)
        self.assertTrue(self.rows("ea.audit.task.attachment", self.engagement).filtered(lambda r: r.name == "banque.txt" and not r.deleted_at))

    def test_no_evidence_box_copies_nothing_not_even_the_permanent_file(self):
        """Owner 2026-11-16: no permanent-file restriction; evidence is all or nothing."""
        self.assertFalse(self.carried_files(self.without("evidence")))

    def test_paper_answers_carried_as_drafts(self):
        """Owner 2026-11-16: roll forward everything. Every answer of every paper comes in as a draft,
        marked; this year's work record, conclusions and sign-offs start again; the source is unchanged."""
        source_paper = self.env["ea.audit.paper"].sudo().search([("engagement_id", "=", self.engagement.id), ("code", "=", "E4.1")])
        before = {a.field_key: a.value for a in source_paper.answer_ids}
        target = self.roll()
        paper = self.env["ea.audit.paper"].sudo().search([("engagement_id", "=", target.id), ("code", "=", "E4.1")])
        carried = {a.field_key: a.value for a in paper.answer_ids}
        self.assertEqual(carried.get("exceptions"), "Aucune exception")
        self.assertEqual(carried.get("q_walkthrough"), "yes")
        self.assertEqual(carried.get("key_findings"), "Ventes stables")
        self.assertNotIn("p_flow", carried)
        self.assertNotIn("c_0", carried)
        self.assertTrue(all(a.carried_forward for a in paper.answer_ids))
        self.assertEqual(paper.carried_from_year, 2025)
        self.assertFalse(paper.history_ids)
        self.assertFalse(self.env["ea.audit.signoff"].sudo().search([("file_item_id", "=", paper.file_item_id.id)]))
        self.assertEqual(paper.state, "draft")
        self.assertEqual(paper.get_payload()["carried"], "Carried forward from 2025: to update")
        # the source file is left as it was
        self.assertEqual({a.field_key: a.value for a in source_paper.answer_ids}, before)

    def test_paper_answers_box_unticked_carries_none(self):
        other = self.without("answers")
        paper = self.env["ea.audit.paper"].sudo().search([("engagement_id", "=", other.id), ("code", "=", "E4.1")])
        self.assertFalse(paper.answer_ids.filtered("carried_forward"))

    def test_evidence_waits_on_a_hidden_task_until_the_questionnaire_brings_it(self):
        target = self.roll(approach="change")
        copy = self.carried_files(target).filtered(lambda c: c.name == "statuts.txt")
        self.assertTrue(copy.file_item_id.conditional)
        target.sudo().complexity = "complex"
        target._ea_instantiate_file_index()
        self.assertFalse(copy.file_item_id.conditional)
