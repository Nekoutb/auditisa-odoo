import re

from odoo import api, fields, models

from ..rules import rule_error
from ..services.ap_schedules import ap_lead_schedules, index_resolver
from ..services.errors import ServiceError
from ..services.fs_captions import asset_basis_label, bilan_totals
from ..services.import_matching import TB_KIND, apply_reading_options
from ..services.lead_classes import LEAD_INDEX_BY_CODE, lead_schedule_alerts, sub_index_for
from ..services.significance_variance import sums_by_index
from ..services.tb_reasons import explain_tb_summary
from ..services.tb import extract_tb_rows, infer_tb_mapping, left_out_rows, preview_trial_balance, readability_of, validate_mapping, validate_tb_rows
from .tool_record import grouped, is_french, upload_stamp

TIMING_SELECTION = [
    ("pre_audit", "Pre-audit"),
    ("post_audit", "Post-audit"),
    ("prior_year", "Prior year"),
]
_ACCOUNT_PREFIX = re.compile(r"^[0-9]{1,8}$")
_SECTION_CODE = re.compile(r"^E[0-9]+.[0-9]+$")


class TrialBalance(models.Model):
    _name = "ea.audit.tb"
    _inherit = ["ea.audit.tool.record"]
    _description = "Trial balance"
    _rec_name = "engagement_id"

    currency = fields.Char(default="XAF", required=True)
    period_end = fields.Date()
    current_version_no = fields.Integer(string="Current version", default=0)
    # The highest number ever given: a deleted version's number is not given again.
    last_version_no = fields.Integer(default=0)
    version_ids = fields.One2many("ea.audit.tb.version", "tb_id", string="Versions")

    _engagement_uniq = models.Constraint("UNIQUE(engagement_id)", "An engagement has one trial balance.")


class TbVersion(models.Model):
    """One upload. A new upload supersedes a version and never rewrites it; a member who may
    import may delete one (Engagement.delete_tb_version). A person knows a version by the date
    and time of its upload: the number only orders them."""

    _name = "ea.audit.tb.version"
    _inherit = ["ea.audit.tool.record"]
    _description = "Trial balance version"
    _order = "version_no desc"
    _rec_name = "source_filename"

    tb_id = fields.Many2one("ea.audit.tb", required=True, ondelete="cascade", index=True)
    version_no = fields.Integer(string="Version", required=True)
    version_kind = fields.Selection([("initial", "Import"), ("adjusted", "Adjusted"), ("final", "Final")], default="initial", required=True)
    timing = fields.Selection(TIMING_SELECTION, default="pre_audit", required=True)
    validation_status = fields.Selection([("valid", "Valid"), ("invalid", "Invalid")], required=True)
    source_filename = fields.Char(string="File")
    row_count = fields.Integer(string="Rows")
    total_debit = fields.Float(digits=(18, 2))
    total_credit = fields.Float(digits=(18, 2))
    validation_summary = fields.Json()
    superseded_at = fields.Datetime()
    line_ids = fields.One2many("ea.audit.tb.line", "version_id", string="Accounts")
    is_current = fields.Boolean(string="Drives the file", compute="_compute_is_current", compute_sudo=True)
    checks_text = fields.Text(string="Checks", compute="_compute_checks_text", compute_sudo=True)

    _version_uniq = models.Constraint("UNIQUE(tb_id, version_no)", "A version number is used once on a trial balance.")

    @api.depends("tb_id.current_version_no", "version_no")
    def _compute_is_current(self):
        for version in self:
            version.is_current = version.tb_id.current_version_no == version.version_no

    @api.depends("source_filename", "create_date")
    @api.depends_context("tz")
    def _compute_display_name(self):
        for version in self:
            version.display_name = "%s · %s" % (upload_stamp(version, version.create_date), version.source_filename or "")

    def action_delete(self):
        """The bin of a line: the confirmation first, which says what goes and what takes over."""
        self.ensure_one()
        return self.env["ea.audit.import.delete.wizard"]._ea_open(self.sudo().engagement_id.with_env(self.env), version=self)

    @api.depends("validation_summary")
    @api.depends_context("lang")
    def _compute_checks_text(self):
        labels = {
            "balanced": self.env._("Debits equal credits"),
            "openingBalanced": self.env._("Opening balances balance"),
            "closingEquation": self.env._("Closing equals opening plus movements"),
            "codification": self.env._("Account codes valid"),
        }
        for version in self:
            checks = (version.validation_summary or {}).get("checks") or {}
            lines = []
            for key, label in labels.items():
                check = checks.get(key)
                if check:
                    lines.append("%s %s" % ("OK" if check.get("ok") else "KO", label))
            if checks.get("unknownAccounts"):
                lines.append(self.env._("Unknown accounts: %(accounts)s", accounts=", ".join(str(item) for item in checks["unknownAccounts"][:20])))
            prior = checks.get("openingTiesToPrior") or {}
            if prior.get("checked"):
                lines.append(self.env._("Opening ties to prior year: %(count)s exception(s)", count=len(prior.get("exceptions") or [])))
            version.checks_text = "\n".join(lines)


class TbLine(models.Model):
    _name = "ea.audit.tb.line"
    _inherit = ["ea.audit.tool.record"]
    _description = "Trial balance row"
    _order = "version_id desc, row_no"
    _rec_name = "account_code"

    version_id = fields.Many2one("ea.audit.tb.version", required=True, ondelete="cascade", index=True)
    row_no = fields.Integer()
    account_code = fields.Char(string="Account", required=True, index=True)
    account_name = fields.Char(string="Description")
    opening_debit = fields.Float(digits=(18, 2))
    opening_credit = fields.Float(digits=(18, 2))
    debit = fields.Float(digits=(18, 2))
    credit = fields.Float(digits=(18, 2))
    opening = fields.Float(digits=(18, 2), compute="_compute_balances", store=True)
    closing = fields.Float(digits=(18, 2), compute="_compute_balances", store=True)
    raw_data = fields.Json()

    @api.depends("opening_debit", "opening_credit", "debit", "credit")
    def _compute_balances(self):
        for line in self:
            line.opening = line.opening_debit - line.opening_credit
            line.closing = line.opening + line.debit - line.credit


class GroupingRule(models.Model):
    """syscohada_grouping_rule, the methodology seed. Reference data, no engagement."""

    _name = "ea.audit.grouping.rule"
    _description = "SYSCOHADA grouping rule"
    _order = "account_prefix"
    _rec_name = "account_prefix"

    account_prefix = fields.Char(required=True, index=True)
    label = fields.Char(required=True, translate=True)
    fs_ref = fields.Char(string="FS reference")
    section_code = fields.Char(string="Section")
    priority = fields.Integer(default=0)
    source = fields.Char()
    active = fields.Boolean(default=True)


class ClientOverrideMixin(models.AbstractModel):
    """Client-scoped, as the platform: read by a member of one of the client's teams."""

    _name = "ea.audit.client.override.mixin"
    _description = "Client mapping override"

    client_id = fields.Many2one("ea.audit.client", required=True, index=True, ondelete="cascade")
    account_prefix = fields.Char(required=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise rule_error(self.env, "forbidden")
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            raise rule_error(self.env, "forbidden")
        return super().write(vals)

    def unlink(self):
        if not self.env.su:
            raise rule_error(self.env, "forbidden")
        return super().unlink()


class ClientGroupingOverride(models.Model):
    _name = "ea.audit.client.grouping.override"
    _inherit = ["ea.audit.client.override.mixin"]
    _description = "Client grouping override"
    _rec_name = "account_prefix"

    match_type = fields.Selection([("prefix", "Prefix"), ("exact", "Exact")], default="prefix", required=True)
    section_code = fields.Char(string="Section", required=True)
    rationale = fields.Char(required=True)
    active = fields.Boolean(default=True)

    _client_prefix_uniq = models.Constraint(
        "UNIQUE(client_id, match_type, account_prefix)", "This client already overrides that account.",
    )


class ClientLeadIndexOverride(models.Model):
    _name = "ea.audit.lead.index.override"
    _inherit = ["ea.audit.client.override.mixin"]
    _description = "Client lead-index override"
    _rec_name = "account_prefix"

    index_code = fields.Char(string="Lead index", required=True)

    _client_prefix_uniq = models.Constraint(
        "UNIQUE(client_id, account_prefix)", "This client already overrides that account prefix.",
    )


class EngagementTb(models.Model):
    _inherit = "ea.audit.engagement"

    tb_version_ids = fields.One2many("ea.audit.tb.version", "engagement_id", string="Trial balance versions")
    lead_override_ids = fields.Many2many("ea.audit.lead.index.override", compute="_compute_client_overrides", compute_sudo=True, string="Lead index overrides")
    grouping_override_ids = fields.Many2many("ea.audit.client.grouping.override", compute="_compute_client_overrides", compute_sudo=True, string="Section overrides")
    tb_current_label = fields.Char(string="Trial balance", compute="_compute_tb_card", compute_sudo=True)
    tb_status_label = fields.Char(string="Trial balance status", compute="_compute_tb_card", compute_sudo=True)
    bilan_fixed_assets = fields.Float(string="Fixed assets", digits=(18, 0), compute="_compute_bilan", compute_sudo=True)
    bilan_inventory = fields.Float(string="Inventory", digits=(18, 0), compute="_compute_bilan", compute_sudo=True)
    bilan_receivables = fields.Float(string="Receivables", digits=(18, 0), compute="_compute_bilan", compute_sudo=True)
    bilan_cash_assets = fields.Float(string="Cash assets", digits=(18, 0), compute="_compute_bilan", compute_sudo=True)
    bilan_total_assets = fields.Float(string="Total net assets", digits=(18, 0), compute="_compute_bilan", compute_sudo=True)
    bilan_class1 = fields.Float(string="Class 1 (credit)", digits=(18, 0), compute="_compute_bilan", compute_sudo=True)
    bilan_class4_credit = fields.Float(string="Class 4 in credit", digits=(18, 0), compute="_compute_bilan", compute_sudo=True)
    bilan_cash_liabilities = fields.Float(string="Treasury liabilities", digits=(18, 0), compute="_compute_bilan", compute_sudo=True)
    bilan_net_result = fields.Float(string="Net result", digits=(18, 0), compute="_compute_bilan", compute_sudo=True)
    bilan_total_equity_liabilities = fields.Float(string="Total equity and liabilities", digits=(18, 0), compute="_compute_bilan", compute_sudo=True)
    bilan_label = fields.Char(string="Basis", compute="_compute_bilan", compute_sudo=True)
    tb_invalid_reason = fields.Text(string="Why the last import is invalid", compute="_compute_tb_alerts", compute_sudo=True)
    tb_openings_warning = fields.Char(string="Opening balances", compute="_compute_tb_alerts", compute_sudo=True)

    def _compute_client_overrides(self):
        for engagement in self:
            client = engagement.client_id.id
            engagement.lead_override_ids = self.env["ea.audit.lead.index.override"].sudo().search([("client_id", "=", client)])
            engagement.grouping_override_ids = self.env["ea.audit.client.grouping.override"].sudo().search([("client_id", "=", client)])

    @api.depends_context("lang", "tz")
    def _compute_tb_card(self):
        for engagement in self:
            version = engagement._ea_current_tb_version()
            engagement.tb_current_label = upload_stamp(engagement, version.create_date) if version else "—"
            engagement.tb_status_label = "%s · %s" % (
                version.source_filename or "", self.env._("%(count)s rows", count=version.row_count),
            ) if version else ""

    @api.depends_context("lang")
    def _compute_tb_alerts(self):
        for engagement in self:
            engagement.tb_invalid_reason = "\n".join(engagement._ea_tb_invalid_reasons()) or False
            engagement.tb_openings_warning = engagement._ea_tb_openings_warning()

    def _ea_tb_invalid_reasons(self):
        """F018: the newest import, when it was refused: why, in lines a person can act on."""
        self.ensure_one()
        version = self.env["ea.audit.tb.version"].sudo().search([
            ("engagement_id", "=", self.id), ("timing", "=", "pre_audit"),
        ], order="version_no desc", limit=1)
        if version.validation_status != "invalid":
            return []
        locale = "fr" if is_french(self.env) else "en"
        return [line["text"] for line in explain_tb_summary(version.validation_summary, locale) if line["blocking"]]

    def _ea_tb_openings_warning(self):
        """F016: nothing stands behind the prior-year column, and the reader should know."""
        self.ensure_one()
        version = self._ea_current_tb_version()
        if not version or self._ea_comparatives()[0] != "opening" or any(line.opening for line in version.line_ids):
            return False
        return self.env._(
            "No opening balances and no prior-year trial balance on this file: the prior-year column reads 0. Import a trial balance with its opening balances, or a prior-year one.",
        )

    def action_export_tb_template(self):
        return self._ea_export_action("tb_template")

    def _ea_export_tb_template(self, fr):
        """F016: the columns the import reads by itself."""
        from ..exports import simple_workbook

        head = (
            ["Compte", "Libellé", "Solde ouverture débit", "Solde ouverture crédit", "Mouvement débit", "Mouvement crédit"]
            if fr else ["Account", "Label", "Opening debit", "Opening credit", "Debit", "Credit"]
        )
        return "tb_%s.xlsx" % ("modele" if fr else "template"), simple_workbook("Modèle" if fr else "Template", head, [])

    def _compute_bilan(self):
        for engagement in self:
            version = engagement._ea_current_tb_version()
            bilan = bilan_totals(engagement._ea_tb_balances())
            engagement.bilan_fixed_assets = bilan["fixedAssets"]
            engagement.bilan_inventory = bilan["inventory"]
            engagement.bilan_receivables = bilan["receivables"]
            engagement.bilan_cash_assets = bilan["cashAssets"]
            engagement.bilan_total_assets = bilan["totalAssets"]
            engagement.bilan_class1 = bilan["class1"]
            engagement.bilan_class4_credit = bilan["class4Credit"]
            engagement.bilan_cash_liabilities = bilan["cashLiabilities"]
            engagement.bilan_net_result = bilan["netResult"]
            engagement.bilan_total_equity_liabilities = bilan["totalLiabilitiesAndEquity"]
            engagement.bilan_label = asset_basis_label(
                "fr" if is_french(self.env) else "en", None,
                imported_on=upload_stamp(engagement, version.create_date) if version else None,
            )

    # ------------------------------------------------------------------
    # Reading the TB
    # ------------------------------------------------------------------

    def _ea_tb(self):
        self.ensure_one()
        return self.env["ea.audit.tb"].sudo().search([("engagement_id", "=", self.id)], limit=1)

    def _ea_current_tb_version(self):
        """The version that drives the file: only a valid pre-audit import sets it."""
        tb = self._ea_tb()
        if not tb or tb.current_version_no <= 0:
            return self.env["ea.audit.tb.version"].sudo()
        return self.env["ea.audit.tb.version"].sudo().search(
            [("tb_id", "=", tb.id), ("version_no", "=", tb.current_version_no)], limit=1,
        )

    def _ea_tb_balances(self):
        """{account, value}, closings of the current version, as the source's every query."""
        version = self._ea_current_tb_version()
        return [{"account": line.account_code, "value": line.closing} for line in version.line_ids]

    def _ea_prior_closings_map(self):
        """priorClosingsMap: the prior engagement's audited closings, else its current version.
        Feeds opening-ties-to-prior only. None when there is no prior year."""
        self.ensure_one()
        prior = self.sudo().search([
            ("client_id", "=", self.sudo().client_id.id), ("fiscal_year", "<", self.sudo().fiscal_year),
        ], order="fiscal_year desc", limit=1)
        if not prior:
            return None
        tb = prior._ea_tb()
        if not tb:
            return None
        version = self.env["ea.audit.tb.version"].sudo().search([
            ("tb_id", "=", tb.id), ("timing", "=", "post_audit"), ("superseded_at", "=", False),
        ], order="version_no desc", limit=1) or prior._ea_current_tb_version()
        if not version or not version.line_ids:
            return None
        return {line.account_code: line.closing for line in version.line_ids}

    def _ea_prior_year_closings(self):
        """The Lead Schedule's comparative: the latest valid prior_year upload (UAT B81)."""
        tb = self._ea_tb()
        if not tb:
            return {}
        version = self.env["ea.audit.tb.version"].sudo().search([
            ("tb_id", "=", tb.id), ("timing", "=", "prior_year"), ("validation_status", "=", "valid"),
        ], order="version_no desc", limit=1)
        out = {}
        for line in version.line_ids:
            out[line.account_code] = out.get(line.account_code, 0) + line.closing
        return out

    def _ea_comparatives(self):
        """The one N-1 of the file (F012): (source, {account: balance}). The lead schedules, the
        analytical review and the financial analysis all read it. A prior-year TB uploaded here
        first, else the closing TB of the client's prior file, the only ones that hold last
        year's income statement; the current TB's openings only when neither exists."""
        self.ensure_one()
        uploaded = self._ea_prior_year_closings()
        if uploaded:
            return "prior_year_tb", uploaded
        prior_file = self._ea_prior_closings_map()
        if prior_file:
            return "prior_file", prior_file
        out = {}
        for line in self._ea_current_tb_version().line_ids:
            out[line.account_code] = out.get(line.account_code, 0) + line.opening
        return "opening", out

    def _ea_comparative_label(self):
        self.ensure_one()
        source, _closings = self.sudo()._ea_comparatives()
        if source == "prior_year_tb":
            return self.env._("Prior year: the valid prior-year trial balance")
        if source == "prior_file":
            year = self.sudo().search([
                ("client_id", "=", self.sudo().client_id.id), ("fiscal_year", "<", self.sudo().fiscal_year),
            ], order="fiscal_year desc", limit=1).fiscal_year
            return self.env._("Prior year: the closing balances of the %(year)s file", year=year)
        return self.env._("Prior year: the current trial balance's opening balances")

    def _ea_known_prefixes(self):
        self.ensure_one()
        client = self.sudo().client_id
        prefixes = set(self.env["ea.audit.grouping.rule"].sudo().search([]).mapped("account_prefix"))
        prefixes |= set(self.env["ea.audit.client.grouping.override"].sudo().search(
            [("client_id", "=", client.id)],
        ).mapped("account_prefix"))
        return sorted(prefixes)

    def _ea_grouping_matchers(self):
        """The test of the tb_mapped gate: an active global rule, or a client override."""
        self.ensure_one()
        global_prefixes = tuple(self.env["ea.audit.grouping.rule"].sudo().search([]).mapped("account_prefix"))
        overrides = self.env["ea.audit.client.grouping.override"].sudo().search(
            [("client_id", "=", self.sudo().client_id.id)],
        )
        exact = {o.account_prefix for o in overrides if o.match_type == "exact"}
        prefixed = tuple(o.account_prefix for o in overrides if o.match_type == "prefix")

        def known(code):
            return code.startswith(global_prefixes) or code in exact or code.startswith(prefixed)

        return known

    def _ea_lead_overrides(self):
        self.ensure_one()
        rows = self.env["ea.audit.lead.index.override"].sudo().search([("client_id", "=", self.sudo().client_id.id)])
        return [(row.account_prefix, row.index_code) for row in rows]

    # ------------------------------------------------------------------
    # Import (3.1)
    # ------------------------------------------------------------------

    def preview_trial_balance_file(self, filename, content, mapping=None, header_row=True):
        """The file analysed without ingesting: the confirm-and-map step."""
        self.ensure_one()
        self._ea_tool_guard()
        table = self._ea_parse(filename, content, header_row)
        return preview_trial_balance(table, mapping, index_overrides=dict(self._ea_lead_overrides()))

    def _ea_tb_read(self, filename, content, mapping, header_row, options):
        """The file as the import will take it: (table, mapping, rows, summary). Writes nothing,
        so the check screen and the import read the same thing."""
        table = self._ea_parse(filename, content, header_row, options)
        try:
            mapping = mapping if mapping is not None else infer_tb_mapping(table["headers"])
            validate_mapping({column: header for column, header in mapping.items() if header in table["headers"]})
            apply_reading_options(table, TB_KIND, mapping, (options or {}).get("decimal"), (options or {}).get("date_format"))
            rows = extract_tb_rows(table, mapping)
        except ServiceError as error:
            raise rule_error(self.env, error.code) from error
        summary = validate_tb_rows(
            rows, self._ea_known_prefixes(), self._ea_prior_closings_map(), mapping, readability_of(table, mapping),
        )
        return table, mapping, rows, summary

    def _ea_tb_check(self, filename, content, mapping, header_row, options):
        """The check screen of a trial balance. Blocking is what made a version invalid."""
        table, mapping, rows, summary = self._ea_tb_read(filename, content, mapping, header_row, options)
        locale = "fr" if is_french(self.env) else "en"
        checks = summary["checks"]
        issues = []
        left_out = left_out_rows(table, mapping)
        if left_out:
            issues.append({"effect": "left_out", "rows": [row["row"] for row in left_out], "text": self.env._(
                "Total lines, titles and lines with no account number. They are not accounts.",
            )})
        # the reasons, without the line about skipped rows, which the list above replaces
        read = dict(summary.get("readability") or {}, rowsWithoutAccount=0)
        for line in explain_tb_summary(dict(summary, readability=read), locale):
            issues.append({"effect": "blocking" if line["blocking"] else "warning", "rows": [], "text": line["text"]})
        balanced = checks["balanced"]
        return {
            "kind": TB_KIND, "fileRows": len(table["rows"]), "rows": len(rows), "leftOut": len(left_out),
            "totalDebit": balanced["totalDebit"], "totalCredit": balanced["totalCredit"],
            "balanced": balanced["ok"], "difference": balanced["totalDebit"] - balanced["totalCredit"],
            "issues": issues, "blocking": summary["status"] != "valid",
        }

    def import_trial_balance(self, filename, content, mapping=None, timing="pre_audit", header_row=True, options=None, remember=False):
        """importTrialBalance: the next version, activated when pre-audit. A file that fails the
        checks is refused and nothing of it is kept (owner's ruling of 2026-11-15): the check
        screen is where it stops."""
        self.ensure_one()
        self._ea_tool_guard()
        if timing not in dict(TIMING_SELECTION):
            raise rule_error(self.env, "invalid-value")
        table, mapping, rows, summary = self._ea_tb_read(filename, content, mapping, header_row, options)
        if summary["status"] != "valid":
            locale = "fr" if is_french(self.env) else "en"
            reasons = [line["text"] for line in explain_tb_summary(summary, locale) if line["blocking"]]
            raise rule_error(self.env, "import-refused", reasons=" ".join(reasons))

        as_root = self.sudo()
        tb = self._ea_tb() or self.env["ea.audit.tb"].sudo().create({
            "engagement_id": self.id, "period_end": as_root.period_end,
        })
        self.env.cr.execute("SELECT id FROM ea_audit_tb WHERE id = %s FOR UPDATE", [tb.id])
        Version = self.env["ea.audit.tb.version"].sudo()
        # One live TB per timing: a new upload supersedes the one before, which stays on the list.
        Version.search([
            ("tb_id", "=", tb.id), ("timing", "=", timing), ("superseded_at", "=", False),
        ]).write({"superseded_at": fields.Datetime.now()})
        last = Version.search([("tb_id", "=", tb.id)], order="version_no desc", limit=1)
        version_no = max(last.version_no, tb.last_version_no) + 1
        tb.last_version_no = version_no
        version = Version.create({
            "engagement_id": self.id,
            "tb_id": tb.id,
            "version_no": version_no,
            "timing": timing,
            "validation_status": summary["status"],
            "source_filename": filename,
            "row_count": len(rows),
            "total_debit": summary["checks"]["balanced"]["totalDebit"],
            "total_credit": summary["checks"]["balanced"]["totalCredit"],
            "validation_summary": summary,
        })
        self.env["ea.audit.tb.line"].sudo().create([{
            "engagement_id": self.id,
            "version_id": version.id,
            "row_no": row_no,
            "account_code": row["account"],
            "account_name": row["label"],
            "opening_debit": row["openingDebit"],
            "opening_credit": row["openingCredit"],
            "debit": row["debit"],
            "credit": row["credit"],
            "raw_data": dict(row["raw"]),
        } for row_no, row in enumerate(rows, start=1)])
        if timing == "pre_audit":
            tb.current_version_no = version_no
        # The TB is the file's primary evidence: every import is on the trail (UAT B62).
        self._ea_log("tb_imported", "Trial balance imported: %s (%s, %d rows)" % (filename, timing, len(rows)))
        self._ea_rebuild_lead_schedules()
        self._ea_sync_significance()
        if remember:
            self._ea_remember_matching(TB_KIND, table["headers"], mapping)
        return {"versionId": version.id, "versionNo": version_no, "summary": summary}

    def _ea_tb_successor(self, version):
        """The version that takes over when this one is deleted: the latest other valid one of
        its timing. Empty when none remains."""
        return self.env["ea.audit.tb.version"].sudo().search([
            ("tb_id", "=", version.tb_id.id), ("timing", "=", version.timing),
            ("validation_status", "=", "valid"), ("id", "!=", version.id),
        ], order="version_no desc", limit=1)

    def delete_tb_version(self, version_id):
        """Whoever may import may delete (owner's ruling of 2026-11-15): no reason asked, no
        version protected. The latest valid version left of the same timing is in use again; for
        a pre-audit one it drives the file, and the schedules follow as they do after an import.
        The trail keeps what was deleted."""
        self.ensure_one()
        self._ea_tool_guard()
        version = self.env["ea.audit.tb.version"].sudo().search([
            ("id", "=", int(version_id or 0)), ("engagement_id", "=", self.id),
        ], limit=1)
        if not version:
            raise rule_error(self.env, "not-found")
        tb = version.tb_id
        self.env.cr.execute("SELECT id FROM ea_audit_tb WHERE id = %s FOR UPDATE", [tb.id])
        timing, was_current = version.timing, version.is_current
        refresh = was_current or (timing == "prior_year" and version.validation_status == "valid")
        successor = self._ea_tb_successor(version)
        facts = (
            version.source_filename, timing, upload_stamp(self, version.create_date), version.row_count,
            grouped(version.total_debit, "en"), grouped(version.total_credit, "en"),
        )
        version.unlink()
        if successor.superseded_at:
            successor.superseded_at = False
        if timing == "pre_audit" and tb.current_version_no != (successor.version_no or 0):
            tb.current_version_no = successor.version_no or 0
        self._ea_log("tb_deleted", "Trial balance deleted: %s (%s, imported on %s, %d rows, total debit %s, total credit %s)" % facts)
        # the version in use, or the comparative, has moved: the schedules follow, as after an import
        if refresh and self._ea_current_tb_version():
            self._ea_rebuild_lead_schedules()
        elif was_current:
            self.env["ea.audit.lead.schedule"].sudo().search([("engagement_id", "=", self.id)]).unlink()
        if refresh:
            self._ea_sync_significance()
        return {"successorId": successor.id or False}

    # ------------------------------------------------------------------
    # Lead schedules
    # ------------------------------------------------------------------

    def _ea_ap_lead_schedules(self):
        self.ensure_one()
        version = self._ea_current_tb_version()
        rows = [{
            "account": line.account_code, "name": line.account_name,
            "opening": line.opening, "closing": line.closing,
        } for line in version.line_ids.sorted("account_code")]
        source, closings = self._ea_comparatives()
        if source == "opening":
            closings = {}
        # An account closed since last year still has its comparative.
        seen = {row["account"] for row in rows}
        rows += [{"account": code, "name": "", "opening": 0, "closing": 0} for code in closings if code not in seen]
        return ap_lead_schedules(sorted(rows, key=lambda row: row["account"]), closings, self._ea_lead_overrides(), source)

    def _ea_refresh_lead_schedules(self):
        """The comparative can move after the import: the prior file's TB is replaced, or
        schedules were built before this rule. Rebuilt on opening, only when it differs."""
        self.ensure_one()
        if self._ea_is_archived() or not self._ea_current_tb_version():
            return
        wanted = {s["index"]: (s["prior"], s["priorSource"]) for s in self._ea_ap_lead_schedules()}
        stored = {
            row.index_code: (row.prior, row.prior_source)
            for row in self.env["ea.audit.lead.schedule"].sudo().search([("engagement_id", "=", self.id)])
        }
        if wanted != stored:
            self._ea_rebuild_lead_schedules()

    def _ea_rebuild_lead_schedules(self):
        """Derived rows: recomputed whole when the TB or the client's mapping changes."""
        self.ensure_one()
        Schedule = self.env["ea.audit.lead.schedule"].sudo()
        Schedule.search([("engagement_id", "=", self.id)]).unlink()
        for schedule in self._ea_ap_lead_schedules():
            definition = schedule["definition"]
            created = Schedule.create({
                "engagement_id": self.id,
                "index_code": schedule["index"],
                "closing": schedule["closing"],
                "prior": schedule["prior"],
                "movement": schedule["movement"],
                "variance_pct": schedule["variancePct"] or 0,
                "has_variance_pct": schedule["variancePct"] is not None,
                "prior_source": schedule["priorSource"],
                "account_type": definition["accountType"],
                "account_class": definition["accountClass"],
                "alerts": "\n".join(alert["code"] for alert in lead_schedule_alerts(schedule["accounts"])),
            })
            self.env["ea.audit.lead.line"].sudo().create([{
                "engagement_id": self.id,
                "schedule_id": created.id,
                "index_code": schedule["index"],
                "sub_index": sub_index_for(account["account"]) or "%s-1" % schedule["index"],
                "account_code": account["account"],
                "account_name": account["name"],
                "closing": account["closing"],
                "prior": account["prior"],
                "movement": account["movement"],
                "variance_pct": account["variancePct"] or 0,
                "has_variance_pct": account["variancePct"] is not None,
            } for account in schedule["accounts"]])

    def _ea_closings_by_index(self):
        """Closing per lead index, with the client's overrides, as significantAccounts sums them."""
        return self._ea_sum_by_index((balance["account"], balance["value"]) for balance in self._ea_tb_balances())

    def _ea_sum_by_index(self, balances):
        """(account, amount) pairs summed per lead index, with the client's overrides: the one
        mapping of the current year and of the prior year on the significant accounts."""
        return sums_by_index(balances, index_resolver(self._ea_lead_overrides()))

    def _ea_prior_by_index(self):
        """(source, {index: prior-year balance}) from the file's one comparative (F012)."""
        self.ensure_one()
        source, balances = self.sudo()._ea_comparatives()
        return source, self.sudo()._ea_sum_by_index(balances.items())

    def save_lead_index_override(self, account_prefix, index_code):
        """saveLeadIndexOverride. Refused unless the caller is on this client's file."""
        self.ensure_one()
        self._ea_tool_guard()
        if not _ACCOUNT_PREFIX.match(account_prefix or ""):
            raise rule_error(self.env, "invalid-prefix")
        if index_code not in LEAD_INDEX_BY_CODE:
            raise rule_error(self.env, "invalid-index")
        Override = self.env["ea.audit.lead.index.override"].sudo()
        client = self.sudo().client_id
        found = Override.search([("client_id", "=", client.id), ("account_prefix", "=", account_prefix)], limit=1)
        if found:
            found.index_code = index_code
        else:
            Override.create({"client_id": client.id, "account_prefix": account_prefix, "index_code": index_code})
        self._ea_rebuild_lead_schedules()
        self._ea_sync_significance()

    def add_grouping_override(self, match_type, account_prefix, section_code, rationale):
        """addOverride."""
        self.ensure_one()
        self._ea_tool_guard()
        if not _ACCOUNT_PREFIX.match(account_prefix or ""):
            raise rule_error(self.env, "invalid-prefix")
        if not _SECTION_CODE.match(section_code or ""):
            raise rule_error(self.env, "invalid-section")
        if not (rationale or "").strip():
            raise rule_error(self.env, "rationale-required")
        match_type = "exact" if match_type == "exact" else "prefix"
        Override = self.env["ea.audit.client.grouping.override"].sudo().with_context(active_test=False)
        client = self.sudo().client_id
        found = Override.search([
            ("client_id", "=", client.id), ("match_type", "=", match_type), ("account_prefix", "=", account_prefix),
        ], limit=1)
        values = {"section_code": section_code, "rationale": rationale, "active": True}
        if found:
            found.write(values)
        else:
            Override.create({"client_id": client.id, "match_type": match_type, "account_prefix": account_prefix, **values})

    def action_tool_tb(self):
        return self._ea_board("ea_audit_tools.view_engagement_tb_board", self.env._("Trial balance"))

    def action_open_tb_import(self):
        self.ensure_one()
        self._ea_require_access()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Import a trial balance"),
            "res_model": "ea.audit.import.wizard",
            "view_mode": "form", "views": [(False, "form")],
            "target": "new",
            "context": {"default_engagement_id": self.id, "default_kind": TB_KIND, "dialog_size": "extra-large"},
        }

