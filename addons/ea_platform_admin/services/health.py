"""The colour of a firm on the board, and why. Pure."""

from datetime import timedelta

from .messages import _

GREEN, AMBER, RED, GREY = "green", "amber", "red", "grey"

_RANK = {GREY: 0, GREEN: 1, AMBER: 2, RED: 3}

# Agreed with the timers in deploy/firm: heartbeat every 15 min, backup nightly, restore test weekly.
HEARTBEAT_AMBER = timedelta(minutes=45)
HEARTBEAT_RED = timedelta(hours=2)
BACKUP_AMBER = timedelta(hours=26)
BACKUP_RED = timedelta(hours=50)
RESTORE_AMBER = timedelta(days=8)
RESTORE_RED = timedelta(days=15)
CERT_AMBER_DAYS = 21
CERT_RED_DAYS = 7
DISK_AMBER_PCT = 80
DISK_RED_PCT = 90
MEMORY_AMBER_PCT = 10
MEMORY_RED_PCT = 5


def evaluate(firm, now):
    """(colour, reasons) from a dict of a firm's figures. `reasons` lists the worst first."""
    found = []

    def add(colour, reason):
        found.append((colour, reason))

    state = firm.get("state")
    if firm.get("orphan_flag"):
        add(RED, _("ORPHAN SERVER: %(detail)s", detail=firm.get("orphan_detail") or _("to check at the provider")))
    if state == "archived":
        return (found[0][0], [found[0][1]]) if found else (GREY, [_("Archived")])
    if state == "suspended":
        return (found[0][0], [found[0][1]]) if found else (GREY, [_("Suspended")])
    if state == "provisioning":
        if firm.get("job_failed"):
            add(RED, _("Provisioning failed"))
        if found:
            return _result(found)
        return GREY, [_("Provisioning under way")]

    _heartbeat(firm, now, add)
    if firm.get("last_heartbeat_at"):
        _backup(firm, now, add)
        _restore_test(firm, now, add)
        _certificate(firm, now, add)
        _resources(firm, add)
        _update(firm, add)
        _addons(firm, add)
    if not firm.get("backup_key_escrowed") and state == "active":
        add(AMBER, _("Backup key not yet confirmed as stored in the safe"))
    unlogged = (firm.get("ssh_sessions_24h") or 0) - (firm.get("breakglass_24h") or 0)
    if unlogged > 0:
        add(AMBER, _("%(count)s SSH login(s) with no entry in the break-glass log", count=unlogged))
    if firm.get("export_state") == "failed":
        add(RED, _("Data export failed"))
    if firm.get("heartbeat_rejects_24h"):
        add(AMBER, _("%(count)s heartbeat(s) rejected in 24 hours", count=firm["heartbeat_rejects_24h"]))

    if not found:
        return GREEN, [_("All is normal")]
    return _result(found)


def _result(found):
    found.sort(key=lambda item: -_RANK[item[0]])
    return found[0][0], [reason for _colour, reason in found]


def _heartbeat(firm, now, add):
    last = firm.get("last_heartbeat_at")
    if not last:
        add(RED, _("No heartbeat received"))
    elif now - last > HEARTBEAT_RED:
        add(RED, _("No heartbeat for %(age)s", age=_age(now - last)))
    elif now - last > HEARTBEAT_AMBER:
        add(AMBER, _("No heartbeat for %(age)s", age=_age(now - last)))


def _backup(firm, now, add):
    last = firm.get("last_backup_at")
    if not last:
        # A new server has until the first night to make its first backup.
        created = firm.get("activated_at")
        if created and now - created <= BACKUP_AMBER:
            return
        add(RED, _("No backup made"))
    elif firm.get("last_backup_ok") is False:
        add(RED, _("The last backup failed"))
    elif now - last > BACKUP_RED:
        add(RED, _("Backup missed: the last one is %(age)s old", age=_age(now - last)))
    elif now - last > BACKUP_AMBER:
        add(AMBER, _("Backup late: the last one is %(age)s old", age=_age(now - last)))


def _restore_test(firm, now, add):
    last = firm.get("last_restore_test_at")
    if not last:
        created = firm.get("activated_at")
        if created and now - created <= RESTORE_AMBER:
            return
        add(RED, _("No restore test made"))
    elif firm.get("last_restore_test_ok") is False:
        add(RED, _("The last restore test failed"))
    elif now - last > RESTORE_RED:
        add(RED, _("Restore test missed: the last one is %(age)s old", age=_age(now - last)))
    elif now - last > RESTORE_AMBER:
        add(AMBER, _("Restore test late: the last one is %(age)s old", age=_age(now - last)))


def _certificate(firm, now, add):
    expires = firm.get("cert_expires_on")
    if not expires:
        add(AMBER, _("HTTPS certificate missing or unreadable"))
        return
    days = (expires - now.date()).days
    if days < 0:
        add(RED, _("HTTPS certificate expired"))
    elif days < CERT_RED_DAYS:
        add(RED, _("HTTPS certificate: expires in %(days)s day(s)", days=days))
    elif days < CERT_AMBER_DAYS:
        add(AMBER, _("HTTPS certificate: expires in %(days)s day(s)", days=days))


def _resources(firm, add):
    disk = firm.get("disk_used_pct")
    if disk is not None:
        if disk >= DISK_RED_PCT:
            add(RED, _("Disk %(pct)s%% full", pct=disk))
        elif disk >= DISK_AMBER_PCT:
            add(AMBER, _("Disk %(pct)s%% full", pct=disk))
    total, available = firm.get("mem_total_mb"), firm.get("mem_available_mb")
    if total and available is not None:
        free = available * 100 // total
        if free < MEMORY_RED_PCT:
            add(RED, _("Memory: %(pct)s%% available", pct=free))
        elif free < MEMORY_AMBER_PCT:
            add(AMBER, _("Memory: %(pct)s%% available", pct=free))


def _update(firm, add):
    if firm.get("update_state") == "failed":
        add(RED, _("Update failed, rollback not confirmed"))
    elif firm.get("update_state") == "rolled_back":
        add(AMBER, _("Update cancelled by automatic rollback"))


def _addons(firm, add):
    if firm.get("addons_differ"):
        add(AMBER, _("Add-ons: %(count)s not as asked", count=firm["addons_differ"]))
    if firm.get("addons_refused"):
        add(AMBER, _("Add-ons: the firm's server refused %(count)s request(s)", count=firm["addons_refused"]))
    if firm.get("addons_unknown"):
        add(AMBER, _("Add-ons: the firm reports %(count)s code(s) outside the catalogue", count=firm["addons_unknown"]))


def backup_state(last, succeeded, now):
    """none, failed, late, missed or ok, by the same limits as the health reasons."""
    if not last:
        return "none"
    if succeeded is False:
        return "failed"
    if now - last > BACKUP_RED:
        return "missed"
    if now - last > BACKUP_AMBER:
        return "late"
    return "ok"


def _age(delta):
    hours = int(delta.total_seconds() // 3600)
    if hours >= 48:
        return _("%(count)s days", count=hours // 24)
    if hours >= 1:
        return _("%(count)s h", count=hours)
    return _("%(count)s min", count=int(delta.total_seconds() // 60))
