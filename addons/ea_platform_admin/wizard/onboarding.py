import secrets

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..services.catalogue import LANGUAGES, REGIONS, SIZES, monthly_cost, selection
from ..services.validation import (
    flatten_errors,
    normalise_slug,
    onboarding_errors,
    parse_allowlist,
)

STEP_FIELDS = {
    "identity": ("name", "slug", "contact_name", "contact_email", "allowed_email_domains"),
    "technical": ("region", "size", "lang", "ssh_public_key"),
}


class PlatformOnboardingWizard(models.TransientModel):
    """A new client firm: three screens, then the provisioning job with its visible step log."""

    _name = "platform.onboarding.wizard"
    _description = "Nouveau cabinet"

    step = fields.Selection(
        [("identity", "Le cabinet"), ("technical", "Le serveur"), ("preflight", "Vérification")],
        default="identity", required=True,
    )
    name = fields.Char("Nom du cabinet")
    slug = fields.Char("Identifiant", help="Devient l'adresse : identifiant.auditisa.com. Ne change plus jamais.")
    contact_name = fields.Char("Nom du contact")
    contact_email = fields.Char("E-mail du contact", help="Sera l'identifiant du premier administrateur.")
    contact_phone = fields.Char("Téléphone")
    allowed_email_domains = fields.Text("Domaines de messagerie autorisés", help="Un par ligne, par exemple exemple.cm")
    region = fields.Selection(selection(REGIONS), "Région", default="cdg")
    size = fields.Selection(selection(SIZES), "Taille", default="standard")
    lang = fields.Selection(selection(LANGUAGES), "Langue", default="fr_FR")
    ssh_public_key = fields.Char(
        "Clé publique SSH du cabinet",
        help="Le contenu du fichier .pub créé sur votre ordinateur pour ce cabinet. "
             "La clé privée reste chez vous : ne la collez jamais ici.",
    )
    release_id = fields.Many2one(
        "platform.release", "Version à installer",
        default=lambda self: self.env["platform.release"].search([], limit=1),
    )
    confirmed = fields.Boolean("Je confirme la création de ce serveur et son coût mensuel estimé.")

    preview_address = fields.Char("Adresse", compute="_compute_preview")
    preview_server = fields.Char("Serveur", compute="_compute_preview")
    preview_server_cost = fields.Float("Serveur (USD/mois)", compute="_compute_preview")
    preview_storage_cost = fields.Float("Stockage de sauvegarde (USD/mois)", compute="_compute_preview")
    preview_total_cost = fields.Float("Total estimé (USD/mois)", compute="_compute_preview")
    preview_mode = fields.Char("Mode", compute="_compute_preview")
    preview_allowlist = fields.Char("Port 22 ouvert à", compute="_compute_preview")

    @api.depends("slug", "size", "region")
    def _compute_preview(self):
        get_param = self.env["ir.config_parameter"].sudo().get_param
        base = get_param("ea_platform.base_domain", "auditisa.com")
        simulation = self.env["platform.services"]._is_simulation()
        for wizard in self:
            size = SIZES.get(wizard.size)
            wizard.preview_address = f"{normalise_slug(wizard.slug)}.{base}" if wizard.slug else False
            wizard.preview_server = (
                f"{size['vcpu']} vCPU, {size['ram_gb']} Go de mémoire, {size['disk_gb']} Go de disque, "
                f"{REGIONS.get(wizard.region, '')}"
            ) if size else False
            server, storage, total = monthly_cost(wizard.size) if size else (0.0, 0.0, 0.0)
            wizard.preview_server_cost = server
            wizard.preview_storage_cost = storage
            wizard.preview_total_cost = total
            wizard.preview_mode = (
                "SIMULATION : aucun serveur ne sera créé et rien ne sera facturé."
                if simulation else "RÉEL : un serveur sera créé et facturé par le fournisseur."
            )
            wizard.preview_allowlist = ", ".join(parse_allowlist(get_param("ea_platform.ssh_allowlist", ""))[0]) or (
                "aucune adresse réglée" + (" (simulation)" if simulation else "")
            )

    def _data(self):
        self.ensure_one()
        return {
            "name": self.name, "slug": normalise_slug(self.slug), "contact_name": self.contact_name,
            "contact_email": (self.contact_email or "").strip(), "region": self.region, "size": self.size,
            "lang": self.lang, "allowed_email_domains": self.allowed_email_domains,
            "ssh_public_key": (self.ssh_public_key or "").strip(),
        }

    def _errors(self, fields_to_check=None):
        firms = self.env["platform.firm"].sudo().with_context(active_test=False).search([])
        errors = onboarding_errors(
            self._data(),
            existing_slugs=firms.mapped("slug"),
            existing_fingerprints=firms.mapped("ssh_key_fingerprint"),
        )
        if fields_to_check is not None:
            errors = {field: messages for field, messages in errors.items() if field in fields_to_check}
        return errors

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_next(self):
        self.ensure_one()
        errors = self._errors(STEP_FIELDS.get(self.step))
        if errors:
            raise UserError(flatten_errors(errors))
        self.write({
            "slug": normalise_slug(self.slug),
            "step": {"identity": "technical", "technical": "preflight"}[self.step],
            "confirmed": False,
        })
        return self._reopen()

    def action_back(self):
        self.ensure_one()
        self.write({"step": {"preflight": "technical", "technical": "identity"}[self.step], "confirmed": False})
        return self._reopen()

    def action_confirm(self):
        self.ensure_one()
        if self.step != "preflight":
            raise UserError("Passez d'abord par l'écran de vérification.")
        if not self.confirmed:
            raise UserError("Cochez la confirmation : rien n'est créé sans elle.")
        errors = self._errors()
        if errors:
            raise UserError(flatten_errors(errors))
        if not self.release_id:
            raise UserError(
                "Aucune version n'est enregistrée. Enregistrez d'abord une version signée "
                "(Plateforme > Versions) : voir docs/runbook/UPDATING.md."
            )
        simulation = self.env["platform.services"]._is_simulation()
        if not simulation:
            self._check_settings()
        data = self._data()
        firm = self.env["platform.firm"].sudo().create({
            **data,
            "contact_phone": self.contact_phone,
            "state": "provisioning",
            "is_simulation": simulation,
            "desired_release_id": self.release_id.id,
            "heartbeat_token": secrets.token_hex(32),
        })
        self.env["platform.log"]._record(
            "Nouveau cabinet confirmé", firm,
            f"Taille {firm.size}, région {firm.region}, coût estimé {firm.monthly_cost_usd:.2f} USD/mois",
        )
        job = self.env["platform.provision.job"]._start(firm)
        job._run()
        return {
            "type": "ir.actions.act_window",
            "res_model": "platform.provision.job",
            "res_id": job.id,
            "view_mode": "form",
            "target": "current",
        }

    def _check_settings(self):
        get_param = self.env["ir.config_parameter"].sudo().get_param
        required = {
            "ea_platform.heartbeat_url": "Adresse de réception des heartbeats",
            "ea_platform.release_base_url": "Adresse des versions",
            "ea_platform.release_signing_public_key": "Clé publique de signature des versions",
            "ea_platform.ssh_allowlist": "Adresses de l'opérateur pour le port 22",
            "ea_platform.vultr_os_id": "Système du serveur (identifiant Vultr)",
            "ea_platform.vultr_storage_cluster": "Grappe de stockage objet (identifiant Vultr)",
            "ea_platform.dns_zone_id": "Zone DNS",
        }
        missing = [label for key, label in required.items() if not get_param(key)]
        if missing:
            raise UserError("Réglages manquants (Plateforme > Réglages) :\n" + "\n".join(missing))

    @api.onchange("ssh_public_key")
    def _onchange_ssh_public_key(self):
        if self.ssh_public_key and "PRIVATE KEY" in self.ssh_public_key:
            self.ssh_public_key = False
            return {"warning": {
                "title": "Clé privée effacée",
                "message": "Vous avez collé une clé PRIVÉE. Elle a été effacée de ce formulaire sans être "
                           "enregistrée. Collez le contenu du fichier .pub.",
            }}
        return None

