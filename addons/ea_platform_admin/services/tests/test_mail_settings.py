"""The "Email for this firm" screen's checks agree with what the firm's server accepts (deploy/firm/firm_mail.py).

The console refuses in plain words before anything leaves; the firm's server checks again with its own
rules. If the two disagreed, an operator would be told "sent" for settings the firm then refuses, or the
reverse. Pure: no Odoo.
"""

import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest

from .. import heartbeat, mail_handoff, mail_settings

ROOT = Path(__file__).parents[4]


def _load_firm_mail():
    spec = importlib.util.spec_from_file_location("firm_mail_under_test", ROOT / "deploy" / "firm" / "firm_mail.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


firm_mail = _load_firm_mail()

GOOD = {
    "host": "smtp.office365.com", "port": 587, "encryption": "starttls",
    "user": "cabinet@exemple.cm", "password": "Un mot de passe: avec = et #", "sender": "cabinet@exemple.cm",
}

CASES = [
    {},
    {"host": "SMTP.Gmail.com", "port": 465, "encryption": "ssl"},
    {"user": "", "password": ""},
    {"sender": "exemple.cm"},
    {"port": "587"},
    {"host": "8.8.8.8"},
    {"host": "10.0.0.5"},
    {"host": "127.0.0.1"},
    {"host": "169.254.169.254"},
    {"host": "::1"},
    {"host": "localhost"},
    {"host": "mail.localhost"},
    {"host": "smtp"},
    {"host": "smtp..example.com"},
    {"host": "-smtp.example.com"},
    {"host": ""},
    {"port": 22},
    {"port": 0},
    {"port": 2525},
    {"port": 25},
    {"encryption": "none"},
    {"encryption": "tls"},
    {"encryption": ""},
    {"user": "", "password": "seul"},
    {"user": "seul@exemple.cm", "password": ""},
    {"user": "deux mots"},
    {"password": "x" * 512},
    {"password": "x" * 513},
    {"password": "avec\nune ligne"},
    {"password": "avec\ttab"},
    {"password": "accentué é ü"},
    {"sender": "pas une adresse"},
    {"sender": "a@b"},
    {"sender": ""},
    {"sender": "Cabinet <cabinet@exemple.cm>"},
]


def _firm_accepts(values):
    data = mail_settings.clean(values)
    try:
        text = firm_mail.env_text(data["host"], data["port"], data["encryption"], data["user"], data["password"], data["sender"])
        firm_mail.parse(text)
    except firm_mail.MailFileError:
        return False
    return True


@pytest.mark.parametrize("change", CASES, ids=[json.dumps(case, ensure_ascii=True)[:60] for case in CASES])
def test_the_console_and_the_firm_s_server_agree(change):
    values = {**GOOD, **change}
    console_accepts = not mail_settings.errors(values)
    assert console_accepts == _firm_accepts(values)


def test_the_good_settings_are_accepted_and_the_bad_ones_named_in_plain_words():
    assert mail_settings.errors(GOOD) == {}
    found = mail_settings.errors({**GOOD, "host": "10.0.0.5", "port": 22, "encryption": "none", "sender": "x"})
    assert set(found) == {"host", "port", "encryption", "sender"}
    assert found["host"][0].startswith("Server:")
    assert found["port"][0].startswith("Port:")
    together = mail_settings.errors({**GOOD, "password": ""})
    assert "go together" in together["password"][0]


def test_every_preset_passes_and_fills_server_port_and_encryption():
    for code, _label in mail_settings.PRESET_CHOICES:
        preset = mail_settings.preset(code)
        if code == "other":
            assert preset == {}
            continue
        assert set(preset) == {"host", "port", "encryption"}
        assert mail_settings.errors({**GOOD, **preset}) == {}
    assert mail_settings.preset("microsoft365")["host"] == "smtp.office365.com"
    assert mail_settings.preset("google")["host"] == "smtp.gmail.com"


def test_the_summary_never_holds_the_password():
    line = mail_settings.summary(GOOD)
    assert line == "smtp.office365.com:587 STARTTLS, cabinet@exemple.cm"
    assert GOOD["password"] not in line
    assert mail_settings.summary({**GOOD, "sender": "noreply@exemple.cm"}).endswith("cabinet@exemple.cm, noreply@exemple.cm")


def test_an_optional_step_left_empty_is_not_filled():
    assert not mail_settings.filled({"port": 587, "encryption": "starttls"})
    assert mail_settings.filled({"password": "x"})


def test_every_state_has_its_plain_message_and_the_words_agree_everywhere():
    states = [code for code, _label in mail_settings.STATES]
    assert set(states) == set(mail_settings.MESSAGES)
    assert set(mail_settings.RESULTS) <= set(states)
    assert tuple(heartbeat.MAIL_RESULTS) == tuple(mail_settings.RESULTS)
    agent = (ROOT / "addons" / "ea_audit_firm_agent" / "services" / "collect.py").read_text(encoding="utf-8")
    assert 'MAIL_RESULTS = ("on", "off", "login", "connect", "tls", "sender", "staging", "refused", "failed")' in agent
    script = (ROOT / "deploy" / "firm" / "firm-mail-server.sh").read_text(encoding="utf-8")
    for word in ("login|connect|tls|sender", "report on", "report off", "stop staging", "stop refused", "stop failed"):
        assert word in script


def test_the_heartbeat_carries_the_answer_as_a_reference_and_one_word():
    assert heartbeat.FIGURES["mail_request_ref"]("0123456789abcdef")
    assert not heartbeat.FIGURES["mail_request_ref"]("Cabinet Agro SA")
    assert heartbeat.FIGURES["mail_request_result"]("login")
    assert not heartbeat.FIGURES["mail_request_result"]("Authentication failed for cabinet@agro.cm")


# ---------------------------------------------------------------------- the request, on the firm's side

def _request(**changes):
    settings = mail_settings.settings(GOOD)
    return json.dumps({"ref": "0123456789abcdef", "action": "set", **settings, **changes})


def test_the_firm_reads_the_console_s_request_with_its_own_rules():
    ref, action, text = firm_mail.read_request(_request())
    assert (ref, action) == ("0123456789abcdef", "set")
    parsed = firm_mail.parse(text)
    assert parsed["password"] == GOOD["password"]
    assert parsed["host"] == "smtp.office365.com"
    assert parsed["from_filter"] == "cabinet@exemple.cm"
    assert firm_mail.read_request(json.dumps({"ref": "0123456789abcdef", "action": "off"})) == ("0123456789abcdef", "off", None)


@pytest.mark.parametrize("bad", [
    {"host": "10.0.0.5"},
    {"port": "587"},
    {"encryption": "none"},
    {"password": "a\nMAIL_HOST=10.0.0.5"},
    {"user": "x\nMAIL_DEBUG=1"},
    {"action": "run"},
    {"extra": "rm -rf /"},
])
def test_a_bad_request_is_refused_under_its_reference_and_never_quotes_the_password(bad):
    with pytest.raises(firm_mail.RequestRefused) as caught:
        firm_mail.read_request(_request(**bad))
    assert caught.value.ref == "0123456789abcdef"
    assert GOOD["password"] not in str(caught.value)


def test_a_request_without_a_reference_cannot_be_answered():
    for text in ("not json", "[]", json.dumps({"ref": "XYZ", "action": "off"})):
        with pytest.raises(firm_mail.MailFileError) as caught:
            firm_mail.read_request(text)
        assert not isinstance(caught.value, firm_mail.RequestRefused)


def test_the_spool_file_is_erased_and_the_settings_written_for_root_only(tmp_path, capsys):
    spool, target = tmp_path / "mail.json", tmp_path / "mail.env"
    spool.write_text(_request(), encoding="utf-8")
    assert firm_mail.main(["firm_mail.py", "request", str(spool), str(target)]) == 0
    assert capsys.readouterr().out.strip() == "0123456789abcdef set"
    assert not spool.exists()
    if os.name == "posix":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert firm_mail.parse(target.read_text(encoding="utf-8"))["password"] == GOOD["password"]
    spool.write_text(_request(host="10.0.0.5"), encoding="utf-8")
    assert firm_mail.main(["firm_mail.py", "request", str(spool), str(tmp_path / "other.env")]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "0123456789abcdef refused"
    assert GOOD["password"] not in captured.out + captured.err
    assert not spool.exists() and not (tmp_path / "other.env").exists()
    spool.write_text("garbage", encoding="utf-8")
    assert firm_mail.main(["firm_mail.py", "request", str(spool), str(target)]) == 2
    assert not spool.exists()


# ---------------------------------------------------------------------- the waiting file, on the console

def test_the_waiting_files_are_private_and_named_safely(tmp_path):
    folder = str(tmp_path / "firm-mail")
    name = mail_handoff.firm_name("cabinet-a")
    mail_handoff.store(folder, name, b"sealed")
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(folder).st_mode) == 0o700
        assert stat.S_IMODE(os.stat(os.path.join(folder, name)).st_mode) == 0o600
    assert mail_handoff.read(folder, name) == b"sealed"
    assert mail_handoff.take(folder, name) == b"sealed"
    assert mail_handoff.take(folder, name) is None
    for bad in ("../etc/passwd", "firm-", "firm-A", "cabinet-a", "form-x--y-1", "firm-cabinet-a/../x"):
        with pytest.raises(ValueError):
            mail_handoff.path(folder, bad)
    assert mail_handoff.form_name("platform_firm_mail_wizard", 12) == "form-platform-firm-mail-wizard-12"
    mail_handoff.path(folder, mail_handoff.form_name("platform_onboarding_wizard", 3))


def test_the_sweep_erases_old_files_of_one_kind_only(tmp_path):
    folder = str(tmp_path)
    mail_handoff.store(folder, "form-platform-firm-mail-wizard-1", b"a")
    mail_handoff.store(folder, "firm-cabinet-a", b"b")
    now = os.path.getmtime(os.path.join(folder, "firm-cabinet-a"))
    assert mail_handoff.sweep(folder, 3600, prefix="form-", now=now + 10) == []
    assert mail_handoff.sweep(folder, 3600, prefix="form-", now=now + 7200) == ["form-platform-firm-mail-wizard-1"]
    assert mail_handoff.sweep(folder, 6 * 3600, prefix="firm-", now=now + 7200) == []
    assert mail_handoff.sweep(str(tmp_path / "none"), 1) == []
