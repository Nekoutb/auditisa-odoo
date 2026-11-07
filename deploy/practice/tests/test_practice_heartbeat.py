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
                     "users": 6, "last_login_on": "2026-11-06"}


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
