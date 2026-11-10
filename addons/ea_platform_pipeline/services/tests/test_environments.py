"""What the Status page reads about staging and the practice spaces, and what it may ask. Pure."""

import json
from datetime import datetime, timedelta

from ea_platform_pipeline.services import collected, environments as envs

NOW = datetime(2026, 11, 9, 12, 0, 0)
STAMP = "2026-11-09T12:00:00Z"
HASH = "$pbkdf2-sha512$600000$c2FsdHNhbHRzYWx0$" + "A" * 86


def state(**changes):
    data = {
        "schema": 1, "generated": STAMP,
        "staging": {"reachable": True, "service_active": True, "odoo_version": "19.0", "revision": "24a65a86",
                    "modules": [["ea_audit_core", "19.0.1.0.0"], ["bad name", "1"]], "db_size_mb": 76, "up_since": STAMP,
                    "mail_off": True, "releases": [{"name": "24a65a86", "at": STAMP, "result": "running"}],
                    "users": [{"login": "a@b.cm", "name": "Awa", "role": "manager", "active": True, "last_login": STAMP,
                               "online": True, "protected": False},
                              {"login": "x@y.cm", "name": "<script>", "role": "god", "active": "yes"}]},
        "practice": {"reachable": True, "spaces": [{"slug": "demo-akwa", "db_size_mb": 75, "users": []}, {"slug": "../etc"}]},
        "requests": [{"id": "0123456789abcdef", "state": "done", "code": "", "at": STAMP},
                     {"id": "nothex", "state": "done"}, {"id": "fedcba9876543210", "state": "failed", "code": "rm -rf"}],
    }
    data.update(changes)
    return json.dumps(data).encode()


def test_the_state_keeps_only_what_passes():
    read = envs.read_env_state(state(), NOW)
    assert read["stale"] is False
    assert read["staging"]["modules"] == [("ea_audit_core", "19.0.1.0.0")]
    awa, other = read["staging"]["users"]
    assert awa["online"] and awa["role"] == "manager"
    assert other["name"] == "x@y.cm" and other["role"] == "user" and other["active"] is False
    assert [space["slug"] for space in read["practice"]["spaces"]] == ["demo-akwa"]
    assert set(read["requests"]) == {"0123456789abcdef", "fedcba9876543210"}
    assert read["requests"]["fedcba9876543210"]["code"] is None


def test_a_bad_or_old_file_is_refused_or_marked():
    assert envs.read_env_state(b"not json", NOW) is None
    assert envs.read_env_state(state(schema=2), NOW) is None
    assert envs.read_env_state(b"x" * (envs.MAX_BYTES + 1), NOW) is None
    assert envs.read_env_state(state(), NOW + timedelta(minutes=10))["stale"] is True


def test_requests_go_to_staging_or_a_practice_space_only():
    assert envs.request_errors("create", "staging", "a@b.cm", "Awa", "staff", HASH) == []
    assert envs.request_errors("disable", "practice:demo-akwa", "a@b.cm") == []
    for target in ("firm:cabinet-a", "cabinet-a", "practice:../x", "production", ""):
        assert envs.request_errors("disable", target, "a@b.cm"), target
    assert envs.request_errors("create", "staging", "not-an-email", "Awa", "staff", HASH)
    assert envs.request_errors("create", "staging", "a@b.cm", "<b>", "staff", HASH)
    assert envs.request_errors("create", "staging", "a@b.cm", "Awa", "superuser", HASH)
    assert envs.request_errors("create", "staging", "a@b.cm", "Awa", "staff", "plain-password")
    assert envs.request_errors("drop", "staging", "a@b.cm")


def test_the_payload_carries_a_hash_and_nothing_more():
    payload = envs.request_payload("0123456789abcdef", "create", "staging", " A@B.cm ", "Awa ", "staff", HASH)
    assert payload == {"schema": 1, "id": "0123456789abcdef", "action": "create", "target": "staging", "login": "a@b.cm",
                       "name": "Awa", "role": "staff", "password_hash": HASH}
    assert "password_hash" not in envs.request_payload("0123456789abcdef", "disable", "staging", "a@b.cm")


def test_changes_between_two_commits_of_a_branch():
    log = [{"sha": c * 40, "author": "N", "at": STAMP, "subject": f"change {c}"} for c in "dcba"]
    assert [row["sha"][0] for row in envs.changes_between(log, "b" * 12, "d" * 40)] == ["d", "c"]
    assert envs.changes_between(log, "e" * 12, "d" * 40) is None
    assert envs.changes_between(log, "d" * 12, "b" * 40) is None
    assert envs.changes_between([], "a", "b") is None


def test_no_signing_command_is_shown_any_more():
    assert not hasattr(envs, "sign_commands")


def test_the_collector_keeps_commit_subjects_as_plain_text():
    raw = json.dumps({"schema": 1, "generated": STAMP, "odoo": {"github": "ok", "log": {"dev": [
        {"sha": "a" * 40, "author": "N", "at": STAMP, "subject": "Fix <b>it</b>"},
        {"sha": "zz", "subject": "dropped"}, {"sha": "b" * 40, "subject": "line\nbreak"}]}}}).encode()
    read = collected.read_state(raw, NOW)
    log = read["odoo"]["log"]["dev"]
    assert [row["sha"][0] for row in log] == ["a", "b"]
    assert log[0]["subject"] == "Fix <b>it</b>"
    assert log[1]["subject"] is None
    assert read["odoo"]["log"]["main"] == []
