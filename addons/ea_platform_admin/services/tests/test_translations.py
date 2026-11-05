"""Every screen and message works in English and French: English in the source, French in fr.po."""

import ast
import re
from pathlib import Path

import pytest

ADDONS = Path(__file__).parents[3]
BOTH = ["ea_platform_admin", "ea_audit_firm_agent"]


def read_po(addon):
    """{msgid: msgstr}, by hand so these tests need nothing but the standard library."""
    entries, msgid, msgstr, into = {}, None, None, None
    for line in (ADDONS / addon / "i18n" / "fr.po").read_text(encoding="utf-8").splitlines():
        if line.startswith("msgid "):
            if msgid:
                entries[msgid] = msgstr
            msgid, msgstr, into = ast.literal_eval(line[6:]), "", "id"
        elif line.startswith("msgstr "):
            msgstr, into = ast.literal_eval(line[7:]), "str"
        elif line.startswith('"'):
            if into == "id":
                msgid += ast.literal_eval(line)
            elif into == "str":
                msgstr += ast.literal_eval(line)
    if msgid:
        entries[msgid] = msgstr
    return entries


def sources(addon):
    for path in (ADDONS / addon).rglob("*"):
        if path.suffix in (".py", ".xml") and "tests" not in path.parts:
            yield path


def underscore_literals(addon):
    """Every string given to `_()` or `env._()` in the addon's code."""
    for path in sources(addon):
        if path.suffix != ".py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            if name == "_" and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                yield path.name, node.args[0].value


@pytest.mark.parametrize("addon", BOTH)
def test_every_entry_has_its_french(addon):
    empty = [msgid for msgid, msgstr in read_po(addon).items() if not msgstr]
    assert empty == []


@pytest.mark.parametrize("addon", BOTH)
def test_french_keeps_every_placeholder(addon):
    for msgid, msgstr in read_po(addon).items():
        assert sorted(re.findall(r"%\(\w+\)s", msgid)) == sorted(re.findall(r"%\(\w+\)s", msgstr)), msgid


@pytest.mark.parametrize("addon", BOTH)
def test_every_message_in_the_code_is_in_fr_po(addon):
    known = read_po(addon)
    missing = [(name, text) for name, text in underscore_literals(addon) if text not in known]
    assert missing == []


@pytest.mark.parametrize("addon", BOTH)
def test_no_french_is_hard_coded(addon):
    """English sources are ASCII, and every accented letter belongs in fr.po."""
    wrong = []
    for path in sources(addon):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"[À-ÿ«»]", line):
                wrong.append(f"{path.name}:{number}")
    assert wrong == []


def test_french_really_is_french():
    entries = read_po("ea_platform_admin")
    assert entries["Needs attention"] == "À surveiller"
    assert entries["The last backup failed"] == "La dernière sauvegarde a échoué"
    agent = read_po("ea_audit_firm_agent")
    assert agent["Welcome"] == "Bienvenue"
