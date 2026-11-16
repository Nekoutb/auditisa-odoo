import inspect

from odoo.tools.translate import _get_lang

from odoo import api, fields, models
from odoo.tools.translate import LazyTranslate

from ..rules import rule_error
from ..services.assertions import ASSERTIONS
from ..services.lead_classes import LEAD_INDEXES, lead_index_label


def is_french(env):
    return (env.lang or env.context.get("lang") or "").startswith("fr")


def bracketed(text):
    """A negative figure as an accountant writes it: (1 250), not -1 250 (owner, 2026-11-15).
    A figure that rounds to nothing loses its sign: -0 reads 0."""
    if not text.startswith("-"):
        return text
    digits = text[1:]
    return "(%s)" % digits if any(c in "123456789" for c in digits) else digits


def grouped(amount, lang=None):
    """No decimals; the separator follows the language: of ``lang``, else of the caller's
    environment found as odoo's _ finds it. French groups with a space, English with a comma.
    A negative reads in brackets."""
    if lang is None:
        lang = _get_lang(inspect.currentframe().f_back)
    digits = "{:,.0f}".format(amount)
    return bracketed(digits.replace(",", " ") if (lang or "").startswith("fr") else digits)


def fcfa(amount, lang=None):
    """formatFCFA: no decimals, grouped as the language groups, a negative in brackets."""
    if amount is None or amount is False:
        return "—"
    negative = round(amount) < 0  # -0.4 reads 0, never -0 (F019)
    if lang is None:
        lang = _get_lang(inspect.currentframe().f_back)
    text = grouped(abs(amount), lang)
    return "(%s) FCFA" % text if negative else "%s FCFA" % text


def decimal_label(value, lang=None):
    """A number with its decimal mark as the language writes it: 0,3 in French, 0.3 in English."""
    if lang is None:
        lang = _get_lang(inspect.currentframe().f_back)
    text = str(value)
    return bracketed(text.replace(".", ",") if (lang or "").startswith("fr") else text)


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

_lt = LazyTranslate("ea_audit_tools")

# What each assertion means, in a line (the assertion picker, owner's mock-up of 2026-11-16).
ASSERTION_DESCRIPTIONS = {
    "C": _lt("All transactions and balances that should be recorded are recorded."),
    "E": _lt("Assets and liabilities exist; recorded transactions took place."),
    "A": _lt("Amounts are recorded correctly and in the right period."),
    "V": _lt("Balances are stated at appropriate amounts."),
    "P": _lt("Items are classified and disclosed properly."),
    "RO": _lt("The entity holds the rights to assets; liabilities are its obligations."),
}


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

    # One line under the name in the assertion picker; computed, so nothing is stored.
    description = fields.Char(compute="_compute_description")

    @api.depends("code")
    @api.depends_context("lang")
    def _compute_description(self):
        for assertion in self:
            source = ASSERTION_DESCRIPTIONS.get(assertion.code)
            assertion.description = self.env._(source) if source else False

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
