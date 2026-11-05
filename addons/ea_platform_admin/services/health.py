"""The colour of a firm on the board, and why. Pure."""

from datetime import timedelta

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
        add(RED, "SERVEUR ORPHELIN : " + (firm.get("orphan_detail") or "à vérifier chez le fournisseur"))
    if state == "archived":
        return (found[0][0], [found[0][1]]) if found else (GREY, ["Archivé"])
    if state == "suspended":
        return (found[0][0], [found[0][1]]) if found else (GREY, ["Suspendu"])
    if state == "provisioning":
        if firm.get("job_failed"):
            add(RED, "Mise en service en échec")
        if found:
            return _result(found)
        return GREY, ["Mise en service en cours"]

    _heartbeat(firm, now, add)
    if firm.get("last_heartbeat_at"):
        _backup(firm, now, add)
        _restore_test(firm, now, add)
        _certificate(firm, now, add)
        _resources(firm, add)
        _update(firm, add)
    if not firm.get("backup_key_escrowed") and state == "active":
        add(AMBER, "Clé de sauvegarde pas encore confirmée au coffre")
    unlogged = (firm.get("ssh_sessions_24h") or 0) - (firm.get("breakglass_24h") or 0)
    if unlogged > 0:
        add(AMBER, f"{unlogged} connexion(s) SSH sans entrée au journal d'accès d'urgence")
    if firm.get("export_state") == "failed":
        add(RED, "Export des données en échec")
    if firm.get("heartbeat_rejects_24h"):
        add(AMBER, f"{firm['heartbeat_rejects_24h']} heartbeat(s) rejeté(s) en 24 h")

    if not found:
        return GREEN, ["Tout est normal"]
    return _result(found)


def _result(found):
    found.sort(key=lambda item: -_RANK[item[0]])
    return found[0][0], [reason for _colour, reason in found]


def _heartbeat(firm, now, add):
    last = firm.get("last_heartbeat_at")
    if not last:
        add(RED, "Aucun heartbeat reçu")
    elif now - last > HEARTBEAT_RED:
        add(RED, f"Aucun heartbeat depuis {_age(now - last)}")
    elif now - last > HEARTBEAT_AMBER:
        add(AMBER, f"Aucun heartbeat depuis {_age(now - last)}")


def _backup(firm, now, add):
    last = firm.get("last_backup_at")
    if not last:
        # A new server has until the first night to make its first backup.
        created = firm.get("activated_at")
        if created and now - created <= BACKUP_AMBER:
            return
        add(RED, "Aucune sauvegarde réalisée")
    elif firm.get("last_backup_ok") is False:
        add(RED, "La dernière sauvegarde a échoué")
    elif now - last > BACKUP_RED:
        add(RED, f"Sauvegarde manquée : la dernière date de {_age(now - last)}")
    elif now - last > BACKUP_AMBER:
        add(AMBER, f"Sauvegarde en retard : la dernière date de {_age(now - last)}")


def _restore_test(firm, now, add):
    last = firm.get("last_restore_test_at")
    if not last:
        created = firm.get("activated_at")
        if created and now - created <= RESTORE_AMBER:
            return
        add(RED, "Aucun test de restauration réalisé")
    elif firm.get("last_restore_test_ok") is False:
        add(RED, "Le dernier test de restauration a échoué")
    elif now - last > RESTORE_RED:
        add(RED, f"Test de restauration manqué : le dernier date de {_age(now - last)}")
    elif now - last > RESTORE_AMBER:
        add(AMBER, f"Test de restauration en retard : le dernier date de {_age(now - last)}")


def _certificate(firm, now, add):
    expires = firm.get("cert_expires_on")
    if not expires:
        add(AMBER, "Certificat HTTPS absent ou illisible")
        return
    days = (expires - now.date()).days
    if days < 0:
        add(RED, "Certificat HTTPS expiré")
    elif days < CERT_RED_DAYS:
        add(RED, f"Certificat HTTPS : expire dans {days} jour(s)")
    elif days < CERT_AMBER_DAYS:
        add(AMBER, f"Certificat HTTPS : expire dans {days} jours")


def _resources(firm, add):
    disk = firm.get("disk_used_pct")
    if disk is not None:
        if disk >= DISK_RED_PCT:
            add(RED, f"Disque plein à {disk} %")
        elif disk >= DISK_AMBER_PCT:
            add(AMBER, f"Disque plein à {disk} %")
    total, available = firm.get("mem_total_mb"), firm.get("mem_available_mb")
    if total and available is not None:
        free = available * 100 // total
        if free < MEMORY_RED_PCT:
            add(RED, f"Mémoire : {free} % disponible")
        elif free < MEMORY_AMBER_PCT:
            add(AMBER, f"Mémoire : {free} % disponible")


def _update(firm, add):
    if firm.get("update_state") == "failed":
        add(RED, "Mise à jour en échec, retour arrière non confirmé")
    elif firm.get("update_state") == "rolled_back":
        add(AMBER, "Mise à jour annulée par retour arrière automatique")


def _age(delta):
    hours = int(delta.total_seconds() // 3600)
    if hours >= 48:
        return f"{hours // 24} jours"
    if hours >= 1:
        return f"{hours} h"
    return f"{int(delta.total_seconds() // 60)} min"
