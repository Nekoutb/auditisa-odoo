from odoo import api, models

# Both languages read DD/MM/YYYY; the separators follow the language.
_FORMATS = {
    "en_US": {"date_format": "%d/%m/%Y", "time_format": "%H:%M:%S", "decimal_point": ".", "thousands_sep": ",", "grouping": "[3,0]"},
    "fr_FR": {"date_format": "%d/%m/%Y", "time_format": "%H:%M:%S", "decimal_point": ",", "thousands_sep": "\u00a0", "grouping": "[3,0]"},
}


class ResLang(models.Model):
    _inherit = "res.lang"

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
