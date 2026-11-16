"""Financial analysis (C.7.3), analytical procedures (C.5.8, lib/analytics.ts), the client's overrides,
the potential risks screen and the working-paper templates (C.7.18, lib/wp-templates.ts)."""
import base64
import re

from markupsafe import Markup

from odoo import fields, models
from odoo.tools import file_open

from ..rules import rule_error
from ..services.financial_analysis import financial_analysis
from ..workbooks import substantive_workbook
from .tool_record import decimal_label, fcfa, is_french

_WP_KIND = re.compile(r"^wp_(\d+)$")
# A shipped paper that exists in French too: the English file -> (the French file, its download name).
_FRENCH_SHIPPED = {
    "C3.1_Representation_letter_EN.docx": ("C3.1_Representation_letter_FR.docx", "C3.1 Lettre d'affirmation de la direction (modele).docx"),
}
_MIMETYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def mimetype_of(filename):
    """The content type of a paper, by its extension (a workbook unless it says otherwise)."""
    extension = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in (filename or "") else ""
    return _MIMETYPES.get(extension, _MIMETYPES[".xlsx"])


class FaRatio(models.Model):
    """One ratio, current against prior. Derived rows; the commentary outlives them, as on the lead."""

    _name = "ea.audit.fa.ratio"
    _inherit = ["ea.audit.lead.comment.mixin"]
    _description = "Financial ratio"
    _order = "sequence, id"
    _rec_name = "label"

    key = fields.Char(required=True)
    sequence = fields.Integer()
    group = fields.Selection([
        ("Liquidity", "Liquidity"), ("Activity", "Activity"), ("Profitability", "Profitability"),
        ("Leverage", "Leverage"), ("Investment", "Investment"),
    ], required=True)
    label = fields.Char(required=True)
    formula = fields.Char()
    unit = fields.Char()
    # Ratios and amounts do not add up: no total on a group's row (F064).
    current = fields.Float(digits=(18, 2), aggregator=None)
    has_current = fields.Boolean()
    prior = fields.Float(digits=(18, 2), aggregator=None)
    has_prior = fields.Boolean()
    variance = fields.Float(string="Change", digits=(18, 2), aggregator=None, help="In the ratio's own unit: percentage points for a percentage, never a relative %.")
    has_variance = fields.Boolean()
    note = fields.Char()

    def _ea_comment_key(self):
        return "FA", self.key


class WpTemplate(models.Model):
    """The catalogue of blank papers. Downloading changes nothing on the file."""

    _name = "ea.audit.wp.template"
    _description = "Working-paper template"
    _order = "sequence, id"

    key = fields.Char(required=True, readonly=True)
    category = fields.Selection(
        [("test-of-controls", "Tests of controls"), ("substantive", "Substantive procedures"), ("general-procedures", "General audit procedures")],
        required=True, readonly=True,
    )
    name = fields.Char(required=True, translate=True, readonly=True)
    filename = fields.Char(readonly=True)
    description = fields.Char(translate=True, readonly=True)
    default_for = fields.Char(string="Standard paper for", readonly=True)
    shipped_file = fields.Char(readonly=True)
    sequence = fields.Integer(default=10, readonly=True)

    _key_uniq = models.Constraint("UNIQUE(key)", "A template key is unique.")

    def action_download(self):
        self.ensure_one()
        engagement = self.env["ea.audit.engagement"].browse(self.env.context.get("ea_engagement_id"))
        return engagement._ea_export_action("wp_%d" % self.id)

    def action_open_assign(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": self.env._("Assign to a task"), "res_model": "ea.audit.wp.assign.wizard", "view_mode": "form", "target": "new",
            "context": {"default_template_id": self.id, "default_engagement_id": self.env.context.get("ea_engagement_id")},
        }

    def _ea_content(self, engagement, fr):
        """The bytes of the paper in the reader's language. A shipped one is the file as it left the firm."""
        self.ensure_one()
        as_root = self.sudo()
        if as_root.shipped_file:
            shipped, filename = as_root.shipped_file, as_root.filename
            if fr and shipped in _FRENCH_SHIPPED:
                shipped, filename = _FRENCH_SHIPPED[shipped]
            with file_open("ea_audit_tools/data/wp_templates/%s" % shipped, "rb") as handle:
                return filename, handle.read()
        from ..workbooks import je_workbook, toc_sample_workbook

        client = {"clientName": "", "fiscalYear": "", "periodEnd": "", "preparer": ""}
        if as_root.key == "je-testing":
            return as_root.filename, je_workbook({**client, "ledger": None, "checks": [], "result": None}, fr)
        if as_root.key == "toc-scot":
            return as_root.filename, toc_sample_workbook({**client, "controls": []}, fr)
        code = as_root.default_for or ""
        title = as_root.with_context(lang="fr_FR" if fr else "en_US").name
        return as_root.filename, substantive_workbook(code, title, fr)


class EngagementAnalysis(models.Model):
    _inherit = "ea.audit.engagement"

    fa_rows_note = fields.Char(string="Basis", compute="_compute_analysis_board", compute_sudo=True)
    analytics_html = fields.Html(string="Preliminary analytical review", compute="_compute_analysis_board", sanitize=False, compute_sudo=True)

    def _compute_analysis_board(self):
        for engagement in self:
            engagement.fa_rows_note = self._ea_fa_note(engagement)
            engagement.analytics_html = engagement._ea_analytics_html()

    def _ea_fa_note(self, engagement):
        return engagement._ea_comparative_label()

    # ------------------------------------------------------------------
    # Financial analysis
    # ------------------------------------------------------------------

    def financial_analysis_view(self):
        """financialAnalysis: None without a TB. Prior-year TB closings beat the working TB's openings."""
        self.ensure_one()
        self._ea_require_access()
        as_root = self.sudo()
        version = as_root._ea_current_tb_version()
        if not version:
            return None
        rows = [{"account_code": line.account_code, "opening": line.opening, "closing": line.closing} for line in version.line_ids]
        source, prior = as_root._ea_comparatives()
        prior_rows = None if source == "opening" else [{"account_code": code, "closing": closing} for code, closing in prior.items()]
        ledger = as_root._ea_ledger()
        if ledger and ledger.timing == "prior_year":
            ledger = ledger.browse()  # only a prior-year ledger: this year has none
        gl_rows = [row["data"] for row in as_root._ea_dataset_rows(ledger)] if ledger else ()
        prior_ledger = as_root._ea_prior_ledger()
        prior_gl_rows = [row["data"] for row in as_root._ea_dataset_rows(prior_ledger)] if prior_ledger else ()
        return financial_analysis(
            rows, as_root.period_end.isoformat(), prior_rows, as_root._ea_lead_overrides(), ledger.mapping if ledger else None, gl_rows,
            prior_ledger.mapping if prior_ledger else None, prior_gl_rows,
        )

    def _ea_sync_fa(self):
        self.ensure_one()
        view = self.financial_analysis_view()
        Ratio = self.env["ea.audit.fa.ratio"].sudo()
        Ratio.search([("engagement_id", "=", self.id)]).unlink()
        if not view:
            return Ratio
        fr = is_french(self.env)
        units = {"days": "jours"} if fr else {}
        values = []
        for position, row in enumerate(view["rows"]):
            current, prior = row.get("current"), row.get("prior")
            both = current is not None and prior is not None
            values.append({
                "engagement_id": self.id, "key": row["key"], "sequence": position, "group": row["group"],
                "label": row["labelFr"] if fr else row["label"], "formula": row["formulaFr"] if fr else row["formula"],
                "unit": units.get(row.get("unit"), row.get("unit")) or False,
                "current": current or 0, "has_current": current is not None, "prior": prior or 0, "has_prior": prior is not None,
                "variance": (current - prior) if both else 0, "has_variance": both, "note": " ".join(filter(None, (row.get("blankFr" if fr else "blank"), row.get("noteFr" if fr else "note")))) or False,
            })
        return Ratio.create(values)

    def action_tool_financial(self):
        self.ensure_one()
        self._ea_require_access()
        self.sudo()._ea_sync_fa()
        return self._ea_list(
            "ea.audit.fa.ratio", self.env._("Financial analysis"), [("ea_audit_tools.view_fa_ratio_list", "list")],
            {"context": {"ea_engagement_id": self.id, "create": False, "search_default_group_ratio": 1}, "search_view_id": self.env.ref("ea_audit_tools.view_fa_ratio_search").id},
        )

    def _ea_export_financial(self, fr):
        from ..exports import simple_workbook

        rows = []
        groups = dict(self.env["ea.audit.fa.ratio"]._fields["group"]._description_selection(self.env))
        for ratio in self.sudo()._ea_sync_fa():
            rows.append([groups[ratio.group], ratio.label, ratio.current if ratio.has_current else "", ratio.prior if ratio.has_prior else "", ratio.variance if ratio.has_variance else "", ratio.unit or "", ratio.commentary or "", ratio.note or ""])
        head = ["Groupe", "Ratio", "N", "N-1", "Variation", "Unité", "Commentaire", "Note"] if fr else ["Group", "Ratio", "Current", "Prior", "Variance", "Unit", "Commentary", "Note"]
        return "financial-analysis-%s.xlsx" % self._ea_export_slug(), simple_workbook("Ratios", head, rows)

    # ------------------------------------------------------------------
    # Analytical procedures
    # ------------------------------------------------------------------

    def _ea_section_resolver(self):
        """Grouping rules with the client's overrides: an override beats a rule, then the longest."""
        self.ensure_one()
        rules = [(rule.account_prefix, rule.section_code, rule.priority, False, False) for rule in self.env["ea.audit.grouping.rule"].sudo().search([])]
        rules += [
            (o.account_prefix, o.section_code, 100, True, o.match_type == "exact")
            for o in self.env["ea.audit.client.grouping.override"].sudo().search([("client_id", "=", self.sudo().client_id.id)])
        ]

        def resolve(code):
            best = None
            for prefix, section, priority, override, exact in rules:
                if not (code == prefix if exact else code.startswith(prefix)):
                    continue
                if (
                    best is None or (override and not best[3])
                    or (override == best[3] and (len(prefix) > len(best[0]) or (len(prefix) == len(best[0]) and priority > best[2])))
                ):
                    best = (prefix, section, priority, override)
            return best[1] if best and best[1] else "—"

        return resolve

    def analytical_review(self):
        """analyticalReview (P3.2, ISA 315): variance by section, flagged above performance materiality."""
        self.ensure_one()
        self._ea_require_access()
        as_root = self.sudo()
        current = as_root._ea_tb_balances()
        # The lead schedules' comparative, so the two screens cannot disagree (F012).
        source, closings = as_root._ea_comparatives()
        prior = [{"account": code, "value": value} for code, value in closings.items()]
        approved = as_root._ea_approved_materiality()
        performance = approved.performance if approved else None
        resolve = as_root._ea_section_resolver()
        sections = {}
        for rows, field in ((current, "closing"), (prior, "prior")):
            for row in rows:
                entry = sections.setdefault(resolve(row["account"]), {"closing": 0, "prior": 0})
                entry[field] += row["value"]
        lines = []
        for section, totals in sections.items():
            movement = totals["closing"] - totals["prior"]
            lines.append({
                "sectionCode": section, "closing": totals["closing"], "prior": totals["prior"], "movement": movement,
                "variancePct": (movement / abs(totals["prior"])) * 100 if totals["prior"] else None,
                "flagged": performance is not None and abs(movement) > performance,
            })
        lines.sort(key=lambda line: -abs(line["movement"]))

        def ratios(rows):
            def total(prefixes):
                amount = 0
                for row in rows:
                    if row["account"].startswith(tuple(prefixes)):
                        amount += row["value"]
                return amount

            revenue = abs(total(("70", "71", "72", "73")))
            return {
                "revenue": revenue or None,
                "payroll_to_revenue": total(("66",)) / revenue * 100 if revenue else None,
                "finance_to_revenue": total(("67",)) / revenue * 100 if revenue else None,
                "purchases_to_revenue": total(("60", "61")) / revenue * 100 if revenue else None,
            }

        now, then = ratios(current), ratios(prior)
        return {
            "hasTb": bool(current), "hasPrior": source != "opening", "priorSource": source, "performanceMateriality": performance, "lines": lines,
            "ratios": [{"key": key, "current": now[key], "prior": then[key]} for key in now],
        }

    def _ea_analytics_html(self):
        review = self.analytical_review() if self._ea_member(self.env.user) or self.env.su else None
        if not review or not review["hasTb"]:
            return False
        fr = is_french(self.env)
        lines = Markup("").join(
            Markup("<tr class='{css}'><td>{s}</td><td class='text-end'>{c}</td><td class='text-end'>{p}</td><td class='text-end'>{m}</td><td class='text-end'>{v}</td></tr>").format(
                css="table-warning" if line["flagged"] else "", s=line["sectionCode"], c=fcfa(line["closing"]), p=fcfa(line["prior"]), m=fcfa(line["movement"]),
                v="%s %%" % decimal_label(round(line["variancePct"], 1), "fr" if fr else "en") if line["variancePct"] is not None else "—",
            ) for line in review["lines"]
        )
        titles = {"revenue": ("Chiffre d'affaires", "Revenue"), "payroll_to_revenue": ("Paie / CA %", "Payroll to revenue %"), "finance_to_revenue": ("Charges financières / CA %", "Finance costs to revenue %"), "purchases_to_revenue": ("Achats / CA %", "Purchases to revenue %")}

        def show(value, key):
            return "—" if value is None else fcfa(value) if key == "revenue" else decimal_label(round(value, 1), "fr" if fr else "en")

        ratios = Markup("").join(
            Markup("<tr><td>{a}</td><td class='text-end'>{b}</td><td class='text-end'>{c}</td></tr>").format(
                a=titles[row["key"]][0 if fr else 1], b=show(row["current"], row["key"]), c=show(row["prior"], row["key"]),
            ) for row in review["ratios"]
        )
        return Markup(
            "<table class='table table-sm o_ea_table'><thead><tr><th>{a}</th><th class='text-end'>N</th><th class='text-end'>N-1</th><th class='text-end'>{b}</th><th class='text-end'>%</th></tr></thead><tbody>{lines}</tbody></table>"
            "<table class='table table-sm o_ea_table'><thead><tr><th>Ratio</th><th class='text-end'>N</th><th class='text-end'>N-1</th></tr></thead><tbody>{ratios}</tbody></table>"
        ).format(a="Section", b="Mouvement" if fr else "Movement", lines=lines, ratios=ratios)

    def action_tool_analytics(self):
        self.ensure_one()
        self._ea_require_access()
        self.sudo()._ea_refresh_lead_schedules()
        return self._ea_board("ea_audit_tools.view_engagement_analytics_board", self.env._("Analytical procedures"))

    # ------------------------------------------------------------------
    # The client's overrides and the potential risks
    # ------------------------------------------------------------------

    def action_tool_overrides(self):
        self.ensure_one()
        self._ea_require_access()
        return self._ea_board("ea_audit_tools.view_engagement_overrides_board", self.env._("Client overrides"))

    def action_open_override_wizard(self):
        return self._ea_action_wizard("ea.audit.override.wizard", self.env._("Add an override"))

    def action_open_potential_wizard(self):
        return self._ea_action_wizard("ea.audit.potential.wizard", self.env._("Raise a potential risk"))

    def action_tool_potential(self):
        return self.action_tool_potential_risks()

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------

    def _ea_sync_wp_generics(self):
        """A generic substantive paper for each E4 task with no paper of its own (F062)."""
        Template = self.env["ea.audit.wp.template"].sudo()
        named = set(Template.search([]).mapped("default_for"))
        Task = self.env["ea.audit.task.template"].sudo()
        for sequence, task in enumerate(Task.search([("code", "=like", "E4.%")], order="code")):
            if task.code in named:
                continue
            safe = re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9 &'-]+", " ", task.with_context(lang="en_US").title or task.code)).strip()
            Template.create({
                "key": "substantive-generic-%s" % task.code, "category": "substantive", "name": "%s %s" % (task.code, task.with_context(lang="en_US").title),
                "filename": "%s_%s.xlsx" % (task.code, safe), "description": "Generic substantive paper: population, selection, tests, exceptions and conclusion.",
                "default_for": task.code, "sequence": 100 + sequence,
            })

    def action_tool_templates(self):
        self.ensure_one()
        self._ea_require_access()
        self._ea_sync_wp_generics()
        return {
            "type": "ir.actions.act_window", "name": self.env._("Paper templates"), "res_model": "ea.audit.wp.template", "view_mode": "list",
            "views": [(self.env.ref("ea_audit_tools.view_wp_template_list").id, "list")], "target": "current",
            "context": {"ea_engagement_id": self.id, "create": False, "search_default_group_category": 1},
            "search_view_id": self.env.ref("ea_audit_tools.view_wp_template_search").id,
        }

    def assign_template(self, template, file_item):
        """assignTemplate: copied in as a task file; a later change to the template leaves it alone."""
        self.ensure_one()
        self._ea_tool_guard()
        if not file_item or file_item.sudo().engagement_id != self.sudo():
            raise rule_error(self.env, "not-found")
        filename, content = template._ea_content(self, is_french(self.env))
        attachment = self.env["ir.attachment"].sudo().create({
            "name": filename, "res_model": "ea.audit.file.item", "res_id": file_item.id, "datas": base64.b64encode(content),
            "mimetype": mimetype_of(filename),
        })
        self._ea_invalidate_signoffs(file_item.sudo().code)
        self._ea_log("attachment_template_assigned", "Template %s assigned to %s" % (filename, file_item.sudo().code))
        return attachment

    def _ea_export_dynamic_method(self, kind):
        found = super()._ea_export_dynamic_method(kind)
        if found:
            return found
        match = _WP_KIND.match(kind or "")
        if match:
            return lambda fr: self._ea_export_wp(int(match[1]), fr)
        return None

    def _ea_export_wp(self, template_id, fr):
        template = self.env["ea.audit.wp.template"].sudo().browse(template_id).exists()
        if not template:
            raise rule_error(self.env, "not-found")
        return template._ea_content(self, fr)

    def action_export_financial(self):
        return self._ea_export_action("financial")

