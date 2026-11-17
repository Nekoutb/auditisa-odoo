"""What the build script, the label finder and the pure tests share about the user manual.

Standard library only: the pure tests run without Odoo.

A help page is one file, en/<id>.html and fr/<id>.html, holding one <article> whose attributes
carry its place in the contents:

    <article class="ea-help-page" data-id="materiality" data-part="..." data-part-order="5"
             data-order="5.03" data-screens="view:ea_audit_tools.view_engagement_materiality_board">

data-screens (English page only) lists the screens the page explains, as the "? Help" button of
the top bar names them: an action's XML id, "tag:<client action tag>", "view:<board view XML id>",
"dataset:<kind>", "model:<model>" or "model:<model>:<view type>".
"""
import csv
import glob
import html
import json
import os
import re
from html.parser import HTMLParser

MANUAL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDONS = os.path.dirname(os.path.dirname(os.path.dirname(MANUAL)))
LANGS = ("en", "fr")
IMG_PREFIX = "/ea_audit_ui/static/manual/img/"


# ----------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------

def page_files(lang):
    return sorted(glob.glob(os.path.join(MANUAL, lang, "*.html")))


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def page_meta(text):
    """The article's attributes and its first heading."""
    match = re.search(r"<article\b([^>]*)>", text)
    attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', match.group(1))) if match else {}
    title = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S)
    return {
        "id": attrs.get("data-id"),
        "part": html.unescape(attrs.get("data-part", "")),
        "part_order": attrs.get("data-part-order", ""),
        "order": attrs.get("data-order", ""),
        "screens": [s.strip() for s in attrs.get("data-screens", "").split(",") if s.strip()],
        "title": plain(title.group(1)) if title else "",
    }


def plain(fragment):
    """The words of an HTML fragment, for the search."""
    fragment = re.sub(r"<!--.*?-->", " ", fragment, flags=re.S)
    fragment = re.sub(r"<(script|style)\b.*?</\1>", " ", fragment, flags=re.S)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(fragment)).strip()


def images(text):
    return re.findall(r'<img\b[^>]*\bsrc="([^"]+)"', text)


def links(text):
    return re.findall(r'<a\b[^>]*\bhref="#([^"]+)"', text)


class _Bold(HTMLParser):
    """Every <b> of a page, except the heading of a box (Tip, Good to know, Careful) and of "Who:"."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.found, self.depth, self.buffer = [], [], 0, None
        self.box_first = False

    def handle_starttag(self, tag, attrs):
        classes = (dict(attrs).get("class") or "").split()
        if tag == "div" and {"tip", "note", "warn"} & set(classes):
            self.box_first = True
        if tag == "b":
            if self.box_first:
                self.buffer = None
                self.box_first = False
                self.skip = True
            else:
                self.buffer, self.skip = [], False
            self.depth += 1

    def handle_endtag(self, tag):
        if tag == "b" and self.depth:
            self.depth -= 1
            if self.buffer is not None and not self.skip:
                self.found.append(re.sub(r"\s+", " ", "".join(self.buffer)).strip())
            self.buffer = None

    def handle_data(self, data):
        if self.buffer is not None:
            self.buffer.append(data)


def bold_labels(text):
    text = re.sub(r'<p class="who">\s*<b>[^<]*</b>', '<p class="who">', text)
    parser = _Bold()
    parser.feed(text)
    return [label for label in parser.found if label]


# ----------------------------------------------------------------------
# The application's own words
# ----------------------------------------------------------------------

def po_entries(path):
    """(msgid, msgstr) pairs of a .po file, read without polib."""
    entries, current, field = [], {"msgid": [], "msgstr": []}, None
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().split("\n") + [""]
    for line in lines:
        if line.startswith("msgid "):
            if current["msgid"] or current["msgstr"]:
                entries.append(("".join(current["msgid"]), "".join(current["msgstr"])))
            current, field = {"msgid": [json.loads(line[6:])], "msgstr": []}, "msgid"
        elif line.startswith("msgstr "):
            current["msgstr"], field = [json.loads(line[7:])], "msgstr"
        elif line.startswith('"') and field:
            current[field].append(json.loads(line))
        elif not line.strip():
            field = None
    if current["msgid"] or current["msgstr"]:
        entries.append(("".join(current["msgid"]), "".join(current["msgstr"])))
    return [(msgid, msgstr) for msgid, msgstr in entries if msgid]


def _json_pairs(node, out):
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str):
                if key.endswith("En") and isinstance(node.get(key[:-2] + "Fr"), str):
                    out.append((value, node[key[:-2] + "Fr"]))
                elif key == "en" and isinstance(node.get("fr"), str):
                    out.append((value, node["fr"]))
            else:
                _json_pairs(value, out)
    elif isinstance(node, list):
        for value in node:
            _json_pairs(value, out)


def ui_pairs(addons=ADDONS):
    """(English, French) of every screen text: the msgid/msgstr of each add-on's fr.po, and the
    bilingual data of the working-paper definitions (the other place French screen text lives)."""
    pairs = []
    for path in sorted(glob.glob(os.path.join(addons, "*", "i18n", "fr.po"))):
        pairs += [(msgid, msgstr) for msgid, msgstr in po_entries(path) if msgstr]
    data = glob.glob(os.path.join(addons, "*", "data", "**", "*.json"), recursive=True)
    for path in sorted(data):
        if "shadowed" in path or "legacy" in path:
            continue
        with open(path, encoding="utf-8") as handle:
            try:
                _json_pairs(json.load(handle), pairs)
            except ValueError:
                continue
    for path in sorted(glob.glob(os.path.join(addons, "*", "data", "*.csv"))):
        with open(path, encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                for key, value in row.items():
                    if key and key.endswith("_fr") and value and row.get(key[:-3]):
                        pairs.append((row[key[:-3]], value))
    return pairs


_PLACEHOLDER = re.compile(r"%\([^)]*\)[sd]|%[sd]|\{[^}]*\}|<[^>]+>|\n")


def normalize(text):
    text = html.unescape(text).replace(" ", " ").replace(" ", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip(" :.…→←&#;").strip().casefold()


def known_texts(strings):
    """Every screen text, and each piece of it between placeholders, normalized."""
    known = set()
    for text in strings:
        known.add(normalize(text))
        for piece in _PLACEHOLDER.split(text):
            if piece.strip():
                known.add(normalize(piece))
    known.discard("")
    return known


# Task and paper codes (P6.1, S4.2, C1.1, E3.1), figures and keys are not labels.
NOT_A_LABEL = re.compile(r"^([PSEC]\d+(\.\d+)*( to [PSEC]?\d+(\.\d+)*)?|\d+([.,]\d+)?\s?%?|[A-Z]|Esc|Enter)$")
# The same in French: "P1 à P7", and the keys as a French keyboard names them.
NOT_A_LABEL_FR = re.compile(r"^([PSEC]\d+(\.\d+)* à [PSEC]?\d+(\.\d+)*|Échap|Entrée)$")


def label_known(label, known):
    label = label.strip()
    if NOT_A_LABEL.match(label) or NOT_A_LABEL_FR.match(label):
        return True
    return normalize(label) in known
