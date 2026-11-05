"""Checks on what the onboarding wizard is given. Pure: no Odoo, no network.

Every function returns messages for the screen (see messages.py), or an empty value when all is
well. The checks run twice: on the wizard's screens, and again as the first provisioning step,
because a job can be resumed days later.
"""

import base64
import binascii
import hashlib
import ipaddress
import re
import struct

from .catalogue import LANGUAGES, REGIONS, SIZES
from .messages import _

SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}[a-z0-9]$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HOSTNAME_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
DOMAIN_RE = re.compile(r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")

# Names that belong to the platform or that a mail, DNS or web service expects. Extended on purpose
# beyond the owner's list (www, dev, test, status): a firm must not be able to shadow any of them.
RESERVED_SLUGS = frozenset("""
    www dev test status staging stage prod production preprod uat demo sandbox
    admin administrator root superuser operator owner platform control controlplane console
    hb heartbeat api app apps web portal login auth sso oauth account accounts
    mail smtp imap pop pop3 email webmail mx autoconfig autodiscover ftp sftp ssh vpn git gitlab
    ns ns1 ns2 ns3 ns4 dns cdn static assets media files releases release backup backups
    db database postgres postgresql odoo erp audit auditisa support help docs doc blog billing
    invoice monitor monitoring grafana metrics localhost wildcard default example
""".split())

MIN_ALLOWLIST_PREFIX_V4 = 16
MIN_ALLOWLIST_PREFIX_V6 = 48


def normalise_slug(value):
    return (value or "").strip().lower()


def slug_errors(slug, existing=()):
    """Why this address cannot be given to a new firm. `existing` holds every slug ever used."""
    slug = normalise_slug(slug)
    if not slug:
        return [_("The slug is required.")]
    errors = []
    if not SLUG_RE.match(slug):
        errors.append(_(
            "The slug must be 3 to 32 characters: lower case letters, digits and hyphens, "
            "starting with a letter and not ending with a hyphen."
        ))
    if "--" in slug:
        errors.append(_("The slug must not hold two hyphens in a row."))
    if slug in RESERVED_SLUGS:
        errors.append(_("\"%(slug)s\" is a name reserved by the platform.", slug=slug))
    if slug in {normalise_slug(s) for s in existing}:
        errors.append(_("The slug \"%(slug)s\" has already been given, even if to an archived firm.", slug=slug))
    return errors


def is_valid_email(value):
    return bool(value) and bool(EMAIL_RE.match(value.strip()))


def parse_domain_list(text):
    """Same reading as ea_audit_core: newlines, commas, semicolons, spaces; leading @ tolerated.

    Returns (domains, errors).
    """
    domains, errors = [], []
    for raw in re.split(r"[\s,;]+", (text or "").strip()):
        if not raw:
            continue
        domain = raw.lstrip("@").lower()
        if not DOMAIN_RE.match(domain):
            errors.append(_("Invalid email domain: \"%(domain)s\".", domain=raw))
        elif domain not in domains:
            domains.append(domain)
    return domains, errors


def custom_domain_errors(value, base_domain):
    value = (value or "").strip().lower()
    if not value:
        return []
    if not HOSTNAME_RE.match(value):
        return [_("Invalid custom domain: \"%(domain)s\".", domain=value)]
    if base_domain and (value == base_domain or value.endswith("." + base_domain)):
        return [_("The firm's own domain cannot be under %(domain)s.", domain=base_domain)]
    return []


def ssh_key_fingerprint(public_key):
    """SHA256 fingerprint of an OpenSSH public key, as `ssh-keygen -lf` writes it."""
    parts = (public_key or "").strip().split()
    blob = base64.b64decode(parts[1], validate=True)
    digest = hashlib.sha256(blob).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


def ssh_public_key_errors(public_key, existing_fingerprints=()):
    """Only an ed25519 public key is accepted, and one that no other firm uses."""
    key = (public_key or "").strip()
    if not key:
        return [_("The firm's public SSH key is required.")]
    if "PRIVATE KEY" in key:
        return [_(
            "This is a PRIVATE key: it must never be pasted here. Erase it and paste the content of "
            "the .pub file."
        )]
    parts = key.split()
    if len(parts) < 2 or parts[0] != "ssh-ed25519" or "\n" in key:
        return [_("One public key is expected, in ssh-ed25519 format.")]
    try:
        blob = base64.b64decode(parts[1], validate=True)
        length = struct.unpack(">I", blob[:4])[0]
        algorithm = blob[4:4 + length]
        key_length = struct.unpack(">I", blob[4 + length:8 + length])[0]
    except (binascii.Error, struct.error, ValueError):
        return [_("The public SSH key cannot be read.")]
    if algorithm != b"ssh-ed25519" or key_length != 32 or len(blob) != 8 + length + key_length:
        return [_("The public SSH key cannot be read.")]
    if ssh_key_fingerprint(key) in set(existing_fingerprints):
        return [_("This SSH key already serves another firm: each firm has its own.")]
    return []


def parse_allowlist(text):
    """The source addresses allowed on port 22. Returns (cidrs, errors).

    An open or very wide range is refused: port 22 is never open to the world.
    """
    cidrs, errors = [], []
    for raw in re.split(r"[\s,;]+", (text or "").strip()):
        if not raw:
            continue
        try:
            network = ipaddress.ip_network(raw, strict=False)
        except ValueError:
            errors.append(_("Invalid IP address: \"%(address)s\".", address=raw))
            continue
        minimum = MIN_ALLOWLIST_PREFIX_V4 if network.version == 4 else MIN_ALLOWLIST_PREFIX_V6
        if network.prefixlen < minimum:
            errors.append(_("Range too wide for port 22: \"%(address)s\" (minimum /%(minimum)s).", address=raw, minimum=minimum))
        elif not network.is_global:
            errors.append(_("Not a public address, for port 22: \"%(address)s\".", address=raw))
        elif str(network) not in cidrs:
            cidrs.append(str(network))
    if not cidrs and not errors:
        errors.append(_("At least one operator IP address is needed for port 22."))
    return cidrs, errors


def onboarding_errors(data, existing_slugs=(), existing_fingerprints=()):
    """Every problem with a new firm's request, by field name. An empty dict means valid."""
    errors = {}

    def add(field, messages):
        if messages:
            errors.setdefault(field, []).extend(messages)

    if not (data.get("name") or "").strip():
        add("name", [_("The firm's name is required.")])
    add("slug", slug_errors(data.get("slug"), existing_slugs))
    if not (data.get("contact_name") or "").strip():
        add("contact_name", [_("The contact's name is required.")])
    if not is_valid_email(data.get("contact_email")):
        add("contact_email", [_("The contact's email is invalid.")])
    if data.get("region") not in REGIONS:
        add("region", [_("Choose a region.")])
    if data.get("size") not in SIZES:
        add("size", [_("Choose a size.")])
    if data.get("lang") not in LANGUAGES:
        add("lang", [_("Choose a language.")])

    domains, domain_errors = parse_domain_list(data.get("allowed_email_domains"))
    add("allowed_email_domains", domain_errors)
    if not domains and not domain_errors:
        add("allowed_email_domains", [_("Give at least one allowed email domain.")])
    contact = (data.get("contact_email") or "").strip().lower()
    if domains and "@" in contact and contact.rsplit("@", 1)[1] not in domains:
        add("contact_email", [_("The contact's email must belong to an allowed domain.")])

    add("ssh_public_key", ssh_public_key_errors(data.get("ssh_public_key"), existing_fingerprints))
    return errors


def flatten_errors(errors):
    """Every message, in a stable order."""
    return [message for field in sorted(errors) for message in errors[field]]
