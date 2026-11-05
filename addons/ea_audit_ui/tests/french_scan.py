"""Finds hard-coded French in the addons' templates and Python messages. Pure stdlib.

French may live only in: i18n/fr.po, the bilingual data of a definition (a value under a key
``fr``/``*Fr``/``*_fr``, a constant named ``*_FR``, the second item of an [en, fr] pair), lines
marked ``i18n: input`` (words read from a client's file or matched in French data, never shown)
or ``i18n: term`` (an OHADA term of art kept in the English wording), and tests. Run as a script from the repository root to list what is left.
"""
import ast
import json
import pathlib
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET

ACCENTS = re.compile("[éèêëàâçùûôîïÉÈÊÀÂÇÔÎ«»œ]")
# Words that do not occur in English prose or in code. Two in one string count as French;
# one trade noun is enough when the string is short.
WEAK = set("""le la les des du une un au aux et ou est sont pour avec sans dans sur par que qui ne pas
ce cette ces son sa ses leur nos vos votre notre doit peut faut aucun aucune avant apres tous toutes
tout plus encore""".split())
STRONG = set("""tache taches lettre lettres exercice compte comptes montant montants valider refus
manquant manquante veuillez seuil seuils risque risques controle controles revue revues societe ecart
ecarts anomalie anomalies accueil tableau bord enregistrer annuler fermer supprimer ajouter modifier
importer exporter generer approuver constatation constatations constats synthese outils commissaire
comptable comptables echantillon sondage nouveau nouvelle""".split())


def _plain(word):
    return "".join(c for c in unicodedata.normalize("NFD", word.lower()) if not unicodedata.combining(c))


def looks_french(text):
    if not isinstance(text, str) or not text.strip():
        return False
    if ACCENTS.search(text):
        return True
    words = [_plain(w) for w in re.findall(r"[^\W\d_]+", text)]
    if len(words) < 2:
        return False
    weak = sum(1 for w in words if w in WEAK)
    if weak >= 2:
        return True
    strong = sum(1 for w in words if w in STRONG)
    return bool(strong) and (weak >= 1 or len(words) <= 3)


# ``_d("Sales", "Ventes")``: the English and the French side by side, the caller chooses.
_PAIR_CALLS = {"_d", "pick"}
_LANG_TESTS = {"fr", "french", "is_french", "_ea_fr", "isFr"}


def _is_fr_key(key):
    return isinstance(key, str) and (key in ("fr", "FR") or key.endswith(("Fr", "_fr", "_FR")))


class _Scan(ast.NodeVisitor):
    def __init__(self, source):
        self.lines = source.splitlines()
        self.found = []
        self.skip = set()

    def _skip_tree(self, node):
        for sub in ast.walk(node):
            self.skip.add(id(sub))

    def _doc(self, node):
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            self._skip_tree(body[0])

    def visit_Module(self, node):
        self._doc(node)
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self._doc(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self._doc(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Dict(self, node):
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and _is_fr_key(key.value):
                self._skip_tree(value)
        self.generic_visit(node)

    def visit_Assign(self, node):
        for target in node.targets:
            if isinstance(target, ast.Name) and _is_fr_key(target.id):
                self._skip_tree(node.value)
        self.generic_visit(node)

    def visit_Call(self, node):
        name = getattr(node.func, "id", getattr(node.func, "attr", ""))
        if name in _PAIR_CALLS and len(node.args) >= 2:
            self._skip_tree(node.args[1])
        for keyword in node.keywords:
            if keyword.arg and _is_fr_key(keyword.arg):
                self._skip_tree(keyword.value)
        self.generic_visit(node)

    def visit_IfExp(self, node):
        """``"Oui" if fr else "Yes"``: both languages are in the code and the caller chooses."""
        names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
        names |= {n.attr for n in ast.walk(node.test) if isinstance(n, ast.Attribute)}
        if names & _LANG_TESTS:
            negated = isinstance(node.test, ast.UnaryOp)
            self._skip_tree(node.orelse if negated else node.body)
        self.generic_visit(node)

    def _pair(self, node):
        """An [en, fr] or (fr, en) pair: one side French, the other not. A longer tuple of
        strings keeps the rule for its last two, as (key, en, fr) rows do."""
        elts = node.elts[-2:]
        if len(elts) == 2 and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in elts):
            first, second = looks_french(elts[0].value), looks_french(elts[1].value)
            if first != second:
                self.skip.add(id(elts[0] if first else elts[1]))

    def visit_List(self, node):
        self._pair(node)
        self.generic_visit(node)

    def visit_Tuple(self, node):
        self._pair(node)
        self.generic_visit(node)

    def visit_Constant(self, node):
        if id(node) in self.skip or not looks_french(node.value):
            return
        for lineno in range(node.lineno, node.end_lineno + 1):
            if lineno <= len(self.lines) and ("i18n: input" in self.lines[lineno - 1] or "i18n: term" in self.lines[lineno - 1]):
                return
        self.found.append((node.lineno, node.value))


def scan_python(source):
    scan = _Scan(source)
    scan.visit(ast.parse(source))
    return scan.found


def _line_of(raw, text):
    index = raw.find(text[:40])
    return raw.count("\n", 0, index) + 1 if index >= 0 else 0


_SKIP_ATTRS = ("id", "name", "path", "domain", "context", "invisible", "readonly", "required", "groups", "class", "model")


def scan_xml(raw):
    found = []
    for node in ET.fromstring(raw).iter():
        for text in (node.text, node.tail):
            if text and looks_french(text):
                found.append((_line_of(raw, text.strip()), text.strip()))
        for attr, value in node.attrib.items():
            if attr.startswith("t-"):
                # Literals inside expressions: t-esc="x or 'Aucun'".
                for literal in re.findall(r"'([^']{3,})'", value):
                    if looks_french(literal):
                        found.append((_line_of(raw, literal), literal))
            elif attr not in _SKIP_ATTRS and looks_french(value):
                found.append((_line_of(raw, value), value))
    return found


_JS_STRING = re.compile(r"""(?<![\w])(?:"((?:[^"\\\n]|\\.)*)"|'((?:[^'\\\n]|\\.)*)'|`((?:[^`\\]|\\.)*)`)""")
_JS_PAIR = re.compile(r"(fr|Fr)\s*:\s*$|fr\s*\?\s*$")
_JS_COMMENT = re.compile(r"/\*.*?\*/|^\s*//.*$|\s//\s.*$", re.S | re.M)


def scan_js(raw):
    found = []
    code = _JS_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), raw)
    for lineno, line in enumerate(code.splitlines(), 1):
        if "i18n: input" in line:
            continue
        for match in _JS_STRING.finditer(line):
            text = match.group(1) or match.group(2) or match.group(3) or ""
            if looks_french(text) and not re.search(r"(\bfr|Fr)\s*:\s*$", line[:match.start()]):
                found.append((lineno, text))
    return found


def scan_addons(root):
    root = pathlib.Path(root)
    report = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if not path.is_file() or re.search(r"(^|/)(tests|tests_pure|i18n|lib|__pycache__)/", rel):
            continue
        try:
            if path.suffix == ".py":
                found = scan_python(path.read_text(encoding="utf-8"))
            elif path.suffix == ".xml":
                found = scan_xml(path.read_text(encoding="utf-8"))
            elif path.suffix == ".js":
                found = scan_js(path.read_text(encoding="utf-8"))
            else:
                continue
        except (SyntaxError, ET.ParseError) as error:
            report.append((rel, 0, "UNPARSEABLE %s" % error))
            continue
        report.extend((rel, line, text) for line, text in found)
    return report


if __name__ == "__main__":
    remaining = scan_addons(sys.argv[1] if len(sys.argv) > 1 else "addons")
    for rel, line, text in remaining:
        print("%s:%s: %s" % (rel, line, json.dumps(text, ensure_ascii=False)))
    print("TOTAL", len(remaining), file=sys.stderr)
