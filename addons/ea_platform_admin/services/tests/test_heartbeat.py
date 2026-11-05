import json
from datetime import datetime

import pytest

from ea_audit_firm_agent.services import collect as agent_collect
from ea_audit_firm_agent.services import signing as agent_signing

from .. import heartbeat
from ..heartbeat import HeartbeatRejected, accept, parse_figures, parse_headers
from ..simulator import healthy_figures, signed_request

TOKEN = "t" * 64
SLUG = "cabinet-a"
NOW = 1_800_000_000
INSTANT = datetime(2026, 11, 5, 12)


def figures(**changes):
    data = healthy_figures(INSTANT, "abcdef123456")
    data.update(changes)
    return data


def find(slug):
    return (TOKEN, 0) if slug == SLUG else None


def code_of(call):
    with pytest.raises(HeartbeatRejected) as caught:
        call()
    return caught.value.code


def test_a_good_heartbeat_is_accepted():
    headers, body = signed_request(TOKEN, SLUG, NOW, figures())
    slug, timestamp, data = accept(headers, body, find, NOW)
    assert (slug, timestamp) == (SLUG, NOW)
    assert data["release"] == "abcdef123456"


def test_agent_and_receiver_sign_the_same_way():
    body = agent_signing.encode(figures())
    assert agent_signing.sign(TOKEN, SLUG, NOW, body) == heartbeat.sign(TOKEN, SLUG, NOW, body)
    answer = b'{"ok":true}'
    assert agent_signing.response_is_authentic(TOKEN, SLUG, NOW, answer, heartbeat.sign_response(TOKEN, SLUG, NOW, answer))
    assert agent_signing.HEADER_SIGNATURE == heartbeat.HEADER_SIGNATURE
    assert agent_signing.HEADER_FIRM == heartbeat.HEADER_FIRM
    assert agent_signing.HEADER_TIMESTAMP == heartbeat.HEADER_TIMESTAMP
    assert agent_signing.HEADER_RESPONSE_SIGNATURE == heartbeat.HEADER_RESPONSE_SIGNATURE


def test_what_the_agent_builds_is_what_the_receiver_accepts():
    status = {"release": "abcdef1", "last_backup_at": "2026-11-05T02:30:00Z", "last_backup_ok": True}
    body = agent_signing.encode(agent_collect.build_figures(
        status, {"mem_total_mb": 8000, "mem_available_mb": 4000},
        {"disk_total_gb": 80, "disk_used_pct": 10}, 5, 2, False,
    ))
    headers = {
        heartbeat.HEADER_FIRM: SLUG,
        heartbeat.HEADER_TIMESTAMP: str(NOW),
        heartbeat.HEADER_SIGNATURE: agent_signing.sign(TOKEN, SLUG, NOW, body),
    }
    assert accept(headers, body, find, NOW)[2]["users_active"] == 5


def test_every_figure_the_agent_may_read_is_known_to_the_receiver():
    assert set(agent_collect.STATUS_FILES) <= set(heartbeat.FIGURES)


def test_unknown_firm_is_rejected():
    headers, body = signed_request(TOKEN, "cabinet-z", NOW, figures())
    assert code_of(lambda: accept(headers, body, find, NOW)) == "unknown_firm"


def test_a_firm_without_token_is_rejected():
    headers, body = signed_request(TOKEN, SLUG, NOW, figures())
    assert code_of(lambda: accept(headers, body, lambda s: ("", 0), NOW)) == "unknown_firm"


def test_wrong_token_is_rejected():
    headers, body = signed_request("x" * 64, SLUG, NOW, figures())
    assert code_of(lambda: accept(headers, body, find, NOW)) == "bad_signature"


def test_another_firms_token_is_rejected():
    tokens = {"cabinet-a": "a" * 64, "cabinet-b": "b" * 64}
    headers, body = signed_request(tokens["cabinet-b"], "cabinet-a", NOW, figures())
    assert code_of(lambda: accept(headers, body, lambda s: (tokens[s], 0), NOW)) == "bad_signature"


def test_changing_a_figure_breaks_the_signature():
    headers, body = signed_request(TOKEN, SLUG, NOW, figures())
    tampered = body.replace(b'"users_active":1', b'"users_active":9')
    assert tampered != body
    assert code_of(lambda: accept(headers, tampered, find, NOW)) == "bad_signature"


def test_old_timestamp_is_rejected():
    headers, body = signed_request(TOKEN, SLUG, NOW - 301, figures())
    assert code_of(lambda: accept(headers, body, find, NOW)) == "stale_timestamp"


def test_future_timestamp_is_rejected():
    headers, body = signed_request(TOKEN, SLUG, NOW + 301, figures())
    assert code_of(lambda: accept(headers, body, find, NOW)) == "stale_timestamp"


def test_replay_is_rejected():
    headers, body = signed_request(TOKEN, SLUG, NOW, figures())
    assert code_of(lambda: accept(headers, body, lambda s: (TOKEN, NOW), NOW)) == "replayed_timestamp"


@pytest.mark.parametrize("extra", [
    {"client_name": "Agro SA"},
    {"note": "x"},
    {"engagements": [{"id": 1, "client": "Agro"}]},
    {"users": ["a@b.c"]},
    {"trial_balance": 1},
])
def test_anything_beyond_the_listed_figures_is_rejected(extra):
    headers, body = signed_request(TOKEN, SLUG, NOW, figures(**extra))
    assert code_of(lambda: accept(headers, body, find, NOW)) == "unknown_key"


@pytest.mark.parametrize("key,value", [
    ("release", "Agro SA - exercice 2025"),
    ("release", "not-hex"),
    ("odoo_version", "dix-neuf"),
    ("disk_used_pct", 101),
    ("disk_used_pct", -1),
    ("disk_used_pct", "12"),
    ("disk_used_pct", 12.5),
    ("disk_used_pct", True),
    ("users_active", {"a": 1}),
    ("users_active", ["x"]),
    ("last_backup_at", "hier"),
    ("last_backup_at", "2026-11-05"),
    ("last_backup_ok", 1),
    ("last_backup_ok", "oui"),
    ("cert_expires_on", "2026-13-45"),
    ("update_state", "Agro SA"),
    ("export_state", "fini"),
    ("export_sha256", "abc"),
    ("mail_enabled", None),
    ("schema", 2),
    ("schema", 1.0),
    ("schema", True),
])
def test_values_are_checked_one_by_one(key, value):
    headers, body = signed_request(TOKEN, SLUG, NOW, figures(**{key: value}))
    assert code_of(lambda: accept(headers, body, find, NOW)) == "bad_value"


def test_no_figure_is_free_text():
    """Whatever the key, a sentence never passes: no field can carry a client's name."""
    for key, check in heartbeat.FIGURES.items():
        assert not check("Société Agro SA, client du cabinet"), key
        assert not check("x" * 500), key


def test_missing_figure_is_rejected():
    data = figures()
    del data["release"]
    headers, body = signed_request(TOKEN, SLUG, NOW, data)
    assert code_of(lambda: accept(headers, body, find, NOW)) == "missing_key"


def test_oversize_body_is_rejected_before_any_lookup():
    body = b"{" + b" " * heartbeat.MAX_BODY_BYTES + b"}"
    headers = {
        heartbeat.HEADER_FIRM: SLUG,
        heartbeat.HEADER_TIMESTAMP: str(NOW),
        heartbeat.HEADER_SIGNATURE: heartbeat.sign(TOKEN, SLUG, NOW, body),
    }

    def must_not_run(slug):
        raise AssertionError("looked up")

    assert code_of(lambda: accept(headers, body, must_not_run, NOW)) == "body_too_large"


def test_duplicate_keys_are_rejected():
    assert code_of(lambda: parse_figures(b'{"schema":1,"schema":1}')) == "duplicate_key"


@pytest.mark.parametrize("body,code", [
    (b"not json", "not_json"),
    (b"\xff\xfe", "not_json"),
    (b"[1,2]", "not_an_object"),
    (b'"x"', "not_an_object"),
])
def test_non_objects_are_rejected(body, code):
    assert code_of(lambda: parse_figures(body)) == code


@pytest.mark.parametrize("change,code", [
    ({heartbeat.HEADER_FIRM: ""}, "bad_firm_header"),
    ({heartbeat.HEADER_FIRM: "../../etc"}, "bad_firm_header"),
    ({heartbeat.HEADER_TIMESTAMP: "soon"}, "bad_timestamp_header"),
    ({heartbeat.HEADER_TIMESTAMP: "١٢٣"}, "bad_timestamp_header"),
    ({heartbeat.HEADER_SIGNATURE: "abc"}, "bad_signature_header"),
])
def test_bad_headers_are_rejected(change, code):
    headers, _body = signed_request(TOKEN, SLUG, NOW, figures())
    headers.update(change)
    assert code_of(lambda: parse_headers(headers)) == code


def test_signature_is_checked_before_the_body_is_read():
    """A caller without the token learns nothing about which keys are accepted."""
    body = json.dumps({"client_name": "x"}).encode()
    headers = {
        heartbeat.HEADER_FIRM: SLUG,
        heartbeat.HEADER_TIMESTAMP: str(NOW),
        heartbeat.HEADER_SIGNATURE: "0" * 64,
    }
    assert code_of(lambda: accept(headers, body, find, NOW)) == "bad_signature"


def test_instants_round_trip():
    assert heartbeat.parse_instant(heartbeat.format_instant(INSTANT)) == INSTANT
    assert heartbeat.parse_instant(None) is None
