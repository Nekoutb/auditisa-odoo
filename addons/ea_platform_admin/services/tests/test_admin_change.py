""""Add / Replace the firm administrator": the console's checks agree with the firm's server's. Pure.

The request goes in the signed heartbeat answer and the result comes back as heartbeat figures. If the two
sides disagreed on a rule, an operator would be told "waiting" for a request the firm drops, or a firm's
heartbeat would be refused whole for a figure the console does not accept.
"""

import json
from datetime import datetime

import pytest

from ea_audit_firm_agent.services import collect as agent_collect
from ea_audit_firm_agent.services import signing as agent_signing

from .. import admin_change, heartbeat
from ..heartbeat import HeartbeatRejected, accept, parse_figures
from ..simulator import healthy_figures

TOKEN = "t" * 64
SLUG = "cabinet-a"
NOW = 1_800_000_000
REF = "0123456789abcdef"
LINK = "https://cabinet-a.auditisa.com/web/signup?db=cabinet_a&token=" + "Ab-_9" * 40


def test_a_good_request_passes():
    assert admin_change.request_errors("Awa Ngono", "Awa@Exemple.cm", "exemple.cm") == []


@pytest.mark.parametrize("name, email, words", [
    ("", "awa@exemple.cm", "name"),
    ("A" * 129, "awa@exemple.cm", "too long"),
    ("Awa\x07", "awa@exemple.cm", "invisible"),
    ("Awa", "pas une adresse", "one email address"),
    ("Awa", "", "one email address"),
    ("Awa", "awa@ailleurs.cm", "allowed email domains (exemple.cm)"),
])
def test_refusals_are_in_plain_words(name, email, words):
    problems = admin_change.request_errors(name, email, "exemple.cm")
    assert problems and words in " ".join(problems)


def test_an_empty_domain_list_allows_every_domain():
    assert admin_change.request_errors("Awa", "awa@ailleurs.cm", "") == []


def test_the_request_is_what_the_firm_s_server_accepts():
    data = admin_change.request(REF, "replace", "  Awa   Ngono ", " AWA@exemple.cm ")
    assert data == {"ref": REF, "action": "replace", "name": "Awa Ngono", "email": "awa@exemple.cm"}
    answer = json.dumps({"admin_request": data}).encode()
    assert agent_collect.parse_desired(answer)["admin_request"] == data


@pytest.mark.parametrize("bad", [
    {"ref": REF, "action": "delete", "name": "Awa", "email": "awa@exemple.cm"},
    {"ref": "x" * 16, "action": "add", "name": "Awa", "email": "awa@exemple.cm"},
    {"ref": REF, "action": "add", "name": "", "email": "awa@exemple.cm"},
    {"ref": REF, "action": "add", "name": "Awa", "email": "awa"},
    {"ref": REF, "action": "add", "name": "Awa", "email": "awa@exemple.cm", "role": "system"},
    {"ref": REF, "action": "add", "name": "Awa\n", "email": "awa@exemple.cm"},
])
def test_both_sides_refuse_the_same_requests(bad):
    assert not admin_change.valid_request(bad)
    assert agent_collect.admin_request(bad) is None
    assert "admin_request" not in agent_collect.parse_desired(json.dumps({"admin_request": bad}).encode())


def test_both_sides_know_the_same_words_and_the_same_link():
    assert admin_change.RESULTS == heartbeat.ADMIN_RESULTS == agent_collect.ADMIN_RESULTS
    assert set(admin_change.RESULTS) | {"none", "waiting"} == {key for key, _label in admin_change.STATES}
    assert set(admin_change.MESSAGES) == {key for key, _label in admin_change.STATES} - {"done"}
    assert admin_change.LINK.pattern == agent_collect.ADMIN_LINK.pattern
    assert admin_change.ACTIONS == agent_collect.ADMIN_ACTIONS


def _figures(**changes):
    data = healthy_figures(datetime(2026, 11, 18, 12), "abcdef123456")
    data.update(changes)
    return data


def test_the_answer_is_accepted_as_figures():
    data = parse_figures(json.dumps(_figures(
        admin_request_ref=REF, admin_request_result="done", admin_request_link=LINK)).encode())
    assert data["admin_request_link"] == LINK


@pytest.mark.parametrize("link", [
    "http://cabinet-a.auditisa.com/web/signup?token=abc",
    "https://cabinet-a.auditisa.com/web/login?token=abc",
    "https://cabinet-a.auditisa.com/web/signup?token=Rapport d'audit",
    "Rapport d'audit de la societe Agro SA",
])
def test_a_link_of_another_shape_is_refused(link):
    with pytest.raises(HeartbeatRejected):
        parse_figures(json.dumps(_figures(admin_request_ref=REF, admin_request_result="done",
                                          admin_request_link=link)).encode())
    assert agent_collect.admin_figures({"ref": REF, "result": "done", "link": link}) == {
        "admin_request_ref": REF, "admin_request_result": "done"}


def test_what_the_agent_builds_is_what_the_receiver_accepts():
    body = agent_signing.encode(agent_collect.build_figures(
        {"release": "abcdef1"}, {"mem_total_mb": 8000, "mem_available_mb": 4000},
        {"disk_total_gb": 80, "disk_used_pct": 10}, 5, 2, False,
        admin_answer={"ref": REF, "result": "done", "link": LINK},
    ))
    headers = {
        heartbeat.HEADER_FIRM: SLUG,
        heartbeat.HEADER_TIMESTAMP: str(NOW),
        heartbeat.HEADER_SIGNATURE: agent_signing.sign(TOKEN, SLUG, NOW, body),
    }
    figures = accept(headers, body, lambda slug: (TOKEN, 0), NOW)[2]
    assert (figures["admin_request_ref"], figures["admin_request_result"]) == (REF, "done")
    assert figures["admin_request_link"] == LINK


def test_a_refusal_carries_no_link():
    assert agent_collect.admin_figures({"ref": REF, "result": "domain", "link": LINK}) == {
        "admin_request_ref": REF, "admin_request_result": "domain"}
    assert agent_collect.admin_figures(None) == {}
    assert agent_collect.admin_figures({"ref": REF, "result": "Rapport", "link": None}) == {}


def test_a_heartbeat_with_the_link_and_many_errors_still_fits():
    errors = [{"module": "ea_audit_papers", "model": "ea.audit.file.item", "kind": "ValidationError",
               "count": 99999, "last_at": "2026-11-18T12:00:00Z"}] * heartbeat.MAX_ERROR_GROUPS
    body = agent_signing.encode(_figures(
        admin_request_ref=REF, admin_request_result="done", admin_request_link=LINK,
        mail_request_ref=REF, mail_request_result="on", errors=errors,
        addons_on=["ea_client_addon_%02d" % number for number in range(8)],
    ))
    assert len(body) <= heartbeat.MAX_BODY_BYTES
