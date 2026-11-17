import json

from odoo.tests import tagged
from odoo.tools.misc import file_open

from odoo.addons.ea_audit_core.services.file_scope import SCOPE_LEGACY, code_in_scope

from .common import EaAuditCase


@tagged("post_install", "-at_install")
class TestFileIndex(EaAuditCase):
    """The data exported from lib/file-index.ts, against itemsForComplexity."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.templates = cls.env["ea.audit.task.template"].search([])
        with file_open("ea_audit_core/tests/data/file_index_scopes.json") as handle:
            cls.golden = json.load(handle)

    def _scope(self, complexity, form=None, nature=None, scope=SCOPE_LEGACY):
        return [
            t.code for t in self.templates
            if code_in_scope(t.code, t.tier, t.conditional, complexity, form, nature, scope)
        ]

    def test_the_118_codes_with_their_gaps(self):
        codes = self.templates.mapped("code")
        self.assertEqual(len(codes), 118)
        self.assertEqual(len(set(codes)), 118)
        self.assertEqual(self.templates.filtered("conditional").mapped("code"), [
            c for c in codes if c in {"P1.2", "P4.2", "P4.3", "S5.1", "S5.2", "S5.3", "E5.1", "E5.2", "E5.3", "E5.4", "E5.5"}
        ])
        self.assertEqual(
            set(self.templates.filtered(lambda t: t.tier == "extended").mapped("code")),
            {"C4.2", "P2.3", "E4.6", "E4.12", "E4.13", "C5.5", "C5.9"},
        )

    def test_scope_matches_the_typescript(self):
        for complexity, count in self.golden["counts"].items():
            self.assertEqual(len(self._scope(complexity)), count, complexity)
        for nature, codes in self.golden["scopes"].items():
            self.assertEqual(self._scope("complex", "SA", nature), codes, nature)

    def test_instantiation_follows_complexity_and_legal_form(self):
        engagement = self.make_engagement(complexity="very_simple")
        self.assertEqual(len(engagement.sudo().file_item_ids), self.golden["current"]["counts"]["SA"]["very_simple"]["onFile"])
        legacy = self.make_engagement(complexity="very_simple", scope_version=SCOPE_LEGACY)
        self.assertEqual(len(legacy.sudo().file_item_ids), self.golden["counts"]["very_simple"])
        sarl = self.env["ea.audit.client"].create({"name": "Petite SARL", "legal_form": "SARL"})
        file_sarl = self.make_engagement(client=sarl)
        self.assertFalse(self.item(file_sarl, "C5.7"))
        self.assertTrue(self.item(self.make_engagement(), "C5.7"))
        sa_ag = self.env["ea.audit.client"].create({"name": "AG SA", "legal_form": "SA_AG"})
        self.assertTrue(self.item(self.make_engagement(client=sa_ag), "C5.7"))

    def test_deferred_scoping_and_reassessment_only_adds(self):
        deferred = self.make_engagement(complexity=False)
        self.assertFalse(deferred.sudo().file_item_ids)
        deferred.with_user(self.partner).apply_complexity("very_simple")
        count = len(deferred.sudo().file_item_ids)
        deferred.with_user(self.partner).apply_complexity("non_complex")
        non_complex = self.golden["current"]["counts"]["SA"]["non_complex"]["onFile"]
        self.assertEqual(len(deferred.sudo().file_item_ids), non_complex)
        self.assertGreater(len(deferred.sudo().file_item_ids), count)
        deferred.with_user(self.partner).apply_complexity("very_simple")
        self.assertEqual(len(deferred.sudo().file_item_ids), non_complex)

    def test_standards_edition_follows_the_period_start(self):
        # a period beginning 1 Jan 2026 stays current; one beginning 1 Jan 2027 is revised
        self.assertEqual(self.make_engagement(2026).sudo().standards_edition, "current")
        self.assertEqual(self.make_engagement(2027).sudo().standards_edition, "revised_2026")
        engagement = self.make_engagement(2026)
        as_partner = engagement.with_user(self.partner)
        self.assertCode("reason-required", as_partner.set_standards_edition, "revised_2026", " ")
        self.assertCode("invalid-standards-edition", as_partner.set_standards_edition, "2031", "why")
        self.assertCode("forbidden", as_partner.write, {"standards_edition": "revised_2026"})
        as_partner.set_standards_edition("revised_2026", "firm decision")
        self.assertEqual(engagement.sudo().standards_edition, "revised_2026")
