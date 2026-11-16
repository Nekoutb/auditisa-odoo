"""Procedure design (owner's mock-ups of 2026-11-16): the tests of controls planned from the SCOTs,
and the tests of details per significant account, from the library of mandatory (MSP) and
alternative (ASP) substantive procedures.

The library replaces the former PSP catalog for every new design. What an engagement already
chose from that catalog (ea.audit.dsp.choice, ea.audit.dsp.osp) stays as it was, read only here.

Data model, for the execution pages
-----------------------------------
``ea.audit.procedure.library``: one row per library procedure, loaded from
data/procedure_library.json at install and update (no engagement, never edited on screen).

``ea.audit.designed.procedure``: one row per engagement x account (index_code) x procedure
(library code, or X1, X2... for a procedure written by the team). ``selected`` says whether it is in
the design; ``assertions`` holds the account's relevant assertions it answers; ``state`` goes
draft -> started (a sample drawn, or the execution page opened it) -> done (concluded). A started
procedure can no longer leave the design. Samples point back at it through
ea.audit.automation.run.designed_procedure_id; ``step_id`` is the E4 program step generated from it.
The conclusion fields (``conclusion``, ``conclusion_note``, ``done_by_id``, ``done_at``) are for
the execution page to fill.
"""
import json
import os

from odoo import api, fields, models

from ..rules import rule_error
from ..services.assertions import ASSERTIONS
from ..services.cra_model import CR_DEFICIENT_BASIS
from ..services.design_procedures_model import OSP_MAX, OSP_TEXT_MAX
from ..services.lead_classes import INDEX_SECTION, LEAD_INDEX_BY_CODE, lead_index_label
from ..services.procedure_design import covered, dataset_kind, design_state, is_locked, sample_mode, suggest
from .tool_record import grouped, is_french

LIBRARY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "procedure_library.json")
KIND_SELECTION = [("MSP", "MSP"), ("ASP", "ASP"), ("custom", "Own procedure")]
STATE_SELECTION = [("draft", "Not started"), ("started", "In progress"), ("done", "Done")]
REASON_SELECTION = [
    ("mandatory", "Mandatory"), ("suggested", "Suggested by the combined risk"), ("control", "Suggested: control not effective"),
    ("condition", "Condition met"), ("choice", "Your choice"),
]
CONCLUSION_SELECTION = [("satisfactory", "No exception"), ("exceptions", "Exceptions found")]
AUTOMATABLE_SELECTION = [
    ("reconciliation", "Reconciliation"), ("cutoff_selection", "Cut-off selection"), ("sample_selection", "Sample selection"),
    ("confirmation", "Confirmations"), ("count_attendance", "Count attendance"),
]


def library_items():
    with open(LIBRARY_FILE, encoding="utf-8") as handle:
        return json.load(handle)


class ProcedureLibrary(models.Model):
    """One procedure of the library (data/procedure_library.json): in our own words, EN and FR."""

    _name = "ea.audit.procedure.library"
    _description = "Substantive procedure library"
    _order = "sequence, code"
    _rec_name = "code"

    code = fields.Char(required=True, index=True)
    cycle = fields.Char(string="Lead index", required=True, index=True)
    kind = fields.Selection([("MSP", "MSP"), ("ASP", "ASP")], required=True)
    sequence = fields.Integer(default=10)
    assertions = fields.Char(required=True, help="Assertion codes, comma separated.")
    title_en = fields.Char(required=True)
    title_fr = fields.Char(required=True)
    summary_en = fields.Text()
    summary_fr = fields.Text()
    when_en = fields.Char(string="When it applies (EN)")
    when_fr = fields.Char(string="When it applies (FR)")
    condition_en = fields.Char(string="Condition (EN)")
    condition_fr = fields.Char(string="Condition (FR)")
    suggest_levels = fields.Char(help="Combined levels at which the tool suggests it, comma separated.")
    suggest_assertions = fields.Char(help="Assertions on which the tool suggests it, comma separated.")
    automatable = fields.Selection(AUTOMATABLE_SELECTION)
    active = fields.Boolean(default=True)
    title = fields.Char(compute="_compute_words")
    summary = fields.Text(compute="_compute_words")

    _code_uniq = models.Constraint("UNIQUE(code)", "One library procedure per code.")

    @api.depends_context("lang")
    def _compute_words(self):
        fr = is_french(self.env)
        for item in self:
            item.title = item.title_fr if fr else item.title_en
            item.summary = item.summary_fr if fr else item.summary_en

    @api.model
    def _ea_load_library(self):
        """Install and update: the JSON is the source. A code no longer in it is archived, never
        deleted (a design may point at it)."""
        Library = self.sudo().with_context(active_test=False)
        existing = {item.code: item for item in Library.search([])}
        seen = set()
        for entry in library_items():
            values = {
                "code": entry["code"], "cycle": entry["cycle"], "kind": entry["kind"], "sequence": entry["sequence"],
                "assertions": ",".join(entry["assertions"]), "title_en": entry["title_en"], "title_fr": entry["title_fr"],
                "summary_en": entry["summary_en"], "summary_fr": entry["summary_fr"],
                "when_en": entry["when_en"], "when_fr": entry["when_fr"],
                "condition_en": entry.get("condition_en") or False, "condition_fr": entry.get("condition_fr") or False,
                "suggest_levels": ",".join(entry.get("suggest_levels") or []) or False,
                "suggest_assertions": ",".join(entry.get("suggest_assertions") or []) or False,
                "automatable": entry.get("automatable") or False, "active": True,
            }
            seen.add(entry["code"])
            item = existing.get(entry["code"])
            if item:
                changed = {key: value for key, value in values.items() if item[key] != value}
                if changed:
                    item.write(changed)
            else:
                Library.create(values)
        for code, item in existing.items():
            if code not in seen and item.active:
                item.active = False
        return len(seen)

    def _ea_rule(self):
        """The dict the pure services read."""
        self.ensure_one()
        return {
            "code": self.code, "cycle": self.cycle, "kind": self.kind,
            "assertions": (self.assertions or "").split(","),
            "suggest_levels": [x for x in (self.suggest_levels or "").split(",") if x],
            "suggest_assertions": [x for x in (self.suggest_assertions or "").split(",") if x],
            "condition_en": self.condition_en or None, "automatable": self.automatable or None,
        }


class DesignedProcedure(models.Model):
    """A procedure in (or offered to) the design of one significant account. See the module doc."""

    _name = "ea.audit.designed.procedure"
    _inherit = ["ea.audit.tool.record"]
    _description = "Designed substantive procedure"
    _order = "index_code, sequence, id"
    _rec_name = "code"

    index_code = fields.Char(string="Lead index", required=True, index=True)
    library_id = fields.Many2one("ea.audit.procedure.library", string="Library procedure", ondelete="restrict", index=True)
    code = fields.Char(required=True)
    kind = fields.Selection(KIND_SELECTION, required=True)
    sequence = fields.Integer(default=10)
    custom_text = fields.Text(string="Procedure written by the team")
    assertions = fields.Char(help="The account's relevant assertions this procedure answers, comma separated.")
    selected = fields.Boolean(string="In the design")
    in_scope = fields.Boolean(default=True, help="False once the account or its assertions no longer call for it.")
    reason = fields.Selection(REASON_SELECTION, string="Why it is here")
    reason_assertion = fields.Char()
    reason_level = fields.Char()
    selected_by_id = fields.Many2one("res.users", string="Chosen by", ondelete="set null")
    selected_at = fields.Datetime(string="Chosen on")
    state = fields.Selection(STATE_SELECTION, default="draft", required=True)
    run_ids = fields.One2many("ea.audit.automation.run", "designed_procedure_id", string="Samples")
    step_id = fields.Many2one("ea.audit.program.step", string="Program step", ondelete="set null")
    conclusion = fields.Selection(CONCLUSION_SELECTION)
    conclusion_note = fields.Text(string="Conclusion note")
    done_by_id = fields.Many2one("res.users", string="Concluded by", ondelete="set null")
    done_at = fields.Datetime(string="Concluded on")
    title = fields.Char(compute="_compute_title", compute_sudo=True)

    _uniq = models.Constraint("UNIQUE(engagement_id, index_code, code)", "One row per account and procedure.")

    @api.depends("library_id", "custom_text")
    @api.depends_context("lang")
    def _compute_title(self):
        fr = is_french(self.env)
        for proc in self:
            if proc.library_id:
                proc.title = proc.library_id.title_fr if fr else proc.library_id.title_en
            else:
                proc.title = proc.custom_text or proc.code

    @api.depends("code", "title")
    def _compute_display_name(self):
        for proc in self:
            proc.display_name = ("%s %s" % (proc.code or "", proc.title or "")).strip()

    def _ea_started(self):
        self.ensure_one()
        return self.state != "draft" or bool(self.sudo().run_ids)

    def _ea_mark_started(self):
        """Work began on it (a sample drawn, the execution page opened it): it stays in the design."""
        for proc in self.sudo().filtered(lambda p: p.state == "draft"):
            proc.state = "started"


class EngagementProcedureDesign(models.Model):
    _inherit = "ea.audit.engagement"

    # ------------------------------------------------------------------
    # The design
    # ------------------------------------------------------------------

    def _ea_design_accounts(self):
        """The significant accounts of the CRA, each with its relevant assertions and their levels."""
        self.ensure_one()
        root = self.sudo()
        significant = {row["index"] for row in root._ea_significance_rows() if row["status"] == "significant"}
        accounts = []
        for row in root.cra_row_ids.filtered(lambda r: r.index_code in significant).sorted(lambda r: (r.sequence, r.id)):
            # an RO cell on the board only by default and unassessed is no relevant assertion yet (F041)
            cells = row.cell_ids.filtered(lambda c: c.relevant and not (
                c.assertion == "RO" and c.relevant_defaulted and not c.ir and not c.cr
            )).sorted(lambda c: (c.sequence, c.id))
            accounts.append({
                "row": row, "code": row.index_code, "cells": cells,
                "relevant": [cell.assertion for cell in cells],
                "levels": {cell.assertion: cell.level for cell in cells},
                "failed": {cell.assertion for cell in cells if cell.cr == "not_rely" and CR_DEFICIENT_BASIS in (cell.cr_basis or "")},
            })
        return accounts

    def _ea_sync_procedures(self):
        """The mandatory procedures of every significant account, ticked; a row whose account or
        assertions no longer call for it leaves the scope (kept, never deleted). Read only on an
        archived file."""
        self.ensure_one()
        root = self.sudo()
        if root._ea_is_archived():
            return
        root._ea_sync_cra()
        Proc = self.env["ea.audit.designed.procedure"].sudo()
        Library = self.env["ea.audit.procedure.library"].sudo()
        existing = {(p.index_code, p.code): p for p in Proc.search([("engagement_id", "=", self.id)])}
        seen = set()
        for account in root._ea_design_accounts():
            relevant = account["relevant"]
            for item in Library.search([("cycle", "=", account["code"])]):
                rule = item._ea_rule()
                answers = covered(rule, relevant)
                key = (account["code"], item.code)
                proc = existing.get(key)
                if not answers:
                    continue
                seen.add(key)
                values = {"assertions": ",".join(answers), "in_scope": True}
                if proc:
                    changed = {name: value for name, value in values.items() if proc[name] != value}
                    if is_locked(rule) and not proc.selected:
                        changed.update({"selected": True, "reason": "mandatory"})
                    if changed:
                        proc.write(changed)
                elif is_locked(rule):
                    Proc.create({
                        "engagement_id": self.id, "index_code": account["code"], "library_id": item.id, "code": item.code,
                        "kind": item.kind, "sequence": item.sequence, "selected": True, "reason": "mandatory", **values,
                    })
        for key, proc in existing.items():
            if key not in seen and proc.kind != "custom" and proc.in_scope:
                proc.write({"in_scope": False})

    def _ea_design_account(self, index_code):
        account = next((a for a in self.sudo()._ea_design_accounts() if a["code"] == index_code), None)
        if not account:
            raise rule_error(self.env, "not-found")
        return account

    def ea_procedure_choose(self, index_code, code, selected):
        """Tick or untick an alternative (or a mandatory procedure that depends on a condition). A
        mandatory procedure stays; a procedure already started stays."""
        self.ensure_one()
        self._ea_tool_guard()
        self.sudo()._ea_sync_procedures()
        account = self._ea_design_account(index_code)
        Proc = self.env["ea.audit.designed.procedure"].sudo()
        proc = Proc.search([("engagement_id", "=", self.id), ("index_code", "=", index_code), ("code", "=", code)], limit=1)
        item = self.env["ea.audit.procedure.library"].sudo().search([("code", "=", code), ("cycle", "=", index_code)], limit=1)
        if not item and not (proc and proc.kind == "custom"):
            raise rule_error(self.env, "not-found")
        rule = item._ea_rule() if item else None
        if rule and is_locked(rule):
            raise rule_error(self.env, "procedure-mandatory")
        answers = covered(rule, account["relevant"]) if rule else (proc.assertions or "").split(",")
        if selected:
            if not answers:
                raise rule_error(self.env, "procedure-not-offered")
            hint = suggest(rule, account["levels"], account["relevant"], account["failed"]) if rule else None
            if hint:
                reason = "suggested" if hint["why"] == "risk" else "control"
            else:
                reason = "condition" if rule and rule["condition_en"] else "choice"
            values = {
                "selected": True, "in_scope": True, "reason": reason, "assertions": ",".join(answers),
                "reason_assertion": hint["assertion"] if hint else False, "reason_level": hint["level"] if hint and hint["level"] else False,
                "selected_by_id": self.env.user.id, "selected_at": fields.Datetime.now(),
            }
            if proc:
                if proc.selected:
                    return self.ea_procedure_design_page()
                proc.write(values)
            else:
                proc = Proc.create({
                    "engagement_id": self.id, "index_code": index_code, "library_id": item.id, "code": item.code,
                    "kind": item.kind, "sequence": item.sequence, **values,
                })
            task_code = INDEX_SECTION.get(index_code)
            if task_code:
                self.sudo()._ea_ensure_task(task_code)
            self._ea_log("dsp_changed", "S5.5 %s %s chosen" % (index_code, code))
        else:
            if not proc or not proc.selected:
                return self.ea_procedure_design_page()
            if proc._ea_started():
                raise rule_error(self.env, "procedure-started")
            proc.write({"selected": False, "reason": False, "reason_assertion": False, "reason_level": False})
            self._ea_log("dsp_changed", "S5.5 %s %s removed" % (index_code, code))
        self._ea_invalidate_signoffs("S5.5")
        return self.ea_procedure_design_page()

    def ea_procedure_add(self, index_code, text, assertions):
        """Add another procedure, written by the team, on the account's relevant assertions."""
        self.ensure_one()
        self._ea_tool_guard()
        self.sudo()._ea_sync_procedures()
        account = self._ea_design_account(index_code)
        text = (text or "").strip()
        codes = [code for code in ASSERTIONS if code in (assertions or []) and code in account["relevant"]]
        if not text or len(text) > OSP_TEXT_MAX or not codes or any(code not in ASSERTIONS for code in assertions or []):
            raise rule_error(self.env, "invalid-osp")
        Proc = self.env["ea.audit.designed.procedure"].sudo()
        own = Proc.search([("engagement_id", "=", self.id), ("index_code", "=", index_code), ("kind", "=", "custom")])
        if len(own) >= OSP_MAX:
            raise rule_error(self.env, "invalid-osp")
        Proc.create({
            "engagement_id": self.id, "index_code": index_code, "code": "%s-X%d" % (index_code, len(own) + 1), "kind": "custom",
            "sequence": 900 + len(own), "custom_text": text, "assertions": ",".join(codes), "selected": True, "reason": "choice",
            "selected_by_id": self.env.user.id, "selected_at": fields.Datetime.now(),
        })
        task_code = INDEX_SECTION.get(index_code)
        if task_code:
            self.sudo()._ea_ensure_task(task_code)
        self._ea_invalidate_signoffs("S5.5")
        self._ea_log("dsp_changed", "S5.5 %s osp_list changed" % index_code)
        return self.ea_procedure_design_page()

    def ea_procedure_draw(self, proc_id):
        """"Draw the sample": the sampling wizard, filled with the account's population."""
        self.ensure_one()
        self._ea_tool_guard()
        proc = self.env["ea.audit.designed.procedure"].sudo().browse(int(proc_id or 0)).exists()
        if not proc or proc.engagement_id != self.sudo() or not proc.selected:
            raise rule_error(self.env, "not-found")
        if proc._ea_mode() == "vouch":
            # K-M2 draws its sample on its own working paper (owner, 2026-11-16)
            return self._ea_paper_action(proc)
        kind = dataset_kind(proc.library_id._ea_rule() if proc.library_id else None, proc.index_code)
        dataset = self.env["ea.audit.dataset"].sudo().search([
            ("engagement_id", "=", self.id), ("kind", "=", kind), ("superseded_at", "=", False), ("timing", "!=", "subsequent"),
        ], limit=1) if kind else self.env["ea.audit.dataset"]
        context = {"default_engagement_id": self.id, "default_designed_procedure_id": proc.id, "default_method": "mus"}
        if dataset:
            context["default_dataset_id"] = dataset.id
        return {
            "type": "ir.actions.act_window", "name": self.env._("Draw the sample"), "res_model": "ea.audit.sampling.wizard",
            "view_mode": "form", "views": [(False, "form")], "target": "new", "context": context,
        }

    def ea_procedure_reliance(self, control_id, reliance):
        """Normal / Heavy on the tests of controls: the SCOT control's own rule-bearing save."""
        self.ensure_one()
        control = self.env["ea.audit.scot.control"].browse(int(control_id or 0)).exists()
        if not control or control.sudo().engagement_id != self.sudo():
            raise rule_error(self.env, "not-found")
        control.update_control({"reliance": reliance})
        return self.ea_procedure_design_page()

    def ea_procedure_open(self, method, res_id=None):
        """The page's links: the sampling page (on one sample), a control's test, the lists upstream."""
        self.ensure_one()
        self._ea_require_access()
        if method == "sample":
            run = self.env["ea.audit.automation.run"].browse(int(res_id or 0)).exists()
            if not run or run.sudo().engagement_id != self.sudo():
                raise rule_error(self.env, "not-found")
            action = self.action_tool_sampling()
            action["params"] = dict(action["params"], focus="tod:%d" % run.id)
            return action
        if method == "control":
            return self.ea_sampling_open("action_open_full", res_id)
        if method not in ("action_tool_cra", "action_tool_scot", "action_tool_sampling", "action_tool_dsp_list"):
            raise rule_error(self.env, "forbidden")
        return getattr(self, method)()

    # ------------------------------------------------------------------
    # The page
    # ------------------------------------------------------------------

    def ea_procedure_design_page(self):
        """What the procedure design page shows: section 1, the controls to test; section 2, the
        tests of details per significant account."""
        self.ensure_one()
        self._ea_require_access()
        root = self.sudo()
        root._ea_sync_procedures()
        fr = is_french(self.env)
        locale = "fr" if fr else "en"
        lang = "fr_FR" if fr else "en_US"
        reason = self._ea_cra_read_only()
        Cell = self.env["ea.audit.cra.assessment"].with_context(lang=lang)
        levels_label = dict(Cell._fields["level"]._description_selection(Cell.env))
        controls = self._ea_design_controls(lang)
        procs = self.env["ea.audit.designed.procedure"].sudo().with_context(lang=lang).search([("engagement_id", "=", self.id)])
        Library = self.env["ea.audit.procedure.library"].sudo().with_context(lang=lang)
        legacy = self._ea_legacy_design()
        accounts, done, tod_count = [], 0, 0
        for account in root._ea_design_accounts():
            code = account["code"]
            relevant = account["relevant"]
            mine = procs.filtered(lambda p: p.index_code == code)
            by_code = {p.code: p for p in mine}
            rows, more = [], []
            for item in Library.search([("cycle", "=", code)]):
                rule = item._ea_rule()
                answers = covered(rule, relevant)
                proc = by_code.get(item.code)
                row = self._ea_design_row(item, rule, proc, account, answers, locale, levels_label)
                if not answers and not (proc and proc.selected):
                    more.append({"code": item.code, "title": item.title})
                    continue
                rows.append(row)
            for proc in mine.filtered(lambda p: p.kind == "custom"):
                rows.append(self._ea_design_row(None, None, proc, account, (proc.assertions or "").split(","), locale, levels_label))
            chosen = [{"kind": p.kind, "assertions": (p.assertions or "").split(",")} for p in mine if p.selected and p.in_scope]
            status = design_state(account["levels"], relevant, chosen)
            done += status["complete"]
            tod_count += len(chosen)
            mandatory = len([r for r in rows if r["kind"] == "MSP" and r["locked"]])
            alternatives = [r for r in rows if r["kind"] != "MSP" or not r["locked"]]
            definition = LEAD_INDEX_BY_CODE.get(code)
            accounts.append({
                "code": code, "label": lead_index_label(definition, locale) if definition else code,
                "closing": grouped(account["row"].closing or 0, lang),
                "levels": [{
                    "assertion": cell.assertion, "level": cell.level, "label": levels_label.get(cell.level, cell.level),
                } for cell in account["cells"]],
                "mandatory": mandatory, "chosen": len([r for r in alternatives if r["selected"]]), "offered": len(alternatives),
                "complete": status["complete"], "to_assess": status["to_assess"], "missing": status["missing_asp"],
                "rows": rows, "more": more, "legacy": legacy.get(code, 0),
            })
        return {
            "engagement": root.display_name,
            "readonly": bool(reason), "archived": reason == "archived",
            "assertions": ASSERTIONS,
            "stats": {
                "controls": len(controls), "occurrences": sum(c["planned"] for c in controls),
                "accounts": len(accounts), "tod": tod_count,
            },
            "progress": {"done": done, "total": len(accounts)},
            "controls": controls,
            "accounts": accounts,
            "missing": False if accounts else (root._ea_cra_missing() if not root.cra_row_ids else "significance"),
        }

    def _ea_design_row(self, item, rule, proc, account, answers, locale, levels_label):
        selected = bool(proc and proc.selected)
        started = bool(proc and proc._ea_started())
        locked = bool(rule and is_locked(rule))
        hint = suggest(rule, account["levels"], account["relevant"], account["failed"]) if rule else None
        fr = locale == "fr"
        own = set(rule["assertions"]) if rule else set(answers)
        dots = {}
        for code in ASSERTIONS:
            if code in answers:
                dots[code] = "covered" if selected else "would"
            elif code in own:
                dots[code] = "other"
        kind = proc.kind if proc else item.kind
        why, why_tone = self._ea_design_why(item, rule, proc, hint, selected, fr, levels_label)
        run = proc.run_ids.sorted("id", reverse=True)[:1] if proc else None
        mode = sample_mode(rule) if rule else "draw"
        sample = None
        if run:
            sample = {"id": run.id, "title": run.purpose or run.title, "count": len(run.sheet_rows or [])}
        state = proc.state if proc and selected else False
        return {
            "id": proc.id if proc else False, "code": proc.code if proc else item.code, "kind": kind,
            "title": proc.title if proc else item.title,
            "summary": (item.summary or "") if item else (proc.custom_text or ""),
            "when": ((item.when_fr if fr else item.when_en) or "") if item else "",
            "selected": selected, "locked": locked, "started": started, "dots": dots,
            "why": why, "why_tone": why_tone, "sample": sample, "sample_mode": mode,
            "state": state, "state_label": dict(_state_labels(self.env)).get(state, "") if state else "",
            # roll forward: chosen last year, carried as a draft
            "carried": self.env._("Carried forward from %(year)s: to update", year=proc.carried_from_year)
            if proc and proc.carried_from_year else False,
        }

    def _ea_design_why(self, item, rule, proc, hint, selected, fr, levels_label):
        """The "Why it is here" tag: (text, tone)."""
        _ = self.env._
        if rule and is_locked(rule):
            return _("Always"), "plain"
        condition_text = ((item.condition_fr if fr else item.condition_en) or "") if item else ""
        if proc and selected:
            if proc.reason == "suggested":
                return _("suggested · %(assertion)s %(level)s", assertion=proc.reason_assertion or "", level=levels_label.get(proc.reason_level, proc.reason_level or "")), "risk-%s" % (proc.reason_level or "high")
            if proc.reason == "control":
                return _("suggested · control not effective on %s", proc.reason_assertion or ""), "risk-high"
            if proc.reason == "condition" and condition_text:
                return _("condition met · %s", condition_text), "condition"
            return _("your choice"), "choice"
        if hint and hint["why"] == "risk":
            return _("suggested · %(assertion)s %(level)s", assertion=hint["assertion"], level=levels_label.get(hint["level"], hint["level"])), "risk-%s" % hint["level"]
        if hint:
            return _("suggested · control not effective on %s", hint["assertion"]), "risk-high"
        if condition_text:
            return _("Only if: %s", condition_text), "plain"
        return "", "plain"

    def _ea_design_controls(self, lang):
        """Section 1: the controls ticked "To test" on the SCOT pages."""
        Control = self.env["ea.audit.scot.control"].sudo().with_context(lang=lang)
        controls = Control.search([("engagement_id", "=", self.id), ("selected_for_testing", "=", True)])
        types = dict(Control._fields["control_type"]._description_selection(Control.env))
        _ = self.env._
        out = []
        for control in controls.sorted(lambda c: (c.scot_id.id, c.id)):
            if control.operating_eval == "effective":
                status, tone = _("Tested · effective"), "good"
            elif control.operating_eval == "not_effective":
                status, tone = _("Tested · not effective"), "bad"
            elif control.testing_started:
                status, tone = _("In progress"), "warn"
            elif control.toc_sample_items:
                status, tone = _("To test"), "warn"
            else:
                status, tone = _("Not started"), "open"
            out.append({
                "id": control.id, "code": control.code, "name": control.name, "scot": control.scot_id.name,
                "type": types.get(control.control_type, control.control_type), "frequency": control.frequency_display or "",
                "reliance": control.reliance or "normal", "suggested": control.suggested_size or 0,
                "planned": control.sample_size or control.suggested_size or 0, "assertions": control._ea_assertions(),
                "status": status, "tone": tone, "drawn": bool(control.toc_sample_items),
            })
        return out

    def _ea_legacy_design(self):
        """Per account, what was chosen before the library (former catalog and other procedures)."""
        counts = {}
        chosen = self.env["ea.audit.dsp.choice"].sudo().search([("engagement_id", "=", self.id), ("selected", "=", True)])
        for choice in chosen:
            counts[choice.design_id.index_code] = counts.get(choice.design_id.index_code, 0) + 1
        for osp in self.env["ea.audit.dsp.osp"].sudo().search([("engagement_id", "=", self.id)]):
            counts[osp.index_code] = counts.get(osp.index_code, 0) + 1
        return counts

    def action_tool_dsp(self):
        """Procedure design, on one page (owner's mock-ups of 2026-11-16)."""
        self.ensure_one()
        self._ea_require_access()
        return {
            "type": "ir.actions.client", "tag": "ea_audit_tools.procedure_design", "target": "current",
            "name": self.env._("Procedure design"), "params": {"engagement_id": self.id},
            "context": {"active_id": self.id, "ea_engagement_id": self.id},
        }


def _state_labels(env):
    _ = env._
    return [("draft", _("Not started")), ("started", _("In progress")), ("done", _("Done"))]


class AutomationRunProcedure(models.Model):
    _inherit = "ea.audit.automation.run"

    designed_procedure_id = fields.Many2one(
        "ea.audit.designed.procedure", string="Designed procedure", ondelete="set null", index=True,
        help="The test of details this sample was drawn for.",
    )
