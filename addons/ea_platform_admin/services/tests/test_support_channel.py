import json
from datetime import datetime

import pytest

from ea_audit_firm_agent.services import signing as agent_signing
from ea_platform_admin.services import heartbeat, support
from ea_platform_admin.services.simulator import healthy_figures

NOW = datetime(2026, 11, 7, 12, 0, 0)
ERROR = {"module": "ea_audit_core", "model": "res.partner", "kind": "ValueError", "count": 3, "last_at": "2026-11-07T11:00:00Z"}


def figures(**changes):
    return {**healthy_figures(NOW, "abcdef123456"), **changes}


def parse(**changes):
    return heartbeat.parse_figures(json.dumps(figures(**changes)).encode())


def test_errors_and_the_visit_state_go_in_a_heartbeat():
    assert parse(errors=[ERROR], support_visit={"id": 4, "state": "open"})


@pytest.mark.parametrize("bad", [
    [{**ERROR, "message": "Agro SA"}],
    [{**ERROR, "kind": "Agro SA, awa@agro.cm"}],
    [{**ERROR, "model": "Client Agro"}],
    [{**ERROR, "module": "../etc"}],
    [{**ERROR, "count": 0}],
    [ERROR] * 9,
    "ValueError in ea_audit_core",
])
def test_an_error_with_any_text_rejects_the_heartbeat(bad):
    with pytest.raises(heartbeat.HeartbeatRejected):
        parse(errors=bad)


@pytest.mark.parametrize("bad", [{"id": 4, "state": "waiting"}, {"id": 4}, {"id": "4", "state": "open"}, {"id": 4, "state": "open", "who": "x"}])
def test_a_visit_state_of_another_form_rejects_the_heartbeat(bad):
    with pytest.raises(heartbeat.HeartbeatRejected):
        parse(support_visit=bad)


def test_a_full_heartbeat_still_fits():
    codes = [f"ea_client_{n:02d}_{'x' * 27}" for n in range(24)]
    errors = [{**ERROR, "module": "m" * 40, "model": "a." + "b" * 70, "kind": "K" * 60} for _ in range(8)]
    body = json.dumps(figures(addons_on=codes, addons_refused=1000, errors=errors, support_visit={"id": 10 ** 8, "state": "expired"},
                              export_sha256="a" * 64, update_release="a" * 40, release="a" * 40),
                      sort_keys=True, separators=(",", ":")).encode()
    assert len(body) <= heartbeat.MAX_BODY_BYTES
    assert heartbeat.parse_figures(body)


def test_the_agent_and_the_platform_sign_the_support_channel_alike():
    body = b'{"refs":[]}'
    for prefix_agent, prefix_platform in ((agent_signing.PREFIX_TICKET, support.PREFIX_TICKET),
                                          (agent_signing.PREFIX_SYNC, support.PREFIX_SYNC),
                                          (agent_signing.PREFIX_TRACE, support.PREFIX_TRACE)):
        assert prefix_agent == prefix_platform
        assert agent_signing.sign_kind(prefix_agent, "t" * 64, "cabinet-a", 1, body) == heartbeat.sign_kind(prefix_platform, "t" * 64, "cabinet-a", 1, body)
    assert heartbeat.sign_kind(support.PREFIX_TICKET, "t" * 64, "cabinet-a", 1, body) != heartbeat.sign("t" * 64, "cabinet-a", 1, body)


def ticket(**changes):
    return json.dumps({"ref": "a" * 32, "subject": "S", "message": "M", "screen": "", **changes}).encode()


def test_a_good_ticket_reads_back():
    assert support.parse_ticket(ticket())["subject"] == "S"


@pytest.mark.parametrize("raw", [
    ticket(ref="x"), ticket(subject=""), ticket(subject="s" * 201), ticket(message="m" * 4001), ticket(screen="Agro SA"),
    json.dumps({"ref": "a" * 32, "subject": "S", "message": "M", "screen": "", "user": "awa@agro.cm"}).encode(),
    b"not json", b"x" * 20000,
])
def test_a_bad_ticket_is_refused(raw):
    with pytest.raises(heartbeat.HeartbeatRejected):
        support.parse_ticket(raw)


def trace(**changes):
    entry = {"at": "2026-11-07T11:00:00Z", "model": "res.partner", "method": "form", "ids": [4, 5]}
    return json.dumps({"visit": 3, "release": "abcdef1", "entries": [entry], **changes}).encode()


def test_a_trail_holds_identifiers_only():
    assert support.parse_trace(trace())["entries"][0]["ids"] == [4, 5]
    for bad in (
        trace(entries=[{"at": "2026-11-07T11:00:00Z", "model": "res.partner", "method": "form", "ids": [4], "name": "Agro"}]),
        trace(entries=[{"at": "2026-11-07T11:00:00Z", "model": "Agro SA", "method": "form", "ids": [4]}]),
        trace(entries=[{"at": "2026-11-07T11:00:00Z", "model": "res.partner", "method": "write", "ids": [4]}]),
        trace(entries=[{"at": "2026-11-07T11:00:00Z", "model": "res.partner", "method": "form", "ids": ["Agro"]}]),
        trace(entries=[]), trace(visit=0), trace(release="Agro"),
    ):
        with pytest.raises(heartbeat.HeartbeatRejected):
            support.parse_trace(bad)
