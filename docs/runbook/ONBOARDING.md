# Mettre en service un nouveau cabinet / Onboarding a new firm

[Français](#français) · [English](#english)

## Français

**Durée :** 10 minutes de votre temps, puis 20 à 45 minutes d'attente. Cette durée est une estimation : elle n'a jamais été mesurée sur un vrai serveur.

### Ce qu'il faut avoir sous la main

- Le nom du cabinet et l'identifiant choisi (`cabinet-exemple` : il devient `cabinet-exemple.auditisa.com` et **ne changera plus**).
- Le nom, l'e-mail et le téléphone du contact. Cet e-mail sera l'identifiant du premier administrateur.
- Les domaines de messagerie autorisés (`exemple.cm`). Le domaine du contact doit en faire partie.
- La région (Paris par défaut), la taille (voir PREREQUISITES) et la langue par défaut du cabinet : français ou anglais. Chaque utilisateur pourra ensuite choisir sa langue dans ses préférences.
- Son accord sur le coût mensuel.
- Le lieu sûr où vous mettrez ses clés (votre coffre).

### Pas à pas

**1. Créez la clé SSH de ce cabinet, sur votre ordinateur.** Une par cabinet, jamais réutilisée :

```
ssh-keygen -t ed25519 -f ~/.ssh/auditisa-cabinet-exemple -C cabinet-exemple
```

Mettez un mot de passe dessus, copiez le fichier sans extension dans votre coffre. Le fichier `.pub` est celui qu'on colle à l'écran.

**2. Plateforme > Nouveau cabinet. Écran « Le cabinet ».** Remplissez, puis **Continuer**. Un message rouge explique tout refus : nom réservé (`www`, `dev`, `test`, `status`, etc.), identifiant déjà attribué même à un ancien cabinet, e-mail hors des domaines.

**3. Écran « Le serveur ».** Région, taille, langue, version, et collez le contenu du `.pub`. **Continuer**. Si vous collez la clé privée par erreur, elle est effacée du formulaire et refusée.

**4. Écran « Modules ».** Allumez les modules propres à ce client, s'il en a, et dites pourquoi : le motif va au journal. Rien à choisir sinon : le code commun est toujours là, et cela peut changer plus tard. Voir CLIENT-ADDONS.md.

**5. Écran « Vérification ».** Relisez : l'adresse, le serveur, les modules, les adresses autorisées sur le port 22, le coût mensuel estimé. Le bandeau dit SIMULATION ou RÉEL. Cochez la confirmation, puis **Créer le serveur**. Rien n'est créé avant.

**6. Le journal des étapes s'affiche.** Onze lignes, de « À faire » à « Fait » :

| Étape | Durée estimée |
|---|---|
| Contrôle, clé SSH, pare-feu, stockage, lien | moins d'une minute |
| Création et démarrage du serveur | 1 à 3 minutes |
| Adresse DNS | quelques secondes |
| Installation sur le serveur (attente du premier heartbeat) | 15 à 40 minutes |
| Contrôle de santé automatique, mise en service | de quelques secondes à quelques minutes |

Vous pouvez fermer la page : tout avance seul, toutes les deux minutes. Pour y revenir : Suivi > Mises en service.

**7. Quand tout est « Fait »,** le cabinet passe à « Actif » sur le tableau, en orange avec le motif « Clé de sauvegarde pas encore confirmée au coffre ». C'est normal.

**8. Mettez la clé de sauvegarde au coffre.** Elle n'existe que sur le serveur du cabinet. Sans elle, si le serveur disparaît, **les sauvegardes sont illisibles**. Sur la fiche, cliquez **Accès d'urgence**, indiquez le motif « clé de sauvegarde », puis :

```
ssh -i ~/.ssh/auditisa-cabinet-exemple root@cabinet-exemple.auditisa.com cat /etc/auditisa-firm/secrets/restic.key
```

Copiez la valeur dans votre coffre, puis cliquez **Clé de sauvegarde mise au coffre** sur la fiche. Le cabinet passe au vert.

**9. Transmettez le lien du premier administrateur.** Sur la fiche, **Afficher le lien du premier administrateur**. Il ne s'affiche **qu'une fois**. Donnez-le au contact par un canal privé (appel, messagerie chiffrée). Il expire après 72 heures et ne sert qu'une fois. Le contact y choisit lui-même son mot de passe : **personne ne reçoit de mot de passe par e-mail, et vous ne le connaissez pas.**

**10. Réglez la messagerie sortante du cabinet.** C'est une étape de la mise en service, faite par vous : aucun utilisateur du cabinet, même son administrateur, ne voit ni ne change ce réglage (décision du propriétaire, 7 novembre 2026). Demandez au contact les réglages de son fournisseur de messagerie : serveur, port, chiffrement (STARTTLS ou SSL), identifiant, mot de passe, adresse ou domaine d'expédition. Après un accès d'urgence enregistré, écrivez-les dans un fichier que seul root peut lire, puis lancez le script :

```
ssh -i ~/.ssh/auditisa-cabinet-exemple root@cabinet-exemple.auditisa.com
install -m 600 /dev/null /etc/auditisa-firm/secrets/mail.env
nano /etc/auditisa-firm/secrets/mail.env
firm-mail-server
```

Le fichier contient une ligne par réglage :

```
MAIL_HOST=smtp.fournisseur.cm
MAIL_PORT=587
MAIL_ENCRYPTION=starttls
MAIL_USER=cabinet@exemple.cm
MAIL_PASSWORD=...
MAIL_FROM=cabinet@exemple.cm
```

Le script enregistre le serveur coupé, teste la connexion (sans envoyer de message) et n'ouvre l'envoi que si le test réussit. Il n'affiche jamais le mot de passe. S'il répond « sending stays off », corrigez le fichier et relancez-le. `firm-mail-server --dry-run` vérifie le fichier sans rien changer. L'écran Paramètres du cabinet dit seulement « Envoi activé » ou « Envoi désactivé ». L'environnement de test (test.auditisa.com) n'envoie jamais de courrier : le script y est refusé.

### Vérifier

- Sur le tableau, le cabinet est vert, avec un heartbeat de moins de 15 minutes.
- `https://cabinet-exemple.auditisa.com` montre la page de connexion, sans cadenas barré.
- `https://cabinet-exemple.auditisa.com/web/database/manager` répond « page introuvable ».
- Le lendemain matin : une date à « Dernière sauvegarde ». Au bout d'une semaine : une date à « Dernier test de restauration ».

### Si une étape échoue

- **Une panne passagère** : l'étape réessaie seule. Son message s'affiche à côté.
- **Un échec définitif** : la plateforme retire tout ce qu'elle a créé. La page dit « aucun serveur ne reste » et l'étape en échec donne le motif. Corrigez, puis **Relancer la mise en service**. L'identifiant reste réservé à ce cabinet.
- **Bandeau rouge « Le nettoyage n'a pas abouti »** : un serveur peut rester et être facturé. Cliquez **Relancer le nettoyage**. S'il échoue encore, voir INCIDENT.md.
- **Page fermée ou serveur de contrôle redémarré** : rien n'est perdu. **Reprendre** continue à la première étape non finie sans rien créer deux fois.
- **L'installation dépasse 60 minutes** : tout est retiré automatiquement. Le plus souvent, l'adresse des versions ou la signature est en cause.

### Qui reçoit quoi

| Quoi | Qui |
|---|---|
| Clé SSH privée du cabinet | Vous, dans votre coffre |
| Clé de sauvegarde | Le serveur du cabinet, et vous, dans votre coffre |
| Lien du premier administrateur | Le contact du cabinet, par vous, une fois |
| Mot de passe de l'administrateur | Le contact seul |
| Mot de passe PostgreSQL, mot de passe maître d'Odoo | Le serveur du cabinet seul. Personne ne les reçoit. |
| Mot de passe de la messagerie sortante | Le contact vous le donne ; il reste sur le serveur du cabinet (fichier lisible par root seul, et Odoo). Aucun utilisateur du cabinet ne le voit. |
| Factures Vultr et Wasabi | Vous |

### Le domaine propre du cabinet (facultatif)

Le cabinet crée un CNAME de `audit.cabinet.cm` vers `cabinet-exemple.auditisa.com`. Après un accès d'urgence enregistré : `ssh ... root@cabinet-exemple.auditisa.com firm-add-domain audit.cabinet.cm`, puis renseignez « Domaine propre » sur la fiche. L'adresse d'origine continue de fonctionner.

## English

**Time:** 10 minutes of yours, then 20 to 45 minutes of waiting. That is an estimate: it has never been measured on a real server.

### Have ready

- The firm's name and its chosen slug (`cabinet-exemple`: it becomes `cabinet-exemple.auditisa.com` and **never changes**).
- The contact's name, email and phone. This email becomes the first administrator's login.
- The allowed email domains (`exemple.cm`). The contact's domain must be one of them.
- The region (Paris by default), the size (see PREREQUISITES) and the firm's default language: French or English. Each user can then choose their own in their preferences.
- Their agreement on the monthly cost.
- Where you will keep their keys (your safe).

### Step by step

**1. Create this firm's SSH key, on your computer.** One per firm, never reused:

```
ssh-keygen -t ed25519 -f ~/.ssh/auditisa-cabinet-exemple -C cabinet-exemple
```

Give it a passphrase and copy the file without an extension to your safe. The `.pub` file is what goes on screen.

**2. Platform > New firm. Screen "The firm".** Fill it in, then **Continue**. A red message explains any refusal: reserved name (`www`, `dev`, `test`, `status`, and so on), slug already given even to a former firm, email outside the domains.

**3. Screen "The server".** Region, size, language, release, and paste the content of the `.pub` file. **Continue**. If you paste the private key by mistake, it is wiped from the form and refused.

**4. Screen "Add-ons".** Switch on any add-ons of this client's own and say why: the reason goes in the log. Otherwise there is nothing to choose: the shared code is always there, and this can change later. See CLIENT-ADDONS.md.

**5. Screen "Review".** Read it through: address, server, add-ons, addresses allowed on port 22, estimated monthly cost. The band says SIMULATION or REAL. Tick the confirmation, then **Create the server**. Nothing is created before that.

**6. The step log appears.** Eleven lines going from "To do" to "Done":

| Step | Estimated time |
|---|---|
| Check, SSH key, firewall, storage, link | under a minute |
| Creating and starting the server | 1 to 3 minutes |
| DNS address | seconds |
| Install on the server (waiting for the first heartbeat) | 15 to 40 minutes |
| Automatic health check, going live | seconds to a few minutes |

You may close the page: it moves on by itself every two minutes. To come back: Tracking > Provisioning runs.

**7. When all say "Done",** the firm shows "Active" on the board, orange with the reason "Backup key not yet confirmed as stored in the safe". That is expected.

**8. Put the backup key in the safe.** It exists only on the firm's server. Without it, if the server is lost, **the backups cannot be read**. On the firm's page click **Break-glass access**, give the reason "backup key", then:

```
ssh -i ~/.ssh/auditisa-cabinet-exemple root@cabinet-exemple.auditisa.com cat /etc/auditisa-firm/secrets/restic.key
```

Copy the value to your safe, then click **Backup key is in the safe**. The firm turns green.

**9. Pass on the first administrator's link.** On the firm's page, **Show the first administrator's link**. It shows **once only**. Give it to the contact over a private channel (a call, encrypted messaging). It expires after 72 hours and works once. The contact chooses their own password there: **nobody receives a password by email, and you do not know it.**

**10. Set up the firm's outgoing mail.** This is an onboarding step, done by you: no firm user, not even its administrator, sees or changes this setting (owner's ruling, 7 November 2026). Ask the contact for their mail provider's settings: server, port, encryption (STARTTLS or SSL), username, password, sender address or domain. After recording a break-glass access, write them to a file only root can read, then run the script:

```
ssh -i ~/.ssh/auditisa-cabinet-exemple root@cabinet-exemple.auditisa.com
install -m 600 /dev/null /etc/auditisa-firm/secrets/mail.env
nano /etc/auditisa-firm/secrets/mail.env
firm-mail-server
```

The file holds one setting per line:

```
MAIL_HOST=smtp.provider.cm
MAIL_PORT=587
MAIL_ENCRYPTION=starttls
MAIL_USER=cabinet@exemple.cm
MAIL_PASSWORD=...
MAIL_FROM=cabinet@exemple.cm
```

The script saves the server switched off, tests the connection (no message is sent) and opens sending only if the test passes. It never prints the password. If it answers "sending stays off", correct the file and run it again. `firm-mail-server --dry-run` checks the file and changes nothing. The firm's Settings screen only says "Sending on" or "Sending off". The test environment (test.auditisa.com) never sends email: the script is refused there.

### How to verify

- On the board the firm is green, with a heartbeat under 15 minutes old.
- `https://cabinet-exemple.auditisa.com` shows the login page, with a valid certificate.
- `https://cabinet-exemple.auditisa.com/web/database/manager` answers "not found".
- Next morning: a date under "Last backup". After a week: a date under "Last restore test".

### If a step fails

- **A passing fault:** the step retries by itself, with its message beside it.
- **A final failure:** the platform removes everything it created. The page says "no server remains", and the failed step gives the reason. Fix it, then **Start provisioning again**. The slug stays reserved for this firm.
- **Red band "The clean-up did not finish":** a server may remain and be billed. Click **Run the clean-up again**. If it fails again, see INCIDENT.md.
- **Page closed or control server restarted:** nothing is lost. **Resume** carries on at the first unfinished step and creates nothing twice.
- **The install runs past 60 minutes:** everything is removed automatically. The releases address or the signature is the usual cause.

### Who gets what

| What | Who |
|---|---|
| The firm's private SSH key | You, in your safe |
| Backup key | The firm's server, and you, in your safe |
| First administrator's link | The firm's contact, from you, once |
| Administrator's password | The contact alone |
| PostgreSQL password, Odoo master password | The firm's server alone. Nobody receives them. |
| Outgoing mail password | The contact gives it to you; it stays on the firm's server (a root-only file, and Odoo). No firm user sees it. |
| Vultr and Wasabi invoices | You |

### The firm's own domain (optional)

The firm creates a CNAME from `audit.cabinet.cm` to `cabinet-exemple.auditisa.com`. After recording a break-glass access: `ssh ... root@cabinet-exemple.auditisa.com firm-add-domain audit.cabinet.cm`, then fill in "The firm's own domain" on the firm's page. The original address keeps working.
