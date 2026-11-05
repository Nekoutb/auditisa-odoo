"""What a firm server would say, for the dry-run mode and the tests. Pure.

It builds real signed heartbeats, which go through the real receiver: a simulated firm can only
report what a real one could.
"""

import json
from datetime import timedelta

from . import heartbeat
from .heartbeat import format_instant


def healthy_figures(now, release, users=1, engagements=0):
    return {
        "schema": heartbeat.SCHEMA_VERSION,
        "odoo_version": "19.0",
        "release": release,
        "disk_total_gb": 160,
        "disk_used_pct": 12,
        "mem_total_mb": 7900,
        "mem_available_mb": 5200,
        "users_active": users,
        "engagements_active": engagements,
        "last_backup_at": format_instant(now),
        "last_backup_ok": True,
        "last_restore_test_at": format_instant(now),
        "last_restore_test_ok": True,
        "cert_expires_on": (now.date() + timedelta(days=80)).isoformat(),
        "mail_enabled": False,
        "update_state": "idle",
        "update_release": None,
        "export_state": "none",
        "export_at": None,
        "export_sha256": None,
        "ssh_sessions_24h": 0,
        "last_ssh_at": None,
    }


def signed_request(token, slug, timestamp, figures):
    """(headers, body), exactly as ea_audit_firm_agent sends them."""
    body = json.dumps(figures, sort_keys=True, separators=(",", ":")).encode("utf-8")
    headers = {
        heartbeat.HEADER_FIRM: slug,
        heartbeat.HEADER_TIMESTAMP: str(timestamp),
        heartbeat.HEADER_SIGNATURE: heartbeat.sign(token, slug, timestamp, body),
    }
    return headers, body
