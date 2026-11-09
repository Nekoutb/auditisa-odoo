# Wasabi : le stockage des sauvegardes et des versions / Wasabi: storage for backups and releases

[Français](#français) · [English](#english)

## Français

### En deux mots

Wasabi est un service qui garde des fichiers en ligne. La plateforme s'en sert pour deux choses :

- **les sauvegardes de chaque cabinet** : chaque cabinet a son propre « bucket » (un dossier en ligne) et sa propre clé, qui n'ouvre que ce dossier-là. Les sauvegardes sont chiffrées sur le serveur du cabinet avant d'être envoyées : Wasabi ne voit que du contenu illisible ;
- **les versions du logiciel** : un dossier privé, `auditisa-releases-...`, d'où les serveurs des cabinets téléchargent les mises à jour. Ils ne reçoivent aucune clé pour cela : la console leur donne, à chaque fois, une adresse de téléchargement qui expire après quelques heures. La signature de chaque version reste la vraie garantie.

Vultr reste le fournisseur des serveurs. Le stockage objet de Vultr n'est plus utilisé.

### Les mots utilisés

| Mot | Ce que c'est |
|---|---|
| **Bucket** | Un dossier en ligne chez Wasabi. |
| **Utilisateur IAM** | Une « identité » secondaire de votre compte Wasabi, avec ses propres droits. Ce n'est pas une personne : c'est la console qui s'en sert. |
| **Politique (policy)** | La liste de ce qu'un utilisateur a le droit de faire. Vous la collez telle quelle, sans la modifier. |
| **Clé d'accès (access key) et clé secrète (secret key)** | Le couple identifiant / mot de passe de cet utilisateur, pour un programme. La clé secrète ne s'affiche **qu'une seule fois**. |
| **Région** | Le centre de données où sont rangés les buckets. Exemple : `eu-central-1` = Amsterdam. |

### Ce qu'il faut choisir : la région

Votre compte Wasabi n'est pas lié à une région ; chaque bucket l'est. Choisissez une région, par exemple **`eu-central-1` (Amsterdam)**, et utilisez **la même partout** : pour le bucket des versions (étape 5) et dans Plateforme > Réglages. Si vous en choisissez une autre, remplacez `eu-central-1` par son code dans ce qui suit.

### Le coût (à confirmer sur wasabi.com)

- Paiement à l'usage : **environ 7 USD par To et par mois**, sans frais de téléchargement.
- **Minimum de facturation : 1 To pour tout le compte** (environ 7 USD par mois), quel que soit le volume réel.
- **Un fichier effacé est facturé comme s'il avait été gardé 90 jours.** Les sauvegardes quotidiennes sont remplacées chaque jour : comptez donc, par cabinet, jusqu'à environ trois mois de fichiers effacés en plus de ce qui est gardé. Détruire un cabinet ne fait pas cesser sa facturation tout de suite : les 90 jours courent encore.
- Pour un cabinet, de l'ordre de **1 USD par mois** (une centaine de Go). Le minimum de 1 To couvre largement les premiers cabinets.

### Ce que vous faites, une seule fois, sur console.wasabisys.com

Connectez-vous à **https://console.wasabisys.com** avec votre compte principal (activez la double authentification si ce n'est pas fait : menu de votre compte > Settings > Security / MFA). Les noms des boutons peuvent varier un peu selon la version de l'écran.

**Étape 1. Créer la politique `auditisa-console-policy`**

1. Dans le menu de gauche, cliquez sur **Policies** (Politiques).
2. Cliquez sur **Create Policy** (Créer une politique).
3. **Policy Name** : tapez exactement `auditisa-console-policy`.
4. **Description** : par exemple `Console AuditISA : buckets et utilisateurs auditisa- seulement`.
5. Dans la grande zone **Policy Document** (ou Policy Editor), effacez ce qui s'y trouve, puis collez **tout** le texte ci-dessous, de la première accolade `{` à la dernière `}`, sans rien changer :

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListBucketNames",
      "Effect": "Allow",
      "Action": "s3:ListAllMyBuckets",
      "Resource": "*"
    },
    {
      "Sid": "FirmBuckets",
      "Effect": "Allow",
      "Action": [
        "s3:CreateBucket",
        "s3:DeleteBucket",
        "s3:ListBucket",
        "s3:GetBucketLocation",
        "s3:PutBucketPolicy"
      ],
      "Resource": "arn:aws:s3:::auditisa-fw-*"
    },
    {
      "Sid": "EmptyFirmBucketsBeforeDeletion",
      "Effect": "Allow",
      "Action": "s3:DeleteObject",
      "Resource": "arn:aws:s3:::auditisa-fw-*/*"
    },
    {
      "Sid": "ReleasesBucket",
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket",
        "s3:GetBucketLocation"
      ],
      "Resource": "arn:aws:s3:::auditisa-releases-*"
    },
    {
      "Sid": "ReleasesFiles",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject"
      ],
      "Resource": "arn:aws:s3:::auditisa-releases-*/*"
    },
    {
      "Sid": "FirmUsersAndTheirKeys",
      "Effect": "Allow",
      "Action": [
        "iam:CreateUser",
        "iam:GetUser",
        "iam:DeleteUser",
        "iam:CreateAccessKey",
        "iam:DeleteAccessKey",
        "iam:ListAccessKeys"
      ],
      "Resource": [
        "arn:aws:iam::*:user/auditisa/auditisa-firm-*",
        "arn:aws:iam::*:user/auditisa-firm-*"
      ]
    }
  ]
}
```

6. Cliquez sur **Create Policy** (ou **Save**). Si Wasabi affiche une erreur sur le texte, ne le corrigez pas vous-même : copiez le message et transmettez-le à votre technicien.

Le même texte est dans le dépôt : `deploy/control-plane/wasabi-console-policy.json`.

**Étape 2. Créer l'utilisateur `auditisa-console`, accès programme seulement**

1. Menu de gauche : **Users** (Utilisateurs), puis **Create User** (Créer un utilisateur).
2. **Username** : tapez exactement `auditisa-console`.
3. **Type of access** (type d'accès) : cochez **Programmatic (create API key)** (accès programme, crée une clé API). **Ne cochez pas** **Console (have a password)** : cet utilisateur n'a pas de mot de passe et ne peut pas ouvrir l'écran de Wasabi.
4. Cliquez sur **Next** (Suivant). À l'écran **Groups** (Groupes), n'ajoutez rien, puis **Next**.

**Étape 3. Lui attacher la politique**

1. À l'écran **Policies** de la création, tapez `auditisa-console-policy` dans la recherche et sélectionnez-la. **N'en sélectionnez aucune autre** (surtout pas `AdministratorAccess` ni `WasabiFullAccess`).
2. **Next**, vérifiez le résumé (nom `auditisa-console`, accès programme seulement, une seule politique `auditisa-console-policy`), puis **Create User**.
3. Si vous aviez sauté cet écran : **Users** > cliquez sur `auditisa-console` > onglet **Policies** > **Attach Policy** (attacher) > choisissez `auditisa-console-policy` > **Attach**.

**Étape 4. Copier la clé d'accès et la clé secrète**

1. Juste après la création, une fenêtre affiche l'**Access Key** (clé d'accès, une suite de lettres majuscules et de chiffres) et la **Secret Key** (clé secrète, plus longue). **La clé secrète ne sera plus jamais affichée.**
2. Cliquez sur **Download CSV** (ou **Copy Keys To Clipboard**) et rangez les deux valeurs **dans votre coffre de mots de passe**, dans une fiche nommée « Wasabi auditisa-console ». Ne les envoyez pas par courriel ni par messagerie, ne les mettez pas dans un document partagé ; effacez le fichier CSV téléchargé une fois les valeurs au coffre.
3. Votre technicien les déposera sur le serveur de la console (voir plus bas), directement depuis votre coffre.
4. Si vous avez fermé la fenêtre trop tôt : **Users** > `auditisa-console` > onglet **Access Keys** > supprimez la clé > **Create Access Key** pour en obtenir une nouvelle.

**Étape 5. Créer le bucket des versions**

1. Menu de gauche : **Buckets**, puis **Create Bucket**.
2. **Bucket Name** : `auditisa-releases-` suivi de 12 lettres minuscules et chiffres pris au hasard (par exemple tirés de votre gestionnaire de mots de passe, sans majuscule ni symbole). Exemple de forme : `auditisa-releases-k3j4h5g6f7d8` (n'utilisez pas celui-ci).
3. **Region** : la région choisie (`eu-central-1`, Amsterdam, dans nos exemples).
4. Laissez tout le reste par défaut : pas de versioning, pas d'Object Lock, **pas d'accès public**. **Create Bucket**.
5. Notez le nom exact du bucket dans votre coffre et donnez-le à votre technicien : il va dans Plateforme > Réglages.

### Ce que fait le technicien (serveur de la console)

Les deux valeurs vont dans deux fichiers que seul root peut lire, comme le jeton Vultr. Elles ne vont **jamais** dans `odoo.conf`, dans la base ou dans un écran, et ne sont jamais affichées :

```
install -m 600 /dev/null /etc/auditisa-platform/wasabi.key
install -m 600 /dev/null /etc/auditisa-platform/wasabi.secret
# coller la clé d'accès, puis Ctrl-D (rien ne s'affiche, rien ne reste dans l'historique)
cat > /etc/auditisa-platform/wasabi.key
# coller la clé secrète, puis Ctrl-D
cat > /etc/auditisa-platform/wasabi.secret
systemctl restart odoo
```

`install-control-plane.sh` déclare ces deux fichiers au service (`LoadCredential=wasabi-key` et `wasabi-secret`) et crée des fichiers vides s'ils manquent, pour que la console démarre en simulation. Ensuite, Plateforme > Réglages : **Région Wasabi** (`eu-central-1`), **Bucket des versions**, et l'adresse Wasabi seulement si elle n'est pas celle de la région (`s3.<région>.wasabisys.com`).

### Ce que la console fait seule, pour chaque cabinet

- **À la mise en service :** un bucket `auditisa-fw-<identifiant>-<12 caractères au hasard>` dans la région choisie, un utilisateur `auditisa-firm-<identifiant>` (sous le chemin `/auditisa/`) **sans aucun droit propre**, une règle sur le bucket qui ouvre **ce bucket seul** à **cet utilisateur seul** (lister, lire, écrire, effacer des fichiers ; rien d'autre), puis une clé. La clé part vers le serveur du cabinet dans son texte de premier démarrage, comme avant, et n'est gardée nulle part sur la console.
- **À la destruction** (après la durée de conservation de la sortie, voir OFFBOARDING.md) : la clé, l'utilisateur, toutes les sauvegardes, puis le bucket. Les 90 jours de facturation minimale de Wasabi courent encore.
- **À chaque mise à jour :** deux adresses de téléchargement signées (la version et sa signature), valables 6 heures, renouvelées à chaque heartbeat ; 3 jours pour le premier démarrage.

### Ce que la clé de la console peut et ne peut pas faire

Elle peut : voir les **noms** de tous les buckets du compte (pas leur contenu) ; créer, vider et supprimer les buckets `auditisa-fw-*` et y écrire leur règle d'accès ; lire et déposer des fichiers dans les buckets `auditisa-releases-*` ; créer et supprimer les utilisateurs `auditisa-firm-*` et leurs clés.

Elle ne peut pas : lire, modifier ou supprimer vos autres buckets ; toucher à vos autres utilisateurs ; se donner une seconde clé ou plus de droits ; écrire ou attacher une politique à un utilisateur ; lire une sauvegarde d'un cabinet. Des tests le vérifient sur le texte de la politique (`services/tests/test_wasabi.py`).

Si elle est volée : au pire, quelqu'un peut supprimer les sauvegardes des cabinets, ou s'ouvrir un bucket `auditisa-fw-*` en y écrivant une règle ; il n'y trouverait que des sauvegardes chiffrées avec la clé de chaque cabinet, qui n'est jamais sur la console. **Réaction :** Wasabi > Users > `auditisa-console` > Access Keys > supprimez la clé, puis créez-en une nouvelle (étape 4). Pour une séparation complète, un compte Wasabi réservé à la plateforme reste possible.

### Serveur d'un cabinet perdu

Pour restaurer sur un nouveau serveur, il faut la clé de sauvegarde (votre coffre) et une clé d'accès au bucket : Wasabi > Users > `auditisa-firm-<identifiant>` > Access Keys > **Create Access Key**. Le nom du bucket est sur la fiche du cabinet (Stockage). Supprimez cette clé une fois la restauration faite.

### Ce que seul un premier essai réel confirmera

Le code a été écrit d'après la documentation d'AWS, que Wasabi suit, et testé hors ligne (signatures comparées aux exemples publiés par AWS). Il n'a **jamais parlé à Wasabi**. Au premier cabinet fictif (PREREQUISITES.md, étape 8), le technicien vérifie :

1. que Wasabi accepte la politique telle quelle, en particulier `arn:aws:iam::*:user/...` (le `*` à la place du numéro de compte) ; sinon, remplacer `*` par le numéro du compte (menu du compte > Settings) ;
2. que la console crée le bucket, l'utilisateur, la règle du bucket et la clé (onglet de mise en service) ;
3. **le point principal :** que la clé du cabinet, qui n'a aucune politique à elle, peut écrire dans son bucket grâce à la seule règle du bucket (`firm-backup` doit réussir, puis `firm-restore-test`). Si Wasabi refuse, il faudra donner aux utilisateurs des cabinets une politique propre, ce qui demande d'élargir la politique de la console : à rediscuter avant ;
4. qu'avec la clé du cabinet A, `restic` ne peut ni lire ni lister le bucket du cabinet B (depuis le serveur A, en changeant `RESTIC_REPOSITORY` vers le bucket de B : doit échouer) ;
5. que le serveur télécharge la version par l'adresse signée au premier démarrage et lors d'une mise à jour ;
6. que la destruction du cabinet fictif supprime la clé, l'utilisateur, les fichiers et le bucket.

## English

### In short

Wasabi is a service that keeps files online. The platform uses it for two things:

- **each firm's backups**: each firm has its own "bucket" (an online folder) and its own key, which opens that folder only. Backups are encrypted on the firm's server before they leave: Wasabi only sees unreadable content;
- **the software releases**: a private folder, `auditisa-releases-...`, from which the firms' servers download updates. They get no key for it: each time, the console gives them a download address that expires after a few hours. Each release's signature remains the real guarantee.

Vultr stays the server provider. Vultr's object storage is no longer used.

### The words used

| Word | What it is |
|---|---|
| **Bucket** | An online folder at Wasabi. |
| **IAM user** | A secondary "identity" of your Wasabi account, with its own rights. Not a person: the console uses it. |
| **Policy** | The list of what a user may do. You paste it as it is, unchanged. |
| **Access key and secret key** | That user's login and password, for a program. The secret key is shown **only once**. |
| **Region** | The data centre where buckets are kept. Example: `eu-central-1` = Amsterdam. |

### What to choose: the region

Your Wasabi account is not tied to a region; each bucket is. Choose a region, for example **`eu-central-1` (Amsterdam)**, and use **the same one everywhere**: for the releases bucket (step 5) and in Platform > Settings. If you choose another, replace `eu-central-1` with its code below.

### The cost (to confirm on wasabi.com)

- Pay as you go: **about USD 7 per TB per month**, no download fees.
- **Minimum billing: 1 TB for the whole account** (about USD 7 a month), whatever is really stored.
- **A deleted file is billed as if it had been kept 90 days.** Daily backups are replaced every day: so count, per firm, up to about three months of deleted files on top of what is kept. Destroying a firm does not stop its billing at once: the 90 days still run.
- For one firm, about **USD 1 a month** (a hundred GB or so). The 1 TB minimum easily covers the first firms.

### What you do, once, on console.wasabisys.com

Sign in at **https://console.wasabisys.com** with your main account (switch on two-factor login if not done yet: your account's menu > Settings > Security / MFA). Button names may differ slightly with the version of the screen.

**Step 1. Create the policy `auditisa-console-policy`**

1. In the left menu, click **Policies**.
2. Click **Create Policy**.
3. **Policy Name**: type exactly `auditisa-console-policy`.
4. **Description**: for example `AuditISA console: auditisa- buckets and users only`.
5. In the large **Policy Document** (or Policy Editor) box, erase what is there, then paste **all** the text below, from the first brace `{` to the last `}`, changing nothing:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListBucketNames",
      "Effect": "Allow",
      "Action": "s3:ListAllMyBuckets",
      "Resource": "*"
    },
    {
      "Sid": "FirmBuckets",
      "Effect": "Allow",
      "Action": [
        "s3:CreateBucket",
        "s3:DeleteBucket",
        "s3:ListBucket",
        "s3:GetBucketLocation",
        "s3:PutBucketPolicy"
      ],
      "Resource": "arn:aws:s3:::auditisa-fw-*"
    },
    {
      "Sid": "EmptyFirmBucketsBeforeDeletion",
      "Effect": "Allow",
      "Action": "s3:DeleteObject",
      "Resource": "arn:aws:s3:::auditisa-fw-*/*"
    },
    {
      "Sid": "ReleasesBucket",
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket",
        "s3:GetBucketLocation"
      ],
      "Resource": "arn:aws:s3:::auditisa-releases-*"
    },
    {
      "Sid": "ReleasesFiles",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject"
      ],
      "Resource": "arn:aws:s3:::auditisa-releases-*/*"
    },
    {
      "Sid": "FirmUsersAndTheirKeys",
      "Effect": "Allow",
      "Action": [
        "iam:CreateUser",
        "iam:GetUser",
        "iam:DeleteUser",
        "iam:CreateAccessKey",
        "iam:DeleteAccessKey",
        "iam:ListAccessKeys"
      ],
      "Resource": [
        "arn:aws:iam::*:user/auditisa/auditisa-firm-*",
        "arn:aws:iam::*:user/auditisa-firm-*"
      ]
    }
  ]
}
```

6. Click **Create Policy** (or **Save**). If Wasabi shows an error about the text, do not fix it yourself: copy the message and pass it to your technician.

The same text is in the repository: `deploy/control-plane/wasabi-console-policy.json`.

**Step 2. Create the user `auditisa-console`, program access only**

1. Left menu: **Users**, then **Create User**.
2. **Username**: type exactly `auditisa-console`.
3. **Type of access**: tick **Programmatic (create API key)**. **Do not tick** **Console (have a password)**: this user has no password and cannot open Wasabi's screens.
4. Click **Next**. On the **Groups** screen, add nothing, then **Next**.

**Step 3. Attach the policy to it**

1. On the creation's **Policies** screen, type `auditisa-console-policy` in the search box and select it. **Select no other** (above all not `AdministratorAccess` nor `WasabiFullAccess`).
2. **Next**, check the summary (name `auditisa-console`, program access only, one policy `auditisa-console-policy`), then **Create User**.
3. If you skipped that screen: **Users** > click `auditisa-console` > **Policies** tab > **Attach Policy** > choose `auditisa-console-policy` > **Attach**.

**Step 4. Copy the access key and the secret key**

1. Right after creation, a window shows the **Access Key** (capital letters and digits) and the **Secret Key** (longer). **The secret key will never be shown again.**
2. Click **Download CSV** (or **Copy Keys To Clipboard**) and put both values **in your password safe**, in an entry named "Wasabi auditisa-console". Do not send them by email or chat, do not put them in a shared document; delete the downloaded CSV file once the values are in the safe.
3. Your technician will put them on the console server (see below), straight from your safe.
4. If you closed the window too early: **Users** > `auditisa-console` > **Access Keys** tab > delete the key > **Create Access Key** to get a new one.

**Step 5. Create the releases bucket**

1. Left menu: **Buckets**, then **Create Bucket**.
2. **Bucket Name**: `auditisa-releases-` followed by 12 random lower-case letters and digits (for example drawn from your password manager, no capitals, no symbols). The shape: `auditisa-releases-k3j4h5g6f7d8` (do not use this one).
3. **Region**: the chosen region (`eu-central-1`, Amsterdam, in our examples).
4. Leave everything else as it is: no versioning, no Object Lock, **no public access**. **Create Bucket**.
5. Write the bucket's exact name in your safe and give it to your technician: it goes in Platform > Settings.

### What the technician does (console server)

The two values go in two files only root can read, like the Vultr token. They **never** go in `odoo.conf`, in the database or on a screen, and are never printed:

```
install -m 600 /dev/null /etc/auditisa-platform/wasabi.key
install -m 600 /dev/null /etc/auditisa-platform/wasabi.secret
# paste the access key, then Ctrl-D (nothing is shown, nothing stays in the history)
cat > /etc/auditisa-platform/wasabi.key
# paste the secret key, then Ctrl-D
cat > /etc/auditisa-platform/wasabi.secret
systemctl restart odoo
```

`install-control-plane.sh` declares both files to the service (`LoadCredential=wasabi-key` and `wasabi-secret`) and creates empty ones if missing, so that the console starts in simulation. Then Platform > Settings: **Wasabi region** (`eu-central-1`), **Releases bucket**, and the Wasabi address only if it is not the region's own (`s3.<region>.wasabisys.com`).

### What the console does by itself, for each firm

- **At onboarding:** a bucket `auditisa-fw-<slug>-<12 random characters>` in the chosen region, a user `auditisa-firm-<slug>` (under the path `/auditisa/`) **with no rights of its own**, a rule on the bucket that opens **that bucket only** to **that user only** (list, read, write, delete files; nothing else), then one key. The key goes to the firm's server in its first-boot text, as before, and is kept nowhere on the console.
- **At destruction** (after the exit's retention period, see OFFBOARDING.md): the key, the user, every backup, then the bucket. Wasabi's 90 days of minimum billing still run.
- **At each update:** two signed download addresses (the release and its signature), valid 6 hours, renewed at each heartbeat; 3 days for the first boot.

### What the console's key can and cannot do

It can: see the **names** of every bucket of the account (not their content); create, empty and delete the `auditisa-fw-*` buckets and write their access rule; read and upload files in the `auditisa-releases-*` buckets; create and delete the `auditisa-firm-*` users and their keys.

It cannot: read, change or delete your other buckets; touch your other users; give itself a second key or more rights; write or attach a policy on any user; read a firm's backup. Tests check this on the policy's text (`services/tests/test_wasabi.py`).

If it is stolen: at worst, someone can delete the firms' backups, or open an `auditisa-fw-*` bucket to themselves by writing a rule on it; they would find only backups encrypted with each firm's key, which is never on the console. **Response:** Wasabi > Users > `auditisa-console` > Access Keys > delete the key, then create a new one (step 4). For complete separation, a Wasabi account kept for the platform alone remains possible.

### A firm's server lost

To restore on a new server you need the backup key (your safe) and an access key to the bucket: Wasabi > Users > `auditisa-firm-<slug>` > Access Keys > **Create Access Key**. The bucket's name is on the firm's page (Storage). Delete that key once the restore is done.

### What only a first real run will confirm

The code was written from AWS's documentation, which Wasabi follows, and tested offline (signatures compared with AWS's published examples). It has **never talked to Wasabi**. With the first made-up firm (PREREQUISITES.md, step 8), the technician checks:

1. that Wasabi accepts the policy as it is, in particular `arn:aws:iam::*:user/...` (the `*` in place of the account number); otherwise, replace `*` with the account number (account menu > Settings);
2. that the console creates the bucket, the user, the bucket's rule and the key (provisioning tab);
3. **the main point:** that the firm's key, which has no policy of its own, can write to its bucket through the bucket's rule alone (`firm-backup` must succeed, then `firm-restore-test`). If Wasabi refuses, the firms' users will need a policy of their own, which means widening the console's policy: to discuss again first;
4. that with firm A's key, `restic` can neither read nor list firm B's bucket (from server A, pointing `RESTIC_REPOSITORY` at B's bucket: must fail);
5. that the server downloads the release through the signed address at first boot and during an update;
6. that destroying the made-up firm removes the key, the user, the files and the bucket.
