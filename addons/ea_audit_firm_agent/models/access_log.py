import logging
import re

from odoo import api, fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)

LOG_FILE = "/var/log/auditisa-firm/break-glass.log"
PARAM_OFFSET = "ea_firm_agent.access_log_offset"

# Written by /etc/ssh/sshrc (deploy/firm/firm-sshrc): instant, event, account, source.
LINE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})Z ([a-z-]{1,32}) ([A-Za-z0-9_.-]{1,64}) ([0-9a-fA-F:.]{0,64})$")


class EaFirmAccessLog(models.Model):
    """What the firm can see of the operator's logins to its server. Read-only on this side."""

    _name = "ea.firm.access.log"
    _description = "Operator access to this server"
    _order = "logged_at desc, id desc"

    logged_at = fields.Datetime("Date", readonly=True, required=True)
    event = fields.Char("Event", readonly=True, required=True)
    account = fields.Char("Account", readonly=True)
    source = fields.Char("Source address", readonly=True)

    def write(self, vals):
        raise AccessError(self.env._("The access log cannot be changed."))

    def unlink(self):
        raise AccessError(self.env._("The access log cannot be deleted."))

    @api.model
    def _cron_import(self):
        """Adds the lines the file gained since the last run. Malformed lines are skipped."""
        params = self.env["ir.config_parameter"].sudo()
        try:
            offset = int(params.get_param(PARAM_OFFSET) or 0)
        except ValueError:
            offset = 0
        try:
            with open(LOG_FILE, "rb") as handle:
                handle.seek(0, 2)
                size = handle.tell()
                if size < offset:
                    _logger.warning("The access log shrank: it is read again from the start")
                    offset = 0
                handle.seek(offset)
                data = handle.read()
        except OSError:
            return 0
        complete = data[:data.rfind(b"\n") + 1]
        rows = []
        for line in complete.decode("utf-8", "replace").splitlines():
            match = LINE.match(line)
            if match:
                rows.append({
                    "logged_at": f"{match[1]} {match[2]}",
                    "event": match[3],
                    "account": match[4],
                    "source": match[5],
                })
        if rows:
            self.sudo().create(rows)
        params.set_param(PARAM_OFFSET, str(offset + len(complete)))
        return len(rows)
