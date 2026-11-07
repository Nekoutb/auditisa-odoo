"""F086, the check: no activity line reaches a reader with its technical key or in the wrong language.

The scan reads every call to _ea_log and _ea_trail in the addons, renders its text with sample
values, and fails on a line the translator does not know. A new line without an entry in
services/activity_summary.py, and without its French, stops here rather than on a client's screen.
"""
import ast
import pathlib
import re

from odoo.tests import TransactionCase, tagged

from ..services.activity_summary import BY_ACTION, ENTRIES, KEYED_LINE, is_known, parse_body, translate_summary

ADDONS = pathlib.Path(__file__).resolve().parents[2]
FIRM_ADDONS = (
    "ea_audit_core", "ea_audit_papers", "ea_audit_tools", "ea_audit_ui", "ea_audit_reports", "ea_audit_legal",
    "ea_audit_portal", "ea_audit_timesheet",
)
# A generic forwarder: _ea_after_evidence_change, whose callers give the words, is scanned itself.
_FORWARDERS = {"%s: %s"}
# A line of a few words which reads the same in both languages is fine; a sentence is not.
_SAME_IN_BOTH = re.compile(r"^\S+( \S+){0,2}$")


def _sample(template):
    """A literal "%s ... %d" with sample values, one word each."""
    return re.sub(r"%\.?\d*[sd]", lambda m: "1" if m[0].endswith("d") else "X1", template)


def _texts(node):
    """The literal templates of an argument: a plain string, the left of %, both sides of an if."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        yield from _texts(node.left)
    elif isinstance(node, ast.IfExp):
        yield from _texts(node.body)
        yield from _texts(node.orelse)


def scan_source(source):
    """[(line number, action or None, rendered line)] of every literal trail line in a source."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in ("_ea_log", "_ea_trail") or len(node.args) < 2:
            continue
        action = node.args[0].value if isinstance(node.args[0], ast.Constant) else None
        for text in _texts(node.args[1]):
            if text not in _FORWARDERS:
                found.append((node.lineno, action, _sample(text)))
    for node in ast.walk(ast.parse(source)):
        # the evidence lines go through one method, which adds the task's code
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_ea_after_evidence_change":
            for text in _texts(node.args[2]):
                found.append((node.lineno, None, "X1: %s" % _sample(text)))
    return found


def scan_addons():
    rows = []
    for addon in FIRM_ADDONS:
        for path in (ADDONS / addon).rglob("*.py"):
            if "tests" in path.parts:
                continue
            for line, action, text in scan_source(path.read_text(encoding="utf-8")):
                rows.append(("%s:%d" % (path.name, line), action, text))
    return rows


@tagged("post_install", "-at_install")
class TestActivitySummaries(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._ea_setup_languages()

    def test_every_line_of_the_trail_has_its_entry(self):
        rows = scan_addons()
        self.assertGreater(len(rows), 40)
        unknown = [row for row in rows if not is_known(row[1], row[2])]
        self.assertEqual(unknown, [])

    def test_the_scan_catches_a_line_with_no_entry(self):
        rows = scan_source('engagement._ea_log("new_thing", "%s did something new" % name)\n')
        self.assertEqual(rows, [(1, "new_thing", "X1 did something new")])
        self.assertFalse(is_known(*rows[0][1:]))
        rows = scan_source('e._ea_log("a", "P1 saved" if x else "%d rows dropped" % y)\n')
        self.assertEqual([row[2] for row in rows], ["P1 saved", "1 rows dropped"])

    def test_every_entry_reads_in_french(self):
        """Every template, in fr.po: an entry without its French fails here."""
        same = []
        for _pattern, template in ENTRIES:
            english = template._translate("en_US")
            french = template._translate("fr_FR")
            if english == french and not _SAME_IN_BOTH.match(english):
                same.append(english)
        for template in BY_ACTION.values():
            if template._translate("en_US") == template._translate("fr_FR"):
                same.append(template._translate("en_US"))
        self.assertEqual(same, [])

    def test_a_french_reader_gets_no_key_and_no_storage_name(self):
        for action, summary, expected, absent in (
            ("signed_off", "P1.4 signed by Jean-Pierre Mbarga as reviewer", "P1.4 signée par Jean-Pierre Mbarga comme réviseur", "reviewer"),
            ("tasks_assigned", "1 task(s) assigned as preparer: P3.1", "1 tâche(s) affectée(s) comme préparateur : P3.1", "assigned"),
            ("paper_saved", "P1.5 working paper saved: c_0, eligibility, key_findings", "P1.5 : feuille de travail enregistrée, 3 champ(s)", "c_0"),
        ):
            text = translate_summary(action, summary, "fr_FR")
            self.assertEqual(text, expected)
            self.assertNotIn(absent, text)
            self.assertNotIn(action, text)

    def test_an_english_reader_gets_no_storage_name_either(self):
        text = translate_summary("paper_saved", "P1.5 working paper saved: c_0, eligibility", "en_US")
        self.assertEqual(text, "P1.5 working paper saved: 2 field(s)")

    def test_an_unknown_line_shows_as_stored_without_its_key(self):
        self.assertEqual(translate_summary("x", "Something else", "fr_FR"), "Something else")
        self.assertEqual(parse_body("<p>signed_off: P1.4 signed by A &amp; B as reviewer</p>"), ("signed_off", "P1.4 signed by A & B as reviewer"))
        self.assertIsNone(parse_body("A person's own note, with no key"))
        self.assertTrue(KEYED_LINE.match("legal_hold.placed: x"))
