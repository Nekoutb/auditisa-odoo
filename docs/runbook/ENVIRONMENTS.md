# Les environnements / The environments

[Français](#français) · [English](#english)

## Français

La page **Statut** de la console (https://console.auditisa.com/odoo/status) montre les quatre environnements de l'outil Odoo, comme la page des branches d'Odoo.sh : à gauche la liste, à droite l'environnement choisi.

| Environnement | Ce que c'est | Se connecter |
|---|---|---|
| **Production** | le serveur propre à chaque cabinet client | lance une **visite de support en lecture seule** (raison, durée, journalisée, vue par le cabinet). Jamais une connexion libre |
| **Entraînement** | les espaces d'entraînement des clients (sur le staging, port 8443 pour l'instant) | demande quel espace, puis l'ouvre dans un nouvel onglet |
| **Staging** | test.auditisa.com, données de test, aucun e-mail | ouvre le site dans un nouvel onglet |
| **Développement** | la branche `dev`, pas de serveur | rien |

En haut : le nom, un point vert / orange / rouge / gris, **Promouvoir staging → production** (propriétaire seul) et **Se connecter**. Puis une ligne : version d'Odoo, modules et leurs versions, taille de la base, révision (lien GitHub), en service depuis, tests sur ce commit. Onglets : **Historique** (déploiements, commits de la branche), **Sauvegardes**, **Surveillance**, **Journaux** (le journal de la plateforme filtré), **Personnes**. L'ancien tableau reste dans Pipeline > Les deux outils côte à côte (`/odoo/status-board`).

### Promouvoir

Deux étapes séparées, chacune avec son écran et son mot à taper :

1. **Staging → Entraînement** : une version **signée sur votre ordinateur** et enregistrée dans Mises à jour > Versions. Si la version du staging n'est pas signée, l'écran le dit et montre les deux commandes de `build_release.sh` (`--unsigned` puis `--sign`). La console ne signe jamais. Écran : de → à, espaces, changements, `ENTRAINEMENT <commit>` et une raison.
2. **Entraînement → Production** : la promotion existante (vérifications, cabinet témoin, lots). La version doit avoir tourné **7 jours** en entraînement ; sinon le bouton **Lever les 7 jours en entraînement...** demande `SANS-ATTENTE <commit>` et une raison écrite, gardée au journal. L'écran de confirmation montre de → à, les cabinets, les changements et la règle de sauvegarde : chaque serveur se sauvegarde juste avant la mise à jour, et sans cette sauvegarde la mise à jour compte comme échouée. Le résultat s'affiche cabinet par cabinet.

### Personnes et comptes de test

- **Staging et entraînement :** nom, e-mail, rôle, dernière connexion, « en ligne maintenant » (actif dans les 3 dernières minutes).
- **Production :** des **nombres** seulement (comptes par cabinet). Les noms ne quittent jamais le serveur d'un cabinet. « En ligne maintenant » n'est pas encore envoyé par les cabinets.
- **Créer un compte de test** (propriétaire et opérateurs) : nom, e-mail, rôle ; sur le staging ou dans un espace d'entraînement choisi. Le mot de passe est montré **une fois**, avec un bouton copier. Aucun e-mail. **Désactiver** et **Nouveau mot de passe** sur chaque ligne. Les administrateurs et le premier administrateur d'un espace sont protégés. Jamais chez un cabinet client. Tout va au journal de la plateforme.

### Comment la console lit le staging (à installer une fois)

La console Odoo ne garde aucune clé et n'ouvre aucune connexion. Un service root à côté, `env-sync`, le fait :

```
console (root)  env-sync  --ssh, clé restreinte-->  staging (root)  auditisa-env-agent
                  |  écrit /var/lib/auditisa-platform/env-state.json  (lu par Odoo)
                  |  lit   /var/lib/auditisa-platform/env-requests/   (déposé par Odoo : une demande, un hash de mot de passe)
```

1. Sur la **console**, en root : `python3 deploy/control-plane/env-sync.py --new-key` fabrique `/root/.ssh/auditisa_env_agent` et affiche sa clé **publique**.
2. Copiez cette clé publique sur le **staging** dans un fichier, puis en root : `python3 deploy/staging/auditisa-env-agent.py --install-key <fichier>`. La ligne ajoutée à `/root/.ssh/authorized_keys` commence par `restrict,command="/usr/local/sbin/auditisa-env-agent"` : cette clé ne peut lancer que ce programme, sans terminal ni redirection.
3. Sur la **console** : `python3 deploy/control-plane/env-sync.py --print` (lit une fois, ne change rien), puis `--install` (minuterie chaque minute, et déclenchement immédiat quand une demande arrive).

Retirer : `env-sync.py --uninstall` sur la console, `auditisa-env-agent --uninstall` sur le staging.

**Ce que l'agent peut faire :** `state` (lecture des chiffres et des comptes) et `account` (créer, désactiver, nouveau mot de passe) sur la base du staging et les bases `practice_<espace>` enregistrées, rien d'autre. Il reçoit un **hash** de mot de passe, jamais le mot de passe. Les comptes sont créés sans invitation : aucun e-mail. Le courrier sortant du staging est de toute façon fermé (`smtp_server = False`, aucun serveur de messagerie, ports 25/465/587 bloqués).

**Les commits avec leur message** viennent du collecteur (`pipeline-collect.py`), qui garde maintenant la ligne de titre des 20 derniers commits de chaque branche. Sans la clé GitHub en lecture seule (PIPELINE.md, section 2), l'onglet Historique le dit et donne les deux commandes.

## English

The console's **Status** page (https://console.auditisa.com/odoo/status) shows the Odoo tool's four environments, like Odoo.sh's branches page: the list on the left, the chosen environment on the right.

| Environment | What it is | Connect |
|---|---|---|
| **Production** | each client firm's own server | starts a **read-only support visit** (reason, length, logged, shown to the firm). Never a free sign-in |
| **Practice** | the clients' practice spaces (on staging, port 8443 for now) | asks which space, then opens it in a new tab |
| **Staging** | test.auditisa.com, test data, no email | opens the site in a new tab |
| **Development** | the `dev` branch, no server | nothing |

At the top: the name, a green / amber / red / grey dot, **Promote staging → production** (owner only) and **Connect**. Then one line: Odoo version, add-ons and their versions, database size, revision (GitHub link), up since, tests on this commit. Tabs: **History** (deploys, commits on the branch), **Backups**, **Monitor**, **Logs** (the platform log, filtered), **People**. The previous board stays in Pipeline > Both tools side by side (`/odoo/status-board`).

### Promote

Two separate steps, each with its own screen and its own word to type:

1. **Staging → Practice**: a release **signed on your computer** and registered in Updates > Releases. If staging's version is not signed, the screen says so and shows the two `build_release.sh` commands (`--unsigned`, then `--sign`). The console never signs. Screen: from → to, spaces, changes, `PRACTICE <commit>` and a reason.
2. **Practice → Production**: the existing promotion (pre-checks, test firm, batches). The release must have run **7 days** on practice; otherwise the **Skip the 7 days on practice...** button asks for `NO-WAIT <commit>` and a written reason, kept in the log. The confirmation screen shows from → to, the firms, the changes and the backup rule: each server backs itself up just before it updates, and without that backup the update counts as failed. The result shows firm by firm.

### People and test accounts

- **Staging and Practice:** name, email, role, last login, "online now" (active in the last 3 minutes).
- **Production:** **counts** only (accounts per firm). Names never leave a firm's server. "Online now" is not sent by the firms yet.
- **Create a test account** (owner and operators): name, email, role; on staging or in a chosen practice space. The password is shown **once**, with a copy button. No email. **Disable** and **New password** on each line. Administrators and a space's first administrator are protected. Never on a client firm. Everything goes to the platform log.

### How the console reads staging (to install once)

The console's Odoo keeps no key and opens no connection. A root service beside it, `env-sync`, does:

```
console (root)  env-sync  --ssh, restricted key-->  staging (root)  auditisa-env-agent
                  |  writes /var/lib/auditisa-platform/env-state.json  (read by Odoo)
                  |  reads  /var/lib/auditisa-platform/env-requests/   (dropped by Odoo: one request, a password hash)
```

1. On the **console**, as root: `python3 deploy/control-plane/env-sync.py --new-key` makes `/root/.ssh/auditisa_env_agent` and prints its **public** key.
2. Copy that public key to **staging** into a file, then as root: `python3 deploy/staging/auditisa-env-agent.py --install-key <file>`. The line added to `/root/.ssh/authorized_keys` starts with `restrict,command="/usr/local/sbin/auditisa-env-agent"`: that key can run this program only, with no terminal and no forwarding.
3. On the **console**: `python3 deploy/control-plane/env-sync.py --print` (reads once, changes nothing), then `--install` (a timer each minute, and at once when a request arrives).

To remove: `env-sync.py --uninstall` on the console, `auditisa-env-agent --uninstall` on staging.

**What the agent can do:** `state` (read figures and accounts) and `account` (create, disable, new password) on staging's database and the registered `practice_<space>` databases, nothing else. It receives a password **hash**, never the password. Accounts are created with no invitation: no email. Staging's outgoing mail is closed anyway (`smtp_server = False`, no mail server, ports 25/465/587 blocked).

**Commits with their message** come from the collector (`pipeline-collect.py`), which now keeps the subject line of the last 20 commits of each branch. Without the GitHub read-only key (PIPELINE.md, section 2), the History tab says so and gives the two commands.
