from odoo import fields, models

from ..services.texts import CAPACITY_SELECTION, STAGE_SELECTION


class LegalWizard(models.TransientModel):
    """One form for the small dialogues of the legal page. The rules are the engagement's."""

    _name = "ea.audit.legal.wizard"
    _description = "OHADA legal register dialogue"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True, ondelete="cascade")
    mode = fields.Selection([
        ("dates", "Meeting dates"),
        ("convention", "Regulated agreement"),
        ("alerte_start", "Start the alert procedure"),
        ("alerte_advance", "Next stage of the alert procedure"),
        ("alerte_resume", "Resume the alert procedure"),
        ("fait", "Disclosure of criminal facts"),
        ("irregularities", "Report of irregularities"),
        ("titres", "Securities attestation"),
        ("capital", "Share capital"),
        ("joint", "Joint auditor file"),
    ], required=True)
    agm_date = fields.Date(string="General meeting")
    board_date = fields.Date(string="Board meeting closing the accounts")
    parties = fields.Char()
    interested = fields.Char(string="Interested person")
    capacity = fields.Selection(CAPACITY_SELECTION)
    nature = fields.Char()
    terms = fields.Text()
    amounts_period = fields.Float(string="Amounts of the period (FCFA)", digits=(18, 0))
    continuing = fields.Boolean()
    board_auth_ref = fields.Char(string="Prior authorisation")
    notified_at = fields.Date(string="Notified on")
    note = fields.Text(string="Observations")
    event_date = fields.Date(string="Date of the event")
    to_stage = fields.Selection(STAGE_SELECTION, string="Next stage")
    satisfactory = fields.Boolean(string="Satisfactory reply: the procedure stops, resumable for six months")
    target = fields.Selection([("ag", "General meeting"), ("board", "Board")], string="Addressed to")
    inspection_date = fields.Date(string="Date of inspection")
    securities_count = fields.Integer(string="Securities shown")
    held_by_intermediary = fields.Boolean(string="Held in accounts by an authorised intermediary")
    intermediary_name = fields.Char(string="Intermediary")
    share_capital = fields.Float(digits=(18, 0))
    joint_key = fields.Selection(
        [("worksplit", "Work split"), ("crossreview", "Cross-review"), ("disagreement", "Disagreement")], string="Section",
    )
    confirmed = fields.Boolean(string="Confirmed with the joint auditor")

    def action_confirm(self):
        self.ensure_one()
        engagement, mode = self.engagement_id, self.mode
        if mode == "dates":
            engagement.set_legal_dates(agm_date=self.agm_date, board_date=self.board_date, clear_board=not self.board_date)
        elif mode == "convention":
            engagement.add_convention(
                self.parties, self.interested, self.capacity, self.nature, terms=self.terms, amounts_period=self.amounts_period,
                continuing=self.continuing, board_auth_ref=self.board_auth_ref, notified_at=self.notified_at,
            )
        elif mode == "alerte_start":
            engagement.start_alerte(self.note, self.event_date and self.event_date.isoformat())
        elif mode == "alerte_advance":
            engagement.advance_alerte(self.to_stage, self.note, self.satisfactory, self.event_date and self.event_date.isoformat())
        elif mode == "alerte_resume":
            engagement.resume_alerte(self.note)
        elif mode == "fait":
            return engagement.reveal_fait(self.note).action_download()
        elif mode == "irregularities":
            return engagement.generate_irregularities_letter(self.target, self.note).action_download()
        elif mode == "titres":
            return engagement.generate_titres_attestation(
                self.inspection_date, self.securities_count, self.held_by_intermediary, self.intermediary_name,
            ).action_download()
        elif mode == "capital":
            engagement.set_share_capital(self.share_capital)
        else:
            engagement.record_joint_auditor(self.joint_key, self.note, self.confirmed)
        return {"type": "ir.actions.act_window_close"}
