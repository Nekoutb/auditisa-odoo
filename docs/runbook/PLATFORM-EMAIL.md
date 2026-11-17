# L'adresse e-mail de la plateforme / The platform email address

Chaque cabinet client peut envoyer ses e-mails (réinitialisation de mot de passe, invitations) depuis
`support@<identifiant>.cm-ea.com`, sans boîte e-mail à lui, dès sa mise en service. La console crée
l'adresse chez MailerSend et ses enregistrements DNS chez Cloudflare (demande du propriétaire, 17 novembre 2026).

Each client firm can send its emails (password resets, invitations) from `support@<slug>.cm-ea.com`,
without a mailbox of its own, as soon as it is live. The console makes the address at MailerSend and its
DNS records at Cloudflare (owner's request, 17 November 2026).

## Français

### Ce que reçoit chaque cabinet

- Une adresse d'envoi : `support@<identifiant>.cm-ea.com` (par exemple `support@cabinet-ngono.cm-ea.com`).
- Les réponses vont à **l'e-mail de contact** saisi dans le formulaire Nouveau cabinet (décision du propriétaire, 18 novembre 2026).
- Un domaine d'envoi chez MailerSend, `<identifiant>.cm-ea.com`, vérifié (SPF, DKIM, chemin de retour), et un utilisateur SMTP à lui (serveur `smtp.mailersend.net`, port 587, STARTTLS).
- Rien d'autre ne change pour le cabinet : son serveur teste les réglages sans envoyer de message, et n'ouvre l'envoi que si le test réussit, comme pour « Messagerie de ce cabinet ».

### Ce que vous faites une seule fois

**1. Le jeton MailerSend.** Dans MailerSend : *Integrations* > *API tokens* > *Generate new token*. Nom : `AuditISA console`. Domaine : *All domains*. Permissions, en *Full access* : **Domains**, **SMTP users** et **Email** (ce dernier pour le bouton « Envoyer un e-mail de test »). Rien d'autre. Copiez le jeton : MailerSend ne le montre qu'une fois.

**2. Le jeton Cloudflare.** Dans Cloudflare : *My Profile* > *API Tokens* > *Create Token* > *Create Custom Token*. Nom : `AuditISA mail cm-ea.com`. Permission : **Zone > DNS > Edit**. Zone Resources : **Include > Specific zone > cm-ea.com**, et aucune autre zone. Si « Tester la connexion » dit plus tard que le jeton ne voit pas la zone, ajoutez **Zone > Zone > Read** sur la même zone. Copiez le jeton.

**3. Donnez les deux jetons à la console.** Comme les autres jetons de la console (Vultr, Cloudflare, Wasabi), ils ne se saisissent pas dans une page : ce sont des fichiers que seul root peut lire sur le serveur de la console, que systemd remet à Odoo. Sur le serveur de la console, en root :

```
/opt/auditisa-platform/deploy/control-plane/set-mail-token.sh mailersend
/opt/auditisa-platform/deploy/control-plane/set-mail-token.sh cloudflare
```

Chaque commande demande le jeton (collez-le, il ne s'affiche pas), l'enregistre (`/etc/auditisa-platform/mailersend.token` et `cloudflare-mail.token`, droits 600) et redémarre la console (quelques secondes). Le jeton n'est jamais affiché, jamais écrit dans un journal, jamais dans la base, jamais dans un export.

**4. Plateforme > Réglages, partie « Service d'envoi pour les cabinets ».** Les cases « Jeton MailerSend reçu » et « Jeton Cloudflare reçu » doivent être cochées. Vérifiez le domaine parent (`cm-ea.com`), la zone Cloudflare (`cm-ea.com`), le nom d'expéditeur (`support`) et « Les réponses vont à » (l'e-mail de contact du cabinet). Cliquez **Appliquer ces réglages**, puis **Tester la connexion** : deux appels en lecture seule, dont le résultat s'affiche en clair (« MailerSend : connecté… », « Cloudflare : connecté. La zone cm-ea.com a été trouvée. »). L'identifiant de la zone est cherché et gardé à ce moment-là.

Dès lors, le formulaire Nouveau cabinet propose d'avance « AuditISA envoie pour ce cabinet ».

### Ce qui se passe pour un cabinet

- **Nouveau cabinet** : à l'écran « Messagerie », gardez le choix recommandé. Pendant l'installation, l'étape **« Mise en place de l'e-mail du cabinet »** crée le domaine chez MailerSend, écrit ses enregistrements DNS chez Cloudflare (DNS seul, jamais proxifiés ; ceux qui sont déjà justes ne sont pas réécrits), et demande à MailerSend de vérifier le domaine.
- La vérification prend en général quelques minutes, parfois une heure. **Elle ne retient jamais le cabinet** : l'installation continue, et la console vérifie de nouveau d'elle-même (après 1, 2, 5, 10, 15, 30 minutes, puis toutes les heures). Après 48 heures sans vérification, la fiche le dit et propose « Vérifier de nouveau maintenant ».
- Une fois le domaine vérifié, la console crée l'utilisateur SMTP et envoie ses réglages au serveur du cabinet, dans la réponse signée à son prochain signal, une seule fois. Le mot de passe SMTP n'est jamais enregistré dans la base : il attend chiffré hors de la base, au plus 6 heures. S'il n'est pas récupéré à temps (installation longue), la console crée un nouveau mot de passe et renvoie, jusqu'à 3 fois.
- L'onglet **Messagerie** de la fiche montre l'adresse, l'état de la vérification du domaine, le dernier contrôle, le dernier e-mail de test, puis « L'envoi est activé, depuis support@… ».
- Une erreur de MailerSend ou de Cloudflare n'annule jamais un cabinet : elle s'affiche sur la fiche, en clair, avec quoi faire.

**Un cabinet déjà en service** : sur sa fiche, **Donner une adresse e-mail de la plateforme à ce cabinet** (la console demande confirmation), puis tout se passe comme ci-dessus.

**Les boutons de la fiche :**

- **Envoyer un e-mail de test** : un court e-mail, de l'adresse du cabinet vers l'adresse que vous saisissez. Le résultat s'affiche en clair (« MailerSend a accepté l'e-mail de test… »). Il ne contient que le nom du cabinet.
- **Utiliser plutôt la boîte e-mail du cabinet** : le formulaire « Messagerie de ce cabinet » habituel. L'adresse de la plateforme reste, mais ne sert plus ; retirez-la si elle n'est plus utile.
- **Retirer l'adresse de la plateforme** : après confirmation, supprime l'utilisateur SMTP et le domaine chez MailerSend, et ses enregistrements DNS chez Cloudflare. Si le cabinet envoyait depuis cette adresse, l'envoi est coupé sur son serveur.
- **La sortie d'un cabinet** (destruction du serveur) retire aussi son domaine MailerSend et ses enregistrements DNS. Ce qui ne peut pas être retiré est signalé, comme pour le serveur.

### Les espaces d'entraînement et le site de test

- **test.auditisa.com n'envoie jamais d'e-mail**, quoi qu'il arrive : il ne reçoit pas d'adresse de la plateforme.
- **Les espaces d'entraînement** n'envoient aucun e-mail par défaut. Plateforme > Réglages, « Les espaces d'entraînement ne peuvent écrire qu'à ces adresses » : une adresse par ligne. Vide (par défaut) : aucun e-mail. Remplie : un espace d'entraînement n'écrit qu'à ces adresses ; tout autre destinataire est écarté et journalisé (adresse masquée). La liste part vers l'ordinateur d'entraînement à son prochain signal, et chaque espace l'applique.
- Pour qu'un espace d'entraînement envoie vraiment, il faut **en plus**, sur l'ordinateur d'entraînement, que root le permette (`PRACTICE_MAIL_ALLOWED='1'` dans `practice.env`) et ouvre le port 587 en sortie, qui reste fermé par défaut. C'est la décision du propriétaire, pas un réglage par défaut.
- **Preuve d'envoi** : sur la fiche d'un cabinet dont l'adresse est vérifiée, **Envoyer un e-mail de test**, case « Comme le ferait un espace d'entraînement » cochée. L'e-mail ne part que si l'adresse est sur la liste ; sinon, rien ne part et la console le dit.

### Limites

- **Nombre de domaines d'envoi** (grille publique de MailerSend, novembre 2026) : Free et Hobby, 1 domaine ; **Starter, 10 domaines** ; **Professional, illimité**. Chaque cabinet utilise un domaine. Au-delà de la limite, la fiche du cabinet dit « le compte a atteint le nombre de domaines d'envoi de son abonnement » : passez à l'abonnement supérieur, ou retirez l'adresse d'un cabinet parti.
- Volume : celui de l'abonnement (par exemple 50 000 e-mails par mois pour Starter et Professional). Les e-mails d'AuditISA sont peu nombreux (réinitialisations, invitations).
- Requêtes API par jour : 100 000 (Starter), 500 000 (Professional) ; la console en fait quelques-unes par cabinet.
- Le nombre d'utilisateurs SMTP par abonnement n'est pas publié sur la grille : chaque cabinet en utilise un. Si MailerSend refuse, la fiche le dit.
- Un domaine non vérifié ne peut pas envoyer : MailerSend refuse l'expéditeur.

### Confidentialité

Les e-mails qu'envoie un cabinet ne portent qu'un nom, un nombre et un lien (par exemple « 3 demandes en attente » et le lien vers la page). **Jamais de donnée de client** : ni pièce, ni montant, ni contenu de dossier. L'e-mail de test ne porte que le nom du cabinet. La console ne garde ni les jetons (fichiers root), ni le mot de passe SMTP, et le journal de la plateforme ne nomme que le domaine du destinataire d'un e-mail de test.

## English

### What each firm gets

- A sending address: `support@<slug>.cm-ea.com` (for example `support@cabinet-ngono.cm-ea.com`).
- Replies go to the **contact email** typed in the New firm form (owner's decision, 18 November 2026).
- A sending domain at MailerSend, `<slug>.cm-ea.com`, verified (SPF, DKIM, return path), and an SMTP user of its own (server `smtp.mailersend.net`, port 587, STARTTLS).
- Nothing else changes for the firm: its server tests the settings without sending a message, and opens sending only if the test passes, as with "Email for this firm".

### What you do once

**1. The MailerSend token.** In MailerSend: *Integrations* > *API tokens* > *Generate new token*. Name: `AuditISA console`. Domain: *All domains*. Permissions, at *Full access*: **Domains**, **SMTP users** and **Email** (the last one for the "Send a test email" button). Nothing else. Copy the token: MailerSend shows it once only.

**2. The Cloudflare token.** In Cloudflare: *My Profile* > *API Tokens* > *Create Token* > *Create Custom Token*. Name: `AuditISA mail cm-ea.com`. Permission: **Zone > DNS > Edit**. Zone Resources: **Include > Specific zone > cm-ea.com**, and no other zone. If "Test the connection" later says the token cannot see the zone, add **Zone > Zone > Read** on the same zone. Copy the token.

**3. Give the two tokens to the console.** Like the console's other tokens (Vultr, Cloudflare, Wasabi), they are not typed into a page: they are files only root can read on the console's server, which systemd hands to Odoo. On the console's server, as root:

```
/opt/auditisa-platform/deploy/control-plane/set-mail-token.sh mailersend
/opt/auditisa-platform/deploy/control-plane/set-mail-token.sh cloudflare
```

Each command asks for the token (paste it, it is not shown), saves it (`/etc/auditisa-platform/mailersend.token` and `cloudflare-mail.token`, mode 600) and restarts the console (a few seconds). The token is never shown, never written to a log, never in the database, never in an export.

**4. Platform > Settings, part "Sending service for firms".** "MailerSend token received" and "Cloudflare token received" must be ticked. Check the parent domain (`cm-ea.com`), the Cloudflare zone (`cm-ea.com`), the sender name (`support`) and "Replies go to" (the firm's contact email). Click **Apply these settings**, then **Test the connection**: two read-only calls, whose result shows in plain words ("MailerSend: connected...", "Cloudflare: connected. The zone cm-ea.com was found."). The zone's id is looked up and kept then.

From then on, the New firm form offers "AuditISA sends for this firm" in advance.

### What happens for a firm

- **New firm**: on the "Email" screen, keep the recommended choice. During provisioning, the step **"Set up the firm's email"** makes the domain at MailerSend, writes its DNS records at Cloudflare (DNS only, never proxied; those already right are not written again), and asks MailerSend to check the domain.
- The check usually takes a few minutes, sometimes an hour. **It never holds up the firm**: provisioning goes on, and the console checks again by itself (after 1, 2, 5, 10, 15, 30 minutes, then every hour). After 48 hours without verification, the page says so and offers "Check again now".
- Once the domain is verified, the console makes the SMTP user and sends its settings to the firm's server, in the signed answer to its next heartbeat, once. The SMTP password is never saved in the database: it waits encrypted outside it, 6 hours at most. If it is not collected in time (a long install), the console makes a new password and sends again, up to 3 times.
- The page's **Email** tab shows the address, the domain check, the last check, the last test email, then "Sending is on, from support@...".
- A MailerSend or Cloudflare error never cancels a firm: it shows on the page, in plain words, with what to do.

**A firm already live**: on its page, **Give this firm a platform email address** (the console asks to confirm), then everything happens as above.

**The page's buttons:**

- **Send a test email**: one short email, from the firm's address to the address you type. The result shows in plain words ("MailerSend accepted the test email..."). It carries the firm's name only.
- **Use the firm's own mailbox instead**: the usual "Email for this firm" form. The platform address stays but is no longer used; remove it if it is not needed any more.
- **Remove the platform address**: after confirmation, deletes the SMTP user and the domain at MailerSend, and its DNS records at Cloudflare. If the firm was sending from this address, sending is switched off on its server.
- **A firm's exit** (its server destroyed) also removes its MailerSend domain and DNS records. What cannot be removed is reported, as for the server.

### Practice spaces and the test site

- **test.auditisa.com never sends email**, whatever happens: it gets no platform address.
- **Practice spaces** send no email by default. Platform > Settings, "Practice spaces may email only these addresses": one address per line. Empty (the default): no email. Filled: a practice space writes to these addresses only; every other recipient is dropped and logged (address masked). The list goes to the practice computer at its next heartbeat, and every space applies it.
- For a practice space to really send, root must **also** allow it on the practice computer (`PRACTICE_MAIL_ALLOWED='1'` in `practice.env`) and open outgoing port 587, which stays closed by default. This is the owner's decision, not a default.
- **Proof of sending**: on the page of a firm whose address is verified, **Send a test email** with "As a practice space would" ticked. The email goes only if the address is on the list; otherwise nothing goes and the console says so.

### Limits

- **Number of sending domains** (MailerSend's public price list, November 2026): Free and Hobby, 1 domain; **Starter, 10 domains**; **Professional, unlimited**. Each firm uses one domain. Past the limit, the firm's page says "the account has reached its plan's number of sending domains": upgrade the plan, or remove the address of a firm that left.
- Volume: the plan's (for example 50,000 emails a month for Starter and Professional). AuditISA sends few emails (resets, invitations).
- API requests a day: 100,000 (Starter), 500,000 (Professional); the console makes a few per firm.
- The number of SMTP users per plan is not on the price list: each firm uses one. If MailerSend refuses, the page says so.
- A domain not verified cannot send: MailerSend refuses the sender.

### Confidentiality

The emails a firm sends carry only a name, a count and a link (for example "3 requests waiting" and the link to the page). **Never a client's data**: no document, no amount, no file content. The test email carries the firm's name only. The console keeps neither the tokens (root files) nor the SMTP password, and the platform log names only the recipient's domain for a test email.

### For the developer

- Code: `addons/ea_platform_admin/services/platform_mail.py` (pure: the rules, both APIs, the simulation, one pass), `models/firm_platform_mail.py` (the firm's states, the watch, the heartbeat), `wizard/settings_mail.py`, `wizard/platform_mail.py`. Firm side: `addons/ea_audit_firm_agent/services/recipients.py` and `models/ir_mail_server.py` (reply address, practice recipient gate). Practice computer: `deploy/practice/practice-apply-desired.sh`, `practice-guard.sh`.
- API calls: MailerSend `GET/POST /v1/domains`, `GET /v1/domains/{id}`, `GET /v1/domains/{id}/dns-records`, `GET /v1/domains/{id}/verify`, `GET/POST /v1/domains/{id}/smtp-users`, `DELETE /v1/domains/{id}/smtp-users/{user}`, `DELETE /v1/domains/{id}`, `POST /v1/email`; Cloudflare `GET /user/tokens/verify`, `GET /zones?name=`, `GET/POST/PATCH/DELETE /zones/{zone}/dns_records`.
- SIMULATION: both services are faked (no network, no token); tests never reach the network.
- To check before the first real firm: that MailerSend's DNS hostnames are full names (as its documentation shows), and that the verify answer reads as the code expects (`message` "The domain is verified.", or `data.spf` and `data.dkim` true).
