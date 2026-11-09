# En cas d'incident / When something goes wrong

[Français](#français) · [English](#english)

## Français

**Règle : avant toute connexion à un serveur de cabinet, enregistrez un accès d'urgence** sur sa fiche (motif, cabinet informé ou non). Chaque connexion est comptée par le serveur ; une connexion sans entrée fait passer le cabinet à l'orange.

**Point de départ :** Plateforme > À surveiller. Le motif est écrit sur chaque cabinet.

| Ce que dit le tableau | Ce que cela veut dire | Que faire |
|---|---|---|
| **Aucun heartbeat depuis...** | Serveur arrêté, Odoo tombé, ou réseau | Ouvrez l'adresse du cabinet. Regardez le serveur sur Vultr. Puis sur le serveur : `systemctl status odoo nginx postgresql`, `journalctl -u odoo -n 50`. |
| **Sauvegarde manquée / échouée** | Stockage inaccessible, disque plein, script en panne | `journalctl -u firm-backup -n 50`. Après correction, `firm-backup`. |
| **Test de restauration manqué / échoué** | Prenez cela au sérieux : **la sauvegarde peut ne pas servir** | `journalctl -u firm-restore-test -n 50`, puis `firm-restore-test`. |
| **Certificat HTTPS** | Renouvellement bloqué | `certbot renew`, `journalctl -u certbot -n 50`. Vérifiez le DNS. |
| **Disque plein à X %** | | `df -h`, `du -sh /var/lib/odoo /var/lib/postgresql /var/log/*`. Passez à une taille supérieure si cela se répète. |
| **Mémoire : X % disponible** | Serveur trop petit | Passez à une taille supérieure. |
| **Mise à jour annulée** | Retour arrière réussi : le cabinet fonctionne sur l'ancienne version | Voir UPDATING.md. |
| **Mise à jour en échec** | **Retour arrière non confirmé : le cabinet peut être arrêté** | Urgent. `firm-update` a gardé `firm_SLUG_predeploy` et `firm_SLUG_failed_*`. Appelez votre technicien avant de toucher aux bases. |
| **Connexion SSH sans entrée au journal** | Quelqu'un s'est connecté sans le déclarer | Si c'est vous : enregistrez l'accès. **Sinon, traitez cela comme une intrusion :** voir plus bas. |
| **Heartbeat(s) rejeté(s)** | Le serveur a envoyé autre chose que les chiffres autorisés, ou son horloge dérive | Le motif est à l'onglet Sécurité. `unknown_key`, avec un jeton valable, est anormal : voir plus bas. `stale_timestamp` : `timedatectl`. |
| **SERVEUR ORPHELIN** | Un serveur existe sans fiche pour le suivre, et il peut être facturé | Le détail donne son identifiant. **Sur la mise en service :** Relancer le nettoyage. Sinon, vérifiez sur Vultr que ce serveur n'a rien d'utile, puis supprimez-le là-bas. La plateforme ne détruit jamais seule un serveur qu'elle ne reconnaît pas. |

### Mise en service bloquée

Suivi > Mises en service. **Reprendre** relance sans rien recréer. **Annuler et nettoyer** retire tout.

### Le contrôle lui-même est en panne

Les cabinets continuent de fonctionner : ils n'en dépendent pas, sauvegardes comprises. Vous perdez le tableau, les alertes et les mises à jour jusqu'au retour. Rien ne surveille le contrôle : **abonnez-le à un service de surveillance extérieur** (ce point n'est pas construit). Sa base (fiches, journal, jetons de heartbeat) doit être sauvegardée à part. Si elle est perdue, il faudra redonner un jeton à chaque cabinet.

### Intrusion suspectée sur un cabinet

1. **Suspendez le cabinet** (fiche > Suspendre) : le serveur s'arrête, ses disques restent intacts pour l'enquête.
2. Prévenez le cabinet. Ses obligations de notification dépendent de sa juridiction : demandez conseil.
3. Ne restaurez rien avant d'avoir compris. Construisez un serveur neuf plutôt que de réparer l'ancien.
4. Changez la clé SSH, le jeton de heartbeat et la clé de stockage de ce cabinet. Les autres cabinets n'ont pas ces secrets et n'ont rien à changer, sauf si l'attaquant est passé par vous ou par le compte Vultr.

### Intrusion suspectée sur le contrôle ou sur votre poste

Le contrôle ne peut pas lire les données des cabinets ni s'y connecter, mais :

- avec le **jeton Vultr**, on peut détruire ou arrêter tous les serveurs. Révoquez-le chez Vultr immédiatement.
- avec la **clé Wasabi de la console**, on peut supprimer les sauvegardes des cabinets (pas les lire). Supprimez-la chez Wasabi (Users > `auditisa-console` > Access Keys), puis créez-en une nouvelle (WASABI.md, étape 4).
- avec le **jeton DNS**, on peut détourner les adresses. Révoquez-le.
- les **jetons de heartbeat** permettent de se faire passer pour un cabinet : changez-les.
- votre **poste** contient, lui, les clés SSH et la clé de signature : c'est le pire cas. Tout changer, cabinet par cabinet.

## English

**Rule: before any login to a firm's server, record a break-glass access** on its page (reason, whether the firm was told). The server counts each login; one without an entry turns the firm orange.

**Starting point:** Platform > Needs attention. The reason is written on each firm.

| What the board says | What it means | What to do |
|---|---|---|
| **No heartbeat for...** | Server off, Odoo down, or network | Open the firm's address. Look at the server on Vultr. Then on the server: `systemctl status odoo nginx postgresql`, `journalctl -u odoo -n 50`. |
| **Backup missed / failed** | Storage out of reach, disk full, script broken | `journalctl -u firm-backup -n 50`. Once fixed, `firm-backup`. |
| **Restore test missed / failed** | Take it seriously: **the backup may be of no use** | `journalctl -u firm-restore-test -n 50`, then `firm-restore-test`. |
| **HTTPS certificate** | Renewal stuck | `certbot renew`, `journalctl -u certbot -n 50`. Check the DNS. |
| **Disk X% full** | | `df -h`, `du -sh /var/lib/odoo /var/lib/postgresql /var/log/*`. Move to a bigger size if it recurs. |
| **Memory: X% available** | Server too small | Move to a bigger size. |
| **Update cancelled** | Rollback worked: the firm runs on the old release | See UPDATING.md. |
| **Update failed** | **Rollback not confirmed: the firm may be down** | Urgent. `firm-update` kept `firm_SLUG_predeploy` and `firm_SLUG_failed_*`. Call your technician before touching the databases. |
| **SSH login with no entry in the log** | Someone logged in without declaring it | If it was you: record the access. **Otherwise treat it as an intrusion:** see below. |
| **Heartbeat(s) rejected** | The server sent something other than the allowed figures, or its clock drifts | The reason is on the Security tab. `unknown_key` with a valid token is abnormal: see below. `stale_timestamp`: `timedatectl`. |
| **ORPHAN SERVER** | A server exists with no record following it, and may be billed | The detail gives its id. **During provisioning:** Run the clean-up again. Otherwise check on Vultr that the server holds nothing useful, then delete it there. The platform never destroys by itself a server it does not recognise. |

### Provisioning stuck

Tracking > Provisioning runs. **Resume** restarts without recreating anything. **Cancel and clean up** removes it all.

### The control plane itself is down

The firms keep working: they do not depend on it, backups included. You lose the board, alerts and updates until it is back. Nothing watches the control plane: **subscribe it to an outside monitoring service** (that part is not built). Its database (records, log, heartbeat tokens) must be backed up separately. If it is lost, each firm will need a new token.

### Suspected intrusion on a firm

1. **Suspend the firm** (page > Suspend): the server stops and its disks stay intact for the investigation.
2. Tell the firm. Its notification duties depend on its jurisdiction: take advice.
3. Restore nothing before understanding. Build a new server rather than repairing the old one.
4. Change that firm's SSH key, heartbeat token and storage key. The other firms do not have these secrets and need no change, unless the attacker came through you or the Vultr account.

### Suspected intrusion on the control plane or your computer

The control plane can neither read firm data nor log in to a firm, but:

- with the **Vultr token**, anyone can destroy or stop every server. Revoke it at Vultr at once.
- with the **console's Wasabi key**, anyone can delete the firms' backups (not read them). Delete it at Wasabi (Users > `auditisa-console` > Access Keys), then make a new one (WASABI.md, step 4).
- with the **DNS token**, anyone can divert the addresses. Revoke it.
- the **heartbeat tokens** let someone impersonate a firm: change them.
- your **computer**, though, holds the SSH keys and the signing key: that is the worst case. Change everything, firm by firm.
