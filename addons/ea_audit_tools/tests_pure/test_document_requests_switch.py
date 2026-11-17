"""Owner ruling 2026-11-17: document requests are switched off for now. The switch reads as off
unless it says on, every screen entry point carries it, and the client's pages check it."""
import pathlib
import re

from xml.etree import ElementTree as etree

from services.document_requests import PARAM, reads_as_on

ADDONS = pathlib.Path(__file__).resolve().parents[2]
PORTAL = ADDONS / "ea_audit_portal"


def test_off_unless_it_says_on():
    assert PARAM == "ea_audit_portal.document_requests"
    for value in (None, "", "False", "false", "0", "no", "off", "nonsense"):
        assert not reads_as_on(value), value
    for value in ("True", "true", "1", " yes ", "ON"):
        assert reads_as_on(value), value


def test_the_shipped_default_is_off():
    record = etree.parse(str(ADDONS / "ea_audit_tools" / "data" / "document_requests.xml")).getroot()
    assert record.get("noupdate") == "1"
    assert record.findtext(".//field[@name='key']") == PARAM
    assert not reads_as_on(record.findtext(".//field[@name='value']"))


def test_every_button_on_the_engagement_and_the_client_carries_the_switch():
    views = etree.parse(str(PORTAL / "views" / "pbc_views.xml")).getroot()
    for name in ("action_view_pbc", "action_open_pbc_request"):
        (button,) = views.findall(".//record[@id='view_engagement_form_pbc_button']//button[@name='%s']" % name)
        assert "not document_requests_enabled" in button.get("invisible", ""), name
    (panel,) = [div for div in views.findall(".//record[@id='view_client_form_portal']//div")
                if div.find("button[@name='action_add_portal_contact']") is not None]
    assert panel.get("invisible") == "not document_requests_enabled"


def test_the_portal_home_card_carries_the_switch():
    templates = etree.parse(str(PORTAL / "views" / "portal_templates.xml")).getroot()
    (entry,) = templates.findall(".//template[@id='portal_my_home_pbc']//t[@t-call='portal.portal_docs_entry']")
    assert entry.get("t-if") == "ea_document_requests"


def test_every_client_page_checks_the_switch():
    source = (PORTAL / "controllers" / "portal.py").read_text(encoding="utf-8")
    handlers = re.findall(r"@http\.route\([^\n]*\n    def (\w+)\([^\n]*\n(?:        \"\"\"[^\n]*\n)?        (\S+)", source)
    assert len(handlers) == 4, handlers
    for name, first in handlers:
        assert first == "_require_switch_on()", name
