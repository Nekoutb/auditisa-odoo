"""The pipeline's decisions, the anonymiser's rules and the answers a firm can receive. No Odoo, no database."""

import base64
import importlib.util
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ea_platform_pipeline.services import pipeline

ROOT = Path(__file__).parents[4]
NOW = datetime(2026, 11, 7, 12, 0, 0)
SHA = "abcdef123456abcdef123456abcdef123456abcd"
DIGEST = "a" * 64


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


anon = load("deploy/firm/firm_anon.py", "firm_anon")
MANIFEST = json.loads((ROOT / "deploy/firm/anon-manifest.json").read_text(encoding="utf-8"))


def text(message):
    return str(message)


# ------------------------------------------------------------------ attestation


@pytest.fixture
def keys():
    ed25519 = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
    serialization = pytest.importorskip("cryptography.hazmat.primitives.serialization")
    private = ed25519.Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private, public


def signed(private, sha=SHA, digest=DIGEST):
    return base64.b64encode(private.sign(pipeline.attestation_message(sha, digest))).decode()


def test_attestation_holds_for_what_was_signed(keys):
    private, public = keys
    assert pipeline.attestation_holds(public, SHA, DIGEST, signed(private))


def test_attestation_tolerates_line_breaks_from_a_paste(keys):
    private, public = keys
    value = signed(private)
    assert pipeline.attestation_holds(public, SHA, DIGEST, value[:20] + "\n" + value[20:] + "\n")


@pytest.mark.parametrize("sha, digest", [("0" * 40, DIGEST), (SHA, "b" * 64)])
def test_attestation_is_refused_for_another_commit_or_digest(keys, sha, digest):
    private, public = keys
    assert not pipeline.attestation_holds(public, sha, digest, signed(private))


def test_attestation_from_another_key_is_refused(keys):
    ed25519 = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
    _private, public = keys
    other = ed25519.Ed25519PrivateKey.generate()
    assert not pipeline.attestation_holds(public, SHA, DIGEST, signed(other))


@pytest.mark.parametrize("public, value", [("", "abc"), ("not a key", "abc"), (None, None)])
def test_attestation_with_no_or_broken_input_is_refused(public, value):
    assert not pipeline.attestation_holds(public, SHA, DIGEST, value)


def test_attestation_with_garbage_is_refused(keys):
    _private, public = keys
    assert not pipeline.attestation_holds(public, SHA, DIGEST, "%%% not base64 %%%")
    assert not pipeline.attestation_holds(public, SHA, DIGEST, base64.b64encode(b"short").decode())


# ------------------------------------------------------------------ pre-checks


def test_commits_compare_short_and_long():
    assert pipeline.same_commit(SHA[:12], SHA)
    assert pipeline.same_commit(SHA, SHA[:7])
    assert not pipeline.same_commit(SHA, "0" + SHA[1:])
    assert not pipeline.same_commit(None, SHA)
    assert not pipeline.same_commit("", SHA)


def test_tests_must_be_recorded():
    assert not pipeline.test_check([])["ok"]


def test_a_green_run_passes():
    assert pipeline.test_check([{"suite": "odoo", "passed": 10, "failed": 0}])["ok"]


def test_the_newest_run_of_a_suite_decides():
    assert pipeline.test_check([
        {"suite": "odoo", "passed": 10, "failed": 0},
        {"suite": "odoo", "passed": 9, "failed": 1},
    ])["ok"]
    assert not pipeline.test_check([
        {"suite": "odoo", "passed": 9, "failed": 1},
        {"suite": "odoo", "passed": 10, "failed": 0},
    ])["ok"]


def test_one_red_suite_is_enough():
    assert not pipeline.test_check([
        {"suite": "odoo", "passed": 10, "failed": 0},
        {"suite": "pure", "passed": 3, "failed": 2},
    ])["ok"]


def test_a_run_of_nothing_is_not_green():
    assert not pipeline.test_check([{"suite": "odoo", "passed": 0, "failed": 0}])["ok"]


STAGING = {"last_heartbeat_at": NOW - timedelta(minutes=10), "health_color": "green", "release": SHA[:12], "mail_enabled": False}


def test_staging_healthy_on_this_commit_passes():
    assert pipeline.staging_check(STAGING, SHA, NOW)["ok"]


@pytest.mark.parametrize("change", [
    {"last_heartbeat_at": NOW - timedelta(hours=2)},
    {"last_heartbeat_at": None},
    {"release": "0" * 12},
    {"mail_enabled": True},
])
def test_staging_fails_each_way(change):
    assert not pipeline.staging_check({**STAGING, **change}, SHA, NOW)["ok"]


def test_staging_unknown_fails():
    assert not pipeline.staging_check(None, SHA, NOW)["ok"]


def test_backups():
    good = {"name": "A", "last_backup_at": NOW - timedelta(hours=3), "last_backup_ok": True}
    assert pipeline.backup_check([good], NOW)["ok"]
    assert not pipeline.backup_check([], NOW)["ok"]
    assert not pipeline.backup_check([good, {**good, "last_backup_ok": False}], NOW)["ok"]
    assert not pipeline.backup_check([{**good, "last_backup_at": NOW - timedelta(hours=30)}], NOW)["ok"]
    assert not pipeline.backup_check([{**good, "last_backup_at": None}], NOW)["ok"]


# ------------------------------------------------------------------ confirmation and address


def test_phrase_names_the_target_in_the_readers_language():
    assert pipeline.phrase("promote", "abc", "fr_FR") == "PROMOUVOIR abc"
    assert pipeline.phrase("promote", "abc", "en_US") == "PROMOTE abc"
    assert pipeline.phrase("rebuild", "cabinet-a", "fr_FR") == "RECONSTRUIRE cabinet-a"


def test_confirmation_needs_the_exact_line_and_a_reason():
    expected = "PROMOTE abc"
    assert not pipeline.confirmation_errors(expected, expected, "Staging signed off by the owner")
    assert pipeline.confirmation_errors(expected, "promote abc", "Staging signed off by the owner")
    assert pipeline.confirmation_errors(expected, "PROMOTE other", "Staging signed off by the owner")
    assert pipeline.confirmation_errors(expected, expected, "")
    assert pipeline.confirmation_errors(expected, expected, "too short")


@pytest.mark.parametrize("address, cidrs, allowed", [
    ("143.105.152.209", ["143.105.152.209/32"], True),
    ("143.105.152.9", ["143.105.152.0/24"], True),
    ("8.8.8.8", ["143.105.152.209/32"], False),
    ("143.105.152.209", [], False),
    (None, ["143.105.152.209/32"], False),
    ("not an address", ["143.105.152.209/32"], False),
    ("2001:db8::1", ["2001:db8::/48"], True),
])
def test_address(address, cidrs, allowed):
    assert pipeline.address_allowed(address, cidrs) is allowed


# ------------------------------------------------------------------ rebuild and heartbeat


@pytest.mark.parametrize("state, reported, digest, expected", [
    ("requested", "running", None, "running"),
    ("running", "done", "c" * 64, "exported"),
    ("requested", "done", "c" * 64, "exported"),
    ("running", "done", None, None),
    ("running", "failed", None, "failed"),
    ("requested", "refused", None, "refused"),
    ("exported", "failed", None, None),
])
def test_rebuild_follows_the_firm(state, reported, digest, expected):
    figures = {"anon_export_ref": "1" * 16, "anon_export_state": reported, "anon_export_sha256": digest}
    assert pipeline.rebuild_transition(state, figures, "1" * 16) == expected


def test_rebuild_ignores_another_reference():
    figures = {"anon_export_ref": "2" * 16, "anon_export_state": "done", "anon_export_sha256": "c" * 64}
    assert pipeline.rebuild_transition("requested", figures, "1" * 16) is None


def test_public_state_keeps_only_the_listed_keys():
    result = pipeline.public_state({"firms_total": 3, "firm_name": "Cabinet A", "reason": "x"})
    assert set(result) == set(pipeline.PUBLIC_KEYS)
    assert "Cabinet A" not in json.dumps(result)


def test_public_keys_name_no_firm_person_or_reason():
    joined = " ".join(pipeline.PUBLIC_KEYS)
    for word in ("name", "reason", "email", "slug", "user", "by"):
        assert not re.search(rf"\b{word}\b|_{word}\b", joined), word


def test_new_figures_carry_no_free_text():
    from ea_platform_admin.services.heartbeat import FIGURES

    names = ["anon_export_state", "anon_export_ref", "anon_export_at", "anon_export_sha256"]
    for name in names:
        assert not FIGURES[name]("Rapport d'audit de la société Agro SA"), name
        assert not FIGURES[name]("Jean Dupont"), name


# ------------------------------------------------------------------ the anonymiser's rules


def inventory(**changes):
    table = {name: "character varying" for name in MANIFEST["tables"]["ea_audit_client"]["columns"]}
    table["id"] = "integer"
    base = {"tables": {"ea_audit_client": table}, "models": ["ea.audit.client"], "other_relations": []}
    base.update(changes)
    return base


def test_the_manifest_is_well_formed():
    anon.check_manifest_shape(MANIFEST)


def test_a_covered_database_passes():
    assert anon.compare_inventory(MANIFEST, inventory()) == []


def test_a_table_not_on_the_list_stops():
    data = inventory()
    data["tables"]["x_new"] = {"id": "integer"}
    assert ("unlisted-table", "x_new") in anon.compare_inventory(MANIFEST, data)


def test_a_model_not_on_the_list_stops():
    data = inventory(models=["x.new"])
    assert ("unlisted-model", "x.new") in anon.compare_inventory(MANIFEST, data)


def test_a_text_column_not_on_the_list_stops():
    data = inventory()
    data["tables"]["ea_audit_client"]["x_note"] = "text"
    assert ("unlisted-column", "ea_audit_client.x_note") in anon.compare_inventory(MANIFEST, data)


def test_a_new_number_column_does_not_stop():
    data = inventory()
    data["tables"]["ea_audit_client"]["x_total"] = "numeric"
    assert anon.compare_inventory(MANIFEST, data) == []


def test_a_column_of_an_unknown_type_stops():
    data = inventory()
    data["tables"]["ea_audit_client"]["x_addr"] = "inet"
    assert ("unknown-type", "ea_audit_client.x_addr") in anon.compare_inventory(MANIFEST, data)


def test_text_in_a_relation_table_stops():
    relation = next(name for name, entry in MANIFEST["tables"].items() if entry["class"] == "relation")
    data = inventory()
    data["tables"][relation] = {"x_note": "text"}
    assert ("text-in-relation", relation) in anon.compare_inventory(MANIFEST, data)


def test_anything_outside_public_stops():
    data = inventory(other_relations=["other.table"])
    assert ("unlisted-relation", "other.table") in anon.compare_inventory(MANIFEST, data)


def test_bad_manifests_are_refused():
    with pytest.raises(anon.Stop):
        anon.check_manifest_shape({"tables": {"a": {"class": "whatever"}}})
    with pytest.raises(anon.Stop):
        anon.check_manifest_shape({"tables": {"a": {"class": "firm", "columns": {"b": "keep_everything"}}}})
    with pytest.raises(anon.Stop):
        anon.check_manifest_shape({"patterns": {}, "tables": {"a": {"class": "firm", "columns": {"b": "keep:NOPE"}}}})


def test_identifying_tables_are_never_kept_as_they_are():
    wrong = [
        name for name in ("res_partner", "res_users", "res_company", "ea_audit_client", "ea_audit_engagement", "hr_employee",
                          "ea_audit_paper_answer", "ea_audit_gl_line", "ea_audit_tb_line", "ea_audit_dataset_row")
        if MANIFEST["tables"][name]["class"] != "firm"
    ]
    assert wrong == []


def test_chatter_files_and_logs_are_purged():
    wrong = [
        name for name in ("mail_message", "mail_tracking_value", "mail_mail", "mail_activity", "ir_attachment", "ir_logging",
                          "ea_audit_firm_log", "res_device_log", "res_users_log", "res_users_apikeys", "auth_totp_device",
                          "ir_mail_server", "fetchmail_server", "ea_firm_access_log")
        if MANIFEST["tables"][name]["class"] != "purge"
    ]
    assert wrong == []


def test_no_keep_pattern_accepts_a_name_or_an_email():
    for name, spec in MANIFEST["patterns"].items():
        pattern = re.compile(spec["re"])
        for value in ("Jean Dupont-Mbarga", "jean.dupont@planted-client.cm", "Societe Planted Agro SA", "+237 699 12 34 56"):
            assert not pattern.search(value), f"{name} accepts {value}"


def test_the_secret_and_the_address_are_not_kept():
    keep = MANIFEST["config_keep"]
    for key in ("database.secret", "database.uuid", "web.base.url", "ea_firm_agent.heartbeat_url", "ea_firm_agent.slug", "mail.catchall.domain"):
        assert not any(re.fullmatch(pattern, key) for pattern in keep), key


@pytest.mark.parametrize("rule", sorted(anon.RULES))
def test_each_rule_builds_sql(rule):
    sql = anon.expression(rule, "col", MANIFEST["patterns"], table="t")
    assert sql


def test_expressions_quote_a_pattern_and_keep_nulls():
    sql = anon.expression("keep:ACCOUNT", "col", MANIFEST["patterns"])
    assert '"col" IS NULL' in sql and "~" in sql


def test_a_bad_identifier_is_refused():
    with pytest.raises(anon.Stop):
        anon.quote_ident('x"; DROP TABLE y; --')


def scanner(denied=("Jean Dupont-Mbarga", "planted-client.cm")):
    return anon.build_scanner(denied, MANIFEST["scan"])


@pytest.mark.parametrize("line, expected", [
    ("COPY of nothing", []),
    ("a\tJean Dupont-Mbarga\tb", ["identifying-value"]),
    ("a\tJEAN DUPONT-MBARGA\tb", ["identifying-value"]),
    ("someone@somewhere-else.cm", ["email-address"]),
    ("u12ab@anon.invalid", []),
    ("NIU M012345678901A here", ["tax-number"]),
    ("+237 699 12 34 56", ["cameroon-phone"]),
    ("RC/DLA/2021/B/1234", ["trade-register"]),
    ("CM21 10005 00001 12345678901 23", ["bank-account"]),
    ("14137000", []),
    ("[anon 12ab34cd56]", []),
])
def test_scanner(line, expected):
    assert scanner()(line) == expected


def test_scanner_does_not_match_inside_a_longer_word():
    assert scanner(("Dupont",))("Dupontel") == []


def test_scanner_tells_where_and_never_what():
    lines = ["COPY public.res_partner (id, name) FROM stdin;\n", "1\tJean Dupont-Mbarga\n", "\\.\n", "COPY public.x (id) FROM stdin;\n", "1\n", "\\.\n"]
    hits = anon.scan_lines(lines, scanner())
    assert hits == {("res_partner", "identifying-value"): 1}
    assert "Dupont" not in " ".join(anon.scan_failures(hits))


def test_stop_never_carries_a_value():
    assert "Dupont" not in str(anon.Stop("survivors", "2 table and kind pairs"))


# ------------------------------------------------------------------ what a firm can be asked


def test_the_agent_validates_the_new_request():
    from ea_audit_firm_agent.services.collect import parse_desired

    assert parse_desired(json.dumps({"anon_export_ref": "1" * 16}).encode())["anon_export_ref"] == "1" * 16
    for bad in ("x" * 16, "1" * 15, "; rm -rf /", 12, None):
        assert "anon_export_ref" not in parse_desired(json.dumps({"anon_export_ref": bad}).encode())


def test_the_agent_reads_the_new_figures_only_if_valid(tmp_path):
    from ea_audit_firm_agent.services.collect import read_status

    (tmp_path / "anon_export_state").write_text("done", encoding="ascii")
    (tmp_path / "anon_export_ref").write_text("1" * 16, encoding="ascii")
    (tmp_path / "anon_export_sha256").write_text("not a digest", encoding="ascii")
    figures = read_status(str(tmp_path))
    assert figures["anon_export_state"] == "done"
    assert figures["anon_export_ref"] == "1" * 16
    assert "anon_export_sha256" not in figures


def test_the_shell_side_validates_the_request_again():
    source = (ROOT / "deploy/firm/firm-apply-desired.sh").read_text(encoding="utf-8")
    assert 're.fullmatch(r"[0-9a-f]{16}", ref)' in source
    export = (ROOT / "deploy/firm/firm-anon-export.sh").read_text(encoding="utf-8")
    assert 'valid_anon_ref "$REF"' in export
    assert "ANON_EXPORT_ALLOWED" in export


def test_the_export_never_touches_the_filestore():
    export = (ROOT / "deploy/firm/firm-anon-export.sh").read_text(encoding="utf-8")
    assert "tar -cf" in export and "db.dump ANON-REPORT.json SHA256SUMS" in export
    code = "\n".join(line for line in export.splitlines() if not line.lstrip().startswith("#"))
    assert "filestore" not in code


def test_the_bundle_leaves_this_addon_out():
    source = (ROOT / "scripts/provision/build_release.sh").read_text(encoding="utf-8")
    assert "grep -v '^addons/ea_platform_'" in source


# ------------------------------------------------------------------ the owner's signing


def test_what_the_owners_script_prints_is_what_the_screen_accepts(tmp_path):
    pytest.importorskip("cryptography")
    for tool in ("bash", "openssl", "git"):
        if not shutil.which(tool):
            pytest.skip(f"needs {tool}")

    def run(*args):
        return subprocess.run([shutil.which("bash"), *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout

    relative = os.path.relpath(tmp_path, ROOT).replace(os.sep, "/")
    created = run("scripts/provision/build_release.sh", "--new-key", f"{relative}/key.pem")
    public = created[created.index("-----BEGIN"):]
    printed = run("scripts/pipeline/sign_promotion.sh", "HEAD", "--key", f"{relative}/key.pem", "--out", f"{relative}/out")
    sha = re.search(r"^commit +(\S+)", printed, re.M).group(1)
    digest = re.search(r"^sha256 +(\S+)", printed, re.M).group(1)
    attestation = re.search(r"^attestation +(\S+)", printed, re.M).group(1)
    assert pipeline.attestation_holds(public, sha, digest, attestation)
    assert not pipeline.attestation_holds(public, "0" * 40, digest, attestation)
    assert not pipeline.attestation_holds(public, sha, "b" * 64, attestation)
    assert "PRIVATE" not in printed
