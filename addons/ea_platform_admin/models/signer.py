from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..services import signers as trust
from ..services.messages import _
from .i18n import t

PARAM_SERIAL = "ea_platform.signers_serial"
# Before the list of signers there was one key, in this parameter. It is read once, by the migration,
# and left in place for the release tools that still read it (upload-release.sh before 2026-11-10).
PARAM_LEGACY_KEY = "ea_platform.release_signing_public_key"
OWNER_NAME = "Owner"
OWNER_EMAIL = "contact@cm-ea.com"


class PlatformSigner(models.Model):
    """One person allowed to sign a new version, with their OWN key. Never a shared key.

    The private half stays on that person's computer, locked by their passphrase. Only the public half
    comes here. Only the console's owner adds or removes a signer, and the platform log keeps each change.
    Removing a signer refuses their future signatures; what they signed while trusted stays valid.
    """

    _name = "platform.signer"
    _description = "Trusted signer"
    _order = "active desc, added_at, id"

    name = fields.Char("Name", required=True)
    email = fields.Char("Email", required=True)
    public_pem = fields.Text("Public key", required=True, readonly=True,
                             help="The content of the person's .pub file. It is not secret.")
    fingerprint = fields.Char("Fingerprint", required=True, readonly=True, index=True)
    fingerprint_short = fields.Char("Fingerprint (short)", compute="_compute_short",
                                    help="The first 16 characters. The desktop tool shows the same to the person signing.")
    active = fields.Boolean("Trusted", default=True, readonly=True)
    added_at = fields.Datetime("Added on", readonly=True, default=fields.Datetime.now)
    added_by_id = fields.Many2one("res.users", "Added by", readonly=True, default=lambda self: self.env.user)
    removed_at = fields.Datetime("Removed on", readonly=True)
    removed_by_id = fields.Many2one("res.users", "Removed by", readonly=True)
    release_ids = fields.One2many("platform.release", "signer_id", "Versions signed")
    release_count = fields.Integer("Versions signed", compute="_compute_release_count")

    _fingerprint_unique = models.Constraint(
        "unique(fingerprint)", "This key is already in the list. A removed key cannot come back: make a new one.",
    )

    @api.depends("fingerprint")
    def _compute_short(self):
        for signer in self:
            signer.fingerprint_short = trust.short(signer.fingerprint)

    def _compute_release_count(self):
        for signer in self:
            signer.release_count = len(signer.with_context(active_test=False).release_ids)

    @api.depends("name", "email")
    def _compute_display_name(self):
        for signer in self:
            signer.display_name = f"{signer.name} ({signer.email})" if signer.email else signer.name or ""

    # ------------------------------------------------------------------ changes, owner only

    def _check_owner(self):
        if self.env.su:
            return
        if not self.env.user.has_group("ea_platform_admin.group_platform_owner"):
            raise AccessError(t(self.env, _("Only the owner adds or removes a signer.")))

    @api.model
    def _bump_serial(self):
        params = self.env["ir.config_parameter"].sudo()
        serial = int(params.get_param(PARAM_SERIAL, "0") or 0) + 1
        params.set_param(PARAM_SERIAL, str(serial))
        return serial

    @api.model
    def _serial(self):
        return int(self.env["ir.config_parameter"].sudo().get_param(PARAM_SERIAL, "0") or 0)

    @api.model_create_multi
    def create(self, vals_list):
        self._check_owner()
        for vals in vals_list:
            try:
                vals["name"] = trust.check_name(vals.get("name"))
                vals["email"] = trust.check_email(vals.get("email"))
                vals["public_pem"] = trust.normalise(vals.get("public_pem"))
            except trust.SignerRefused as refused:
                raise UserError(t(self.env, refused.message)) from None
            vals["fingerprint"] = trust.fingerprint(vals["public_pem"])
            vals["active"] = True
            vals.pop("removed_at", None)
            vals.pop("removed_by_id", None)
            if self.with_context(active_test=False).search_count([("fingerprint", "=", vals["fingerprint"])]):
                raise UserError(t(self.env, _("This key is already in the list. A removed key cannot come back: make a new one.")))
        signers = super().create(vals_list)
        for signer in signers:
            serial = self._bump_serial()
            self.env["platform.log"]._record(
                _("Signer added"),
                detail=_("%(name)s (%(email)s), fingerprint %(fingerprint)s. List number %(serial)s.",
                         name=signer.name, email=signer.email, fingerprint=signer.fingerprint_short, serial=serial),
            )
        return signers

    def write(self, vals):
        if {"public_pem", "fingerprint"} & set(vals) and not self.env.context.get("ea_signer_migration"):
            raise UserError(t(self.env, _("A signer's key never changes: remove the signer and add the new key.")))
        if {"active", "removed_at", "removed_by_id"} & set(vals) and not self.env.context.get("ea_signer_removal"):
            raise UserError(t(self.env, _("Use the Remove button: it is logged.")))
        if {"name", "email"} & set(vals):
            self._check_owner()
            try:
                if "name" in vals:
                    vals["name"] = trust.check_name(vals["name"])
                if "email" in vals:
                    vals["email"] = trust.check_email(vals["email"])
            except trust.SignerRefused as refused:
                raise UserError(t(self.env, refused.message)) from None
        result = super().write(vals)
        if {"name", "email"} & set(vals):
            serial = self._bump_serial()
            for signer in self:
                self.env["platform.log"]._record(
                    _("Signer changed"),
                    detail=_("%(name)s (%(email)s), fingerprint %(fingerprint)s. List number %(serial)s.",
                             name=signer.name, email=signer.email, fingerprint=signer.fingerprint_short, serial=serial),
                )
        return result

    def unlink(self):
        raise UserError(t(self.env, _("A signer is never deleted: use Remove. The record keeps who signed what.")))

    def action_remove(self):
        self._check_owner()
        for signer in self:
            if not signer.active:
                continue
            others = self.search([("id", "!=", signer.id)])
            if not others:
                raise UserError(t(self.env, _(
                    "At least one signer must stay: without one, no new version could ever be accepted.")))
            signer.with_context(ea_signer_removal=True).write({
                "active": False, "removed_at": fields.Datetime.now(), "removed_by_id": self.env.user.id,
            })
            serial = self._bump_serial()
            self.env["platform.log"]._record(
                _("Signer removed"),
                detail=_("%(name)s (%(email)s), fingerprint %(fingerprint)s. List number %(serial)s. "
                         "Their future signatures are refused; the versions they signed before stay valid.",
                         name=signer.name, email=signer.email, fingerprint=signer.fingerprint_short, serial=serial),
            )
        return True

    # ------------------------------------------------------------------ what the rest of the console asks

    @api.model
    def _trusted(self):
        """The signers whose signature is accepted today, as plain dicts."""
        return [{"id": s.id, "name": s.name, "email": s.email, "pem": s.public_pem}
                for s in self.sudo().search([])]

    @api.model
    def _who_signed(self, signature, data):
        """The active signer whose key made this signature, or an empty recordset."""
        found = trust.which(self._trusted(), signature, data)
        return self.sudo().browse(found["id"]) if found else self.sudo().browse()

    @api.model
    def _document(self):
        """deploy/trust/signers.json for the next version, and what a new firm gets at first boot."""
        everyone = self.sudo().with_context(active_test=False).search([])
        active = [{"name": s.name, "email": s.email, "pem": s.public_pem} for s in everyone if s.active]
        retired = [{"name": s.name, "email": s.email, "pem": s.public_pem,
                    "valid_for": s.with_context(active_test=False).release_ids.mapped("bundle_sha256")}
                   for s in everyone if not s.active]
        try:
            return trust.document(max(self._serial(), 1), active, retired)
        except trust.SignerRefused as refused:
            raise UserError(t(self.env, refused.message)) from None

    def action_download_list(self):
        """The file a technician puts at deploy/trust/signers.json before building the next version."""
        if not self.env.user.has_group("ea_platform_admin.group_platform_operator"):
            raise AccessError(t(self.env, _("Only the owner and operators download the list.")))
        raw = self._document()
        attachment = self.env["ir.attachment"].create({
            "name": "signers.json", "raw": raw, "mimetype": "application/json",
            "res_model": "platform.signer", "res_id": 0,
        })
        return {"type": "ir.actions.act_url", "url": f"/web/content/{attachment.id}?download=true", "target": "self"}

    # ------------------------------------------------------------------ the move from one key to a list

    @api.model
    def _migrate_single_key(self):
        """Brings the one key of before into the list, as the owner's. Does nothing if a list exists."""
        model = self.sudo().with_context(active_test=False)
        if model.search_count([]):
            return model.browse()
        pem = self.env["ir.config_parameter"].sudo().get_param(PARAM_LEGACY_KEY)
        if not pem or "BEGIN PUBLIC KEY" not in pem:
            return model.browse()
        try:
            pem = trust.normalise(pem)
        except trust.SignerRefused:
            return model.browse()
        root = self.env(user=SUPERUSER_ID)["platform.signer"]
        signer = root.create({"name": OWNER_NAME, "email": OWNER_EMAIL, "public_pem": pem})
        # A catalogue whose signature the console checked was signed with that one key.
        releases = self.env["platform.release"].sudo().with_context(active_test=False).search(
            [("signer_id", "=", False), ("catalogue_signed", "=", True)])
        releases.write({"signer_id": signer.id})
        return signer
