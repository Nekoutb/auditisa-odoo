"""The How-to guides: complete steps, every picture in both languages, every text in French."""

from pathlib import Path

import pytest

from .. import howto
from .test_translations import read_po

STATIC = Path(__file__).parents[2] / "static" / "howto"
# Words that are the same in both languages.
SAME_IN_FRENCH = {"Standard", "ORPHAN SERVER", "Supervision"}


@pytest.mark.parametrize("item", howto.GUIDES, ids=lambda item: item["code"])
def test_every_step_has_a_heading_a_picture_and_its_three_parts(item):
    for step in item["steps"]:
        assert step["heading"]
        assert step.get("images"), step["heading"]
        assert step.get("do"), step["heading"]
        assert step.get("why") and step.get("next"), step["heading"]


def test_provision_a_new_firm_has_its_eight_steps_in_order():
    item = howto.guide("new_firm")
    headings = [str(step["heading"]) for step in item["steps"]]
    assert len(headings) == 8
    assert headings[0].startswith("Before you start")
    assert headings[2].startswith("Creating the server")
    assert headings[6] == "If something goes wrong"
    assert headings[7] == "Closing a firm"


@pytest.mark.parametrize("item", howto.GUIDES, ids=lambda item: item["code"])
@pytest.mark.parametrize("folder", howto.LANGUAGE_FOLDERS)
def test_every_picture_exists_in_both_languages(item, folder):
    names = howto.images(item)
    assert len(names) == len(set(names)), "a picture is named twice"
    missing = [name for name in names if not (STATIC / item["code"] / folder / name).is_file()]
    assert missing == []


@pytest.mark.parametrize("item", howto.GUIDES, ids=lambda item: item["code"])
def test_no_picture_is_left_unused(item):
    for folder in howto.LANGUAGE_FOLDERS:
        on_disk = {path.name for path in (STATIC / item["code"] / folder).glob("*.png")}
        assert on_disk == set(howto.images(item)), folder


@pytest.mark.parametrize("item", howto.GUIDES, ids=lambda item: item["code"])
def test_every_text_has_its_french(item):
    po = read_po("ea_platform_admin")
    texts = [str(message.template) for message in howto.messages(item)]
    texts += [str(message.template) for message in howto.LABELS.values()]
    missing = [text for text in texts if not po.get(text)]
    assert missing == []
    untranslated = [text for text in texts if po[text] == text and text not in SAME_IN_FRENCH]
    assert untranslated == []


@pytest.mark.parametrize("item", howto.GUIDES, ids=lambda item: item["code"])
def test_bold_marks_come_in_pairs_in_both_languages(item):
    po = read_po("ea_platform_admin")
    for message in howto.messages(item):
        source = str(message.template)
        assert source.count("**") % 2 == 0, source
        assert po[source].count("**") == source.count("**"), source


def test_the_picture_folder_follows_the_language():
    assert howto.image_folder("fr_FR") == "fr"
    assert howto.image_folder("en_US") == "en"
    assert howto.image_folder(None) == "en"
