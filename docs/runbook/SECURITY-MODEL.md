# Le modèle de sécurité / The security model

[Français](#français) · [English](#english)

## Français

**Décision du propriétaire :** un serveur dédié par cabinet, et un Odoo d'administration séparé qui les voit tous.

**Ce qui a changé le 2026-11-07 (décision du propriétaire) :** la salle de contrôle a désormais un **accès prévu** aux cabinets, en trois moyens décrits dans SUPPORT.md : les erreurs techniques (des codes, dans le heartbeat), « Signaler un problème » (un texte qu'un utilisateur choisit d'envoyer, par un canal à part) et la **visite de support** (une connexion limitée dans le temps, en lecture seule, sous un compte nommé, numérotée et conservée, sans approbation du cabinet). Le contrôle n'a toujours **aucun mot de passe** d'un cabinet : la visite passe par un lien à usage limité dont il ne garde que l'empreinte.

**Le contrôle automatique couvre la conception, pas encore la réalité :** les tests prouvent les règles du contrôle et les fichiers produits par la recette. Aucun vrai serveur n'a été construit : la preuve réelle sera `verify_firm_isolation.sh` entre deux vrais cabinets (PREREQUISITES, étape 8).

### Ce qui est séparé, par cabinet

| Quoi | Comment | Vérifié par |
|---|---|---|
| Serveur, Odoo, PostgreSQL, fichiers | Une machine par cabinet | Conception ; test d'isolation à refaire sur de vrais serveurs |
| Clé SSH | Une par cabinet ; une clé déjà utilisée est refusée | Tests |
| Mot de passe PostgreSQL, mot de passe maître | Générés sur le serveur, n'en sortent jamais | Essai à blanc |
| Stockage et clé de sauvegarde | Propres au cabinet. La clé de chiffrement n'est jamais sur le contrôle | Essai à blanc, tests |
| Jeton de heartbeat | Un par cabinet ; celui d'un autre cabinet est refusé | Tests |
| Pare-feu | Le port 22 ne s'ouvre qu'aux adresses de l'opérateur ; un cabinet n'a aucun chemin vers le 22 ou la base d'un autre | Essai à blanc ; **à vérifier en réel** |
| Adresse | Une par cabinet | Tests |

### Ce que voit le contrôle

**Uniquement** ces chiffres : version, disque, mémoire, nombre d'utilisateurs et de missions, dates et résultats de sauvegarde et de test de restauration, expiration du certificat, messagerie ouverte ou non, état de la mise à jour et de l'export, nombre de connexions SSH, et les codes des modules clients allumés avec le nombre de demandes refusées.

- Un code de module qui n'est pas au catalogue est compté, jamais conservé : ce canal ne peut pas transporter de texte.
- Les erreurs techniques arrivent aussi en codes : module, écran (modèle), type d'erreur, heure, nombre. Jamais un message ni une trace.
- **Une exception, voulue :** les problèmes signalés contiennent le texte qu'un utilisateur du cabinet a écrit, après un avertissement de ne pas y mettre de détails de clients. Ils arrivent par un canal signé à part, pas par le heartbeat, et sont la seule donnée en texte libre venue d'un cabinet.
- L'écran de supervision et son export Excel n'affichent que ces chiffres, l'identité technique du serveur et ses références chez l'hébergeur. Aucune donnée d'audit, aucun jeton.
- Toute autre donnée dans un heartbeat fait rejeter le tout, et aucun champ n'accepte de texte libre.
- Un serveur de cabinet peut aussi dire qu'il a fait une copie anonymisée : un état, une référence, une date, une empreinte. La copie elle-même reste chez lui (PIPELINE.md).
- Pas de mot de passe de base, pas de clé de sauvegarde, pas de clé de stockage, pas de clé SSH privée. Le code ne contient ni client SSH, ni connexion à une base distante, ni appel RPC. Un test vérifie tout cela.
- Il refuse de s'installer dans la base d'un cabinet, et n'est pas dans le paquet livré aux cabinets.

**Un cabinet n'a accès au contrôle que pour son heartbeat :** une seule adresse (hb.auditisa.com), un seul chemin, en POST signé, avec une limite de débit. Le canal des problèmes signalés et celui de l'ordinateur d'entraînement n'y sont ouverts que sur décision (`FIRM_DOORS`) : fermés à ce jour.

**Les écrans (console.auditisa.com) s'ouvrent de partout** (décision du propriétaire du 8 novembre 2026). Ce qui les protège : la connexion, avec la double authentification (auth_totp) proposée à chaque utilisateur ; fail2ban, qui bannit une adresse après des connexions Odoo ou SSH échouées ; une limite de débit nginx sur `/web/login` et `/web/session/authenticate` ; ni gestionnaire ni liste des bases (`/web/database/*` refusé par nginx) ; pas d'inscription publique ; SSH par clé seulement ; HTTPS seulement, avec HSTS ; mises à jour de sécurité automatiques. Promouvoir et Reconstruire ne vérifient plus l'adresse, sauf si le paramètre `ea_platform_pipeline.owner_addresses` est rempli.

**La visite de support.** Sur demande motivée de l'opérateur, la réponse signée au heartbeat donne au serveur du cabinet le numéro, la durée, l'empreinte du lien, le nom de l'opérateur et le motif ; le script root revérifie tout et ouvre la visite. Le compte « AuditISA support (operator, not a firm user) » lit tous les écrans et ne peut rien écrire : le serveur refuse toute création, modification et suppression sous ce compte, même en superutilisateur, et lui ferme export, téléchargement, impression et dépôt. L'administrateur du cabinet est prévenu à l'écran et peut y mettre fin. Chaque visite reste, numérotée et non modifiable, des deux côtés, avec les écrans et fiches ouverts (identifiants). **Risque connu :** une intrusion sur le contrôle peut demander une visite et obtenir un lien, donc lire les données d'un cabinet pendant la durée de la visite, sans rien pouvoir modifier ; l'administrateur du cabinet la voit et peut l'arrêter. C'était déjà possible par l'accès d'urgence SSH de l'opérateur (voir plus bas).

**Le contrôle peut demander des modules clients, sans les imposer :** la réponse au heartbeat donne une liste de codes, et le script root du cabinet la refuse entière si un seul code n'est pas un module optionnel de la version signée en service. Une intrusion sur le contrôle peut donc allumer ou couper un module que cette version contient, avec au plus une installation et son arrêt de quelques minutes ; elle ne peut ni ajouter du code, ni toucher une fonction de base, ni rien désinstaller. Voir CLIENT-ADDONS.md.

### Les deux secrets que garde le contrôle

- **Le jeton de heartbeat de chaque cabinet.** Il permet de se faire passer pour lui auprès du contrôle. Il n'ouvre rien chez le cabinet.
- **Le lien du premier administrateur**, seulement entre sa création et son affichage (72 heures au plus). **Risque connu :** une intrusion sur le contrôle pendant ce délai pourrait prendre le compte administrateur d'un cabinet tout neuf, encore vide. Pour l'écarter : générez le lien sur le serveur (`firm-first-admin-link`).

Et, hors d'Odoo, en fichiers lisibles par root seul : le jeton Vultr, le jeton DNS, et la clé et le secret Wasabi de l'utilisateur `auditisa-console`. Cette clé Wasabi ne touche que les buckets `auditisa-*` et les utilisateurs `auditisa-firm-*`, ne peut écrire aucune politique sur un utilisateur et ne lit aucune sauvegarde (WASABI.md). La clé de stockage de chaque cabinet n'est gardée nulle part sur le contrôle.

Pour l'ordinateur d'entraînement (PRACTICE-SPACES.md), de la même façon : son jeton de heartbeat, et le lien de première connexion de chaque espace d'entraînement jusqu'à son affichage. Ils n'ouvrent que des espaces aux données fictives, jamais un serveur de cabinet.

Pour le staging (ENVIRONMENTS.md) : la clé SSH restreinte `/root/.ssh/auditisa_env_agent`, en fichier root sur la console, hors d'Odoo. Sur le staging elle ne peut lancer que `auditisa-env-agent` (lire les chiffres et les comptes, créer, désactiver ou changer le mot de passe d'un compte de test sur le staging ou un espace d'entraînement). Le mot de passe d'un compte de test est montré une fois à l'écran puis effacé ; seul son hash part au staging. Jamais un serveur de cabinet.

### Ce qui reste partagé

| Partagé | Conséquence | Comment durcir |
|---|---|---|
| **Le code** | Une faille dans les modules touche tous les cabinets. C'est le prix d'un seul produit. | Déploiement par témoin puis par lots, passage obligé par le staging. |
| **L'opérateur** (vous) | **Vous détenez toutes les clés : vous pouvez lire les données de tous les cabinets.** Le journal d'accès rend cela visible, sans l'empêcher. | Voir l'option plus bas. Clés sur clé matérielle, poste dédié. |
| **Le compte Vultr** | Son jeton permet d'arrêter ou de détruire tous les serveurs, et sa console donne la main sur eux. | Double authentification, jeton limité à l'adresse du contrôle. Un sous-compte par cabinet, ou le compte du cabinet lui-même. |
| **Le compte DNS** | Son jeton permet de détourner toutes les adresses `*.auditisa.com`. | Jeton limité à la zone. Le domaine propre du cabinet sort de ce risque. |
| **Le compte Wasabi** | La clé de la console peut supprimer les sauvegardes de tous les cabinets (pas les lire : elles sont chiffrées avec la clé de chaque cabinet). Le compte principal, lui, donne la main sur tout. | Double authentification sur le compte principal ; la clé de la console limitée par `auditisa-console-policy` ; un compte Wasabi réservé à la plateforme si vous voulez séparer complètement. |
| **La console** | Depuis le 10 novembre 2026 (décision du propriétaire), il n'y a plus de signature : qui prend la main sur la console, ou sur le compte du propriétaire, peut enregistrer une version et la faire installer par tous les cabinets. Les serveurs ne vérifient que l'empreinte SHA-256 que la console leur donne. | Mot de passe fort et double authentification pour le propriétaire ; si besoin, limiter Promouvoir à quelques adresses (`ea_platform_pipeline.owner_addresses`, PIPELINE.md) ; la console à jour. |
| **Le texte de premier démarrage** | Il reste chez Vultr et contient le jeton de heartbeat et la clé de stockage (qui n'ouvre que le bucket de ce cabinet). | Faire tourner la clé de stockage après l'installation (non construit). Le serveur bloque l'adresse de métadonnées sauf pour root et efface ses copies. |

### Qui peut mettre une version en ligne (depuis le 10 novembre 2026)

Le propriétaire, connecté à la console : **Promouvoir vers le staging**, puis **Promouvoir vers la production**. Il n'y a plus de clé de signature ni de liste de signataires. Un serveur de cabinet, ou l'ordinateur d'entraînement, n'installe un paquet que si son empreinte SHA-256 est celle que la console lui envoie dans sa réponse au heartbeat (HTTPS, authentifiée par le jeton propre à ce serveur) : le bucket des versions et l'adresse de téléchargement ne peuvent pas faire passer un autre fichier. La console, elle, devient le point à protéger.

### Limites du journal d'accès

Le serveur inscrit chaque connexion SSH dans un fichier en ajout seul, recopié dans son Odoo pour la salle de contrôle et la trace du support. Le cabinet ne le voit plus à l'écran depuis le 7 novembre 2026 (décision du propriétaire). Mais **root peut tout effacer** : ce journal décourage et révèle les oublis, il n'arrête pas un opérateur décidé. Le journal de la plateforme, lui, est en ajout seul jusque dans la base, et chaîné par empreintes : une modification se voit.

### Question ouverte : protéger les cabinets de l'opérateur ?

Le propriétaire n'a pas encore répondu. En attendant, il détient les clés. **La porte reste ouverte :**

| Option | Ce qui change | Ce que l'on perd |
|---|---|---|
| **A. Aujourd'hui :** l'opérateur détient tout | Simple ; vous pouvez dépanner seul | La confiance repose sur vous seul |
| **B. Clé SSH détenue par le cabinet.** Le cabinet fournit sa clé publique à la mise en service | Plus de connexion sans qu'il vous l'ouvre. La plateforme n'a rien à changer : elle ne reçoit déjà que la clé publique. | Chaque dépannage demande son accord ; s'il perd sa clé, reconstruction depuis les sauvegardes |
| **C. Clé de sauvegarde détenue aussi par le cabinet,** et chiffrement à clé publique | Même avec le serveur, vous ne lisez pas les anciennes sauvegardes | Le test de restauration automatique ne peut plus tourner sur le serveur, à repenser |
| **D. Le cabinet ouvre son propre compte Vultr** | Vous n'êtes plus propriétaire de la machine | Facturation, jeton par cabinet |

Même en B ou C, l'opérateur publie le code : une version publiée pourrait lire les données. Seule une revue du code par le cabinet, ou par un tiers, couvre ce point.

### Durcir ensuite

Double authentification sur Vultr, Cloudflare, GitHub et le contrôle ; surveillance extérieure du contrôle ; journaux envoyés hors du serveur ; `auth_totp` pour les associés (décision I-8) ; test d'intrusion avant le premier vrai cabinet.

## English

**The owner's decision:** one dedicated server per firm, and one separate admin Odoo that sees them all.

**What changed on 2026-11-07 (owner's decision):** the control room now has **provisioned access** to the firms, by three means described in SUPPORT.md: technical errors (codes, in the heartbeat), "Report a problem" (text a user chooses to send, on a separate channel) and the **support visit** (a time-limited, read-only sign-in as a named account, numbered and kept, with no approval from the firm). The control plane still holds **no password** of any firm: a visit goes through a time-limited link of which it keeps only the fingerprint.

**Automated checks cover the design, not yet reality:** the tests prove the control plane's rules and the files the recipe produces. No real server has been built: the real proof will be `verify_firm_isolation.sh` between two real firms (PREREQUISITES, step 8).

### What is separate, per firm

| What | How | Checked by |
|---|---|---|
| Server, Odoo, PostgreSQL, files | One machine per firm | Design; the isolation test must be repeated on real servers |
| SSH key | One per firm; a key already used is refused | Tests |
| PostgreSQL password, master password | Generated on the server, never leave it | Dry run |
| Backup storage and key | The firm's own. The encryption key is never on the control plane | Dry run, tests |
| Heartbeat token | One per firm; another firm's is refused | Tests |
| Firewall | Port 22 opens only to the operator's addresses; a firm has no path to another's port 22 or database | Dry run; **to be verified for real** |
| Address | One per firm | Tests |

### What the control plane sees

**Only** these figures: release, disk, memory, numbers of users and engagements, dates and results of backup and restore test, certificate expiry, whether mail is open, update and export state, number of SSH logins, and the codes of the client add-ons that are on with the number of refused requests.

- An add-on code outside the catalogue is counted and never kept: this channel cannot carry text.
- Technical errors arrive as codes too: addon, screen (model), error type, time, count. Never a message or a traceback.
- **One deliberate exception:** reported problems hold the text a firm's user wrote, after a warning not to put client details in it. They arrive on a separate signed channel, not in the heartbeat, and are the only free text that comes from a firm.
- The supervision page and its Excel export show only these figures, the server's technical identity and its references at the provider. No audit data and no token.
- Anything else in a heartbeat gets it all rejected, and no field accepts free text.
- A firm's server can also say it has made an anonymised copy: a state, a reference, a date and a digest. The copy itself stays there (PIPELINE.md).
- No database password, no backup key, no storage key, no private SSH key. The code holds no SSH client, no remote database connection, no RPC call. A test checks all of this.
- It refuses to install in a firm's database, and is not in the bundle firms receive.

**A firm reaches the control plane for its heartbeat only:** one address (hb.auditisa.com), one path, a signed, rate-limited POST. The reported-problems channel and the practice computer's are opened there only by decision (`FIRM_DOORS`): closed today.

**The screens (console.auditisa.com) open from anywhere** (the owner's ruling of 8 November 2026). What protects them: sign-in, with two-factor (auth_totp) available to every user; fail2ban, which bans an address after failed Odoo or SSH sign-ins; an nginx rate limit on `/web/login` and `/web/session/authenticate`; no database manager and no database list (`/web/database/*` refused by nginx); no public sign-up; SSH by key only; HTTPS only, with HSTS; automatic security updates. Promote and Rebuild no longer check the address, unless the parameter `ea_platform_pipeline.owner_addresses` is filled in.

**The support visit.** On the operator's stated reason, the signed heartbeat answer gives the firm's server the visit's number, its length, the link's fingerprint, the operator's name and the reason; the root script checks it all again and opens the visit. The account "AuditISA support (operator, not a firm user)" reads every screen and can write nothing: the server refuses every create, change and delete under that account, even as superuser, and closes export, download, print and upload to it. The firm's administrator is told on screen and can end it. Every visit stays, numbered and unchangeable, on both sides, with the screens and records opened (identifiers). **Known risk:** an intrusion on the control plane can ask for a visit and get a link, and so read a firm's data for the length of the visit, without being able to change anything; the firm's administrator sees it and can stop it. This was already possible through the operator's SSH break-glass access (see below).

**The control plane can ask for client add-ons, not impose them:** the heartbeat answer gives a list of codes, and the firm's root script refuses all of it if a single code is not an optional add-on of the signed release in use. An intrusion on the control plane can therefore switch on or off an add-on that release carries, at most causing an install and its outage of a few minutes; it cannot add code, touch a base feature or uninstall anything. See CLIENT-ADDONS.md.

### The two secrets the control plane keeps

- **Each firm's heartbeat token.** It lets someone impersonate that firm to the control plane. It opens nothing at the firm.
- **The first administrator's link**, only between its creation and its display (72 hours at most). **Known risk:** an intrusion on the control plane in that window could take the administrator account of a brand-new, still empty firm. To rule it out: generate the link on the server (`firm-first-admin-link`).

And, outside Odoo, in root-only files: the Vultr token, the DNS token, and the Wasabi key and secret of the user `auditisa-console`. That Wasabi key touches only the `auditisa-*` buckets and the `auditisa-firm-*` users, cannot write a policy on any user and reads no backup (WASABI.md). Each firm's storage key is kept nowhere on the control plane.

For the practice computer (PRACTICE-SPACES.md), the same two kinds: its heartbeat token, and each practice space's first-login link until it is shown. They open only spaces of made-up data, never a firm's server.

For staging (ENVIRONMENTS.md): the restricted SSH key `/root/.ssh/auditisa_env_agent`, a root file on the console, outside Odoo. On staging it can run `auditisa-env-agent` only (read figures and accounts; create, disable or give a new password to a test account on staging or in a practice space). A test account's password is shown once on screen, then blanked; only its hash goes to staging. Never a firm's server.

### What is still shared

| Shared | Consequence | How to harden |
|---|---|---|
| **The code** | A flaw in the addons touches every firm. That is the price of one product. | Canary then batches, Staging first. |
| **The operator** (you) | **You hold every key: you can read every firm's data.** The access log makes it visible, it does not prevent it. | See the option below. Keys on a hardware key, a dedicated computer. |
| **The Vultr account** | Its token can stop or destroy every server, and its console gives control of them. | Two-factor login, token limited to the control plane's address. A sub-account per firm, or the firm's own account. |
| **The DNS account** | Its token can divert every `*.auditisa.com` address. | Token limited to the zone. A firm's own domain leaves this risk. |
| **The Wasabi account** | The console's key can delete every firm's backups (not read them: they are encrypted with each firm's key). The main account controls everything. | Two-factor login on the main account; the console's key limited by `auditisa-console-policy`; a Wasabi account kept for the platform alone for complete separation. |
| **The console** | Since 10 November 2026 (the owner's decision) there is no signature: whoever takes over the console, or the owner's account, can register a release and have every firm install it. Servers only check the SHA-256 the console gives them. | A strong password and two-factor login for the owner; if needed, limit Promote to some addresses (`ea_platform_pipeline.owner_addresses`, PIPELINE.md); keep the console up to date. |
| **The first-boot text** | It stays at Vultr and holds the heartbeat token and the storage key (which opens that firm's bucket only). | Rotate the storage key after the install (not built). The server blocks the metadata address for all but root and erases its copies. |

### Who can put a release live (since 10 November 2026)

The owner, signed in to the console: **Promote to Staging**, then **Promote to Production**. There is no signing key and no list of signers any more. A firm's server, or the practice computer, installs a bundle only if its SHA-256 is the one the console sends in its heartbeat answer (HTTPS, authenticated with that server's own token): the releases bucket and the download address cannot slip another file in. The console itself is now what must be protected.

### Limits of the access log

The server writes each SSH login to an append-only file, copied into its Odoo for the control room and the support trail. Since 7 November 2026 (owner's ruling) the firm no longer sees it on screen. But **root can erase anything**: this log deters and reveals omissions, it does not stop a determined operator. The platform's own log is append-only down to the database and hash-chained: a change shows.

### Open question: protect firms from the operator?

The owner has not answered yet. Meanwhile, the owner holds the keys. **The door stays open:**

| Option | What changes | What is lost |
|---|---|---|
| **A. Today:** the operator holds everything | Simple; you can fix things alone | Trust rests on you alone |
| **B. SSH key held by the firm.** The firm supplies its public key at onboarding | No login unless it lets you in. The platform needs no change: it already only receives the public key. | Each fix needs its agreement; if it loses its key, rebuild from backups |
| **C. Backup key also held by the firm,** with public-key encryption | Even with the server, you cannot read old backups | The automatic restore test can no longer run on the server, to rethink |
| **D. The firm opens its own Vultr account** | You no longer own the machine | Billing, a token per firm |

Even with B or C, the operator publishes the code: a published release could read the data. Only a code review by the firm, or a third party, covers that.

### Hardening next

Two-factor login on Vultr, Cloudflare, GitHub and the control plane; outside monitoring of the control plane; logs sent off the server; `auth_totp` for partners (decision I-8); a penetration test before the first real firm.
