import hashlib
import json
import secrets
import time
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..services import heartbeat, support
from ..services.messages import _
from .i18n import t

TICKET_STATES = [("open", "Open"), ("in_progress", "In progress"), ("closed", "Closed")]
VISIT_STATES = [
    ("requested", "Asked, waiting for the firm's server"),
    ("open", "Open"),
    ("ended", "Ended"),
    ("expired", "Time is up"),
]
LIVE_VISIT = ("requested", "open")
MAX_VISIT_MINUTES = 240
DEFAULT_VISIT_MINUTES = 60


class PlatformFirmError(models.Model):
    """Technical errors a firm's server reported: codes and counts only, never a message."""

    _name = "platform.firm.error"
    _description = "Technical error of a firm"
    _order = "last_at desc, id desc"

    firm_id = fields.Many2one("platform.firm", "Firm", required=True, readonly=True, ondelete="cascade", index=True)
    module = fields.Char("Addon", readonly=True)
    model_name = fields.Char("Screen (model)", readonly=True)
    kind = fields.Char("Error type", readonly=True)
    count = fields.Integer("Count", readonly=True)
    last_at = fields.Datetime("Last seen", readonly=True, index=True)
    received_at = fields.Datetime("Reported on", readonly=True)


class PlatformTicket(models.Model):
    """A problem a firm's user reported with 'Report a problem', and the operator's reply.

    The one place on the platform that holds text a firm's user typed. The firm's form warns them not
    to write client details. Who wrote it is not sent: the reply goes back to that user by its reference.
    """

    _name = "platform.ticket"
    _description = "Reported problem"
    _inherit = ["mail.thread"]
    _order = "state_rank, received_at desc"
    _rec_name = "subject"

    firm_id = fields.Many2one("platform.firm", "Firm", required=True, readonly=True, ondelete="restrict", index=True)
    ref = fields.Char("Reference", required=True, readonly=True, index=True)
    subject = fields.Char("Subject", readonly=True)
    message = fields.Text("Message", readonly=True)
    screen = fields.Char("Screen", readonly=True)
    state = fields.Selection(TICKET_STATES, "State", default="open", required=True, tracking=True)
    state_rank = fields.Integer(compute="_compute_rank", store=True)
    reply = fields.Text("Reply to the user", tracking=True)
    received_at = fields.Datetime("Received on", readonly=True)
    replied_at = fields.Datetime("Replied on", readonly=True)
    replied_by = fields.Many2one("res.users", "Replied by", readonly=True)

    _ref_unique = models.Constraint("unique(firm_id, ref)", "A firm's ticket arrives once.")

    @api.depends("state")
    def _compute_rank(self):
        for ticket in self:
            ticket.state_rank = {"open": 0, "in_progress": 1, "closed": 2}.get(ticket.state, 3)

    def write(self, vals):
        if "reply" in vals:
            vals = {**vals, "replied_at": fields.Datetime.now(), "replied_by": self.env.user.id}
        result = super().write(vals)
        if "reply" in vals or "state" in vals:
            for ticket in self:
                self.env["platform.log"]._record(
                    _("Reported problem answered") if "reply" in vals else _("Reported problem moved on"),
                    ticket.firm_id, _("Ticket %(ref)s: %(state)s", ref=ticket.ref[:8], state=ticket.state),
                )
                ticket.firm_id._evaluate_health()
        return result

    def action_in_progress(self):
        self.write({"state": "in_progress"})
        return True

    def action_close(self):
        self.write({"state": "closed"})
        return True

    def action_reopen(self):
        self.write({"state": "open"})
        return True


class PlatformSupportVisit(models.Model):
    """A numbered, time-limited, read-only sign-in into a firm's Odoo, as its named support account.

    The platform keeps the reason and the link's fingerprint, never the link: it is shown once to the
    operator who asked. The firm's server learns the fingerprint from the signed heartbeat answer; its
    root script opens the visit; its administrator is told on screen and can end it. The record is
    never edited nor deleted once made: only its state follows what the firm's server reports, and
    the screens opened are added to it as they arrive.
    """

    _name = "platform.support.visit"
    _description = "Support visit"
    _order = "id desc"
    _rec_name = "id"

    firm_id = fields.Many2one("platform.firm", "Firm", required=True, readonly=True, ondelete="restrict", index=True)
    reason = fields.Text("Reason", required=True, readonly=True)
    minutes = fields.Integer("Length (minutes)", readonly=True)
    state = fields.Selection(VISIT_STATES, "State", readonly=True, default="requested", index=True)
    link_fingerprint = fields.Char("Link fingerprint", readonly=True, copy=False)
    requested_by = fields.Many2one("res.users", "Asked by", readonly=True)
    requested_at = fields.Datetime("Asked on", readonly=True)
    end_requested = fields.Boolean("End asked", readonly=True)
    reported_at = fields.Datetime("Last state from the firm", readonly=True)
    expected_end = fields.Datetime("Ends at the latest", compute="_compute_end")
    release = fields.Char("Release in use", readonly=True)
    trace_ids = fields.One2many("platform.support.trace", "visit_id", "Screens and records opened")

    _IMMUTABLE = frozenset({"firm_id", "reason", "minutes", "link_fingerprint", "requested_by", "requested_at"})

    def write(self, vals):
        if self._IMMUTABLE & set(vals) or not self.env.context.get("ea_visit_internal"):
            raise UserError(t(self.env, _("A support visit's record cannot be changed.")))
        return super().write(vals)

    def unlink(self):
        raise UserError(t(self.env, _("A support visit's record cannot be deleted.")))

    @api.depends("firm_id")
    def _compute_display_name(self):
        for visit in self:
            visit.display_name = t(self.env, _("Visit %(id)s", id=visit.id)) if visit.id else ""

    @api.depends("reported_at", "requested_at", "minutes", "state")
    def _compute_end(self):
        for visit in self:
            start = visit.reported_at if visit.state == "open" else visit.requested_at
            visit.expected_end = start + timedelta(minutes=visit.minutes) if start and visit.minutes else False

    def _answer(self):
        """What the heartbeat answer may say about this visit."""
        self.ensure_one()
        if self.end_requested and self.state in LIVE_VISIT:
            return {"support_visit_end": self.id}
        if self.state == "requested":
            return {"support_visit": {
                "id": self.id, "minutes": self.minutes, "token_sha256": self.link_fingerprint,
                "operator": _operator_name(self.requested_by), "reason": (self.reason or "")[:500],
            }}
        return {}

    def action_end(self):
        self.firm_id.check_access("write")
        for visit in self.sudo().filtered(lambda v: v.state in LIVE_VISIT):
            visit.with_context(ea_visit_internal=True).write({"end_requested": True})
            self.env["platform.log"]._record(_("Support visit: end asked"), visit.firm_id, _("Visit %(id)s", id=visit.id))
        return True


class PlatformSupportTrace(models.Model):
    """One screen or record a support visit opened: model, kind, ids. Never content. Append-only."""

    _name = "platform.support.trace"
    _description = "Screen opened during a support visit"
    _order = "opened_at, id"

    visit_id = fields.Many2one("platform.support.visit", "Visit", required=True, readonly=True, ondelete="restrict", index=True)
    opened_at = fields.Datetime("Opened on", readonly=True)
    model_name = fields.Char("Screen (model)", readonly=True)
    method = fields.Char("Kind", readonly=True)
    res_ids = fields.Char("Record ids", readonly=True)

    def write(self, vals):
        raise UserError(t(self.env, _("A support visit's trail cannot be changed.")))

    def unlink(self):
        raise UserError(t(self.env, _("A support visit's trail cannot be deleted.")))


def _operator_name(user):
    """The operator's name, in the shape the firm's root script accepts."""
    import re

    name = re.sub(r"[^\w .'-]", "", user.name or "") .strip()[:64]
    return name or "Operator"


class PlatformSupportVisitWizard(models.TransientModel):
    _name = "platform.support.visit.wizard"
    _description = "Start a support visit"

    firm_id = fields.Many2one("platform.firm", "Firm", required=True, readonly=True)
    reason = fields.Text("Reason", required=True, help="Goes in the platform log and is the visit's record.")
    minutes = fields.Integer("Length (minutes)", default=DEFAULT_VISIT_MINUTES, required=True)
    link = fields.Char("Sign-in link, shown once", readonly=True)
    started = fields.Boolean(readonly=True)

    def action_confirm(self):
        self.ensure_one()
        firm = self.firm_id.sudo()
        if firm.state != "active":
            raise UserError(t(self.env, _("A support visit is for a firm that is live.")))
        if not (1 <= self.minutes <= MAX_VISIT_MINUTES):
            raise UserError(t(self.env, _("A visit lasts from 1 to %(max)s minutes.", max=MAX_VISIT_MINUTES)))
        if not (self.reason or "").strip():
            raise UserError(t(self.env, _("Say why: the reason goes in the platform log.")))
        if firm.support_visit_ids.filtered(lambda v: v.state in LIVE_VISIT):
            raise UserError(t(self.env, _("A visit is already under way for this firm: end it first.")))
        token = secrets.token_urlsafe(32)
        visit = self.env["platform.support.visit"].sudo().create({
            "firm_id": firm.id, "reason": self.reason.strip()[:500], "minutes": self.minutes,
            "link_fingerprint": hashlib.sha256(token.encode("ascii")).hexdigest(),
            "requested_by": self.env.user.id, "requested_at": fields.Datetime.now(), "release": firm.addon_release,
        })
        self.env["platform.log"]._record(
            _("Support visit asked"), firm,
            _("Visit %(id)s, %(minutes)s minutes. Reason: %(reason)s", id=visit.id, minutes=self.minutes, reason=self.reason.strip()),
            user=self.env.user,
        )
        firm._evaluate_health()
        self.write({"started": True, "link": f"https://{firm.address}/ea-firm/support/{token}"})
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
            "view_mode": "form", "target": "new", "name": self.env["ir.model"]._get(self._name).name,
        }

    def action_close(self):
        """Nothing of the link outlives the screen."""
        self.write({"link": False})
        return {"type": "ir.actions.act_window_close"}


class PlatformFirmSupport(models.Model):
    _inherit = "platform.firm"

    error_ids = fields.One2many("platform.firm.error", "firm_id", "Technical errors")
    ticket_ids = fields.One2many("platform.ticket", "firm_id", "Reported problems")
    support_visit_ids = fields.One2many("platform.support.visit", "firm_id", "Support visits")
    last_support_timestamp = fields.Integer("Last support message timestamp", readonly=True, copy=False)
    errors_24h = fields.Integer("Technical errors (24 h)", compute="_compute_support_figures")
    tickets_open = fields.Integer("Open problems", compute="_compute_support_figures")
    visit_state = fields.Char("Support visit", compute="_compute_support_figures")

    @api.depends_context("lang")
    def _compute_support_figures(self):
        since = fields.Datetime.now() - timedelta(hours=24)
        labels = dict(self.env["platform.support.visit"]._fields["state"]._description_selection(self.env))
        for firm in self:
            sudo = firm.sudo()
            firm.errors_24h = sum(sudo.error_ids.filtered(lambda e: e.last_at and e.last_at >= since).mapped("count"))
            firm.tickets_open = len(sudo.ticket_ids.filtered(lambda tk: tk.state != "closed"))
            live = sudo.support_visit_ids.filtered(lambda v: v.state in LIVE_VISIT)[:1]
            firm.visit_state = labels.get(live.state) if live else False

    def _health_input(self):
        result = super()._health_input()
        if self.state == "active":
            result["errors_24h"] = self.errors_24h
            result["tickets_open"] = self.tickets_open
            result["visit_open"] = bool(self.sudo().support_visit_ids.filtered(lambda v: v.state == "open"))
        return result

    def _heartbeat_answer(self):
        answer = super()._heartbeat_answer()
        if self.state == "active":
            visit = self.sudo().support_visit_ids.filtered(lambda v: v.state in LIVE_VISIT)[:1]
            if visit:
                answer.update(visit._answer())
        return answer

    def _apply_figures(self, figures, timestamp):
        firm = self.sudo()
        now = fields.Datetime.now()
        rows = [{
            "firm_id": firm.id, "module": item["module"], "model_name": item["model"], "kind": item["kind"],
            "count": item["count"], "last_at": heartbeat.parse_instant(item["last_at"]), "received_at": now,
        } for item in figures.get("errors") or ()]
        if rows:
            self.env["platform.firm.error"].sudo().create(rows)
        reported = figures.get("support_visit")
        if reported:
            visit = firm.support_visit_ids.filtered(lambda v: v.id == reported["id"])
            if visit and visit.state != reported["state"]:
                visit.with_context(ea_visit_internal=True).write({"state": reported["state"], "reported_at": now})
                self.env["platform.log"]._record(_("Support visit: the firm's server says %(state)s", state=reported["state"]), firm, _("Visit %(id)s", id=visit.id))
        return super()._apply_figures(figures, timestamp)

    def _simulate_heartbeat(self, release=None, **changes):
        """A simulated firm opens an asked visit at once, and ends it when asked."""
        firm = self.sudo()
        if firm.is_simulation and "support_visit" not in changes:
            visit = firm.support_visit_ids.filtered(lambda v: v.state in LIVE_VISIT)[:1]
            if visit:
                changes["support_visit"] = {"id": visit.id, "state": "ended" if visit.end_requested else "open"}
        return super()._simulate_heartbeat(release=release, **changes)

    # ------------------------------------------------------------------ the support channel

    @api.model
    def _receive_support(self, prefix, headers, body):
        """A signed message from a firm's 'Report a problem'. Returns (answer, signature)."""
        firms = self.sudo().with_context(active_test=False)
        found = {}

        def find_firm(slug):
            firm = firms.search([("slug", "=", slug), ("state", "in", ("active", "suspended", "offboarding"))], limit=1)
            if not firm:
                return None
            self.env.cr.execute("SELECT id FROM platform_firm WHERE id = %s FOR UPDATE", [firm.id])
            found["firm"] = firm
            return firm.heartbeat_token, firm.last_support_timestamp

        slug, timestamp = heartbeat.accept_kind(prefix, headers, body, find_firm, int(time.time()), support.MAX_BODY_BYTES)
        firm = found["firm"]
        firm.write({"last_support_timestamp": timestamp})
        if prefix == support.PREFIX_TICKET:
            data = support.parse_ticket(body)
            tickets = self.env["platform.ticket"].sudo()
            if not tickets.search_count([("firm_id", "=", firm.id), ("ref", "=", data["ref"])]):
                ticket = tickets.create({
                    "firm_id": firm.id, "ref": data["ref"], "subject": data["subject"].strip(),
                    "message": data["message"], "screen": data["screen"] or False, "received_at": fields.Datetime.now(),
                })
                self.env["platform.log"]._record(_("Problem reported"), firm, _("Ticket %(ref)s", ref=ticket.ref[:8]))
                firm._evaluate_health()
            answer = {"ok": True}
        elif prefix == support.PREFIX_TRACE:
            data = support.parse_trace(body)
            visit = firm.support_visit_ids.filtered(lambda v: v.id == data["visit"])
            if not visit:
                raise heartbeat.HeartbeatRejected("unknown_visit")
            self.env["platform.support.trace"].sudo().create([{
                "visit_id": visit.id, "opened_at": heartbeat.parse_instant(entry["at"]), "model_name": entry["model"],
                "method": entry["method"], "res_ids": ",".join(str(i) for i in entry["ids"]),
            } for entry in data["entries"]])
            if data["release"] and not visit.release:
                visit.with_context(ea_visit_internal=True).write({"release": data["release"]})
            answer = {"ok": True}
        else:
            refs = support.parse_sync(body)
            tickets = self.env["platform.ticket"].sudo().search([("firm_id", "=", firm.id), ("ref", "in", refs)])
            answer = {"tickets": [{"ref": tk.ref, "state": tk.state, "reply": tk.reply or ""} for tk in tickets]}
        raw = json.dumps(answer, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return raw, heartbeat.sign_kind(prefix + b"-response", firm.heartbeat_token, slug, timestamp, raw)

    def action_support_visit(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": "platform.support.visit.wizard", "view_mode": "form",
            "target": "new", "context": {"default_firm_id": self.id},
            "name": self.env["ir.model"]._get("platform.support.visit.wizard").name,
        }

    def action_end_support_visit(self):
        self.ensure_one()
        self.check_access("write")
        self.sudo().support_visit_ids.filtered(lambda v: v.state in LIVE_VISIT).action_end()
        return True
