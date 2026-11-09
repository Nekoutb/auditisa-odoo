"""The trusted signers of releases. Pure: stdlib and cryptography only.

A release is signed offline, on a signer's own computer, with that signer's own ed25519 key. Each
signer has a key of their own, never a shared one, so that the console can tell who signed and can
remove one person without touching the others.

The console keeps the list (platform.signer). Firms and the practice computer keep their OWN copy,
and change it only from a release signed by a key they already trust: that release carries the new
list as deploy/trust/signers.json. This module writes and reads that file. The firm side reads it
again, with the standard library only, in deploy/firm/release_trust.py: the two must agree.

The fingerprint of a key is the SHA-256 of its DER SubjectPublicKeyInfo, which is the base64 body of
the PEM: the same value `openssl pkey -pubin -outform DER | sha256sum` prints.
"""

import base64
import hashlib
import json
import re

from .messages import _

SCHEMA = "auditisa-signers-v1"
# The DER prefix of an ed25519 SubjectPublicKeyInfo: SEQUENCE, AlgorithmIdentifier 1.3.101.112, BIT STRING.
ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")
_PEM = re.compile(r"^-----BEGIN PUBLIC KEY-----\s*([A-Za-z0-9+/=\s]+?)\s*-----END PUBLIC KEY-----\s*$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_EMAIL = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")
NAME_MAX = 64


class SignerRefused(ValueError):
    """A key or a list that cannot be trusted. `message` is a translatable Msg."""

    def __init__(self, message):
        super().__init__(str(message))
        self.message = message


def der_of(pem):
    """The DER of an ed25519 public key in PEM, or SignerRefused. A private key is refused by name."""
    text = (pem or "").strip()
    if "PRIVATE" in text.upper():
        raise SignerRefused(_("This is a PRIVATE key: it was not kept. Send the public one only (the .pub file)."))
    found = _PEM.match(text)
    if not found:
        raise SignerRefused(_("A public key starts with -----BEGIN PUBLIC KEY----- and ends with -----END PUBLIC KEY-----."))
    try:
        der = base64.b64decode("".join(found.group(1).split()), validate=True)
    except (ValueError, TypeError):
        raise SignerRefused(_("This public key cannot be read.")) from None
    if len(der) != len(ED25519_SPKI_PREFIX) + 32 or not der.startswith(ED25519_SPKI_PREFIX):
        raise SignerRefused(_("Only an ed25519 public key is accepted, as made by the \"Make my signing key\" tool."))
    return der


def normalise(pem):
    """The PEM in its one canonical form (64-character lines), so that one key is written one way."""
    body = base64.b64encode(der_of(pem)).decode("ascii")
    lines = [body[i:i + 64] for i in range(0, len(body), 64)]
    return "-----BEGIN PUBLIC KEY-----\n" + "\n".join(lines) + "\n-----END PUBLIC KEY-----\n"


def fingerprint(pem):
    return hashlib.sha256(der_of(pem)).hexdigest()


def short(fingerprint_hex):
    """What a person compares by eye: the first 16 characters in groups of four, as the desktop tool shows."""
    value = (fingerprint_hex or "").upper()[:16]
    return " ".join(value[i:i + 4] for i in range(0, len(value), 4))


def verifies(pem, signature, data):
    """Whether `signature` over `data` was made with the key `pem`. False on anything unexpected."""
    if not pem or not signature:
        return False
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:  # pragma: no cover
        return False
    try:
        key = Ed25519PublicKey.from_public_bytes(der_of(pem)[len(ED25519_SPKI_PREFIX):])
        key.verify(signature, data)
    except (InvalidSignature, SignerRefused, ValueError, TypeError):
        return False
    return True


def which(signers, signature, data):
    """The first of `signers` (anything with a `pem` key or attribute) whose key made the signature."""
    for signer in signers:
        pem = signer["pem"] if isinstance(signer, dict) else signer.pem
        if verifies(pem, signature, data):
            return signer
    return None


def check_name(name):
    name = (name or "").strip()
    if not name or len(name) > NAME_MAX or any(ord(ch) < 32 for ch in name):
        raise SignerRefused(_("A signer's name: 1 to %(count)s characters.", count=NAME_MAX))
    return name


def check_email(email):
    email = (email or "").strip()
    if not _EMAIL.match(email):
        raise SignerRefused(_("A signer's email address, such as name@example.com."))
    return email


def document(serial, active, retired=()):
    """deploy/trust/signers.json, as bytes.

    `active`: dicts with name, email, pem. `retired`: the same plus `valid_for`, the bundle digests that
    a removed signer signed while trusted: those releases stay valid, nothing else of theirs does.
    """
    if type(serial) is not int or serial < 1:
        raise SignerRefused(_("The list's number must be 1 or more."))
    if not active:
        raise SignerRefused(_("At least one signer must stay: without one, no new version could ever be accepted."))
    def entry(row, with_digests):
        pem = normalise(row["pem"])
        item = {"name": check_name(row["name"]), "email": check_email(row["email"]),
                "fingerprint": fingerprint(pem), "public_key": pem}
        if with_digests:
            item["valid_for"] = sorted({d for d in row.get("valid_for", ()) if _DIGEST.match(d or "")})
        return item
    body = {
        "schema": SCHEMA,
        "serial": serial,
        "signers": sorted((entry(row, False) for row in active), key=lambda item: item["fingerprint"]),
        "retired": sorted((entry(row, True) for row in retired), key=lambda item: item["fingerprint"]),
    }
    seen = [item["fingerprint"] for item in body["signers"] + body["retired"]]
    if len(seen) != len(set(seen)):
        raise SignerRefused(_("The same key is listed twice."))
    return (json.dumps(body, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")


def parse(raw):
    """The list from deploy/trust/signers.json, checked as firmly as a firm checks it. SignerRefused."""
    try:
        data = json.loads(raw.decode("ascii") if isinstance(raw, bytes) else raw)
    except (UnicodeDecodeError, ValueError):
        raise SignerRefused(_("The list of signers cannot be read.")) from None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise SignerRefused(_("The list of signers cannot be read."))
    serial = data.get("serial")
    if type(serial) is not int or serial < 1:
        raise SignerRefused(_("The list's number must be 1 or more."))
    result = {"serial": serial, "signers": [], "retired": []}
    for group in ("signers", "retired"):
        rows = data.get(group, [])
        if not isinstance(rows, list) or len(rows) > 50:
            raise SignerRefused(_("The list of signers cannot be read."))
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("public_key"), str):
                raise SignerRefused(_("The list of signers cannot be read."))
            pem = normalise(row["public_key"])
            if row.get("fingerprint") != fingerprint(pem):
                raise SignerRefused(_("A fingerprint in the list does not match its key."))
            item = {"name": check_name(row.get("name")), "email": check_email(row.get("email")),
                    "fingerprint": fingerprint(pem), "pem": pem}
            if group == "retired":
                digests = row.get("valid_for", [])
                if not isinstance(digests, list) or not all(isinstance(d, str) and _DIGEST.match(d) for d in digests):
                    raise SignerRefused(_("The list of signers cannot be read."))
                item["valid_for"] = sorted(set(digests))
            result[group].append(item)
    if not result["signers"]:
        raise SignerRefused(_("At least one signer must stay: without one, no new version could ever be accepted."))
    seen = [item["fingerprint"] for item in result["signers"] + result["retired"]]
    if len(seen) != len(set(seen)):
        raise SignerRefused(_("The same key is listed twice."))
    return result


def accepts(trust, digest, signature, data):
    """The signer, from a parsed list, who may vouch for this bundle: an active one, or a retired one
    for a digest it signed while trusted. None when nobody can."""
    found = which(trust["signers"], signature, data)
    if found:
        return found
    for row in trust["retired"]:
        if digest in row["valid_for"] and verifies(row["pem"], signature, data):
            return row
    return None


ATTESTATION_PREFIX = "ea-promotion-v1"


def attestation_message(sha, bundle_sha256):
    """What a signer signs beside the bundle (the <sha>.attestation file): this commit and this digest."""
    return f"{ATTESTATION_PREFIX}\n{sha}\n{bundle_sha256}\n".encode("ascii")


def attestation_signature(text):
    """The signature inside an .attestation file (base64), or None."""
    try:
        return base64.b64decode("".join((text or "").split()), validate=True) or None
    except (ValueError, TypeError):
        return None
