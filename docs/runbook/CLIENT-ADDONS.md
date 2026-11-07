# Les modules propres à un client / Client add-ons

[Français](#français) · [English](#english)

## Français

Tous les cabinets partagent le même code. Quand un client demande une fonction qui lui est propre, on écrit un module, et il s'active cabinet par cabinet depuis l'assistant de mise en service ou la fiche du cabinet.

**Décision du propriétaire :** couper un module pour un cabinet le **masque et garde ses données** ; le rallumer rend tout. On ne désinstalle jamais à la bascule : la désinstallation d'Odoo supprime des tables, et les dossiers d'audit ont des règles de conservation.

**État réel :** toute la chaîne a tourné sur une base jetable, avec les vrais scripts et de vrais heartbeats signés (voir « Ce qui est prouvé »). Elle n'a jamais tourné sur un vrai serveur de cabinet.

### Ce qui est de base, ce qui est au choix

| | Base | Module client |
|---|---|---|
| Ce qui le désigne | Pas de marqueur | `"ea_client_addon": True` dans le manifeste |
| Présence | Sur tous les cabinets | Dans chaque version, installé seulement là où il a été demandé |
| Interrupteur | Aucun. Les rapports en font partie. | Oui, par cabinet |

### Créer un module client

Le module `ea_client_addon_sample` est l'exemple complet, à recopier. Il suffit de cinq choses.

**1. Le manifeste.** Le nom technique commence par `ea_client_`. Il dépend de `ea_audit_addons`, et porte le marqueur :

```python
{
    "name": "Client notes",
    "summary": "One English sentence: the catalogue shows it.",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "author": "AuditISA",
    "depends": ["ea_audit_addons"],
    "data": ["security/feature.xml", "security/ir.model.access.csv", "views/note_views.xml"],
    "ea_client_addon": True,
}
```

**2. Le groupe `group_feature`**, dans `security/feature.xml`. C'est l'interrupteur : tant que le module est allumé, tout utilisateur interne le détient. Ce nom exact est obligatoire, et ne lui donnez ni `implied_ids` ni utilisateurs.

```xml
<record id="group_feature" model="res.groups">
    <field name="name">Client notes is on</field>
</record>
```

**3. Les droits et les menus sur ce groupe.** Mettez `group_feature` à chaque ligne de `ir.model.access.csv`, `groups="group_feature"` à chaque menu de premier niveau, et ce groupe sur toute vue héritée d'un écran de base (`<field name="group_ids" eval="[(4, ref('group_feature'))]"/>`). Odoo masque alors tout seul.

**4. Les modèles** héritent du mixin, qui refuse création, modification et suppression pendant l'arrêt, même au code en superutilisateur. Les boutons et actions serveur prennent le décorateur :

```python
from odoo.addons.ea_audit_addons.models.addon_switch import addon_required

class ClientNote(models.Model):
    _name = "ea.client.note"
    _inherit = ["ea.client.addon.mixin"]

    @addon_required
    def action_mark_reviewed(self):
        ...
```

Une tâche planifiée du module doit commencer par `if not self.env["ea.addon.switch"]._is_on("mon_module"): return`.

**5. Publier.** Ajoutez une ligne à `ea_platform_admin/services/addon_texts.py` pour le nom et le résumé (un test le vérifie), mettez le français dans `fr.po`, puis construisez une version signée : voir UPDATING.md.

**Trois limites à connaître :**

- Un champ ajouté par héritage à un modèle de base existe en base dès l'installation et reste là à l'arrêt. Pour une vraie donnée client, préférez un modèle à part.
- Une table `ea.client.*` à l'arrêt reste lisible en base et dans les sauvegardes : à l'arrêt, elle est masquée, pas effacée. L'export d'un cabinet qui part la contient.
- Un utilisateur du portail ne reçoit pas `group_feature`. Un écran de portail demande d'écrire ses propres droits.

### Inscrire la version

`build_release.sh` écrit à côté du paquet `<commit>.catalogue.json` et sa signature. Plateforme > Mises à jour > Versions, ouvrez la version, **Charger le fichier du catalogue**. Sur la vraie plateforme, la signature est exigée et vérifiée. Le catalogue (Plateforme > Modules) montre alors tout ce que contient le code, et qui a quoi.

### Allumer ou couper pour un cabinet

- **À la mise en service :** écran « Modules » de l'assistant. Indiquez pourquoi : le motif va au journal.
- **Ensuite :** fiche du cabinet, onglet « Modules », **Allumer** ou **Couper**. Qui, quand et pourquoi vont au journal de la plateforme.

Ce qui se passe, sans que le contrôle se connecte au cabinet :

1. Au prochain heartbeat (15 minutes au plus), la réponse signée donne la liste voulue. N'y figure que ce que la version en service du cabinet contient.
2. Dans les 5 minutes, `firm-addons`, lancé par root, revérifie **toute** la liste sur les manifestes de la version signée qu'il exécute. Un seul nom hors liste, et toute la demande est refusée.
3. **La première fois pour ce cabinet,** root installe le module : sauvegarde, arrêt d'Odoo quelques minutes, copie de la base, installation, redémarrage, contrôle de santé. En cas d'échec, la copie est remise et la base en échec conservée. **Prévenez le cabinet.**
4. Dans les 5 minutes, Odoo applique la liste. Les fois suivantes, rien n'est installé et rien ne s'arrête.
5. Le heartbeat suivant rapporte les codes allumés, et la fiche compare.

### Lire l'état

| État | Sens |
|---|---|
| Allumé, Coupé | Le cabinet dit la même chose que ce qui est demandé |
| En cours d'allumage, de coupure | Demandé il y a moins d'une heure |
| Demandé allumé, le cabinet dit coupé (et l'inverse) | Plus d'une heure : le cabinet passe à l'orange |
| Absent de la version du cabinet | Faites d'abord la mise à jour vers une version qui le contient |

Un cabinet orange avec « le serveur du cabinet a refusé » veut dire qu'un nom ne figure pas dans sa version, ou que l'installation a échoué. Un module en échec n'est pas retenté sur cette version. Pour redemander : corrigez, puis **Couper** et **Allumer**.

### Ce qui ne bouge jamais

Rien n'appelle la désinstallation : un test le vérifie dans les scripts et les modules du cabinet. Si un jour un module doit vraiment disparaître, c'est une opération à part, décidée par le propriétaire, après un export et un examen des règles de conservation.

### Ce qui est prouvé, ce qui ne l'est pas

| | |
|---|---|
| **Prouvé sur une base jetable,** vrais scripts et vrai Odoo (`.github/ci/firm-addons-rehearsal.sh`) | Première installation, sauvegarde d'abord ; coupure : menu masqué, modèle refusé, table et lignes conservées, module toujours installé ; rallumage sans installation ; refus de toute la demande pour un module de base, le module d'administration ou un nom inconnu ; échec d'installation avec retour de la copie ; mise à jour qui n'installe pas ce que personne n'a demandé ; aller-retour avec de vrais heartbeats signés vers un Odoo d'administration |
| **Remplacé dans cet essai** | `systemctl` et les appels `curl` de santé (aucun service n'est touché), `firm-backup` (pas de stockage) |
| **Jamais essayé** | Un vrai serveur de cabinet, son unité systemd, nginx, restic ; la vraie durée de l'arrêt ; le timer de 5 minutes ; Vultr et Cloudflare : la mise en service reste en SIMULATION |

## English

All firms share one codebase. When a client asks for a feature of their own, it is written as an add-on and switched on firm by firm, from the onboarding wizard or the firm's page.

**The owner's ruling:** switching an add-on off for a firm **hides it and keeps its data**; switching it back on restores everything. Nothing is ever uninstalled on a toggle: Odoo's uninstall drops tables, and audit records have retention rules.

**Where this really stands:** the whole path has run on a throwaway database, with the real scripts and real signed heartbeats (see "What is proved"). It has never run on a real firm server.

### What is base, what is optional

| | Base | Client add-on |
|---|---|---|
| What marks it | No marker | `"ea_client_addon": True` in the manifest |
| Where it is | On every firm | In every release, installed only where it was asked for |
| Switch | None. Reports are one of these. | Yes, per firm |

### Creating a client add-on

`ea_client_addon_sample` is the complete example to copy. It takes five things.

**1. The manifest.** The technical name starts with `ea_client_`. It depends on `ea_audit_addons` and carries the marker:

```python
{
    "name": "Client notes",
    "summary": "One English sentence: the catalogue shows it.",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "author": "AuditISA",
    "depends": ["ea_audit_addons"],
    "data": ["security/feature.xml", "security/ir.model.access.csv", "views/note_views.xml"],
    "ea_client_addon": True,
}
```

**2. The group `group_feature`**, in `security/feature.xml`. It is the switch: while the add-on is on, every internal user holds it. That exact name is required. Give it no `implied_ids` and no users.

```xml
<record id="group_feature" model="res.groups">
    <field name="name">Client notes is on</field>
</record>
```

**3. Access rules and menus on that group.** Put `group_feature` on every line of `ir.model.access.csv`, `groups="group_feature"` on every top-level menu, and that group on any view inherited from a base screen (`<field name="group_ids" eval="[(4, ref('group_feature'))]"/>`). Odoo then does the hiding itself.

**4. Models** inherit the mixin, which refuses create, write and unlink while off, even to code running as superuser. Buttons and server actions take the decorator:

```python
from odoo.addons.ea_audit_addons.models.addon_switch import addon_required

class ClientNote(models.Model):
    _name = "ea.client.note"
    _inherit = ["ea.client.addon.mixin"]

    @addon_required
    def action_mark_reviewed(self):
        ...
```

A scheduled job of the add-on must start with `if not self.env["ea.addon.switch"]._is_on("my_addon"): return`.

**5. Publish.** Add a line to `ea_platform_admin/services/addon_texts.py` for the name and summary (a test checks it), put the French in `fr.po`, then build a signed release: see UPDATING.md.

**Three limits to know:**

- A field added by inheritance to a base model exists in the database from the install and stays there while off. For real client data, prefer a separate model.
- An `ea.client.*` table that is off stays readable in the database and in backups: off means hidden, not erased. The export of a firm leaving contains it.
- A portal user does not get `group_feature`. A portal screen needs its own access rules.

### Registering the release

`build_release.sh` writes `<commit>.catalogue.json` and its signature beside the bundle. Platform > Updates > Releases, open the release, **Load the catalogue file**. On the real platform the signature is required and checked. The catalogue (Platform > Add-ons) then shows everything in the code and who has what.

### Switching on or off for a firm

- **At onboarding:** the wizard's "Add-ons" screen. Say why: the reason goes in the log.
- **Later:** the firm's page, "Add-ons" tab, **Switch on** or **Switch off**. Who, when and why go in the platform log.

What happens, with the control plane never logging in to the firm:

1. At the next heartbeat (15 minutes at most), the signed answer gives the desired list. Only what the firm's running release carries goes in it.
2. Within 5 minutes, `firm-addons`, run by root, checks the **whole** list again against the manifests of the signed release it runs. One name outside that list and the whole request is refused.
3. **The first time for this firm,** root installs the add-on: backup, Odoo stopped for a few minutes, database copied, install, restart, health check. On failure the copy goes back and the failed database is kept. **Warn the firm.**
4. Within 5 minutes, Odoo applies the list. After that, nothing is installed and nothing stops.
5. The next heartbeat reports the codes that are on, and the firm's page compares.

### Reading the state

| State | Meaning |
|---|---|
| On, Off | The firm says the same as what was asked |
| Switching on, Switching off | Asked less than an hour ago |
| Asked on, firm says off (and the reverse) | Over an hour: the firm turns amber |
| Not in the firm's release | Update first to a release that carries it |

An amber firm with "the firm's server refused" means a name is not in its release, or the install failed. A failed add-on is not tried again on that release. To ask again: fix it, then **Switch off** and **Switch on**.

### What never moves

Nothing calls an uninstall: a test checks the firm's scripts and addons for it. If an add-on must one day really go, that is a separate operation, decided by the owner, after an export and a look at the retention rules.

### What is proved, what is not

| | |
|---|---|
| **Proved on a throwaway database,** real scripts and real Odoo (`.github/ci/firm-addons-rehearsal.sh`) | First install, backup first; off: menu hidden, model refused, table and rows kept, module still installed; on again with no install; the whole request refused for a base module, the admin addon or an unknown name; a failed install with the copy put back; an update that does not install what nobody asked for; a round trip with real signed heartbeats to an admin Odoo |
| **Replaced in that test** | `systemctl` and the health `curl` calls (no service is touched), `firm-backup` (no storage) |
| **Never tried** | A real firm server, its systemd unit, nginx, restic; the real length of the outage; the 5-minute timer; Vultr and Cloudflare: provisioning stays in SIMULATION |
