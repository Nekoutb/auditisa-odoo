# Mettre à jour les cabinets / Updating the firms

[Français](#français) · [English](#english)

## Français

Depuis le 10 novembre 2026 (décision du propriétaire), une nouvelle version se met en ligne en **trois étapes**, sans clé ni signature. La sécurité, c'est l'accès à la console : seul le propriétaire, connecté (mot de passe et code à deux facteurs), voit et utilise les deux boutons **Promouvoir**.

| Étape | Qui | Où | Ce qui se passe |
|---|---|---|---|
| 1. Nouvelle version prête | le développeur | son ordinateur, puis la console | la version est construite, déposée et enregistrée. La page **Statut** affiche « Nouvelle version prête » |
| 2. **Promouvoir vers le staging** | le propriétaire | console > Statut | la version part vers les espaces d'entraînement (sur le serveur de staging, test.auditisa.com:8443). Une fenêtre explique, vous cliquez **Oui** |
| 3. **Promouvoir vers la production** | le propriétaire | console > Statut | la version qui tourne sur le staging part vers les cabinets clients. Une fenêtre explique, vous cliquez **Oui** |

Rien à taper, aucun délai d'attente. La production n'accepte **que** la version qui tourne sur le staging à ce moment-là : le bouton le vérifie et le dit en clair sinon.

« Staging » désigne ici les **espaces d'entraînement** des clients, qui tournent sur le serveur de staging. La page Statut les liste sous « Entraînement ».

### 1. Le développeur prépare la version

Sur son ordinateur, dans le dossier `auditisa-odoo` :

```
git fetch && git checkout <commit à publier>
bash scripts/provision/build_release.sh <commit> --since <version en service> --out release-<commit>/
```

Le script écrit trois fichiers : `<commit>.tar.gz` (le paquet), `<commit>.catalogue.json` (ce qu'il contient) et `<commit>.changes.txt` (la liste des changements). Il affiche le commit et l'empreinte `sha256` du paquet. Le paquet ne contient jamais `ea_platform_*`.

Puis, sur la console, en root : le dossier de la version et les outils (`deploy/control-plane/release-tools/`) sont copiés sur la console, et

```
bash release-tools/publish-release.sh release-<commit>/ "étiquette courte"
```

`publish-release.sh` dépose le paquet et le catalogue dans le bucket privé des versions (avec la clé Wasabi de la console), puis enregistre la version sur la console avec son empreinte et charge son catalogue. `DRY_RUN=1 bash release-tools/register-release.sh ...` répète l'enregistrement sans rien garder.

### 2. Promouvoir vers le staging

Console > **Statut**. En haut, le panneau **Versions** dit où en est chaque version, sur trois lignes : Nouvelle version, Staging, Production. Sur la ligne Nouvelle version, cliquez **Promouvoir vers le staging**. La fenêtre montre la version, ce qui va se passer et la liste des changements. Cliquez **Oui, promouvoir vers le staging**. Le staging démarre en une minute environ, puis la ligne Staging montre une barre de progression, étape par étape (environ deux minutes par espace d'entraînement, puis quelques-unes pour le modèle de démonstration). Si l'installation échoue, la ligne passe au rouge avec la raison : tout est remis en l'état, et il faut prévenir le développeur (le staging ne réessaie pas cette version : sur le serveur, elle est notée dans `/var/lib/auditisa-practice/refused-releases`).

L'ordinateur d'entraînement la prend dans les minutes qui suivent : il copie chaque espace, installe la version, vérifie que chaque espace répond, et **remet tout comme avant** si un point échoue. La ligne passe à « Sur le staging : <commit> ». Regardez la version dans un espace d'entraînement (bouton **Se connecter**).

### 3. Promouvoir vers la production

Quand la version tourne sur le staging et vous convient : **Promouvoir vers la production**, puis **Oui, promouvoir vers la production**. La fenêtre refuse en clair si ce n'est pas possible (la version n'est pas sur le staging, aucun cabinet, une mise à jour déjà en cours, tous les cabinets l'ont déjà).

Un cabinet passe d'abord, seul, puis les autres par petits lots. L'écran de la promotion montre le résultat cabinet par cabinet, et l'onglet **Historique** de la page Statut le garde.

### Ce qui se passe sur chaque cabinet (automatique)

Au prochain heartbeat (15 minutes au plus), puis dans les 5 minutes, sur le serveur :

1. Téléchargement du paquet. **Refus si son empreinte SHA-256 n'est pas celle que la console a donnée.** La console envoie cette empreinte dans sa réponse au heartbeat, en HTTPS, authentifiée par le jeton propre au cabinet : ni le bucket ni l'adresse de téléchargement ne peuvent faire passer un autre fichier.
2. Sauvegarde chiffrée. **Pas de sauvegarde, pas de mise à jour.**
3. Arrêt d'Odoo, copie de la base, passage à la nouvelle version, mise à jour des modules, redémarrage.
4. Contrôle de santé.
5. **Si un point échoue : retour automatique** à la version et à la base d'avant. La base en échec est conservée pour analyse.

Le cabinet est coupé pendant l'étape 3, de quelques minutes à une demi-heure.

Pour être réussie, une ligne exige : la nouvelle version en service, le serveur qui confirme, une sauvegarde postérieure à la demande, et un cabinet qui n'est pas rouge. Sont écartés, avec le motif affiché : les cabinets non actifs, rouges, verrouillés, sans sauvegarde valable, ou déjà sur cette version. Une seule mise à jour à la fois.

### Si cela s'arrête

La mise à jour s'arrête et une alerte part. Le cabinet en échec est de nouveau sur son ancienne version, et les suivants n'ont rien reçu. Le développeur cherche la cause (`/var/log/odoo/update-*.log` sur le serveur, après un accès d'urgence). Un serveur ne retente pas une version refusée : corriger et publier une **nouvelle** version. Si l'état est « Échec » et non « Retour arrière », voir INCIDENT.md.

### Exclure un cabinet

Cochez « Version verrouillée » sur sa fiche.

### Ce qui a disparu le 10 novembre 2026

Les signataires et leurs clés, l'outil de bureau « Sign new version », l'écran « En attente de signature », la liste `deploy/trust/signers.json`, l'attente de 7 jours sur l'entraînement et sa levée par `SANS-ATTENTE <commit>`. Les fichiers `.sig` et `.attestation` ne sont plus ni faits ni lus.

## English

Since 10 November 2026 (the owner's decision), a new version goes live in **three steps**, with no key and no signature. The security is access to the console: only the owner, signed in (password and two-factor code), sees and uses the two **Promote** buttons.

| Step | Who | Where | What happens |
|---|---|---|---|
| 1. New version ready | the developer | their computer, then the console | the version is built, uploaded and registered. The **Status** page shows "New version ready" |
| 2. **Promote to Staging** | the owner | console > Status | the version goes to the practice spaces (on the staging server, test.auditisa.com:8443). A window explains, you click **Yes** |
| 3. **Promote to Production** | the owner | console > Status | the version that runs on Staging goes to the client firms. A window explains, you click **Yes** |

Nothing to type, no waiting period. Production takes **only** the version that runs on Staging at that moment: the button checks it and says so in plain words otherwise.

"Staging" here means the clients' **practice spaces**, which run on the staging server. The Status page lists them under "Practice".

### 1. The developer prepares the version

On their computer, in the `auditisa-odoo` folder:

```
git fetch && git checkout <commit to publish>
bash scripts/provision/build_release.sh <commit> --since <release in service> --out release-<commit>/
```

The script writes three files: `<commit>.tar.gz` (the bundle), `<commit>.catalogue.json` (what it holds) and `<commit>.changes.txt` (the list of changes). It prints the commit and the bundle's `sha256`. The bundle never holds `ea_platform_*`.

Then, on the console, as root: the release folder and the tools (`deploy/control-plane/release-tools/`) are copied to the console, and

```
bash release-tools/publish-release.sh release-<commit>/ "short label"
```

`publish-release.sh` puts the bundle and the catalogue in the private releases bucket (with the console's Wasabi key), then registers the release on the console with its fingerprint and loads its catalogue. `DRY_RUN=1 bash release-tools/register-release.sh ...` rehearses the registration and keeps nothing.

### 2. Promote to Staging

Console > **Status**. At the top, the **Versions** panel says where each version is, on three rows: New version, Staging, Production. On the New version row, click **Promote to Staging**. The window shows the version, what will happen and the list of changes. Click **Yes, promote to Staging**. Staging starts within about a minute, then the Staging row shows a progress bar, step by step (about two minutes per practice space, then a few for the demo template). If the installation fails, the row turns red with the reason: everything is put back as it was, and the developer must be told (Staging does not try that version again: on the server it is noted in `/var/lib/auditisa-practice/refused-releases`).

The practice computer takes it within minutes: it copies each space, installs the version, checks that each space answers, and **puts everything back as it was** if anything fails. The line then reads "On Staging: <commit>". Look at the version in a practice space (the **Connect** button).

### 3. Promote to Production

When the version runs on Staging and you are happy with it: **Promote to Production**, then **Yes, promote to Production**. The window refuses in plain words when it cannot go (the version is not on Staging, no firm, an update already running, every firm already has it).

One firm goes first, alone, then the others in small batches. The promotion's screen shows the result firm by firm, and the Status page's **History** tab keeps it.

### What happens on each firm (automatic)

At the next heartbeat (15 minutes at most), then within 5 minutes, on the server:

1. Downloads the bundle. **Refused if its SHA-256 is not the one the console gave.** The console sends that fingerprint in its heartbeat answer, over HTTPS, authenticated with the firm's own token: neither the bucket nor the download address can slip another file in.
2. Encrypted backup. **No backup, no update.**
3. Stops Odoo, copies the database, switches to the new release, updates the modules, restarts.
4. Health check.
5. **If anything fails: automatic return** to the previous release and database. The failed database is kept for analysis.

The firm is offline during step 3, from a few minutes to half an hour.

A line succeeds only with: the new release running, the server confirming, a backup later than the request, and a firm that is not red. Set aside, with the reason shown: firms that are not active, are red, are locked, have no good backup, or already run this release. One update at a time.

### If it stops

The rollout stops and an alert goes out. The failed firm is back on its old release and the following ones received nothing. The developer finds the cause (`/var/log/odoo/update-*.log` on the server, after a break-glass entry). A server does not retry a refused release: fix it and publish a **new** release. If the state is "Failed" rather than "Rolled back", see INCIDENT.md.

### Keeping a firm out

Tick "Release locked" on its page.

### What went away on 10 November 2026

The signers and their keys, the "Sign new version" desktop tool, the "Waiting for signature" screen, the `deploy/trust/signers.json` list, the 7-day wait on practice and its `NO-WAIT <commit>` override. `.sig` and `.attestation` files are no longer made nor read.
