"""The pipeline's decisions, the anonymiser's rules and the answers a firm can receive. No Odoo, no database."""

import hashlib
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


# ------------------------------------------------------------------ no signature any more


def test_nothing_signs_or_checks_a_signature_any_more():
    """2026-11-10: the console's sign-in is the security; a server checks the bundle's SHA-256 only."""
    for gone in ("attestation_message", "attestation_holds", "ATTESTATION_PREFIX", "test_check", "staging_check", "backup_check"):
        assert not hasattr(pipeline, gone), gone
    for kind in ("promote", "rollback", "rebuild", "main", "rebuilt"):
        assert pipeline.phrase(kind, "x")
    for gone in ("override", "practice"):
        with pytest.raises(KeyError):
            pipeline.phrase(gone, "x")


def test_commits_compare_short_and_long():
    assert pipeline.same_commit(SHA[:12], SHA)
    assert pipeline.same_commit(SHA, SHA[:7])
    assert not pipeline.same_commit(SHA, "0" + SHA[1:])
    assert not pipeline.same_commit(None, SHA)
    assert not pipeline.same_commit("", SHA)


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


@pytest.mark.parametrize("address, text, allowed", [
    # No list: the owner's choice, no address check (ruling of 2026-11-08).
    ("8.8.8.8", "", True),
    ("8.8.8.8", None, True),
    (None, "", True),
    # A list, once written, binds.
    ("143.105.152.209", "143.105.152.209/32", True),
    ("8.8.8.8", "143.105.152.209/32, 2001:db8::/48", False),
    ("2001:db8::1", "143.105.152.209/32, 2001:db8::/48", True),
    (None, "143.105.152.209/32", False),
    # A list that holds no valid range refuses everything rather than opening up.
    ("8.8.8.8", "not-an-address", False),
])
def test_owner_address(address, text, allowed):
    assert pipeline.owner_address_ok(address, pipeline.owner_addresses(text)) is allowed


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


# ------------------------------------------------------------------ the developer's build


def test_the_build_needs_no_key_and_prints_the_sha256_of_its_bundle(tmp_path):
    for tool in ("bash", "git"):
        if not shutil.which(tool):
            pytest.skip(f"needs {tool}")
    try:  # build_release.sh may call python3, which some Windows machines only alias to the Store.
        subprocess.run(["python3", "--version"], capture_output=True, check=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("needs a working python3")

    def run(*args, check=True):
        return subprocess.run([shutil.which("bash"), *args], cwd=ROOT, capture_output=True, text=True, check=check)

    relative = os.path.relpath(tmp_path, ROOT).replace(os.sep, "/")
    printed = run("scripts/provision/build_release.sh", "HEAD", "--out", f"{relative}/out").stdout
    sha = re.search(r"^commit +(\S+)", printed, re.M).group(1)
    digest = re.search(r"^sha256 +(\S+)", printed, re.M).group(1)
    bundle = tmp_path / "out" / f"{sha}.tar.gz"
    assert hashlib.sha256(bundle.read_bytes()).hexdigest() == digest
    assert sorted(path.name for path in (tmp_path / "out").iterdir()) == sorted(
        [f"{sha}.tar.gz", f"{sha}.catalogue.json", f"{sha}.changes.txt"])
    refused = run("scripts/provision/build_release.sh", "HEAD", "--key", "x.pem", "--out", f"{relative}/again", check=False)
    assert refused.returncode != 0 and "no longer signed" in refused.stderr


# ------------------------------------------------------------------ what the collector wrote


from ea_platform_pipeline.services import collected  # noqa: E402

GOOD = {
    "schema": 1, "generated": "2026-11-07T12:00:00Z",
    "next": {"github": "ok", "branches": {"dev": {"sha": "a" * 40, "author": "Nekoutb", "at": "2026-11-04T09:43:00Z"}},
             "running": {"staging": {"sha": "a" * 40}}, "ahead": {"staging_over_production": 36},
             "sites": {"staging": {"up": True, "started_at": "2026-11-04T09:53:26.366Z"}}},
    "odoo": {"github": "no_key", "branches": {}, "running": {}, "ahead": {}, "sites": {"staging": {"up": True, "mail_off": True, "band_on": True}}},
}


def test_the_collected_state_reads():
    state = collected.read_state(json.dumps(GOOD).encode(), NOW)
    assert state["next"]["branches"]["dev"]["author"] == "Nekoutb"
    assert state["next"]["ahead"]["staging_over_production"] == 36
    assert state["odoo"]["github"] == "no_key"
    assert state["odoo"]["sites"]["staging"]["mail_off"] is True
    assert not state["stale"]


def test_an_old_reading_is_marked():
    assert collected.read_state(json.dumps(GOOD).encode(), NOW + timedelta(minutes=10))["stale"]


@pytest.mark.parametrize("bad", [b"", b"not json", b"[]", json.dumps({"schema": 2}).encode(),
                                 json.dumps({**GOOD, "generated": "yesterday"}).encode(), b"x" * 70000], ids=range(6))
def test_a_bad_file_is_no_reading(bad):
    assert collected.read_state(bad, NOW) is None


def test_what_comes_from_outside_is_checked():
    hostile = json.loads(json.dumps(GOOD))
    hostile["next"]["branches"]["dev"]["author"] = "<script>alert(1)</script>"
    hostile["next"]["branches"]["main"] = {"sha": "not a sha"}
    hostile["next"]["ahead"]["staging_over_production"] = "many"
    hostile["next"]["github"] = "whatever"
    hostile["next"]["extra"] = "Cabinet Agro"
    state = collected.read_state(json.dumps(hostile).encode(), NOW)
    assert state["next"]["branches"]["dev"]["author"] is None
    assert state["next"]["branches"]["main"] is None
    assert state["next"]["ahead"]["staging_over_production"] is None
    assert state["next"]["github"] == "unreachable"
    assert "Agro" not in json.dumps(state, default=str)
