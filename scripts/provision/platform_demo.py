"""Three made-up firms for a preview of the admin Odoo, in SIMULATION only. Run in its Odoo shell:

    odoo-bin shell -c CONF -d DB --no-http < scripts/provision/platform_demo.py

One healthy, one with technical errors and a reported problem, one in the middle of onboarding.
Everything goes through the screens' own code (the wizard, the dry-run provider, signed simulated
heartbeats). It refuses to run on a platform switched to the real provider, and runs once.
"""

import base64
import struct
import time
from datetime import datetime

from odoo.addons.ea_platform_admin.services import heartbeat
from odoo.addons.ea_platform_admin.services.provider import DryRunDns, DryRunProbe, DryRunProvider

DEMO_SHA = "d0d0d0d0d0d0"


def ssh_key(number):
    algorithm = b"ssh-ed25519"
    blob = struct.pack(">I", len(algorithm)) + algorithm + struct.pack(">I", 32) + bytes([number]) * 32
    return "ssh-ed25519 " + base64.b64encode(blob).decode() + " demo@preview"


def demo(env):
    if not env["platform.services"]._is_simulation():
        raise SystemExit("Refused: this platform uses the real provider. The demo is for a simulation only.")
    if env["platform.firm"].sudo().search_count([("slug", "like", "demo-")]):
        print("RESULT the demo firms are already there")
        return
    admin = env.ref("base.user_admin")
    user_env = env(user=admin.id, su=False)
    release = env["platform.release"].sudo().search([("sha", "=", DEMO_SHA)]) or env["platform.release"].sudo().create({
        "sha": DEMO_SHA, "bundle_sha256": "d" * 64, "label": "Demo release (simulation)",
    })
    if not release.catalogue_loaded_at:
        release.with_user(admin).action_read_catalogue_here()
    services = type(env["platform.services"])

    def onboard(name, slug, number, addons=False, slow=False):
        wizard = user_env["platform.onboarding.wizard"].create({
            "name": name, "slug": slug, "contact_name": "Demo Contact", "contact_email": f"contact@{slug}.example",
            "allowed_email_domains": f"{slug}.example", "region": "cdg", "size": "standard", "lang": "fr_FR",
            "ssh_public_key": ssh_key(number), "release_id": release.id,
        })
        wizard.action_next()
        wizard.action_next()
        if addons:
            wizard.addon_line_ids.write({"enabled": True})
            wizard.addons_reason = "Demo: asked for in the engagement letter"
        wizard.action_next()
        wizard.confirmed = True
        original = services._outside
        if slow:
            # A server that takes its time to start: the run waits at "Creating the server".
            def slow_outside(self):
                state = self._dry_state()
                return DryRunProvider(state["provider"], boot_polls=10 ** 6), DryRunDns(state["dns"]), DryRunProbe()
            services._outside = slow_outside
        try:
            result = wizard.action_confirm()
        finally:
            services._outside = original
        env.cr.commit()
        return env["platform.provision.job"].browse(result["res_id"]).firm_id.sudo()

    healthy = onboard("Cabinet Akwa (demo)", "demo-akwa", 61, addons=True)
    healthy.with_user(admin).action_confirm_key_escrow()
    healthy._simulate_heartbeat()

    troubled = onboard("Cabinet Bonapriso (demo)", "demo-bonapriso", 62)
    troubled.with_user(admin).action_confirm_key_escrow()
    now = heartbeat.format_instant(datetime.utcnow().replace(microsecond=0))
    troubled._simulate_heartbeat(errors=[
        {"module": "ea_audit_tools", "model": "ea.audit.tb.line", "kind": "ZeroDivisionError", "count": 7, "last_at": now},
        {"module": "ea_audit_papers", "model": "ea.audit.paper", "kind": "KeyError", "count": 2, "last_at": now},
    ])
    env["platform.ticket"].sudo().create({
        "firm_id": troubled.id, "ref": "d" * 32, "subject": "The materiality screen shows an error",
        "message": "Demo message: when I open materiality on a new engagement, an error appears.",
        "screen": "ea.audit.materiality", "received_at": datetime.utcnow().replace(microsecond=0),
    })
    troubled._evaluate_health()

    onboard("Cabinet Deido (demo)", "demo-deido", 63, slow=True)
    env.cr.commit()
    for firm in env["platform.firm"].sudo().search([("slug", "like", "demo-")]):
        print("RESULT", firm.name, "|", firm.state, "|", firm.health_color, "|", firm.health_summary)


demo(env)  # noqa: F821 - given by the Odoo shell
env.cr.commit()  # noqa: F821
time.sleep(0)
