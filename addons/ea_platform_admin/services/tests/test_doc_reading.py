"""Document reading (owner, 2026-11-20): the console and the firm's agent speak the same words, and what the
agent reports is accepted by the console's heartbeat."""

import json
from datetime import datetime

from ea_audit_firm_agent.services import collect as agent_collect

from .. import heartbeat, mail_handoff
from ..heartbeat import parse_figures
from ..simulator import healthy_figures

REF = "0123456789abcdef"
KEY = "sk-ant-api03-Cabinet-Key-For-Reading-7f3aQx9Z"


def test_both_sides_know_the_same_words():
    assert heartbeat.DOC_READING_RESULTS == agent_collect.DOC_RESULTS


def test_what_the_agent_reports_the_console_accepts():
    figures = agent_collect.doc_reading_figures(
        {"ref": REF, "result": "on", "last4": KEY[-4:], "month": "2026-11", "documents": 4, "pages": 19})
    assert figures == {"doc_reading_ref": REF, "doc_reading_result": "on", "doc_reading_last4": "Qx9Z",
                       "doc_reading_month": "2026-11", "doc_reading_documents": 4, "doc_reading_pages": 19}
    body = json.dumps({**healthy_figures(datetime(2026, 11, 21, 12), "abcdef123456"), **figures}).encode()
    assert parse_figures(body)["doc_reading_result"] == "on"


def test_nothing_is_reported_before_a_first_request():
    assert agent_collect.doc_reading_figures(None) == {}
    assert agent_collect.doc_reading_figures({"ref": REF, "result": "great"}) == {}


def test_the_agent_takes_only_well_formed_requests():
    assert agent_collect.doc_reading_request({"ref": REF, "action": "set", "key": KEY}) == {"ref": REF, "action": "set", "key": KEY}
    assert agent_collect.doc_reading_request({"ref": REF, "action": "test"}) == {"ref": REF, "action": "test"}
    for bad in (
        {"ref": REF, "action": "set", "key": "short"},
        {"ref": REF, "action": "set", "key": KEY + " "},
        {"ref": REF, "action": "test", "key": KEY},
        {"ref": "XYZ", "action": "remove"},
    ):
        assert agent_collect.doc_reading_request(bad) is None
        assert "doc_reading_request" not in agent_collect.parse_desired(json.dumps({"doc_reading_request": bad}).encode())


def test_the_waiting_key_has_a_file_name_of_its_own():
    assert mail_handoff.reading_name("cabinet-a") == "reading-cabinet-a"
    assert mail_handoff.path("/x", "reading-cabinet-a").endswith("reading-cabinet-a")
