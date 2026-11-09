# Mettre à jour les cabinets / Updating the firms

[Français](#français) · [English](#english)

## Français

**Le passage par étapes, du staging aux cabinets, se fait depuis l'écran Pipeline : voir PIPELINE.md. Cette page reste valable pour le déploiement lui-même.**

Chaque cabinet a sa version, inscrite sur sa fiche. Une mise à jour part d'abord vers **un cabinet témoin**, puis par lots, et s'arrête au premier échec. Le contrôle ne se connecte jamais aux cabinets : il nomme la version dans la réponse au heartbeat, et chaque serveur fait le reste lui-même.

**Ce mécanisme n'a tourné qu'en simulation côté cabinet.** `firm-update.sh` n'a jamais mis à jour un vrai serveur : essayez-le d'abord sur un cabinet fictif.

### 1. Construire et signer la version (sur votre ordinateur)

```
git fetch && git checkout <commit à publier>
scripts/provision/build_release.sh <commit> --key signature.pem --out sortie/
```

Ou en deux temps : `build_release.sh <commit> --unsigned --out sortie/` (sans la clé), puis `build_release.sh --sign sortie/<commit>.tar.gz --key signature.pem --pub signature.pub`, qui demande la phrase de passe une seule fois et signe le paquet, le catalogue et l'attestation (`<commit>.attestation`, pour l'écran Pipeline).

La commande affiche le commit et l'empreinte `sha256`. Déposez les deux fichiers (`<commit>.tar.gz` et `<commit>.tar.gz.sig`) dans le bucket des versions : console.wasabisys.com > Buckets > `auditisa-releases-...` > **Upload**, sans les renommer et sans dossier. Le bucket reste privé : chaque serveur reçoit de la console une adresse de téléchargement signée, valable 6 heures et renouvelée à chaque heartbeat. Le paquet ne contient jamais `ea_platform_admin`.

### 2. L'enregistrer

Plateforme > Mises à jour > Versions > Nouveau : collez le commit et l'empreinte. Puis **Charger le fichier du catalogue** : `<commit>.catalogue.json` et sa signature, écrits à côté du paquet. Sans cela, l'écran « Modules » n'a rien à proposer pour cette version et aucune demande de module ne part (CLIENT-ADDONS.md).

### 3. Lancer

Mises à jour > Déploiements > Nouveau : la version, le **cabinet témoin** (un cabinet qui accepte d'être le premier), les cabinets concernés, la taille des lots. **Lancer : le témoin d'abord.**

Sont écartés, avec le motif affiché : les cabinets non actifs, rouges, verrouillés, sans sauvegarde valable, ou déjà sur cette version. Une seule mise à jour à la fois.

### 4. Ce qui se passe sur chaque cabinet

Au prochain heartbeat (15 minutes au plus), puis dans les 5 minutes, sur le serveur :

1. Téléchargement du paquet. **Refus si l'empreinte ou la signature ne correspond pas.**
2. Sauvegarde chiffrée. **Pas de sauvegarde, pas de mise à jour.**
3. Arrêt d'Odoo, copie de la base, passage à la nouvelle version, mise à jour des modules, redémarrage.
4. Contrôle de santé.
5. **Si un point échoue : retour automatique** à la version et à la base d'avant. La base en échec est conservée pour analyse.

Le cabinet est coupé pendant l'étape 3, de quelques minutes à une demi-heure. Prévenez-le.

### 5. Suivre

La fiche du déploiement montre chaque cabinet : En attente, Demandée, Réussie, Échec, Retour arrière, Sans réponse (90 minutes), Annulée.

Pour être réussie, une ligne exige : la nouvelle version en service, le serveur qui confirme, une sauvegarde postérieure à la demande, et un cabinet qui n'est pas rouge.

### Si cela s'arrête

La mise à jour s'arrête et une alerte part. Le cabinet en échec est de nouveau sur son ancienne version, et les suivants n'ont rien reçu. Cherchez la cause avant de relancer (`/var/log/odoo/update-*.log` sur le serveur, après un accès d'urgence). Une version refusée n'est pas retentée par ce serveur : corrigez et publiez une **nouvelle** version. Si l'état est « Échec » et non « Retour arrière », voir INCIDENT.md.

### Exclure un cabinet

Cochez « Version verrouillée » sur sa fiche.

## English

**The staged path, from staging to the firms, runs from the Pipeline screen: see PIPELINE.md. This page still holds for the rollout itself.**

Each firm has its own release, shown on its page. An update goes first to **one canary firm**, then in batches, and stops at the first failure. The control plane never logs in to a firm: it names the release in the heartbeat answer, and each server does the rest itself.

**This has only run as a simulation on the firm's side.** `firm-update.sh` has never updated a real server: try it first on a made-up firm.

### 1. Build and sign the release (on your computer)

```
git fetch && git checkout <commit to publish>
scripts/provision/build_release.sh <commit> --key signing.pem --out out/
```

Or in two steps: `build_release.sh <commit> --unsigned --out out/` (no key needed), then `build_release.sh --sign out/<commit>.tar.gz --key signing.pem --pub signing.pub`, which asks for the passphrase once and signs the bundle, the catalogue and the attestation (`<commit>.attestation`, for the Pipeline screen).

It prints the commit and the `sha256`. Upload both files (`<commit>.tar.gz` and `<commit>.tar.gz.sig`) to the releases bucket: console.wasabisys.com > Buckets > `auditisa-releases-...` > **Upload**, without renaming them and without a folder. The bucket stays private: each server gets a signed download address from the console, valid 6 hours and renewed at each heartbeat. The bundle never holds `ea_platform_admin`.

### 2. Register it

Platform > Updates > Releases > New: paste the commit and the digest. Then **Load the catalogue file**: `<commit>.catalogue.json` and its signature, written beside the bundle. Without it the "Add-ons" screen has nothing to offer for this release, and no add-on request goes out (CLIENT-ADDONS.md).

### 3. Start it

Updates > Rollouts > New: the release, the **canary firm** (one that accepts going first), the firms concerned, the batch size. **Start: canary first.**

Set aside, with the reason shown: firms that are not active, are red, are locked, have no good backup, or already run this release. One update at a time.

### 4. What happens on each firm

At the next heartbeat (15 minutes at most), then within 5 minutes, on the server:

1. Downloads the bundle. **Refused if the digest or signature does not hold.**
2. Encrypted backup. **No backup, no update.**
3. Stops Odoo, copies the database, switches to the new release, updates the modules, restarts.
4. Health check.
5. **If anything fails: automatic return** to the previous release and database. The failed database is kept for analysis.

The firm is offline during step 3, from a few minutes to half an hour. Warn it.

### 5. Follow it

The rollout's page shows each firm: Waiting, Requested, Succeeded, Failed, Rolled back, No answer (90 minutes), Cancelled.

A line succeeds only with: the new release running, the server confirming, a backup later than the request, and a firm that is not red.

### If it stops

The rollout stops and an alert goes out. The failed firm is back on its old release and the following ones received nothing. Find the cause before trying again (`/var/log/odoo/update-*.log` on the server, after a break-glass entry). That server will not retry a refused release: fix it and publish a **new** release. If the state is "Failed" rather than "Rolled back", see INCIDENT.md.

### Keeping a firm out

Tick "Release locked" on its page.
