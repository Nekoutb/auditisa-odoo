"""The import of a file, in three steps and for the nine kinds: upload, match the columns, check.
Nothing is kept before Import is pressed on the last step. The deletion of an upload is confirmed
here too."""
import base64

from markupsafe import Markup

from odoo import Command, api, fields, models

from ..models.dataset import DATASET_TIMING_SELECTION
from ..models.import_matching import IMPORT_KIND_SELECTION
from ..models.tool_record import grouped, is_french, upload_stamp
from ..rules import rule_error
from ..services.dataset_mapping import JE_KEY, JE_KEY_MAX, encode_je_key, je_key_columns
from ..services.import_matching import JE_KEY_LABEL, TB_KIND, fields_of, groups_of, mandatory_marks, missing_fields, required_keys
from ..services.subsequent import SUBSEQUENT, SUBSEQUENT_KINDS

_RELOAD = {"type": "ir.actions.client", "tag": "soft_reload"}
_SEPARATOR = {";": ";", ",": ",", "tab": "\t", "|": "|"}
_SHOWN_ROWS = 8
_EFFECT_CSS = {"left_out": "o_ea_chip", "warning": "o_ea_chip o_ea_chip_warn", "blocking": "o_ea_chip o_ea_chip_bad"}


class ImportWizard(models.TransientModel):
    """Upload, then match the columns, then check, then import. The first three write nothing."""

    _name = "ea.audit.import.wizard"
    _description = "Import data"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    kind = fields.Selection(IMPORT_KIND_SELECTION, string="Kind of data", required=True, default=TB_KIND)
    timing = fields.Selection(DATASET_TIMING_SELECTION, default="pre_audit", required=True)
    file = fields.Binary(string="File (.csv, .xlsx)", required=True)
    filename = fields.Char()
    header_row = fields.Boolean(string="The first line holds the column titles", default=True)
    step = fields.Selection(
        [("upload", "1 Upload"), ("match", "2 Match the columns"), ("check", "3 Check")], default="upload", required=True,
    )
    template_html = fields.Html(compute="_compute_template_html", sanitize=False)

    # The reading options: automatic unless a person chooses.
    is_excel = fields.Boolean(compute="_compute_file_kind")
    has_dates = fields.Boolean(compute="_compute_file_kind")
    sheet_ids = fields.One2many("ea.audit.import.wizard.sheet", "wizard_id", string="Sheets of the file")
    sheet_id = fields.Many2one("ea.audit.import.wizard.sheet", string="Sheet", domain="[('wizard_id', '=', id)]")
    csv_separator = fields.Selection(
        [("auto", "Automatic"), (";", "Semicolon ;"), (",", "Comma ,"), ("tab", "Tab"), ("|", "Vertical bar |")],
        string="Column separator", default="auto", required=True,
    )
    decimal_separator = fields.Selection(
        [("auto", "Automatic"), ("comma", "Comma: 1 234,56"), ("point", "Point: 1,234.56")],
        string="Decimal separator", default="auto", required=True,
    )
    date_format = fields.Selection(
        [("auto", "Automatic"), ("dmy", "Day/month/year: 31/12/2025"), ("mdy", "Month/day/year: 12/31/2025"), ("ymd", "Year-month-day: 2025-12-31")],
        string="Date format", default="auto", required=True,
    )
    found_note = fields.Char(readonly=True)

    # The matching.
    row_count = fields.Integer(readonly=True)
    column_ids = fields.One2many("ea.audit.import.wizard.column", "wizard_id", string="Columns of the file")
    je_key_column_ids = fields.Many2many(
        "ea.audit.import.wizard.column", "ea_audit_import_wizard_je_key_rel", "wizard_id", "column_id",
        string="Entry identified by several columns", domain="[('wizard_id', '=', id)]",
        help="Optional, for a ledger whose entry is identified by several columns together (for instance journal and voucher number): choose them here, four at most.",
    )
    remember = fields.Boolean(string="Remember this matching for this client's next file of this kind", default=True)
    match_html = fields.Html(compute="_compute_match", sanitize=False)
    missing_count = fields.Integer(compute="_compute_match")

    # The check.
    check_html = fields.Html(sanitize=False, readonly=True)
    blocking = fields.Boolean(readonly=True)

    # ------------------------------------------------------------------
    # What the file and the lines say
    # ------------------------------------------------------------------

    def _content(self):
        """The file's bytes. A screen reads a binary field as its size: asked for here in full."""
        record = (self._origin or self).with_context(bin_size=False)
        return base64.b64decode(record.file or b"")

    def _options(self):
        return {
            "sheet": self.sheet_id.name or None,
            "delimiter": _SEPARATOR.get(self.csv_separator),
            "decimal": self.decimal_separator,
            "date_format": self.date_format,
        }

    def _mapping(self):
        """{field key: column title} of the lines, and the entry identified by several columns."""
        mapping = {}
        for line in self.column_ids:
            if line.field_id and not line.field_id.skip and line.field_id.key not in mapping:
                mapping[line.field_id.key] = line.header
        if self.kind == "journal_entries" and self.je_key_column_ids:
            mapping[JE_KEY] = encode_je_key(self.je_key_column_ids.sorted("sequence").mapped("header"))
        return mapping

    def _twice(self):
        """The fields chosen on more than one column: a field is fed by one column."""
        seen, twice = set(), []
        for line in self.column_ids:
            field = line.field_id
            if not field or field.skip:
                continue
            if field in seen and field not in twice:
                twice.append(field)
            seen.add(field)
        return twice

    @api.depends("filename", "kind")
    def _compute_file_kind(self):
        for wizard in self:
            wizard.is_excel = (wizard.filename or "").lower().endswith(".xlsx")
            wizard.has_dates = any(field["key"] in ("date", "journalDate", "jeDate") for field in fields_of(wizard.kind or TB_KIND))

    @api.depends("engagement_id", "kind")
    @api.depends_context("lang")
    def _compute_template_html(self):
        """F016. A link, not a button: a button would save the wizard, and the file is still missing."""
        for wizard in self:
            export = "tb_template" if wizard.kind == TB_KIND else "template_%s" % wizard.kind
            wizard.template_html = Markup("<a href='/ea_audit_tools/export/{export}/{id}' data-ea-template='1'>{label}</a>").format(
                export=export, id=wizard.engagement_id.id, label=self.env._("Download the template for this kind of data"),
            )

    @api.depends("column_ids.field_id", "je_key_column_ids", "kind", "row_count")
    @api.depends_context("lang")
    def _compute_match(self):
        """The banner of the matching step: what is matched, or what is still missing and how to give it."""
        for wizard in self:
            kind = wizard.kind or TB_KIND
            french = is_french(self.env)
            language = "fr" if french else "en"
            labels = {field["key"]: field[language] for field in fields_of(kind)}
            labels[JE_KEY] = JE_KEY_LABEL[language]
            mapping = wizard._mapping()
            missing = missing_fields(kind, mapping)
            twice = wizard._twice()
            wizard.missing_count = len(missing) + len(twice)
            if not wizard.column_ids:
                wizard.match_html = False
                continue
            chip = Markup("<span class='o_ea_chip {css} me-1'>{text}</span>")
            if not missing and not twice:
                chips = []
                for key in required_keys(kind):
                    chips.append(chip.format(css="o_ea_chip_good", text="%s ← %s" % (labels[key], mapping[key])))
                marks = mandatory_marks(kind, mapping)
                for group in groups_of(kind):
                    used = [key for alternative in group["alternatives"] for key in alternative if key in marks]
                    titles = je_key_columns(mapping) if used == [JE_KEY] else [mapping[key] for key in used]
                    chips.append(chip.format(css="o_ea_chip_good", text="%s ← %s" % (group[language], " + ".join(titles))))
                wizard.match_html = Markup("<div class='alert alert-success mb-2' role='status'><b>{head}</b><div class='mt-1'>{chips}</div></div>").format(
                    head=self.env._("All mandatory fields are matched. %(count)s lines in the file.", count=grouped(wizard.row_count, self.env.lang)),
                    chips=Markup("").join(chips),
                )
                continue
            lines, chips = [], []
            for entry in missing:
                if entry["alternatives"]:
                    ways = [" + ".join(labels[key] for key in alternative) for alternative in entry["alternatives"]]
                    lines.append(self.env._(
                        "%(name)s: choose the column(s) for %(ways)s.", name=entry[language], ways=(" %s " % self.env._("or")).join(ways),
                    ))
                else:
                    lines.append(self.env._("%(name)s: choose its column.", name=entry[language]))
                chips.append(chip.format(css="o_ea_chip_bad", text=self.env._("Missing: %(name)s", name=entry[language])))
            for field in twice:
                lines.append(self.env._("%(name)s is chosen for more than one column: keep it on one.", name=field.display_name))
            wizard.match_html = Markup(
                "<div class='alert alert-danger mb-2' role='alert'><b>{head}</b>{lines}<div class='mt-1'>{chips}</div></div>"
            ).format(
                head=self.env._("%(count)s point(s) still to settle. The file cannot be imported yet.", count=len(missing) + len(twice)),
                lines=Markup("").join(Markup("<div>{}</div>").format(line) for line in lines),
                chips=Markup("").join(chips),
            )

    # ------------------------------------------------------------------
    # Step 1 to step 2: read the file
    # ------------------------------------------------------------------

    def _ea_title(self):
        if self.step == "upload" or not self.filename:
            return self.env._("Import data")
        kinds = dict(self._fields["kind"]._description_selection(self.env))
        return "%s · %s" % (kinds.get(self.kind, ""), self.filename)

    def _ea_reopen(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
            "view_mode": "form", "views": [(False, "form")], "target": "new", "name": self._ea_title(), "context": {"dialog_size": "extra-large"},
        }

    def _ea_found_note(self, found):
        """What the reader found by itself, said under the options."""
        parts = []
        separator = {";": self.env._("semicolon"), ",": self.env._("comma"), "\t": self.env._("tab"), "|": self.env._("vertical bar")}.get(found["delimiter"])
        if separator:
            parts.append(self.env._("column separator: %(found)s", found=separator))
        decimal = {"comma": self.env._("comma"), "point": self.env._("point")}.get(found["decimal"])
        if decimal:
            parts.append(self.env._("decimal separator: %(found)s", found=decimal))
        order = {
            "dmy": self.env._("day/month/year"), "mdy": self.env._("month/day/year"), "ymd": self.env._("year-month-day"),
        }.get(found["date"])
        if order:
            parts.append(self.env._("dates: %(found)s", found=order))
        return self.env._("Found in the file: %(found)s.", found=", ".join(parts)) if parts else False

    def _ea_load_columns(self):
        """One line per column of the file, with the field proposed for it."""
        self.ensure_one()
        engagement = self.engagement_id
        read = engagement.ea_import_read(self.kind, self.filename, self._content(), self.header_row, self._options())
        Field = self.env["ea.audit.import.field"]
        by_header = {header: key for key, header in read["mapping"].items() if key != JE_KEY}
        skip = Field._ea_of(self.kind)
        lines = [Command.clear()]
        for sequence, header in enumerate(read["headers"]):
            field = Field._ea_of(self.kind, by_header.get(header)) or skip
            lines.append(Command.create({
                "sequence": sequence, "header": header, "sample": " · ".join(read["headerSamples"].get(header, [])),
                "field_id": field.id, "detected_field_id": field.id,
            }))
        self.je_key_column_ids = [Command.clear()]
        self.column_ids = lines
        self._ea_mark_lines()
        self.row_count = read["rowCount"]
        self.found_note = self._ea_found_note(read["found"])
        return read

    def action_read(self):
        """Read the file: opens it and proposes a matching. Saves nothing of it."""
        self.ensure_one()
        if self.timing == SUBSEQUENT and self.kind not in SUBSEQUENT_KINDS:
            raise rule_error(self.env, "subsequent-kind")
        self.write({"sheet_id": False, "csv_separator": "auto", "decimal_separator": "auto", "date_format": "auto"})
        read = self._ea_load_columns()
        sheets = [Command.clear()] + [Command.create({"sequence": position, "name": name}) for position, name in enumerate(read["sheets"])]
        self.write({"sheet_ids": sheets, "step": "match", "check_html": False, "blocking": False})
        self.sheet_id = self.sheet_ids[:1]
        keys = je_key_columns(read["mapping"])
        if keys:
            self.je_key_column_ids = [Command.set(self.column_ids.filtered(lambda line: line.header in keys).ids)]
        return self._ea_reopen()

    @api.onchange("sheet_id", "csv_separator")
    def _onchange_reading(self):
        """Another sheet or another separator is another set of columns: the file is read again."""
        if self.step == "match" and self.filename and (self._origin or self).file:
            self._ea_load_columns()

    @api.onchange("je_key_column_ids")
    def _onchange_je_key(self):
        if len(self.je_key_column_ids) > JE_KEY_MAX:
            self.je_key_column_ids = [Command.set(self.je_key_column_ids.ids[:JE_KEY_MAX])]

    @api.onchange("column_ids", "je_key_column_ids")
    def _onchange_marks(self):
        self._ea_mark_lines()

    def _ea_mark_lines(self):
        """The mark beside each field the import cannot do without, as matched now. A line's mark
        depends on its neighbours (the debit's waits for the credit's column), and a screen is
        only told of a line's change when the value was stored and has moved: so the mark is a
        plain field, set here for every line at each change, and not a computed one."""
        for wizard in self:
            marks = mandatory_marks(wizard.kind or TB_KIND, wizard._mapping())
            for line in wizard.column_ids:
                mark = self.env._("mandatory") if line.field_id.key in marks and not line.field_id.skip else False
                if line.mandatory != mark:
                    line.mandatory = mark

    def write(self, vals):
        result = super().write(vals)
        if "je_key_column_ids" in vals or "kind" in vals:
            self._ea_mark_lines()
        return result

    def action_back_to_upload(self):
        self.ensure_one()
        self.step = "upload"
        return self._ea_reopen()

    # ------------------------------------------------------------------
    # Step 2 to step 3: check the file
    # ------------------------------------------------------------------

    def _ea_refuse_unmatched(self):
        """Not only the button: the method itself refuses while a mandatory field is unmatched."""
        if self._twice():
            raise rule_error(self.env, "field-matched-twice")
        if missing_fields(self.kind, self._mapping()):
            raise rule_error(self.env, "mapping-incomplete")

    def action_check(self):
        """Check the file: the import's own checks, on the file as matched, with nothing kept."""
        self.ensure_one()
        self._ea_refuse_unmatched()
        result = self.engagement_id.ea_import_check(
            self.kind, self.filename, self._content(), self._mapping(), self.header_row, self._options(), timing=self.timing,
        )
        self.write({"step": "check", "check_html": self._ea_check_html(result), "blocking": result["blocking"]})
        return self._ea_reopen()

    def action_back_to_matching(self):
        """The choices stay as they were."""
        self.ensure_one()
        self.step = "match"
        return self._ea_reopen()

    def _ea_where(self, rows):
        if not rows:
            return self.env._("Whole file")
        shown = ", ".join(str(row) for row in rows[:_SHOWN_ROWS])
        more = len(rows) - _SHOWN_ROWS
        if more > 0:
            return self.env._("Lines %(rows)s and %(more)s more", rows=shown, more=more)
        return self.env._("Lines %(rows)s", rows=shown) if len(rows) > 1 else self.env._("Line %(rows)s", rows=shown)

    def _ea_check_html(self, result):
        """Rows read, totals, balanced or not, then each point found with its effect."""
        lang = self.env.lang
        card = Markup(
            "<div class='o_ea_card'><div class='o_ea_card_label'>{label}</div><div class='o_ea_card_value {css}'>{value}</div>"
            "<div class='o_ea_card_note'>{note}</div></div>"
        )
        cards = [card.format(
            label=self.env._("Rows read"), css="", value=grouped(result["rows"], lang),
            note=self.env._("%(lines)s lines in the file, %(left)s left out", lines=grouped(result["fileRows"], lang), left=grouped(result["leftOut"], lang)),
        )]
        if result["balanced"] is None:
            cards.append(card.format(label=self.env._("Total amount"), css="", value=grouped(result["total"], lang), note=""))
        else:
            cards.append(card.format(label=self.env._("Total debit"), css="", value=grouped(result["totalDebit"], lang), note=""))
            cards.append(card.format(label=self.env._("Total credit"), css="", value=grouped(result["totalCredit"], lang), note=""))
            cards.append(card.format(
                label=self.env._("Balanced"), css="text-success" if result["balanced"] else "o_ea_card_bad",
                value=self.env._("Yes") if result["balanced"] else self.env._("No"),
                note=self.env._("difference %(amount)s", amount=grouped(result["difference"], lang)),
            ))
        issues = result["issues"]
        if result["blocking"]:
            banner = Markup("<div class='alert alert-danger' role='alert'><b>{head}</b><div>{body}</div></div>").format(
                head=self.env._("The file cannot be imported."),
                body=self.env._("Read the blocking points below. Correct the file, or go back to the matching if a wrong column was chosen. Nothing has been saved."),
            )
        else:
            notes = [self._ea_takeover_note()]
            if issues:
                notes.append(self.env._("%(count)s point(s) to read below. None of them blocks the import.", count=len(issues)))
            banner = Markup("<div class='alert alert-success' role='status'><b>{head}</b>{notes}</div>").format(
                head=self.env._("The file can be imported. Nothing is saved until you press Import."),
                notes=Markup("").join(Markup("<div>{}</div>").format(note) for note in notes if note),
            )
        effects = {
            "left_out": self.env._("Left out"),
            "warning": self.env._("Imported with a warning"),
            "blocking": self.env._("Blocks the import"),
        }
        table = ""
        if issues:
            rows = Markup("").join(
                Markup("<tr><td class='text-nowrap'>{where}</td><td>{text}</td><td class='text-nowrap'><span class='{css}'>{effect}</span></td></tr>").format(
                    where=self._ea_where(issue["rows"]), text=issue["text"], css=_EFFECT_CSS[issue["effect"]], effect=effects[issue["effect"]],
                )
                for issue in sorted(issues, key=lambda issue: issue["effect"] != "blocking")
            )
            table = Markup(
                "<div class='table-responsive'><table class='table table-sm o_ea_table'><thead><tr><th>{where}</th><th>{found}</th><th>{effect}</th></tr></thead>"
                "<tbody>{rows}</tbody></table></div>"
            ).format(where=self.env._("Where"), found=self.env._("What the system found"), effect=self.env._("Effect"), rows=rows)
        return Markup("<div class='o_ea_cards'>{cards}</div>{banner}{table}").format(cards=Markup("").join(cards), banner=banner, table=table)

    def _ea_takeover_note(self):
        """What becomes of the upload in use: it is superseded and stays on the list."""
        engagement = self.engagement_id.sudo()
        replaced = engagement._ea_import_replaced(self.kind, self.timing)
        stamp = upload_stamp(self, replaced.create_date)
        if self.kind == TB_KIND and self.timing == "pre_audit":
            if replaced:
                return self.env._(
                    "It will drive the file. The version imported on %(stamp)s (%(file)s) stays in the list, superseded.",
                    stamp=stamp, file=replaced.source_filename,
                )
            return self.env._("It will drive the file.")
        if replaced:
            return self.env._(
                "It will be the one in use. The upload of %(stamp)s (%(file)s) stays in the list, superseded.",
                stamp=stamp, file=replaced.source_filename,
            )
        return False

    # ------------------------------------------------------------------
    # Step 3: import
    # ------------------------------------------------------------------

    def action_import(self):
        """The only step that keeps something. The engagement's method checks again and refuses
        a file that fails: the screen is not the control."""
        self.ensure_one()
        self._ea_refuse_unmatched()
        engagement = self.engagement_id
        engagement.ea_import_file(
            self.kind, self.filename, self._content(), self._mapping(), timing=self.timing, header_row=self.header_row,
            options=self._options(), remember=self.remember,
        )
        if self.kind == TB_KIND:
            # F016: nothing stands behind the prior-year column, and the reader should know
            warning = engagement.sudo().with_context(lang=self.env.lang)._ea_tb_openings_warning()
            if warning:
                return {
                    "type": "ir.actions.client", "tag": "display_notification",
                    "params": {"title": self.env._("Opening balances"), "message": warning, "type": "warning", "sticky": True, "next": _RELOAD},
                }
        return _RELOAD


class ImportWizardSheet(models.TransientModel):
    _name = "ea.audit.import.wizard.sheet"
    _description = "Sheet of an imported Excel file"
    _order = "sequence, id"

    wizard_id = fields.Many2one("ea.audit.import.wizard", required=True, ondelete="cascade")
    sequence = fields.Integer()
    name = fields.Char(required=True)


class ImportWizardColumn(models.TransientModel):
    """One column of the file: its title, its first values, and the field chosen for it."""

    _name = "ea.audit.import.wizard.column"
    _description = "Column of an imported file"
    _order = "sequence, id"
    _rec_name = "header"

    wizard_id = fields.Many2one("ea.audit.import.wizard", required=True, ondelete="cascade")
    kind = fields.Selection(related="wizard_id.kind")
    sequence = fields.Integer()
    header = fields.Char(string="Column in your file", readonly=True)
    sample = fields.Char(string="First three values", readonly=True)
    field_id = fields.Many2one(
        "ea.audit.import.field", string="AuditISA field", required=True, ondelete="cascade", domain="[('kind', '=', kind)]",
    )
    detected_field_id = fields.Many2one("ea.audit.import.field", ondelete="cascade", readonly=True)
    mandatory = fields.Char(string="Mandatory", readonly=True)
    match_state = fields.Selection(
        [("auto", "Matched automatically"), ("you", "Chosen by you"), ("none", "Not recognised")],
        string="How it was matched", compute="_compute_match_state",
    )

    @api.depends("field_id", "detected_field_id")
    def _compute_match_state(self):
        for line in self:
            if line.field_id != line.detected_field_id:
                line.match_state = "you"
            else:
                line.match_state = "none" if line.field_id.skip or not line.field_id else "auto"

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.wizard_id._ea_mark_lines()
        return lines

    def write(self, vals):
        result = super().write(vals)
        if "field_id" in vals:
            self.wizard_id._ea_mark_lines()
        return result


class ImportDeleteWizard(models.TransientModel):
    """The confirmation before an upload is deleted: what goes, and what is in use afterwards.
    No reason is asked and no upload is protected (owner's ruling of 2026-11-15)."""

    _name = "ea.audit.import.delete.wizard"
    _description = "Delete an upload"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True, ondelete="cascade")
    version_id = fields.Many2one("ea.audit.tb.version", ondelete="cascade")
    dataset_id = fields.Many2one("ea.audit.dataset", ondelete="cascade")
    summary_html = fields.Html(compute="_compute_summary_html", sanitize=False)

    @api.model
    def _ea_open(self, engagement, version=None, dataset=None):
        """Refused here as the deletion itself would be, so that nobody confirms for nothing."""
        engagement._ea_tool_guard()
        record = (version or dataset).sudo()
        wizard = self.create({
            "engagement_id": engagement.id, "version_id": version.id if version else False, "dataset_id": dataset.id if dataset else False,
        })
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": wizard.id, "view_mode": "form", "views": [(False, "form")], "target": "new",
            "name": self.env._("Delete the upload of %(stamp)s?", stamp=upload_stamp(self, record.create_date)),
        }

    @api.depends("version_id", "dataset_id")
    @api.depends_context("lang", "tz")
    def _compute_summary_html(self):
        for wizard in self:
            engagement = wizard.engagement_id.sudo()
            record = (wizard.version_id or wizard.dataset_id).sudo()
            if not record:
                wizard.summary_html = False
                continue
            timing = dict(record._fields["timing"]._description_selection(self.env))[record.timing]
            if wizard.version_id:
                status = dict(record._fields["validation_status"]._description_selection(self.env))[record.validation_status]
                state = self.env._("drives the file") if record.is_current else self.env._("does not drive the file")
                content = [timing, status, state]
                after = wizard._ea_after_version(engagement, record)
            else:
                kind = dict(record._fields["kind"]._description_selection(self.env))[record.kind]
                content = [kind, timing, self.env._("in use") if record.is_current else self.env._("superseded")]
                after = wizard._ea_after_dataset(engagement, record)
            facts = Markup(
                "<table class='table table-sm o_ea_table'><tbody><tr><th>{file}</th><td>{name}</td></tr>"
                "<tr><th>{imported}</th><td>{who}</td></tr><tr><th>{content}</th><td>{what}</td></tr></tbody></table>"
            ).format(
                file=self.env._("File"), name=record.source_filename or "",
                imported=self.env._("Imported"), who=self.env._(
                    "by %(name)s on %(stamp)s", name=record.create_uid.name or "", stamp=upload_stamp(self, record.create_date),
                ),
                content=self.env._("Content"), what=" · ".join([self.env._("%(count)s rows", count=grouped(record.row_count, self.env.lang))] + content),
            )
            notes = [self.env._("The rows of this upload are removed for good.")] + after + [
                self.env._("A line stays in the engagement log: who deleted it, when, the file name, its rows and its totals."),
            ]
            wizard.summary_html = facts + Markup("").join(Markup("<p>{}</p>").format(note) for note in notes)

    def _ea_after_version(self, engagement, version):
        """What reads the trial balance once this version is gone."""
        in_use = version.is_current or (version.timing != "pre_audit" and version.validation_status == "valid" and not version.superseded_at)
        if not in_use:
            return []
        successor = engagement._ea_tb_successor(version)
        stamp = upload_stamp(self, successor.create_date)
        if version.timing == "pre_audit":
            if successor:
                return [self.env._(
                    "This version drives the file. Once it is deleted, the version imported on %(stamp)s (%(file)s) drives the file again and the lead schedules are recalculated.",
                    stamp=stamp, file=successor.source_filename,
                )]
            return [self.env._(
                "This version drives the file and no other valid pre-audit version remains: once it is deleted, the file has no trial balance and the lead schedules are emptied.",
            )]
        if successor:
            return [self.env._(
                "This version is the one in use for its timing. Once it is deleted, the version imported on %(stamp)s (%(file)s) is used instead.",
                stamp=stamp, file=successor.source_filename,
            )]
        return [self.env._("This version is the one in use for its timing, and no other one remains for it.")]

    def _ea_after_dataset(self, engagement, dataset):
        notes = [self.env._("Samples and selections already drawn from it are kept, without their link to this file.")]
        if dataset.superseded_at:
            return notes
        successor = engagement._ea_dataset_successor(dataset)
        if successor:
            notes.insert(0, self.env._(
                "This upload is the one in use. Once it is deleted, the upload of %(stamp)s (%(file)s) is in use again.",
                stamp=upload_stamp(self, successor.create_date), file=successor.source_filename,
            ))
        else:
            notes.insert(0, self.env._("This upload is the one in use, and no other one of this kind and timing remains."))
        return notes

    def action_confirm(self):
        self.ensure_one()
        engagement = self.engagement_id
        if self.version_id:
            engagement.delete_tb_version(self.version_id.id)
        elif self.dataset_id:
            engagement.delete_dataset(self.dataset_id.id)
        return _RELOAD
