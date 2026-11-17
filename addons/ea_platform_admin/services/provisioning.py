"""The steps that bring up one firm server, and how they run, resume and roll back. Pure.

`advance` runs steps until one must wait or all are done. Every step is safe to run twice, because
it first looks for what it would create: a job stopped at any point (crash, restart, failure) can
be resumed. `rollback` undoes what was done, in reverse. A resource that cannot be removed is
reported in `orphans`, and the caller flags the firm loudly: nothing fails silently.

The steps know nothing of Odoo. They work on `ctx`, whose `resources` dict the caller saves after
each step, and call its hooks.
"""

from datetime import timedelta

from .messages import _
from .provider import ProviderError, ServerSpec

PENDING, RUNNING, DONE, FAILED, UNDONE = "pending", "running", "done", "failed", "undone"
JOB_RUNNING, JOB_WAITING, JOB_DONE, JOB_ROLLED_BACK, JOB_ROLLBACK_FAILED = (
    "running", "waiting", "done", "rolled_back", "rollback_failed",
)

MAX_ATTEMPTS = 3
SERVER_TAG = "auditisa-firm"


class Wait(Exception):
    """The step cannot finish yet; it is run again later. Not an error."""


class Context:
    """What the steps need. Hooks are plain callables, so tests can replace any of them."""

    def __init__(self, provider, dns, probe, resources, hooks, config, now):
        self.provider = provider
        self.dns = dns
        self.probe = probe
        self.resources = resources
        self.hooks = hooks
        self.config = config
        self.now = now


def label_of(slug):
    return f"auditisa-firm-{slug}"


# --------------------------------------------------------------------- the steps


def _do_validate(ctx):
    errors = ctx.hooks["validate"]()
    if errors:
        raise ProviderError(_("Check refused: %(reason)s", reason=errors[0]))
    ctx.hooks["check_release"]()


def _do_ssh_key(ctx):
    label = label_of(ctx.config["slug"])
    key_id = ctx.resources.get("ssh_key_id") or ctx.provider.find_ssh_key(label)
    if not key_id:
        key_id = ctx.provider.create_ssh_key(label, ctx.config["ssh_public_key"])
    ctx.resources["ssh_key_id"] = key_id


def _undo_ssh_key(ctx):
    key_id = ctx.resources.get("ssh_key_id") or ctx.provider.find_ssh_key(label_of(ctx.config["slug"]))
    if key_id:
        ctx.provider.delete_ssh_key(key_id)
    ctx.resources.pop("ssh_key_id", None)


def _do_firewall(ctx):
    label = label_of(ctx.config["slug"])
    firewall_id = ctx.resources.get("firewall_id") or ctx.provider.find_firewall(label)
    if not firewall_id:
        firewall_id = ctx.provider.create_firewall(label, ctx.config["ssh_allowlist"])
    ctx.resources["firewall_id"] = firewall_id


def _undo_firewall(ctx):
    firewall_id = ctx.resources.get("firewall_id") or ctx.provider.find_firewall(label_of(ctx.config["slug"]))
    if firewall_id:
        ctx.provider.delete_firewall(firewall_id)
    ctx.resources.pop("firewall_id", None)


def _do_storage(ctx):
    label = label_of(ctx.config["slug"])
    storage_id = ctx.resources.get("storage_id") or ctx.provider.find_storage(label)
    if not storage_id:
        storage_id = ctx.provider.create_storage(label, ctx.config["region"])
    ctx.resources["storage_id"] = storage_id


def _undo_storage(ctx):
    storage_id = ctx.resources.get("storage_id") or ctx.provider.find_storage(label_of(ctx.config["slug"]))
    if storage_id:
        ctx.provider.delete_storage(storage_id)
    ctx.resources.pop("storage_id", None)


def _do_first_admin(ctx):
    ctx.hooks["prepare_first_admin"]()


def _do_server(ctx):
    label = label_of(ctx.config["slug"])
    server = ctx.provider.find_server(label)
    if not server:
        # The storage credentials are read now, passed on and forgotten: nothing keeps them here.
        credentials = ctx.provider.storage_credentials(ctx.resources["storage_id"])
        spec = ServerSpec(
            label=label,
            hostname=ctx.config["host"],
            region=ctx.config["region"],
            plan=ctx.config["plan"],
            os_id=ctx.config["os_id"],
            user_data=ctx.hooks["user_data"](credentials),
            ssh_key_id=ctx.resources["ssh_key_id"],
            firewall_id=ctx.resources["firewall_id"],
            tags=[SERVER_TAG, f"firm-{ctx.config['slug']}"],
        )
        server = ctx.provider.create_server(spec)
    ctx.resources["server_id"] = server.id
    ctx.resources["server_ip"] = server.ip


def _undo_server(ctx):
    server_id = ctx.resources.get("server_id")
    if not server_id:
        found = ctx.provider.find_server(label_of(ctx.config["slug"]))
        server_id = found.id if found else None
    if server_id:
        ctx.provider.destroy_server(server_id)
        # Destroying is asynchronous at some providers: an answer is not proof, so look again.
        if ctx.provider.get_server(server_id):
            raise ProviderError(_("Server %(id)s still exists after being destroyed.", id=server_id))
    ctx.resources.pop("server_id", None)
    ctx.resources.pop("server_ip", None)


def _do_wait_server(ctx):
    server = ctx.provider.get_server(ctx.resources["server_id"])
    if not server:
        raise ProviderError(_("The server has gone from the provider."))
    if server.status != "active" or not server.ip:
        raise Wait(_("The provider is starting the server."))
    ctx.resources["server_ip"] = server.ip


def _do_dns(ctx):
    # Always the platform's address: a firm's own domain comes later, as a second name on the same
    # server, once the firm has pointed it here (docs/runbook/ONBOARDING.md).
    host = ctx.config["host"]
    if ctx.dns.find_record(host) != ctx.resources["server_ip"]:
        ctx.dns.upsert_a_record(host, ctx.resources["server_ip"])
    ctx.resources["dns_record"] = host


def _undo_dns(ctx):
    host = ctx.config["host"]
    if ctx.dns.find_record(host) is not None:
        ctx.dns.delete_record(host)
    ctx.resources.pop("dns_record", None)


def _do_platform_mail(ctx):
    """The firm's platform email address (services/platform_mail.py), early, so that MailerSend's domain
    check runs while the server installs. The hook never fails the firm for an email problem: it
    asks for a retry twice, then records the problem on the firm, whose own checks carry on."""
    hook = ctx.hooks.get("platform_mail")
    if hook:
        hook()


def _undo_platform_mail(ctx):
    hook = ctx.hooks.get("platform_mail_undo")
    if hook:
        hook()


def _do_wait_install(ctx):
    if not ctx.hooks["heartbeat_seen"]():
        raise Wait(_("Installing on the server: waiting for the first heartbeat."))


def _do_health_check(ctx):
    host = ctx.config["host"]
    expected = (
        (f"http://{host}/web/login", (301, 308), _("port 80 must redirect to HTTPS")),
        (f"https://{host}/web/health", (200,), _("Odoo must answer")),
        (f"https://{host}/web/login", (200,), _("the login page must answer")),
    )
    # Reachable but not 200 is what list_db = False and nginx give; an unreachable server says nothing.
    refused = (f"https://{host}/web/database/manager", _("the database manager must be closed"))
    problems = []
    for url, codes, why in expected:
        code = ctx.probe.status_code(url)
        if code not in codes:
            problems.append(_("%(url)s: %(code)s (%(why)s)", url=url, code=code, why=why))
    code = ctx.probe.status_code(refused[0])
    if code in (0, 200):
        problems.append(_("%(url)s: %(code)s (%(why)s)", url=refused[0], code=code, why=refused[1]))
    problems.extend(ctx.hooks["figures_problems"]())
    if problems:
        raise ProviderError(_("Health check refused: %(problem)s", problem=problems[0]), retryable=True)


def _do_activate(ctx):
    ctx.hooks["activate"]()


class Step:
    def __init__(self, code, label, do, undo=None, timeout_minutes=None, seconds=0):
        self.code = code
        self.label = label
        self.do = do
        self.undo = undo
        self.timeout = timedelta(minutes=timeout_minutes) if timeout_minutes else None
        self.seconds = seconds


PIPELINE = (
    Step("validate", _("Checking the request"), _do_validate),
    Step("ssh_key", _("The firm's SSH key at the provider"), _do_ssh_key, _undo_ssh_key),
    Step("firewall", _("Provider firewall (22 restricted, 80, 443)"), _do_firewall, _undo_firewall),
    Step("storage", _("The firm's own backup storage"), _do_storage, _undo_storage),
    Step("first_admin", _("First administrator's one-time link"), _do_first_admin),
    Step("server", _("Creating the server"), _do_server, _undo_server),
    Step("wait_server", _("Starting the server"), _do_wait_server, timeout_minutes=15),
    Step("dns", _("The firm's address (DNS)"), _do_dns, _undo_dns),
    Step("platform_mail", _("Set up the firm's email"), _do_platform_mail, _undo_platform_mail),
    Step("wait_install", _("Install (Odoo, PostgreSQL, HTTPS, backups)"), _do_wait_install, timeout_minutes=60),
    Step("health_check", _("Automatic health check"), _do_health_check, timeout_minutes=30),
    Step("activate", _("Going live"), _do_activate),
)
STEP_CODES = tuple(step.code for step in PIPELINE)


# --------------------------------------------------------------------- the engine


def new_steps(pipeline=PIPELINE):
    return [
        {"code": s.code, "label": s.label, "state": PENDING, "attempts": 0,
         "message": "", "started_at": None, "finished_at": None}
        for s in pipeline
    ]


def advance(steps, ctx, pipeline=PIPELINE, on_change=None, max_attempts=MAX_ATTEMPTS):
    """Runs from the first unfinished step. Returns the job's state after this pass.

    JOB_DONE: all finished. JOB_WAITING: run again later. JOB_RUNNING is never returned.
    Raises nothing: a step that fails for good triggers the rollback, whose outcome is returned.
    """
    by_code = {step.code: step for step in pipeline}
    notify = on_change or (lambda: None)
    for state in steps:
        if state["state"] == DONE:
            continue
        step = by_code[state["code"]]
        if not state["started_at"]:
            state["started_at"] = ctx.now
        state["state"] = RUNNING
        notify()
        try:
            step.do(ctx)
        except Wait as wait:
            state["message"] = wait.args[0]
            if step.timeout and ctx.now - state["started_at"] > step.timeout:
                return _give_up(steps, state, ctx, pipeline, notify, _("Time limit passed: %(message)s", message=wait.args[0]))
            notify()
            return JOB_WAITING
        except ProviderError as error:
            state["attempts"] += 1
            state["message"] = error.message
            within_timeout = not step.timeout or ctx.now - state["started_at"] <= step.timeout
            if error.retryable and (state["attempts"] < max_attempts or (step.timeout and within_timeout)):
                notify()
                return JOB_WAITING
            return _give_up(steps, state, ctx, pipeline, notify, error.message)
        except Exception as error:  # noqa: BLE001  a bug in a step must still lead to a clean-up
            return _give_up(steps, state, ctx, pipeline, notify, _("Internal error: %(error)s", error=type(error).__name__))
        state["state"] = DONE
        state["finished_at"] = ctx.now
        state["message"] = ""
        notify()
    return JOB_DONE


def _give_up(steps, state, ctx, pipeline, notify, message):
    state["state"] = FAILED
    state["message"] = message
    state["finished_at"] = ctx.now
    notify()
    result, _orphans = rollback(steps, ctx, pipeline, notify)
    return result


def rollback(steps, ctx, pipeline=PIPELINE, on_change=None):
    """Undoes every step that started, last first. Returns (job state, orphans).

    An undo that fails does not stop the others: the point is to leave as little as possible.
    """
    by_code = {step.code: step for step in pipeline}
    notify = on_change or (lambda: None)
    orphans = []
    for state in reversed(steps):
        if state["state"] == PENDING or state["state"] == UNDONE:
            continue
        step = by_code[state["code"]]
        failed_message = state["message"] if state["state"] == FAILED else ""
        if step.undo:
            try:
                step.undo(ctx)
            except Exception as error:  # noqa: BLE001  whatever went wrong, it is reported below
                what = error.message if isinstance(error, ProviderError) else type(error).__name__
                orphans.append(_("%(step)s: %(what)s", step=state["label"], what=what))
                state["message"] = _("Rollback impossible: %(what)s", what=what)
                notify()
                continue
        state["state"] = FAILED if failed_message else UNDONE
        state["message"] = failed_message or _("Cancelled")
        notify()
    return (JOB_ROLLBACK_FAILED if orphans else JOB_ROLLED_BACK), orphans


def destroy_resources(ctx):
    """Offboarding: everything the steps made, in reverse. Returns what could not be removed."""
    leftovers = []
    for undo, label in (
        (_undo_platform_mail, _("email address")),
        (_undo_dns, _("DNS")),
        (_undo_server, _("server")),
        (_undo_storage, _("storage")),
        (_undo_firewall, _("firewall")),
        (_undo_ssh_key, _("SSH key")),
    ):
        try:
            undo(ctx)
        except ProviderError as error:
            leftovers.append(_("%(what)s: %(reason)s", what=label, reason=error.message))
    return leftovers
