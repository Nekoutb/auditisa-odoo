from werkzeug.wsgi import wrap_file

from odoo import http
from odoo.http import request


class AuditExport(http.Controller):
    @http.route("/ea_audit/engagement/<int:engagement_id>/export", type="http", auth="user", readonly=False)
    def export_bundle(self, engagement_id, **_kw):
        """The complete audit file. The refusals are the model: team only, whatever the firm role."""
        engagement = request.env["ea.audit.engagement"].browse(engagement_id)
        filename, handle = engagement.export_engagement_bundle()
        headers = [
            ("Content-Type", "application/zip"),
            ("Content-Disposition", http.content_disposition(filename)),
        ]
        return request.make_response(wrap_file(request.httprequest.environ, handle), headers=headers)
