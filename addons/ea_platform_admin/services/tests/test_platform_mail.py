"""The platform email address (services/platform_mail.py): the rules, the two APIs with a fake transport,
the simulation, and one pass of the set-up and of the removal. Pure, and never a network connection."""

import json
import socket

import pytest

from .. import mail_settings, platform_mail as pm
from .. import provisioning as engine
from ..provider import ProviderError
from ..provider_vultr import HttpResponse

SECRET = "SECRET-MAILERSEND-TOKEN"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to open a network connection")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


class FakeTransport:
    """Answers by (method, fragment of the address); the first match wins. Keeps every request."""

    def __init__(self, answers=()):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, method, url, headers, body):
        self.requests.append((method, url, headers, json.loads(body) if body else None))
        for m, fragment, answer in self.answers:
            if m == method and fragment in url:
                return answer
        return HttpResponse(200, b"{}")


def ok(payload, status=200):
    return HttpResponse(status, json.dumps(payload).encode())


DNS_ANSWER = {"data": {
    "id": "dom1",
    "spf": {"hostname": "cab.cm-ea.com", "type": "TXT", "value": "v=spf1 include:_spf.mailersend.net ~all"},
    "dkim": {"hostname": None, "type": None, "value": None},
    "dkim_ms1": {"hostname": "ms1._domainkey.cab.cm-ea.com", "type": "CNAME", "value": "ms1._domainkey.mailersend.net"},
    "dkim_ms2": {"hostname": "ms2._domainkey.cab.cm-ea.com", "type": "CNAME", "value": "ms2._domainkey.mailersend.net"},
    "return_path": {"hostname": "mta.cab.cm-ea.com", "type": "CNAME", "value": "mailersend.net"},
    "custom_tracking": {"hostname": "email.cab.cm-ea.com", "type": "CNAME", "value": "links.mailersend.net"},
    "inbound_routing": {"hostname": "inbound.cab.cm-ea.com", "type": "MX", "value": "inbound.mailersend.net"},
}}


# --------------------------------------------------------------------- rules


def test_the_address_is_built_from_the_slug_and_the_parent_domain():
    assert pm.subdomain("cab", " CM-EA.com. ") == "cab.cm-ea.com"
    assert pm.sender("support", "cab.cm-ea.com") == "support@cab.cm-ea.com"
    assert pm.sender("", "cab.cm-ea.com") == "support@cab.cm-ea.com"


def test_parent_domain_and_sender_name_are_checked():
    assert pm.parent_errors("cm-ea.com") == []
    assert pm.parent_errors("not a domain") and pm.parent_errors("")
    assert pm.local_part_errors("support") == [] and pm.local_part_errors("no-reply") == []
    assert pm.local_part_errors("sup port") and pm.local_part_errors("x@y")


def test_reply_to_follows_the_policy():
    assert pm.reply_to("contact", " awa@exemple.cm ") == "awa@exemple.cm"
    assert pm.reply_to("none", "awa@exemple.cm") == ""
    assert pm.reply_to("contact", "not an address") == ""


def test_the_practice_allowlist_takes_addresses_only():
    addresses, errors = pm.parse_allowlist("Owner@Exemple.cm\nowner@exemple.cm, test@cm-ea.com")
    assert addresses == ["owner@exemple.cm", "test@cm-ea.com"] and errors == []
    _addresses, errors = pm.parse_allowlist("owner@exemple.cm nonsense")
    assert len(errors) == 1
    assert pm.parse_allowlist("") == ([], [])
    assert pm.allowed("OWNER@exemple.cm", ["owner@exemple.cm"])
    assert not pm.allowed("other@exemple.cm", ["owner@exemple.cm"])
    assert not pm.allowed("owner@exemple.cm", [])


def test_the_checks_back_off_to_once_an_hour():
    assert [pm.next_check_minutes(n) for n in range(9)] == [1, 2, 5, 10, 15, 30, 60, 60, 60]


def test_only_txt_and_cname_inside_the_firms_subdomain_are_kept():
    answer = json.loads(json.dumps(DNS_ANSWER))
    answer["data"]["return_path"]["hostname"] = "www.cm-ea.com"  # outside: refused
    records = pm.records_from_answer(answer, "cab.cm-ea.com")
    assert {r["name"] for r in records} == {
        "cab.cm-ea.com", "ms1._domainkey.cab.cm-ea.com", "ms2._domainkey.cab.cm-ea.com", "email.cab.cm-ea.com"}
    assert all(r["type"] in ("TXT", "CNAME") for r in records)


def test_the_platform_settings_pass_the_firms_own_checks():
    """What the firm's server receives is what the existing "Email for this firm" rules accept."""
    values = {"host": pm.SMTP_HOST, "port": pm.SMTP_PORT, "encryption": pm.SMTP_ENCRYPTION,
              "user": "MS_abc@cab.cm-ea.com", "password": "x" * 30, "sender": "support@cab.cm-ea.com"}
    assert mail_settings.errors(values) == {}


# --------------------------------------------------------------------- the real clients, fake transport


def test_mailersend_calls_the_documented_endpoints_and_hides_its_token():
    transport = FakeTransport([
        ("GET", "/domains?limit=100&page=1", ok({"data": [], "meta": {"last_page": 1}})),
        ("POST", "/domains/dom1/smtp-users", ok({"data": {"id": "u1", "username": "MS_x@cab.cm-ea.com", "password": "pw"}}, 201)),
        ("POST", "/domains", ok({"data": {"id": "dom1", "name": "cab.cm-ea.com"}}, 201)),
        ("GET", "/domains/dom1/dns-records", ok(DNS_ANSWER)),
        ("GET", "/domains/dom1/verify", ok({"message": "The domain is verified.", "data": {"spf": True, "dkim": True}})),
        ("GET", "/domains/dom1/smtp-users", ok({"data": []})),
    ])
    client = pm.MailerSend(SECRET, transport=transport)
    assert SECRET not in repr(client)
    assert client.find_domain("cab.cm-ea.com") is None
    assert client.create_domain("cab.cm-ea.com") == "dom1"
    assert len(client.dns_records("dom1", "cab.cm-ea.com")) == 5
    assert client.verify("dom1") is True
    assert client.find_smtp_user("dom1", "AuditISA") is None
    assert client.create_smtp_user("dom1", "AuditISA") == ("u1", "MS_x@cab.cm-ea.com", "pw")
    urls = [(m, u.replace(pm.MAILERSEND_API, "")) for m, u, _h, _b in transport.requests]
    assert ("POST", "/domains") in urls and ("GET", "/domains/dom1/verify") in urls
    assert transport.requests[1][3] == {"name": "cab.cm-ea.com"}
    assert all(h["Authorization"] == f"Bearer {SECRET}" for _m, _u, h, _b in transport.requests)


def test_a_domain_not_verified_yet_says_so():
    transport = FakeTransport([("GET", "/verify", ok({"message": "The domain was not verified, please check your DNS "
                                                                 "records and try again.", "data": {"spf": False}}))])
    assert pm.MailerSend(SECRET, transport=transport).verify("dom1") is False


def test_refusals_are_said_in_our_words_and_never_quote_the_answer():
    body = json.dumps({"message": f"domain limit reached {SECRET}"}).encode()
    client = pm.MailerSend(SECRET, transport=FakeTransport([("POST", "/domains", HttpResponse(422, body))]))
    with pytest.raises(ProviderError) as error:
        client.create_domain("cab.cm-ea.com")
    assert "plan" in str(error.value) and SECRET not in str(error.value)
    client = pm.MailerSend(SECRET, transport=FakeTransport([("GET", "/domains", HttpResponse(401, b"{}"))]))
    with pytest.raises(ProviderError) as error:
        client.check()
    assert "token" in str(error.value) and not error.value.retryable
    client = pm.MailerSend(SECRET, transport=FakeTransport([("GET", "/domains", HttpResponse(503, b""))]))
    with pytest.raises(ProviderError) as error:
        client.check()
    assert error.value.retryable


def test_cloudflare_looks_up_the_zone_and_writes_dns_only_records():
    transport = FakeTransport([
        ("GET", "/user/tokens/verify", ok({"result": {"status": "active"}})),
        ("GET", "/zones?name=cm-ea.com", ok({"result": [{"id": "z1"}]})),
        ("GET", "/dns_records?type=TXT", ok({"result": [{"id": "r1", "content": '"v=spf1 include:_spf.mailersend.net ~all"'}]})),
        ("GET", "/dns_records?type=CNAME", ok({"result": []})),
        ("POST", "/dns_records", ok({"result": {"id": "r2"}})),
    ])
    zone = pm.CloudflareZone(SECRET, transport=transport)
    assert zone.check() is True
    assert zone.find_zone("cm-ea.com") == "z1"
    zone.zone_id = "z1"
    written = pm.write_records(zone, pm.records_from_answer(DNS_ANSWER, "cab.cm-ea.com"))
    assert len(written) == 5
    posts = [body for method, _u, _h, body in transport.requests if method == "POST"]
    assert len(posts) == 4, "the SPF record was already right: not written again"
    assert all(body["proxied"] is False and body["ttl"] == pm.DNS_TTL for body in posts)
    assert SECRET not in repr(zone)


def test_cloudflare_without_a_zone_refuses_plainly():
    with pytest.raises(ProviderError):
        pm.CloudflareZone(SECRET, transport=FakeTransport()).find("TXT", "cab.cm-ea.com")


def test_a_wrong_cname_is_corrected_not_doubled():
    zone = pm.DryRunZone()
    zone.create("CNAME", "mta.cab.cm-ea.com", "old.example.net")
    pm.write_records(zone, [{"type": "CNAME", "name": "mta.cab.cm-ea.com", "content": "mailersend.net"}])
    assert [r["content"] for r in zone.state["records"].values()] == ["mailersend.net"]


# --------------------------------------------------------------------- one pass, simulated


def test_setup_runs_to_the_end_and_is_safe_to_run_again():
    ms, zone = pm.DryRunMailerSend(), pm.DryRunZone()
    state = {"domain": "cab.cm-ea.com"}
    phase, credentials = pm.setup(ms, zone, state)
    assert phase == "ready"
    assert credentials["host"] == "smtp.mailersend.net" and credentials["port"] == 587
    assert credentials["user"].endswith("@cab.cm-ea.com") and credentials["password"]
    assert len(zone.state["records"]) == 4
    assert pm.setup(ms, zone, state) == ("done", None)
    assert len(zone.state["records"]) == 4 and len(ms.state["domains"]) == 1


def test_setup_waits_for_the_domain_check_and_resumes():
    ms, zone = pm.DryRunMailerSend(), pm.DryRunZone()
    ms.state["verify_after"] = 3
    state = {"domain": "cab.cm-ea.com"}
    assert pm.setup(ms, zone, state) == ("verifying", None)
    assert pm.setup(ms, zone, state) == ("verifying", None)
    assert pm.setup(ms, zone, state)[0] == "ready"
    assert ms.calls.count("create_domain") == 1 and zone.calls.count("create") == 4


def test_a_crash_after_the_smtp_user_was_made_gives_a_new_one():
    ms, zone = pm.DryRunMailerSend(), pm.DryRunZone()
    state = {"domain": "cab.cm-ea.com"}
    pm.setup(ms, zone, state)
    state.pop("smtp_user_id")  # the answer was lost
    phase, _credentials = pm.setup(ms, zone, state)
    assert phase == "ready"
    domain = next(iter(ms.state["domains"].values()))
    assert len(domain["smtp"]) == 1


def test_a_temporary_fault_leaves_a_resumable_state():
    ms, zone = pm.DryRunMailerSend(), pm.DryRunZone(fail_on={"create": 1})
    state = {"domain": "cab.cm-ea.com"}
    with pytest.raises(ProviderError) as error:
        pm.setup(ms, zone, state)
    assert error.value.retryable and state.get("domain_id") and not state.get("dns")
    assert pm.setup(ms, zone, state)[0] == "ready"
    assert len(zone.state["records"]) == 4


def test_a_domain_deleted_at_mailersend_is_made_again():
    ms, zone = pm.DryRunMailerSend(), pm.DryRunZone()
    state = {"domain": "cab.cm-ea.com"}
    pm.setup(ms, zone, state)
    ms.state["domains"].clear()
    assert pm.setup(ms, zone, state)[0] == "ready"
    assert len(zone.state["records"]) == 4


def test_remove_takes_away_everything_and_only_the_firms_names():
    ms, zone = pm.DryRunMailerSend(), pm.DryRunZone()
    zone.create("A", "www.cm-ea.com", "192.0.2.1")
    zone.create("TXT", "cm-ea.com", "v=spf1 -all")
    state = {"domain": "cab.cm-ea.com"}
    pm.setup(ms, zone, state)
    assert pm.remove(ms, zone, state) == []
    assert ms.state["domains"] == {}
    assert sorted(r["name"] for r in zone.state["records"].values()) == ["cm-ea.com", "www.cm-ea.com"]
    assert pm.remove(ms, zone, state) == [], "removing twice is harmless"


def test_remove_reports_what_stays():
    ms, zone = pm.DryRunMailerSend(fail_on={"delete_domain": ProviderError("refused")}), pm.DryRunZone()
    state = {"domain": "cab.cm-ea.com"}
    pm.setup(ms, zone, state)
    leftovers = pm.remove(ms, zone, state)
    assert len(leftovers) == 1 and "MailerSend domain" in leftovers[0]
    assert zone.state["records"] == {}


def test_the_simulated_test_email_needs_a_verified_domain():
    ms = pm.DryRunMailerSend()
    ms.state["verify_after"] = 2
    state = {"domain": "cab.cm-ea.com"}
    pm.setup(ms, pm.DryRunZone(), state)
    with pytest.raises(ProviderError):
        ms.send_test("support@cab.cm-ea.com", "Cabinet", "owner@exemple.cm", "", "Test", "Test")
    pm.setup(ms, pm.DryRunZone(), state)
    assert ms.send_test("support@cab.cm-ea.com", "Cabinet", "owner@exemple.cm", "", "Test", "Test")
    assert ms.state["sent"] == 1


# --------------------------------------------------------------------- the provisioning step


def test_the_step_is_in_the_list_after_the_address():
    codes = engine.STEP_CODES
    assert codes.index("platform_mail") == codes.index("dns") + 1


def test_the_step_never_stops_a_firm_and_hands_over_to_its_hook():
    seen = []
    ctx = engine.Context(None, None, None, {}, {"platform_mail": lambda: seen.append("run")}, {}, None)
    step = next(s for s in engine.PIPELINE if s.code == "platform_mail")
    step.do(ctx)
    step.undo(ctx)  # no undo hook given: nothing to do
    assert seen == ["run"]
    ctx = engine.Context(None, None, None, {}, {}, {}, None)
    step.do(ctx)  # an older caller without the hook: nothing to do


def test_cloudflare_accepts_an_account_token():
    """Cloudflare's newer screen makes account tokens: /user/tokens/verify refuses them, the zones answer."""
    transport = FakeTransport([
        ("GET", "/user/tokens/verify", HttpResponse(401, json.dumps({"success": False, "errors": [{"message": "Invalid API Token"}]}).encode())),
        ("GET", "/zones?per_page=1", ok({"result": [{"id": "z1"}]})),
    ])
    assert pm.CloudflareZone(SECRET, transport=transport).check() is True
    wrong = FakeTransport([
        ("GET", "/user/tokens/verify", HttpResponse(401, b"{}")),
        ("GET", "/zones?per_page=1", HttpResponse(401, b"{}")),
    ])
    with pytest.raises(ProviderError):
        pm.CloudflareZone(SECRET, transport=wrong).check()
