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

### Dans la salle de contrôle

- **Nouveau cabinet :** le dernier écran a l'interrupteur « Créer aussi son espace d'entraînement », **allumé par défaut**. L'espace a les mêmes modules complémentaires que le cabinet ; quand vous allumez ou éteignez un module sur le cabinet, son espace suit.
- **Plateforme > Espaces d'entraînement :** chaque espace avec son adresse, son état, sa version, sa dernière remise à zéro, ses utilisateurs et son dernier heartbeat.
- **Afficher la première connexion :** l'adresse, l'identifiant et un lien à usage unique (72 heures) avec lequel l'administrateur du cabinet choisit son mot de passe. Il s'affiche **une seule fois**. Perdu ou expiré : « Nouveau lien de première connexion ».
- **Remettre les données de démonstration :** tapez l'identifiant du cabinet et un motif. L'ordinateur d'entraînement le fait à son prochain passage (un quart d'heure environ).
- **Ordre des versions :** Plateforme > Espaces d'entraînement > Ordinateur d'entraînement > **Envoyer une version**. Les cabinets ne se voient proposer une version qu'après **7 jours** sur l'ordinateur d'entraînement (changeable sur la version, 0 pour ne pas attendre : vous seul). Promouvoir et les déploiements refusent avant ce délai. Tant qu'aucun ordinateur d'entraînement n'est enregistré, la règle ne s'applique pas, et l'écran le dit.
- **Enregistrer l'ordinateur d'entraînement, une fois :** sur la salle de contrôle, dans `odoo shell`, `env["platform.practice.computer"]._enrol("practice-1"); env.cr.commit()`. Le jeton va dans `/etc/auditisa-platform/practice-heartbeat.token`, jamais à l'écran : copiez-le dans `/etc/auditisa-practice/secrets/heartbeat.token` (600) sur l'ordinateur d'entraînement, et mettez `PRACTICE_HEARTBEAT_URL=https://<HEARTBEAT_HOST>/platform/practice-heartbeat` dans son `practice.env`.

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
- `practice-space create|reset|delete|addons|first-admin|list`: see the header of `practice-space.sh`. Every command refuses a name that is not `practice_<valid slug>` before it touches anything.
- **Reset keeps the first administrator's login and password** (the root file's, or the one the firm chose through its link), so the firm is not locked out; `--new-password` draws a new one into the root-only file instead. Everything else typed in the space is gone, including passwords given to the demonstration people. Each create or reset draws new `database.secret` and `database.uuid`, so a session from before is worth nothing.
- `practice-update --bundle FILE --digest SHA256`: all spaces to a signed release, all or nothing, then the template again.
- `practice-heartbeat` (timer): figures only (release, template release, guard verdict, and per space: state, last reset, active internal users, day of last login), signed with the practice prefix, sent when `PRACTICE_HEARTBEAT_URL` and `secrets/heartbeat.token` exist.
- `practice_isolation_test.py A B [--preview-url URL]`: proves against the running service that A's login does not open B by any route (host, `?db=`, header, session cookie), that there is no database list or manager, and that the practice role cannot read the other databases.

### In the control room

- **New firm:** the last screen has the switch "Also create its practice space", **on by default**. The space has the firm's optional add-ons; switching one on or off on the firm does the same in its space.
- **Platform > Practice spaces:** each space with its address, state, version, last reset, users, last login and last heartbeat.
- **Show the first login:** the address, the login and a one-time link (72 hours) with which the firm's administrator chooses a password. Shown **once**; only its hash leaves the control room. Lost or expired: "New first-login link".
- **Reset to fresh demo data:** type the firm's slug and a reason. The practice computer does it on its next pass (`practice-apply-desired`, every five minutes after the heartbeat).
- **Release order:** Practice computer > **Send a release**. A firm is offered a release only after it has run on the practice computer for the release's holding period (**7 days**; the owner alone changes it per release, 0 = do not wait). Promote shows it as a pre-check and the rollout refuses to start before it; a rollback to an earlier release does not wait. While no practice computer is registered the rule does not apply, and the release says so.
- **Register the practice computer, once:** on the control room, in `odoo shell`, `env["platform.practice.computer"]._enrol("practice-1"); env.cr.commit()`. The token goes to `/etc/auditisa-platform/practice-heartbeat.token`, never on screen: copy it to the practice computer's `/etc/auditisa-practice/secrets/heartbeat.token` (600) and set `PRACTICE_HEARTBEAT_URL=https://<HEARTBEAT_HOST>/platform/practice-heartbeat` in its `practice.env`. Its heartbeat answer can ask only for a signed release, each firm's space (name, first administrator's login, language, add-ons, a reset number, a link's hash) and removals; `practice-apply-desired` checks every value again and acts only through `practice-space` and `practice-update`.

### Later step: the wildcard certificate

`practice-cert --cloudflare-credentials FILE` gets `*.practice.auditisa.com` by DNS challenge and switches HTTPS on. It needs the DNS record and a Cloudflare token limited to DNS edit on auditisa.com (see the script's header). Until then port 80 serves nothing but a redirect.

### The preview on staging

`deploy/practice/preview-staging.env`: a second Odoo service (`odoo-practice`, port 8099, threaded, 700 MB ceiling) beside staging's, with its own system user and PostgreSQL role, which cannot read staging's databases. No wildcard name exists, so nginx listens on **one extra HTTPS port, 8443**, with test.auditisa.com's certificate. The link `https://test.auditisa.com:8443/practice/<slug>` sets a cookie that chooses the space; nginx turns it into the host name the real computer would receive, so Odoo's configuration is the same as on the real one. Without a chosen space, nginx answers 403. The guard looks only at the `practice_*` and `tpl_practice_*` databases there, since staging's PostgreSQL holds other ones.
