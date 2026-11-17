"""Two languages: English in the source, French in fr.po, the user's language decides.
Dates stay DD/MM/YYYY in both."""
import pathlib
import re
from xml.etree import ElementTree

from odoo.tests import tagged
from odoo.tools.misc import file_path

from odoo.addons.ea_audit_core.services.errors import AuditRuleError

from ..models.common import MESSAGES, refuse
from .common import AT_LOCK, MONDAY, TUESDAY, TimesheetCase

_ADDON = "ea_audit_timesheet"
_ATTRS = ("placeholder", "title", "label", "aria-label", "alt")


def _template_terms():
    root = ElementTree.parse(file_path("%s/static/src/xml/timesheet.xml" % _ADDON)).getroot()
    terms = set()
    for node in root.iter():
        for text in (node.text, node.tail):
            text = (text or "").strip()
            if re.search(r"[A-Za-z]", text or ""):
                terms.add(text)
        terms.update(node.attrib[a].strip() for a in _ATTRS if a in node.attrib)
    return terms


def _script_terms():
    terms = set()
    folder = pathlib.Path(file_path("%s/static/src/js" % _ADDON))
    for script in folder.glob("*.js"):
        terms.update(re.findall(r'_t\(\s*"((?:[^"\\]|\\.)*)"', script.read_text(encoding="utf-8")))
    return terms


def _po_js_terms():
    text = pathlib.Path(file_path("%s/i18n/fr.po" % _ADDON)).read_text(encoding="utf-8")
    terms = set()
    for block in text.split("\n\n"):
        match = re.search(r'^msgid "(.*)"$', block, re.M)
        if match and "odoo-javascript" in block:
            terms.add(match.group(1).replace('\\"', '"'))
    return terms


@tagged("post_install", "-at_install")
class TestLanguages(TimesheetCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang("fr_FR")
        cls.env["ir.module.module"].search([("name", "=", _ADDON)])._update_translations(["fr_FR"], overwrite=True)

    def in_lang(self, user, lang):
        return self.Sheet.with_user(user).with_context(lang=lang)

    def test_every_refusal_has_its_french(self):
        fr = self.env(context=dict(self.env.context, lang="fr_FR"))
        en = self.env(context=dict(self.env.context, lang="en_US"))
        same = [code for code in MESSAGES if refuse(fr, code).args[0] == refuse(en, code).args[0]]
        self.assertEqual(same, [])

    def test_a_refusal_reaches_each_person_in_their_language(self):
        self.at(AT_LOCK)
        for lang, word in (("en_US", "locked"), ("fr_FR", "verrouillée")):
            with self.assertRaises(AuditRuleError) as caught:
                self.in_lang(self.staff, lang).ea_ts_charge(str(TUESDAY), self.project.id, 1)
            self.assertEqual(caught.exception.code, "ts-week-locked")
            self.assertIn(word, caught.exception.args[0])

    def test_the_timesheet_screen_in_both_languages(self):
        self.in_lang(self.staff, "en_US").ea_ts_charge(str(MONDAY), self.project.id, 3)
        english = self.in_lang(self.staff, "en_US").ea_ts_sheet(str(TUESDAY))
        french = self.in_lang(self.staff, "fr_FR").ea_ts_sheet(str(TUESDAY))
        self.assertEqual(english["label"], "Week of 02/11/2026 to 08/11/2026")
        self.assertEqual(french["label"], "Semaine du 02/11/2026 au 08/11/2026")
        self.assertEqual(english["status_label"], "Open")
        self.assertEqual(french["status_label"], "Ouverte")
        self.assertEqual(english["days"][0]["label"], "Mon 02/11/2026")
        self.assertEqual(french["days"][0]["label"], "lun. 02/11/2026")
        self.assertEqual(english["deadline_label"], "Tuesday 10/11/2026, 23:59")
        self.assertEqual(french["deadline_label"], "mardi 10/11/2026, 23:59")
        tasks_en = next(p for p in english["projects"] if p["id"] == self.project.id)["tasks"]
        tasks_fr = next(p for p in french["projects"] if p["id"] == self.project.id)["tasks"]
        self.assertIn("Strategy and risks", [t["name"] for t in tasks_en])
        self.assertIn("Stratégie & risques", [t["name"] for t in tasks_fr])

    def test_the_switcher_in_both_languages(self):
        Ui = self.env["ea.audit.ui"].with_user(self.admin)
        labels = lambda lang: [a["label"] for a in Ui.with_context(lang=lang)._ea_ui_apps()]
        self.assertEqual(labels("en_US"), ["Audit", "Timesheet", "Users", "Settings"])
        self.assertEqual(labels("fr_FR")[1:], ["Feuille de temps", "Utilisateurs", "Paramètres"])

    def test_screens_and_lists_in_both_languages(self):
        fa = self.FirmAdmin.with_user(self.admin)
        roles = lambda lang: {r["key"]: r["label"] for r in fa.with_context(lang=lang).ea_fa_users()["roles"]}
        self.assertEqual(roles("en_US")["partner"], "Partner")
        self.assertEqual(roles("fr_FR")["partner"], "Associé")
        action = self.env.ref("ea_audit_timesheet.action_sheet")
        self.assertEqual(action.with_context(lang="fr_FR").name, "Feuille de temps")
        self.assertEqual(action.with_context(lang="en_US").name, "Timesheet")
        phases = self.env["account.analytic.line"].with_context(lang="fr_FR").fields_get(["ea_phase"])
        self.assertEqual(dict(phases["ea_phase"]["selection"])["strategy"], "Stratégie & risques")

    def test_dates_stay_day_first_in_both(self):
        for lang in ("en_US", "fr_FR"):
            self.assertIn("02/11/2026", self.in_lang(self.staff, lang).ea_ts_sheet(str(TUESDAY))["label"])

    def test_no_template_or_script_term_is_left_without_french(self):
        missing = (_template_terms() | _script_terms()) - _po_js_terms()
        # the protocol names of the mail screen and the masks are the same in both languages
        missing -= {"STARTTLS", "SSL/TLS"}
        self.assertEqual(sorted(missing), [])
