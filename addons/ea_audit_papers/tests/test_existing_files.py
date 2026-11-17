from odoo.tests import tagged

from odoo.addons.ea_audit_core.services.file_scope import SCOPE_LEGACY

from ..models.paper_answer import ANSWER_DOOR
from ..services import CONCLUSION_KEY, legacy_entry, paper_for, required_keys
from .common import PaperCase


@tagged("post_install", "-at_install")
class TestExistingFiles(PaperCase):
    """Files opened before the layout of 2026-11-17 (owner's condition: a paper complete before
    stays complete; the merged tasks' work stays where it was done)."""

    def legacy_file(self, year=2023):
        engagement = self.make_engagement(year, complexity="complex", scope_version=SCOPE_LEGACY)
        self.set_phase(engagement, "execution")
        return engagement

    def put_back(self, engagement, code):
        """A merged task an older file still carries."""
        template = self.env["ea.audit.task.template"].sudo().search([("code", "=", code)], limit=1)
        item = self.item(engagement, code)
        if item:
            item.sudo().conditional = False
            return item
        return self.env["ea.audit.file.item"].sudo().create({
            "engagement_id": engagement.id, "template_id": template.id, "conditional": False,
        })

    def store(self, engagement, code, values):
        """Answers as a file saved them before the conversion (the old conclusion keys included,
        which the converted paper no longer lets a save write)."""
        paper = self.paper(code, engagement)
        self.env["ea.audit.paper.answer"].sudo().with_context(**{ANSWER_DOOR: True}).create([
            {"paper_id": paper.id, "field_key": key, "value": value} for key, value in values.items()
        ])
        return paper

    def old_answers(self, code):
        """Every key the converted paper requires, but its new conclusion box, plus the old
        conclusion statements answered Yes."""
        values = {
            key: "yes" if key[:2] in ("q_", "c_") else "Done, see file."
            for key in required_keys(paper_for(code, "current", self.client.legal_form)) if key != CONCLUSION_KEY
        }
        values.update({"c_%d" % index: "yes" for index in range(len(legacy_entry(code)["conclEn"]))})
        return values

    def sections(self, payload):
        procs = {p["key"] for s in payload["definition"]["sections"] if s["kind"] == "proc" for p in s["procs"]}
        items = {i["key"] for s in payload["definition"]["sections"] if s["kind"] == "yn" for i in s["items"]}
        return procs, items

    # a) the old conclusion keys

    def test_an_old_conclusion_shows_and_counts(self):
        paper = self.store(self.engagement, "P3.2", self.old_answers("P3.2"))
        payload = paper.with_user(self.manager).get_payload()
        self.assertNotIn(CONCLUSION_KEY, payload["missing"])
        self.assertTrue(payload["legacy_values"][CONCLUSION_KEY])
        self.assertNotIn(CONCLUSION_KEY, payload["values"])
        self.assertNotIn(CONCLUSION_KEY, paper._ea_values())

    def test_without_the_old_keys_the_conclusion_is_asked(self):
        values = {k: v for k, v in self.old_answers("P3.2").items() if not k.startswith("c_")}
        paper = self.store(self.engagement, "P3.2", values)
        payload = paper.with_user(self.manager).get_payload()
        self.assertIn(CONCLUSION_KEY, payload["missing"])
        self.assertFalse(payload["legacy_values"])

    def test_an_old_p11_still_opens_the_acceptance_gate(self):
        older = self.legacy_file()
        values = self.old_answers("P1.1")
        values["rating"] = "low"
        self.store(older, "P1.1", values)
        self.assertTrue(older.sudo()._ea_p11_form_state()["complete"])
        # a file of the current scope writes the conclusion of the new layout
        self.store(self.engagement, "P1.1", values)
        self.assertFalse(self.engagement.sudo()._ea_p11_form_state()["complete"])

    # b) the merged tasks

    def test_p41_shows_the_control_environment_on_a_current_file(self):
        procs, items = self.sections(self.paper("P4.1").with_user(self.manager).get_payload())
        self.assertIn("tone", procs)
        self.assertIn("foundation", items)

    def test_a_file_carrying_p42_keeps_the_control_environment_there(self):
        self.put_back(self.engagement, "P4.2")
        payload = self.paper("P4.1").with_user(self.manager).get_payload()
        procs, items = self.sections(payload)
        self.assertFalse({"tone", "oversight", "structure", "competence", "pressure"} & procs)
        self.assertFalse({"culture", "foundation", "no_pressure"} & items)
        self.assertNotIn("p_tone", payload["missing"])
        self.assertIn("risk_process", procs)

    def test_an_older_file_reads_c41_and_e63_without_the_merged_parts(self):
        older = self.legacy_file()
        for code, procs_gone in (("C4.1", {"points", "points_clear"}), ("E6.3", {"capital", "capital_procedure"})):
            self.assertTrue(self.item(older, code), code)
            procs, _items = self.sections(self.paper(code, older).with_user(self.partner).get_payload())
            self.assertFalse(procs_gone & procs, code)
        procs, _items = self.sections(self.paper("E6.3").with_user(self.manager).get_payload())
        self.assertIn("capital", procs)

    # c) S6.1's detailed control-environment assessment

    def test_s61_brings_p41_and_never_p42_on_a_current_file(self):
        p41 = self.item(self.engagement, "P4.1")
        self.save(self.manager, "S6.1", {"assess_control_env": "yes"})
        p42 = self.item(self.engagement, "P4.2")
        self.assertFalse(p42 and not p42.conditional)
        self.assertTrue(p41 and not p41.conditional)
        self.save(self.manager, "S6.1", {"assess_control_env": "no"})
        self.assertFalse(self.item(self.engagement, "P4.1").conditional)

    def test_s61_still_brings_p42_on_an_older_file(self):
        older = self.legacy_file()
        self.save(self.partner, "S6.1", {"assess_control_env": "yes"}, engagement=older)
        p42 = self.item(older, "P4.2")
        self.assertTrue(p42 and not p42.conditional)
