"""The small interfaces behind which every outside service sits. Pure.

The control plane talks to the server provider, the DNS service and the firm's public address only
through these classes. The dry-run implementations are used by all tests and by the screens until
the owner switches on the real provider. The real ones are in provider_vultr.py.
"""

import abc
import copy
import hashlib
from dataclasses import asdict, dataclass, field


class ProviderError(Exception):
    """`retryable` is True when trying again may help (network, 5xx, rate limit)."""

    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class Server:
    id: str
    label: str
    status: str  # "pending" | "active" | "stopped"
    ip: str = ""
    region: str = ""
    plan: str = ""
    tags: list = field(default_factory=list)


@dataclass
class ServerSpec:
    label: str
    hostname: str
    region: str
    plan: str
    os_id: int
    user_data: str
    ssh_key_id: str
    firewall_id: str
    tags: list = field(default_factory=list)


@dataclass
class StorageCredentials:
    """Handed to the firm's server once. Never persisted on the control plane."""

    endpoint: str
    bucket: str
    access_key: str
    secret_key: str

    def __repr__(self):
        return f"StorageCredentials(endpoint={self.endpoint!r}, bucket={self.bucket!r}, ...)"


class ServerProvider(abc.ABC):
    """Every find_* looks a resource up by its label: that is what makes a step safe to re-run."""

    name = "abstract"
    is_simulation = False

    @abc.abstractmethod
    def find_ssh_key(self, label): ...

    @abc.abstractmethod
    def create_ssh_key(self, label, public_key): ...

    @abc.abstractmethod
    def delete_ssh_key(self, key_id): ...

    @abc.abstractmethod
    def find_firewall(self, label): ...

    @abc.abstractmethod
    def create_firewall(self, label, ssh_allowlist): ...

    @abc.abstractmethod
    def set_ssh_allowlist(self, firewall_id, ssh_allowlist): ...

    @abc.abstractmethod
    def delete_firewall(self, firewall_id): ...

    @abc.abstractmethod
    def find_storage(self, label): ...

    @abc.abstractmethod
    def create_storage(self, label, region): ...

    @abc.abstractmethod
    def storage_credentials(self, storage_id): ...

    @abc.abstractmethod
    def delete_storage(self, storage_id): ...

    @abc.abstractmethod
    def find_server(self, label): ...

    @abc.abstractmethod
    def create_server(self, spec): ...

    @abc.abstractmethod
    def get_server(self, server_id): ...

    @abc.abstractmethod
    def stop_server(self, server_id): ...

    @abc.abstractmethod
    def start_server(self, server_id): ...

    @abc.abstractmethod
    def destroy_server(self, server_id): ...

    @abc.abstractmethod
    def list_servers(self, tag): ...


class DnsProvider(abc.ABC):
    name = "abstract"
    is_simulation = False

    @abc.abstractmethod
    def find_record(self, hostname): ...

    @abc.abstractmethod
    def upsert_a_record(self, hostname, ip): ...

    @abc.abstractmethod
    def delete_record(self, hostname): ...


class HealthProbe(abc.ABC):
    is_simulation = False

    @abc.abstractmethod
    def status_code(self, url):
        """The HTTP status of a GET that does not follow redirects, or 0 if unreachable."""


class DryRunProvider(ServerProvider):
    """Changes nothing anywhere and makes no network call.

    Keeps its resources in `state`, a JSON-able dict, so they outlast a request when the caller
    saves it. `fail_on` maps a method name to an error, or to a number of failures before it starts
    to work: that is how the tests rehearse every failure.
    """

    name = "dry-run"
    is_simulation = True

    def __init__(self, state=None, fail_on=None, boot_polls=0):
        self.state = state if state is not None else {}
        for kind in ("ssh_keys", "firewalls", "storages", "servers"):
            self.state.setdefault(kind, {})
        self.state.setdefault("counter", 0)
        self.fail_on = dict(fail_on or {})
        self.boot_polls = boot_polls
        self.calls = []

    def _enter(self, method, *args):
        self.calls.append((method, args))
        rule = self.fail_on.get(method)
        if rule is None:
            return
        if isinstance(rule, int):
            if rule > 0:
                self.fail_on[method] = rule - 1
                raise ProviderError(f"{method}: panne simulée (temporaire)", retryable=True)
            return
        raise rule

    def _new_id(self, prefix):
        self.state["counter"] += 1
        return f"dry-{prefix}-{self.state['counter']:04d}"

    def _find(self, kind, label):
        for resource_id, resource in self.state[kind].items():
            if resource["label"] == label:
                return resource_id
        return None

    def find_ssh_key(self, label):
        self._enter("find_ssh_key", label)
        return self._find("ssh_keys", label)

    def create_ssh_key(self, label, public_key):
        self._enter("create_ssh_key", label)
        key_id = self._new_id("sshkey")
        self.state["ssh_keys"][key_id] = {"label": label, "public_key": public_key}
        return key_id

    def delete_ssh_key(self, key_id):
        self._enter("delete_ssh_key", key_id)
        self.state["ssh_keys"].pop(key_id, None)

    def find_firewall(self, label):
        self._enter("find_firewall", label)
        return self._find("firewalls", label)

    def create_firewall(self, label, ssh_allowlist):
        self._enter("create_firewall", label)
        firewall_id = self._new_id("firewall")
        self.state["firewalls"][firewall_id] = {
            "label": label,
            "rules": _firewall_rules(ssh_allowlist),
        }
        return firewall_id

    def set_ssh_allowlist(self, firewall_id, ssh_allowlist):
        self._enter("set_ssh_allowlist", firewall_id)
        self.state["firewalls"][firewall_id]["rules"] = _firewall_rules(ssh_allowlist)

    def delete_firewall(self, firewall_id):
        self._enter("delete_firewall", firewall_id)
        self.state["firewalls"].pop(firewall_id, None)

    def find_storage(self, label):
        self._enter("find_storage", label)
        return self._find("storages", label)

    def create_storage(self, label, region):
        self._enter("create_storage", label)
        storage_id = self._new_id("storage")
        self.state["storages"][storage_id] = {"label": label, "region": region}
        return storage_id

    def storage_credentials(self, storage_id):
        self._enter("storage_credentials", storage_id)
        if storage_id not in self.state["storages"]:
            raise ProviderError(f"stockage inconnu : {storage_id}")
        seed = hashlib.sha256(f"dry-run-storage-{storage_id}".encode()).hexdigest()
        return StorageCredentials(
            endpoint="dry-run.invalid",
            bucket=self.state["storages"][storage_id]["label"],
            access_key="DRYRUN" + seed[:14].upper(),
            secret_key=seed[14:54],
        )

    def delete_storage(self, storage_id):
        self._enter("delete_storage", storage_id)
        self.state["storages"].pop(storage_id, None)

    def find_server(self, label):
        self._enter("find_server", label)
        server_id = self._find("servers", label)
        return self._server(server_id) if server_id else None

    def create_server(self, spec):
        self._enter("create_server", spec.label)
        server_id = self._new_id("server")
        number = self.state["counter"]
        self.state["servers"][server_id] = {
            "label": spec.label,
            "status": "active" if not self.boot_polls else "pending",
            "polls": self.boot_polls,
            # 203.0.113.0/24 is reserved for documentation: it can never reach anything real.
            "ip": f"203.0.113.{(number % 250) + 1}",
            "region": spec.region,
            "plan": spec.plan,
            "tags": list(spec.tags),
            # Only a digest: the text holds secrets, and this state is kept between requests.
            "user_data_sha256": hashlib.sha256(spec.user_data.encode("utf-8")).hexdigest(),
            "firewall_id": spec.firewall_id,
            "ssh_key_id": spec.ssh_key_id,
        }
        return self._server(server_id)

    def _server(self, server_id):
        data = self.state["servers"][server_id]
        return Server(
            id=server_id,
            label=data["label"],
            status=data["status"],
            ip=data["ip"],
            region=data["region"],
            plan=data["plan"],
            tags=list(data["tags"]),
        )

    def get_server(self, server_id):
        self._enter("get_server", server_id)
        data = self.state["servers"].get(server_id)
        if data is None:
            return None
        if data["status"] == "pending":
            data["polls"] -= 1
            if data["polls"] <= 0:
                data["status"] = "active"
        return self._server(server_id)

    def stop_server(self, server_id):
        self._enter("stop_server", server_id)
        self.state["servers"][server_id]["status"] = "stopped"

    def start_server(self, server_id):
        self._enter("start_server", server_id)
        self.state["servers"][server_id]["status"] = "active"

    def destroy_server(self, server_id):
        self._enter("destroy_server", server_id)
        self.state["servers"].pop(server_id, None)

    def list_servers(self, tag):
        self._enter("list_servers", tag)
        return [self._server(s) for s, data in self.state["servers"].items() if tag in data["tags"]]

    def snapshot(self):
        return copy.deepcopy(self.state)


class DryRunDns(DnsProvider):
    name = "dry-run"
    is_simulation = True

    def __init__(self, state=None, fail_on=None):
        self.state = state if state is not None else {}
        self.state.setdefault("records", {})
        self.fail_on = dict(fail_on or {})
        self.calls = []

    def _enter(self, method, *args):
        self.calls.append((method, args))
        rule = self.fail_on.get(method)
        if rule is None:
            return
        if isinstance(rule, int):
            if rule > 0:
                self.fail_on[method] = rule - 1
                raise ProviderError(f"{method}: panne simulée (temporaire)", retryable=True)
            return
        raise rule

    def find_record(self, hostname):
        self._enter("find_record", hostname)
        return self.state["records"].get(hostname)

    def upsert_a_record(self, hostname, ip):
        self._enter("upsert_a_record", hostname)
        self.state["records"][hostname] = ip

    def delete_record(self, hostname):
        self._enter("delete_record", hostname)
        self.state["records"].pop(hostname, None)


class DryRunProbe(HealthProbe):
    """Answers like a correctly built firm server, unless `answers` says otherwise."""

    is_simulation = True

    def __init__(self, answers=None):
        self.answers = dict(answers or {})
        self.calls = []

    def status_code(self, url):
        self.calls.append(url)
        for fragment, code in self.answers.items():
            if fragment in url:
                return code
        if url.startswith("http://"):
            return 301
        if "/web/database" in url:
            return 404
        return 200


def _firewall_rules(ssh_allowlist):
    rules = [{"port": 22, "from": cidr} for cidr in ssh_allowlist]
    rules += [{"port": 80, "from": "any"}, {"port": 443, "from": "any"}]
    return rules


def server_as_dict(server):
    return asdict(server)
