# Le support des cabinets / Supporting the firms

[Français](#français) · [English](#english)

## Français

Trois moyens, depuis la salle de contrôle (l'Odoo d'administration), de voir ce qui arrive à un cabinet. **Décisions du propriétaire (2026-11-07) :** l'opérateur a un accès prévu aux serveurs des cabinets ; une visite de support se fait **sans approbation du cabinet**, mais elle est **numérotée, conservée et en lecture seule**.

**État réel :** tout a tourné sur des bases jetables et dans l'Odoo d'administration en SIMULATION. Rien sur un vrai serveur de cabinet. Voir « Ce qui est prouvé ».

### 1. Les erreurs techniques

Le serveur du cabinet compte ses erreurs techniques (celles qu'Odoo journalise comme erreur, avec trace) et les envoie dans son heartbeat, **sous forme de codes seulement** : le module, l'écran (le nom technique du modèle, seulement s'il existe), le type d'erreur (le nom de la classe), l'heure, le nombre. Jamais le message, jamais la trace, jamais une valeur : ce sont eux qui contiennent les noms de clients et les montants. Un test place des données de client dans une erreur et vérifie qu'il n'en sort rien.

Plateforme > Support > Erreurs techniques, et l'onglet « Support » de la fiche. Une erreur dans les dernières 24 heures met le cabinet à l'orange.

### 2. « Signaler un problème »

Dans le menu utilisateur de chaque écran du cabinet. L'utilisateur écrit un sujet et un message ; le formulaire lui dit que cela part chez l'opérateur d'AuditISA, pas chez son cabinet, et **lui demande de ne pas écrire de détails de clients**. Le message part par un canal signé à part, pas par le heartbeat, dont la règle « des chiffres et des codes, jamais de texte » ne change pas.

Plateforme > Support > Problèmes signalés : **En cours**, **Fermer**, et une **réponse** que l'utilisateur voit dans « Mes problèmes signalés » (au plus tard 15 minutes après, ou tout de suite avec « Vérifier la réponse »). L'opérateur voit le texte et une référence, pas le nom de l'utilisateur. Un problème non fermé met le cabinet à l'orange.

### 3. La visite de support

Sur la fiche du cabinet : **Visite de support**. Un motif (obligatoire), une durée (60 minutes par défaut, 240 au plus).

1. La plateforme affiche **une fois** un lien de connexion. Elle n'en garde que l'empreinte. Copiez-le.
2. Au prochain heartbeat, la réponse signée donne au serveur du cabinet le numéro de la visite, la durée, l'empreinte, votre nom et le motif. Le script root du cabinet revérifie tout et ouvre la visite.
3. Le lien vous connecte au cabinet sous le compte **« AuditISA support (operator, not a firm user) »**, jusqu'à la fin de la visite. Ce compte n'a aucun mot de passe connu.
4. L'administrateur du cabinet est **prévenu à l'écran**. Il voit la visite dans Configuration > Visites de support et peut **y mettre fin** à tout moment.
5. À l'heure, la visite se ferme seule : le compte est désactivé et ses sessions tombent.

**En lecture seule.** Le compte de support ouvre tous les écrans que voient les utilisateurs du cabinet, et **ne peut rien créer, modifier, supprimer, signer, déposer, exporter ni envoyer**. C'est le serveur qui le refuse, pour tout modèle et même dans le code qui passe en superutilisateur, et les adresses d'export, de téléchargement, d'impression et de dépôt lui sont fermées. Un test essaie chaque sorte d'écriture sous ce compte.

**Numérotée et conservée.** Chaque visite est une fiche numérotée qui ne se modifie ni ne se supprime : son numéro, l'opérateur, le motif, le début et la fin, la version du cabinet, et la liste des écrans et des fiches ouverts (identifiants seulement, aucun contenu). L'opérateur la lit dans Plateforme > Support > Visites de support ; l'administrateur du cabinet la lit dans son outil. Le journal d'accès du serveur et le journal de la plateforme l'enregistrent aussi. Ce journal d'accès n'est plus un écran du cabinet depuis le 7 novembre 2026 (décision du propriétaire) : il reste collecté sur le serveur, pour la salle de contrôle et la trace du support.

### Ce qui est prouvé, ce qui ne l'est pas

| | |
|---|---|
| **Couvert par des tests** (bases jetables `ci_tenants*`) | Erreurs : seuls les codes sortent, les données de client plantées n'apparaissent ni dans le fichier ni dans le heartbeat, la plateforme refuse un heartbeat dont une erreur porte du texte. Problèmes : signature propre au canal, refus d'une autre signature ou d'un ancien horodatage, une seule fois par référence, réponse rendue à l'utilisateur, un utilisateur ne voit que les siens. Visite : lien gardé en empreinte seulement, connexion par le lien seulement, aucune par mot de passe, chaque sorte d'écriture refusée au compte de support, export/contenu/impression refusés, trace des écrans par identifiants, fiche et trace impossibles à modifier ou supprimer, fin par l'administrateur, par la plateforme ou à l'heure |
| **Simulé** | Dans l'Odoo d'administration, les cabinets sont simulés : un cabinet simulé ouvre et ferme la visite tout de suite |
| **Jamais essayé** | Un vrai serveur de cabinet ; le lien à travers nginx et HTTPS ; la notification à l'écran sur un vrai navigateur de cabinet ; le minuteur de 5 minutes de root |

## English

Three ways, from the control room (the admin Odoo), to see what is happening to a firm. **The owner's decisions (2026-11-07):** the operator has provisioned access to the firms' servers; a support visit needs **no approval from the firm**, but it is **numbered, kept for good and read-only**.

**Where this really stands:** all of it has run on throwaway databases and in the admin Odoo in SIMULATION. Nothing on a real firm server. See "What is proved".

### 1. Technical errors

The firm's server counts its technical errors (those Odoo logs as an error, with a traceback) and sends them in its heartbeat **as codes only**: the addon, the screen (the model's technical name, only if it exists), the error type (the class name), the time, the count. Never the message, never the traceback, never a value: those are what hold client names and amounts. A test plants client data in an error and checks that none of it leaves.

Platform > Support > Technical errors, and the firm page's "Support" tab. An error in the last 24 hours turns the firm amber.

### 2. "Report a problem"

In the user menu of every screen of the firm. The user writes a subject and a message; the form tells them it goes to AuditISA's operator, not to their firm, and **asks them not to write client details**. The message travels on a separate signed channel, not in the heartbeat, whose rule (figures and codes, never text) does not change.

Platform > Support > Reported problems: **In progress**, **Close**, and a **reply** the user sees in "My reported problems" (within 15 minutes, or at once with "Check for a reply"). The operator sees the text and a reference, not the user's name. A problem not closed turns the firm amber.

### 3. The support visit

On the firm's page: **Support visit**. A reason (required) and a length (60 minutes by default, 240 at most).

1. The platform shows a sign-in link **once**. It keeps only its fingerprint. Copy it.
2. At the next heartbeat, the signed answer gives the firm's server the visit's number, its length, the fingerprint, your name and the reason. The firm's root script checks it all again and opens the visit.
3. The link signs you in to the firm as **"AuditISA support (operator, not a firm user)"** until the visit ends. That account has no password anyone knows.
4. The firm's administrator is **told on screen**. They see the visit in Settings > Support visits and can **end it** at any time.
5. When time is up the visit closes by itself: the account is switched off and its sessions end.

**Read-only.** The support account opens every screen the firm's users see, and **cannot create, change, delete, sign, upload, export or send anything**. The server refuses it, for every model and even in code that runs as superuser, and the export, download, print and upload addresses are closed to it. A test tries each kind of write as that account.

**Numbered and kept.** Each visit is a numbered record that cannot be edited or deleted: its number, the operator, the reason, start and end, the firm's release, and the list of screens and records opened (identifiers only, no content). The operator reads it in Platform > Support > Support visits; the firm's administrator reads it in their tool. The server's access log and the platform log record it too. Since 7 November 2026 (owner's ruling) that access log is no longer a screen of the firm's: it is still collected on the server, for the control room and the support trail.

### What is proved, what is not

| | |
|---|---|
| **Covered by tests** (throwaway `ci_tenants*` databases) | Errors: only codes leave, planted client data appears neither in the file nor in the heartbeat, the platform refuses a heartbeat whose error carries text. Problems: the channel's own signature, another signature or an old timestamp refused, once per reference, the reply back to the user, a user sees only their own. Visit: the link kept as a fingerprint only, sign-in by the link only and never by password, each kind of write refused to the support account, export/content/print refused, screens traced by identifiers, record and trail impossible to change or delete, ended by the administrator, by the platform or when time is up |
| **Simulated** | In the admin Odoo the firms are simulated: a simulated firm opens and closes the visit at once |
| **Never tried** | A real firm server; the link through nginx and HTTPS; the on-screen notice in a real firm's browser; root's 5-minute timer |
