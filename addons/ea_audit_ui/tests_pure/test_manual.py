"""The user manual built into the application (static/manual): read without Odoo.

Every page of the index in English and in French, every picture and link there, nothing about switched-off
features, no reviewer's CHECK note left, and every bold label of a French page written as the French screens say it.
"""
import json
import os
import re

import pytest

import build_index
import manual_lib

PAGES = {
    (lang, os.path.splitext(os.path.basename(path))[0]): manual_lib.read(path)
    for lang in manual_lib.LANGS
    for path in manual_lib.page_files(lang)
}
KEYS = sorted(PAGES)

# Switched off by owner ruling: WhatsApp, document requests and the client portal; and no Odoo branding.
FORBIDDEN = re.compile(
    r"whats\s*app|document requests?|requests? for documents|client documents|portal|portail|"
    r"demandes? de documents|documents du client|powered by odoo",
    re.I,
)

# The owner's list of abbreviations to spell out (as in ea_audit_core/tests_pure/test_display_abbreviations.py).
ABBREVIATIONS = re.compile(
    r"(?<![\w/])(Prelim\.?|Rep\.|FS|vs\.?|SCOTs?|WCGWs?|FSCPs?|ITGCs?|ToCs?|ToDs?|JEs?|EQRs?|TCWG|NOCLAR|SAD|CRAs?|"
    r"PBC|TB|GL|AP|RPs?|KAMs?|HR|IPE|CEO|CFO|PCA|AGO|AGE|AGM|EGM|AUSCGIE|TFT|DSF|CNPS|RCCM|Docs|Ref\.?|Pct|"
    r"Recon|Min\.?|Q[0-9]{1,2})(?![\w/])|PP&E|N/A|n/a"
)

# Bold words of French pages that are on a screen of Odoo itself (sign-in, Preferences), not of the add-ons.
FRENCH_LABEL_EXCEPTIONS = {
    "Actions", "Désarchiver",  # Odoo's own list menu (client list)
    "Changer le mot de passe", "Mettre à jour les préférences",  # Odoo's Preferences window
    "Formation", "Congés", "Administration",  # the firm's internal timesheet projects (ea_audit_timesheet/hooks.py)
    "MSP", "ASP",  # kept names, the same in both languages
    "n/a",  # written as is on the working paper, in both languages
    "ISA 570 révisée 2024",  # a standard's edition (ea_audit_papers/data/standards_refs.json)
}


def test_the_index_is_what_the_pages_say():
    built, errors = build_index.build()
    assert not errors, "\n".join(errors)
    index, search = built
    with open(os.path.join(manual_lib.MANUAL, "index.json"), encoding="utf-8") as handle:
        assert json.load(handle) == index, "run static/manual/tools/build_index.py"
    for lang, words in search.items():
        with open(os.path.join(manual_lib.MANUAL, "search-%s.json" % lang), encoding="utf-8") as handle:
            assert json.load(handle) == words, "run static/manual/tools/build_index.py"


def test_every_index_entry_has_an_english_and_a_french_page():
    with open(os.path.join(manual_lib.MANUAL, "index.json"), encoding="utf-8") as handle:
        index = json.load(handle)
    assert len(index["pages"]) >= 45
    assert [part["key"] for part in index["parts"]] == [str(n) for n in range(1, len(index["parts"]) + 1)]
    for page in index["pages"]:
        for lang in manual_lib.LANGS:
            assert (lang, page["id"]) in PAGES, "%s/%s.html is missing" % (lang, page["id"])
            assert page["title"][lang]
    assert {name for _lang, name in KEYS} == {page["id"] for page in index["pages"]}


def test_a_screen_leads_to_one_page_only():
    owners = {}
    for (lang, name), text in PAGES.items():
        if lang == "en":
            for key in manual_lib.page_meta(text)["screens"]:
                owners.setdefault(key, []).append(name)
    shared = {key: names for key, names in owners.items() if len(names) > 1}
    assert not shared, shared


@pytest.mark.parametrize("lang,name", KEYS)
def test_no_switched_off_feature_is_mentioned(lang, name):
    found = FORBIDDEN.findall(manual_lib.plain(PAGES[lang, name]) + " " + PAGES[lang, name])
    assert not found, found


@pytest.mark.parametrize("lang,name", KEYS)
def test_no_check_comment_is_left(lang, name):
    assert "<!--" not in PAGES[lang, name]
    assert "CHECK" not in PAGES[lang, name]


@pytest.mark.parametrize("lang,name", KEYS)
def test_every_picture_exists(lang, name):
    for src in manual_lib.images(PAGES[lang, name]):
        assert src.startswith(manual_lib.IMG_PREFIX), src
        assert os.path.isfile(os.path.join(manual_lib.MANUAL, "img", src[len(manual_lib.IMG_PREFIX):])), src


@pytest.mark.parametrize("lang,name", KEYS)
def test_every_link_opens_a_page(lang, name):
    for target in manual_lib.links(PAGES[lang, name]):
        assert (lang, target) in PAGES, target


@pytest.mark.parametrize("lang,name", KEYS)
def test_a_page_says_what_the_screen_is_for_then_who(lang, name):
    who = "Who:" if lang == "en" else "Qui :"
    head = re.search(r"</h1>\s*<p class=\"lead\">(.*?)</p>\s*<p class=\"who\"><b>([^<]*)</b>(.*?)</p>", PAGES[lang, name], re.S)
    assert head, "the page must open with a lead line, then the Who line"
    assert head.group(2).replace(" ", " ").strip() == who
    # no ISA citation at the top of a page
    assert not re.search(r"\bISA\s*\d", head.group(1) + head.group(3))


@pytest.mark.parametrize("lang,name", KEYS)
def test_wording(lang, name):
    text = manual_lib.plain(PAGES[lang, name])
    assert not re.search(r"\bQ\d{1,2}\b", text), "write question 11, not Q11"
    assert "only two people" not in text.lower()
    # The glossary quotes the French screens (SCOT, EQR); "n/a" in bold is the working paper's own word.
    if lang == "en" and name != "glossary":
        found = sorted({m.group(0) for m in ABBREVIATIONS.finditer(manual_lib.plain(PAGES[lang, name].replace("<b>n/a</b>", "")))})
        assert not found, found


FRENCH_SCREEN_TEXT = manual_lib.known_texts(fr for _en, fr in manual_lib.ui_pairs())


@pytest.mark.parametrize("name", sorted(name for lang, name in KEYS if lang == "fr"))
def test_french_bold_labels_are_the_screens_words(name):
    missing = [
        label for label in manual_lib.bold_labels(PAGES["fr", name])
        if not manual_lib.label_known(label, FRENCH_SCREEN_TEXT) and label not in FRENCH_LABEL_EXCEPTIONS
    ]
    assert not missing, missing


def test_the_label_check_catches_a_made_up_label():
    assert manual_lib.label_known("Fiche de la mission", FRENCH_SCREEN_TEXT)
    assert not manual_lib.label_known("Bouton inventé pour le test", FRENCH_SCREEN_TEXT)
    assert manual_lib.bold_labels('<div class="tip"><b>Astuce</b> Cliquez sur <b>Lever</b>.</div>') == ["Lever"]
    assert manual_lib.bold_labels('<p class="who"><b>Qui :</b> tout le monde.</p>') == []


def test_the_manual_screen_has_its_french():
    """Every word of the manual's screen and of the "? Help" button has a French msgstr in fr.po."""
    from xml.etree import ElementTree

    addon = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    terms = set()
    for node in ElementTree.parse(os.path.join(addon, "static", "src", "xml", "help.xml")).getroot().iter():
        for text in (node.text, node.tail):
            if re.search(r"[A-Za-z]", text or ""):
                terms.add(text.strip())
        terms.update(node.attrib[a].strip() for a in ("placeholder", "title", "label", "aria-label", "alt") if a in node.attrib)
    for name in ("help.js", "top_bar.js"):
        with open(os.path.join(addon, "static", "src", "js", name), encoding="utf-8") as handle:
            terms.update(re.findall(r'_t\(\s*"((?:[^"\\]|\\.)*)"', handle.read()))
    terms |= {"Help", "Help on this page"}
    french = dict(manual_lib.po_entries(os.path.join(addon, "i18n", "fr.po")))
    missing = sorted(term for term in terms if not french.get(term))
    assert not missing, missing


def test_every_picture_shipped_is_shown():
    used = {src.rsplit("/", 1)[-1] for text in PAGES.values() for src in manual_lib.images(text)}
    shipped = set(os.listdir(os.path.join(manual_lib.MANUAL, "img")))
    assert not shipped - used, sorted(shipped - used)
