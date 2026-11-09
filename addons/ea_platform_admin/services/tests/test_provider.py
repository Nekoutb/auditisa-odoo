import base64
import json
import os
import socket
from pathlib import Path

import pytest

from ..provider import (
    DnsProvider,
    DryRunDns,
    DryRunProbe,
    DryRunProvider,
    ProviderError,
    ServerProvider,
    ServerSpec,
    StorageCredentials,
)
from ..provider_vultr import CloudflareDns, HttpResponse, VultrProvider, read_secret_file

SECRET_TOKEN = "SECRET-TOKEN-VALUE"


def spec(label="auditisa-firm-a", user_data="#cloud-config"):
    return ServerSpec(label=label, hostname="a.auditisa.com", region="cdg", plan="vc2-4c-8gb", os_id=1,
                      user_data=user_data, ssh_key_id="k", firewall_id="f", tags=["auditisa-firm"])


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """No test here may open a connection: real Vultr and Cloudflare are never called."""
    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to open a network connection")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


class FakeTransport:
    def __init__(self, answers=None):
        self.answers = answers or {}
        self.requests = []

    def __call__(self, method, url, headers, body):
        self.requests.append((method, url, headers, json.loads(body) if body else None))
        for (m, fragment), answer in self.answers.items():
            if m == method and fragment in url:
                return answer
        return HttpResponse(200, b"{}")


def ok(payload, status=200):
    return HttpResponse(status, json.dumps(payload).encode())


def test_implementations_satisfy_the_interfaces():
    assert issubclass(DryRunProvider, ServerProvider)
    assert issubclass(VultrProvider, ServerProvider)
    assert issubclass(DryRunDns, DnsProvider)
    assert issubclass(CloudflareDns, DnsProvider)
    assert DryRunProvider().is_simulation is True
    assert VultrProvider("t", transport=FakeTransport()).is_simulation is False


def test_dry_run_finds_what_it_created():
    provider = DryRunProvider()
    assert provider.find_ssh_key("a") is None
    key_id = provider.create_ssh_key("a", "ssh-ed25519 x")
    assert provider.find_ssh_key("a") == key_id
    server = provider.create_server(spec())
    assert provider.find_server("auditisa-firm-a").id == server.id
    assert provider.get_server(server.id).status == "active"
    assert server.ip.startswith("203.0.113.")
    assert [s.id for s in provider.list_servers("auditisa-firm")] == [server.id]


def test_dry_run_destroy_and_stop():
    provider = DryRunProvider()
    server = provider.create_server(spec())
    provider.stop_server(server.id)
    assert provider.get_server(server.id).status == "stopped"
    provider.start_server(server.id)
    assert provider.get_server(server.id).status == "active"
    provider.destroy_server(server.id)
    assert provider.get_server(server.id) is None
    assert provider.list_servers("auditisa-firm") == []


def test_dry_run_boots_after_some_polls():
    provider = DryRunProvider(boot_polls=2)
    server = provider.create_server(spec())
    assert server.status == "pending"
    assert provider.get_server(server.id).status == "pending"
    assert provider.get_server(server.id).status == "active"


def test_dry_run_state_outlasts_the_object():
    first = DryRunProvider()
    server = first.create_server(spec())
    second = DryRunProvider(state=json.loads(json.dumps(first.state)))
    assert second.get_server(server.id).id == server.id


def test_dry_run_failures_are_injected():
    provider = DryRunProvider(fail_on={"create_server": 1})
    with pytest.raises(ProviderError) as caught:
        provider.create_server(spec())
    assert caught.value.retryable
    assert provider.create_server(spec())
    always = DryRunProvider(fail_on={"create_server": ProviderError("non", retryable=False)})
    with pytest.raises(ProviderError):
        always.create_server(spec())


def test_dry_run_firewall_opens_22_only_to_the_list():
    provider = DryRunProvider()
    firewall_id = provider.create_firewall("a", ["198.51.100.7/32"])
    rules = provider.state["firewalls"][firewall_id]["rules"]
    assert {"port": 22, "from": "198.51.100.7/32"} in rules
    assert not [r for r in rules if r["port"] == 22 and r["from"] == "any"]
    assert {"port": 443, "from": "any"} in rules


def test_dry_run_gives_each_storage_its_own_credentials():
    provider = DryRunProvider()
    first = provider.storage_credentials(provider.create_storage("a", "cdg"))
    second = provider.storage_credentials(provider.create_storage("b", "cdg"))
    assert first.bucket != second.bucket
    assert first.access_key != second.access_key
    assert first.secret_key != second.secret_key


def test_credentials_do_not_print_their_secret():
    credentials = StorageCredentials("e", "b", "ACCESS-VALUE", "SECRET-VALUE")
    assert "SECRET-VALUE" not in repr(credentials)
    assert "ACCESS-VALUE" not in repr(credentials)


def test_dry_run_dns():
    dns = DryRunDns()
    assert dns.find_record("a.auditisa.com") is None
    dns.upsert_a_record("a.auditisa.com", "203.0.113.1")
    assert dns.find_record("a.auditisa.com") == "203.0.113.1"
    dns.delete_record("a.auditisa.com")
    assert dns.find_record("a.auditisa.com") is None


def test_dry_run_probe_answers_like_a_good_server_unless_told_otherwise():
    probe = DryRunProbe()
    assert probe.status_code("https://a/web/health") == 200
    assert probe.status_code("http://a/") == 301
    assert probe.status_code("https://a/web/database/manager") == 404
    assert DryRunProbe({"/web/health": 502}).status_code("https://a/web/health") == 502


# ---------------------------------------------------------------- Vultr, on a fake transport only


def test_vultr_creates_a_server_with_the_official_shape():
    transport = FakeTransport({("POST", "/instances"): ok({"instance": {
        "id": "uuid-1", "label": "l", "status": "pending", "main_ip": "0.0.0.0", "default_password": "ROOT-PASSWORD",
    }}, 202)})
    server = VultrProvider(SECRET_TOKEN, transport=transport).create_server(spec(user_data="hello"))
    method, url, headers, payload = transport.requests[0]
    assert (method, url) == ("POST", "https://api.vultr.com/v2/instances")
    assert headers["Authorization"] == f"Bearer {SECRET_TOKEN}"
    assert base64.b64decode(payload["user_data"]) == b"hello"
    assert payload["sshkey_id"] == ["k"]
    assert payload["firewall_group_id"] == "f"
    assert payload["enable_ipv6"] is False
    assert server.id == "uuid-1"
    assert server.ip == ""
    assert "ROOT-PASSWORD" not in repr(server)


def test_vultr_reads_a_stopped_server():
    transport = FakeTransport({("GET", "/instances/x"): ok({"instance": {
        "id": "x", "status": "active", "power_status": "stopped", "main_ip": "1.2.3.4"}})})
    assert VultrProvider("t", transport=transport).get_server("x").status == "stopped"


def test_vultr_missing_server_is_none():
    transport = FakeTransport({("GET", "/instances/x"): HttpResponse(404)})
    assert VultrProvider("t", transport=transport).get_server("x") is None


def test_vultr_finds_by_label_exactly():
    transport = FakeTransport({("GET", "/instances"): ok({"instances": [
        {"id": "1", "label": "auditisa-firm-ab", "status": "active"},
        {"id": "2", "label": "auditisa-firm-a", "status": "active"},
    ]})})
    assert VultrProvider("t", transport=transport).find_server("auditisa-firm-a").id == "2"


def test_vultr_follows_pages():
    calls = []

    def transport(method, url, headers, body):
        calls.append(url)
        if "cursor=next" in url:
            return ok({"ssh_keys": [{"id": "2", "name": "b"}], "meta": {"links": {"next": ""}}})
        return ok({"ssh_keys": [{"id": "1", "name": "a"}], "meta": {"links": {"next": "next"}}})

    assert VultrProvider("t", transport=transport).find_ssh_key("b") == "2"
    assert len(calls) == 2


def test_vultr_firewall_opens_22_to_the_list_only():
    transport = FakeTransport({("POST", "/firewalls"): ok({"firewall_group": {"id": "fw"}})})
    assert VultrProvider("t", transport=transport).create_firewall("l", ["198.51.100.7/32"]) == "fw"
    rules = [r[3] for r in transport.requests if r[0] == "POST" and "/rules" in r[1]]
    assert {(r["subnet"], r["subnet_size"], r["port"]) for r in rules if r["port"] == "22"} == {("198.51.100.7", 32, "22")}
    assert {r["port"] for r in rules} == {"22", "80", "443"}


def test_vultr_has_no_storage_of_its_own():
    """Backups are at Wasabi: without a storage given, the storage steps refuse, and Vultr is not called."""
    transport = FakeTransport()
    with pytest.raises(ProviderError):
        VultrProvider("t", transport=transport).create_storage("auditisa-firm-a", "cdg")
    assert transport.requests == []


def test_vultr_hands_storage_to_the_storage_given():
    class Storage:
        def __init__(self):
            self.calls = []

        def __getattr__(self, name):
            return lambda *args: self.calls.append((name, args)) or f"{name}-result"

    storage, transport = Storage(), FakeTransport()
    provider = VultrProvider("t", storage=storage, transport=transport)
    assert provider.find_storage("auditisa-firm-a") == "find_storage-result"
    assert provider.create_storage("auditisa-firm-a", "cdg") == "create_storage-result"
    assert provider.storage_credentials("b") == "storage_credentials-result"
    provider.delete_storage("b")
    assert [name for name, _args in storage.calls] == ["find_storage", "create_storage", "storage_credentials", "delete_storage"]
    assert transport.requests == []


@pytest.mark.parametrize("status,retryable", [(429, True), (500, True), (503, True), (400, False), (401, False), (403, False)])
def test_vultr_errors_say_if_a_retry_may_help(status, retryable):
    transport = FakeTransport({("POST", "/ssh-keys"): HttpResponse(status, SECRET_TOKEN.encode())})
    with pytest.raises(ProviderError) as caught:
        VultrProvider(SECRET_TOKEN, transport=transport).create_ssh_key("l", "k")
    assert caught.value.retryable is retryable
    assert SECRET_TOKEN not in str(caught.value)


def test_the_token_is_not_in_the_repr():
    provider = VultrProvider(SECRET_TOKEN, transport=FakeTransport())
    assert SECRET_TOKEN not in repr(provider)
    assert SECRET_TOKEN not in repr(provider._api)
    assert SECRET_TOKEN not in str(vars(provider))


def test_cloudflare_adds_then_updates_a_dns_only_record():
    empty = FakeTransport({("GET", "dns_records"): ok({"result": []})})
    CloudflareDns("t", "zone", transport=empty).upsert_a_record("a.auditisa.com", "1.2.3.4")
    assert empty.requests[1][0] == "POST"
    assert empty.requests[1][3]["proxied"] is False
    existing = FakeTransport({("GET", "dns_records"): ok({"result": [{"id": "r1", "content": "9.9.9.9"}]})})
    CloudflareDns("t", "zone", transport=existing).upsert_a_record("a.auditisa.com", "1.2.3.4")
    assert existing.requests[1][0] == "PUT"
    assert existing.requests[1][1].endswith("/dns_records/r1")


def test_cloudflare_reads_and_deletes():
    transport = FakeTransport({("GET", "dns_records"): ok({"result": [{"id": "r1", "content": "9.9.9.9"}]})})
    dns = CloudflareDns("t", "zone", transport=transport)
    assert dns.find_record("a.auditisa.com") == "9.9.9.9"
    dns.delete_record("a.auditisa.com")
    assert transport.requests[-1][0] == "DELETE"


# ---------------------------------------------------------------- the token file


def test_token_file_is_read_and_stripped(tmp_path):
    path = tmp_path / "token"
    path.write_text("value\n")
    os.chmod(path, 0o600)
    assert read_secret_file(str(path)) == "value"


@pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX")
@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o660])
def test_token_file_that_others_can_read_is_refused(tmp_path, mode):
    path = tmp_path / "token"
    path.write_text("value\n")
    os.chmod(path, mode)
    with pytest.raises(ProviderError) as caught:
        read_secret_file(str(path))
    assert "value" not in str(caught.value)


def test_missing_or_empty_token_file_is_refused(tmp_path):
    with pytest.raises(ProviderError):
        read_secret_file(str(tmp_path / "none"))
    path = tmp_path / "empty"
    path.write_text("  \n")
    os.chmod(path, 0o600)
    with pytest.raises(ProviderError):
        read_secret_file(str(path))
    with pytest.raises(ProviderError):
        read_secret_file(str(tmp_path))


def test_no_token_or_real_address_is_committed():
    """The repository holds the API's address but no credential for it."""
    services = Path(__file__).parents[1]
    for path in services.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "Bearer " not in text or "self.__token" in text, path
