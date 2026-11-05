from datetime import datetime, timedelta

import pytest

from .. import provisioning as p
from ..provider import DryRunDns, DryRunProbe, DryRunProvider, ProviderError
from ..recipe import REQUIRED_KEYS, SECRET_KEYS, render_user_data

NOW = datetime(2026, 11, 5, 12)
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJ owner@laptop"
PUB = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEA\n-----END PUBLIC KEY-----"


def values(**changes):
    data = {key: "x" for key in REQUIRED_KEYS}
    data.update({
        "FIRM_SLUG": "cabinet-a",
        "FIRM_HOST": "cabinet-a.auditisa.com",
        "RELEASE_BASE_URL": "https://releases.example.invalid/abc",
        "HEARTBEAT_TOKEN": "HBTOKEN",
        "S3_ACCESS_KEY": "ACCESSKEY",
        "S3_SECRET_KEY": "SECRETKEY",
    })
    data.update(changes)
    return data


def build(provider=None, dns=None, probe=None, heartbeat=True, config=None, resources=None):
    state = {"activated": False, "first_admin": 0, "user_data": None, "seen": heartbeat}
    provider = provider if provider is not None else DryRunProvider()
    hooks = {
        "validate": lambda: "",
        "check_release": lambda: None,
        "prepare_first_admin": lambda: state.__setitem__("first_admin", state["first_admin"] + 1),
        "user_data": lambda credentials: render_user_data(
            values(S3_ACCESS_KEY=credentials.access_key, S3_SECRET_KEY=credentials.secret_key,
                   S3_BUCKET=credentials.bucket, S3_ENDPOINT=credentials.endpoint),
            KEY, PUB),
        "heartbeat_seen": lambda: state["seen"],
        "figures_problems": lambda: [],
        "activate": lambda: state.__setitem__("activated", True),
    }
    cfg = {
        "slug": "cabinet-a", "host": "cabinet-a.auditisa.com", "region": "cdg", "plan": "vc2-4c-8gb",
        "os_id": 1, "ssh_public_key": KEY, "ssh_allowlist": ["198.51.100.7/32"],
    }
    cfg.update(config or {})
    ctx = p.Context(provider, dns if dns is not None else DryRunDns(), probe or DryRunProbe(),
                    resources if resources is not None else {}, hooks, cfg, NOW)
    return ctx, state


def provider_is_empty(provider):
    return not any(provider.state[kind] for kind in ("ssh_keys", "firewalls", "storages", "servers"))


def test_all_steps_run_and_the_firm_ends_active():
    ctx, state = build()
    steps = p.new_steps()
    assert p.advance(steps, ctx) == p.JOB_DONE
    assert all(step["state"] == p.DONE for step in steps)
    assert state["activated"]
    assert state["first_admin"] == 1
    assert ctx.resources["server_id"]
    assert ctx.dns.find_record("cabinet-a.auditisa.com") == ctx.resources["server_ip"]


def test_the_health_check_is_automatic_and_last_but_one():
    assert p.STEP_CODES[-2:] == ("health_check", "activate")


def test_it_waits_for_the_server_to_boot_then_resumes():
    ctx, _state = build(provider=DryRunProvider(boot_polls=2))
    steps = p.new_steps()
    assert p.advance(steps, ctx) == p.JOB_WAITING
    assert p.advance(steps, ctx) == p.JOB_DONE


def test_it_waits_for_the_first_heartbeat():
    ctx, state = build(heartbeat=False)
    steps = p.new_steps()
    assert p.advance(steps, ctx) == p.JOB_WAITING
    assert not state["activated"]
    state["seen"] = True
    assert p.advance(steps, ctx) == p.JOB_DONE
    assert state["activated"]


def test_running_again_creates_nothing_new():
    ctx, _state = build(heartbeat=False)
    steps = p.new_steps()
    p.advance(steps, ctx)
    before = ctx.provider.snapshot()
    for step in steps:
        if step["code"] != "validate":
            step["state"] = p.PENDING  # the worst case: the job forgot everything it did
    ctx.resources.clear()
    p.advance(steps, ctx)
    assert ctx.provider.snapshot() == before
    assert ctx.resources["server_id"]


def test_a_crash_in_the_middle_resumes_where_it_stopped():
    provider = DryRunProvider()
    ctx, _state = build(provider=provider, heartbeat=False)
    steps = p.new_steps()
    p.advance(steps, ctx)
    done = [s["code"] for s in steps if s["state"] == p.DONE]
    assert "server" in done
    # A new process with a new context and only what was saved.
    ctx2, state2 = build(provider=provider, dns=ctx.dns, resources=dict(ctx.resources))
    assert p.advance(steps, ctx2) == p.JOB_DONE
    assert len(provider.state["servers"]) == 1
    assert state2["activated"]


def test_a_running_step_found_after_a_crash_is_run_again():
    provider = DryRunProvider()
    ctx, _state = build(provider=provider, heartbeat=False)
    steps = p.new_steps()
    p.advance(steps, ctx)
    server_step = next(s for s in steps if s["code"] == "server")
    server_step["state"] = p.RUNNING
    ctx.resources.pop("server_id")
    ctx2, _ = build(provider=provider, dns=ctx.dns, resources=dict(ctx.resources))
    assert p.advance(steps, ctx2) == p.JOB_DONE
    assert len(provider.state["servers"]) == 1


def test_a_temporary_failure_retries_then_succeeds():
    ctx, state = build(provider=DryRunProvider(fail_on={"create_server": 2}))
    steps = p.new_steps()
    assert p.advance(steps, ctx) == p.JOB_WAITING
    assert p.advance(steps, ctx) == p.JOB_WAITING
    assert p.advance(steps, ctx) == p.JOB_DONE
    assert state["activated"]


def test_a_failure_that_keeps_coming_ends_in_rollback():
    ctx, state = build(provider=DryRunProvider(fail_on={"create_server": 99}))
    steps = p.new_steps()
    results = [p.advance(steps, ctx) for _ in range(p.MAX_ATTEMPTS)]
    assert results[-1] == p.JOB_ROLLED_BACK
    assert provider_is_empty(ctx.provider)
    assert not state["activated"]


FAILING_METHODS = [
    ("create_ssh_key", "ssh_key"),
    ("create_firewall", "firewall"),
    ("create_storage", "storage"),
    ("storage_credentials", "server"),
    ("create_server", "server"),
    ("get_server", "wait_server"),
]


@pytest.mark.parametrize("method,code", FAILING_METHODS)
def test_a_failure_at_any_provider_step_leaves_nothing(method, code):
    provider = DryRunProvider(fail_on={method: ProviderError("refusé")})
    if method == "get_server":
        # Fails in the step, and once in the undo's confirmation it no longer does.
        provider.fail_on = {}
        real = provider.get_server
        attempts = {"n": 0}

        def flaky(server_id):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise ProviderError("refusé")
            return real(server_id)

        provider.get_server = flaky
    ctx, state = build(provider=provider)
    steps = p.new_steps()
    assert p.advance(steps, ctx) == p.JOB_ROLLED_BACK
    assert provider_is_empty(provider)
    assert next(s for s in steps if s["code"] == code)["state"] == p.FAILED
    assert not state["activated"]


def test_a_dns_failure_removes_the_server():
    provider = DryRunProvider()
    dns = DryRunDns(fail_on={"upsert_a_record": ProviderError("refusé")})
    ctx, _state = build(provider=provider, dns=dns)
    assert p.advance(p.new_steps(), ctx) == p.JOB_ROLLED_BACK
    assert provider_is_empty(provider)
    assert dns.state["records"] == {}


def test_a_failed_health_check_after_its_timeout_removes_everything():
    probe = DryRunProbe({"/web/health": 502})
    ctx, state = build(probe=probe)
    steps = p.new_steps()
    assert p.advance(steps, ctx) == p.JOB_WAITING
    assert "502" in next(s for s in steps if s["code"] == "health_check")["message"]
    ctx.now = NOW + timedelta(minutes=45)
    next(s for s in steps if s["code"] == "health_check")["attempts"] = p.MAX_ATTEMPTS
    assert p.advance(steps, ctx) == p.JOB_ROLLED_BACK
    assert provider_is_empty(ctx.provider)
    assert ctx.dns.state["records"] == {}
    assert not state["activated"]


def test_an_open_database_manager_fails_the_health_check():
    ctx, _state = build(probe=DryRunProbe({"/web/database/manager": 200}))
    steps = p.new_steps()
    assert p.advance(steps, ctx) == p.JOB_WAITING
    assert "gestionnaire de bases" in next(s for s in steps if s["code"] == "health_check")["message"]


def test_an_install_that_never_ends_times_out_and_rolls_back():
    ctx, _state = build(heartbeat=False)
    steps = p.new_steps()
    assert p.advance(steps, ctx) == p.JOB_WAITING
    ctx.now = NOW + timedelta(minutes=61)
    assert p.advance(steps, ctx) == p.JOB_ROLLED_BACK
    assert provider_is_empty(ctx.provider)


def test_a_server_that_cannot_be_destroyed_is_reported_as_an_orphan():
    provider = DryRunProvider(fail_on={"destroy_server": ProviderError("refusé par le fournisseur")})
    ctx, _state = build(provider=provider, heartbeat=False)
    steps = p.new_steps()
    p.advance(steps, ctx)
    result, orphans = p.rollback(steps, ctx)
    assert result == p.JOB_ROLLBACK_FAILED
    assert len(orphans) == 1
    assert "Création du serveur" in orphans[0]
    assert provider.state["servers"]
    # The other resources are still removed, except what the server still needs at the provider.
    assert not provider.state["ssh_keys"]


def test_a_destroy_that_answers_ok_but_leaves_the_server_is_an_orphan():
    provider = DryRunProvider()
    provider.destroy_server = lambda server_id: None
    ctx, _state = build(provider=provider, heartbeat=False)
    steps = p.new_steps()
    p.advance(steps, ctx)
    result, orphans = p.rollback(steps, ctx)
    assert result == p.JOB_ROLLBACK_FAILED
    assert "existe encore" in orphans[0]


def test_a_bug_in_a_step_still_cleans_up():
    ctx, _state = build(heartbeat=False)
    ctx.hooks["figures_problems"] = lambda: 1 / 0
    ctx.hooks["heartbeat_seen"] = lambda: True
    steps = p.new_steps()
    assert p.advance(steps, ctx) == p.JOB_ROLLED_BACK
    assert provider_is_empty(ctx.provider)
    assert "ZeroDivisionError" in next(s for s in steps if s["code"] == "health_check")["message"]


def test_refused_validation_creates_nothing():
    ctx, _state = build()
    ctx.hooks["validate"] = lambda: "slug déjà pris"
    steps = p.new_steps()
    assert p.advance(steps, ctx) == p.JOB_ROLLED_BACK
    assert ctx.provider.calls == []


def test_offboarding_removes_everything():
    ctx, _state = build()
    p.advance(p.new_steps(), ctx)
    assert not provider_is_empty(ctx.provider)
    assert p.destroy_resources(ctx) == []
    assert provider_is_empty(ctx.provider)
    assert ctx.dns.state["records"] == {}


def test_offboarding_reports_what_stays():
    provider = DryRunProvider()
    ctx, _state = build(provider=provider)
    p.advance(p.new_steps(), ctx)
    provider.fail_on["destroy_server"] = ProviderError("refusé")
    leftovers = p.destroy_resources(ctx)
    assert len(leftovers) == 1
    assert leftovers[0].startswith("serveur")


def test_two_firms_share_no_resource():
    provider, dns = DryRunProvider(), DryRunDns()
    a, _ = build(provider=provider, dns=dns)
    b, _ = build(provider=provider, dns=dns, config={"slug": "cabinet-b", "host": "cabinet-b.auditisa.com"})
    p.advance(p.new_steps(), a)
    p.advance(p.new_steps(), b)
    for key in ("ssh_key_id", "firewall_id", "storage_id", "server_id", "server_ip"):
        assert a.resources[key] != b.resources[key], key


# ---------------------------------------------------------------- the first-boot text


def test_user_data_holds_only_the_listed_secrets():
    assert SECRET_KEYS == {"HEARTBEAT_TOKEN", "S3_ACCESS_KEY", "S3_SECRET_KEY"}
    text = render_user_data(values(), KEY, PUB)
    assert text.startswith("#cloud-config")
    assert "HBTOKEN" in text
    for word in ("admin_passwd", "db_password", "MASTER", "RESTIC", "PGPASSWORD", "PASSWORD"):
        assert word not in text


def test_user_data_checks_the_signature_before_running_anything():
    text = render_user_data(values(), KEY, PUB)
    assert text.index("pkeyutl -verify") < text.rindex("install-firm-server.sh")
    assert text.index("sha256sum -c") < text.rindex("install-firm-server.sh")
    assert "set -euo pipefail" in text
    assert "ssh_pwauth: false" in text


@pytest.mark.parametrize("bad", ["a'b", "a;reboot", "$(reboot)", "a`b`", "a\nb", 'a"b'])
def test_user_data_refuses_values_that_could_break_out(bad):
    with pytest.raises(ValueError):
        render_user_data(values(FIRM_ADMIN_EMAIL=bad), KEY, PUB)


def test_user_data_refuses_missing_and_unknown_keys():
    data = values()
    del data["HEARTBEAT_TOKEN"]
    with pytest.raises(ValueError):
        render_user_data(data, KEY, PUB)
    with pytest.raises(ValueError):
        render_user_data(values(DB_PASSWORD="x"), KEY, PUB)


def test_user_data_refuses_a_key_that_is_not_one_public_key():
    with pytest.raises(ValueError):
        render_user_data(values(), "ssh-rsa AAAA", PUB)
    with pytest.raises(ValueError):
        render_user_data(values(), KEY + "\nssh-ed25519 BBBB", PUB)


def test_user_data_stays_under_the_limit():
    assert len(render_user_data(values(), KEY, PUB)) < 8000
