# La pipeline / The pipeline

[Français](#français) · [English](#english)

## Français

**Décisions du propriétaire :** L'onglet Statut de la salle de contrôle montre l'outil Next.js et l'outil Odoo côte à côte, avec les commits GitHub en direct. Les boutons Promouvoir et Reconstruire ne pilotent **qu'Odoo** : un clic malheureux ne peut pas atteindre l'outil du cabinet en service. Reconstruire le staging depuis la production se fait sur une **copie anonymisée** : clients, personnes et documents remplacés, chiffres gardés, pièces justificatives laissées de côté.

**Ce qui a réellement tourné :** l'anonymiseur et la reconstruction sur des bases jetables, avec des données de démonstration ; le reste (promotion, déploiement, cabinets) seulement en simulation. Aucun vrai serveur de cabinet n'existe encore.

### 1. Les trois étapes

| | Développement | Staging | Production |
|---|---|---|---|
| **Branche** | `dev` | `staging` (à créer) | `main` |
| **Où** | bases jetables | test.auditisa.com | les serveurs des cabinets |
| **Comment on y arrive** | fusion d'une branche `feat/*` | `git push origin <commit>:refs/heads/staging`, puis déploiement | version signée, puis déploiement par témoin et lots |

Pour l'outil Next.js, rien ne change : `dev` sur dev.auditisa.com, `main` sur www, sans serveur de staging à part.

Créer la branche, une seule fois, quand vous êtes d'accord : `git push origin origin/dev:refs/heads/staging`. Puis, sur le staging, `BRANCH=staging` pour `deploy-staging.sh`. Jusque-là, la page indique que le staging suit `dev`.

### 2. À mettre en place une fois

**L'onglet « État » de la salle de contrôle** (Plateforme > Statut, à côté de Supervision) montre les deux outils, leurs trois étapes, les commits GitHub, les chiffres de l'outil actuel, et les boutons Promouvoir et Reconstruire. Tant que rien n'est branché, il affiche des **DONNÉES D'EXEMPLE**, écrit sur chaque carte.

**Le collecteur, sur le serveur de la salle de contrôle (quand il existe) :**

```
python3 deploy/control-plane/pipeline-collect.py --print     # lit une fois, n'écrit rien
python3 deploy/control-plane/pipeline-collect.py --install   # chaque minute, dans /var/lib/auditisa-platform/pipeline-state.json
```

Il tourne en dehors d'Odoo, en root : l'Odoo d'administration ne garde ni code réseau ni clé, il lit ce fichier et revérifie chaque valeur.

**L'accès au dépôt Odoo privé (clé en lecture seule, par vous), sur ce même serveur :**

```
ssh-keygen -t ed25519 -N '' -C 'control room read-only' -f /root/.ssh/auditisa_odoo_ro
gh repo deploy-key add /root/.ssh/auditisa_odoo_ro.pub --repo Nekoutb/auditisa-odoo --title control-room-read-only
```

**Ne cochez pas l'écriture.** Sans cette clé, les cartes Odoo disent que l'accès n'est pas en place. Le dépôt Next.js est public : rien à faire.

**Les chiffres de l'outil actuel : rien à installer sur le serveur de production.** Le collecteur lit `https://www.auditisa.com/api/version` et `https://dev.auditisa.com/api/version` (déjà publics : commit et dates), et `https://status.auditisa.com/status.json` (déjà public), dont il ne garde que des chiffres : dates et commits des déploiements, sauvegardes de nuit et leur taille, migrations. Les chemins, ports, noms de base et la mémoire de ce fichier sont écartés. Les résultats de tests ne s'y trouvent pas : l'écran le dit.

**Ce que le staging publie (sur 108.61.209.30) :** `bash deploy/staging/publish-staging-state.sh --install`. Pour retirer : `--uninstall`. Le fichier public ne contient qu'un commit, deux réponses oui ou non et deux dates.

**Le script de reconstruction (sur 108.61.209.30) :** `install -m 700 deploy/staging/staging-rebuild.sh deploy/staging/seat_owner.py /usr/local/sbin/` puis `mv /usr/local/sbin/staging-rebuild.sh /usr/local/sbin/staging-rebuild`.

**Quand la salle de contrôle a son ordinateur :**

1. Déclarer le staging : sur la salle de contrôle, dans `odoo shell`, `env["platform.firm"]._pipeline_enrol_staging(); env.cr.commit()`. Le jeton va dans `/etc/auditisa-platform/staging-heartbeat.token`, jamais à l'écran. Copiez-le sur le staging dans `/etc/auditisa-staging/heartbeat.token` (600), et créez `/etc/auditisa-staging/heartbeat.env` avec `HEARTBEAT_URL=https://<HEARTBEAT_HOST>/platform/heartbeat` et `SLUG=staging-server`.
2. Plateforme > Réglages : la clé publique de signature, et vos adresses dans `ssh_allowlist`. **Les boutons refusent toute action d'une autre adresse, et refusent tout si cette liste est vide.**
3. status.auditisa.com renvoie vers la salle de contrôle, `/status.json` restant servi pour le collecteur (sur le VPS de production, par vous) :
   ```
   ssh -J root@185.92.222.217 root@45.32.150.96 'bash -s -- check' < deploy/status/redirect-status-site.sh
   ssh -J root@185.92.222.217 root@45.32.150.96 'bash -s -- apply https://www.auditisa.com/admin' < deploy/status/redirect-status-site.sh
   ```
   Pour revenir : même commande avec `rollback`. Le générateur actuel reste en place : il produit les chiffres que l'onglet lit.

### 3. Promouvoir le staging en production

Rien ne peut démarrer sans une version que vous avez signée vous-même, hors ligne.

1. **Sur votre ordinateur, avec la clé branchée seulement pour cette commande :**
   ```
   git fetch && scripts/pipeline/sign_promotion.sh origin/staging --key signature.pem --out sortie/
   ```
   Déposez les deux fichiers affichés à l'emplacement des versions. Si deux personnes doivent signer, c'est ici.
2. **Plateforme > Mises à jour > Versions > Nouveau :** collez le commit, l'empreinte et l'attestation. « Signée hors ligne » doit être coché.
3. **Pipeline > Essais :** inscrivez les tests de ce commit (GitHub Actions est à l'arrêt).
4. **Statut > Promouvoir :** la version, le cabinet témoin, les cabinets, la taille des lots. **Lancer les contrôles :**
   - attestation valable pour ce commit et cette empreinte ;
   - tests verts sur ce commit, le dernier essai de chaque suite faisant foi ;
   - le staging tourne sur ce commit, a répondu depuis moins de 45 minutes, courriel coupé ;
   - chaque cabinet a une bonne sauvegarde de moins de 26 heures ;
   - un seul déploiement à la fois.
5. **Démarrer :** tapez exactement la ligne demandée (`PROMOUVOIR <12 caractères du commit>`) et un motif. Les contrôles repassent à ce moment.
6. **Le déploiement existant fait le reste :** témoin, puis lots, arrêt au premier échec. Voir UPDATING.md.
7. **Quand tous les cabinets sont passés,** déplacez `main` vous-même, puis **Confirmer main déplacé** :
   ```
   git push origin <commit>:refs/heads/main
   ```
   `main` bouge en dernier : il dit toujours ce que tournent les cabinets. L'écran n'a aucun accès en écriture à GitHub.

### 4. Revenir en arrière

**Un cabinet qui échoue revient seul** à sa version et à sa base d'avant, et le déploiement s'arrête. `main` n'a pas bougé. Corrigez, et publiez une **nouvelle** version.

**Sur une promotion, Préparer un retour** demande la version d'avant, déjà signée, à tous les cabinets, dans le même ordre, avec la même confirmation. **Limite :** cela ramène le code, pas la base. Une version qui a modifié le schéma ne se défait pas ainsi : voir BACKUP-RESTORE.md. Si `main` a déjà bougé, ne le forcez pas : annulez le commit sur `dev` et promouvez cette correction.

### 5. Reconstruire le staging depuis un cabinet

Le serveur du cabinet fait tout le travail sensible. L'Odoo d'administration demande et note, rien de plus : il ne reçoit qu'un état et une empreinte, par le heartbeat habituel, et **aucune donnée n'y arrive**.

**Une fois, avec l'accord du cabinet :** sur son serveur, ajoutez `ANON_EXPORT_ALLOWED=1` à `/etc/auditisa-firm/firm.env`. Sans cela, le serveur refuse et le dit.

1. **Statut > Reconstruire :** le cabinet source, la ligne à taper (`RECONSTRUIRE <cabinet>`) et un motif.
2. **Au prochain heartbeat (15 minutes au plus),** le serveur du cabinet copie sa base sans s'arrêter, l'anonymise, relit le résultat et s'arrête au moindre doute. Le fichier reste chez lui, lisible par root seul. Le cabinet voit l'opération dans Configuration > Accès de l'opérateur.
3. **L'écran affiche la référence et l'empreinte.** Notez l'accès d'urgence dans le journal, car vous vous connectez au serveur du cabinet, puis, sur votre ordinateur :
   ```
   scripts/pipeline/relay_anon_dump.sh root@<cabinet> <réf> <empreinte> root@108.61.209.30 --apply
   ```
   Le fichier traverse votre poste sans y rester, et il est refusé à l'arrivée si l'empreinte diffère.
4. **Sur le staging, à blanc d'abord :**
   ```
   staging-rebuild --dump /var/lib/auditisa-staging/incoming/anon-<réf>.tar --sha256 <empreinte>
   ```
   **Lisez ce qu'elle affiche d'abord : ce qui a été saisi sur le staging depuis la dernière reconstruction, avec les noms des clients et des missions. La reconstruction le remplace** (ces saisies ne restent que dans la base mise de côté). Puis ajoutez `--apply`, et `--accept-loss <nombre>` s'il y a des saisies : le nombre est celui affiché, et s'il a changé, le script s'arrête de nouveau. Prévenez quiconque teste.
5. **Pipeline > Noter le staging reconstruit.**

**Ce que fait `--apply`, dans l'ordre :** vérifie le fichier ; sauvegarde la base en service dans `/var/backups/odoo/before-rebuild/` ; restaure sous un autre nom ; vérifie que la copie est bien anonymisée ; applique les protections et les relit une à une (courriel coupé, bandeau affiché, mots de passe effacés, tâches planifiées coupées, `web.base.url` figé, pas de heartbeat au nom d'un cabinet). **Si une seule ne tient pas, la copie est supprimée et rien d'autre n'a changé.** Puis il échange les noms, met les modules à jour, replace votre connexion par `deploy/staging/seat_owner.py` (comme `/root/add_contact_user.py`, qui s’arrête sur une mission archivée) et démarre Odoo. Si Odoo ne répond pas, l'ancienne base revient seule.

**Revenir à la base d'avant :** `staging-rebuild --rollback <date> --apply`. La date est affichée à la fin de la reconstruction. L'ancienne base, ses fichiers et la sauvegarde restent jusqu'à ce que vous les supprimiez.

**Avec les déploiements :** ce script n'utilise jamais `ea_audit_staging_prev` ni `ea_audit_staging_new`. Il s'arrête si `ea_audit_staging_new` existe (déploiement en cours), et prévient si `ea_audit_staging_prev` existe, car `fd_switch.sh` s'arrête alors.

### 6. Ce que garantit l'anonymiseur, et ce qu'il ne garantit pas

**S'arrête plutôt que deviner :** une table, une colonne de texte ou un modèle absent de `deploy/firm/anon-manifest.json` arrête l'export, sans laisser de fichier ni de copie. Quand une version ajoute un champ, l'export s'arrête jusqu'à ce que le manifeste soit refait : `scripts/pipeline/anon_manifest_gen.py`.

**Remplacé :** noms, adresses, courriels, téléphones, numéros fiscaux et de registre, intitulés, texte libre, réponses aux feuilles de travail (sauf oui, non et autres réponses fermées). **Supprimé :** discussions, journaux, pièces jointes, sessions, jetons, mots de passe, serveurs de courriel. **Gardé :** montants, dates, comptes, structure des missions.

**Contrôle final :** le fichier terminé est relu comme du texte, à la recherche de chaque nom relevé avant le traitement et des formes d'un courriel, d'un NIU, d'un téléphone camerounais, d'un RCCM et d'un compte bancaire. Un seul résultat arrête tout. Le journal dit où, jamais quoi.

**Limites connues :**

- Les montants et dates restent : ensemble, ils peuvent permettre de reconnaître un client par quelqu'un qui connaît ses comptes. **Le staging n'a que la connexion Odoo pour protection** : à décider avant une vraie copie (voir le point ci-dessous).
- Un identifiant composé seulement de chiffres dans un fichier importé, ou un mot seul en minuscules dans une clé de JSON, et qui ne figure sur aucune fiche, n'est pas reconnu.
- Les empreintes de signature sont remplacées : sur le staging, les feuilles signées se lisent comme modifiées depuis leur signature.

**Accord du cabinet :** une copie anonymisée reste une utilisation de ses données. Prévoyez-le au contrat avant d'activer `ANON_EXPORT_ALLOWED`.

### 7. L'onglet Statut

Il est dans la salle de contrôle, derrière vos adresses et votre connexion : plus de page publique. Il montre des commits, des noms d'auteur, des dates, des mots d'état et des nombres ; pas de message de commit, pas de secret.

**Retard :** le collecteur lit GitHub chaque minute par `git ls-remote`. **L'onglet a donc au plus environ une minute de retard**, plus le temps de recharger la page. Une lecture de plus de trois minutes est marquée comme ancienne. Un webhook serait immédiat mais demanderait une adresse publique et un réglage du dépôt : non retenu.

### 8. Si cela s'arrête

| Ce que vous voyez | Ce que cela veut dire | Que faire |
|---|---|---|
| Contrôles : `NO` | Une condition manque | Le motif est écrit. Rien n'a démarré |
| « This address is not one of the owner's » | Vous n'êtes pas sur une de vos adresses, ou la liste est vide | Plateforme > Réglages |
| Déploiement arrêté | Un cabinet a échoué et est revenu seul | UPDATING.md, « Si cela s'arrête » |
| Reconstruction : Refusée | Le cabinet n'a pas `ANON_EXPORT_ALLOWED=1` | Section 5 |
| Reconstruction : Échec | L'anonymiseur s'est arrêté. Rien n'est sorti | Sur le serveur du cabinet, `firm-anon-export <réf>` à la main dit pourquoi. Refaites le manifeste si une version a ajouté un champ |
| `STOP survivor in …` | Un nom ou une forme interdite reste dans une table | Le message nomme la table. Corrigez le manifeste ou la donnée. **Ne contournez pas ce contrôle** |
| `safeguard: …` sur le staging | Une protection ne tient pas | La copie a été supprimée, le staging est intact |

---

## English

**The owner's rulings:** The control room's Status tab shows the Next.js tool and the Odoo tool side by side, with live GitHub commits. The Promote and Rebuild buttons control **Odoo only**, so a mis-click cannot reach the live firm's tool. Rebuilding staging from production uses an **anonymised copy**: client, people and document details replaced, figures kept, evidence files left out.

**What has really run:** the anonymiser and the rebuild, on throwaway databases with demo data; the rest (promotion, rollout, firms) in simulation only. No real firm server exists yet.

### 1. The three stages

| | Development | Staging | Production |
|---|---|---|---|
| **Branch** | `dev` | `staging` (to be created) | `main` |
| **Where** | throwaway databases | test.auditisa.com | the firm servers |
| **How it gets there** | merge of a `feat/*` branch | `git push origin <commit>:refs/heads/staging`, then deploy | a signed release, then canary and batches |

For the Next.js tool nothing changes: `dev` on dev.auditisa.com, `main` on www, with no separate staging server.

To create the branch, once, when you agree: `git push origin origin/dev:refs/heads/staging`. Then, on staging, `BRANCH=staging` for `deploy-staging.sh`. Until then the page says staging follows `dev`.

### 2. To set up once

**The "Status" tab of the control room** (Platform > Status, beside Supervision) shows both tools, their three stages, the GitHub commits, the current tool's figures, and the Promote and Rebuild buttons. Until anything is connected it shows **SAMPLE DATA**, written on every card.

**The collector, on the control room's server (once it exists):**

```
python3 deploy/control-plane/pipeline-collect.py --print     # reads once, writes nothing
python3 deploy/control-plane/pipeline-collect.py --install   # each minute, into /var/lib/auditisa-platform/pipeline-state.json
```

It runs outside Odoo, as root: the admin Odoo keeps no network code and no key, it reads this file and checks each value again.

**Access to the private Odoo repository (a read-only key, by you), on that same server:**

```
ssh-keygen -t ed25519 -N '' -C 'control room read-only' -f /root/.ssh/auditisa_odoo_ro
gh repo deploy-key add /root/.ssh/auditisa_odoo_ro.pub --repo Nekoutb/auditisa-odoo --title control-room-read-only
```

**Do not tick write access.** Without this key, the Odoo cards say access is not set up. The Next.js repository is public: nothing to do.

**The current tool's figures: nothing to install on the production server.** The collector reads `https://www.auditisa.com/api/version` and `https://dev.auditisa.com/api/version` (public already: commit and dates), and `https://status.auditisa.com/status.json` (public already), of which it keeps figures only: deploy dates and commits, nightly backups and their size, migrations. That file's paths, ports, database names and memory are dropped. Test results are not in it: the screen says so.

**What staging publishes (on 108.61.209.30):** `bash deploy/staging/publish-staging-state.sh --install`. To remove: `--uninstall`. The public file holds a commit, two yes-or-no answers and two dates, nothing else.

**The rebuild script (on 108.61.209.30):** `install -m 700 deploy/staging/staging-rebuild.sh deploy/staging/seat_owner.py /usr/local/sbin/`, then `mv /usr/local/sbin/staging-rebuild.sh /usr/local/sbin/staging-rebuild`.

**Once the control room has its own computer:**

1. Enrol staging: on the control room, in `odoo shell`, `env["platform.firm"]._pipeline_enrol_staging(); env.cr.commit()`. The token goes to `/etc/auditisa-platform/staging-heartbeat.token`, never to the screen. Copy it to staging as `/etc/auditisa-staging/heartbeat.token` (600), and create `/etc/auditisa-staging/heartbeat.env` with `HEARTBEAT_URL=https://<HEARTBEAT_HOST>/platform/heartbeat` and `SLUG=staging-server`.
2. Platform > Settings: the public signing key, and your addresses in `ssh_allowlist`. **The buttons refuse any action from another address, and refuse everything if that list is empty.**
3. status.auditisa.com sends people to the control room, `/status.json` still being served for the collector (on the production VPS, by you):
   ```
   ssh -J root@185.92.222.217 root@45.32.150.96 'bash -s -- check' < deploy/status/redirect-status-site.sh
   ssh -J root@185.92.222.217 root@45.32.150.96 'bash -s -- apply https://www.auditisa.com/admin' < deploy/status/redirect-status-site.sh
   ```
   To go back: the same command with `rollback`. The current generator stays: it makes the figures the tab reads.

### 3. Promoting staging to production

Nothing can start without a release you signed yourself, offline.

1. **On your computer, with the key plugged in for this command only:**
   ```
   git fetch && scripts/pipeline/sign_promotion.sh origin/staging --key signing.pem --out out/
   ```
   Upload the two files it names to the releases location. If two people are to sign, this is where.
2. **Platform > Updates > Releases > New:** paste the commit, the digest and the attestation. "Signed offline" must show ticked.
3. **Pipeline > Test runs:** record this commit's tests (GitHub Actions is stopped).
4. **Status > Promote:** the release, the test firm, the firms, the batch size. **Run the pre-checks:**
   - the attestation holds for this commit and digest;
   - tests are green on this commit, the newest run of each suite counting;
   - staging runs this commit, reported within 45 minutes, mail off;
   - every firm has a good backup less than 26 hours old;
   - one rollout at a time.
5. **Start:** type exactly the line asked for (`PROMOTE <12 characters of the commit>`) and a reason. The pre-checks run again at this moment.
6. **The existing rollout does the rest:** canary, then batches, stopping at the first failure. See UPDATING.md.
7. **Once every firm is through,** move `main` yourself, then **Confirm main moved**:
   ```
   git push origin <commit>:refs/heads/main
   ```
   `main` moves last, so it always says what the firms run. The screen has no write access to GitHub.

### 4. Going back

**A firm that fails goes back by itself** to its previous release and database, and the rollout stops. `main` has not moved. Fix it and publish a **new** release.

**On a promotion, Prepare a rollback** asks every firm for the previous, already signed release, in the same order, with the same confirmation. **Limit:** this brings the code back, not the database. A release that changed the schema is not undone this way: see BACKUP-RESTORE.md. If `main` has already moved, do not force it: revert the commit on `dev` and promote that fix.

### 5. Rebuilding staging from a firm

The firm's server does all the sensitive work. The admin Odoo asks and logs, no more: it receives only a state and a digest, through the usual heartbeat, and **no data reaches it**.

**Once, with the firm's agreement:** on its server, add `ANON_EXPORT_ALLOWED=1` to `/etc/auditisa-firm/firm.env`. Without it the server refuses, and says so.

1. **Status > Rebuild:** the source firm, the line to type (`REBUILD <firm>`) and a reason.
2. **At the next heartbeat (15 minutes at most),** the firm's server copies its database without stopping, anonymises it, reads the result back, and stops at the slightest doubt. The file stays there, readable by root only. The firm sees it in Settings > Operator access.
3. **The screen shows the reference and the digest.** Enter a break-glass access in the log, since you are logging in to the firm's server, then, on your computer:
   ```
   scripts/pipeline/relay_anon_dump.sh root@<firm> <ref> <digest> root@108.61.209.30 --apply
   ```
   The file passes through your computer without staying there, and is refused on arrival if the digest differs.
4. **On staging, as a dry run first:**
   ```
   staging-rebuild --dump /var/lib/auditisa-staging/incoming/anon-<ref>.tar --sha256 <digest>
   ```
   **Read what it shows first: what has been entered on staging since the last rebuild, with the names of clients and engagements. The rebuild replaces it** (those records stay only in the database kept aside). Then add `--apply`, and `--accept-loss <count>` if there are any: the count is the one shown, and if it has changed the script stops again. Tell anyone who is testing.
5. **Pipeline > Record staging rebuilt.**

**What `--apply` does, in order:** checks the file; backs up the database in service to `/var/backups/odoo/before-rebuild/`; restores under another name; checks the copy really is anonymised; applies the safeguards and reads each back (mail off, band on, passwords cleared, crons off, `web.base.url` frozen, no heartbeat in a firm's name). **If one does not hold, the copy is dropped and nothing else has changed.** Then it swaps the names, updates the addons, re-seats your login with `deploy/staging/seat_owner.py` (as `/root/add_contact_user.py`, which stops on an archived engagement) and starts Odoo. If Odoo does not answer, the old database comes back by itself.

**Back to the previous database:** `staging-rebuild --rollback <date> --apply`. The date is printed at the end of the rebuild. The old database, its files and the backup stay until you remove them.

**With deployments:** this script never uses `ea_audit_staging_prev` or `ea_audit_staging_new`. It stops if `ea_audit_staging_new` exists (a deployment is under way), and warns if `ea_audit_staging_prev` exists, as `fd_switch.sh` then stops.

### 6. What the anonymiser guarantees, and what it does not

**It stops rather than guesses:** a table, a text column or a model missing from `deploy/firm/anon-manifest.json` stops the export, leaving no file and no copy. When a release adds a field, the export stops until the manifest is rebuilt: `scripts/pipeline/anon_manifest_gen.py`.

**Replaced:** names, addresses, emails, phones, tax and register numbers, labels, free text, working-paper answers (except yes, no and other closed answers). **Removed:** chatter, logs, attachments, sessions, tokens, passwords, mail servers. **Kept:** amounts, dates, accounts, the structure of engagements.

**Final check:** the finished file is read back as text, searching for every name collected before the work began and for the shapes of an email, a NIU, a Cameroon phone number, an RCCM and a bank account. One hit stops everything. The log says where, never what.

**Known limits:**

- Amounts and dates remain: together they may let someone who knows a client's accounts recognise them. **Staging has only the Odoo login to protect it:** to be decided before a real copy goes there.
- An identifier made only of digits in an imported file, or a single lower-case word used as a JSON key, that appears on no record, is not recognised.
- Signature digests are replaced: on staging, signed papers read as changed since signing.

**The firm's agreement:** an anonymised copy is still a use of its data. Cover it in the contract before switching on `ANON_EXPORT_ALLOWED`.

### 7. The Status tab

It is in the control room, behind your addresses and your sign-in: there is no public page any more. It shows commits, author names, dates, state words and counts; no commit message, no secret.

**How far behind:** the collector reads GitHub each minute with `git ls-remote`. **So the tab is at most about one minute behind**, plus the time to reload the page. A reading older than three minutes is marked as old. A webhook would be instant but needs a public address and a repository setting: not chosen.

### 8. If it stops

| What you see | What it means | What to do |
|---|---|---|
| Pre-checks: `NO` | A condition is missing | The reason is written there. Nothing started |
| "This address is not one of the owner's" | You are not on one of your addresses, or the list is empty | Platform > Settings |
| Rollout stopped | A firm failed and went back by itself | UPDATING.md, "If it stops" |
| Rebuild: Refused | The firm does not have `ANON_EXPORT_ALLOWED=1` | Section 5 |
| Rebuild: Failed | The anonymiser stopped. Nothing left the firm | On the firm's server, `firm-anon-export <ref>` by hand says why. Rebuild the manifest if a release added a field |
| `STOP survivor in …` | A name or forbidden shape remains in a table | The message names the table. Fix the manifest or the data. **Do not work around this check** |
| `safeguard: …` on staging | A safeguard does not hold | The copy was dropped, staging is untouched |
