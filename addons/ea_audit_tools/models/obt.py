"""Opening Balance Testing (owner's mock-ups "obt" v4, approved 20/11/2026; ISA 510, working paper E6.5).

Three steps on one page, as the mock-ups show them:
1. the prior-year financial statements are uploaded (PDF or photos), as signed;
2. AuditISA reads them into the lines of the SYSCOHADA balance sheet (services/obt_reader.py), or the
   user types the figures by hand; nothing read is used until a person confirms it, and every figure
   corrected is kept with who corrected it;
3. the confirmed figures are compared with the trial balance's opening balances, grouped with the
   owner's own table (services/obt.py). Above 1 FCFA a line is a difference: the user is warned on the
   page, on the tile and on E6.5, and every difference is gathered in one table for appreciation, with
   an Excel extract. No sign-off on the tool (owner's rulings, 20/11/2026).

The key that lets this server read is the firm's own, set by the platform owner on the console. It
reaches this server through the heartbeat (ea_audit_firm_agent) and lives in a file of Odoo's data
folder, readable by Odoo's own user only, never in the database (KEY_FILE).
"""
import base64
import json
import logging
import os
import re

from odoo import api, fields, models
from odoo.tools import config

from ..rules import rule_error
from .. import obt_reading as obt_reader
from ..services import obt
from .tool_record import grouped, is_french, upload_stamp

_logger = logging.getLogger(__name__)

#: Where the firm's reading key is, under Odoo's data folder. ea_audit_firm_agent writes it (same path).
KEY_FILE = ("auditisa", "document-reading.key")
#: This month's use, read by ea_audit_firm_agent for the console: {"month": "2026-11", "documents": n, "pages": n}.
PARAM_USAGE = "ea_audit_tools.document_reading_usage"
TILE_CODE = "opening-balance-testing"
STEPS = [("upload", "Upload"), ("check", "Check"), ("result", "Result")]
UNIT_SELECTION = [("units", "Units"), ("thousands", "Thousands"), ("millions", "Millions")]
MAX_FILES = 12
_FORM = None


def form():
    """The SYSCOHADA balance-sheet table, read once per process."""
    global _FORM
    if _FORM is None:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "services", obt.FORM_FILE_NAME)
        with open(path, encoding="utf-8") as handle:
            _FORM = obt.load_form(handle.read())
    return _FORM


def key_path():
    return os.path.join(config["data_dir"], *KEY_FILE)


def read_key():
    """The firm's reading key, or "" when the platform owner has not set one for this firm."""
    try:
        with open(key_path(), encoding="ascii") as handle:
            return handle.read(512).strip()
    except (OSError, UnicodeDecodeError):
        return ""


def reading_installed():
    try:
        import anthropic  # noqa: F401, PLC0415  only whether it is there
    except ImportError:
        return False
    return True


class OpeningBalanceTest(models.Model):
    """One per engagement: the statements, their figures, and where the page is."""

    _name = "ea.audit.obt"
    _inherit = ["ea.audit.tool.record"]
    _description = "Opening Balance Testing"
    _rec_name = "engagement_id"

    step = fields.Selection(STEPS, required=True, default="upload")
    source = fields.Selection([("reader", "Read by AuditISA"), ("hand", "Typed by hand")])
    year_end = fields.Date(string="Year of the statements")
    signed = fields.Boolean(string="Signed or approved statements", default=True)
    unit = fields.Selection(UNIT_SELECTION, default="units", required=True)
    column = fields.Char(string="Column used")
    net_result = fields.Float(string="Net result on the income statement", digits=(18, 2))
    has_net_result = fields.Boolean()
    read_at = fields.Datetime(string="Read on")
    read_by_id = fields.Many2one("res.users", string="Read by")
    read_error = fields.Char(string="Last reading problem")
    confirmed_at = fields.Datetime(string="Confirmed on")
    confirmed_by_id = fields.Many2one("res.users", string="Confirmed by")
    file_ids = fields.One2many("ea.audit.obt.file", "obt_id", string="Statements")
    line_ids = fields.One2many("ea.audit.obt.line", "obt_id", string="Figures")

    _engagement_uniq = models.Constraint("UNIQUE(engagement_id)", "One Opening Balance Testing per engagement.")


class OpeningBalanceFile(models.Model):
    _name = "ea.audit.obt.file"
    _inherit = ["ea.audit.tool.record"]
    _description = "Opening Balance Testing statements"
    _order = "id"

    obt_id = fields.Many2one("ea.audit.obt", required=True, ondelete="cascade", index=True)
    name = fields.Char(required=True)
    mimetype = fields.Char()
    data = fields.Binary(attachment=True, required=True)


class OpeningBalanceLine(models.Model):
    """One reference of the form: the figure read, the figure kept, and the appreciation of a difference."""

    _name = "ea.audit.obt.line"
    _inherit = ["ea.audit.tool.record"]
    _description = "Opening Balance Testing figure"
    _order = "sequence, id"
    _rec_name = "ref"

    obt_id = fields.Many2one("ea.audit.obt", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer()
    ref = fields.Char(required=True)
    amount = fields.Float(digits=(18, 2))
    has_amount = fields.Boolean()
    read_amount = fields.Float(digits=(18, 2))
    has_read = fields.Boolean()
    page = fields.Integer()
    corrected_by_id = fields.Many2one("res.users")
    corrected_at = fields.Datetime()
    appreciation = fields.Text()
    appreciation_by_id = fields.Many2one("res.users")
    appreciation_at = fields.Datetime()

    _obt_ref_uniq = models.Constraint("UNIQUE(obt_id, ref)", "A reference is kept once.")


class OpeningBalancePlacement(models.Model):
    """Where a "p" account goes for one client, chosen once (owner, 20/11/2026)."""

    _name = "ea.audit.obt.placement"
    _inherit = ["ea.audit.tool.record"]
    _description = "Opening Balance Testing placement"

    client_id = fields.Many2one("ea.audit.client", required=True, index=True, ondelete="cascade")
    account = fields.Char(required=True)
    ref = fields.Char(required=True)

    _client_account_uniq = models.Constraint("UNIQUE(client_id, account)", "An account is placed once per client.")


class ToolTileObt(models.Model):
    _inherit = "ea.audit.tool.tile"

    @api.depends_context("ea_engagement_id", "lang")
    def _compute_upload_chip(self):
        """The tile warns of differences not yet appreciated (owner, 20/11/2026)."""
        super()._compute_upload_chip()
        tile = self.filtered(lambda t: t.code == TILE_CODE)
        engagement = self.env["ea.audit.engagement"].browse(self.env.context.get("ea_engagement_id")).exists()
        if not tile or not engagement or not (self.env.su or engagement._ea_member(self.env.user)):
            return
        warning = engagement.sudo()._ea_obt_warning()
        if warning:
            tile.upload_chip, tile.uploaded = warning, False
        elif engagement.sudo()._ea_obt_record().step == "result":
            tile.upload_chip, tile.uploaded = self.env._("Agrees with the prior-year statements"), True


class EngagementObt(models.Model):
    _inherit = "ea.audit.engagement"

    # ------------------------------------------------------------------ reading the record

    def _ea_obt_record(self):
        self.ensure_one()
        return self.env["ea.audit.obt"].sudo().search([("engagement_id", "=", self.id)], limit=1)

    def _ea_obt_editable(self):
        """The record, created on first use, for a member who may change the file."""
        self.ensure_one()
        self._ea_tool_guard()
        record = self._ea_obt_record()
        if not record:
            record = self.env["ea.audit.obt"].sudo().create({"engagement_id": self.id})
        return record

    def _ea_obt_readonly(self):
        root = self.sudo()
        if root._ea_is_archived():
            return "archived"
        role = self.env.user._ea_firm_role()
        if not role or role == "read_only" or root._ea_acts_as_eqr(self.env.user):
            return "read-only"
        return False

    def _ea_obt_opening(self):
        """[{account, name, opening}] of the trial balance in use, and its file name."""
        version = self.sudo()._ea_current_tb_version()
        accounts = [
            {"account": line.account_code or "", "name": line.account_name or "", "opening": line.opening}
            for line in version.line_ids
        ]
        return accounts, version

    def _ea_obt_chosen(self):
        client = self.sudo().client_id
        placements = self.env["ea.audit.obt.placement"].sudo().search([("client_id", "=", client.id)])
        return {p.account: p.ref for p in placements}

    def _ea_obt_figures(self, record):
        """{ref: amount} of what was confirmed (or is being checked)."""
        return {line.ref: line.amount for line in record.line_ids if line.has_amount}

    def _ea_obt_compare(self, record=None):
        """(rows, summary, grouping) of the comparison, or None without figures or trial balance."""
        record = record or self._ea_obt_record()
        accounts, version = self._ea_obt_opening()
        if not record or not version:
            return None
        lines, unmapped, to_choose = obt.group(accounts, form(), self._ea_obt_chosen())
        opening = {ref: line["amount"] for ref, line in lines.items()}
        line_refs = {row["ref"] for row in form() if row["kind"] == "line"}
        statements = {ref: amount for ref, amount in self._ea_obt_figures(record).items() if ref in line_refs}
        rows = obt.compare(statements, opening, form())
        return rows, obt.summary(rows), {"lines": lines, "unmapped": unmapped, "to_choose": to_choose}

    def _ea_obt_open_differences(self, record, rows):
        """The lines that differ, and those of them with no appreciation yet."""
        appreciated = {line.ref for line in record.line_ids if (line.appreciation or "").strip()}
        differing = [row for row in rows if row["kind"] == "line" and not row["empty"] and not row["agrees"]]
        return differing, [row for row in differing if row["ref"] not in appreciated]

    def _ea_obt_warning(self):
        """The warning of the tile and of E6.5, or "" (no difference, or every one appreciated)."""
        self.ensure_one()
        record = self._ea_obt_record()
        if not record or record.step != "result":
            return ""
        compared = self._ea_obt_compare(record)
        if not compared:
            return ""
        differing, open_ = self._ea_obt_open_differences(record, compared[0])
        if not open_:
            return ""
        return self.env._("⚠ %(count)s difference(s) to appreciate", count=len(open_))

    # ------------------------------------------------------------------ the page

    def action_tool_obt(self):
        """Opening Balance Testing (owner's mock-ups "obt", 20/11/2026)."""
        self.ensure_one()
        self._ea_require_access()
        return {
            "type": "ir.actions.client", "tag": "ea_audit_tools.obt_page", "target": "current",
            "name": self.env._("Opening Balance Testing"), "params": {"engagement_id": self.id},
            "context": {"active_id": self.id, "ea_engagement_id": self.id},
        }

    def _ea_obt_label(self, ref, fr):
        row = next(row for row in form() if row["ref"] == ref)
        return row["label_fr"] if fr else row["label_en"]

    def _ea_obt_reading_state(self):
        """(available, why): whether this server can read documents, else the sentence that says why."""
        _ = self.env._
        if not reading_installed():
            return False, _("Reading by AuditISA is not available on this server yet: type the figures by hand.")
        if not read_key():
            return False, _("Reading by AuditISA is not set up for this firm: type the figures by hand, or ask the platform to set it up.")
        return True, ""

    def _ea_obt_error_text(self, code):
        _ = self.env._
        return {
            "not_installed": _("Reading by AuditISA is not available on this server yet: type the figures by hand."),
            "no_key": _("Reading by AuditISA is not set up for this firm: type the figures by hand, or ask the platform to set it up."),
            "key_refused": _("The reading service refused this firm's key: ask the platform to check it. You can type the figures by hand."),
            "unreachable": _("The reading service could not be reached: try again in a moment, or type the figures by hand."),
            "busy": _("The reading service is busy: try again in a moment."),
            "too_large": _("The files are too large to be read together (22 MB at most): upload the balance sheet and income statement pages only."),
            "unsupported": _("Only PDF files and photos (PNG, JPG) can be read."),
            "refused": _("The reading service declined these pages: type the figures by hand."),
            "unreadable": _("These pages could not be read into a table: check that they are the financial statements, or type the figures by hand."),
            "failed": _("The reading failed: try again, or type the figures by hand."),
        }.get(code, _("The reading failed: try again, or type the figures by hand."))

    def _ea_obt_amount(self, value, fr):
        return grouped(value or 0, "fr_FR" if fr else "en_US")

    def ea_obt_page(self):
        """What the page shows, every word already in the reader's language."""
        self.ensure_one()
        self._ea_require_access()
        fr = is_french(self.env)
        root = self.sudo()
        record = self._ea_obt_record()
        readonly = self._ea_obt_readonly()
        available, why = self._ea_obt_reading_state()
        accounts, version = self._ea_obt_opening()
        page = {
            "engagement": "%s · %s" % (root.client_id.name or "", root.fiscal_year or ""),
            "readonly": bool(readonly), "archived": readonly == "archived",
            "step": record.step if record else "upload",
            "reading": {"available": available, "why": why},
            "tb": {"file": version.source_filename or "", "accounts": len(accounts)} if version else None,
            "files": [], "meta": {}, "check": None, "result": None,
        }
        if not record:
            page["meta"] = {"signed": True, "unit": "units", "yearEnd": "", "column": "", "source": "", "error": ""}
            return page
        page["files"] = [{
            "id": f.id, "name": f.name, "ext": (f.name.rsplit(".", 1)[-1] if "." in f.name else "").upper()[:4],
            "url": "/web/content?model=ea.audit.obt.file&id=%d&field=data&filename_field=name&download=true" % f.id,
            "by": f.create_uid.name, "date": upload_stamp(f, f.create_date),
        } for f in record.file_ids]
        page["meta"] = {
            "signed": record.signed, "unit": record.unit, "yearEnd": fields.Date.to_string(record.year_end) if record.year_end else "",
            "column": record.column or "", "source": record.source or "",
            "readAt": upload_stamp(record, record.read_at) if record.read_at else "", "readBy": record.read_by_id.name or "",
            "confirmedAt": upload_stamp(record, record.confirmed_at) if record.confirmed_at else "",
            "confirmedBy": record.confirmed_by_id.name or "",
            "error": self._ea_obt_error_text(record.read_error) if record.read_error else "",
        }
        _ = self.env._
        meta = page["meta"]
        meta["readLine"] = _("Read on %(when)s by %(who)s", when=meta["readAt"], who=meta["readBy"]) if record.read_at else ""
        if meta["readLine"] and record.column:
            meta["readLine"] += " · " + record.column
        meta["confirmedLine"] = (_("Statements confirmed by %(who)s on %(when)s", who=meta["confirmedBy"], when=meta["confirmedAt"])
                                 if record.confirmed_at else "")
        meta["tbLine"] = (_("Trial balance %(file)s, opening balances, grouped with the SYSCOHADA balance-sheet table",
                            file=version.source_filename or "") if version else "")
        if record.step == "check":
            page["check"] = self._ea_obt_check_view(record, fr)
        elif record.step == "result":
            page["result"] = self._ea_obt_result_view(record, fr)
        return page

    def _ea_obt_check_view(self, record, fr):
        by_ref = {line.ref: line for line in record.line_ids}
        rows = []
        for row in form():
            line = by_ref.get(row["ref"])
            rows.append({
                "ref": row["ref"], "label": self._ea_obt_label(row["ref"], fr), "side": row["side"], "kind": row["kind"],
                "amount": line.amount if line and line.has_amount else None,
                "text": self._ea_obt_amount(line.amount, fr) if line and line.has_amount else "",
                "page": line.page if line and line.page else "",
                "corrected": bool(line and line.corrected_by_id),
                "correctedBy": self.env._("corrected by %(who)s", who=line.corrected_by_id.name) if line and line.corrected_by_id else "",
            })
        read = {line.ref: line.amount for line in record.line_ids if line.has_amount}
        checks = []
        for check in obt.arithmetic_checks(read, form()):
            if check["key"] == "balance":
                text = self.env._("Total assets = total liabilities and equity (%(a)s / %(b)s)",
                                  a=self._ea_obt_amount(check["expected"], fr), b=self._ea_obt_amount(check["found"], fr))
            else:
                text = self.env._("%(ref)s adds up (%(found)s, its lines give %(expected)s)", ref=check["refs"][0],
                                  found=self._ea_obt_amount(check["found"], fr), expected=self._ea_obt_amount(check["expected"], fr))
            checks.append({"ok": check["ok"], "text": text, "refs": check["refs"]})
        if record.has_net_result and "CJ" in read:
            ok = abs(record.net_result - read["CJ"]) <= obt.TOLERANCE
            checks.append({"ok": ok, "refs": ["CJ"], "text": self.env._(
                "Net result in the balance sheet = income statement (%(a)s / %(b)s)",
                a=self._ea_obt_amount(read["CJ"], fr), b=self._ea_obt_amount(record.net_result, fr))})
        return {"rows": rows, "checks": checks, "carrying": len([r for r in rows if r["kind"] == "line" and r["amount"]])}

    def _ea_obt_result_view(self, record, fr):
        compared = self._ea_obt_compare(record)
        if not compared:
            return {"noTb": True}
        rows, summary, grouping = compared
        appreciation = {line.ref: line for line in record.line_ids}
        out = {"asset": [], "liability": []}
        for row in rows:
            if row["empty"]:
                continue
            accounts = grouping["lines"].get(row["ref"], {}).get("accounts", [])
            out[row["side"]].append({
                "ref": row["ref"], "label": self._ea_obt_label(row["ref"], fr), "total": row["kind"] != "line",
                "statements": self._ea_obt_amount(row["statements"], fr), "opening": self._ea_obt_amount(row["opening"], fr),
                "difference": self._ea_obt_amount(row["difference"], fr), "agrees": row["agrees"],
                "accounts": len(accounts) if row["kind"] == "line" else 0,
                "accountsText": self.env._("%(count)s account(s) ▸", count=len(accounts)) if row["kind"] == "line" and accounts else "",
            })
        differing, open_ = self._ea_obt_open_differences(record, rows)
        differences = [{
            "ref": row["ref"], "label": self._ea_obt_label(row["ref"], fr),
            "statements": self._ea_obt_amount(row["statements"], fr), "opening": self._ea_obt_amount(row["opening"], fr),
            "difference": self._ea_obt_amount(row["difference"], fr),
            "appreciation": appreciation[row["ref"]].appreciation or "" if row["ref"] in appreciation else "",
            "by": (self.env._("by %(who)s", who=appreciation[row["ref"]].appreciation_by_id.name)
                   if row["ref"] in appreciation and appreciation[row["ref"]].appreciation_by_id else ""),
        } for row in differing]
        choose = [{
            "account": item["account"], "name": item["name"], "opening": self._ea_obt_amount(item["opening"], fr),
            "choices": [{"ref": ref, "label": "%s %s" % (ref, self._ea_obt_label(ref, fr))} for ref in item["choices"]],
        } for item in grouping["to_choose"]]
        unmapped = [{"account": item["account"], "name": item["name"], "opening": self._ea_obt_amount(item["opening"], fr)}
                    for item in grouping["unmapped"]]
        _ = self.env._
        warning = ""
        if differing:
            warning = _("The opening balances do not agree with the prior-year statements on %(count)s line(s) (tolerance 1 FCFA).",
                        count=len(differing))
        related = [{
            "key": "net", "label": _("Net result: income statement = balance sheet"),
            "result": (self._ea_obt_amount(record.net_result, fr) + " / " + self._ea_obt_amount(
                next((r["statements"] for r in rows if r["ref"] == "CJ"), 0), fr)) if record.has_net_result else _("Not printed on the statements read"),
        }]
        return {
            "warning": warning, "toAppreciate": len(open_),
            "score": {
                "lines": summary["lines"], "agree": summary["agree"], "differences": summary["differences"],
                "assets": "%d / %d" % (summary["by_side"]["asset"]["agree"], summary["by_side"]["asset"]["lines"]),
                "liabilities": "%d / %d" % (summary["by_side"]["liability"]["agree"], summary["by_side"]["liability"]["lines"]),
                "notMapped": len(unmapped) + len(choose),
                "headline": _("%(agree)s of %(lines)s lines", agree=summary["agree"], lines=summary["lines"]),
                "totals": _("Total assets differ by %(assets)s · total liabilities and equity by %(liabilities)s",
                            assets=self._ea_obt_amount(summary["assets_difference"], fr),
                            liabilities=self._ea_obt_amount(summary["liabilities_difference"], fr)),
                "badge": _("%(count)s difference(s)", count=summary["differences"]) if summary["differences"] else _("Agrees"),
            },
            "assets": out["asset"], "liabilities": out["liability"], "differences": differences,
            "choose": choose, "unmapped": unmapped, "related": related,
            "exportUrl": self._ea_export_action("obt")["url"],
            "exportDifferencesUrl": self._ea_export_action("obt_differences")["url"] if differing else "",
        }

    # ------------------------------------------------------------------ the page's actions

    def ea_obt_upload(self, files):
        """[{name, content (base64)}]: the statements, added to the upload step."""
        record = self._ea_obt_editable()
        if record.step != "upload":
            raise rule_error(self.env, "forbidden")
        if len(record.file_ids) + len(files or []) > MAX_FILES:
            raise rule_error(self.env, "invalid-field")
        for item in files or []:
            name = str(item.get("name") or "").strip()[:200] or "statements"
            mimetype = obt_reader.media_type(name, item.get("mimetype"))
            if not mimetype or not item.get("content"):
                raise rule_error(self.env, "invalid-field")
            self.env["ea.audit.obt.file"].sudo().create({
                "engagement_id": self.id, "obt_id": record.id, "name": name, "mimetype": mimetype, "data": item["content"],
            })
            self._ea_log("obt_uploaded", "Opening Balance Testing: %s uploaded" % name)
        return self.ea_obt_page()

    def ea_obt_remove_file(self, file_id):
        record = self._ea_obt_editable()
        found = record.file_ids.filtered(lambda f: f.id == int(file_id or 0))
        if not found or record.step != "upload":
            raise rule_error(self.env, "not-found")
        name = found.name
        found.unlink()
        self._ea_log("obt_removed", "Opening Balance Testing: %s removed" % name)
        return self.ea_obt_page()

    def ea_obt_meta(self, values):
        """The facts of the upload step: signed, the unit, the year."""
        record = self._ea_obt_editable()
        allowed = {"signed", "unit", "year_end"}
        if set(values or {}) - allowed:
            raise rule_error(self.env, "invalid-field")
        changes = {}
        if "signed" in values:
            changes["signed"] = bool(values["signed"])
        if "unit" in values:
            if values["unit"] not in dict(UNIT_SELECTION):
                raise rule_error(self.env, "invalid-field")
            changes["unit"] = values["unit"]
        if "year_end" in values:
            value = values["year_end"] or False
            if value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)):
                raise rule_error(self.env, "invalid-field")
            changes["year_end"] = value
        if changes:
            record.write(changes)
        return self.ea_obt_page()

    def _ea_obt_set_lines(self, record, values, read=None):
        """Every reference of the form gets its line; ``values``: {ref: {amount, page}}."""
        by_ref = {line.ref: line for line in record.line_ids}
        Line = self.env["ea.audit.obt.line"].sudo()
        for sequence, row in enumerate(form()):
            item = values.get(row["ref"])
            vals = {
                "amount": item["amount"] if item else 0.0, "has_amount": bool(item), "page": (item or {}).get("page") or 0,
                "read_amount": item["amount"] if (item and read) else 0.0, "has_read": bool(item and read),
                "corrected_by_id": False, "corrected_at": False,
            }
            line = by_ref.get(row["ref"])
            if line:
                line.write(vals)
            else:
                Line.create({**vals, "engagement_id": self.id, "obt_id": record.id, "ref": row["ref"], "sequence": sequence})

    def ea_obt_read(self):
        """AuditISA reads the statements uploaded. A reading problem is said on the page, nothing is lost."""
        record = self._ea_obt_editable()
        if record.step != "upload" or not record.file_ids:
            raise rule_error(self.env, "forbidden")
        files = [(f.name, f.mimetype, base64.b64decode(f.with_context(bin_size=False).data or b"")) for f in record.file_ids]
        try:
            data = obt_reader.read(read_key(), files, obt.reading_instructions(form()), obt.reading_schema())
            reading = obt.parse_reading(data, form())
        except obt_reader.ReadingError as error:
            record.write({"read_error": error.code})
            return self.ea_obt_page()
        except ValueError:
            record.write({"read_error": "unreadable"})
            return self.ea_obt_page()
        self._ea_obt_count_use(files)
        self._ea_obt_set_lines(record, reading["lines"], read=True)
        record.write({
            "step": "check", "source": "reader", "read_error": False, "read_at": fields.Datetime.now(),
            "read_by_id": self.env.user.id, "unit": reading["unit"], "column": reading["column"] or False,
            "year_end": reading["year_end"] or record.year_end, "signed": reading["signed"] or record.signed,
            "net_result": reading["net_result"] or 0.0, "has_net_result": reading["net_result"] is not None,
            "confirmed_at": False, "confirmed_by_id": False,
        })
        self._ea_log("obt_read", "Opening Balance Testing: %d lines read from %d file(s)" % (len(reading["lines"]), len(files)))
        return self.ea_obt_page()

    def _ea_obt_count_use(self, files):
        """This month's documents and pages, for the console (as the firm's server reports them)."""
        params = self.env["ir.config_parameter"].sudo()
        month = fields.Date.context_today(self).strftime("%Y-%m")
        try:
            usage = json.loads(params.get_param(PARAM_USAGE) or "{}")
        except ValueError:
            usage = {}
        if usage.get("month") != month:
            usage = {"month": month, "documents": 0, "pages": 0}
        pages = 0
        for _name, mimetype, data in files:
            pages += max(1, data.count(b"/Type /Page") - data.count(b"/Type /Pages")) if mimetype == "application/pdf" else 1
        usage["documents"] = int(usage.get("documents") or 0) + len(files)
        usage["pages"] = int(usage.get("pages") or 0) + pages
        params.set_param(PARAM_USAGE, json.dumps(usage, sort_keys=True))

    def ea_obt_by_hand(self):
        """The same table, typed by hand: no key, a reading problem, or the user's choice."""
        record = self._ea_obt_editable()
        if record.step != "upload":
            raise rule_error(self.env, "forbidden")
        if not record.line_ids or record.source != "hand":
            self._ea_obt_set_lines(record, {})
        record.write({"step": "check", "source": "hand", "read_error": False, "confirmed_at": False, "confirmed_by_id": False})
        self._ea_log("obt_hand", "Opening Balance Testing: figures typed by hand")
        return self.ea_obt_page()

    def ea_obt_set(self, ref, amount):
        """A figure of the check step, typed or corrected. A figure read and changed keeps who changed it."""
        record = self._ea_obt_editable()
        line = record.line_ids.filtered(lambda l: l.ref == ref)
        if record.step != "check" or not line:
            raise rule_error(self.env, "not-found")
        if amount in (None, False, ""):
            vals = {"amount": 0.0, "has_amount": False}
        else:
            try:
                value = round(float(amount), 2)
            except (TypeError, ValueError):
                raise rule_error(self.env, "invalid-field") from None
            vals = {"amount": value, "has_amount": True}
        if vals["amount"] == line.amount and vals["has_amount"] == line.has_amount:
            return self.ea_obt_page()
        before = line.amount if line.has_amount else None
        if line.has_read and (not vals["has_amount"] or abs(vals["amount"] - line.read_amount) > 0.005):
            vals.update({"corrected_by_id": self.env.user.id, "corrected_at": fields.Datetime.now()})
        else:
            vals.update({"corrected_by_id": False, "corrected_at": False})
        line.write(vals)
        if line.has_read:
            self._ea_log("obt_corrected", "Opening Balance Testing: %s corrected from %s to %s" % (
                ref, "—" if before is None else "%.2f" % before, "—" if not vals["has_amount"] else "%.2f" % vals["amount"]))
        return self.ea_obt_page()

    def ea_obt_confirm(self):
        """The figures are confirmed: they are compared with the opening balances."""
        record = self._ea_obt_editable()
        if record.step != "check":
            raise rule_error(self.env, "forbidden")
        if not record.line_ids.filtered(lambda l: l.has_amount):
            raise rule_error(self.env, "invalid-field")
        record.write({"step": "result", "confirmed_at": fields.Datetime.now(), "confirmed_by_id": self.env.user.id})
        compared = self._ea_obt_compare(record)
        if compared:
            summary = compared[1]
            self._ea_log("obt_confirmed", "Opening Balance Testing: figures confirmed, %d of %d lines agree" % (summary["agree"], summary["lines"]))
        else:
            self._ea_log("obt_confirmed", "Opening Balance Testing: figures confirmed, %d of %d lines agree" % (0, 0))
        return self.ea_obt_page()

    def ea_obt_change(self):
        """Back to the statements (Change the statements): figures and appreciations are kept."""
        record = self._ea_obt_editable()
        if record.step == "upload":
            return self.ea_obt_page()
        record.write({"step": "upload", "confirmed_at": False, "confirmed_by_id": False})
        self._ea_log("obt_reopened", "Opening Balance Testing: statements reopened")
        return self.ea_obt_page()

    def ea_obt_back_to_check(self):
        record = self._ea_obt_editable()
        if record.step != "result":
            raise rule_error(self.env, "forbidden")
        record.write({"step": "check", "confirmed_at": False, "confirmed_by_id": False})
        self._ea_log("obt_reopened", "Opening Balance Testing: statements reopened")
        return self.ea_obt_page()

    def ea_obt_appreciate(self, ref, text):
        """The appreciation of a difference: click, type, saved."""
        record = self._ea_obt_editable()
        line = record.line_ids.filtered(lambda l: l.ref == ref)
        compared = self._ea_obt_compare(record)
        if record.step != "result" or not line or not compared:
            raise rule_error(self.env, "not-found")
        differing, _open = self._ea_obt_open_differences(record, compared[0])
        if ref not in {row["ref"] for row in differing}:
            raise rule_error(self.env, "not-found")
        text = (text or "").strip()[:4000] or False
        if (line.appreciation or False) != text:
            line.write({"appreciation": text, "appreciation_by_id": self.env.user.id if text else False,
                        "appreciation_at": fields.Datetime.now() if text else False})
            self._ea_log("obt_appreciated", "Opening Balance Testing: appreciation of %s saved" % ref)
        return self.ea_obt_page()

    def ea_obt_place(self, account, ref):
        """A "p" account the rule could not place, placed by the user for this client."""
        self._ea_obt_editable()
        accounts, _version = self._ea_obt_opening()
        item = next((a for a in accounts if a["account"] == account), None)
        if not item:
            raise rule_error(self.env, "not-found")
        _found, how, refs = obt.place(account, item["opening"], form())
        if ref not in refs:
            raise rule_error(self.env, "invalid-field")
        client = self.sudo().client_id
        Placement = self.env["ea.audit.obt.placement"].sudo()
        existing = Placement.search([("client_id", "=", client.id), ("account", "=", account)])
        if existing:
            existing.write({"ref": ref})
        else:
            Placement.create({"engagement_id": self.id, "client_id": client.id, "account": account, "ref": ref})
        self._ea_log("obt_placed", "Opening Balance Testing: account %s placed on %s" % (account, ref))
        return self.ea_obt_page()

    def ea_obt_open(self, target, value=None):
        """The page's links: the accounts behind a line, the trial balance, working paper E6.5."""
        self.ensure_one()
        self._ea_require_access()
        if target == "accounts":
            compared = self._ea_obt_compare()
            if not compared:
                raise rule_error(self.env, "not-found")
            codes = [a["account"] for a in compared[2]["lines"].get(str(value or ""), {}).get("accounts", [])]
            version = self.sudo()._ea_current_tb_version()
            ids = version.line_ids.filtered(lambda l: l.account_code in codes).ids
            return {
                "type": "ir.actions.act_window", "res_model": "ea.audit.tb.line", "view_mode": "list",
                "views": [(False, "list")], "domain": [("id", "in", ids)], "target": "current",
                "name": "%s %s" % (value, self._ea_obt_label(str(value), is_french(self.env))),
                "context": {"create": False, "edit": False, "ea_engagement_id": self.id},
            }
        if target == "tb":
            return self.action_tool_tb()
        if target == "e65":
            item = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.id), ("code", "=", "E6.5")], limit=1)
            if not item:
                raise rule_error(self.env, "not-found")
            return item.with_env(self.env).action_open_paper()
        raise rule_error(self.env, "not-found")

    # ------------------------------------------------------------------ the extracts

    def _ea_obt_sheet(self, fr, only_differences):
        from ..exports import registers_workbook  # noqa: PLC0415
        record = self._ea_obt_record()
        compared = self._ea_obt_compare(record) if record and record.step == "result" else None
        if not compared:
            raise rule_error(self.env, "not-found")
        rows, _summary, _grouping = compared
        appreciation = {line.ref: line.appreciation or "" for line in record.line_ids}
        head = (["Réf", "Poste", "États financiers N-1", "Soldes d'ouverture (balance)", "Écart", "Statut", "Appréciation"]
                if fr else ["Reference", "Statement line", "Prior-year statements", "Opening balances (trial balance)", "Difference", "Status", "Appreciation"])
        out = []
        for row in rows:
            if row["empty"] or (only_differences and (row["kind"] != "line" or row["agrees"])):
                continue
            status = ("Concorde" if fr else "Agrees") if row["agrees"] else ("Écart" if fr else "Difference")
            out.append([row["ref"], self._ea_obt_label(row["ref"], fr), row["statements"], row["opening"], row["difference"],
                        status, appreciation.get(row["ref"], "") if not row["agrees"] else ""])
        title = ("Contrôle des soldes d'ouverture" if fr else "Opening Balance Testing")
        if only_differences:
            title += " — " + ("écarts à apprécier" if fr else "differences for appreciation")
        sheet = ("Écarts" if fr else "Differences") if only_differences else ("Soldes d'ouverture" if fr else "Opening balances")
        return registers_workbook([(sheet, head, out, "%s — %s" % (title, self.sudo().client_id.name or ""))])

    def _ea_export_obt(self, fr):
        return "opening-balance-testing-%s.xlsx" % self._ea_export_slug(), self._ea_obt_sheet(fr, False)

    def _ea_export_obt_differences(self, fr):
        return "opening-balance-differences-%s.xlsx" % self._ea_export_slug(), self._ea_obt_sheet(fr, True)


class PaperObt(models.Model):
    _inherit = "ea.audit.paper"

    def _ea_tool_links(self):
        """E6.5: Opening Balance Testing, with its warning while differences wait for an appreciation.
        The paper switches language on its own, so the warning goes in both."""
        links = super()._ea_tool_links()
        paper = self.sudo()
        if paper.code != "E6.5":
            return links
        engagement = paper.engagement_id
        links.append({
            "en": "Opening Balance Testing", "fr": "Contrôle des soldes d'ouverture",
            "note_en": engagement.with_context(lang="en_US")._ea_obt_warning(),
            "note_fr": engagement.with_context(lang="fr_FR")._ea_obt_warning(),
            "action": engagement.with_env(self.env).action_tool_obt(),
        })
        return links
