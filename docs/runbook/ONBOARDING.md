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

Puis l'écran **« Messagerie »**, facultatif : la boîte de messagerie du cabinet, voir l'étape 10. Laissé vide, cela se fait plus tard depuis la fiche du cabinet.

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

**10. Réglez la messagerie du cabinet, depuis la console.** Les e-mails du cabinet (réinitialisation de mot de passe, invitations) partent de sa propre boîte de messagerie (décision du propriétaire, 17 novembre 2026). Aucun utilisateur du cabinet, même son administrateur, ne voit ni ne change ce réglage. Demandez au contact, ou à son prestataire informatique, les réglages de sa boîte : fournisseur, serveur, port, chiffrement (STARTTLS ou SSL), identifiant, mot de passe, adresse d'expédition.

Sur la fiche du cabinet, cliquez **Messagerie de ce cabinet**. Choisissez le fournisseur (Microsoft 365, Google Workspace, Hostinger, MailerSend) : le serveur, le port et le chiffrement se remplissent seuls. Sinon choisissez « Autre fournisseur » et remplissez-les. Saisissez l'identifiant, le mot de passe et l'adresse d'expédition, puis **Enregistrer et tester**. Une ligne d'aide sous chaque champ dit quoi y mettre. Un champ mal rempli est refusé tout de suite, en clair, et rien ne part.

Ce qui se passe ensuite, sans rien faire de votre part :

- La console n'ouvre jamais de session sur le serveur du cabinet. Les réglages partent dans la réponse signée au prochain signal (heartbeat) du serveur du cabinet, une seule fois, sous 15 minutes.
- Le serveur du cabinet les vérifie de nouveau, enregistre le serveur d'envoi coupé, teste la connexion sans envoyer aucun message, et n'ouvre l'envoi que si le test réussit.
- Le résultat revient au signal suivant : onglet **Messagerie** de la fiche, sous 30 minutes. Rechargez la page. Il est dit en clair : « Envoi actif », « Identifiant ou mot de passe refusé », « Serveur de messagerie injoignable », « Chiffrement ou port à vérifier », « Adresse d'expéditeur refusée », etc., avec quoi faire. Corrigez et cliquez de nouveau **Messagerie de ce cabinet** : le formulaire s'ouvre sur les derniers réglages, sauf le mot de passe.
- Une fois l'envoi actif, la page de connexion du cabinet montre « Mot de passe oublié ? », et l'écran Utilisateurs propose **Envoyer par e-mail** à côté de **Copier** pour les liens d'invitation.

**Le mot de passe** n'est jamais enregistré dans la base de la console, jamais écrit dans un journal, jamais affiché de nouveau. Il attend, chiffré, dans un fichier que seul le service de la console peut lire (`/var/lib/odoo/firm-mail`), jusqu'au signal du serveur du cabinet. Il est effacé à ce moment-là, et au plus tard après 6 heures (le résultat dit alors « Pas récupéré à temps » : saisissez-le de nouveau). Le journal de la plateforme garde qui a envoyé quels réglages et quand, sans le mot de passe. Aucun accès d'urgence n'est nécessaire : rien ne passe par le port 22, le cabinet ne passe pas à l'orange.

**Couper l'envoi** (sur la fiche, quand l'envoi est actif) arrête tout envoi et masque « Mot de passe oublié ? ». Le résultat revient de la même façon.

**Pendant la création d'un cabinet**, l'écran facultatif « Messagerie » du formulaire Nouveau cabinet prend les mêmes réglages (« Vous pouvez le faire plus tard depuis la fiche du cabinet »). Remplis, ils partent au serveur du cabinet dès sa mise en service, puis tout se passe comme ci-dessus.

L'environnement de test (test.auditisa.com) n'envoie jamais de courrier : sa réponse est « Environnement de test : n'envoie jamais ». Un serveur de cabinet d'une version antérieure au 17 novembre 2026 ne sait pas encore lire ces réglages (« Pas de réponse du serveur du cabinet ») : mettez-le à jour d'abord.

**En dernier recours, à la main** (par exemple si la console est indisponible) : après un accès d'urgence enregistré, écrivez les réglages dans un fichier que seul root peut lire, puis lancez le script.

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

Le script fait le même test et n'affiche jamais le mot de passe. `firm-mail-server --dry-run` vérifie le fichier sans rien changer ; `firm-mail-server --off` coupe l'envoi.

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

Then the **"Email"** screen, optional: the firm's mailbox, see step 10. Left empty, it is done later from the firm's page.

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

**10. Set up the firm's email, from the console.** The firm's emails (password resets, invitations) go out from its own mailbox (owner's ruling, 17 November 2026). No firm user, not even its administrator, sees or changes this setting. Ask the contact, or their IT provider, for their mailbox settings: provider, server, port, encryption (STARTTLS or SSL), username, password, sender address.

On the firm's page, click **Email for this firm**. Choose the provider (Microsoft 365, Google Workspace, Hostinger, MailerSend): the server, the port and the encryption fill in by themselves. Otherwise choose "Another provider" and fill them in. Enter the username, the password and the sender address, then **Save and test**. A help line under each field says what goes there. A field filled in wrongly is refused at once, in plain words, and nothing is sent.

What happens next, with nothing to do on your side:

- The console never logs in to the firm's server. The settings travel in the signed answer to the firm's server's next heartbeat, once, within 15 minutes.
- The firm's server checks them again, saves the mail server switched off, tests the connection without sending any message, and opens sending only if the test passes.
- The result comes back with the following heartbeat: the **Email** tab of the firm's page, within 30 minutes. Reload the page. It is said in plain words: "Sending is on", "Username or password refused", "Mail server not reached", "Encryption or port to check", "Sender address refused", and so on, with what to do. Correct and click **Email for this firm** again: the form opens on the last settings, the password excepted.
- Once sending is on, the firm's login page shows "Forgot your password?", and the Users screen offers **Send by email** next to **Copy** for invitation links.

**The password** is never saved in the console's database, never written to a log, never shown again. It waits, encrypted, in a file only the console's service can read (`/var/lib/odoo/firm-mail`), until the firm's server's heartbeat. It is erased then, and after 6 hours at the latest (the result then says "Not collected in time": enter it again). The platform log keeps who sent which settings and when, without the password. No break-glass access is needed: nothing goes through port 22, and the firm does not turn amber.

**Switch sending off** (on the firm's page, when sending is on) stops all sending and hides "Forgot your password?". The result comes back the same way.

**While creating a firm**, the New firm form's optional "Email" screen takes the same settings ("You can do this later from the firm's page"). Filled in, they go to the firm's server as soon as it is live, then everything happens as above.

The test environment (test.auditisa.com) never sends email: its answer is "Test environment: never sends". A firm server on a release older than 17 November 2026 cannot read these settings yet ("No answer from the firm's server"): update it first.

**As a last resort, by hand** (for example if the console is down): after recording a break-glass access, write the settings to a file only root can read, then run the script.

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

The script runs the same test and never prints the password. `firm-mail-server --dry-run` checks the file and changes nothing; `firm-mail-server --off` switches sending off.

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
