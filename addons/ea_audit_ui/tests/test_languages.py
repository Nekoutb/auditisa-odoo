"""English and French: nothing hard-coded, every paper and refusal in both, no raw key shown."""
import importlib
import pathlib
import re

from odoo.tests import TransactionCase, tagged

from odoo.addons.ea_audit_papers.services import paper_for
from odoo.addons.ea_audit_reports.services.articles import mark_articles
from odoo.addons.ea_audit_reports.services.gates import GATE_LABELS, gate_label
from odoo.addons.ea_audit_reports.services.opinion import OPINIONS, report_blocks
from odoo.addons.ea_audit_tools.models.tool_record import fcfa, grouped

from ..services.presentation import (
    FIRM_ROLE_LABELS,
    HOME_EMPTY,
    HOME_EMPTY_START,
    NATURE_LABELS,
    STATUS_PILLS,
    STATUS_WORDS,
    TASKS_AWAIT_PROFILE,
    TASKS_NONE_MINE,
    TASKS_NONE_OPEN,
    TEAM_ROLE_LABELS,
)
from ..services.task_groups import SECTION_LABELS, SECTION_SHORT_LABELS, TASK_GROUPS
from .french_scan import scan_addons, scan_js, scan_python

ADDONS = pathlib.Path(__file__).resolve().parents[2]
REFUSALS = (
    "ea_audit_core.services.errors", "ea_audit_papers.models.errors", "ea_audit_tools.rules", "ea_audit_reports.rules",
    "ea_audit_legal.rules", "ea_audit_portal.rules",
)


@tagged("post_install", "-at_install")
class TestScan(TransactionCase):
    def test_no_hard_coded_french_is_left(self):
        left = ["%s:%s %s" % row for row in scan_addons(ADDONS)]
        self.assertEqual(left, [])

    def test_the_scan_catches_what_it_should(self):
        self.assertTrue(scan_python('x = "Tâche terminée"\n'))
        self.assertTrue(scan_python('raise ValueError("le dossier est fermé")\n'))
        self.assertTrue(scan_python('x = "Aucun dossier pour le client"\n'))
        self.assertFalse(scan_python('x = "Task complete"\n'))
        self.assertFalse(scan_python('x = {"en": "Task", "fr": "Tâche"}\n'))
        self.assertFalse(scan_python('x = "Oui" if fr else "Yes"\n'))
        self.assertTrue(scan_js('const x = "Échéance";\n'))
        self.assertFalse(scan_js('const x = _t("Deadline");\n'))


@tagged("post_install", "-at_install")
class TestBothLanguages(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._ea_setup_languages()
        cls.fr = cls.env(context=dict(cls.env.context, lang="fr_FR"))
        cls.en = cls.env(context=dict(cls.env.context, lang="en_US"))

    def test_both_languages_are_installed_and_read_day_first(self):
        installed = dict(self.env["res.lang"].get_installed())
        for code in ("en_US", "fr_FR"):
            self.assertIn(code, installed)
            self.assertEqual(self.env["res.lang"]._get_data(code=code).date_format, "%d/%m/%Y")

    def test_separators_follow_the_language(self):
        english = self.env["res.lang"]._get_data(code="en_US")
        french = self.env["res.lang"]._get_data(code="fr_FR")
        self.assertEqual((english.thousands_sep, english.decimal_point), (",", "."))
        self.assertEqual((french.thousands_sep, french.decimal_point), (" ", ","))
        self.assertEqual(fcfa(1234567, "en_US"), "1,234,567 FCFA")
        self.assertEqual(fcfa(1234567, "fr_FR"), "1 234 567 FCFA")
        self.assertEqual(grouped(-2500, "en_US"), "(2,500)")  # brackets (owner, 2026-11-15)

    def test_every_paper_resolves_in_both(self):
        missing = []
        templates = self.env["ea.audit.task.template"].sudo().search([])
        self.assertGreater(len(templates), 100)
        for template in templates:
            paper = paper_for(template.code, "current", "SA")
            if not paper:
                continue
            if not _both_sides(paper):
                missing.append(template.code)
        self.assertEqual(missing, [])

    def test_every_task_title_and_short_title_reads_in_both(self):
        untranslated = []
        for template in self.env["ea.audit.task.template"].sudo().search([]):
            english, french = template.with_env(self.en), template.with_env(self.fr)
            if not english.title or not french.title:
                untranslated.append(template.code)
            elif english.title == french.title and len(english.title.split()) > 3:
                untranslated.append(template.code)
        self.assertEqual(untranslated, [])

    def test_every_refusal_code_has_both(self):
        one_word = re.compile(r"^\S+$")
        for module_name in REFUSALS:
            module = importlib.import_module("odoo.addons.%s" % module_name)
            for code, message in module.MESSAGES.items():
                english = _text(self.en, message)
                french = _text(self.fr, message)
                self.assertTrue(english, code)
                self.assertTrue(french, code)
                if not one_word.match(english):
                    self.assertNotEqual(english, french, "%s: %s has no French" % (module_name, code))

    def test_no_raw_key_in_the_renderer(self):
        """Every label the paper templates ask for exists in labels.js."""
        root = ADDONS / "ea_audit_papers/static/src/paper"
        labels = (root / "labels.js").read_text(encoding="utf-8")
        known = set(re.findall(r"^\s+\"?([\w-]+)\"?: _t\(", labels, re.M))
        wanted = set()
        for path in root.iterdir():
            if path.suffix in (".xml", ".js"):
                wanted |= set(re.findall(r"\bt\(['\"]([\w]+)['\"]\)", path.read_text(encoding="utf-8")))
        self.assertEqual(sorted(wanted - known), [])
        self.assertNotIn('["', re.sub(r"export const CHIP_LETTER.*", "", labels))

    def test_screens_words_exist_in_french(self):
        same_allowed = {"Manager", "Senior", "manager", "senior", "senior manager", "Conclusion"}
        words = list(FIRM_ROLE_LABELS.values()) + list(TEAM_ROLE_LABELS.values()) + list(NATURE_LABELS.values())
        words += list(STATUS_WORDS.values()) + [pill for pill, _tone in STATUS_PILLS.values()]
        words += list(SECTION_LABELS.values()) + list(SECTION_SHORT_LABELS.values())
        words += [group["title"] for group in TASK_GROUPS] + [group["short"] for group in TASK_GROUPS if group.get("short")]
        # what an empty screen says
        words += [HOME_EMPTY, HOME_EMPTY_START, TASKS_AWAIT_PROFILE, TASKS_NONE_MINE, TASKS_NONE_OPEN]
        Ui = self.env["ea.audit.ui"]
        french_env = Ui.with_env(self.fr).env
        for word in words:
            translated = _as_ui_module(french_env, word)
            self.assertTrue(translated)
            if word not in same_allowed:
                self.assertNotEqual(translated, word, word)

    def test_gate_labels_in_both(self):
        for key in GATE_LABELS:
            self.assertNotEqual(gate_label(key, True), gate_label(key, False), key)
        self.assertEqual(gate_label("no-such-gate", False), "no-such-gate")

    def test_report_in_either_language(self):
        import datetime

        end, dated = datetime.date(2025, 12, 31), datetime.date(2026, 3, 1)
        for opinion in OPINIONS:
            english = " ".join(b["s"] for b in report_blocks(opinion, "ACME", end, dated, basis="x", fr=False))
            french = " ".join(b["s"] for b in report_blocks(opinion, "ACME", end, dated, basis="x", fr=True))
            self.assertIn("(to validate)", english, opinion)
            self.assertIn("31/12/2025", english)
            self.assertIn("31 décembre 2025", french)
            self.assertNotIn("certifions", english)
            self.assertIn("certifi", french)
        self.assertIn("art. 716 (to validate)", mark_articles("art. 716", False, False))
        self.assertIn("art. 716 (à valider)", mark_articles("art. 716", False, True))

    def test_notification_reads_in_the_addressee_language(self):
        reader = self.fr
        self.assertEqual(reader["ea.audit.ui"]._ea_ui_word("to_review"), "À réviser")
        self.assertEqual(self.en["ea.audit.ui"]._ea_ui_word("to_review"), "To review")


def _as_ui_module(env, word):
    """env._ takes the module of its caller: this test lives in ea_audit_ui."""
    return env._(word)


def _text(env, message):
    """A lazy message of LazyTranslate, read in that environment's language."""
    return message._translate(env.lang or "en_US")


def _both_sides(node):
    """A definition holds each En key with its Fr twin, and en with fr."""
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str) and value.strip():
                if key.endswith("En") and not node.get(key[:-2] + "Fr", "").strip():
                    return False
                if key.endswith("Fr") and not node.get(key[:-2] + "En", "").strip():
                    return False
                if key == "en" and not (node.get("fr") or "").strip():
                    return False
                if key == "fr" and not (node.get("en") or "").strip():
                    return False
            elif not _both_sides(value):
                return False
    elif isinstance(node, list):
        return all(_both_sides(value) for value in node)
    return True
