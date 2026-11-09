# Les signataires / Trusted signers

Ajouté le 10 novembre 2026 (branche feat/signers). / Added on 10 November 2026 (branch feat/signers).

## Français

### En deux phrases

Une nouvelle version d'AuditISA ne s'installe chez un cabinet que si **une personne de confiance l'a signée** avec **sa propre clé**, gardée sur son ordinateur et verrouillée par **sa propre phrase secrète**. Il n'y a jamais de clé partagée : la console sait ainsi qui a signé, et le propriétaire peut retirer une personne sans toucher aux autres.

### Qui est où

| Où | Ce qui s'y trouve | Qui le change |
|---|---|---|
| L'ordinateur de chaque signataire | Sa clé privée (`%USERPROFILE%\auditisa-signing\auditisa-signing-key.pem`), verrouillée par sa phrase secrète, et sa clé publique (`.pub`) | Lui seul, avec « Make my signing key » |
| La console (Plateforme > Mises à jour > Signataires) | La liste des clés **publiques** de confiance : nom, e-mail, empreinte, ajouté par/quand, actif | Le propriétaire seul ; chaque changement est au journal de la plateforme |
| Le dépôt (`deploy/trust/signers.json`) | La même liste, numérotée, qui part dans chaque version | Le technicien, à partir du fichier téléchargé sur la console |
| Chaque cabinet et l'ordinateur d'entraînement (`/etc/auditisa-firm/trusted-signers/`, `/etc/auditisa-practice/trusted-signers/`) | **Leur propre copie** de la liste | Seulement une version signée par une personne qu'ils reconnaissent **déjà** |

### Pourquoi les cabinets ne suivent pas la console aveuglément

Si quelqu'un s'introduisait dans la console, il pourrait ajouter sa clé à la liste de la console. Cela ne lui servirait à rien pour les cabinets existants : un cabinet ne change sa liste qu'à partir de `deploy/trust/signers.json` **à l'intérieur d'une version dont il a déjà vérifié la signature** avec une clé qu'il reconnaît. La console ne peut fabriquer aucune signature (elle n'a que des clés publiques), donc elle ne peut ni pousser du code ni ajouter une clé chez un cabinet.

Règles appliquées par le serveur du cabinet (`deploy/firm/release_trust.py`, `firm-lib.sh`) :

1. Une version est acceptée si sa signature est celle d'une clé de **sa** liste.
2. Après une mise à jour réussie, et à chaque passage de `firm-apply-desired` (toutes les 5 minutes) pour la version en service, il lit la liste que porte cette version et la prend **seulement si son numéro est plus grand** que celui de la liste en service. Une ancienne version réinstallée ne peut donc pas ramener un signataire retiré.
3. Une liste mal formée (empreinte qui ne correspond pas, aucune personne active, clé en double) est refusée en bloc ; la liste en service reste.
4. Une personne **retirée** reste dans la liste, avec un fichier `.only` : ses signatures ne valent plus que pour les versions qu'elle a signées quand elle était de confiance (leurs empreintes). Tout ce qu'elle signe ensuite est refusé.

**Exception connue :** un **nouveau** cabinet reçoit au premier démarrage la liste de la console du moment (dans le texte de démarrage). C'est inévitable : la console crée le serveur et pourrait de toute façon y écrire ce qu'elle veut à ce moment. Les cabinets existants, eux, ne dépendent plus de la console pour leur confiance.

L'ordinateur d'entraînement suit la même règle (`practice-lib.sh`, `practice-update.sh`, `practice-apply-desired.sh`). Ses scripts ne se mettent pas à jour tout seuls : après le déploiement de cette branche, le technicien les recopie (`install-practice-server.sh`, voir PRACTICE-SPACES.md) pour qu'il applique la règle.

### Ajouter une deuxième personne (de bout en bout)

1. **La personne** installe Git pour Windows (git-scm.com) si ce n'est pas fait, copie le dossier « AuditISA signing » sur son bureau, et double-clique **« Make my signing key »**. Elle choisit une phrase secrète (12 caractères au moins) qu'elle seule connaît. L'outil affiche sa clé publique et son empreinte courte (4 groupes de 4 caractères) et copie la clé publique.
2. Elle **envoie la clé publique** au propriétaire par e-mail. Jamais le fichier `.pem`.
3. **Le propriétaire** ouvre la console > Plateforme > Mises à jour > Signataires > Nouveau, saisit le nom et l'e-mail, colle la clé publique, enregistre.
4. Le propriétaire **appelle la personne** et compare l'empreinte courte affichée sur la console avec celle de son écran. Si elles diffèrent : retirer tout de suite.
5. À partir de là, **la console** accepte ses signatures (versions en attente de signature, catalogues, attestations).
6. **Pour les cabinets :** le technicien télécharge la liste (Signataires > « Download the list for the next version (signers.json) »), la met dans `deploy/trust/signers.json`, la valide dans git, puis construit la version suivante. **Cette version doit être signée par une personne que les cabinets reconnaissent déjà** (au début : le propriétaire). Une fois installée, chaque cabinet reconnaît aussi la nouvelle personne. Le numéro de liste de chaque cabinet est visible sur sa fiche (« Signer list in use »).

Avant l'étape 6, une version signée par la nouvelle personne est acceptée par la console mais **refusée par les cabinets** : c'est voulu.

### Retirer une personne

Console > Signataires > la personne > **Retirer ce signataire** (propriétaire seul, au journal). Ses signatures futures sont refusées par la console tout de suite. Les versions qu'elle a signées restent valides. Pour les cabinets : comme à l'étape 6, une nouvelle version avec la nouvelle liste, signée par une personne restante. Une clé retirée ne revient jamais : la personne en crée une nouvelle (en déplaçant d'abord ses anciens fichiers).

On ne peut pas retirer la dernière personne : sans elle, plus aucune version ne pourrait être acceptée.

### Signer une version

Deux chemins, le même outil (« Sign new version ») :

- **Sur l'ordinateur du propriétaire** : le technicien construit la version non signée dans `Documents\Odoo-migration\console-live\release-<commit>\`. L'outil la trouve tout seul.
- **Sans l'ordinateur du propriétaire** : le technicien téléverse la version non signée sur la console (Plateforme > Mises à jour > En attente de signature > Nouveau : le `.tar.gz`, le `.catalogue.json` et le `.changes.txt`). Le signataire télécharge ces fichiers (le dossier Téléchargements convient), double-clique « Sign new version », puis téléverse sur la même page les trois fichiers créés (`.tar.gz.sig`, `.catalogue.json.sig`, `.attestation`) et clique « Vérifier les signatures et publier ». La console vérifie les trois avec la liste du jour (même signataire pour les trois), envoie la version dans le compartiment des versions et l'enregistre.

Avant toute question, l'outil montre : la version (commit court), la date, la liste des changements, l'empreinte du fichier, les personnes que cette version fera reconnaître, et sous quel nom on signe.

## English

### In two sentences

A new version of AuditISA installs at a firm only if **a trusted person signed it** with **their own key**, kept on their own computer and locked by **their own passphrase**. There is never a shared key: the console can tell who signed, and the owner can remove one person without touching the others.

### What is where

| Where | What | Who changes it |
|---|---|---|
| Each signer's computer | Their private key (`%USERPROFILE%\auditisa-signing\auditisa-signing-key.pem`), locked by their passphrase, and their public key (`.pub`) | Only them, with "Make my signing key" |
| The console (Platform > Updates > Signers) | The list of trusted **public** keys: name, email, fingerprint, added by/when, active | The owner only; every change is in the platform log |
| The repository (`deploy/trust/signers.json`) | The same list, numbered, carried by every release | The technician, from the file downloaded from the console |
| Each firm and the practice computer (`/etc/auditisa-firm/trusted-signers/`, `/etc/auditisa-practice/trusted-signers/`) | **Their own copy** of the list | Only a release signed by someone they **already** trust |

### Why firms do not follow the console blindly

Someone who broke into the console could add their key to the console's list. It would not help them with existing firms: a firm changes its list only from the `deploy/trust/signers.json` **inside a release whose signature it has already checked** with a key it trusts. The console cannot make a signature (it holds public keys only), so it can neither push code nor add a key at a firm.

Rules on the firm's server (`deploy/firm/release_trust.py`, `firm-lib.sh`):

1. A release is accepted if it is signed by a key in **its own** list.
2. After a successful update, and on every run of `firm-apply-desired` (every 5 minutes) for the release in use, it reads the list that release carries and takes it **only if its number is higher** than the list in use. An older release installed again cannot bring a removed signer back.
3. A malformed list (fingerprint that does not match its key, no active signer, a key listed twice) is refused whole; the list in use stays.
4. A **removed** signer stays in the list with a `.only` file: their signatures count only for the releases they signed while trusted (by bundle digest). Anything they sign later is refused.

**Known exception:** a **new** firm gets the console's list of the day at first boot (in its first-boot text). That cannot be avoided: the console creates the server and could write anything on it at that moment anyway. Existing firms no longer depend on the console for their trust.

The practice computer follows the same rule (`practice-lib.sh`, `practice-update.sh`, `practice-apply-desired.sh`). Its scripts do not update themselves: after this branch is deployed, the technician copies them again (`install-practice-server.sh`, see PRACTICE-SPACES.md) so that it applies the rule.

### Adding a second person, end to end

1. **The person** installs Git for Windows (git-scm.com) if needed, copies the "AuditISA signing" folder to their desktop and double-clicks **"Make my signing key"**. They choose a passphrase (12 characters at least) that only they know. The tool shows their public key and short fingerprint (4 groups of 4 characters) and copies the public key.
2. They **email the public key** to the owner. Never the `.pem` file.
3. **The owner** opens the console > Platform > Updates > Signers > New, types the name and email, pastes the public key, saves.
4. The owner **phones the person** and compares the short fingerprint on the console with the one on their screen. If they differ: remove at once.
5. From then on **the console** accepts their signatures (versions waiting for signature, catalogues, attestations).
6. **For the firms:** the technician downloads the list (Signers > "Download the list for the next version (signers.json)"), puts it at `deploy/trust/signers.json`, commits it, and builds the next release. **That release must be signed by someone the firms already trust** (at first: the owner). Once it is installed, each firm trusts the new person too. Each firm's list number shows on its page ("Signer list in use").

Before step 6, a release signed by the new person is accepted by the console but **refused by the firms**: on purpose.

### Removing a person

Console > Signers > the person > **Remove this signer** (owner only, logged). The console refuses their future signatures at once. The releases they signed stay valid. For the firms: as in step 6, a new release with the new list, signed by a remaining signer. A removed key never comes back: the person makes a new one (after moving their old files away).

The last person cannot be removed: without one, no release could ever be accepted again.

### Signing a release

Two paths, one tool ("Sign new version"):

- **On the owner's computer:** the technician builds the unsigned release in `Documents\Odoo-migration\console-live\release-<commit>\`. The tool finds it by itself.
- **Without the owner's computer:** the technician uploads the unsigned release to the console (Platform > Updates > Waiting for signature > New: the `.tar.gz`, the `.catalogue.json` and the `.changes.txt`). The signer downloads those files (the Downloads folder is fine), double-clicks "Sign new version", then uploads on the same page the three files it made (`.tar.gz.sig`, `.catalogue.json.sig`, `.attestation`) and clicks "Check the signatures and publish". The console checks all three against the list of the day (the same signer for all three), puts the release in the releases bucket and registers it.

Before asking anything, the tool shows: the version (short commit), the date, the list of changes, the file fingerprint, the people this release will make the firms trust, and who you sign as.

### Technical notes

- Fingerprint: SHA-256 of the key's DER SubjectPublicKeyInfo (`openssl pkey -pubin -in key.pub -outform DER | sha256sum`). The short form is its first 16 characters.
- List format: `deploy/trust/signers.json`, schema `auditisa-signers-v1`, written byte for byte the same by the console (`ea_platform_admin/services/signers.py`) and read by the firm with the standard library only (`deploy/firm/release_trust.py`). Tests: `deploy/firm/tests/test_release_trust.py`, `ea_platform_admin/services/tests/test_signers.py`, `ea_platform_admin/tests/test_signers.py`.
- Migration (ea_platform_admin 19.0.1.1.0): the one key of Platform > Settings became the signer "Owner" (contact@cm-ea.com), list number 1. The old parameter `ea_platform.release_signing_public_key` is kept, unread by the console, for `upload-release.sh` which still reads it.
- Heartbeat: a firm reports `signers_serial` once its server has taken a list. The console must be deployed **before** a release that sends it (an older console refuses an unknown figure).
