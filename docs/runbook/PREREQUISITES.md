# Ce qu'il faut avant le premier vrai cabinet / What is needed before the first real firm

[Français](#français) · [English](#english)

## Français

**La console (le serveur de contrôle) est installée depuis le 8 novembre 2026 : https://console.auditisa.com**, en simulation. Aucun jeton Vultr, DNS ou Wasabi n'y est déposé : la création de cabinets n'est pas encore branchée, et chaque écran le dit.

**Décision du 9 novembre 2026 :** les sauvegardes et les versions vont chez **Wasabi** (compte du propriétaire), plus chez Vultr Object Storage. Vultr reste le fournisseur des serveurs. Mode d'emploi pas à pas : **WASABI.md**.

État à ce jour, pour les cabinets : **tout a tourné en simulation.** Aucun serveur Vultr n'a été créé, Vultr, Wasabi et Cloudflare n'ont jamais été appelés, et le script d'installation d'un cabinet n'a tourné qu'en mode essai. Le premier vrai cabinet sera donc aussi le premier essai réel : faites-le d'abord sur un cabinet fictif (étape 8).

### Ce que vous devez fournir

| # | Quoi | Où le trouver | Où cela va |
|---|---|---|---|
| 1 | **Jeton API Vultr** | Vultr > Account > API. Limitez-le à l'adresse IP du serveur de contrôle. | `/etc/auditisa-platform/vultr.token` sur le serveur de contrôle, droits 600, root. Jamais dans Odoo, jamais dans le dépôt. |
| 2 | **Serveur de contrôle** | Un petit serveur Vultr séparé de tous les cabinets (1 vCPU, 2 Go). Ubuntu 26.04. **Fait :** 45.76.80.53. | `deploy/control-plane/install-control-plane.sh` |
| 3 | **Deux adresses** pour lui | `console.auditisa.com` (les écrans) et `hb.auditisa.com` (les heartbeats des cabinets, rien d'autre). **Faites.** | Enregistrements DNS que vous créez à la main. |
| 4 | **Stockage des sauvegardes : Wasabi** | Votre compte Wasabi : une politique `auditisa-console-policy` et un utilisateur `auditisa-console` (accès programme seulement), créés une fois en suivant **WASABI.md**. Sa clé d'accès et sa clé secrète vont dans votre coffre. Pour chaque cabinet, la console crée ensuite seule un bucket et une clé qui n'ouvre que lui. | `/etc/auditisa-platform/wasabi.key` et `wasabi.secret` sur le serveur de contrôle, droits 600, root. Jamais dans Odoo, jamais dans le dépôt. La région va dans Réglages. |
| 5 | **Accès DNS** | Jeton Cloudflare limité à « Zone DNS Edit » sur `auditisa.com`, et l'identifiant de la zone. Si le DNS n'est pas chez Cloudflare, il faut écrire une petite classe de plus. | `/etc/auditisa-platform/cloudflare.token`, droits 600, root. L'identifiant de zone va dans Réglages. |
| 6 | **Bucket des versions** | Un bucket Wasabi privé `auditisa-releases-<12 caractères au hasard>`, dans la même région (WASABI.md, étape 5). Les cabinets n'y ont aucune clé : la console leur donne des adresses de téléchargement qui expirent. | Plateforme > Réglages. |
| 7 | **Clé de signature** | Plus nécessaire depuis le 10 novembre 2026 : les versions ne sont plus signées (UPDATING.md). | |
| 8 | **Votre adresse IP publique fixe** | Pour le port 22 des serveurs des cabinets. Sans IP fixe, prévoyez un petit relais à adresse fixe. **La console, elle, s'ouvre de partout** (décision du 8 novembre 2026, `OPERATOR_IPS=any`) : une liste d'adresses reste possible pour la restreindre. | Réglages (port 22 des cabinets) ; `OPERATOR_IPS` (console). |
| 9 | **Un coffre** | Un gestionnaire de mots de passe. Il recevra la clé SSH et la clé de sauvegarde de chaque cabinet. | Chez vous. |
| 10 | **Vos décisions** | La question laissée ouverte (les cabinets doivent-ils être protégés de l'opérateur ?) et le lieu des données : voir SECURITY-MODEL. | |

### Taille et coût mensuel par cabinet

**À confirmer sur vultr.com et wasabi.com :** ces prix viennent de mémoire des tarifs publics ; ils n'ont pas été vérifiés, aucun appel à Vultr ni à Wasabi n'étant permis pendant ce travail. Ce sont eux que l'écran de vérification affiche : corrigez `services/catalogue.py` s'ils ont changé. La bande passante au-delà du forfait et les taxes ne sont pas comptées.

| Taille | Utilisateurs (ordre de grandeur) | Serveur Vultr | Serveur / mois | Sauvegardes Wasabi / mois | Total estimé |
|---|---|---|---|---|---|
| Petit | jusqu'à 10 | 2 vCPU, 4 Go, 80 Go (`vc2-2c-4gb`) | 20 USD | environ 1 USD | **21 USD** |
| Standard | jusqu'à 30 | 4 vCPU, 8 Go, 160 Go (`vc2-4c-8gb`) | 40 USD | environ 1 USD | **41 USD** |
| Grand | plus de 30 | 6 vCPU, 16 Go, 320 Go (`vc2-6c-16gb`) | 80 USD | environ 1 USD | **81 USD** |

Sauvegardes : Wasabi à l'usage, **environ 7 USD par To et par mois**, soit environ 1 USD pour la centaine de Go d'un cabinet. **Deux règles de Wasabi à connaître** (à confirmer sur wasabi.com) : le compte paie **au moins 1 To** (environ 7 USD par mois) quel que soit le volume, et **un fichier effacé est facturé comme s'il avait été gardé 90 jours** ; les sauvegardes quotidiennes étant remplacées chaque jour, le volume facturé d'un cabinet dépasse un peu ce qu'il garde.

S'y ajoutent, une seule fois pour toute la plateforme : le serveur de contrôle (`vc2-1c-2gb`, environ 10 USD/mois) et le minimum Wasabi de 1 To (environ 7 USD/mois, qui couvre les premiers cabinets et les versions). Il n'y a plus d'abonnement de stockage par cabinet.

### Mise en route, dans l'ordre

1. **Fait le 8 novembre 2026.** Créez le serveur de contrôle et ses deux adresses DNS. Copiez sur le serveur `addons/ea_platform_admin` et `addons/ea_platform_pipeline` (et aucun autre module), `deploy/control-plane` et `deploy/firm/recipe.env` (`git archive <commit> addons/ea_platform_admin addons/ea_platform_pipeline deploy/control-plane deploy/firm/recipe.env | ssh root@serveur tar -x -C /opt/auditisa-platform`), puis lancez `install-control-plane.sh --env fichier.env` (modèle : `deploy/control-plane/sample.env`). Créez ensuite votre connexion : `set-owner.sh --login vous@exemple.com --name "Votre nom"`, le mot de passe sur l'entrée standard. Le compte `admin` reçoit un mot de passe aléatoire que personne n'utilise, gardé dans `/etc/auditisa-platform/admin.password` (root seul).
2. Suivez **WASABI.md** (politique, utilisateur `auditisa-console`, bucket des versions). Déposez les deux jetons et les deux valeurs Wasabi, droits 600, puis `systemctl restart odoo`. Si la console a été installée avant l'arrivée de Wasabi, relancez d'abord `install-control-plane.sh` : il déclare `wasabi.key` et `wasabi.secret` au service.
3. Faites vérifier par votre technicien, une seule fois avec le vrai jeton, ce qui n'a jamais pu l'être : l'identifiant du système (`GET /v2/os`, Ubuntu 26.04 doit figurer), les plans (`GET /v2/plans`) et la disponibilité de la région choisie. **Le code Vultr et le code Wasabi ont été écrits d'après la documentation publique et n'ont jamais parlé à ces services** : la liste des points Wasabi à vérifier est à la fin de WASABI.md.
4. Construisez et signez une version (UPDATING.md), déposez-la dans le bucket des versions, enregistrez-la dans Plateforme > Versions.
5. Remplissez Plateforme > Réglages. Le passage au réel demande tous les réglages, les deux jetons, les deux valeurs Wasabi et une case cochée. Le bandeau « Simulation » disparaît alors.
6. Corrigez les prix si besoin.
7. Prévenez votre technicien : le premier passage réel de `install-firm-server.sh` révélera sans doute des erreurs que le mode essai ne peut pas voir.
8. Créez un **cabinet fictif** (ONBOARDING.md), vérifiez tout, dont la sauvegarde, le test de restauration et une mise à jour. Créez-en un second, puis lancez `scripts/provision/verify_firm_isolation.sh` entre les deux : le contrôle des routes et des ports n'a jamais tourné pour de vrai.
9. Détruisez les deux fictifs, puis passez au premier cabinet.

## English

**The console (the control server) has been installed since 8 November 2026: https://console.auditisa.com**, in simulation. No Vultr, DNS or Wasabi key is on it: firm creation is not connected yet, and every screen says so.

**Decision of 9 November 2026:** backups and releases go to **Wasabi** (the owner's account), no longer to Vultr Object Storage. Vultr stays the server provider. Step-by-step guide: **WASABI.md**.

Status today, for firms: **everything has only run as a simulation.** No Vultr server was created, Vultr, Wasabi and Cloudflare were never called, and the firm install script has only run in dry-run mode. The first real firm is therefore also the first real trial: do it first on a made-up firm (step 8).

### What you must supply

| # | What | Where to get it | Where it goes |
|---|---|---|---|
| 1 | **Vultr API token** | Vultr > Account > API. Restrict it to the control server's IP address. | `/etc/auditisa-platform/vultr.token` on the control server, mode 600, root. Never in Odoo, never in the repository. |
| 2 | **Control server** | A small Vultr server apart from every firm (1 vCPU, 2 GB), Ubuntu 26.04. **Done:** 45.76.80.53. | `deploy/control-plane/install-control-plane.sh` |
| 3 | **Two addresses** for it | `console.auditisa.com` (the screens) and `hb.auditisa.com` (the firms' heartbeats, nothing else). **Done.** | DNS records you create by hand. |
| 4 | **Backup storage: Wasabi** | Your Wasabi account: a policy `auditisa-console-policy` and a user `auditisa-console` (program access only), made once by following **WASABI.md**. Its access key and secret key go in your safe. For each firm the console then makes, by itself, a bucket and a key that opens it alone. | `/etc/auditisa-platform/wasabi.key` and `wasabi.secret` on the control server, mode 600, root. Never in Odoo, never in the repository. The region goes in Settings. |
| 5 | **DNS access** | A Cloudflare token limited to "Zone DNS Edit" on `auditisa.com`, and the zone id. If the DNS is not at Cloudflare, one more small class must be written. | `/etc/auditisa-platform/cloudflare.token`, mode 600, root. The zone id goes in Settings. |
| 6 | **Releases bucket** | A private Wasabi bucket `auditisa-releases-<12 random characters>`, in the same region (WASABI.md, step 5). Firms hold no key to it: the console gives them download addresses that expire. | Platform > Settings. |
| 7 | **Signing key** | No longer needed since 10 November 2026: releases are not signed any more (UPDATING.md). | |
| 8 | **Your fixed public IP address** | For port 22 of the firms' servers. Without a fixed IP, plan a small relay with a fixed address. **The console itself opens from anywhere** (ruling of 8 November 2026, `OPERATOR_IPS=any`): a list of addresses is still possible to restrict it. | Settings (firms' port 22); `OPERATOR_IPS` (console). |
| 9 | **A safe** | A password manager, for each firm's SSH key and backup key. | With you. |
| 10 | **Your decisions** | The open question (do firms need protection from the operator?) and where the data lives: see SECURITY-MODEL. | |

### Size and monthly cost per firm

**To be confirmed on vultr.com and wasabi.com:** these prices are from memory of the public price lists and were not checked, since no call to Vultr or Wasabi was allowed during this work. They are what the preflight screen shows: correct `services/catalogue.py` if they have moved. Bandwidth beyond the allowance and taxes are not counted.

| Size | Users (rough guide) | Vultr server | Server / month | Wasabi backups / month | Estimated total |
|---|---|---|---|---|---|
| Small | up to 10 | 2 vCPU, 4 GB, 80 GB (`vc2-2c-4gb`) | USD 20 | about USD 1 | **USD 21** |
| Standard | up to 30 | 4 vCPU, 8 GB, 160 GB (`vc2-4c-8gb`) | USD 40 | about USD 1 | **USD 41** |
| Large | over 30 | 6 vCPU, 16 GB, 320 GB (`vc2-6c-16gb`) | USD 80 | about USD 1 | **USD 81** |

Backups: Wasabi pay as you go, **about USD 7 per TB per month**, so about USD 1 for a firm's hundred GB or so. **Two Wasabi rules to know** (to confirm on wasabi.com): the account pays for **at least 1 TB** (about USD 7 a month) whatever is stored, and **a deleted file is billed as if it had been kept 90 days**; since daily backups are replaced every day, a firm's billed volume is somewhat above what it keeps.

Add, once for the whole platform: the control server (`vc2-1c-2gb`, about USD 10 a month) and Wasabi's 1 TB minimum (about USD 7 a month, which covers the first firms and the releases). There is no longer a storage subscription per firm.

### Getting started, in order

1. **Done on 8 November 2026.** Create the control server and its two DNS addresses. Copy to it `addons/ea_platform_admin` and `addons/ea_platform_pipeline` (and no other addon), `deploy/control-plane` and `deploy/firm/recipe.env` (`git archive <commit> addons/ea_platform_admin addons/ea_platform_pipeline deploy/control-plane deploy/firm/recipe.env | ssh root@server tar -x -C /opt/auditisa-platform`), and run `install-control-plane.sh --env file.env` (template: `deploy/control-plane/sample.env`). Then make your sign-in: `set-owner.sh --login you@example.com --name "Your name"`, the password on stdin. The `admin` account gets a random password nobody uses, kept in `/etc/auditisa-platform/admin.password` (root only).
2. Follow **WASABI.md** (policy, user `auditisa-console`, releases bucket). Put the two tokens and the two Wasabi values in place, mode 600, then `systemctl restart odoo`. If the console was installed before Wasabi came in, run `install-control-plane.sh` again first: it declares `wasabi.key` and `wasabi.secret` to the service.
3. Have your technician check, once and with the real token, what could not be checked so far: the system id (`GET /v2/os`, Ubuntu 26.04 must be listed), the plans (`GET /v2/plans`) and the chosen region's availability. **The Vultr code and the Wasabi code were written from the public documentation and have never talked to those services**: the Wasabi points to check are listed at the end of WASABI.md.
4. Build and sign a release (UPDATING.md), upload it to the releases bucket, register it in Platform > Releases.
5. Fill in Platform > Settings. Going real needs every setting, both tokens, both Wasabi values and a ticked box. The "Simulation" band then goes away.
6. Correct the prices if needed.
7. Warn your technician: the first real run of `install-firm-server.sh` will probably find errors a dry run cannot see.
8. Create a **made-up firm** (ONBOARDING.md) and check everything, including the backup, the restore test and an update. Create a second one and run `scripts/provision/verify_firm_isolation.sh` between them: the routes and ports check has never run for real.
9. Destroy both, then move on to the first firm.
