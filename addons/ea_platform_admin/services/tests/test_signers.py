"""Trusted signers, pure: keys, the list a release carries, and what a new firm gets at first boot."""

import base64
import hashlib
import json
import re

import os

import pytest

from .. import signers as trust
from ..recipe import render_user_data
from .test_provisioning import KEY, values


def make():
    """A key pair, for the tests that sign: they need cryptography (skipped where it is not installed)."""
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    private = Ed25519PrivateKey.generate()
    pem = private.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    return private, pem


def public_only():
    """A public key in PEM, for the tests that only read keys: the standard library is enough."""
    body = base64.b64encode(trust.ED25519_SPKI_PREFIX + os.urandom(32)).decode()
    return None, f"-----BEGIN PUBLIC KEY-----\n{body}\n-----END PUBLIC KEY-----\n"


def der_sha(pem):
    body = "".join(line for line in pem.strip().splitlines() if "-----" not in line)
    return hashlib.sha256(base64.b64decode(body)).hexdigest()


def test_the_fingerprint_is_the_sha256_of_the_public_key_der():
    _private, pem = public_only()
    assert trust.fingerprint(pem) == der_sha(pem)
    assert re.fullmatch(r"[0-9A-F]{4} [0-9A-F]{4} [0-9A-F]{4} [0-9A-F]{4}", trust.short(trust.fingerprint(pem)))


def test_a_private_key_or_another_kind_of_key_is_refused():
    with pytest.raises(trust.SignerRefused, match="PRIVATE"):
        trust.der_of("-----BEGIN PRIVATE KEY-----\nMC4CAQAwBQYDK2VwBCIEIA==\n-----END PRIVATE KEY-----")
    with pytest.raises(trust.SignerRefused):
        trust.der_of("-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEA\n-----END PUBLIC KEY-----")
    with pytest.raises(trust.SignerRefused):
        trust.der_of("ssh-ed25519 AAAA owner@laptop")


def test_one_key_is_written_one_way():
    _private, pem = public_only()
    messy = pem.replace("\n", "\r\n") + "\n\n"
    assert trust.normalise(messy) == trust.normalise(pem)
    assert trust.fingerprint(messy) == trust.fingerprint(pem)


def test_the_signer_who_signed_is_found_and_nobody_else():
    alice, alice_pem = make()
    bob, bob_pem = make()
    _carol, carol_pem = make()
    data = b"bundle"
    signers = [{"id": 1, "pem": alice_pem}, {"id": 2, "pem": bob_pem}]
    assert trust.which(signers, bob.sign(data), data)["id"] == 2
    assert trust.which(signers, alice.sign(data + b"x"), data) is None
    assert trust.which([{"id": 3, "pem": carol_pem}], alice.sign(data), data) is None


def test_the_list_reads_back_and_keeps_removed_signers_for_their_own_bundles_only():
    alice, alice_pem = make()
    bob, bob_pem = make()
    raw = trust.document(3, [{"name": "Owner", "email": "contact@cm-ea.com", "pem": alice_pem}],
                         [{"name": "Bob", "email": "bob@example.com", "pem": bob_pem, "valid_for": ["a" * 64]}])
    parsed = trust.parse(raw)
    assert parsed["serial"] == 3
    assert [row["name"] for row in parsed["signers"]] == ["Owner"]
    assert parsed["retired"][0]["valid_for"] == ["a" * 64]
    data = b"bundle"
    assert trust.accepts(parsed, "b" * 64, alice.sign(data), data)["name"] == "Owner"
    # A removed signer: only for a bundle they signed while trusted.
    assert trust.accepts(parsed, "a" * 64, bob.sign(data), data)["name"] == "Bob"
    assert trust.accepts(parsed, "b" * 64, bob.sign(data), data) is None


def test_a_list_with_a_forged_fingerprint_no_signer_or_a_twice_listed_key_is_refused():
    _a, pem = public_only()
    good = json.loads(trust.document(1, [{"name": "Owner", "email": "contact@cm-ea.com", "pem": pem}]))
    forged = dict(good, signers=[dict(good["signers"][0], fingerprint="0" * 64)])
    with pytest.raises(trust.SignerRefused):
        trust.parse(json.dumps(forged))
    with pytest.raises(trust.SignerRefused):
        trust.parse(json.dumps(dict(good, signers=[])))
    with pytest.raises(trust.SignerRefused):
        trust.parse(json.dumps(dict(good, retired=good["signers"])))
    with pytest.raises(trust.SignerRefused):
        trust.parse(json.dumps(dict(good, serial=0)))
    with pytest.raises(trust.SignerRefused):
        trust.document(1, [])


def test_the_repository_list_is_the_owners_key_number_one():
    from pathlib import Path
    raw = (Path(__file__).parents[4] / "deploy/trust/signers.json").read_bytes()
    parsed = trust.parse(raw)
    assert parsed["serial"] >= 1
    assert parsed["signers"][0]["name"] == "Owner"
    # Written exactly as the console writes it, so that the two can be compared byte for byte.
    assert raw == trust.document(parsed["serial"], parsed["signers"], parsed["retired"])


def test_the_attestation_is_the_message_of_the_pipeline():
    from ea_platform_pipeline.services import pipeline
    assert trust.attestation_message("a" * 40, "b" * 64) == pipeline.attestation_message("a" * 40, "b" * 64)
    private, pem = make()
    signature = base64.b64encode(private.sign(trust.attestation_message("a" * 40, "b" * 64))).decode()
    assert trust.verifies(pem, trust.attestation_signature(signature), trust.attestation_message("a" * 40, "b" * 64))
    assert trust.attestation_signature("not base64!") is None


def test_a_new_firm_gets_every_signer_and_checks_the_bundle_against_them():
    _a, alice_pem = public_only()
    _b, bob_pem = public_only()
    raw = trust.document(2, [{"name": "Owner", "email": "contact@cm-ea.com", "pem": alice_pem},
                             {"name": "Marie", "email": "marie@example.com", "pem": bob_pem}],
                         [{"name": "Old", "email": "old@example.com", "pem": public_only()[1], "valid_for": ["c" * 64]}])
    text = render_user_data(values(), KEY, raw)
    yaml = pytest.importorskip("yaml")
    data = yaml.safe_load(text)
    files = {item["path"]: item["content"] for item in data["write_files"]}
    folder = "/etc/auditisa-firm/trusted-signers"
    for pem in (alice_pem, bob_pem):
        assert files[f"{folder}/{trust.fingerprint(pem)}.pub"].strip() == trust.normalise(pem).strip()
    only = [path for path in files if path.endswith(".only")]
    assert len(only) == 1 and files[only[0]].strip() == "c" * 64
    assert files[f"{folder}/serial"].strip() == "2"
    assert trust.parse(files[f"{folder}/signers.json"])["serial"] == 2
    command = data["runcmd"][0][2]
    assert "trusted-signers/*.pub" in command
    assert command.index("pkeyutl -verify") < command.index("install-firm-server.sh")
    assert "exit 1" in command


def test_a_list_that_does_not_hold_stops_the_first_boot_text():
    with pytest.raises(ValueError):
        render_user_data(values(), KEY, b'{"schema": "auditisa-signers-v1", "serial": 1, "signers": []}')
