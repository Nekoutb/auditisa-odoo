# La sortie d'un cabinet / Offboarding a firm

[Français](#français) · [English](#english)

## Français

Seul le propriétaire peut lancer une sortie. Elle se fait en deux temps séparés par la durée de conservation, et chacun demande de taper l'identifiant du cabinet. **N'a tourné qu'en simulation.**

### Premier temps : l'export

1. Fiche du cabinet > **Sortie du cabinet**. Indiquez le motif et la durée de conservation (90 jours par défaut, 30 au minimum), tapez l'identifiant. Rien n'est détruit. Le cabinet passe à « Sortie en cours ».
2. Dans les 20 minutes environ, le serveur du cabinet exporte ses données : base, fichiers et empreintes. Le fichier reste **sur le serveur du cabinet**, avec une copie chiffrée dans son stockage ; le contrôle ne reçoit que son empreinte.
3. Enregistrez un accès d'urgence, récupérez le fichier et vérifiez-le :
   ```
   scp -i ~/.ssh/auditisa-SLUG root@SLUG.auditisa.com:/var/lib/auditisa-firm/exports/SLUG-*.tar.gz .
   sha256sum SLUG-*.tar.gz
   ```
   L'empreinte doit être celle de l'onglet « Sortie ».
4. Remettez le fichier au cabinet par un moyen sûr. Le cabinet doit vérifier qu'il peut l'exploiter : c'est une sauvegarde technique (base PostgreSQL et fichiers), pas un rapport lisible. Prévoyez l'accompagnement.
5. Cliquez **Export remis au cabinet**.

Le serveur reste en marche pendant la conservation, et donc facturé. Vous pouvez convenir d'exports lisibles (Excel) avant de lancer la sortie.

### Second temps : la destruction

Le bouton **Détruire le serveur** n'apparaît qu'une fois réunis : export terminé, remise confirmée, durée de conservation écoulée.

1. Tapez l'identifiant, **Continuer**.
2. Tapez `DESTROY`, **Détruire définitivement**.

Sont supprimés : le serveur et ses disques, son stockage **avec toutes ses sauvegardes**, l'adresse DNS, le pare-feu, la clé SSH chez le fournisseur. La fiche et son journal restent, sans aucun jeton, et l'identifiant ne sera jamais réattribué.

Si la destruction est incomplète, un message rouge le dit, le cabinet reste en sortie et passe au rouge « SERVEUR ORPHELIN » : voir INCIDENT.md.

### Ensuite

Effacez la clé SSH et la clé de sauvegarde de ce cabinet de votre coffre, et l'export de votre ordinateur. Les obligations de conservation des dossiers d'audit restent à la charge du cabinet ; faites-le-lui confirmer par écrit.

## English

Only the owner can start an exit. It has two stages separated by the retention period, and each asks you to type the firm's slug. **Has only run as a simulation.**

### First stage: the export

1. Firm's page > **Firm's exit**. Give the reason and the retention period (90 days by default, 30 at least), type the slug. Nothing is destroyed. The firm shows "Leaving".
2. Within about 20 minutes the firm's server exports its data: database, files and digests. The file stays **on the firm's server**, with an encrypted copy in its storage; the control plane receives only its digest.
3. Record a break-glass access, fetch the file and check it:
   ```
   scp -i ~/.ssh/auditisa-SLUG root@SLUG.auditisa.com:/var/lib/auditisa-firm/exports/SLUG-*.tar.gz .
   sha256sum SLUG-*.tar.gz
   ```
   The digest must match the "Exit" tab.
4. Hand the file to the firm by a safe means. The firm should check it can use it: this is a technical backup (PostgreSQL database and files), not a readable report. Plan for support.
5. Click **Export handed to the firm**.

The server keeps running during retention, and so keeps being billed. You can agree readable exports (Excel) before starting the exit.

### Second stage: destruction

The **Destroy the server** button appears only once: export finished, handover confirmed, retention period over.

1. Type the slug, **Continue**.
2. Type `DESTROY`, **Destroy for good**.

Removed: the server and its disks, its storage **with all its backups**, the DNS address, the firewall, the SSH key at the provider. The firm's record and its log remain, with no token, and the slug is never given again.

If destruction is incomplete, a red message says so, the firm stays in exit and turns red "ORPHAN SERVER": see INCIDENT.md.

### Afterwards

Erase this firm's SSH key and backup key from your safe, and the export from your computer. The retention duties on audit files stay with the firm; have it confirm that in writing.
