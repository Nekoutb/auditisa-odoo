"""JeSelectionStudio, native: criteria and thresholds as fields, rules as lines, results server-rendered."""
from markupsafe import Markup

from odoo import api, fields, models

from ..models.tool_record import fcfa, is_french
from ..rules import rule_error
from ..services.je_catalogue import JE_CRITERIA, PAIRINGS, RULE_FIELDS, RULE_OPERATOR_LABELS

_CRITERIA = [c["key"] for c in JE_CRITERIA if c["key"] != "user-defined"]


def _field_name(key):
    return "use_%s" % key.replace("-", "_")


def _pair_name(key):
    return "pair_%s" % key.replace("-", "_")


class JeStudio(models.TransientModel):
    _name = "ea.audit.je.studio"
    _description = "Journal-entry selection studio"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    dataset_id = fields.Many2one("ea.audit.dataset", string="Ledger", domain="[('engagement_id', '=', engagement_id), ('kind', '=', 'journal_entries'), ('superseded_at', '=', False), ('timing', '!=', 'subsequent')]")
    limit = fields.Selection([("50", "50"), ("200", "200"), ("500", "500")], string="Lines per page", default="200", required=True)
    offset = fields.Integer(default=0)
    date_basis = fields.Selection([("journal", "Journal date"), ("entry", "Entry (recording) date")], string="Date tested", default="journal", required=True)
    country = fields.Char(default="CM", help="ISO two-letter code of the calendar to read. CM (Cameroon) is the seeded one.")
    round_min = fields.Float(string="Minimum absolute amount", digits=(18, 2), default=100000)
    round_step = fields.Float(string="Multiple of", digits=(18, 2), default=100000)
    top_entries = fields.Integer(string="How many entries", default=5)
    year_end_days = fields.Integer(string="Closing window (days)", default=15)
    volume_basis = fields.Selection([("lines", "Number of lines"), ("value", "Gross value")], string="Volume measured by", default="lines", required=True)
    min_chars = fields.Integer(string="Minimum characters", default=10)
    min_words = fields.Integer(string="Minimum words", default=2)
    rules_mode = fields.Selection([("any", "Any rule"), ("all", "All rules")], string="Rules combine", default="any", required=True)
    rule_ids = fields.One2many("ea.audit.je.studio.rule", "studio_id", string="The auditor's own rules")
    result_html = fields.Html(sanitize=False, readonly=True)
    result_truncated = fields.Boolean(readonly=True)
    designs_count = fields.Integer(string="Designs recorded", compute="_compute_designs_count")
    prerequisites_html = fields.Html(string="Prerequisites", compute="_compute_prerequisites_html", sanitize=False, compute_sudo=True)

    for _criterion in JE_CRITERIA:
        if _criterion["key"] != "user-defined":
            locals()[_field_name(_criterion["key"])] = fields.Boolean(string=_criterion["nameEn"], help=_criterion["rationaleEn"], default=True)
    for _pairing in PAIRINGS:
        locals()[_pair_name(_pairing["key"])] = fields.Boolean(string=_pairing["labelEn"], default=True)
    del _criterion, _pairing

    @api.depends_context("lang")
    def _compute_display_name(self):
        """A title for the breadcrumb, not the record's technical id."""
        for studio in self:
            studio.display_name = self.env._("Journal entries")

    @api.depends("engagement_id")
    @api.depends_context("lang")
    def _compute_prerequisites_html(self):
        for studio in self:
            studio.prerequisites_html = studio.engagement_id._ea_prerequisites_html()

    @api.depends("engagement_id")
    def _compute_designs_count(self):
        for studio in self:
            studio.designs_count = self.env["ea.audit.je.design"].sudo().search_count([("engagement_id", "=", studio.engagement_id.id)])

    def _ea_request(self):
        """The body the studio sends. Every threshold is clamped again in resolve_settings."""
        self.ensure_one()
        return {
            "criteria": [key for key in _CRITERIA if self[_field_name(key)]],
            "params": {
                "locale": "fr" if is_french(self.env) else "en", "dateBasis": self.date_basis, "country": self.country,
                "roundMin": self.round_min, "roundStep": self.round_step, "topEntries": self.top_entries, "yearEndDays": self.year_end_days,
                "volumeBasis": self.volume_basis, "minDescriptionChars": self.min_chars, "minDescriptionWords": self.min_words,
                "pairings": [p["key"] for p in PAIRINGS if self[_pair_name(p["key"])]],
            },
            "userRules": [line._ea_rule() for line in self.rule_ids],
            "userRulesMode": self.rules_mode,
            "limit": int(self.limit),
            "offset": self.offset,
        }

    def _ea_reopen(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id, "view_mode": "form", "target": "current",
            "name": self.env._("Journal entries: risk-directed selection"), "context": {"ea_engagement_id": self.engagement_id.id},
        }

    def _ea_require_dataset(self):
        if not self.dataset_id:
            raise rule_error(self.env, "no-dataset")
        return self.dataset_id

    def _ea_render(self):
        result = self.engagement_id.je_run_selection(self._ea_require_dataset().id, self._ea_request())
        self.write({"result_html": self._ea_result_html(result), "result_truncated": result["truncated"]})

    def _ea_result_html(self, result):
        fr = is_french(self.env)
        population = result["population"]
        head = Markup("<p><b>{a}</b> {b} · <b>{c}</b> {d} · {e} {f}</p>").format(
            a=result["selectedLines"], b="ligne(s) retenue(s)" if fr else "line(s) selected",
            c=result["selectedEntries"], d="écriture(s)" if fr else "entries",
            e="population :" if fr else "population:",
            f=("%s lignes, %s écritures" if fr else "%s lines, %s entries") % (population["lines"], population["entries"]),
        )
        notes = Markup("").join(Markup("<p class='o_ea_legend'>{}</p>").format(note) for note in result["notes"])
        coverage = Markup("").join(
            Markup("<tr><td>{a}</td><td class='text-end'>{b}</td><td class='text-end'>{c}</td></tr>").format(a=row["name"], b=row["matchedLines"], c=row["matchedEntries"])
            for row in result["criteria"]
        )
        lines = Markup("").join(
            Markup(
                "<tr><td>{a}</td><td>{b}</td><td>{c}</td><td>{d}</td><td class='text-end'>{e}</td><td>{f}</td><td>{g}</td></tr>"
            ).format(
                a=line["jeNumber"], b=line["lineNo"], c=line["account"],
                d="%s/%s/%s" % (line["journalDate"][8:10], line["journalDate"][5:7], line["journalDate"][:4]) if line["journalDate"] else "",
                e=fcfa(line["signed"]), f=line["lineDescription"] or line["jeDescription"] or "",
                g=Markup("<br/>").join("%s : %s" % (reason["label"], reason["detail"]) for reason in line["reasons"]),
            )
            for line in result["lines"]
        )
        titles = ["Écriture", "Ligne", "Compte", "Date", "Montant", "Libellé", "Motifs"] if fr else ["Entry", "Line", "Account", "Date", "Amount", "Description", "Reasons"]
        return Markup(
            "{head}{notes}<table class='table table-sm o_ea_table'><thead><tr><th>{c}</th><th class='text-end'>{l}</th><th class='text-end'>{e}</th></tr></thead><tbody>{coverage}</tbody></table>"
            "<div class='table-responsive'><table class='table table-sm o_ea_table'><thead><tr>{titles}</tr></thead><tbody>{lines}</tbody></table></div>"
        ).format(
            head=head, notes=notes, c="Critère" if fr else "Criterion", l="Lignes" if fr else "Lines", e="Écritures" if fr else "Entries", coverage=coverage,
            titles=Markup("").join(Markup("<th>{}</th>").format(title) for title in titles), lines=lines,
        )

    def action_run(self):
        self.ensure_one()
        self.offset = 0
        self._ea_render()
        return self._ea_reopen()

    def action_next(self):
        self.ensure_one()
        self.offset = self.offset + int(self.limit)
        self._ea_render()
        return self._ea_reopen()

    def action_previous(self):
        self.ensure_one()
        self.offset = max(0, self.offset - int(self.limit))
        self._ea_render()
        return self._ea_reopen()

    def action_record(self):
        self.ensure_one()
        self.engagement_id.je_record_design(self._ea_require_dataset().id, self._ea_request())
        return self._ea_reopen()

    def action_export(self):
        self.ensure_one()
        return self.engagement_id._ea_export_action("je_studio_%d" % self.id)

    def action_designs(self):
        self.ensure_one()
        return self.engagement_id.action_open_je_designs()

    def action_open_page(self):
        """The journal-entry page on this studio's criteria."""
        self.ensure_one()
        return {
            "type": "ir.actions.client", "tag": "ea_audit_tools.je_page", "target": "current",
            "name": self.env._("Journal entries"),
            "params": {"engagement_id": self.engagement_id.id, "studio_id": self.id},
            "context": {"active_id": self.engagement_id.id, "ea_engagement_id": self.engagement_id.id},
        }

    def ea_open(self, method):
        """The page's links to the studio's own screens."""
        self.ensure_one()
        if method not in ("_ea_reopen", "action_export", "action_designs", "action_import_ledger"):
            raise rule_error(self.env, "forbidden")
        return getattr(self, method)()

    def action_import_ledger(self):
        self.ensure_one()
        return self.engagement_id.action_tool_gl()


class JeStudioRule(models.TransientModel):
    _name = "ea.audit.je.studio.rule"
    _description = "Auditor rule of the selection studio"

    studio_id = fields.Many2one("ea.audit.je.studio", required=True, ondelete="cascade")
    field = fields.Selection([(f["key"], f["labelEn"]) for f in RULE_FIELDS], string="Column", required=True, default="account")
    operator = fields.Selection([(key, value["en"]) for key, value in RULE_OPERATOR_LABELS.items()], required=True, default="equals")
    value = fields.Char()
    value2 = fields.Char(string="Second bound")

    def _ea_rule(self):
        self.ensure_one()
        return {"id": "r%d" % self.id, "field": self.field, "operator": self.operator, "value": self.value or None, "value2": self.value2 or None}

