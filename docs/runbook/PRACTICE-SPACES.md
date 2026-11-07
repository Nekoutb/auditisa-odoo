# Espaces d'entraînement des cabinets / Client practice spaces

[Français](#français) · [English](#english)

## Français

### En bref

Un **ordinateur d'entraînement** commun. Chaque cabinet client y a **son propre espace**, séparé des autres : sa propre base Odoo (`practice_<cabinet>`), sa propre adresse (`<cabinet>.practice.auditisa.com`) et ses propres identifiants. Un cabinet ne voit jamais l'espace d'un autre. Chaque espace est rempli de **données fictives** (le « Cabinet Démo », ses cinq collaborateurs, ses clients et ses dossiers) et a les mêmes modules complémentaires que le vrai système du cabinet.

Les nouvelles versions arrivent **d'abord** sur l'ordinateur d'entraînement : le cabinet peut les essayer (7 jours par défaut) avant que son vrai serveur soit mis à jour.

**Jamais de vraies données clients ici**, même anonymisées. Aucun script ne charge une sauvegarde ; le gestionnaire de bases d'Odoo est coupé ; un gardien (`practice-guard`) refuse de servir toute base qui n'est pas une copie du modèle de démonstration, et arrête le service s'il en trouve une.

Votre salle de répétition (test.auditisa.com) reste privée : elle n'est pas un espace d'entraînement.

### Ce qu'il faut de vous (plus tard)

1. **Un ordinateur** pour l'entraînement (même taille qu'un petit cabinet suffit pour une dizaine d'espaces).
2. **Une entrée DNS** : `*.practice.auditisa.com` vers cet ordinateur.
3. **Un jeton Cloudflare** limité à « DNS : modifier » sur auditisa.com, pour le certificat qui couvre toutes les adresses (`practice-cert`). Sans lui, l'ordinateur ne sert aucun espace.

### Les gestes

| Geste | Commande (en root, sur l'ordinateur d'entraînement) |
|---|---|
| Préparer le modèle de démonstration | `practice-template build` |
| Créer l'espace d'un cabinet | `practice-space create --slug cabinet-x --name "Cabinet X" --admin-login admin@cabinet-x.cm [--addons a,b]` |
| Remettre les données de démonstration | `practice-space reset --slug cabinet-x` (même identifiant et même mot de passe) ; `--new-password` pour en tirer un nouveau |
| Changer les modules d'un espace | `practice-space addons --slug cabinet-x --set a,b` |
| Supprimer un espace | `practice-space delete --slug cabinet-x --yes` |
| Voir les espaces | `practice-space list` |
| Mettre une nouvelle version | `practice-update --bundle <sha>.tar.gz --digest <sha256>` (paquet signé, comme pour les cabinets) |

Le **premier administrateur** de chaque espace : son identifiant, son mot de passe et l'adresse sont dans `/etc/auditisa-practice/secrets/logins/<cabinet>` (root seulement). Le mot de passe n'est jamais affiché ni écrit dans un journal.

Après une **remise à zéro**, tout ce que le cabinet a saisi disparaît, y compris les mots de passe donnés aux collaborateurs de démonstration ; le premier administrateur garde son accès.

### Si le gardien trouve une base

Le service s'arrête et la base est fermée aux connexions. Regardez ce que c'est (`/var/log/auditisa-practice/actions.log`), supprimez-la à la main (`DROP DATABASE`), puis `systemctl start odoo-practice`.

## English

### In short

One shared **practice computer**. Each client firm has **its own space** on it, separate from the others: its own Odoo database (`practice_<firm>`), its own address (`<firm>.practice.auditisa.com`) and its own logins. Odoo picks the database from the first part of the host name (`dbfilter = ^practice_%d$`); there is no database list and no database manager. Every space is a copy of the **demo template**: made-up data only (the "Cabinet Démo" firm, its five people, clients and files from `ea_audit_ui/demo`, without Odoo's own demo records), every password cleared, mail off. A space has the same optional add-ons as the firm's real system.

New releases reach the practice computer **first**; a firm's real server is offered a release only after a holding period (7 days by default, set per release in the control room).

**Real client data never goes on the practice computer**, not even anonymised copies:

- no practice script restores, loads or copies a database from a file (a test checks it);
- the database manager is off three ways: `list_db = False`, a random master password in a root-only file, and nginx answers 404 on `/web/database`;
- `practice-guard` runs before every start of the service and every ten minutes. Every `practice_*` database must be registered by `practice-space`, carry its slug and the id of this computer's template build, and none of a firm's or an anonymised copy's marks. On the real computer, any other database of the cluster is a finding too. A finding closes that database to connections, stops the service, and the service will not start until the operator has dropped it.

### Layout

| Path | What |
|---|---|
| `/etc/auditisa-practice/practice.env` | who this computer is (no secret) |
| `/etc/auditisa-practice/secrets/` | root 700: `master.password`, `db.password`, `heartbeat.token`, `logins/<slug>` (600) |
| `/var/lib/auditisa-practice/spaces/<slug>.env` | a space: name, first administrator's login, add-ons, created, last reset, template id |
| `/var/lib/auditisa-practice/template.env` | the template's id, release and build date |
| `/var/lib/auditisa-practice/status/` | release, guard verdict, `heartbeat.json` |
| `/opt/auditisa-practice/releases/<sha>`, `current` | the code |
| `/etc/odoo/practice.conf`, `odoo-practice.service` | one Odoo service, its own system user `odoo-practice` and PostgreSQL role `odoo_practice` (NOCREATEDB) |
| `/var/log/auditisa-practice/actions.log` | what the scripts did |

### Commands (root)

- `install-practice-server --env FILE --release DIR [--preview]`: sets the computer up (`deploy/practice/sample.env`). Outgoing traffic is denied except DNS, NTP, 80 and 443; mail ports 25, 465, 587, 2525 are rejected by name.
- `practice-template build`: the demo template on the current release.
- `practice-space create|reset|delete|addons|list`: see the header of `practice-space.sh`. Every command refuses a name that is not `practice_<valid slug>` before it touches anything.
- **Reset keeps the first administrator's login and password**, so the firm is not locked out; `--new-password` draws a new one into the same root-only file. Everything else typed in the space is gone, including passwords given to the demonstration people. Each create or reset draws new `database.secret` and `database.uuid`, so a session from before is worth nothing.
- `practice-update --bundle FILE --digest SHA256`: all spaces to a signed release, all or nothing, then the template again.
- `practice-heartbeat` (timer): figures only (release, template release, guard verdict, and per space: state, last reset, active internal users, day of last login), signed with the practice prefix, sent when `PRACTICE_HEARTBEAT_URL` and `secrets/heartbeat.token` exist.
- `practice_isolation_test.py A B [--preview-url URL]`: proves against the running service that A's login does not open B by any route (host, `?db=`, header, session cookie), that there is no database list or manager, and that the practice role cannot read the other databases.

### Later step: the wildcard certificate

`practice-cert --cloudflare-credentials FILE` gets `*.practice.auditisa.com` by DNS challenge and switches HTTPS on. It needs the DNS record and a Cloudflare token limited to DNS edit on auditisa.com (see the script's header). Until then port 80 serves nothing but a redirect.

### The preview on staging

`deploy/practice/preview-staging.env`: a second Odoo service (`odoo-practice`, port 8099, threaded, 700 MB ceiling) beside staging's, with its own system user and PostgreSQL role, which cannot read staging's databases. No wildcard name exists, so nginx listens on **one extra HTTPS port, 8443**, with test.auditisa.com's certificate. The link `https://test.auditisa.com:8443/practice/<slug>` sets a cookie that chooses the space; nginx turns it into the host name the real computer would receive, so Odoo's configuration is the same as on the real one. Without a chosen space, nginx answers 403. The guard looks only at the `practice_*` and `tpl_practice_*` databases there, since staging's PostgreSQL holds other ones.
