import hashlib
import json
from datetime import datetime, timedelta

from ..collect import STATUS_FILES, build_figures, memory_figures, parse_desired, read_status
from ..first_admin import is_expired, password_problem, token_hash, token_matches
from ..signing import encode, response_is_authentic, sign

TOKEN = "a" * 40


def test_signature_depends_on_the_token_the_firm_the_time_and_the_body():
    base = sign(TOKEN, "cabinet-a", 1000, b"{}")
    assert len(base) == 64
    assert sign("b" * 40, "cabinet-a", 1000, b"{}") != base
    assert sign(TOKEN, "cabinet-b", 1000, b"{}") != base
    assert sign(TOKEN, "cabinet-a", 1001, b"{}") != base
    assert sign(TOKEN, "cabinet-a", 1000, b"{ }") != base


def test_an_answer_is_not_a_valid_request_and_a_request_not_a_valid_answer():
    request = sign(TOKEN, "cabinet-a", 1000, b"{}")
    assert not response_is_authentic(TOKEN, "cabinet-a", 1000, b"{}", request)
    assert not response_is_authentic(TOKEN, "cabinet-a", 1000, b"{}", "")
    assert not response_is_authentic(TOKEN, "cabinet-a", 1000, b"{}", None)


def test_encoding_is_stable_whatever_the_order():
    assert encode({"b": 1, "a": 2}) == encode({"a": 2, "b": 1})


def test_status_reads_only_listed_files_and_valid_values(tmp_path):
    (tmp_path / "release").write_text("abcdef123456\n")
    (tmp_path / "last_backup_at").write_text("2026-11-05T02:30:00Z\n")
    (tmp_path / "last_backup_ok").write_text("1\n")
    (tmp_path / "ssh_sessions_24h").write_text("3\n")
    (tmp_path / "last_restore_test_ok").write_text("yes\n")
    (tmp_path / "update_state").write_text("<script>\n")
    (tmp_path / "client_name").write_text("Agro SA\n")
    assert read_status(str(tmp_path)) == {
        "release": "abcdef123456",
        "last_backup_at": "2026-11-05T02:30:00Z",
        "last_backup_ok": True,
        "ssh_sessions_24h": 3,
    }


def test_status_of_a_missing_folder_is_empty(tmp_path):
    assert read_status(str(tmp_path / "nothing")) == {}


def test_body_holds_figures_only():
    figures = build_figures(
        {"release": "abcdef1"}, {"mem_total_mb": 8, "mem_available_mb": 4},
        {"disk_total_gb": 80, "disk_used_pct": 10}, 5, 2, False,
    )
    assert figures["schema"] == 1
    assert figures["users_active"] == 5
    assert figures["engagements_active"] == 2
    assert figures["mail_enabled"] is False
    assert figures["update_state"] == "idle"
    allowed = set(STATUS_FILES) | {
        "schema", "mem_total_mb", "mem_available_mb", "disk_total_gb", "disk_used_pct",
        "users_active", "engagements_active", "mail_enabled", "addons_on",
    }
    assert set(figures) <= allowed
    assert figures["addons_on"] == []
    assert figures["addons_refused"] == 0


def test_add_on_codes_are_technical_names_and_too_many_are_not_sent():
    args = ({"release": "abcdef1"}, {}, {}, 1, 0, False)
    assert build_figures(*args, ["ea_client_b", "ea_client_a", "Rapport Agro SA"])["addons_on"] == ["ea_client_a", "ea_client_b"]
    assert "addons_on" not in build_figures(*args, [f"ea_client_{n}" for n in range(25)])


def test_memory_reads_proc_format(tmp_path):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:  8192000 kB\nMemFree: 1 kB\nMemAvailable:  4096000 kB\n")
    assert memory_figures(str(meminfo)) == {"mem_total_mb": 8000, "mem_available_mb": 4000}
    assert memory_figures(str(tmp_path / "none")) == {"mem_total_mb": 0, "mem_available_mb": 0}


def test_answer_needs_release_and_digest_together():
    digest = hashlib.sha256(b"x").hexdigest()
    both = parse_desired(json.dumps({"desired_release": "abcdef1", "desired_bundle_sha256": digest}).encode())
    assert both["release"] == "abcdef1"
    assert both["bundle_sha256"] == digest
    assert both["export_requested"] is False
    assert "release" not in parse_desired(json.dumps({"desired_release": "abcdef1"}).encode())
    assert "release" not in parse_desired(json.dumps(
        {"desired_release": "$(reboot)", "desired_bundle_sha256": digest}).encode())


def test_answer_drops_what_it_does_not_know():
    desired = parse_desired(json.dumps({"run": "rm -rf /", "export_requested": True}).encode())
    assert desired == {"export_requested": True}
    assert parse_desired(b"not json") is None
    assert parse_desired(b"[1]") is None


def test_answer_allowlist_must_look_like_addresses():
    good = parse_desired(json.dumps({"ssh_allowlist": ["198.51.100.7/32"]}).encode())
    assert good["ssh_allowlist"] == ["198.51.100.7/32"]
    bad = parse_desired(json.dumps({"ssh_allowlist": ["198.51.100.7/32; reboot"]}).encode())
    assert "ssh_allowlist" not in bad


def test_first_admin_token_is_compared_by_hash_only():
    token = "A" * 43
    assert token_matches(token, token_hash(token))
    assert not token_matches("B" * 43, token_hash(token))
    assert not token_matches(token, "")
    assert not token_matches("", token_hash(token))
    assert not token_matches("short", token_hash("short"))
    assert not token_matches("A" * 42 + "'", token_hash(token))


def test_first_admin_link_expires():
    now = datetime(2026, 11, 5, 12)
    assert not is_expired(now + timedelta(seconds=1), now)
    assert is_expired(now, now)
    assert is_expired(None, now)


def test_first_admin_password_rules():
    assert password_problem("court", "court") == "too_short"
    assert password_problem("un mot de passe long", "autre chose encore") == "mismatch"
    assert password_problem(None, None) == "too_short"
    assert password_problem("un mot de passe long", "un mot de passe long") is None
