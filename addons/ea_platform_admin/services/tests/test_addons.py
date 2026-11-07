import ast
import importlib.util
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ea_platform_admin.services import addons, health, heartbeat
from ea_platform_admin.services.simulator import healthy_figures

ROOT = Path(__file__).parents[4]
SHA = "abcdef123456"
NOW = datetime(2026, 11, 7, 12, 0, 0)


def entry(code="ea_client_x", **changes):
    return {"code": code, "name": "X", "summary": "", "version": "19.0.1.0.0", "optional": True, "sample": False, **changes}


def document(*entries, release=SHA, schema=1):
    return json.dumps({"schema": schema, "release": release, "addons": list(entries)}).encode()


def manifest(code):
    return ast.literal_eval((ROOT / "addons" / code / "__manifest__.py").read_text(encoding="utf-8"))


def test_the_catalogue_script_and_the_service_read_alike():
    spec = importlib.util.spec_from_file_location("build_catalogue", ROOT / "scripts/provision/build_catalogue.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.scan(ROOT / "addons") == addons.scan(ROOT / "addons")
    assert script.MARKER == addons.MARKER


def test_the_real_codebase_reads_as_base_features_and_one_sample():
    found = {item["code"]: item for item in addons.scan(ROOT / "addons")}
    assert "ea_platform_admin" not in found
    assert found["ea_audit_reports"]["optional"] is False
    assert found["ea_audit_core"]["optional"] is False
    assert found["ea_audit_addons"]["optional"] is False
    assert [code for code, item in found.items() if item["optional"]] == ["ea_client_addon_sample"]
    assert found["ea_client_addon_sample"]["sample"] is True


def test_every_addon_name_has_its_translation_source():
    from ea_platform_admin.services.addon_texts import TEXTS
    for item in addons.scan(ROOT / "addons"):
        assert item["name"] in TEXTS, item["code"]
        assert item["summary"] in TEXTS, item["code"]


def test_a_good_catalogue_reads_back():
    assert addons.parse_catalogue(document(entry()), SHA) == [entry()]


@pytest.mark.parametrize("raw", [b"", b"nope", b"[]", b"{}", document(entry(), schema=2), document()])
def test_a_file_that_is_no_catalogue_is_refused(raw):
    with pytest.raises(addons.CatalogueRefused):
        addons.parse_catalogue(raw, SHA)


def test_a_catalogue_made_for_another_release_is_refused():
    with pytest.raises(addons.CatalogueRefused):
        addons.parse_catalogue(document(entry(), release="fedcba654321"), SHA)


@pytest.mark.parametrize("bad", [
    entry("Bad Code"), entry("x;reboot"), entry("ea_platform_admin"), entry("a" * 41), entry(name="n" * 301),
    entry(optional="yes"), {"code": "ea_client_x"}, {**entry(), "extra": 1},
])
def test_a_bad_entry_refuses_the_file(bad):
    with pytest.raises(addons.CatalogueRefused):
        addons.parse_catalogue(document(bad), SHA)


def test_too_many_optional_add_ons_or_a_duplicate_are_refused():
    with pytest.raises(addons.CatalogueRefused):
        addons.parse_catalogue(document(*[entry(f"ea_client_{n}") for n in range(25)]), SHA)
    with pytest.raises(addons.CatalogueRefused):
        addons.parse_catalogue(document(entry(), entry()), SHA)


def test_the_answer_only_holds_what_the_running_release_carries():
    assert addons.desired_answer(["a_b", "c_d"], ["c_d", "e_f"]) == ["c_d"]
    assert addons.desired_answer([], ["c_d"]) == []


@pytest.mark.parametrize("desired,reported,known,in_release,changed,expected", [
    (True, True, True, True, None, addons.ON),
    (False, False, True, True, None, addons.OFF),
    (False, False, False, True, None, addons.OFF),
    (True, False, True, True, NOW - timedelta(minutes=10), addons.SWITCHING_ON),
    (False, True, True, True, NOW - timedelta(minutes=10), addons.SWITCHING_OFF),
    (True, False, True, True, NOW - timedelta(hours=2), addons.DIFFERS_ON),
    (False, True, True, True, NOW - timedelta(hours=2), addons.DIFFERS_OFF),
    (False, True, True, True, None, addons.DIFFERS_OFF),
    (True, False, False, True, NOW - timedelta(hours=2), addons.DIFFERS_ON),
    (True, True, True, False, None, addons.NOT_IN_RELEASE),
])
def test_how_an_add_on_stands(desired, reported, known, in_release, changed, expected):
    assert addons.line_status(desired, reported, known, in_release, changed, NOW) == expected


def test_a_reported_code_outside_the_catalogue_is_counted_and_not_kept():
    assert addons.split_reported(["ea_client_a", "client_acme_sarl"], {"ea_client_a"}) == (["ea_client_a"], 1)
    assert addons.split_reported(None, {"ea_client_a"}) == ([], 0)


def figures(**changes):
    return {**healthy_figures(NOW, SHA), **changes}


def test_the_heartbeat_takes_codes_and_nothing_else():
    assert heartbeat.parse_figures(json.dumps(figures(addons_on=["ea_client_a"], addons_refused=0)).encode())
    assert heartbeat.parse_figures(json.dumps(figures()).encode())  # a firm on an older release


@pytest.mark.parametrize("value", [
    "ea_client_a", ["Client Agro SA"], ["x" * 41], [1], [None], ["ea_client_a", "ea_client_a"],
    [f"ea_client_{n}" for n in range(25)], {"a": 1},
])
def test_free_text_as_an_add_on_rejects_the_heartbeat(value):
    with pytest.raises(heartbeat.HeartbeatRejected) as caught:
        heartbeat.parse_figures(json.dumps(figures(addons_on=value)).encode())
    assert caught.value.code == "bad_value"


def test_every_add_on_a_release_may_carry_fits_in_a_heartbeat():
    codes = [f"ea_client_{n:02d}_{'x' * 27}" for n in range(addons.MAX_OPTIONAL)]
    assert all(addons.CODE.match(code) and len(code) == 40 for code in codes)
    body = json.dumps(figures(
        addons_on=codes, addons_refused=1000, export_sha256="a" * 64, update_release="a" * 40, release="a" * 40,
    ), sort_keys=True, separators=(",", ":")).encode()
    assert len(body) <= heartbeat.MAX_BODY_BYTES
    assert heartbeat.parse_figures(body)


def base_input(**changes):
    return {
        "state": "active", "last_heartbeat_at": NOW, "last_backup_at": NOW, "last_backup_ok": True,
        "last_restore_test_at": NOW, "last_restore_test_ok": True, "cert_expires_on": NOW.date() + timedelta(days=80),
        "backup_key_escrowed": True, **changes,
    }


@pytest.mark.parametrize("key,word", [("addons_differ", "not as asked"), ("addons_refused", "refused"), ("addons_unknown", "outside")])
def test_an_add_on_difference_is_an_attention_reason(key, word):
    colour, reasons = health.evaluate(base_input(**{key: 2}), NOW)
    assert colour == health.AMBER
    assert word in reasons[0]


def test_no_difference_stays_green():
    assert health.evaluate(base_input(addons_differ=0, addons_refused=0, addons_unknown=0), NOW)[0] == health.GREEN


@pytest.mark.parametrize("last,ok,expected", [
    (None, None, "none"),
    (NOW, False, "failed"),
    (NOW - timedelta(hours=60), True, "missed"),
    (NOW - timedelta(hours=30), True, "late"),
    (NOW - timedelta(hours=2), True, "ok"),
])
def test_backup_state(last, ok, expected):
    assert health.backup_state(last, ok, NOW) == expected


def scripts():
    return [*(ROOT / "deploy/firm").glob("*.sh"), ROOT / "scripts/provision/build_release.sh"]


def test_nothing_on_a_firm_ever_uninstalls():
    """Owner's ruling: off hides and keeps. Odoo's uninstall drops tables."""
    pattern = re.compile(r"button_immediate_uninstall|button_uninstall|module_uninstall|--uninstall|\buninstall\b", re.I)
    code_paths = [
        *scripts(),
        *(ROOT / "addons/ea_audit_addons").rglob("*.py"),
        *(ROOT / "addons/ea_audit_firm_agent").rglob("*.py"),
        *(ROOT / "addons/ea_client_addon_sample/models").rglob("*.py"),
    ]
    for path in code_paths:
        if "tests" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#") or '"""' in line:
                continue
            assert not pattern.search(line) or "NOTHING" in line or "uninstall drops" in line, f"{path.name}:{number}"


def test_reports_are_listed_but_no_switch_can_reach_them():
    assert manifest("ea_audit_reports").get("ea_client_addon") is None
    script = (ROOT / "deploy/firm/firm-addons.sh").read_text(encoding="utf-8")
    assert 'data.get("ea_client_addon") is True' in script


def test_root_script_is_installed_and_shares_the_shape_of_a_code():
    install = (ROOT / "deploy/firm/install-firm-server.sh").read_text(encoding="utf-8")
    assert "firm-addons.sh" in install
    shape = "[a-z][a-z0-9_]{2,39}"
    assert shape in (ROOT / "deploy/firm/firm-addons.sh").read_text(encoding="utf-8")
    assert shape in (ROOT / "deploy/firm/firm-apply-desired.sh").read_text(encoding="utf-8")
    assert addons.CODE.pattern == f"^{shape}$"
    assert (ROOT / "deploy/firm/firm-update.sh").read_text(encoding="utf-8").count('"ea_client_addon"') == 1
