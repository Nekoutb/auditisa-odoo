import json
import pathlib
import sys
from datetime import datetime

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


def test_staging_status_takes_only_what_staging_runs_now_with_no_wait():
    sha = "a" * 40
    ok, message = practice.staging_status(sha[:12], sha)
    assert ok and "may go to Production" in message
    ok, message = practice.staging_status(None, sha)
    assert not ok and "not on Staging yet" in message
    ok, message = practice.staging_status("b" * 12, sha)
    assert not ok and "another version (bbbbbbbbbbbb)" in message
    assert not hasattr(practice, "hold_status") and not hasattr(practice, "DEFAULT_HOLD_DAYS")


def test_json_of_the_answer_is_plain():
    assert json.loads(json.dumps(practice.space_request("cabinet-a", "A", "a@b.c", "en_US", [], 0)))["lang"] == "en_US"


# ---------------------------------------------------------------------------- the progress of an update

PROGRESS = {"target": "fedcba654321", "step": 3, "total": 9, "code": "space", "slug": "cabinet-a", "failed": False,
            "reason": None, "at": "2026-11-11T10:00:00Z"}


def with_progress(**changes):
    return figures(progress={**PROGRESS, **changes})


def test_a_heartbeat_without_progress_is_still_accepted():
    """A practice computer from before the progress report: nothing changes for it."""
    data = figures()
    assert "progress" not in data
    _name, _timestamp, parsed = practice.accept(*request(data), find, NOW)
    assert parsed["progress"] is None
    _name, _timestamp, parsed = practice.accept(*request(figures(progress=None)), find, NOW)
    assert parsed["progress"] is None


def test_the_progress_the_sender_builds_is_accepted():
    record = {"TARGET": "fedcba654321", "STEP": "3", "TOTAL": "9", "CODE": "space", "SLUG": "cabinet-a", "FAILED": "0",
              "REASON": "", "AT": "2026-11-11T10:00:00Z"}
    data = sender.build_figures("practice-1", "abcdef123456", "abcdef123456", "ok", [], sender.progress_figures(record))
    _name, _timestamp, parsed = practice.accept(*request(data), find, NOW)
    assert parsed["progress"] == PROGRESS
    failed = sender.progress_figures({**record, "FAILED": "1", "REASON": "space_update"})
    data = sender.build_figures("practice-1", "abcdef123456", "abcdef123456", "ok", [], failed)
    assert practice.accept(*request(data), find, NOW)[2]["progress"]["reason"] == "space_update"


def test_every_step_and_every_reason_of_the_lists_is_accepted():
    assert practice.PROGRESS_CODES == sender.PROGRESS_CODES and practice.PROGRESS_REASONS == sender.PROGRESS_REASONS
    for step_code in practice.PROGRESS_CODES:
        assert practice.parse_figures(sender.encode(with_progress(code=step_code)))
    for reason in practice.PROGRESS_REASONS:
        assert practice.parse_figures(sender.encode(with_progress(failed=True, reason=reason)))


@pytest.mark.parametrize("change, expected", [
    ({"code": "rm -rf /"}, "bad_value"),
    ({"code": "Updating Cabinet Akwa"}, "bad_value"),
    ({"reason": "disk full on /dev/sda1", "failed": True}, "bad_value"),
    ({"reason": "space_update"}, "bad_value"),            # a reason without the failed flag
    ({"failed": True}, "bad_value"),                      # failed without a reason
    ({"failed": "yes"}, "bad_value"),
    ({"target": "Release of Agro SA"}, "bad_value"),
    ({"target": None}, "bad_value"),
    ({"slug": "Cabinet Akwa"}, "bad_value"),
    ({"slug": "../etc"}, "bad_value"),
    ({"step": "3"}, "bad_value"),
    ({"step": True}, "bad_value"),
    ({"step": -1}, "bad_value"),
    ({"step": 10}, "bad_value"),                          # further than the total
    ({"total": 0}, "bad_value"),
    ({"total": 1000}, "bad_value"),
    ({"at": "this morning"}, "bad_value"),
    ({"note": "the owner asked"}, "bad_progress"),        # no free text, under any name
])
def test_progress_outside_the_closed_words_refuses_the_whole_heartbeat(change, expected):
    assert code(*request(with_progress(**change))) == expected


def test_progress_must_be_whole_and_a_dictionary():
    missing = dict(PROGRESS)
    del missing["reason"]
    assert code(*request(figures(progress=missing))) == "bad_progress"
    for value in ("downloading", ["space"], 3, {}):
        assert code(*request(figures(progress=value))) == "bad_progress"
    # Another unknown key beside it is still refused.
    data = with_progress()
    data["status_text"] = "all good"
    assert code(*request(data)) == "unknown_key"
