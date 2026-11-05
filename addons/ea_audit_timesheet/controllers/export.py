from odoo import fields, http
from odoo.http import content_disposition, request

from ..services.workbook import report_workbook


class TimesheetExport(http.Controller):
    @http.route("/ea_audit_timesheet/export", type="http", auth="user", methods=["GET"], readonly=True)
    def export(self, date_from, date_to, **_kwargs):
        """The search runs under the caller: the line rules decide what is in the file."""
        first = fields.Date.to_date(date_from)
        last = fields.Date.to_date(date_to)
        sheets = request.env["ea.audit.timesheet.sheet"]._ea_ts_export(first, last)
        name = "heures_%s_%s.xlsx" % (first.strftime("%d-%m-%Y"), last.strftime("%d-%m-%Y"))
        return request.make_response(
            report_workbook(sheets),
            headers=[
                ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                ("Content-Disposition", content_disposition(name)),
            ],
        )
