"""Each client firm's document-reading key, set from the console (owner's ruling of 2026-11-20).

Opening Balance Testing reads the prior-year financial statements a user uploads; the firm's server needs
the firm's own key for that. The platform owner pastes it on the firm's page ("Document reading"); it goes
the way "Email for this firm" sends a password: encrypted in a file outside the database
(services/mail_handoff.py, reading-<slug>) until the firm's next heartbeat answer takes it, once, and is
erased then. The firm's server keeps it in a file of its own, tests it, and answers with a reference and
one word; it also reports this month's use.

What the console keeps: who asked, when, the key's last four characters, the answer and the use. Never the key.
"""

import re
import secrets
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..services import mail_handoff
from ..services.heartbeat import DOC_READING_RESULTS
from ..services.messages import _
from .i18n import t

HANDOFF_HOURS = 6
#: A key as the reading service issues them: letters, figures, dashes and underscores, no space.
_KEY = re.compile(r"^[A-Za-z0-9_-]{20,300}$")

DOC_READING_STATES = [
    ("none", "Not set"),
    ("waiting", "Waiting for the firm's server"),
    ("on", "Works"),
    ("refused", "Key refused by the reading service"),
    ("unreachable", "The firm's server could not reach the reading service"),
    ("removed", "Removed"),
    ("unavailable", "The firm's server cannot read documents yet (its next update brings it)"),
    ("failed", "Failed on the firm's server"),
    ("expired", "Not collected in time: send it again"),
    ("no_answer", "Collected, no answer yet"),
]


class PlatformFirm(models.Model):
    _inherit = "platform.firm"

    docr_state = fields.Selection(DOC_READING_STATES, "Document reading", default="none", required=True, readonly=True, copy=False)
    docr_action = fields.Selection(
        [("set", "Key sent"), ("test", "Test asked"), ("remove", "Removal asked")], "Last request", readonly=True, copy=False,
    )
    docr_ref = fields.Char("Request reference", readonly=True, copy=False)
    docr_last4 = fields.Char(
        "Key ending", readonly=True, copy=False, help="The last four characters of the key sent: the console never keeps the key.",
    )
    docr_at = fields.Datetime("Asked on", readonly=True, copy=False)
    docr_by = fields.Many2one("res.users", "Asked by", readonly=True, copy=False)
    docr_delivered_at = fields.Datetime("Collected by the firm's server on", readonly=True, copy=False)
    docr_answered_at = fields.Datetime("Answer received on", readonly=True, copy=False)
    docr_month = fields.Char("Month", readonly=True, copy=False)
    docr_documents = fields.Integer("Documents read this month", readonly=True, copy=False)
    docr_pages = fields.Integer("Pages read this month", readonly=True, copy=False)

    # ------------------------------------------------------------------ the owner's requests

    def _docr_check_live(self):
        if self.state != "active":
            raise UserError(t(self.env, _("The document-reading key goes only to a live firm.")))

    def _docr_ask(self, action, last4=None, user=None):
        self.ensure_one()
        values = {
            "docr_state": "waiting", "docr_action": action, "docr_ref": secrets.token_hex(8),
            "docr_at": fields.Datetime.now(), "docr_by": (user or self.env.user).id,
            "docr_delivered_at": False, "docr_answered_at": False,
        }
        if last4 is not None:
            values["docr_last4"] = last4
        self.sudo().write(values)

    def _docr_send_key(self, key, user=None):
        """Checks the key, keeps it out of the database until the firm's server collects it, logs who asked."""
        self.ensure_one()
        firm = self.sudo()
        firm._docr_check_live()
        key = (key or "").strip()
        if not _KEY.match(key):
            raise UserError(t(self.env, _("This does not look like a key: paste the whole key, without spaces.")))
        firm._docr_ask("set", key[-4:], user=user)
        firm._mail_seal(mail_handoff.reading_name(firm.slug), {"ref": firm.docr_ref, "key": key})
        self.env["platform.log"]._record(
            _("Document reading key sent to the firm's server"), firm, "…" + key[-4:], user=user or self.env.user,
        )

    def _docr_test(self, user=None):
        self.ensure_one()
        firm = self.sudo()
        firm._docr_check_live()
        if not firm.docr_last4 or firm.docr_state == "removed":
            raise UserError(t(self.env, _("No key has been sent to this firm yet.")))
        mail_handoff.discard(self._mail_folder(), mail_handoff.reading_name(firm.slug))
        firm._docr_ask("test", user=user)
        self.env["platform.log"]._record(_("Document reading: test asked"), firm, user=user or self.env.user)

    def _docr_remove(self, user=None):
        self.ensure_one()
        firm = self.sudo()
        firm._docr_check_live()
        mail_handoff.discard(self._mail_folder(), mail_handoff.reading_name(firm.slug))
        firm._docr_ask("remove", user=user)
        self.env["platform.log"]._record(_("Document reading: removal asked"), firm, user=user or self.env.user)

    def action_docr_test(self):
        self.ensure_one()
        self._docr_test(self.env.user)
        self._docr_simulate_answer()
        return True

    def action_docr_remove(self):
        self.ensure_one()
        self._docr_remove(self.env.user)
        self._docr_simulate_answer()
        return True

    def _docr_simulate_answer(self):
        """A simulation firm answers at once: one heartbeat collects the request, the next reports."""
        firm = self.sudo()
        if firm.is_simulation and firm.state == "active" and firm.docr_state == "waiting":
            firm._simulate_heartbeat()
            firm._simulate_heartbeat()

    # ------------------------------------------------------------------ heartbeat

    def _heartbeat_answer(self):
        """Adds the document-reading request, once, to a live firm's answer. A key is taken from its file."""
        answer = super()._heartbeat_answer()
        firm = self.sudo()
        if firm.state == "active" and firm.docr_state == "waiting" and not firm.docr_delivered_at:
            request = firm._docr_take_request()
            if request:
                answer["doc_reading_request"] = request
                firm.write({"docr_delivered_at": fields.Datetime.now()})
        return answer

    def _docr_take_request(self):
        self.ensure_one()
        if self.docr_action in ("test", "remove"):
            return {"ref": self.docr_ref, "action": self.docr_action}
        data = self._mail_unseal(mail_handoff.take(self._mail_folder(), mail_handoff.reading_name(self.slug)))
        if not data or set(data) != {"ref", "key"} or data["ref"] != self.docr_ref:
            self._docr_close("expired")
            return None
        return {"ref": data["ref"], "action": "set", "key": data["key"]}

    def _apply_figures(self, figures, timestamp):
        result = super()._apply_figures(figures, timestamp)
        firm = self.sudo()
        usage = {}
        if figures.get("doc_reading_month"):
            usage = {"docr_month": figures["doc_reading_month"],
                     "docr_documents": figures.get("doc_reading_documents") or 0,
                     "docr_pages": figures.get("doc_reading_pages") or 0}
        if usage:
            firm.write(usage)
        ref, word = figures.get("doc_reading_ref"), figures.get("doc_reading_result")
        if ref and word in DOC_READING_RESULTS and ref == firm.docr_ref and firm.docr_state == "waiting":
            if figures.get("doc_reading_last4") and word == "on":
                firm.write({"docr_last4": figures["doc_reading_last4"]})
            firm._docr_close(word)
        return result

    def _docr_close(self, state):
        self.ensure_one()
        self.sudo().write({"docr_state": state, "docr_answered_at": fields.Datetime.now()})
        label = dict(DOC_READING_STATES)[state]
        self.env["platform.log"]._record(_("Document reading: the firm's server answered"), self, label)

    def _simulate_heartbeat(self, release=None, **changes):
        """A simulation firm obeys: a key it collected works, a test works, a removal removes."""
        self.ensure_one()
        firm = self.sudo()
        if firm.is_simulation and firm.docr_ref and firm.docr_state == "waiting" and firm.docr_delivered_at:
            changes.setdefault("doc_reading_ref", firm.docr_ref)
            changes.setdefault("doc_reading_result", "removed" if firm.docr_action == "remove" else "on")
        return super()._simulate_heartbeat(release=release, **changes)

    # ------------------------------------------------------------------ clean-up

    @api.model
    def _cron_watch(self):
        result = super()._cron_watch()
        self._docr_expire()
        return result

    @api.model
    def _docr_expire(self):
        """Nothing waits for ever: a request not collected, or not answered, is closed and its file erased."""
        limit = fields.Datetime.now() - timedelta(hours=HANDOFF_HOURS)
        folder = self._mail_folder()
        for firm in self.sudo().search([("docr_state", "=", "waiting"), ("docr_at", "<", limit)]):
            mail_handoff.discard(folder, mail_handoff.reading_name(firm.slug))
            firm._docr_close("no_answer" if firm.docr_delivered_at else "expired")
        mail_handoff.sweep(folder, HANDOFF_HOURS * 3600, prefix="reading-")

    def _drop_console_key(self):
        """A destroyed firm's waiting key goes with its maintenance key."""
        for firm in self.sudo():
            mail_handoff.discard(self._mail_folder(), mail_handoff.reading_name(firm.slug))
        return super()._drop_console_key()
