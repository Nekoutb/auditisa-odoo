"""Sub-ledger analyzers (C.5.9, C.5.10, C.7.2): one per kind, the aging, the agreement to the TB."""
import re
from datetime import datetime, timezone

from markupsafe import Markup

from odoo import api, fields, models

from ..rules import rule_error
from ..services.aging import aging
from ..services.dataset_mapping import FIELDS
from ..services.engines import RECON_PREFIXES, recon_preview, run_reconciliation, run_supplier_recon
from ..services.errors import ServiceError
from ..services.subledger_kinds import SUB_LEDGER_KINDS
from .tool_record import fcfa, french_date, is_french

RECON_TASK = {
    "ar_open_items": "E4.1", "ap_open_items": "E4.2", "inventory_listing": "E4.3",
    "fixed_asset_register": "E4.4", "payroll_register": "E4.11", "bank_statement": "E4.7",
}
_TEMPLATE_KIND = re.compile(r"^template_([a-z_]+)$")


class DatasetAnalyzer(models.Model):
    _inherit = "ea.audit.dataset"

    aging_html = fields.Html(string="Aging", compute="_compute_analyzer", sanitize=False, compute_sudo=True)
    recon_html = fields.Html(string="Agreement to the trial balance", compute="_compute_analyzer", sanitize=False, compute_sudo=True)
    has_recon = fields.Boolean(compute="_compute_analyzer", compute_sudo=True)
    run_ids = fields.One2many("ea.audit.automation.run", "dataset_id", string="Runs")

    @api.depends_context("lang")
    def _compute_analyzer(self):
        for dataset in self:
            engagement = dataset.engagement_id
            dataset.has_recon = dataset.kind in RECON_PREFIXES
            dataset.recon_html = engagement._ea_recon_html(dataset) if dataset.has_recon else False
            dataset.aging_html = engagement._ea_aging_html(dataset) if dataset.kind in ("ar_open_items", "ap_open_items") else False

    def action_reconcile(self):
        self.ensure_one()
        self.sudo().engagement_id.with_env(self.env).run_reconciliation(self.id)
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    def action_list_template(self):
        return self._ea_context_engagement()._ea_export_action("template_%s" % (self.env.context.get("ea_dataset_kind") or "journal_entries"))

    def action_export_aging(self):
        self.ensure_one()
        return self.sudo().engagement_id.with_env(self.env)._ea_export_action("aging_%s" % self.kind)

    def action_open_supplier_recon(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": self.env._("Supplier statements against the ledger"), "res_model": "ea.audit.supplier.recon.wizard",
            "view_mode": "form", "target": "new", "context": {"default_engagement_id": self.sudo().engagement_id.id, "default_statement_id": self.id},
        }


class EngagementAnalyzer(models.Model):
    _inherit = "ea.audit.engagement"

    def _ea_dataset_rows(self, dataset):
        self.env.cr.execute("SELECT row_no, data, amount FROM ea_audit_dataset_row WHERE dataset_id = %s ORDER BY row_no", [dataset.id])
        return [{"rowNo": row_no, "data": data, "amount": float(amount) if amount is not None else None} for row_no, data, amount in self.env.cr.fetchall()]

    def _ea_tb_closing_for_prefixes(self, prefixes):
        total = 0
        for balance in self._ea_tb_balances():
            if balance["account"].startswith(tuple(prefixes)):
                total += balance["value"]
        return total

    def _ea_recon_html(self, dataset):
        preview = recon_preview(dataset.kind, self._ea_dataset_rows(dataset), self._ea_tb_closing_for_prefixes(RECON_PREFIXES[dataset.kind]))
        fr = is_french(self.env)
        last = self.env["ea.audit.automation.run"].sudo().search([("dataset_id", "=", dataset.id), ("engine", "=like", "recon_%")], limit=1)
        css = "o_ea_chip_bad" if abs(preview["difference"]) > 0.5 else "o_ea_chip_good"
        run_note = (
            Markup("<p class='o_ea_legend'>{} {}</p>").format("Dernier rapprochement :" if fr else "Last reconciled:", french_date(last.create_date))
            if last else ""
        )
        return Markup(
            "<p>{a} <b>{b}</b> · {c} <b>{d}</b> · {e} <span class='o_ea_chip {css}'>{f}</span></p><p class='o_ea_legend'>{g} {h}</p>{run}"
        ).format(
            a="Total du fichier :" if fr else "Dataset total:", b=fcfa(preview["datasetTotal"]),
            c="Balance générale :" if fr else "Trial balance:", d=fcfa(preview["tbTotal"]),
            e="Écart :" if fr else "Difference:", css=css, f=fcfa(preview["difference"]),
            g="Comptes" if fr else "Accounts", h=", ".join(preview["prefixes"]), run=run_note,
        )

    def _ea_aging_of(self, dataset):
        rows = [row["data"] for row in self._ea_dataset_rows(dataset)]
        end = self.sudo().period_end
        stamp = int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp() * 1000)
        return aging(rows, dataset.mapping, stamp)

    def _ea_aging_html(self, dataset):
        result = self._ea_aging_of(dataset)
        if result is None:
            return False
        fr = is_french(self.env)
        titles = (
            ["Tiers", "Conditions", "0-30", "31-60", "61-90", "> 90", "Total"] if fr else
            ["Party", "Terms", "0-30", "31-60", "61-90", "> 90", "Total"]
        )
        lines = Markup("").join(
            Markup("<tr><td>{a}</td><td>{b}</td><td class='text-end'>{c}</td><td class='text-end'>{d}</td><td class='text-end'>{e}</td><td class='text-end'>{f}</td><td class='text-end'><b>{g}</b></td></tr>").format(
                a=row["name"], b=row["terms"] or "", c=fcfa(row["current"]), d=fcfa(row["d31_60"]), e=fcfa(row["d61_90"]), f=fcfa(row["over90"]), g=fcfa(row["total"]),
            )
            for row in result["rows"][:200]
        )
        totals = result["totals"]
        return Markup(
            "<div class='table-responsive'><table class='table table-sm o_ea_table'><thead><tr>{head}</tr></thead><tbody>{lines}</tbody>"
            "<tfoot><tr><th colspan='2'>Total</th><th class='text-end'>{c}</th><th class='text-end'>{d}</th><th class='text-end'>{e}</th><th class='text-end'>{f}</th><th class='text-end'>{g}</th></tr></tfoot></table></div>"
            "<p class='o_ea_legend'>{note}</p>"
        ).format(
            head=Markup("").join(Markup("<th>{}</th>").format(title) for title in titles), lines=lines,
            c=fcfa(totals["current"]), d=fcfa(totals["d31_60"]), e=fcfa(totals["d61_90"]), f=fcfa(totals["over90"]), g=fcfa(totals["total"]),
            note=("%d opérations, %d sans date lisible." if fr else "%d transactions, %d with an unreadable date.") % (result["transactionCount"], result["undated"]),
        )

    def aging_for(self, kind):
        """agingFor: the latest dataset of the kind; None when its mapping lacks party, amount or date."""
        self.ensure_one()
        self._ea_require_access()
        dataset = self.env["ea.audit.dataset"].sudo().search([("engagement_id", "=", self.id), ("kind", "=", kind)], limit=1)
        return self._ea_aging_of(dataset) if dataset else None

    def run_reconciliation(self, dataset_id, stale_days=None):
        """runReconciliation: the agreement recorded as a run on the matching E4 paper, and a
        finding when the difference is above clearly trivial. Reconcile needs the paper on the file."""
        self.ensure_one()
        self._ea_tool_guard()
        dataset = self.env["ea.audit.dataset"].sudo().search([("id", "=", int(dataset_id or 0)), ("engagement_id", "=", self.id)], limit=1)
        if not dataset:
            raise rule_error(self.env, "no-dataset")
        rows = self._ea_dataset_rows(dataset)
        prefixes = RECON_PREFIXES.get(dataset.kind)
        if not prefixes:
            raise rule_error(self.env, "unsupported-dataset")
        item = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.id), ("code", "=", RECON_TASK[dataset.kind])], limit=1)
        if not item:
            raise rule_error(self.env, "recon-task-missing")
        approved = self.sudo()._ea_approved_materiality()
        try:
            result = run_reconciliation(
                dataset.kind, rows, self.sudo()._ea_tb_closing_for_prefixes(prefixes), approved.trivial if approved else None,
                stale_days=stale_days, period_end=self.sudo().period_end.isoformat() if dataset.kind == "bank_statement" else None,
            )
        except ServiceError as error:
            raise rule_error(self.env, error.code) from error
        summary = result["summary"]
        run = self.env["ea.audit.automation.run"].sudo().create({
            "engagement_id": self.id, "title": "Reconciliation", "engine": result["engine"], "method": "recon",
            "dataset_id": dataset.id, "file_item_id": item.id,
            "params": {"datasetKind": dataset.kind, "prefixes": prefixes, "staleDays": stale_days},
            "summary": summary, "sheet_header": ["measure", "amount"],
            "sheet_rows": [
                ["dataset_total", summary["datasetTotal"]], ["tb_total", summary["tbTotal"]], ["difference", summary["difference"]],
                *([["-- stale items --", None]] if result["staleRows"] else []), *result["staleRows"],
            ],
        })
        if result.get("finding"):
            finding = result["finding"]
            self.route_finding(finding["route"], finding["title"], detail=finding.get("detail"), file_item=item)
        self._ea_log("reconciled", "%s reconciled to the trial balance: difference %s" % (dataset.source_filename, summary["difference"]))
        return run.with_env(self.env)

    def run_supplier_recon(self, statement_id, ledger_id):
        """runSupplierRecon: statements against the ledger, per supplier."""
        self.ensure_one()
        self._ea_tool_guard()
        Dataset = self.env["ea.audit.dataset"].sudo()
        statement = Dataset.search([("id", "=", int(statement_id or 0)), ("engagement_id", "=", self.id)], limit=1)
        ledger = Dataset.search([("id", "=", int(ledger_id or 0)), ("engagement_id", "=", self.id)], limit=1)
        if not statement or not ledger:
            raise rule_error(self.env, "no-dataset")
        try:
            result = run_supplier_recon(self._ea_dataset_rows(statement), self._ea_dataset_rows(ledger))
        except ServiceError as error:
            raise rule_error(self.env, error.code) from error
        item = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.id), ("code", "=", "E4.2")], limit=1)
        run = self.env["ea.audit.automation.run"].sudo().create({
            "engagement_id": self.id, "title": "Supplier statements", "engine": "recon_supplier", "method": "recon", "dataset_id": statement.id,
            "file_item_id": item.id or False, "params": {"ledgerDatasetId": ledger.id},
            "summary": {key: value for key, value in result.items() if key != "lines"},
            "sheet_header": ["supplier", "statement", "ledger", "difference"], "sheet_rows": result["lines"],
        })
        return run.with_env(self.env)

    # ------------------------------------------------------------------
    # Screens
    # ------------------------------------------------------------------

    def _ea_analyzer(self, kind, name):
        action = self._ea_list(
            "ea.audit.dataset", name, [("ea_audit_tools.view_dataset_list", "list"), ("ea_audit_tools.view_dataset_form", "form")],
        )
        action["domain"] = [("engagement_id", "=", self.id), ("kind", "=", kind)]
        action["context"] = {"ea_engagement_id": self.id, "ea_dataset_kind": kind, "create": False}
        return action

    def action_tool_data_analytics(self):
        """The analyzers, as a second page of tiles."""
        self.ensure_one()
        self._ea_require_access()
        action = self.action_open_tools()
        action["name"] = self.env._("Data analytics")
        action["domain"] = [("section", "=", "analyzers")]
        return action

    def action_tool_ar(self):
        return self._ea_analyzer("ar_open_items", self.env._("Accounts receivable"))

    def action_tool_ap(self):
        return self._ea_analyzer("ap_open_items", self.env._("Accounts payable"))

    def action_tool_inventory(self):
        return self._ea_analyzer("inventory_listing", self.env._("Inventory"))

    def action_tool_fixed_assets(self):
        return self._ea_analyzer("fixed_asset_register", self.env._("Fixed assets"))

    def action_tool_payroll(self):
        return self._ea_analyzer("payroll_register", self.env._("Payroll"))

    def action_tool_bank(self):
        return self._ea_analyzer("bank_statement", self.env._("Bank statements"))

    def action_tool_supplier(self):
        return self._ea_analyzer("supplier_statements", self.env._("Supplier statements"))

    def _ea_export_dynamic_method(self, kind):
        found = super()._ea_export_dynamic_method(kind)
        if found:
            return found
        template = _TEMPLATE_KIND.match(kind or "")
        if template and template[1] in SUB_LEDGER_KINDS:
            return lambda fr: self._ea_export_dataset_template(template[1], fr)
        if kind in ("aging_ar_open_items", "aging_ap_open_items"):
            return lambda fr: self._ea_export_aging_grid(kind[6:], fr)
        return None

    def _ea_export_dataset_template(self, kind, fr):
        """The expected layout, before any file is read (F066): the headers of the kind."""
        from ..exports import simple_workbook

        head = [field["fr" if fr else "en"] for field in FIELDS[kind]]
        return "%s_%s.xlsx" % (kind, "modele" if fr else "template"), simple_workbook("Modèle" if fr else "Template", head, [])

    def _ea_export_aging_grid(self, kind, fr):
        from ..exports import simple_workbook

        result = self.aging_for(kind)
        if result is None:
            raise rule_error(self.env, "no-dataset")
        head = ["Tiers", "Nom", "Conditions", "0-30", "31-60", "61-90", "> 90", "Total"] if fr else ["Party", "Name", "Terms", "0-30", "31-60", "61-90", "> 90", "Total"]
        rows = [[r["party"], r["name"], r["terms"] or "", r["current"], r["d31_60"], r["d61_90"], r["over90"], r["total"]] for r in result["rows"]]
        return "aging-%s-%s.xlsx" % (kind, self._ea_export_slug()), simple_workbook("Aging", head, rows)

