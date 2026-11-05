import base64
import struct

import pytest

from ..catalogue import LANGUAGES, PRICES_CONFIRMED, REGIONS, SIZES, monthly_cost
from ..validation import (
    RESERVED_SLUGS,
    custom_domain_errors,
    flatten_errors,
    onboarding_errors,
    parse_allowlist,
    parse_domain_list,
    slug_errors,
    ssh_key_fingerprint,
    ssh_public_key_errors,
)


def key(seed=b"\x01"):
    algorithm = b"ssh-ed25519"
    blob = struct.pack(">I", len(algorithm)) + algorithm + struct.pack(">I", 32) + seed * 32
    return "ssh-ed25519 " + base64.b64encode(blob).decode() + " owner@laptop"


def request(**changes):
    data = {
        "name": "Example Firm",
        "slug": "cabinet-exemple",
        "contact_name": "Awa Ngono",
        "contact_email": "awa@exemple.cm",
        "region": "cdg",
        "size": "standard",
        "lang": "fr_FR",
        "allowed_email_domains": "exemple.cm",
        "ssh_public_key": key(),
    }
    data.update(changes)
    return data


@pytest.mark.parametrize("name", ["www", "dev", "test", "status", "admin", "mail", "hb", "api"])
def test_reserved_names_are_refused(name):
    assert name in RESERVED_SLUGS
    assert any("reserved" in message for message in slug_errors(name))


@pytest.mark.parametrize("name", ["WWW", " www ", "Status"])
def test_reserved_names_are_refused_whatever_the_case(name):
    assert any("reserved" in message for message in slug_errors(name))


@pytest.mark.parametrize("bad", ["", "a", "ab", "-abc", "abc-", "1abc", "a_b_c", "a.bc", "été-1", "a" * 33, "a--b", "a b c"])
def test_badly_formed_slugs_are_refused(bad):
    assert slug_errors(bad)


@pytest.mark.parametrize("good", ["abc", "cabinet-1", "eca-douala", "a" * 32])
def test_good_slugs_pass(good):
    assert slug_errors(good) == []


def test_a_slug_is_never_given_twice():
    assert any("already" in message for message in slug_errors("cabinet-a", ["Cabinet-A"]))
    assert slug_errors("cabinet-b", ["cabinet-a"]) == []


def test_domain_list_reads_like_core():
    domains, errors = parse_domain_list("@Exemple.cm, autre.org;\nexemple.cm  troisieme.co.uk")
    assert domains == ["exemple.cm", "autre.org", "troisieme.co.uk"]
    assert errors == []


def test_bad_domain_is_reported():
    domains, errors = parse_domain_list("exemple.cm pas_un_domaine")
    assert domains == ["exemple.cm"]
    assert len(errors) == 1


def test_private_key_is_refused_loudly():
    errors = ssh_public_key_errors("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----")
    assert "PRIVATE" in errors[0]


@pytest.mark.parametrize("bad", ["", "ssh-rsa AAAAB3NzaC1yc2E=", "ssh-ed25519 pasdubase64!", "ssh-ed25519 AAAA", "hello"])
def test_only_a_readable_ed25519_key_passes(bad):
    assert ssh_public_key_errors(bad)


def test_two_keys_at_once_are_refused():
    assert ssh_public_key_errors(key(b"\x01") + "\n" + key(b"\x02"))


def test_a_key_cannot_serve_two_firms():
    assert ssh_public_key_errors(key()) == []
    assert ssh_public_key_errors(key(), [ssh_key_fingerprint(key())])
    assert ssh_public_key_errors(key(b"\x02"), [ssh_key_fingerprint(key())]) == []


def test_fingerprint_has_openssh_form():
    assert ssh_key_fingerprint(key()).startswith("SHA256:")
    assert not ssh_key_fingerprint(key()).endswith("=")


@pytest.mark.parametrize("wide", ["0.0.0.0/0", "::/0", "8.0.0.0/8", "2001:4860::/32"])
def test_port_22_is_never_opened_wide(wide):
    cidrs, errors = parse_allowlist(wide)
    assert cidrs == []
    assert errors


@pytest.mark.parametrize("private", ["10.0.0.1", "192.168.1.0/24", "127.0.0.1"])
def test_port_22_refuses_private_addresses(private):
    assert parse_allowlist(private)[1]


def test_allowlist_reads_addresses_and_ranges():
    cidrs, errors = parse_allowlist("8.8.8.8, 1.1.1.0/24\n8.8.8.8/32")
    assert cidrs == ["8.8.8.8/32", "1.1.1.0/24"]
    assert errors == []


def test_empty_allowlist_is_an_error():
    assert parse_allowlist("")[1]
    assert parse_allowlist("not-an-ip")[1]


def test_valid_request_passes():
    assert onboarding_errors(request()) == {}


@pytest.mark.parametrize("field", ["name", "slug", "contact_name", "contact_email", "region", "size", "lang", "allowed_email_domains", "ssh_public_key"])
def test_every_required_field_is_checked(field):
    assert field in onboarding_errors(request(**{field: ""}))


def test_contact_must_be_in_an_allowed_domain():
    assert "contact_email" in onboarding_errors(request(contact_email="awa@gmail.com"))


def test_unknown_catalogue_values_are_refused():
    assert "region" in onboarding_errors(request(region="moon"))
    assert "size" in onboarding_errors(request(size="huge"))
    assert "lang" in onboarding_errors(request(lang="xx_XX"))


def test_custom_domain_rules():
    assert custom_domain_errors("audit.exemple.cm", "auditisa.com") == []
    assert custom_domain_errors("", "auditisa.com") == []
    assert custom_domain_errors("x.auditisa.com", "auditisa.com")
    assert custom_domain_errors("pas un domaine", "auditisa.com")


def test_errors_flatten_to_one_message_per_line():
    assert len(flatten_errors(onboarding_errors(request(name="", region="")))) == 2


def test_cost_adds_server_and_storage():
    server, storage, total = monthly_cost("standard")
    assert server == SIZES["standard"]["monthly_usd"]
    assert total == server + storage


def test_prices_are_marked_as_unconfirmed():
    assert PRICES_CONFIRMED is False


def test_catalogue_is_consistent():
    assert "cdg" in REGIONS
    assert "fr_FR" in LANGUAGES
    for size in SIZES.values():
        assert size["plan"].startswith("vc2-")
        assert size["workers"] >= 2
