from odoo import api, models

# Both languages read DD/MM/YYYY; the separators follow the language.
_FORMATS = {
    "en_US": {"date_format": "%d/%m/%Y", "time_format": "%H:%M:%S", "decimal_point": ".", "thousands_sep": ",", "grouping": "[3,0]"},
    "fr_FR": {"date_format": "%d/%m/%Y", "time_format": "%H:%M:%S", "decimal_point": ",", "thousands_sep": "\u00a0", "grouping": "[3,0]"},
}


class ResLang(models.Model):
    _inherit = "res.lang"

    @api.model
    def _ea_refresh_french(self, module_name, marker):
        """An update keeps the French a database already holds, so a corrected term stays old on a
        running firm. Called from a module's data with a new marker when its fr.po corrects terms:
        reads the file again over what is there, once."""
        params = self.env["ir.config_parameter"].sudo()
        key = "ea_audit.french_refreshed.%s" % module_name
        if params.get_param(key) == marker:
            return
        params.set_param(key, marker)
        module = self.env["ir.module.module"].sudo().search([("name", "=", module_name)], limit=1)
        if module and module.state != "to install" and self.sudo().search_count([("code", "=", "fr_FR")]):
            module._update_translations(["fr_FR"], overwrite=True)

    @api.model
    def _ea_setup_languages(self):
        """English and French on every firm database, on install and on each update."""
        Lang = self.sudo().with_context(active_test=False)
        french = Lang.search([("code", "=", "fr_FR")], limit=1)
        was_active = bool(french.active)
        for code, values in _FORMATS.items():
            lang = Lang._activate_lang(code)
            lang.write(values)
        if not was_active:
            self.env["ir.module.module"].sudo().search([("state", "=", "installed")])._update_translations(["fr_FR"])
