"""The practice heartbeat's pure part: figures only, closed patterns, its own signature."""

import hashlib
import hmac
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import practice_heartbeat as hb  # noqa: E402

TOKEN = "t" * 64


def test_space_figures_keep_figures_only():
    space = hb.space_figures("demo-akwa", True, "2026-11-07T10:00:00Z", 6, "2026-11-06")
    assert space == {"slug": "demo-akwa", "state": "ready", "last_reset_at": "2026-11-07T10:00:00Z",
                     "users": 6, "last_login_on": "2026-11-06", "reset_generation": 0, "addons_on": [],
                     "link_set": False}


def test_generation_addons_and_link():
    space = hb.space_figures("demo-akwa", True, None, 1, None, 3, ["ea_client_addon_sample", "Bad Name", "x"], True)
    assert space["reset_generation"] == 3
    assert space["addons_on"] == ["ea_client_addon_sample"]
    assert space["link_set"] is True
    assert hb.space_figures("demo-akwa", True, None, 1, None, -1, (), "yes")["reset_generation"] == 0


@pytest.mark.parametrize("reset_at, users, last", [
    ("Cabinet Akwa", "6", "jp.mbarga@cabinet-demo.example"),
    ("2026-11-07 10:00", -1, "2026-11-06T10:00:00Z"),
    (None, 10 ** 9, None),
])
def test_anything_but_a_figure_becomes_nothing(reset_at, users, last):
    space = hb.space_figures("demo-akwa", True, reset_at, users, last)
    assert space["last_reset_at"] is None and space["users"] is None and space["last_login_on"] is None


@pytest.mark.parametrize("slug", ["", "Demo", "demo_akwa", "a", "x" * 40, "demo akwa"])
def test_a_bad_slug_is_refused(slug):
    with pytest.raises(ValueError):
        hb.space_figures(slug, True, None, 1, None)


def test_missing_space_and_closed_values():
    figures = hb.build_figures("practice-1", "b5ccec10", "nothex!", "maybe", [
        hb.space_figures("zeta", False, None, None, None), hb.space_figures("alpha", True, None, 1, None),
    ])
    assert figures["release"] == "b5ccec10"
    assert figures["template_release"] is None
    assert figures["guard"] == "unknown"
    assert [s["slug"] for s in figures["spaces"]] == ["alpha", "zeta"]
    assert figures["spaces"][1]["state"] == "missing"
    assert set(figures) == {"schema", "computer", "release", "template_release", "guard", "spaces"}


def test_signature_matches_the_documented_format():
    body = hb.encode({"b": 1, "a": 2})
    assert body == b'{"a":2,"b":1}'
    message = b"\n".join([b"ea-practice-heartbeat-v1", b"practice-1", b"1700000000", hashlib.sha256(body).hexdigest().encode()])
    assert hb.sign(TOKEN, "practice-1", 1700000000, body) == hmac.new(TOKEN.encode(), message, hashlib.sha256).hexdigest()


def test_a_firm_heartbeat_signature_does_not_pass_for_a_practice_one():
    body = b"{}"
    firm = b"\n".join([b"ea-heartbeat-v1", b"practice-1", b"1", hashlib.sha256(body).hexdigest().encode()])
    assert hmac.new(TOKEN.encode(), firm, hashlib.sha256).hexdigest() != hb.sign(TOKEN, "practice-1", 1, body)


def test_only_a_signed_answer_is_authentic():
    answer = json.dumps({"spaces": []}).encode()
    message = b"\n".join([b"ea-practice-heartbeat-response-v1", b"practice-1", b"5", hashlib.sha256(answer).hexdigest().encode()])
    good = hmac.new(TOKEN.encode(), message, hashlib.sha256).hexdigest()
    assert hb.response_is_authentic(TOKEN, "practice-1", 5, answer, good)
    assert not hb.response_is_authentic(TOKEN, "practice-1", 6, answer, good)
    assert not hb.response_is_authentic(TOKEN, "practice-1", 5, answer + b" ", good)
    assert not hb.response_is_authentic(TOKEN, "practice-1", 5, answer, None)


def test_parse_env_reads_only_quoted_lines():
    assert hb.parse_env("A='1'\nB=2\n# C='3'\nD='x y'\n") == {"A": "1", "D": "x y"}


# ---------------------------------------------------------------------------- the progress of an update

PROGRESS = {"TARGET": "0123456789ab", "STEP": "3", "TOTAL": "9", "CODE": "space", "SLUG": "demo-akwa",
            "FAILED": "0", "REASON": "", "AT": "2026-11-11T10:00:00Z"}


def test_progress_is_read_from_the_file_practice_update_writes():
    text = "".join("%s='%s'\n" % item for item in PROGRESS.items())
    assert hb.progress_figures(hb.parse_env(text)) == {
        "target": "0123456789ab", "step": 3, "total": 9, "code": "space", "slug": "demo-akwa",
        "failed": False, "reason": None, "at": "2026-11-11T10:00:00Z",
    }


def test_a_failure_carries_a_reason_from_the_list_and_nothing_else():
    failed = hb.progress_figures({**PROGRESS, "FAILED": "1", "REASON": "space_update"})
    assert failed["failed"] is True and failed["reason"] == "space_update"
    assert hb.progress_figures({**PROGRESS, "FAILED": "1", "REASON": "disk full on /dev/sda"})["reason"] == "other"
    assert hb.progress_figures({**PROGRESS, "FAILED": "1", "REASON": ""})["reason"] == "other"
    # A reason without the flag is not a failure.
    assert hb.progress_figures({**PROGRESS, "REASON": "digest"})["reason"] is None


def test_progress_outside_the_closed_words_is_left_out():
    for key, value in (("TARGET", "not-a-commit"), ("STEP", "x"), ("STEP", "10"), ("TOTAL", "0"), ("TOTAL", "1000"),
                       ("CODE", "rm -rf"), ("AT", "yesterday"), ("STEP", "\u0663")):
        assert hb.progress_figures({**PROGRESS, key: value}) is None, (key, value)
    assert hb.progress_figures({}) is None
    assert hb.progress_figures({**PROGRESS, "SLUG": "../etc"})["slug"] is None


def test_figures_carry_progress_only_when_there_is_some():
    assert "progress" not in hb.build_figures("practice-1", "0123456789ab", None, "ok", [])
    progress = hb.progress_figures(PROGRESS)
    figures = hb.build_figures("practice-1", "0123456789ab", None, "ok", [], progress)
    assert figures["progress"] == progress


def test_an_older_control_room_still_gets_the_heartbeat_without_progress(monkeypatch, tmp_path):
    """A control room from before the progress report refuses the unknown figure (403): sent again without it."""
    import urllib.error

    sent = []

    def fake_send(url, computer, token, figures):
        sent.append(figures)
        if "progress" in figures:
            raise urllib.error.HTTPError(url, 403, "Forbidden", None, None)

    figures = hb.build_figures("practice-1", "0123456789ab", None, "ok", [], hb.progress_figures(PROGRESS))
    monkeypatch.setattr(hb, "collect", lambda: ({"PRACTICE_HEARTBEAT_URL": "https://console.example/platform/practice-heartbeat"}, figures))
    monkeypatch.setattr(hb, "send", fake_send)
    monkeypatch.setattr(hb, "_read", lambda path: "token")
    monkeypatch.setattr(hb, "_write_atomic", lambda *args: None)
    assert hb.main() == 0
    assert len(sent) == 2 and "progress" in sent[0] and "progress" not in sent[1]
    assert sent[1]["release"] == "0123456789ab"
    # Any other refusal is not retried.
    sent.clear()
    monkeypatch.setattr(hb, "collect", lambda: ({"PRACTICE_HEARTBEAT_URL": "https://console.example/x"},
                                                hb.build_figures("practice-1", None, None, "ok", [])))

    def refuse(url, computer, token, figures):
        sent.append(figures)
        raise urllib.error.HTTPError(url, 403, "Forbidden", None, None)

    monkeypatch.setattr(hb, "send", refuse)
    assert hb.main() == 1
    assert len(sent) == 1
