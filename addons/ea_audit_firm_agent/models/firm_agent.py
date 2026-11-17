import json
import logging
import os
import tempfile
import time

import requests

from odoo import api, models

from ..services import collect, errors, signing

_logger = logging.getLogger(__name__)

# Written by deploy/firm/install-firm-server.sh. The agent does nothing while they are absent,
# which is the case on staging and in any database not built by that script.
TOKEN_FILE = "/etc/auditisa-firm/secrets/heartbeat.token"
STATUS_DIR = "/var/lib/auditisa-firm/status"
SPOOL_FILE = "/var/lib/auditisa-firm/spool/desired.json"
# The console's email request has a file of its own: it holds a password, and root's firm-mail-server
# erases it as it reads it. desired.json, read every five minutes, never holds it.
MAIL_SPOOL_FILE = "/var/lib/auditisa-firm/spool/mail.json"
TIMEOUT_SECONDS = 20

PARAM_URL = "ea_firm_agent.heartbeat_url"
PARAM_SLUG = "ea_firm_agent.slug"
PARAM_MAIL_TESTED = "ea_firm_agent.mail_tested"
# Where replies to this firm's emails go, when the console's platform address sends for it.
PARAM_MAIL_REPLY_TO = "ea_firm_agent.mail_reply_to"
# The console's last "Add / Replace the firm administrator" request: its reference and result, kept so that
# each request is acted on once; and the one-time invitation link, kept only until a heartbeat delivers it.
PARAM_ADMIN_REF = "ea_firm_agent.admin_request_ref"
PARAM_ADMIN_RESULT = "ea_firm_agent.admin_request_result"
PARAM_ADMIN_LINK = "ea_firm_agent.admin_request_link"


class EaFirmAgent(models.AbstractModel):
    _name = "ea.firm.agent"
    _description = "Heartbeat of this firm's server"

    @api.model
    def _read_token(self):
        try:
            with open(TOKEN_FILE, encoding="ascii") as handle:
                return handle.read().strip()
        except (OSError, UnicodeDecodeError):
            return ""

    @api.model
    def _count_users(self):
        return self.env["res.users"].sudo().with_context(active_test=True).search_count([("share", "=", False)])

    @api.model
    def _count_engagements(self):
        """A count, nothing else: no field of an engagement ever leaves this method."""
        if "ea.audit.engagement" not in self.env:
            return 0
        model = self.env["ea.audit.engagement"].sudo()
        domain = [("phase", "!=", "archived")] if "phase" in model._fields else []
        return model.search_count(domain)

    @api.model
    def _error_figures(self):
        """Codes and counts since the last delivered heartbeat. See services/errors.py."""
        lines, sending = self.env["ea.firm.error.capture"]._take()
        self.env.context.get("ea_error_files", []).append(sending)
        return [
            {**{key: item[key] for key in ("module", "model", "kind", "count")},
             "last_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(item["last"]))}
            for item in errors.aggregate(lines)
        ]

    @api.model
    def _build_figures(self):
        get_param = self.env["ir.config_parameter"].sudo().get_param
        return collect.build_figures(
            collect.read_status(STATUS_DIR),
            collect.memory_figures(),
            collect.disk_figures(),
            self._count_users(),
            self._count_engagements(),
            get_param(PARAM_MAIL_TESTED) == "1",
            self.env["ea.addon.switch"]._codes_on(),
            self._error_figures(),
            self.env["ea.firm.support.visit"]._current_figure(),
            self._admin_answer(),
        )

    @api.model
    def _admin_answer(self):
        get_param = self.env["ir.config_parameter"].sudo().get_param
        ref = get_param(PARAM_ADMIN_REF)
        if not ref:
            return None
        return {"ref": ref, "result": get_param(PARAM_ADMIN_RESULT), "link": get_param(PARAM_ADMIN_LINK)}

    @api.model
    def _apply_admin_request(self, request):
        """The console's "Add / Replace the firm administrator", once per reference. The console sends it
        at each answer until this server reports, so a repeat is expected and changes nothing.

        The work is ea_audit_timesheet's (the firm administrator's screens): this addon does not depend
        on it, so a server without it answers "unavailable". Only the error's class is logged."""
        params = self.env["ir.config_parameter"].sudo()
        if params.get_param(PARAM_ADMIN_REF) == request["ref"]:
            return
        link = None
        if "ea.audit.firm.admin" not in self.env:
            result = "unavailable"
        else:
            try:
                with self.env.cr.savepoint():
                    result, link = self.env["ea.audit.firm.admin"].sudo()._ea_fa_from_platform(
                        request["action"], request["name"], request["email"],
                    )
            except Exception as error:  # noqa: BLE001  the heartbeat must carry on, and report it
                _logger.warning("Firm administrator request not applied: %s", type(error).__name__)
                result, link = "failed", None
        params.set_param(PARAM_ADMIN_REF, request["ref"])
        params.set_param(PARAM_ADMIN_RESULT, result)
        params.set_param(PARAM_ADMIN_LINK, link or False)

    @api.model
    def _cron_send_heartbeat(self):
        self.env["ir.mail_server"]._ea_keep_reset_closed()
        get_param = self.env["ir.config_parameter"].sudo().get_param
        url, slug, token = get_param(PARAM_URL), get_param(PARAM_SLUG), self._read_token()
        if not (url and slug and token):
            return False
        if not url.startswith("https://"):
            _logger.warning("Heartbeat refused: the address is not https")
            return False
        files = []
        figures = self.with_context(ea_error_files=files)._build_figures()
        if "release" not in figures:
            _logger.warning("Heartbeat not sent: this server does not know its release yet")
            return False
        sent = self._post(url, slug, token, figures)
        if sent:
            for path in files:
                self.env["ea.firm.error.capture"]._delivered(path)
            # The console has the link: it is erased here, unless a newer request has made another one.
            params = self.env["ir.config_parameter"].sudo()
            if "admin_request_link" in figures and params.get_param(PARAM_ADMIN_REF) == figures["admin_request_ref"]:
                params.set_param(PARAM_ADMIN_LINK, False)
        return sent

    @api.model
    def _post(self, url, slug, token, figures):
        body = signing.encode(figures)
        timestamp = int(time.time())
        headers = {
            "Content-Type": "application/json",
            signing.HEADER_FIRM: slug,
            signing.HEADER_TIMESTAMP: str(timestamp),
            signing.HEADER_SIGNATURE: signing.sign(token, slug, timestamp, body),
        }
        try:
            response = requests.post(url, data=body, headers=headers, timeout=TIMEOUT_SECONDS, allow_redirects=False)
        except requests.RequestException as error:
            _logger.warning("Heartbeat not delivered: %s", type(error).__name__)
            return False
        if response.status_code != 200:
            _logger.warning("Heartbeat refused by the control plane: HTTP %s", response.status_code)
            return False
        # An answer that is not signed by the control plane is ignored, whatever it asks for.
        signature = response.headers.get(signing.HEADER_RESPONSE_SIGNATURE)
        if not signing.response_is_authentic(token, slug, timestamp, response.content, signature):
            _logger.warning("Heartbeat answer ignored: bad signature")
            return False
        desired = collect.parse_desired(response.content)
        if desired is not None:
            self._apply_reply_to(desired.pop("mail_reply_to", None))
            admin = desired.pop("admin_request", None)
            if admin is not None:
                self._apply_admin_request(admin)
            self._write_spool(desired)
        return True

    @api.model
    def _apply_reply_to(self, reply_to):
        """None: the console said nothing (an older console). "": no reply address. Checked by collect.py."""
        if reply_to is None:
            return
        params = self.env["ir.config_parameter"].sudo()
        if (params.get_param(PARAM_MAIL_REPLY_TO) or "") != reply_to:
            params.set_param(PARAM_MAIL_REPLY_TO, reply_to or False)

    @api.model
    def _write_spool(self, desired):
        """Handed to root's firm-apply-desired.sh, which validates it again and acts on it."""
        mail = desired.pop("mail_request", None)
        if mail is not None:
            self._write_file(MAIL_SPOOL_FILE, ".mail-", mail, ensure_ascii=False)
        self._write_file(SPOOL_FILE, ".desired-", desired)

    @api.model
    def _write_file(self, target, prefix, data, ensure_ascii=True):
        """One step, readable by this user only (mkstemp makes it 600). Only the error's class is logged."""
        folder = os.path.dirname(target)
        path = None
        try:
            handle, path = tempfile.mkstemp(dir=folder, prefix=prefix)
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                json.dump(data, out, sort_keys=True, ensure_ascii=ensure_ascii)
            os.replace(path, target)
        except OSError as error:
            _logger.warning("Could not hand over the control plane's answer: %s", type(error).__name__)
            if path and os.path.exists(path):
                os.unlink(path)
