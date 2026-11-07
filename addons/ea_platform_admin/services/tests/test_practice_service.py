import json
import pathlib
import sys
from datetime import datetime, timedelta

import pytest

from .. import practice
from ..heartbeat import HeartbeatRejected

# The practice computer's own sender, which ships with deploy/practice and not with this addon.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "deploy" / "practice"))
import practice_heartbeat as sender  # noqa: E402

TOKEN = "k" * 64
NOW = 1_800_000_000


def figures(**changes):
    data = sender.build_figures("practice-1", "abcdef123456", "abcdef123456", "ok", [
        sender.space_figures("cabinet-a", True, "2026-11-07T10:00:00Z", 6, "2026-11-06", 2, ["ea_client_addon_sample"], True),
    ])
    data.update(changes)
    return data


def request(data, timestamp=NOW, token=TOKEN):
    body = sender.encode(data)
    return {
        practice.HEADER_COMPUTER: "practice-1", practice.HEADER_TIMESTAMP: str(timestamp),
        practice.HEADER_SIGNATURE: sender.sign(token, "practice-1", timestamp, body),
    }, body


def find(name):
    return (TOKEN, 0) if name == "practice-1" else None


def code(headers, body, finder=find):
    with pytest.raises(HeartbeatRejected) as caught:
        practice.accept(headers, body, finder, NOW)
    return caught.value.code


def test_the_sender_and_the_receiver_agree():
    name, timestamp, data = practice.accept(*request(figures()), find, NOW)
    assert (name, timestamp) == ("practice-1", NOW)
    assert data["spaces"][0]["reset_generation"] == 2


def test_the_response_signature_matches_the_senders_check():
    body = b'{"ok":true}'
    assert sender.response_is_authentic(TOKEN, "practice-1", NOW, body, practice.sign_response(TOKEN, "practice-1", NOW, body))


@pytest.mark.parametrize("change, expected", [
    ({"client": "Agro SA"}, "unknown_key"),
    ({"guard": "maybe"}, "bad_value"),
    ({"release": "Release of Agro SA"}, "bad_value"),
])
def test_anything_but_figures_is_refused(change, expected):
    assert code(*request(figures(**change))) == expected


def test_a_space_with_text_or_a_name_is_refused():
    data = figures()
    data["spaces"][0]["firm"] = "Cabinet Akwa"
    assert code(*request(data)) == "bad_space"
    data = figures()
    data["spaces"][0]["last_login_on"] = "jp.mbarga@cabinet-demo.example"
    assert code(*request(data)) == "bad_value"
    data = figures()
    data["spaces"].append(dict(data["spaces"][0]))
    assert code(*request(data)) == "duplicate_space"


def test_signature_freshness_and_identity():
    headers, body = request(figures(), token="x" * 64)
    assert code(headers, body) == "bad_signature"
    assert code(*request(figures(), timestamp=NOW - 3600)) == "stale_timestamp"
    assert code(*request(figures()), finder=lambda name: (TOKEN, NOW)) == "replayed_timestamp"
    headers, body = request(figures())
    headers[practice.HEADER_COMPUTER] = "Practice 1"
    assert code(headers, body) == "bad_computer_header"
    assert code(*request(figures()), finder=lambda name: None) == "unknown_computer"


def test_a_firm_heartbeat_signature_does_not_pass():
    from ..heartbeat import sign as firm_sign
    body = sender.encode(figures())
    headers = {practice.HEADER_COMPUTER: "practice-1", practice.HEADER_TIMESTAMP: str(NOW),
               practice.HEADER_SIGNATURE: firm_sign(TOKEN, "practice-1", NOW, body)}
    assert code(headers, body) == "bad_signature"


def test_the_body_is_capped():
    headers, body = request(figures())
    assert code(headers, body + b" " * practice.MAX_BODY_BYTES) == "body_too_large"


def test_the_space_request_is_closed():
    item = practice.space_request("cabinet-a", "Cabinet A\n(demo)", "awa@exemple.cm", "fr_FR",
                                  ["ea_client_addon_sample", "Bad name"], 3, "a" * 64, datetime(2026, 11, 10, 9))
    assert item["addons"] == ["ea_client_addon_sample"]
    assert item["first_admin_expires"] == "2026-11-10T09:00:00Z"
    assert "\n" not in __import__("base64").b64decode(item["name_b64"]).decode()
    assert practice.space_request("Bad Slug", "x", "a@b.c", "fr_FR", [], 0) is None
    assert practice.space_request("cabinet-a", "x", "a b", "fr_FR", [], 0) is None
    assert practice.space_request("cabinet-a", "x", "a@b.c", "de_DE", [], 0)["lang"] == "fr_FR"
    assert "first_admin_hash" not in practice.space_request("cabinet-a", "x", "a@b.c", "fr_FR", [], 0)


def test_hold_status():
    now = datetime(2026, 11, 20, 12)
    ok, until, _message = practice.hold_status(None, 7, now)
    assert not ok and until is None
    ok, until, _message = practice.hold_status(now - timedelta(days=6), 7, now)
    assert not ok and until == now + timedelta(days=1)
    ok, _until, _message = practice.hold_status(now - timedelta(days=7), 7, now)
    assert ok
    ok, _until, message = practice.hold_status(None, 0, now)
    assert ok and "waived" in message
    assert practice.hold_status(now - timedelta(days=2), None, now)[0] is False  # 7 by default


def test_json_of_the_answer_is_plain():
    assert json.loads(json.dumps(practice.space_request("cabinet-a", "A", "a@b.c", "en_US", [], 0)))["lang"] == "en_US"
