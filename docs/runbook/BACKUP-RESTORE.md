# Sauvegardes et restauration / Backups and restore

[Français](#français) · [English](#english)

## Français

**Ces scripts n'ont tourné qu'en mode essai :** aucune sauvegarde réelle, aucun vrai test de restauration n'a encore eu lieu sur cette plateforme.

### Ce qui se passe seul

| Quand | Quoi |
|---|---|
| Chaque nuit, à partir de 02:30 | Base et fichiers du cabinet, chiffrés par `restic`, envoyés à **son** stockage avec **sa** clé. La copie en clair est effacée dès l'envoi confirmé. |
| Chaque dimanche, à partir de 04:30 | Test de restauration : la dernière sauvegarde est rapatriée, ses empreintes contrôlées, la base restaurée sous un autre nom et vérifiée, puis tout est effacé. La base en service n'est pas touchée. |
| Avant chaque mise à jour | Une sauvegarde, sans laquelle la mise à jour n'a pas lieu. |

Conservation : 14 quotidiennes, 8 hebdomadaires, 12 mensuelles ; 90 jours pour celles d'avant mise à jour. **À confirmer** par rapport aux obligations de conservation des dossiers d'audit, qui peuvent aller bien au-delà : c'est une décision à prendre avec chaque cabinet.

### Les alertes

| Sur le tableau | Signification |
|---|---|
| Orange « Sauvegarde en retard » | Plus de 26 heures |
| Rouge « Sauvegarde manquée » | Plus de 50 heures |
| Rouge « La dernière sauvegarde a échoué » | Le script a échoué |
| Orange / rouge « Test de restauration » | Plus de 8 / 15 jours, ou échec |

Le contrôle voit l'absence, pas seulement l'échec : un serveur mort cesse d'envoyer et passe au rouge en 2 heures. Filtres : « Sauvegarde manquée ou en échec », « Test de restauration manqué ou en échec ».

### La clé de sauvegarde : le point à ne pas oublier

Elle est sur le serveur du cabinet et dans votre coffre, **jamais sur le contrôle**. Si le serveur disparaît et que vous ne l'avez pas : **les sauvegardes sont perdues, sans recours.** Le cabinet reste orange tant que vous n'avez pas confirmé l'avoir mise au coffre.

### Restaurer un cabinet sur le même serveur

Après un accès d'urgence enregistré, et idéalement avec votre technicien :

```
ssh -i ~/.ssh/auditisa-SLUG root@SLUG.auditisa.com
set -a; . /etc/auditisa-firm/secrets/s3.env; set +a
export RESTIC_PASSWORD_FILE=/etc/auditisa-firm/secrets/restic.key
restic snapshots
restic restore <id> --target /var/tmp/restauration
systemctl stop odoo
sudo -u postgres psql -c 'ALTER DATABASE firm_SLUG RENAME TO firm_SLUG_avant'
sudo -u postgres createdb -O odoo -E UTF8 -T template0 --lc-collate=C --lc-ctype=C.UTF-8 firm_SLUG
sudo -u postgres pg_restore --no-owner --role=odoo -d firm_SLUG < /var/tmp/restauration/.../db.dump
mv /var/lib/odoo/filestore/firm_SLUG /var/lib/odoo/filestore/firm_SLUG_avant
tar -xzf /var/tmp/restauration/.../filestore.tar.gz -C /var/lib/odoo/filestore
chown -R odoo:odoo /var/lib/odoo/filestore/firm_SLUG
systemctl start odoo
```

Dans `firm_SLUG`, remplacez les tirets de l'identifiant par des `_`. Vérifiez, puis effacez `/var/tmp/restauration` et, plus tard, la base et les fichiers `_avant`.

### Serveur perdu

Il faut : la clé de sauvegarde (votre coffre), le nom du bucket (fiche du cabinet, « Stockage ») et une clé d'accès à ce bucket, que vous créez chez Wasabi : Users > `auditisa-firm-<identifiant>` > Access Keys > Create Access Key (voir WASABI.md). Créez le serveur à neuf, puis restaurez avec les commandes ci-dessus. **Le passage par un nouveau serveur n'est pas encore automatisé** et n'a jamais été répété : faites-le une fois à blanc sur le cabinet fictif.

## English

**These scripts have only run in dry-run mode:** no real backup and no real restore test has yet happened on this platform.

### What happens by itself

| When | What |
|---|---|
| Every night, from 02:30 | The firm's database and files, encrypted by `restic`, sent to **its** storage with **its** key. The plain copy is erased once the upload is confirmed. |
| Every Sunday, from 04:30 | Restore test: the latest backup is fetched, its digests checked, the database restored under another name and checked, then all is erased. The live database is not touched. |
| Before each update | One backup, without which the update does not happen. |

Retention: 14 daily, 8 weekly, 12 monthly; 90 days for pre-update ones. **To be confirmed** against the retention duties on audit files, which can run much longer: a decision to take with each firm.

### The alerts

| On the board | Meaning |
|---|---|
| Orange "Backup late" | Over 26 hours |
| Red "Backup missed" | Over 50 hours |
| Red "The last backup failed" | The script failed |
| Orange / red "Restore test" | Over 8 / 15 days, or failed |

The control plane sees absence as well as failure: a dead server stops sending and turns red within 2 hours. Filters: "Backup missed or failed", "Restore test missed or failed".

### The backup key: the point not to miss

It is on the firm's server and in your safe, **never on the control plane**. If the server is lost and you do not have it, **the backups are gone, with no remedy.** The firm stays orange until you confirm having put it in the safe.

### Restoring a firm on the same server

After recording a break-glass access, and ideally with your technician:

```
ssh -i ~/.ssh/auditisa-SLUG root@SLUG.auditisa.com
set -a; . /etc/auditisa-firm/secrets/s3.env; set +a
export RESTIC_PASSWORD_FILE=/etc/auditisa-firm/secrets/restic.key
restic snapshots
restic restore <id> --target /var/tmp/restore
systemctl stop odoo
sudo -u postgres psql -c 'ALTER DATABASE firm_SLUG RENAME TO firm_SLUG_before'
sudo -u postgres createdb -O odoo -E UTF8 -T template0 --lc-collate=C --lc-ctype=C.UTF-8 firm_SLUG
sudo -u postgres pg_restore --no-owner --role=odoo -d firm_SLUG < /var/tmp/restore/.../db.dump
mv /var/lib/odoo/filestore/firm_SLUG /var/lib/odoo/filestore/firm_SLUG_before
tar -xzf /var/tmp/restore/.../filestore.tar.gz -C /var/lib/odoo/filestore
chown -R odoo:odoo /var/lib/odoo/filestore/firm_SLUG
systemctl start odoo
```

In `firm_SLUG`, write the slug's hyphens as `_`. Check, then erase `/var/tmp/restore` and, later, the `_before` database and files.

### Server lost

You need: the backup key (your safe), the bucket's name (the firm's page, "Storage") and an access key to that bucket, which you make at Wasabi: Users > `auditisa-firm-<slug>` > Access Keys > Create Access Key (see WASABI.md). Build a new server, then restore with the commands above. **Moving to a new server is not automated yet** and has never been rehearsed: do it once as a dry run on the made-up firm.
