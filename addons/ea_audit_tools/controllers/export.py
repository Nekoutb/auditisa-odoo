from urllib.parse import quote

from odoo import http
from odoo.http import request

from odoo.addons.ea_audit_core.services.errors import AuditRuleError

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ToolExports(http.Controller):
    @http.route("/ea_audit_tools/export/<string:kind>/<int:engagement_id>", type="http", auth="user", methods=["GET"])
    def export(self, kind, engagement_id):
        """A refusal is reported as itself, not collapsed to 401 or 500 as the platform's routes do."""
        engagement = request.env["ea.audit.engagement"].browse(engagement_id)
        try:
            filename, content = engagement.ea_export_xlsx(kind)
        except AuditRuleError as error:
            return request.make_json_response({"error": error.code, "message": str(error)}, status=403)
        return request.make_response(content, headers=[
            ("Content-Type", XLSX),
            ("Content-Disposition", "attachment; filename*=UTF-8''%s" % quote(filename)),
        ])
