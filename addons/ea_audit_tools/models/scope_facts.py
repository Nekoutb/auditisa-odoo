"""Reliance on controls, the fact behind the controls tasks (owner's table of 2026-11-17): S2.1 to
S2.5, E1.1, E1.2 and E2.1 come onto a file of the current scope only when its strategy relies on
controls. The strategy is read where it is decided: a SCOT tested through its controls, a CRA cell
set to rely, or an IT application whose controls are relied on. Adds only: a task stays once on."""

from odoo import api, models

from odoo.addons.ea_audit_core.services.file_scope import CONTROLS_CODES

RELYING_IT_STRATEGIES = ("rely_itgc", "test_direct")


class Engagement(models.Model):
    _inherit = "ea.audit.engagement"

    def _ea_relies_on_controls(self):
        self.ensure_one()
        env = self.env
        return bool(
            env["ea.audit.scot"].sudo().search_count([("engagement_id", "=", self.id), ("strategy", "=", "controls")])
            or env["ea.audit.cra.assessment"].sudo().search_count([("engagement_id", "=", self.id), ("cr", "=", "rely")])
            or env["ea.audit.it.application"].sudo().search_count([
                ("engagement_id", "=", self.id), ("strategy", "in", RELYING_IT_STRATEGIES), ("removed", "=", False),
            ])
        )

    def _ea_fact_codes(self):
        facts = super()._ea_fact_codes()
        if self._ea_relies_on_controls():
            for code in CONTROLS_CODES:
                facts.setdefault(code, "the strategy relies on controls")
        return facts


def _relying(vals, field, values):
    return vals.get(field) in values


class _RelianceWatch(models.AbstractModel):
    """A record whose field says the strategy relies on controls: saving that value brings the
    controls tasks onto the file."""

    _name = "ea.audit.reliance.watch"
    _description = "Reliance on controls watch"
    _ea_reliance_field = None
    _ea_reliance_values = ()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if any(_relying(vals, self._ea_reliance_field, self._ea_reliance_values) for vals in vals_list):
            records.sudo().engagement_id._ea_apply_scope_facts()
        return records

    def write(self, vals):
        result = super().write(vals)
        if _relying(vals, self._ea_reliance_field, self._ea_reliance_values):
            self.sudo().engagement_id._ea_apply_scope_facts()
        return result


class Scot(models.Model):
    _name = "ea.audit.scot"
    _inherit = ["ea.audit.scot", "ea.audit.reliance.watch"]
    _ea_reliance_field = "strategy"
    _ea_reliance_values = ("controls",)


class CraAssessment(models.Model):
    _name = "ea.audit.cra.assessment"
    _inherit = ["ea.audit.cra.assessment", "ea.audit.reliance.watch"]
    _ea_reliance_field = "cr"
    _ea_reliance_values = ("rely",)


class ItApplication(models.Model):
    _name = "ea.audit.it.application"
    _inherit = ["ea.audit.it.application", "ea.audit.reliance.watch"]
    _ea_reliance_field = "strategy"
    _ea_reliance_values = RELYING_IT_STRATEGIES
