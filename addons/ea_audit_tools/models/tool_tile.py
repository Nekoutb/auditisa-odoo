import re

from odoo import fields, models

from ..exports import lead_schedule_workbook, sad_workbook, simple_workbook
from ..rules import rule_error
from ..services.assertions import ASSERTIONS
from ..services.errors import ServiceError
from ..tabular import parse_table
from .tool_record import french_date, is_french


class ToolTile(models.Model):
    """A tile of the hub (m7): reference data. The engagement comes from the action's context."""

    _name = "ea.audit.tool.tile"
    _description = "Tools hub tile"
    _order = "sequence, id"

    code = fields.Char(required=True, readonly=True)
    name = fields.Char(required=True, translate=True, readonly=True)
    description = fields.Char(required=True, translate=True, readonly=True)
    feeds = fields.Char(string="Papers", readonly=True)
    method = fields.Char(readonly=True, help="The engagement method that opens the tool. Empty: not built yet.")
    sequence = fields.Integer(default=10, readonly=True)
    section = fields.Char(default="hub", readonly=True, index=True)
    available = fields.Boolean(compute="_compute_available")
    enabled_method = fields.Char(compute="_compute_available", help="The method, when an installed addon provides it.")
    subtitle = fields.Char(compute="_compute_available")

    _code_uniq = models.Constraint("UNIQUE(code)", "A tile code is unique.")

    def _compute_available(self):
        Engagement = self.env["ea.audit.engagement"]
        for tile in self:
            on = bool(tile.method) and hasattr(Engagement, tile.method)
            tile.available = on
            tile.enabled_method = tile.method if on else False
            tile.subtitle = tile.description if on else "%s %s" % (tile.description, self.env._("(coming)"))

    def action_open_tool(self):
        self.ensure_one()
        engagement = self.env["ea.audit.engagement"].browse(self.env.context.get("ea_engagement_id"))
        engagement._ea_require_access()
        if not self.method or not hasattr(engagement, self.method):
            raise rule_error(self.env, "tool-not-available")
        if not self.method.startswith("action_tool_"):
            raise rule_error(self.env, "forbidden")
        return getattr(engagement, self.method)()


class EngagementTools(models.Model):
    _inherit = "ea.audit.engagement"

    def action_tool_review_notes(self):
        """The file's review notes: section, owner, state and turnaround."""
        return self._ea_list(
            "ea.audit.review.note", self.env._("Review notes"),
            [("ea_audit_tools.view_review_note_register", "list")],
            {"context": {"ea_engagement_id": self.id, "create": False, "group_by": ["state"]}},
        )

    def action_tool_forms(self):
        """Every paper of the file by phase, and who it is assigned to. Opening a row opens its paper."""
        return self._ea_list(
            "ea.audit.file.item", self.env._("Forms"),
            [("ea_audit_tools.view_forms_register", "list")],
            {
                "domain": [("engagement_id", "=", self.id)],
                "context": {"ea_engagement_id": self.id, "create": False, "group_by": ["task_phase"]},
            },
        )

    def action_open_tools(self):
        """/engagements/[id]/tools."""
        self.ensure_one()
        self._ea_require_access()
        as_root = self.sudo()
        year = self.env._("Fiscal year")
        return {
            "type": "ir.actions.act_window",
            "name": "%s — %s · %s %s" % (self.env._("Tools"), as_root.client_id.name, year, as_root.fiscal_year),
            "res_model": "ea.audit.tool.tile",
            "view_mode": "kanban",
            "views": [(self.env.ref("ea_audit_tools.view_tool_tile_kanban").id, "kanban")],
            "target": "current",
            "domain": [("section", "=", "hub")],
            "context": {"ea_engagement_id": self.id, "create": False},
        }

    # ------------------------------------------------------------------
    # Excel. Every export is on the trail, and a refusal says why.
    # ------------------------------------------------------------------

    def _ea_identity(self):
        as_root = self.sudo()
        return {
            "engagement": as_root.name or as_root.client_id.name,
            "client": as_root.client_id.name,
            "period_end": french_date(as_root.period_end),
            "generated": french_date(fields.Date.context_today(self)),
        }

    def ea_export_xlsx(self, kind):
        """(filename, bytes) of one workbook. Read rights: any accepted member, EQR included."""
        self.ensure_one()
        self._ea_require_access()
        method = self._ea_export_dynamic_method(kind) or self._ea_export_method(kind)
        if method is None:
            raise rule_error(self.env, "not-found")
        # An export is a document of the engagement: its report language, whoever asks.
        self = self.with_context(lang=self._ea_report_lang_code())
        method = self._ea_export_dynamic_method(kind) or self._ea_export_method(kind)
        filename, content = method(self._ea_report_fr())
        self._ea_log("exported", "%s exported by %s" % (filename, self.env.user.name))
        return filename, content

    def _ea_export_method(self, kind):
        return getattr(self, "_ea_export_%s" % kind, None) if re.fullmatch(r"[a-z_]+", kind or "") else None

    def _ea_export_slug(self):
        return re.sub(r"[^\w-]+", "_", self.sudo().name or self.sudo().client_id.name or "file")[:60]

    def _ea_export_lead(self, fr):
        as_root = self.sudo()
        schedules = as_root._ea_ap_lead_schedules()
        if not schedules:
            raise rule_error(self.env, "no-tb")
        comments = {
            "%s|%s" % (c.index_code, c.account): c.body
            for c in self.env["ea.audit.ap.comment"].sudo().search([("engagement_id", "=", self.id)])
        }
        return "lead-schedules-%s.xlsx" % self._ea_export_slug(), lead_schedule_workbook(schedules, comments, self._ea_identity(), fr)

    def _ea_export_sad(self, fr):
        view = self._ea_sad_view()
        name = re.sub(r"[^\w-]+", "_", view["entityName"])
        return "SAD-%s-%s.xlsx" % (name, view["periodEnd"]), sad_workbook(view, fr)

    def _ea_export_materiality(self, fr):
        rows = []
        for version in self.sudo().materiality_ids.sorted("version_no"):
            rows.append([
                version.version_no, dict(version._fields["state"]._description_selection(self.env)).get(version.state),
                dict(version._fields["benchmark"]._description_selection(self.env)).get(version.benchmark),
                version.benchmark_amount, version.percentage, version.overall, version.performance_pct, version.performance,
                version.trivial_pct, version.trivial, version.justification, version.performance_justification or "",
                version.approved_by_id.name or "", french_date(version.approved_at),
            ])
        head = (
            ["Version", "État", "Base", "Montant", "%", "Seuil global", "% travail", "Seuil de travail", "% manifestement négligeable", "Manifestement négligeable", "Justification", "Justification du seuil de travail", "Approuvé par", "Approuvé le"]
            if fr else
            ["Version", "Status", "Benchmark", "Amount", "%", "Overall", "Performance %", "Performance", "Trivial %", "Trivial", "Justification", "Performance justification", "Approved by", "Approved on"]
        )
        return "materiality-%s.xlsx" % self._ea_export_slug(), simple_workbook("Seuil" if fr else "Materiality", head, rows)

    def _ea_export_significance(self, fr):
        self.sudo()._ea_sync_significance(activity=False)
        rows = []
        for record in self.env["ea.audit.significance"].sudo().search([("engagement_id", "=", self.id)]):
            rows.append([
                record.index_code, record.closing,
                record.tx_count if record.activity_dataset else "",
                record.preparer_count if record.preparer_known else "",
                record.reviewer_count if record.reviewer_known else "",
                record.status or "", record.default_status or "", record.justification or "",
                ", ".join(record.assertion_ids.mapped("code")), record.specific_te or "", record.risk_assertions or "",
            ])
        head = SIGNIFICANCE_HEAD
        return "significant-accounts-%s.xlsx" % self._ea_export_slug(), simple_workbook("P6.2", head, rows)

    def _ea_export_risks(self, fr):
        rows = []
        for risk in self.env["ea.audit.risk"].sudo().with_context(lang=self.env.lang).search([("engagement_id", "=", self.id)]):
            rows.append([
                risk.title, risk.category or "", risk.level, risk.likelihood, risk.magnitude, risk.inherent_rating,
                "yes" if risk.significant else "no", "yes" if risk.rebutted else "no", risk.status, risk.index_summary or "",
                risk.linked_step_count,
            ])
        return "risks-%s.xlsx" % self._ea_export_slug(), simple_workbook("Risques" if fr else "Risks", RISK_HEAD, rows)

    def _ea_export_cra(self, fr):
        self.sudo()._ea_sync_cra()
        rows = []
        cells = self.env["ea.audit.cra.assessment"].sudo().search([("engagement_id", "=", self.id)])
        for cell in cells:
            rows.append([
                cell.index_code, cell.assertion, "yes" if cell.relevant else "no", cell.ir or "", cell.ir_basis or "",
                cell.cr or "", cell.cr_basis or "", cell.level or "", cell.tod_level or "",
            ])
        return "cra-%s.xlsx" % self._ea_export_slug(), simple_workbook("CRA", CRA_HEAD, rows)

    def _ea_export_findings(self, fr):
        rows = []
        for finding in self.env["ea.audit.finding"].sudo().with_context(lang=self.env.lang).search([("engagement_id", "=", self.id)]):
            rows.append([
                finding.reference, finding.title, finding.file_item_id.code or "", finding.route, finding.severity or "",
                finding.amount or "", finding.state_label, finding.detail or "", finding.recommendation or "",
                finding.management_response or "", str(finding.communicated_on or ""),
            ])
        head = (
            ["N°", "Constat", "Papier", "Voie", "Gravité", "Montant", "État", "Détail", "Recommandation", "Réponse de la direction", "Communiqué le"]
            if fr else
            ["No.", "Finding", "Paper", "Route", "Severity", "Amount", "State", "Detail", "Recommendation", "Management response", "Communicated on"]
        )
        return "findings-%s.xlsx" % self._ea_export_slug(), simple_workbook("Constats" if fr else "Findings", head, rows)

    # ------------------------------------------------------------------
    # Excel import, the first form of the grids (I-6). All or nothing: one
    # refused row refuses the file, through the same method a screen uses.
    # ------------------------------------------------------------------

    def ea_import_xlsx(self, kind, filename, content):
        self.ensure_one()
        self._ea_tool_guard()
        try:
            table = parse_table(filename, content)
        except ServiceError as error:
            raise rule_error(self.env, error.code) from error
        method = {"cra": self._ea_import_cra, "significance": self._ea_import_significance, "risks": self._ea_import_risks}.get(kind)
        if not method and kind in self._ea_extra_import_kinds():
            method = getattr(self, "_ea_import_%s" % kind)
        if not method:
            raise rule_error(self.env, "not-found")
        return method(table)

    def _ea_extra_import_kinds(self):
        """The later tools that take a workbook back."""
        return ("dsp", "pbc")

    def _ea_import_cra(self, table):
        self.sudo()._ea_sync_cra()
        Cell = self.env["ea.audit.cra.assessment"]
        count = 0
        for row in table["rows"]:
            index_code = (row.get("index") or "").strip()
            assertion = (row.get("assertion") or "").strip()
            if assertion not in ASSERTIONS:
                raise rule_error(self.env, "invalid-assertion")
            cell = Cell.sudo().search([
                ("engagement_id", "=", self.id), ("index_code", "=", index_code), ("assertion", "=", assertion),
            ], limit=1)
            if not cell:
                raise rule_error(self.env, "invalid-index")
            patch = {"relevant": (row.get("relevant") or "yes").strip().lower() in ("yes", "oui", "1", "true")}
            for key in ("ir", "cr"):
                value = (row.get(key) or "").strip()
                if value and value not in ({"lower", "higher"} if key == "ir" else {"rely", "not_rely"}):
                    raise rule_error(self.env, "invalid-value")
                if value:
                    patch[key] = value
            for key in ("ir_basis", "cr_basis", "reason"):
                if row.get(key):
                    patch[key] = row[key].strip()
            cell.with_env(self.env)._ea_save_cell(patch)
            count += 1
        return count

    def _ea_import_significance(self, table):
        self.sudo()._ea_sync_significance(activity=False)
        Significance = self.env["ea.audit.significance"]
        count = 0
        for row in table["rows"]:
            record = Significance.sudo().search([
                ("engagement_id", "=", self.id), ("index_code", "=", (row.get("index") or "").strip()),
            ], limit=1)
            if not record:
                raise rule_error(self.env, "invalid-index")
            vals = {}
            if (row.get("status") or "").strip():
                vals["status"] = row["status"].strip()
            if "justification" in row:
                vals["justification"] = row["justification"]
            if row.get("assertions") is not None:
                codes = [code.strip() for code in row["assertions"].split(",")]
                vals["assertion_ids"] = [(6, 0, self.env["ea.audit.assertion"]._ea_from_codes(codes).ids)]
            if (row.get("specific_te") or "").strip():
                vals["specific_te"] = float(row["specific_te"])
            record.with_env(self.env)._ea_save(vals)
            count += 1
        return count

    def _ea_import_risks(self, table):
        count = 0
        for row in table["rows"]:
            self.add_risk(
                row.get("description"),
                category=(row.get("category") or "business").strip(),
                level=(row.get("level") or "assertion").strip(),
                likelihood=(row.get("likelihood") or "").strip() or None,
                magnitude=(row.get("magnitude") or "").strip() or None,
                significant=(row.get("significant") or "").strip().lower() in ("yes", "oui", "1", "true"),
                index=(row.get("index") or "").strip() or None,
                assertions=[code.strip() for code in (row.get("assertions") or "").split(",") if code.strip()],
                source=row.get("source"),
            )
            count += 1
        return count


# The columns of the three registers that come back in: the same words in and out.
# transactions, preparers and reviewers are counted from the ledger: an import reads them not
SIGNIFICANCE_HEAD = ["index", "closing", "transactions", "preparers", "reviewers", "status", "default", "justification", "assertions", "specific_te", "risk_assertions"]
RISK_HEAD = ["description", "category", "level", "likelihood", "magnitude", "rating", "significant", "rebutted", "status", "indexes", "steps"]
CRA_HEAD = ["index", "assertion", "relevant", "ir", "ir_basis", "cr", "cr_basis", "level", "tod"]
