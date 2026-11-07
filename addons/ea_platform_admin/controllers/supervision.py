import io
import re

import xlsxwriter

from odoo import fields, http
from odoo.exceptions import AccessError
from odoo.http import request

from ..models.i18n import t
from ..services.messages import _

_IDS = re.compile(r"^\d+(,\d+)*$")

# Field by field: no token, no note, no contact, nothing a firm typed. See SECURITY-MODEL.md.
COLUMNS = (
    ("name", _("Firm")),
    ("state", _("State")),
    ("health_color", _("Health")),
    ("health_summary", _("Main reason")),
    ("platform_host", _("Platform address")),
    ("custom_domain", _("The firm's own domain")),
    ("provider_label", _("Provider")),
    ("server_id", _("Server id")),
    ("server_ip", _("IP address")),
    ("region", _("Region")),
    ("size", _("Size")),
    ("ssh_key_id", _("SSH key at the provider")),
    ("ssh_key_fingerprint", _("SSH key fingerprint")),
    ("firewall_id", _("Firewall at the provider")),
    ("storage_id", _("Backup storage")),
    ("addon_release", _("Installed release")),
    ("addons_asked_summary", _("Add-ons asked")),
    ("addons_on_summary", _("Add-ons on")),
    ("addons_differ_count", _("Add-ons not as asked")),
    ("last_heartbeat_at", _("Last heartbeat")),
    ("backup_state", _("Backup")),
    ("last_backup_at", _("Last backup")),
    ("restore_state", _("Restore test")),
    ("last_restore_test_at", _("Last restore test")),
    ("cert_expires_on", _("Certificate expiry")),
    ("is_simulation", _("Simulation")),
)


class SupervisionController(http.Controller):
    @http.route("/platform/supervision/export", type="http", auth="user", methods=["GET"], sitemap=False)
    def export(self, ids="", **_kwargs):
        env = request.env
        if not env.user.has_group("ea_platform_admin.group_platform_viewer"):
            raise AccessError(t(env, _("Only platform users export this list.")))
        if ids and not _IDS.match(ids):
            return request.not_found()
        firms = env["platform.firm"].browse([int(value) for value in ids.split(",")] if ids else []).exists()
        firms.check_access("read")
        content = build_workbook(env, firms)
        env["platform.log"]._record(_("Supervision list exported"), None, _("%(count)s firms", count=len(firms)))
        stamp = fields.Datetime.now().strftime("%Y%m%d-%H%M")
        return request.make_response(content, headers=[
            ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("Content-Disposition", f'attachment; filename="auditisa-supervision-{stamp}.xlsx"'),
            ("Cache-Control", "no-store"),
        ])


def _cell(firm, name):
    field = firm._fields[name]
    value = firm[name]
    if field.type == "selection":
        return dict(field._description_selection(firm.env)).get(value, "") if value else ""
    if field.type == "boolean":
        return t(firm.env, _("Yes") if value else _("No"))
    if field.type in ("datetime", "date"):
        return str(value) if value else ""
    return value if value not in (False, None) else ""


def build_workbook(env, firms):
    buffer = io.BytesIO()
    workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})
    sheet = workbook.add_worksheet(t(env, _("Supervision"))[:31])
    head = workbook.add_format({"bold": True, "font_color": "#ffffff", "bg_color": "#0f6e56", "border": 1})
    for column, (_name, title) in enumerate(COLUMNS):
        text = t(env, title)
        sheet.write(0, column, text, head)
        sheet.set_column(column, column, max(14, len(text) + 2))
    for row, firm in enumerate(firms, 1):
        for column, (name, _title) in enumerate(COLUMNS):
            sheet.write(row, column, _cell(firm, name))
    sheet.freeze_panes(1, 1)
    sheet.autofilter(0, 0, max(1, len(firms)), len(COLUMNS) - 1)
    workbook.close()
    return buffer.getvalue()
