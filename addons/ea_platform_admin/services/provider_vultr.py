"""Vultr (official API v2) and Cloudflare behind the interfaces of provider.py. Pure.

NEVER RUN AGAINST THE REAL SERVICES during this build: the tests inject a fake transport and check
the requests. The endpoints are written from Vultr's and Cloudflare's public API documentation and
need the checks listed in docs/runbook/PREREQUISITES.md before the first real firm.

The token is read from a file that only its owner can read and is held by nothing but this object.
It never appears in an error, a log or a repr.
"""

import base64
import json
import os
import stat
import urllib.error
import urllib.request
from dataclasses import dataclass

from .provider import DnsProvider, HealthProbe, ProviderError, Server, ServerProvider, StorageCredentials

VULTR_API = "https://api.vultr.com/v2"
CLOUDFLARE_API = "https://api.cloudflare.com/client/v4"
TIMEOUT_SECONDS = 30

_SERVER_STATUS = {"pending": "pending", "active": "active", "suspended": "stopped", "resizing": "pending"}


def read_secret_file(path):
    """The content of a file nobody but its owner can read. Anything else is refused.

    On the control plane the file is root-only and systemd's LoadCredential hands the Odoo service
    a private copy (see deploy/control-plane/install-control-plane.sh).
    """
    try:
        info = os.stat(path)
    except OSError:
        raise ProviderError("Fichier de jeton introuvable sur le serveur de contrôle.") from None
    if not stat.S_ISREG(info.st_mode):
        raise ProviderError("Le jeton doit être un fichier ordinaire.")
    if os.name == "posix" and info.st_mode & 0o077:
        raise ProviderError("Fichier de jeton trop ouvert : seul son propriétaire doit pouvoir le lire.")
    try:
        with open(path, encoding="utf-8") as handle:
            token = handle.read().strip()
    except OSError:
        raise ProviderError("Fichier de jeton illisible.") from None
    if not token:
        raise ProviderError("Le fichier de jeton est vide.")
    return token


@dataclass
class HttpResponse:
    status: int
    body: bytes = b""


class UrllibTransport:
    """The only code that opens a connection. Tests replace it."""

    def __call__(self, method, url, headers, body):
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
                return HttpResponse(response.status, response.read())
        except urllib.error.HTTPError as error:
            return HttpResponse(error.code, error.read())
        except OSError as error:
            raise ProviderError(f"Fournisseur injoignable ({type(error).__name__}).", retryable=True) from None


class _Api:
    def __init__(self, base, token, transport, service):
        self._base = base
        self.__token = token
        self._transport = transport or UrllibTransport()
        self._service = service

    def __repr__(self):
        return f"<{self._service} API client>"

    def call(self, method, path, payload=None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Authorization": f"Bearer {self.__token}", "Content-Type": "application/json"}
        response = self._transport(method, self._base + path, headers, body)
        if response.status == 404 and method in ("GET", "DELETE"):
            return None
        if response.status in (429,) or response.status >= 500:
            raise ProviderError(f"{self._service} : erreur temporaire {response.status}.", retryable=True)
        if response.status >= 400:
            # The answer is not quoted: it could repeat what was sent, and that may hold secrets.
            raise ProviderError(f"{self._service} a refusé {method} {path.split('?')[0]} ({response.status}).")
        if not response.body:
            return {}
        try:
            return json.loads(response.body)
        except ValueError:
            raise ProviderError(f"{self._service} : réponse illisible.", retryable=True) from None


class VultrProvider(ServerProvider):
    name = "vultr"
    is_simulation = False

    def __init__(self, token, object_storage_cluster=None, transport=None):
        self._api = _Api(VULTR_API, token, transport, "Vultr")
        self._cluster = object_storage_cluster

    def _all(self, path, key):
        """Every page of a list endpoint."""
        items, cursor = [], ""
        while True:
            separator = "&" if "?" in path else "?"
            suffix = f"{separator}per_page=500" + (f"&cursor={cursor}" if cursor else "")
            answer = self._api.call("GET", path + suffix) or {}
            items.extend(answer.get(key, []))
            cursor = (answer.get("meta", {}).get("links", {}) or {}).get("next", "")
            if not cursor:
                return items

    def find_ssh_key(self, label):
        for item in self._all("/ssh-keys", "ssh_keys"):
            if item.get("name") == label:
                return item["id"]
        return None

    def create_ssh_key(self, label, public_key):
        answer = self._api.call("POST", "/ssh-keys", {"name": label, "ssh_key": public_key.strip()})
        return answer["ssh_key"]["id"]

    def delete_ssh_key(self, key_id):
        self._api.call("DELETE", f"/ssh-keys/{key_id}")

    def find_firewall(self, label):
        for item in self._all("/firewalls", "firewall_groups"):
            if item.get("description") == label:
                return item["id"]
        return None

    def create_firewall(self, label, ssh_allowlist):
        answer = self._api.call("POST", "/firewalls", {"description": label})
        firewall_id = answer["firewall_group"]["id"]
        self.set_ssh_allowlist(firewall_id, ssh_allowlist)
        return firewall_id

    def set_ssh_allowlist(self, firewall_id, ssh_allowlist):
        for rule in self._all(f"/firewalls/{firewall_id}/rules", "firewall_rules"):
            self._api.call("DELETE", f"/firewalls/{firewall_id}/rules/{rule['id']}")
        for cidr in ssh_allowlist:
            address, _, size = cidr.partition("/")
            version = "v6" if ":" in address else "v4"
            self._rule(firewall_id, version, address, int(size or (128 if version == "v6" else 32)), "22")
        for port in ("80", "443"):
            self._rule(firewall_id, "v4", "0.0.0.0", 0, port)
            self._rule(firewall_id, "v6", "::", 0, port)

    def _rule(self, firewall_id, version, subnet, size, port):
        self._api.call("POST", f"/firewalls/{firewall_id}/rules", {
            "ip_type": version,
            "protocol": "tcp",
            "subnet": subnet,
            "subnet_size": size,
            "port": port,
        })

    def delete_firewall(self, firewall_id):
        self._api.call("DELETE", f"/firewalls/{firewall_id}")

    def find_storage(self, label):
        for item in self._all("/object-storage", "object_storages"):
            if item.get("label") == label:
                return item["id"]
        return None

    def create_storage(self, label, region):
        if not self._cluster:
            raise ProviderError("Aucun cluster de stockage objet configuré (ea_platform.vultr_storage_cluster).")
        answer = self._api.call("POST", "/object-storage", {"cluster_id": int(self._cluster), "label": label})
        return answer["object_storage"]["id"]

    def storage_credentials(self, storage_id):
        answer = self._api.call("GET", f"/object-storage/{storage_id}")
        if not answer:
            raise ProviderError("Stockage objet introuvable chez Vultr.")
        data = answer["object_storage"]
        if not data.get("s3_access_key"):
            raise ProviderError("Stockage objet pas encore prêt.", retryable=True)
        return StorageCredentials(
            endpoint=data["s3_hostname"],
            bucket=data["label"],
            access_key=data["s3_access_key"],
            secret_key=data["s3_secret_key"],
        )

    def delete_storage(self, storage_id):
        self._api.call("DELETE", f"/object-storage/{storage_id}")

    @staticmethod
    def _server(data):
        status = _SERVER_STATUS.get(data.get("status"), "pending")
        if status == "active" and data.get("power_status") == "stopped":
            status = "stopped"
        return Server(
            id=data["id"],
            label=data.get("label", ""),
            status=status,
            ip=data.get("main_ip", "") if data.get("main_ip") != "0.0.0.0" else "",
            region=data.get("region", ""),
            plan=data.get("plan", ""),
            tags=list(data.get("tags") or []),
        )

    def find_server(self, label):
        for item in self._all(f"/instances?label={label}", "instances"):
            if item.get("label") == label:
                return self._server(item)
        return None

    def create_server(self, spec):
        # Vultr's answer holds a default root password. It is dropped here, kept nowhere, and the
        # install script locks the password on first boot.
        answer = self._api.call("POST", "/instances", {
            "region": spec.region,
            "plan": spec.plan,
            "os_id": int(spec.os_id),
            "label": spec.label,
            "hostname": spec.hostname,
            "sshkey_id": [spec.ssh_key_id],
            "firewall_group_id": spec.firewall_id,
            "user_data": base64.b64encode(spec.user_data.encode("utf-8")).decode("ascii"),
            "tags": list(spec.tags),
            "enable_ipv6": False,
            "activation_email": False,
            "backups": "disabled",
        })
        return self._server(answer["instance"])

    def get_server(self, server_id):
        answer = self._api.call("GET", f"/instances/{server_id}")
        return self._server(answer["instance"]) if answer else None

    def stop_server(self, server_id):
        self._api.call("POST", f"/instances/{server_id}/halt", {})

    def start_server(self, server_id):
        self._api.call("POST", f"/instances/{server_id}/start", {})

    def destroy_server(self, server_id):
        self._api.call("DELETE", f"/instances/{server_id}")

    def list_servers(self, tag):
        return [self._server(item) for item in self._all(f"/instances?tag={tag}", "instances")]


class CloudflareDns(DnsProvider):
    """DNS-only records (no proxy), which is what Let's Encrypt's first check needs."""

    name = "cloudflare"
    is_simulation = False

    def __init__(self, token, zone_id, transport=None):
        self._api = _Api(CLOUDFLARE_API, token, transport, "Cloudflare")
        self._zone = zone_id

    def _record(self, hostname):
        answer = self._api.call("GET", f"/zones/{self._zone}/dns_records?type=A&name={hostname}") or {}
        results = answer.get("result") or []
        return results[0] if results else None

    def find_record(self, hostname):
        record = self._record(hostname)
        return record["content"] if record else None

    def upsert_a_record(self, hostname, ip):
        payload = {"type": "A", "name": hostname, "content": ip, "ttl": 300, "proxied": False}
        record = self._record(hostname)
        if record:
            self._api.call("PUT", f"/zones/{self._zone}/dns_records/{record['id']}", payload)
        else:
            self._api.call("POST", f"/zones/{self._zone}/dns_records", payload)

    def delete_record(self, hostname):
        record = self._record(hostname)
        if record:
            self._api.call("DELETE", f"/zones/{self._zone}/dns_records/{record['id']}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class UrllibProbe(HealthProbe):
    def status_code(self, url):
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(url, timeout=TIMEOUT_SECONDS) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code
        except OSError:
            return 0
