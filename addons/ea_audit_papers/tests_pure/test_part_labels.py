"""F084: a paper's part tabs. The labels are built in paper_action.js; this holds its rule to the
real definitions, so no paper shows the same short name on two tabs."""
import json
import pathlib
import re

ADDON = pathlib.Path(__file__).resolve().parent.parent
PART_TITLE = re.compile(r"^(?:Partie|Part)\s+(\S+)\s+—\s+(.*)$")
PAPER_CODE = re.compile(r"^[A-Z]\d+(?:\.\d+)+$")


def part_label(letter, rest):
    words = rest.split()
    if PAPER_CODE.match(words[0]) and len(words) > 2:
        return "%s %s %s" % (letter, words[1], re.sub(r":$", "", words[2]))
    return "%s %s" % (letter, words[0])


def labels(definition, key):
    out = []
    for section in definition.get("sections") or []:
        match = PART_TITLE.match(section.get(key) or "")
        if match:
            out.append(part_label(match.group(1), match.group(2)))
    return out


def test_the_script_holds_the_same_rule():
    script = (ADDON / "static/src/paper/paper_action.js").read_text(encoding="utf-8")
    assert "const label = match ? partLabel(letter, match[2]) : title;" in script
    assert r"const PAPER_CODE = /^[A-Z]\d+(?:\.\d+)+$/;" in script


def test_e6_10_checklist_tabs_read_apart():
    definition = json.loads((ADDON / "data/papers/E6.10.json").read_text(encoding="utf-8"))["definition"]
    assert labels(definition, "titleEn")[-6:] == [
        "G Checklist A", "G Checklist B", "G Checklist C", "G Checklist D", "G Checklist E", "G Checklist F",
    ]
    assert labels(definition, "titleFr")[-6:] == [
        "G Questionnaire A", "G Questionnaire B", "G Questionnaire C", "G Questionnaire D", "G Questionnaire E", "G Questionnaire F",
    ]


def test_no_paper_repeats_a_tab():
    repeated = {}
    for path in (ADDON / "data/papers").glob("*.json"):
        definition = json.loads(path.read_text(encoding="utf-8")).get("definition") or {}
        for key in ("titleEn", "titleFr"):
            names = labels(definition, key)
            if len(names) != len(set(names)):
                repeated[path.stem] = names
    assert not repeated
