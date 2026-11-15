import inspect

from odoo.tools.translate import _get_lang

from odoo import api, fields, models

from ..rules import rule_error
from ..services.assertions import ASSERTIONS
from ..services.lead_classes import LEAD_INDEXES, lead_index_label


def is_french(env):
    return (env.lang or env.context.get("lang") or "").startswith("fr")


def grouped(amount, lang=None):
    """No decimals; the separator follows the language: of ``lang``, else of the caller's
    environment found as odoo's _ finds it. French groups with a space, English with a comma."""
    if lang is None:
        lang = _get_lang(inspect.currentframe().f_back)
    digits = "{:,.0f}".format(amount)
    return digits.replace(",", " ") if (lang or "").startswith("fr") else digits


def fcfa(amount, lang=None):
    """formatFCFA: no decimals, grouped as the language groups."""
    if amount is None or amount is False:
        return "—"
    negative = round(amount) < 0  # -0.4 reads 0, never -0 (F019)
    if lang is None:
        lang = _get_lang(inspect.currentframe().f_back)
    return "%s%s FCFA" % ("-" if negative else "", grouped(abs(amount), lang))


def decimal_label(value, lang=None):
    """A number with its decimal mark as the language writes it: 0,3 in French, 0.3 in English."""
    if lang is None:
        lang = _get_lang(inspect.currentframe().f_back)
    text = str(value)
    return text.replace(".", ",") if (lang or "").startswith("fr") else text


def french_date(value):
    return value.strftime("%d/%m/%Y") if value else ""


def upload_stamp(record, moment):
    """The date and time of an upload, in the reader's time zone: how a person tells one
    version of a file from another."""
    return fields.Datetime.context_timestamp(record, moment).strftime("%d/%m/%Y %H:%M") if moment else ""


class ToolRecord(models.AbstractModel):
    """Every record of the tools. Nothing reaches the database through the plain
    ORM entry points: create, write and unlink route a user's call to the
    rule-bearing methods below, which guard and then write as superuser, the only
    path where env.su is true. No context key relaxes anything."""

    _name = "ea.audit.tool.record"
    _inherit = ["ea.audit.engagement.mixin"]
    _description = "Tools record"

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.su:
            return super().create(vals_list)
        return self._ea_user_create(vals_list)

    def write(self, vals):
        if self.env.su:
            return super().write(vals)
        return self._ea_user_write(vals)

    def unlink(self):
        if self.env.su:
            return super().unlink()
        return self._ea_user_unlink()

    def _ea_user_create(self, vals_list):
        raise rule_error(self.env, "forbidden")

    def _ea_user_write(self, vals):
        raise rule_error(self.env, "forbidden")

    def _ea_user_unlink(self):
        raise rule_error(self.env, "forbidden")

    def _ea_guard(self):
        """The guard of a write on these records: see Engagement._ea_tool_guard."""
        for engagement in self.sudo().engagement_id.with_env(self.env):
            engagement._ea_tool_guard()

    def _ea_only(self, vals, allowed):
        if set(vals) - set(allowed):
            raise rule_error(self.env, "invalid-field")

    @api.model
    def _lead_index_selection(self):
        fr = is_french(self.env)
        return [
            (d["code"], "%s %s" % (d["code"], lead_index_label(d, "fr" if fr else "en")))
            for d in LEAD_INDEXES
        ]


ASSERTION_SELECTION = [(code, code) for code in ASSERTIONS]


class Assertion(models.Model):
    """The six assertions of lib/assertions.ts, as tags. Reference data, no engagement."""

    _name = "ea.audit.assertion"
    _description = "Audit assertion"
    _order = "sequence, id"
    _rec_name = "code"

    code = fields.Char(required=True, readonly=True)
    name = fields.Char(required=True, translate=True, readonly=True)
    sequence = fields.Integer(default=10, readonly=True)

    _code_uniq = models.Constraint("UNIQUE(code)", "An assertion code is unique.")

    @api.depends("code", "name")
    @api.depends_context("lang")
    def _compute_display_name(self):
        """F041: a picker and a tag read "C — Completeness", never the bare letter."""
        for assertion in self:
            assertion.display_name = "%s — %s" % (assertion.code, assertion.name)

    @api.model
    def _ea_from_codes(self, codes):
        wanted = [code for code in codes if code in ASSERTIONS]
        return self.sudo().search([("code", "in", wanted)])
