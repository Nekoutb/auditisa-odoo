"""A platform email address for each client firm: support@<slug>.cm-ea.com, sent through MailerSend. Pure.

Owner's request of 2026-11-17: when a firm's space is provisioned, it can already send its email
(password resets, invitations) without the firm having a mailbox of its own. The console:

  1. asks MailerSend for a sending domain <slug>.<parent domain> (POST /v1/domains);
  2. reads the DNS records MailerSend wants (GET /v1/domains/{id}/dns-records) and writes them in the
     parent domain's Cloudflare zone, DNS only (never proxied), leaving alone what is already right;
  3. asks MailerSend to check the domain (GET /v1/domains/{id}/verify); DNS can take minutes, so a pass
     that finds it not verified yet simply comes back later (`next_check_minutes`);
  4. once verified, makes an SMTP user for that domain (POST /v1/domains/{id}/smtp-users): MailerSend shows
     its password once, in that answer, and it goes straight to the firm (models/firm_mail.py), never to
     the database;
  5. removing the address undoes all of it (SMTP user, DNS records, domain).

Every pass is safe to run twice: each call first looks for what it would create. The tokens are held by
the client objects only and never appear in an error, a log or a repr. NEVER RUN AGAINST THE REAL
SERVICES in tests: the tests give a fake transport, and the simulation uses the DryRun classes below.

What a firm's emails carry is not this module's business, but the rule is written here too: a name, a
count and a link, never a client's data (docs/runbook/PLATFORM-EMAIL.md).
"""

import json
import re
import urllib.parse

from .messages import _
from .provider import ProviderError
from .provider_vultr import CLOUDFLARE_API, UrllibTransport

MAILERSEND_API = "https://api.mailersend.com/v1"
SMTP_HOST = "smtp.mailersend.net"
SMTP_PORT = 587
SMTP_ENCRYPTION = "starttls"
SMTP_USER_NAME = "AuditISA"
DEFAULT_PARENT = "cm-ea.com"
DEFAULT_LOCAL_PART = "support"
DNS_TTL = 300
# The records a sending domain needs. "inbound_routing" (MX) is left out: the firms receive nothing here.
RECORD_KEYS = ("spf", "dkim", "dkim_ms1", "dkim_ms2", "return_path", "custom_tracking")
RECORD_TYPES = ("TXT", "CNAME")
# A domain not verified after this long is reported as a problem; the operator can still check again.
VERIFY_GIVE_UP_HOURS = 48
_BACKOFF_MINUTES = (1, 2, 5, 10, 15, 30, 60)

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
PARENT_RE = re.compile(r"^(?=.{4,200}$)%s(?:\.%s)+$" % (_LABEL, _LABEL))
LOCAL_PART_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,30}[a-z0-9])?$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
                      r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")
MAX_ALLOWLIST = 50

# Per firm (owner, 2026-11-18): the address is for sending only, so "No reply" is the default.
REPLIES = [
    ("none", "No reply"),
    ("contact", "Go to the firm contact"),
]
NO_REPLY_PREFIX = "(No reply) "

STATES = [
    ("none", "No platform address"),
    ("setting_up", "Being set up"),
    ("verifying", "Waiting for the domain check"),
    ("sending", "Settings sent to the firm's server"),
    ("on", "Sending is on"),
    ("problem", "Needs attention"),
]
MESSAGES = {
    "none": _("This firm has no platform email address. Use \"Give this firm a platform email address\" to make one."),
    "setting_up": _("The console is making the address at MailerSend and its DNS records at Cloudflare."),
    "verifying": _(
        "The DNS records are written. MailerSend checks them: this usually takes a few minutes, sometimes an hour. "
        "The console checks again by itself."
    ),
    "sending": _(
        "The domain is verified. The sending settings went to the firm's server, which tests them at its next "
        "check-in (within 15 minutes)."
    ),
    "on": _("Sending is on: the firm's server sends its email from this address."),
    "problem": _("Something stopped the set-up: see the message below, then use \"Check again now\"."),
}


# --------------------------------------------------------------------- the rules


def clean_parent(value):
    return (value or "").strip().lower().rstrip(".")


def parent_errors(value):
    parent = clean_parent(value)
    if not PARENT_RE.match(parent):
        return [_("Parent domain: a domain name such as cm-ea.com.")]
    return []


def local_part_errors(value):
    if not LOCAL_PART_RE.match((value or "").strip().lower()):
        return [_("Sender name: letters, digits, dots or dashes only, for example support.")]
    return []


def subdomain(slug, parent):
    """<slug>.<parent>. The slug was checked by the New firm form."""
    return f"{slug}.{clean_parent(parent)}"


def sender(local_part, domain):
    return f"{(local_part or DEFAULT_LOCAL_PART).strip().lower()}@{domain}"


def reply_to(policy, contact_email):
    """The reply address the firm's emails carry, or "" for none."""
    email = (contact_email or "").strip()
    return email if policy != "none" and EMAIL_RE.match(email) else ""


def no_reply_subject(subject):
    """The subject of an email from an address that takes no replies: "(No reply) " before it, once."""
    subject = subject or ""
    if subject.lstrip().lower().startswith(NO_REPLY_PREFIX.strip().lower()):
        return subject
    return NO_REPLY_PREFIX + subject


def parse_allowlist(text):
    """(addresses, errors) from one address per line (commas and spaces also separate). Lower case, sorted."""
    addresses, errors = set(), []
    for item in re.split(r"[\s,;]+", text or ""):
        if not item:
            continue
        if not EMAIL_RE.match(item):
            errors.append(_("Not an email address: %(item)s", item=item[:80]))
            continue
        addresses.add(item.lower())
    if len(addresses) > MAX_ALLOWLIST:
        errors.append(_("At most %(count)s addresses.", count=MAX_ALLOWLIST))
    return sorted(addresses), errors


def allowed(address, allowlist):
    return (address or "").strip().lower() in set(allowlist or ())


def next_check_minutes(tries):
    """How long to wait before the next domain check: 1, 2, 5, 10, 15, 30, then every hour."""
    return _BACKOFF_MINUTES[min(max(tries, 0), len(_BACKOFF_MINUTES) - 1)]


def _within(name, domain):
    name = (name or "").lower().rstrip(".")
    return name == domain or name.endswith("." + domain)


def _txt(value):
    """TXT contents compare without the quotes Cloudflare may add."""
    value = (value or "").strip()
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] == '"' else value


def records_from_answer(answer, domain):
    """[{type, name, content}] from MailerSend's dns-records answer. Only names inside the firm's own
    subdomain, of type TXT or CNAME: nothing else of the parent zone can ever be touched."""
    data = (answer or {}).get("data") or {}
    found = []
    for key in RECORD_KEYS:
        record = data.get(key)
        if not isinstance(record, dict):
            continue
        kind, name, value = record.get("type"), record.get("hostname"), record.get("value")
        if not (isinstance(kind, str) and isinstance(name, str) and isinstance(value, str)) or not value:
            continue
        kind = kind.upper()
        name = name.lower().rstrip(".")
        if kind not in RECORD_TYPES or not _within(name, domain):
            continue
        item = {"type": kind, "name": name, "content": value.strip()}
        if item not in found:
            found.append(item)
    return found


# --------------------------------------------------------------------- the real services


class _Client:
    """Bearer-token JSON calls. A refusal is said in our own words, never by quoting the answer."""

    service = ""
    base = ""

    def __init__(self, token, transport=None):
        self.__token = token
        self._transport = transport or UrllibTransport()

    def __repr__(self):
        return f"<{self.service} client>"

    def _call(self, method, path, payload=None, refusals=None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Authorization": f"Bearer {self.__token}", "Content-Type": "application/json",
                   "Accept": "application/json"}
        response = self._transport(method, self.base + path, headers, body)
        if response.status == 404 and method in ("GET", "DELETE"):
            return None
        if response.status == 429 or response.status >= 500:
            raise ProviderError(_("%(service)s: temporary error %(status)s.", service=self.service,
                                  status=response.status), retryable=True)
        if response.status in (401, 403):
            raise ProviderError(_("%(service)s refused the token: check that it is right and has the permissions "
                                  "listed in docs/runbook/PLATFORM-EMAIL.md.", service=self.service))
        if response.status >= 400:
            text = response.body[:2000].decode("utf-8", "replace").lower() if response.body else ""
            for words, message in (refusals or ()):
                if all(word in text for word in words):
                    raise ProviderError(message)
            raise ProviderError(_("%(service)s refused %(call)s (%(status)s).", service=self.service,
                                  call=f"{method} {path.split('?')[0]}", status=response.status))
        if not response.body:
            return {}
        try:
            return json.loads(response.body)
        except ValueError:
            raise ProviderError(_("%(service)s: unreadable answer.", service=self.service), retryable=True) from None


class MailerSend(_Client):
    service = "MailerSend"
    base = MAILERSEND_API
    is_simulation = False

    def check(self):
        """Read-only: lists one page of domains. True, or ProviderError."""
        self._call("GET", "/domains?limit=10")
        return True

    def find_domain(self, name):
        for page in range(1, 51):
            answer = self._call("GET", f"/domains?limit=100&page={page}") or {}
            for domain in answer.get("data") or []:
                if isinstance(domain, dict) and domain.get("name") == name:
                    return str(domain["id"])
            meta = answer.get("meta") or {}
            if not answer.get("data") or page >= int(meta.get("last_page") or page):
                return None
        return None

    def create_domain(self, name):
        answer = self._call("POST", "/domains", {"name": name}, refusals=(
            (("limit",), _("MailerSend: the account has reached its plan's number of sending domains. Upgrade the "
                           "plan, or remove the address of a firm that left, then check again.")),
            (("taken",), _("MailerSend: this domain is already in another MailerSend account.")),
        ))
        domain_id = ((answer or {}).get("data") or {}).get("id")
        if not domain_id:
            raise ProviderError(_("MailerSend: unreadable answer."), retryable=True)
        return str(domain_id)

    def domain_exists(self, domain_id):
        return self._call("GET", f"/domains/{_q(domain_id)}") is not None

    def dns_records(self, domain_id, domain):
        answer = self._call("GET", f"/domains/{_q(domain_id)}/dns-records")
        if answer is None:
            raise ProviderError(_("MailerSend no longer has this firm's domain."))
        return records_from_answer(answer, domain)

    def verify(self, domain_id):
        answer = self._call("GET", f"/domains/{_q(domain_id)}/verify") or {}
        data = answer.get("data") or {}
        if "is verified" in str(answer.get("message") or "").lower():
            return True
        return bool(data.get("spf") and data.get("dkim"))

    def find_smtp_user(self, domain_id, name):
        answer = self._call("GET", f"/domains/{_q(domain_id)}/smtp-users?limit=100") or {}
        for user in answer.get("data") or []:
            if isinstance(user, dict) and user.get("name") == name:
                return str(user["id"])
        return None

    def create_smtp_user(self, domain_id, name):
        """(id, username, password). The password is in this answer only."""
        answer = self._call("POST", f"/domains/{_q(domain_id)}/smtp-users", {"name": name, "enabled": True}, refusals=(
            (("limit",), _("MailerSend: the account has reached its plan's number of SMTP users. Upgrade the plan, "
                           "then check again.")),
        ))
        data = (answer or {}).get("data") or {}
        if not (data.get("id") and data.get("username") and data.get("password")):
            raise ProviderError(_("MailerSend: unreadable answer."), retryable=True)
        return str(data["id"]), str(data["username"]), str(data["password"])

    def delete_smtp_user(self, domain_id, user_id):
        self._call("DELETE", f"/domains/{_q(domain_id)}/smtp-users/{_q(user_id)}")

    def delete_domain(self, domain_id):
        self._call("DELETE", f"/domains/{_q(domain_id)}")

    def send_test(self, from_email, from_name, to_email, reply_to_email, subject, text):
        payload = {"from": {"email": from_email, "name": from_name[:100]}, "to": [{"email": to_email}],
                   "subject": subject, "text": text}
        if reply_to_email:
            payload["reply_to"] = {"email": reply_to_email}
        self._call("POST", "/email", payload, refusals=(
            (("from",), _("MailerSend refused the sender address: the firm's domain is not verified yet.")),
        ))
        return True


class CloudflareZone(_Client):
    """The parent domain's zone. Only names inside a firm's subdomain are ever written or erased."""

    service = "Cloudflare"
    base = CLOUDFLARE_API
    is_simulation = False

    def __init__(self, token, zone_id=None, transport=None):
        super().__init__(token, transport)
        self.zone_id = zone_id

    def check(self):
        """Read-only: the token is valid and active. A user token answers /user/tokens/verify; an account
        token (what Cloudflare's newer token screen makes) is refused there, so it is checked by listing
        the zones it can see instead."""
        try:
            answer = self._call("GET", "/user/tokens/verify") or {}
        except ProviderError as error:
            if error.retryable:
                raise
            self._call("GET", "/zones?per_page=1")  # refused too: the token is wrong after all
            return True
        if ((answer.get("result") or {}).get("status")) != "active":
            raise ProviderError(_("Cloudflare: the token is not active."))
        return True

    def find_zone(self, name):
        answer = self._call("GET", f"/zones?name={_q(name)}") or {}
        results = answer.get("result") or []
        return str(results[0]["id"]) if results else None

    def _zone(self):
        if not self.zone_id:
            raise ProviderError(_("Cloudflare: the zone of the parent domain is not known. Use \"Test the connection\" "
                                  "in the platform settings."))
        return _q(self.zone_id)

    def find(self, kind, name):
        answer = self._call("GET", f"/zones/{self._zone()}/dns_records?type={kind}&name={_q(name)}") or {}
        return [{"id": str(r["id"]), "content": r.get("content") or ""} for r in answer.get("result") or []]

    def create(self, kind, name, content):
        answer = self._call("POST", f"/zones/{self._zone()}/dns_records", {
            "type": kind, "name": name, "content": content, "ttl": DNS_TTL, "proxied": False,
        }) or {}
        return str((answer.get("result") or {}).get("id") or "")

    def update(self, record_id, kind, name, content):
        self._call("PATCH", f"/zones/{self._zone()}/dns_records/{_q(record_id)}", {
            "type": kind, "name": name, "content": content, "ttl": DNS_TTL, "proxied": False,
        })

    def delete(self, record_id):
        self._call("DELETE", f"/zones/{self._zone()}/dns_records/{_q(record_id)}")


def _q(value):
    return urllib.parse.quote(str(value), safe="")


# --------------------------------------------------------------------- the simulation


class _Faults:
    def _enter(self, method):
        self.calls.append(method)
        rule = self.fail_on.get(method)
        if rule is None:
            return
        if isinstance(rule, int):
            if rule > 0:
                self.fail_on[method] = rule - 1
                raise ProviderError(_("%(method)s: simulated fault (temporary)", method=method), retryable=True)
            return
        raise rule


class DryRunMailerSend(_Faults):
    """MailerSend without the network. A domain is verified at its `verify_after`-th check (1 by default)."""

    service = "MailerSend"
    is_simulation = True

    def __init__(self, state=None, fail_on=None):
        self.state = state if state is not None else {}
        self.state.setdefault("domains", {})
        self.state.setdefault("seq", 0)
        self.state.setdefault("verify_after", 1)
        self.state.setdefault("sent", 0)
        self.fail_on = dict(fail_on or {})
        self.calls = []

    def _new_id(self, prefix):
        self.state["seq"] += 1
        return f"{prefix}{self.state['seq']:06d}"

    def check(self):
        self._enter("check")
        return True

    def find_domain(self, name):
        self._enter("find_domain")
        return next((key for key, value in self.state["domains"].items() if value["name"] == name), None)

    def create_domain(self, name):
        self._enter("create_domain")
        key = self._new_id("dom")
        self.state["domains"][key] = {"name": name, "checks": 0, "verified": False, "smtp": {}}
        return key

    def domain_exists(self, domain_id):
        self._enter("domain_exists")
        return domain_id in self.state["domains"]

    def _domain(self, domain_id):
        domain = self.state["domains"].get(domain_id)
        if domain is None:
            raise ProviderError(_("MailerSend no longer has this firm's domain."))
        return domain

    def dns_records(self, domain_id, domain):
        self._enter("dns_records")
        name = self._domain(domain_id)["name"]
        return records_from_answer({"data": {
            "spf": {"hostname": name, "type": "TXT", "value": "v=spf1 include:_spf.mailersend.net ~all"},
            "dkim_ms1": {"hostname": f"ms1._domainkey.{name}", "type": "CNAME", "value": "ms1._domainkey.mailersend.net"},
            "dkim_ms2": {"hostname": f"ms2._domainkey.{name}", "type": "CNAME", "value": "ms2._domainkey.mailersend.net"},
            "return_path": {"hostname": f"mta.{name}", "type": "CNAME", "value": "mailersend.net"},
            "inbound_routing": {"hostname": f"inbound.{name}", "type": "MX", "value": "inbound.mailersend.net"},
        }}, domain)

    def verify(self, domain_id):
        self._enter("verify")
        domain = self._domain(domain_id)
        domain["checks"] += 1
        domain["verified"] = domain["verified"] or domain["checks"] >= self.state["verify_after"]
        return domain["verified"]

    def find_smtp_user(self, domain_id, name):
        self._enter("find_smtp_user")
        smtp = self._domain(domain_id)["smtp"]
        return next((key for key, value in smtp.items() if value["name"] == name), None)

    def create_smtp_user(self, domain_id, name):
        self._enter("create_smtp_user")
        domain = self._domain(domain_id)
        key = self._new_id("smtp")
        username = f"MS_{key}@{domain['name']}"
        domain["smtp"][key] = {"name": name, "username": username}
        # Simulated: not a secret, and different every time, like the real one.
        return key, username, f"simulated-{key}"

    def delete_smtp_user(self, domain_id, user_id):
        self._enter("delete_smtp_user")
        domain = self.state["domains"].get(domain_id)
        if domain:
            domain["smtp"].pop(user_id, None)

    def delete_domain(self, domain_id):
        self._enter("delete_domain")
        self.state["domains"].pop(domain_id, None)

    def send_test(self, from_email, from_name, to_email, reply_to_email, subject, text):
        self._enter("send_test")
        domain = from_email.split("@", 1)[-1]
        if not any(value["name"] == domain and value["verified"] for value in self.state["domains"].values()):
            raise ProviderError(_("MailerSend refused the sender address: the firm's domain is not verified yet."))
        self.state["sent"] += 1
        self.state["last_test"] = {"subject": subject, "reply_to": reply_to_email}
        return True


class DryRunZone(_Faults):
    service = "Cloudflare"
    is_simulation = True

    def __init__(self, state=None, zone_id="zone-simulated", fail_on=None):
        self.state = state if state is not None else {}
        self.state.setdefault("records", {})
        self.state.setdefault("seq", 0)
        self.zone_id = zone_id
        self.fail_on = dict(fail_on or {})
        self.calls = []

    def check(self):
        self._enter("check")
        return True

    def find_zone(self, name):
        self._enter("find_zone")
        return "zone-simulated"

    def find(self, kind, name):
        self._enter("find")
        return [{"id": key, "content": value["content"]} for key, value in sorted(self.state["records"].items())
                if value["type"] == kind and value["name"] == name]

    def create(self, kind, name, content):
        self._enter("create")
        self.state["seq"] += 1
        key = f"rec{self.state['seq']:06d}"
        self.state["records"][key] = {"type": kind, "name": name, "content": content}
        return key

    def update(self, record_id, kind, name, content):
        self._enter("update")
        self.state["records"][record_id] = {"type": kind, "name": name, "content": content}

    def delete(self, record_id):
        self._enter("delete")
        self.state["records"].pop(record_id, None)


# --------------------------------------------------------------------- one pass


def write_records(zone, records):
    """Writes what is missing or wrong. Returns [[type, name]] of every record the domain needs."""
    written = []
    for record in records:
        kind, name, content = record["type"], record["name"], record["content"]
        existing = zone.find(kind, name)
        same = [item for item in existing if _txt(item["content"]).lower() == content.lower()]
        if not same:
            # Only one CNAME per name, and only one SPF: a wrong one is corrected, not doubled.
            wrong = [item for item in existing
                     if kind == "CNAME" or _txt(item["content"]).lower().startswith("v=spf1")]
            if wrong and (kind == "CNAME" or content.lower().startswith("v=spf1")):
                zone.update(wrong[0]["id"], kind, name, content)
            else:
                zone.create(kind, name, content)
        written.append([kind, name])
    return written


def setup(mailersend, zone, state):
    """One pass. `state` (saved by the caller after the pass, whatever happens) holds:
    domain, domain_id, dns ([[type, name]]), verified, smtp_user_id, smtp_username.

    Returns ("verifying", None), ("ready", credentials) the one time an SMTP user is made, or
    ("done", None) when there is nothing left to do. Raises ProviderError.
    """
    domain = state["domain"]
    if state.get("domain_id") and not mailersend.domain_exists(state["domain_id"]):
        for key in ("domain_id", "dns", "verified", "smtp_user_id", "smtp_username"):
            state.pop(key, None)
    if not state.get("domain_id"):
        state["domain_id"] = mailersend.find_domain(domain) or mailersend.create_domain(domain)
    if not state.get("dns"):
        state["dns"] = write_records(zone, mailersend.dns_records(state["domain_id"], domain))
    if not state.get("verified"):
        if not mailersend.verify(state["domain_id"]):
            return "verifying", None
        state["verified"] = True
    if state.get("smtp_user_id"):
        return "done", None
    # A user made before a crash cannot give its password again: it is replaced.
    old = mailersend.find_smtp_user(state["domain_id"], SMTP_USER_NAME)
    if old:
        mailersend.delete_smtp_user(state["domain_id"], old)
    user_id, username, password = mailersend.create_smtp_user(state["domain_id"], SMTP_USER_NAME)
    state["smtp_user_id"], state["smtp_username"] = user_id, username
    return "ready", {"host": SMTP_HOST, "port": SMTP_PORT, "encryption": SMTP_ENCRYPTION,
                     "user": username, "password": password}


def renew_smtp_user(mailersend, state):
    """A new password for a domain already verified: the old user goes, setup() makes the next one."""
    if state.get("domain_id") and state.get("smtp_user_id"):
        mailersend.delete_smtp_user(state["domain_id"], state["smtp_user_id"])
    state.pop("smtp_user_id", None)
    state.pop("smtp_username", None)


def remove(mailersend, zone, state):
    """Undoes everything, last made first. Returns what could not be removed (empty: all gone).

    The DNS names are those saved, or MailerSend's list when none were saved; only names inside the
    firm's own subdomain are ever erased (records_from_answer).
    """
    leftovers = []
    domain = state.get("domain") or ""
    domain_id = state.get("domain_id")
    if not domain_id and domain:
        try:
            domain_id = mailersend.find_domain(domain)
        except ProviderError as error:
            leftovers.append(_("MailerSend domain: %(reason)s", reason=error.message))
    names = [tuple(item) for item in state.get("dns") or []]
    if not names and domain_id:
        try:
            names = [(r["type"], r["name"]) for r in mailersend.dns_records(domain_id, domain)]
        except ProviderError:
            names = []
    if not names and domain:
        # Nothing saved and nothing to ask: the names MailerSend uses (its documentation, 2026-11).
        names = [("TXT", domain)] + [("CNAME", f"{label}.{domain}") for label in
                                     ("ms1._domainkey", "ms2._domainkey", "mta", "email")]
    if domain_id:
        try:
            if state.get("smtp_user_id"):
                mailersend.delete_smtp_user(domain_id, state["smtp_user_id"])
            state.pop("smtp_user_id", None)
        except ProviderError as error:
            leftovers.append(_("MailerSend SMTP user: %(reason)s", reason=error.message))
    kept = []
    for kind, name in names:
        if kind not in RECORD_TYPES or not _within(name, domain):
            continue
        try:
            for item in zone.find(kind, name):
                zone.delete(item["id"])
        except ProviderError as error:
            kept.append([kind, name])
            leftovers.append(_("DNS record %(name)s: %(reason)s", name=name, reason=error.message))
    state["dns"] = kept
    if domain_id:
        try:
            mailersend.delete_domain(domain_id)
            state.pop("domain_id", None)
            state.pop("verified", None)
        except ProviderError as error:
            leftovers.append(_("MailerSend domain: %(reason)s", reason=error.message))
    return leftovers
