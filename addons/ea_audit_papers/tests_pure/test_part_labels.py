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


def test_the_page_has_no_tabs_and_names_a_block_by_its_full_title():
    # The layout of 2026-11-17 is one page: a block of an older paper is listed in the steps under
    # its whole title, so the short tab names below only have to stay apart as headings.
    script = (ADDON / "static/src/paper/paper_action.js").read_text(encoding="utf-8")
    assert "partLabel" not in script
    assert "short: title, title," in script


def test_e6_10_checklist_groups_read_apart():
    # E6.10's checklist is a set of folding groups inside its task (layout of 2026-11-17): each group
    # is named by its own letter, in both languages.
    definition = json.loads((ADDON / "data/papers/E6.10.json").read_text(encoding="utf-8"))["definition"]
    groups = [section for section in definition["sections"] if section.get("task") == "checklist"]
    for key, word in (("titleEn", "Checklist"), ("titleFr", "Questionnaire")):
        names = [section[key].split(" — ")[0] for section in groups]
        assert all(name.startswith(word + " ") for name in names)
        assert len(names) == len(set(names)) == 12


def test_no_paper_repeats_a_tab():
    repeated = {}
    for path in (ADDON / "data/papers").glob("*.json"):
        definition = json.loads(path.read_text(encoding="utf-8")).get("definition") or {}
        for key in ("titleEn", "titleFr"):
            names = labels(definition, key)
            if len(names) != len(set(names)):
                repeated[path.stem] = names
    assert not repeated
