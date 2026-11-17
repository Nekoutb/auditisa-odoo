"""Reliance on controls, the fact behind the controls tasks (owner's table of 2026-11-17): S2.1 to
S2.5, E1.1, E1.2 and E2.1 are on a file of the current scope only while its strategy relies on
controls. The strategy is read where it is decided: a SCOT tested through its controls, a CRA cell
set to rely, or an IT application whose controls are relied on.

The tasks follow the reliance both ways (owner's ruling of 2026-11-17 evening: "remove if not
relying on controls, maintain if relying on controls"). When the strategy stops relying, a controls
task holding no work leaves the file (hidden, as a task waiting for its fact), and a task holding
work stays readable, marked not applicable with the reason; nothing is deleted. When the reliance
comes back, the tasks return with their work intact. Each move is written to the activity trail,
and an archived file is never touched."""

from odoo import api, fields, models

from odoo.addons.ea_audit_core.services.file_scope import CONTROLS_CODES, SCOPE_CURRENT

RELYING_IT_STRATEGIES = ("rely_itgc", "test_direct")

NO_RELIANCE_REASON = (
    "The strategy no longer relies on controls",
    "La stratégie ne s'appuie plus sur les contrôles",
)


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

    def _ea_controls_task_holds_work(self, item):
        """Answers, evidence, a conclusion, a sign-off, or a review note (open or cleared)."""
        return bool(self._ea_task_holds_work(item) or item.sudo().review_note_ids)

    def _ea_follow_controls_reliance(self):
        """The controls tasks follow the strategy, on each open file of the current scope."""
        for engagement in self.exists():
            root = engagement.sudo()
            if root._ea_scope_version() < SCOPE_CURRENT or root._ea_is_archived() or not root.complexity:
                continue
            if root._ea_relies_on_controls():
                engagement._ea_controls_tasks_return()
                root._ea_apply_scope_facts()
            else:
                engagement._ea_controls_tasks_leave()
        return True

    def _ea_controls_tasks_leave(self):
        """Hidden when it holds no work; kept, readable and not applicable, when it does."""
        self.ensure_one()
        root = self.sudo()
        items = self.env["ea.audit.file.item"].sudo().search([
            ("engagement_id", "=", root.id), ("code", "in", list(CONTROLS_CODES)), ("conditional", "=", False),
            ("controls_na", "=", False),
        ])
        if not items:
            return
        # a controls task the profile questionnaire switched on stays: its fact still exists
        keep = set(root._ea_fact_codes())
        hidden, kept = [], []
        reason = root._ea_pick(*NO_RELIANCE_REASON)
        for item in items.filtered(lambda i: i.code not in keep):
            if not root._ea_controls_task_holds_work(item):
                item.conditional = True
                hidden.append(item.code)
            elif not item.not_applicable:
                item.write({
                    "not_applicable": True, "na_reason": reason, "na_by_id": self.env.user.id,
                    "na_at": fields.Datetime.now(), "controls_na": True,
                })
                item._ea_paper()._ea_trail(
                    "marked_not_applicable", "%s marked not applicable: %s" % (item.code, NO_RELIANCE_REASON[0]),
                )
                kept.append(item.code)
        if hidden or kept:
            self._ea_log("tasks_off_by_reliance", (
                "The strategy no longer relies on controls. Taken off the file, holding no work: %s. "
                "Kept as not applicable, holding work: %s"
            ) % (", ".join(sorted(hidden)) or "-", ", ".join(sorted(kept)) or "-"))

    def _ea_controls_tasks_return(self):
        """The tasks marked not applicable when the reliance stopped are applicable again, their
        work as it was. The hidden ones come back through their fact (_ea_apply_scope_facts)."""
        self.ensure_one()
        items = self.env["ea.audit.file.item"].sudo().search([
            ("engagement_id", "=", self.id), ("controls_na", "=", True),
        ])
        if not items:
            return
        items.write({"not_applicable": False, "na_reason": False, "na_by_id": False, "na_at": False, "controls_na": False})
        for item in items:
            item._ea_paper()._ea_trail("na_cleared", "%s no longer marked not applicable" % item.code)
        self._ea_log(
            "tasks_back_by_reliance",
            "The strategy relies on controls again. Applicable again, work kept: %s" % ", ".join(sorted(items.mapped("code"))),
        )


class FileItem(models.Model):
    _inherit = "ea.audit.file.item"

    controls_na = fields.Boolean(
        string="Not applicable because the strategy no longer relies on controls", readonly=True, copy=False,
        help="Set and cleared by the file itself: the task becomes applicable again when the strategy relies on controls.",
    )

    def set_not_applicable(self, reason="", clear=False):
        """A person's own decision replaces the one the strategy made."""
        result = super().set_not_applicable(reason=reason, clear=clear)
        if self.sudo().controls_na:
            self.sudo().controls_na = False
        return result


def _relying(vals, field, values):
    return vals.get(field) in values


class _RelianceWatch(models.AbstractModel):
    """A record whose field says whether the strategy relies on controls: saving it, or deleting the
    record, brings the controls tasks onto the file or takes them off. A person's edit reaches the
    database through the superuser path of ea.audit.tool.record, so the watch acts there, once."""

    _name = "ea.audit.reliance.watch"
    _description = "Reliance on controls watch"
    _ea_reliance_field = None
    _ea_reliance_values = ()
    _ea_reliance_other_fields = ()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if any(_relying(vals, self._ea_reliance_field, self._ea_reliance_values) for vals in vals_list):
            records.sudo().engagement_id._ea_apply_scope_facts()
        return records

    def write(self, vals):
        watched = {self._ea_reliance_field, "engagement_id", *self._ea_reliance_other_fields}
        engagements = self.sudo().engagement_id if self.env.su and watched & set(vals) else None
        result = super().write(vals)
        if engagements is not None:
            (engagements | self.sudo().engagement_id)._ea_follow_controls_reliance()
        return result

    def unlink(self):
        engagements = self.sudo().engagement_id if self.env.su else None
        result = super().unlink()
        if engagements is not None:
            engagements._ea_follow_controls_reliance()
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


class CraRow(models.Model):
    """A row takes its cells with it (database cascade), which their own unlink never sees."""

    _inherit = "ea.audit.cra.row"

    def unlink(self):
        engagements = self.sudo().engagement_id if self.env.su else None
        result = super().unlink()
        if engagements is not None:
            engagements._ea_follow_controls_reliance()
        return result


class ItApplication(models.Model):
    _name = "ea.audit.it.application"
    _inherit = ["ea.audit.it.application", "ea.audit.reliance.watch"]
    _ea_reliance_field = "strategy"
    _ea_reliance_values = RELYING_IT_STRATEGIES
    _ea_reliance_other_fields = ("removed",)
