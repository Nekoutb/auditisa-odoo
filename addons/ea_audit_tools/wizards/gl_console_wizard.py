"""The GL console (GlConsole.tsx): one transient per visit, a tab per question, results rendered
server side. Nothing here decides anything: the engagement's gl_* methods do, and refuse."""
import base64
import re

from markupsafe import Markup

from odoo import api, fields, models

from ..models.tool_record import bracketed, is_french
from ..rules import rule_error
from ..services.gl_analytics import ANALYTICS, column_kind, t
from ..services.gl_correlation import amount_input, split_accounts
from ..services.gl_insights import LAG_KEYS

_MONTH_INPUT = re.compile(r"^(0[1-9]|1[0-2])/([0-9]{4})$")
WEEKDAYS = [("1", "Monday"), ("2", "Tuesday"), ("3", "Wednesday"), ("4", "Thursday"), ("5", "Friday"), ("6", "Saturday"), ("7", "Sunday"), ("n/a", "No date")]
DAY_NAMES = {"fr": ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"], "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}


def whole(value):
    """A figure as FCFA are written: no decimals, a space between thousands."""
    if value is None or value is False:
        return "—"
    return bracketed("{:,.0f}".format(value).replace(",", " "))


def decimal(value, locale):
    if value is None or value is False:
        return "—"
    text = "{:,.2f}".format(value).replace(",", " ")
    return bracketed(text.replace(".", ",") if locale == "fr" else text)


def date_label(iso):
    """YYYY-MM-DD as DD/MM/YYYY."""
    return "%s/%s/%s" % (iso[8:10], iso[5:7], iso[:4]) if iso else ""


def month_label(month, locale):
    if month == "n/a":
        return t(locale, "no date", "sans date")
    return "%s/%s" % (month[5:7], month[:4])


def period_label(key, period, locale):
    if period == "weekday" and key != "n/a":
        return DAY_NAMES[locale][int(key) - 1]
    return month_label(key, locale)


def table(head, rows, foot=None, numeric_from=1):
    """A plain table: every value is escaped by Markup.format."""
    def line(tag, cells):
        return Markup("<tr>{}</tr>").format(Markup("").join(
            Markup("<{tag} class='{css}'>{value}</{tag}>").format(
                tag=Markup(tag), css="text-end" if position >= numeric_from else "", value="" if cell is None else cell,
            )
            for position, cell in enumerate(cells)
        ))

    return Markup("<div class='table-responsive'><table class='table table-sm o_ea_table'><thead>{}</thead><tbody>{}</tbody>{}</table></div>").format(
        line("th", head),
        Markup("").join(line("td", row) for row in rows),
        Markup("<tfoot class='fw-bold'>{}</tfoot>").format(line("td", foot)) if foot else "",
    )


def chip(text, level="good"):
    return Markup("<span class='o_ea_chip o_ea_chip_{}'>{}</span>").format(Markup(level), text)


class GlConsoleAccount(models.TransientModel):
    """A line of the account picker (GlAccountPicker)."""

    _name = "ea.audit.gl.console.account"
    _description = "GL console account"
    _order = "account"

    console_id = fields.Many2one("ea.audit.gl.console", required=True, ondelete="cascade")
    selected = fields.Boolean(string="Pick")
    account = fields.Char(readonly=True)
    name = fields.Char(string="Description", readonly=True)
    lines = fields.Integer(readonly=True)
    entries = fields.Integer(readonly=True)
    debit = fields.Float(digits=(18, 0), readonly=True)
    credit = fields.Float(digits=(18, 0), readonly=True)
    signed = fields.Float(string="Net", digits=(18, 0), readonly=True)


class GlConsole(models.TransientModel):
    _name = "ea.audit.gl.console"
    _description = "General ledger console"
    _rec_name = "dataset_id"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True, ondelete="cascade")
    dataset_id = fields.Many2one(
        "ea.audit.dataset", string="Ledger", required=True, ondelete="cascade",
        domain="[('engagement_id', '=', engagement_id), ('kind', '=', 'journal_entries'), ('superseded_at', '=', False)]",
    )
    gl_built_at = fields.Datetime(related="dataset_id.gl_built_at")
    gl_line_count = fields.Integer(related="dataset_id.gl_line_count")
    validation_status = fields.Selection(related="dataset_id.validation_status")

    # the figure a lead schedule sent here (UAT run 2 B68)
    figure_set = fields.Boolean()
    figure_accounts = fields.Char()
    figure_opening = fields.Float(digits=(18, 2))
    figure_closing = fields.Float(digits=(18, 2))
    figure_html = fields.Html(compute="_compute_figure_html", sanitize=False)
    head_html = fields.Html(compute="_compute_head_html", sanitize=False)

    # the selection and the picker
    selected_accounts = fields.Char(string="Selected accounts", help="Account codes separated by commas: 25 at most.")
    account_search = fields.Char(string="Find an account", help="A piece of the code or of the description.")
    account_ids = fields.One2many("ea.audit.gl.console.account", "console_id", string="Accounts")
    picker_note = fields.Char(readonly=True)

    # drilling a row: the native list opens on the lines behind it
    drill_month = fields.Char(string="Month", help="MM/YYYY as in the table, or n/a for lines with no date.")
    drill_weekday = fields.Selection(WEEKDAYS, string="Weekday")
    drill_account = fields.Char(string="Account")

    # entry analysis
    entry_mode = fields.Selection([("any", "Any of them"), ("all", "All of them")], string="Entries touching", default="any", required=True)
    entry_rank = fields.Selection([
        ("abs", "Gross value"), ("net", "Net value"), ("postings", "Postings"), ("entries", "Entries"), ("account", "Account code"),
    ], string="Rank by", default="abs", required=True)
    entry_limit = fields.Selection([("10", "10"), ("20", "20"), ("50", "50"), ("all", "All")], string="Counterparts shown", default="20", required=True)
    entry_period = fields.Selection([("month", "Month"), ("weekday", "Weekday")], string="Rows", default="month", required=True)
    entry_html = fields.Html(sanitize=False, readonly=True)

    # the line filter (LineFilterBar and the route's whitelist)
    filter_accounts = fields.Char(string="Accounts", help="Empty: the selected accounts.")
    filter_date_from = fields.Date(string="From")
    filter_date_to = fields.Date(string="To")
    filter_min_abs = fields.Char(string="Amount at least")
    filter_max_abs = fields.Char(string="Amount at most")
    filter_journal = fields.Char(string="Journal")
    filter_je = fields.Char(string="Entry number")
    filter_preparer = fields.Char(string="Preparer")
    filter_reviewer = fields.Char(string="Reviewer")
    filter_approver = fields.Char(string="Approver")
    filter_weekend = fields.Boolean(string="Weekends only")
    filter_missing_reference = fields.Boolean(string="No reference")

    # two-account correlation
    corr_a = fields.Char(string="Account A")
    corr_b = fields.Char(string="Account B")
    corr_html = fields.Html(sanitize=False, readonly=True)

    # the catalogue
    catalogue_html = fields.Html(compute="_compute_catalogue_html", sanitize=False)
    analytic_key = fields.Selection(selection="_analytic_selection", string="Analytic", default="ledger-reconciliation", required=True)
    percentile = fields.Float(default=0.99, digits=(6, 4), help="Between 0.5 and 0.9999.")
    sd_factor = fields.Float(string="Standard deviations", default=2, digits=(4, 1), help="Between 0.5 and 6.")
    round_min = fields.Float(string="Minimum amount", default=100000, digits=(18, 0))
    round_step = fields.Float(string="Multiple of", default=100000, digits=(18, 0))
    min_occurrences = fields.Integer(string="Occurrences at least", default=10)
    rare_max = fields.Integer(string="Postings at most", default=3)
    prefixes = fields.Char(string="Account prefixes", default="40, 41")
    top_n = fields.Integer(string="People shown", default=10)
    year_end_days = fields.Integer(string="Closing window (days)", default=15)
    analytic_html = fields.Html(sanitize=False, readonly=True)
    export_file = fields.Binary(attachment=False, readonly=True)
    export_filename = fields.Char(readonly=True)

    # insights
    insights_html = fields.Html(sanitize=False, readonly=True)
    prefix_accounts = fields.Char(string="Account prefixes to compare", help="2 to 6 prefixes of 2 to 4 digits.")
    matrix_html = fields.Html(sanitize=False, readonly=True)

    @api.model
    def _analytic_selection(self):
        french = is_french(self.env)
        return [(d["key"], "%d. %s" % (d["id"], d["titleFr"] if french else d["titleEn"])) for d in ANALYTICS]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self.env["ea.audit.engagement"].browse(vals.get("engagement_id"))._ea_require_access()
        return super().create(vals_list)

    def _ea_reopen(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id, "view_mode": "form",
            "views": [(self.env.ref("ea_audit_tools.view_gl_console_form").id, "form")],
            "target": "current", "name": self.env._("General ledger console"),
            "context": {"ea_engagement_id": self.engagement_id.id},
        }

    def _locale(self):
        return "fr" if is_french(self.env) else "en"

    @api.onchange("dataset_id")
    def _onchange_dataset_id(self):
        """Another ledger: the selection and every result go, as in the source."""
        if self._origin.dataset_id and self.dataset_id != self._origin.dataset_id:
            self.update({
                "selected_accounts": False, "entry_html": False, "corr_html": False, "analytic_html": False,
                "insights_html": False, "matrix_html": False, "account_ids": [(5, 0, 0)], "figure_set": False,
            })

    def write(self, vals):
        # The results are read-only on the form, so the onchange above only shows them cleared:
        # saving must clear them too, or the old ledger's tables come back on the new one.
        if vals.get("dataset_id") and self.filtered(lambda console: console.dataset_id.id != vals["dataset_id"]):
            vals = dict(vals, entry_html=False, corr_html=False, analytic_html=False, insights_html=False, matrix_html=False)
        return super().write(vals)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    @api.depends("dataset_id", "figure_set", "figure_accounts", "figure_opening", "figure_closing")
    @api.depends_context("lang")
    def _compute_figure_html(self):
        for console in self:
            console.figure_html = False
            if not console.figure_set or not console.dataset_id or not console.figure_accounts:
                continue
            figure = console.engagement_id.gl_reconcile_figure(
                console.dataset_id.id, console.figure_accounts.split(","), console.figure_opening, console.figure_closing,
            )
            console.figure_html = Markup(
                "<b>{title}</b> {opening_label} {opening} + {movements_label} {movements} = <b>{computed}</b> · {closing_label} {closing} · {gap_chip}"
            ).format(
                title=self.env._("Lead-schedule figure:"), opening_label=self.env._("Opening balance (TB)"), opening=whole(figure["opening"]),
                movements_label=self.env._("movements (%(count)s lines)", count=figure["lines"]), movements=whole(figure["movements"]),
                computed=whole(figure["computed"]), closing_label=self.env._("balance clicked"), closing=whole(figure["closing"]),
                gap_chip=chip("%s %s" % (self.env._("gap"), whole(figure["gap"])), "good" if figure["gap"] == 0 else "bad"),
            )

    @api.depends("dataset_id", "gl_built_at")
    @api.depends_context("lang")
    def _compute_head_html(self):
        """The ledger at a glance: loadHead."""
        for console in self:
            console.head_html = False
            if not console.dataset_id or not console.gl_built_at:
                continue
            engagement, dataset = console.engagement_id, console.dataset_id.id
            lines, debit, credit, difference = engagement.gl_run_analytic(dataset, "ledger-reconciliation").get("totals") or [0, 0, 0, 0]
            entries = engagement.gl_run_analytic(dataset, "unbalanced-entries")
            accounts = engagement.gl_accounts_for(dataset)["total"]
            console.head_html = Markup("<div class='o_ea_cards'>{}</div>").format(Markup("").join(
                Markup("<div class='o_ea_card'><div class='o_ea_card_label'>{}</div><span class='o_ea_card_value'>{}</span><div class='o_ea_card_note'>{}</div></div>").format(label, value, note)
                for label, value, note in [
                    (self.env._("Lines"), whole(lines), self.env._("%(count)s accounts", count=whole(accounts))),
                    (self.env._("Entries"), whole(entries["population"]), self.env._("%(count)s unbalanced", count=whole(entries["exceptions"]))),
                    (self.env._("Debit"), whole(debit), "FCFA"),
                    (self.env._("Credit"), whole(credit), "FCFA"),
                    (self.env._("Difference"), whole(difference), "FCFA"),
                ]
            ))

    @api.depends("dataset_id")
    @api.depends_context("lang")
    def _compute_catalogue_html(self):
        for console in self:
            console.catalogue_html = console._render_catalogue(
                console.engagement_id.gl_catalogue(console.dataset_id.id)
            ) if console.dataset_id else False

    def _render_catalogue(self, entries):
        rows = [
            [
                entry["id"], entry["title"], entry["objective"], ", ".join(entry["assertions"]),
                entry["exception"],
                chip(entry["unavailable"], "warn") if entry["unavailable"] else chip(self.env._("Available"), "good"),
            ]
            for entry in entries
        ]
        return table(
            ["#", self.env._("Analytic"), self.env._("Objective"), self.env._("Assertions"), self.env._("Exception"), self.env._("Status")],
            rows, numeric_from=99,
        )

    # ------------------------------------------------------------------
    # Picker and entry analysis
    # ------------------------------------------------------------------

    def action_search_accounts(self):
        self.ensure_one()
        found = self.engagement_id.gl_accounts_for(self.dataset_id.id, self.account_search)
        note = self.env._("%(count)s accounts", count=found["total"])
        if found["truncated"]:
            note = self.env._("%(count)s accounts: the first %(shown)s are listed, narrow the search", count=found["total"], shown=len(found["accounts"]))
        self.write({
            "picker_note": note,
            "account_ids": [(5, 0, 0)] + [(0, 0, {
                "account": row["account"], "name": row["name"], "lines": row["lines"], "entries": row["entries"],
                "debit": row["debit"], "credit": row["credit"], "signed": row["signed"],
            }) for row in found["accounts"]],
        })

    def _selected(self):
        return split_accounts(self.selected_accounts)

    def action_add_picked(self):
        """The ticked lines join the selection."""
        self.ensure_one()
        selected = self._selected()
        picked = self.account_ids.filtered("selected").mapped("account")
        self.write({
            "selected_accounts": ", ".join(dict.fromkeys(selected + picked)),
            "account_ids": [(1, line.id, {"selected": False}) for line in self.account_ids.filtered("selected")],
        })

    def action_run_entry(self):
        self.ensure_one()
        limit = self.entry_limit if self.entry_limit == "all" else int(self.entry_limit)
        result = self.engagement_id.gl_entry_analysis(
            self.dataset_id.id, self._selected(), self.entry_mode, self.entry_rank, limit, self.entry_period,
        )
        self.entry_html = self._render_entry(result)

    def _render_entry(self, result):
        locale = self._locale()
        tops = result["counterpartAccounts"]
        summary = Markup("<p>{}</p>").format(self.env._(
            "%(entries)s linked entries · debits %(debit)s · credits %(credit)s · net %(net)s FCFA",
            entries=result["linkedEntries"], debit=whole(result["totalDebit"]), credit=whole(result["totalCredit"]), net=whole(result["net"]),
        ))
        grid = table(
            [self.env._("Period")] + [row["account"] for row in tops] + [self.env._("Total")],
            [
                [period_label(month["month"], result["period"], locale)] + [whole(cell) if cell is not None else "" for cell in month["cells"]] + [whole(month["total"])]
                for month in result["months"]
            ],
        )
        counterparts = table(
            [self.env._("Counterpart"), self.env._("Description"), self.env._("Net"), self.env._("Gross"), self.env._("Postings"), self.env._("Entries")],
            [[row["account"], row["name"], whole(row["net"]), whole(row["gross"]), row["postings"], row["entries"]] for row in tops],
            numeric_from=2,
        )
        hidden = Markup("<p class='o_ea_legend'>{}</p>").format(
            self.env._("%(count)s more counterpart accounts are not shown", count=result["hiddenAccounts"])
        ) if result["hiddenAccounts"] else ""
        return Markup("{}{}{}{}").format(summary, grid, hidden, counterparts)

    # ------------------------------------------------------------------
    # Two accounts
    # ------------------------------------------------------------------

    def action_run_correlation(self):
        self.ensure_one()
        selected = self._selected()
        a = self.corr_a or (selected[0] if selected else "")
        b = self.corr_b or (selected[1] if len(selected) > 1 else "")
        result = self.engagement_id.gl_two_account_correlation(self.dataset_id.id, a, b)
        self.write({"corr_a": a, "corr_b": b, "corr_html": self._render_correlation(result)})

    def action_swap(self):
        self.ensure_one()
        self.write({"corr_a": self.corr_b, "corr_b": self.corr_a})
        if self.corr_a and self.corr_b:
            self.action_run_correlation()

    def _render_correlation(self, result):
        locale = self._locale()
        none = self.env._("not computable")
        r_value, r_abs = result["pearson"], result["pearsonAbs"]
        summary = Markup("<div class='o_ea_cards'>{}</div>").format(Markup("").join(
            Markup("<div class='o_ea_card'><div class='o_ea_card_label'>{}</div><span class='o_ea_card_value'>{}</span></div>").format(label, value)
            for label, value in [
                (self.env._("Common entries"), result["commonEntries"]),
                (self.env._("Pearson r (signed)"), none if r_value is None else decimal(r_value, locale)),
                (self.env._("Pearson r (absolute)"), none if r_abs is None else decimal(r_abs, locale)),
                (self.env._("Largest difference"), "%s (%s)" % (whole(result["largestDifference"]), month_label(result["largestDifferenceMonth"], locale)) if result["largestDifferenceMonth"] else "—"),
            ]
        ))
        grid = table(
            [self.env._("Month"), result["a"], result["b"], self.env._("Ratio"), self.env._("Difference")],
            [
                [month_label(row["month"], locale), whole(row["aTotal"]), whole(row["bTotal"]), "—" if row["ratio"] is None else "{:.4f}".format(row["ratio"]), whole(row["difference"])]
                for row in result["months"]
            ],
            foot=[self.env._("Total"), whole(result["totalA"]), whole(result["totalB"]), "", ""],
        )
        return Markup("{}{}").format(summary, grid)

    # ------------------------------------------------------------------
    # The catalogue
    # ------------------------------------------------------------------

    def _params(self):
        return {
            "percentile": self.percentile, "sdFactor": self.sd_factor, "roundMin": self.round_min, "roundStep": self.round_step,
            "minOccurrences": self.min_occurrences, "rareMax": self.rare_max, "topN": self.top_n, "yearEndDays": self.year_end_days,
            "prefixes": split_accounts(self.prefixes),
        }

    def action_run_analytic(self):
        self.ensure_one()
        self.analytic_html = self._render_analytic(
            self.engagement_id.gl_run_analytic(self.dataset_id.id, self.analytic_key, self._params())
        )

    def _render_analytic(self, result):
        locale = self._locale()
        head = Markup("<p><b>{}</b> — {}</p>").format(result["title"], result["objective"])
        if result.get("unavailable"):
            return Markup("{}<div class='o_ea_banner'>{}</div>").format(head, result["unavailable"])

        kinds = [column_kind(result["key"], column["key"]) for column in result["columns"]]

        def cell(value, kind):
            if value is None:
                return "—"
            if kind == "money":
                return whole(value)
            return decimal(value, locale) if kind == "decimal" else whole(value)

        rows = [[month_label(row["month"], locale)] + [cell(value, kinds[i]) for i, value in enumerate(row["cells"])] for row in result["rows"]]
        foot = None
        if result.get("totals"):
            foot = [self.env._("Total")] + [cell(value, kinds[i]) for i, value in enumerate(result["totals"])]
        count = chip(
            self.env._("%(exceptions)s exceptions requiring audit consideration, of %(population)s", exceptions=whole(result["exceptions"]), population=whole(result["population"])),
            "warn" if result["exceptions"] else "good",
        )
        note = Markup("<p class='o_ea_legend'>{}</p>").format(result["note"]) if result.get("note") else ""
        return Markup("{}<p>{}</p>{}{}").format(
            head, count, table([self.env._("Month")] + [column["label"] for column in result["columns"]], rows, foot), note,
        )

    def action_export_analytic(self):
        """An analytic's rows as a workbook. Logged as every export is, read rights are enough."""
        self.ensure_one()
        filename, content = self.engagement_id.with_context(ea_gl_analytic={
            "dataset": self.dataset_id.id, "key": self.analytic_key, "params": self._params(),
        }).ea_export_xlsx("gl_analytic")
        self.write({"export_file": base64.b64encode(content), "export_filename": filename})
        return {
            "type": "ir.actions.act_url", "target": "self",
            "url": "/web/content?model=%s&id=%d&field=export_file&filename_field=export_filename&download=true" % (self._name, self.id),
        }

    # ------------------------------------------------------------------
    # Insights
    # ------------------------------------------------------------------

    def action_load_insights(self):
        self.ensure_one()
        engagement = self.engagement_id
        locale = self._locale()
        unavailable = Markup("<p class='o_ea_legend'>{}</p>").format(self.env._("Not available on this ledger: a column is not mapped."))
        parts = []

        roles = engagement.gl_preparers_reviewers()
        labels = {"recordedBy": self.env._("Recorded by"), "preparedBy": self.env._("Prepared by"), "approvedBy": self.env._("Approved by")}
        parts.append(Markup("<div class='o_ea_card_label'>{}</div>").format(self.env._("Preparers and reviewers")))
        parts.append(table(
            [self.env._("Role"), self.env._("Current year"), self.env._("Prior year"), self.env._("Only this year"), self.env._("Only last year")],
            [
                [labels[role["key"]], role["cyCount"] if role["mapped"] else "—", "—" if role["pyCount"] is None else role["pyCount"], ", ".join(role["onlyCy"]), ", ".join(role["onlyPy"])]
                for role in roles["roles"]
            ], numeric_from=1,
        ) if roles else unavailable)

        volumes = engagement.gl_class_volumes()
        parts.append(Markup("<div class='o_ea_card_label'>{}</div>").format(self.env._("Volumes per account class")))

        def change(value):
            return "—" if value is None else "%s %%" % decimal(value, locale)

        parts.append(table(
            [self.env._("Class"), self.env._("Lines"), self.env._("Gross value"), self.env._("Prior-year lines"), self.env._("Prior-year value"), self.env._("Change in lines"), self.env._("Change in value")],
            [
                [row["cls"], whole(row["cyLines"]), whole(row["cyGross"]), whole(row["pyLines"]), whole(row["pyGross"]), change(row["linesPct"]), change(row["grossPct"])]
                for row in volumes["rows"]
            ],
        ) if volumes else unavailable)

        weekdays = engagement.gl_weekday_analysis()
        parts.append(Markup("<div class='o_ea_card_label'>{}</div>").format(self.env._("Journals per weekday")))
        if weekdays:
            parts.append(table(
                [self.env._("Weekday"), self.env._("Journals"), self.env._("Lines"), self.env._("Gross value")],
                [[DAY_NAMES[locale][row["dow"]], whole(row["journals"]), whole(row["lines"]), whole(row["gross"])] for row in weekdays["rows"]],
            ))
            if weekdays["undated"]:
                parts.append(Markup("<p class='o_ea_legend'>{}</p>").format(self.env._("%(count)s lines have an unreadable date", count=weekdays["undated"])))
        else:
            parts.append(unavailable)

        lag = engagement.gl_entry_lag()
        parts.append(Markup("<div class='o_ea_card_label'>{}</div>").format(self.env._("Entry date against effective date")))
        if lag:
            names = dict(zip(LAG_KEYS, [
                self.env._("Same day or before"), self.env._("1 to 7 days"), self.env._("8 to 30 days"), self.env._("31 to 90 days"), self.env._("Over 90 days"),
            ]))
            parts.append(Markup("<p>{}</p>").format(self.env._(
                "%(journals)s journals · average %(average)s days · longest %(longest)s days",
                journals=lag["journals"], average=decimal(lag["avgDays"], locale), longest=lag["maxDays"],
            )))
            parts.append(table([self.env._("Lag"), self.env._("Journals")], [[names[b["key"]], whole(b["journals"])] for b in lag["buckets"]]))
        else:
            parts.append(unavailable)

        prefixes = engagement.gl_account_prefixes()
        parts.append(Markup("<div class='o_ea_card_label'>{}</div>").format(self.env._("Account prefixes")))
        parts.append(table(
            [self.env._("Prefix"), self.env._("Description"), self.env._("Lines")],
            [[row["prefix"], row["name"], whole(row["lines"])] for row in prefixes], numeric_from=2,
        ) if prefixes else unavailable)
        self.insights_html = Markup("").join(parts)

    def action_run_matrix(self):
        self.ensure_one()
        result = self.engagement_id.gl_correlation_matrix(split_accounts(self.prefix_accounts))
        locale = self._locale()
        prefixes = table(
            [self.env._("Prefix"), self.env._("Lines"), self.env._("Gross value")],
            [[row["prefix"], whole(row["lines"]), whole(row["gross"])] for row in result["prefixes"]],
        )
        pairs = table(
            [self.env._("Pair"), self.env._("Pearson r on daily volumes")],
            [["%s / %s" % (pair["a"], pair["b"]), "—" if pair["r"] is None else decimal(pair["r"], locale)] for pair in result["pairs"]],
        )
        matrix = table(
            [self.env._("Month")] + list(range(1, 32)),
            [["%02d" % (index + 1)] + [value or "" for value in row] for index, row in enumerate(result["matrix"])],
        )
        self.matrix_html = Markup("<p>{}</p>{}{}{}").format(
            self.env._("%(count)s journals touch every selected prefix", count=result["sharedJournals"]), prefixes, pairs, matrix,
        )

    # ------------------------------------------------------------------
    # Drilling: Odoo's own list, on the same filter
    # ------------------------------------------------------------------

    def _month_input(self):
        """As the tables show it, MM/YYYY, or the source's YYYY-MM; a wrong one is refused later."""
        text = (self.drill_month or "").strip()
        match = _MONTH_INPUT.match(text)
        return "%s-%s" % (match[2], match[1]) if match else text

    def _drill(self, filter_, name, grouped=False):
        return self.engagement_id.gl_drill_action(self.dataset_id.id, filter_, name, grouped)

    def action_drill_month(self):
        """An analytic's row (AnalyticsView.onMonth): the lines of that month."""
        self.ensure_one()
        month = self._month_input()
        if not month:
            raise rule_error(self.env, "invalid-month")
        return self._drill({"month": month}, self.env._("Lines of %(month)s", month=self.drill_month))

    def action_drill_entry(self):
        """A cell of the entry grid: every line of the entries behind it."""
        self.ensure_one()
        filter_ = {"entryAccounts": self._selected(), "entryMode": self.entry_mode, "wholeEntries": True}
        if self.drill_account:
            filter_["accounts"] = [self.drill_account.strip()]
        if self.entry_period == "weekday":
            if self.drill_weekday:
                filter_["weekday"] = self.drill_weekday
        elif self._month_input():
            filter_["month"] = self._month_input()
        return self._drill(filter_, self.env._("Entries behind the cell"), grouped=True)

    def action_drill_correlation(self):
        """A cell of the correlation: one account, in the entries it shares with the other."""
        self.ensure_one()
        account = (self.drill_account or self.corr_a or "").strip()
        other = (self.corr_b if account == (self.corr_a or "").strip() else self.corr_a) or ""
        filter_ = {"accounts": [account], "entryAccounts": [account, other.strip()], "entryMode": "all"}
        if self._month_input():
            filter_["month"] = self._month_input()
        return self._drill(filter_, self.env._("Entries shared by the two accounts"))

    def action_drill_filter(self):
        """LineFilterBar: every condition set must hold."""
        self.ensure_one()
        filter_ = {}
        accounts = split_accounts(self.filter_accounts) or self._selected()
        if accounts:
            filter_["accounts"] = accounts
        if self.filter_date_from:
            filter_["dateFrom"] = self.filter_date_from.isoformat()
        if self.filter_date_to:
            filter_["dateTo"] = self.filter_date_to.isoformat()
        for key, value in (("minAbs", self.filter_min_abs), ("maxAbs", self.filter_max_abs)):
            if (value or "").strip():
                number = amount_input(value)
                if number is not None:
                    filter_[key] = number
        for key, value in (
            ("journalCode", self.filter_journal), ("jeNumber", self.filter_je), ("preparer", self.filter_preparer),
            ("reviewer", self.filter_reviewer), ("approver", self.filter_approver),
        ):
            if (value or "").strip():
                filter_[key] = value.strip()
        if self.filter_weekend:
            filter_["weekendOnly"] = True
        if self.filter_missing_reference:
            filter_["missingReference"] = True
        return self._drill(filter_, self.env._("Filtered lines"))

    def action_drill_figure(self):
        """The lines behind the lead-schedule figure."""
        self.ensure_one()
        return self._drill({"accounts": (self.figure_accounts or "").split(",")}, self.env._("Lines behind the figure"))

    def action_build_projection(self):
        self.ensure_one()
        self.engagement_id.gl_build_projection(self.dataset_id.id)
