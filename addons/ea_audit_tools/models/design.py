"""S5.5, procedure design: nature, timing and extent per assertion (lib/design-procedures.ts, lib/psp.ts), and the audit
programs generated from the library (lib/programs.ts)."""
import re

from odoo import api, fields, models

from ..rules import rule_error
from ..services.assertions import ASSERTIONS, assertion_label
from ..services.design_procedures_model import NATURE_OPTIONS, NATURE_VALUES, OSP_EXTENT_MAX, OSP_MAX, OSP_TEXT_MAX, TIMING_OPTIONS, TIMING_VALUES, cra_level_of, timing_allowed
from ..services.lead_classes import INDEX_SECTION, LEAD_INDEXES
from ..services.procedure_data import GENERIC, PLATFORM_OF_CANONICAL, PROCEDURE_LIBRARY, PROGRAM_LIBRARY, PSP_CATALOG, SIGNIFICANT_RISK_EXTENSIONS
from .tool_record import is_french

NATURE_SELECTION = [(option["value"], option["en"]) for option in NATURE_OPTIONS]
TIMING_SELECTION = [(option["value"], option["en"]) for option in TIMING_OPTIONS]
_INDEX = re.compile(r"^[A-Z][A-Z0-9]{0,2}$")
TIER_RANK = {"baseline": 0, "heightened": 1, "significant": 2}


def psp_for(index_code):
    return PSP_CATALOG.get(index_code) or GENERIC


def indexes_for_task(task_code):
    return [index for index, task in INDEX_SECTION.items() if task == task_code]


class DspDesign(models.Model):
    """One relevant assertion of one significant account, against that assertion's CRA (ISA 330 ¶6-7).
    The rows follow S3.1; what is recorded on them is the design."""

    _name = "ea.audit.dsp.design"
    _inherit = ["ea.audit.tool.record"]
    _description = "Substantive procedure design"
    _order = "sequence, index_code, assertion"
    _rec_name = "index_code"

    index_code = fields.Char(string="Lead index", required=True, index=True)
    assertion = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    nature = fields.Selection(NATURE_SELECTION)
    timing = fields.Selection(TIMING_SELECTION)
    extent = fields.Char()
    tod_level = fields.Char(string="Combined assessment", readonly=True)
    tod_level_label = fields.Char(string="Combined assessment", compute="_compute_labels", compute_sudo=True)
    assertion_label = fields.Char(string="Assertion", compute="_compute_labels", compute_sudo=True)
    significant = fields.Boolean(readonly=True)
    not_rely = fields.Boolean(string="No reliance on controls", readonly=True)
    active_row = fields.Boolean(string="On the board", default=True, readonly=True)
    choice_ids = fields.One2many("ea.audit.dsp.choice", "design_id", string="Procedures")
    selected_count = fields.Integer(string="Selected", compute="_compute_selected", compute_sudo=True)
    selected_positions = fields.Char(string="Positions", compute="_compute_selected", compute_sudo=True)

    _uniq = models.Constraint("UNIQUE(engagement_id, index_code, assertion)", "One design per account and assertion.")

    @api.depends("tod_level", "assertion")
    @api.depends_context("lang")
    def _compute_labels(self):
        """F041, M-05: the words, not the stored codes."""
        levels = dict(self.env["ea.audit.cra.assessment"]._fields["tod_level"]._description_selection(self.env))
        locale = "fr" if is_french(self.env) else "en"
        for design in self:
            design.tod_level_label = levels.get(design.tod_level, design.tod_level) or False
            design.assertion_label = assertion_label(design.assertion, locale)

    @api.depends("choice_ids.selected")
    def _compute_selected(self):
        for design in self:
            chosen = design.choice_ids.filtered("selected").mapped("position")
            design.selected_count = len(chosen)
            design.selected_positions = ",".join(str(position) for position in sorted(chosen))

    def _ea_user_write(self, vals):
        self._ea_only(vals, {"nature", "timing", "extent"})
        for design in self:
            for key in ("nature", "timing", "extent"):
                if key in vals:
                    design.sudo().engagement_id.with_env(self.env).save_dsp(design.sudo().index_code, "%s_%s" % (design.sudo().assertion, key), vals[key] or "")
        return True

    def action_open(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id, "view_mode": "form", "target": "current",
            "views": [(self.env.ref("ea_audit_tools.view_dsp_design_form").id, "form")], "context": {"ea_engagement_id": self.sudo().engagement_id.id},
        }


class DspChoice(models.Model):
    """A library procedure offered for a design: ticking it sends it to the E4 paper."""

    _name = "ea.audit.dsp.choice"
    _inherit = ["ea.audit.tool.record"]
    _description = "Library procedure offered"
    _order = "design_id, position"
    _rec_name = "label"

    design_id = fields.Many2one("ea.audit.dsp.design", required=True, ondelete="cascade", index=True)
    position = fields.Integer(required=True)
    selected = fields.Boolean()
    label = fields.Text(string="Procedure", compute="_compute_label", compute_sudo=True)
    assertions_label = fields.Char(string="Assertions", compute="_compute_label", compute_sudo=True)

    @api.depends("position", "design_id.index_code")
    @api.depends_context("lang")
    def _compute_label(self):
        fr = is_french(self.env)
        for choice in self:
            catalog = psp_for(choice.design_id.index_code)
            proc = catalog[choice.position] if choice.position < len(catalog) else None
            choice.label = (proc["fr"] if fr else proc["en"]) if proc else False
            choice.assertions_label = proc["a"] if proc else False

    def _ea_user_write(self, vals):
        self._ea_only(vals, {"selected"})
        for choice in self:
            as_root = choice.sudo()
            design = as_root.design_id
            others = design.choice_ids.filtered("selected").mapped("position")
            chosen = sorted((set(others) | {as_root.position}) if vals["selected"] else (set(others) - {as_root.position}))
            design.engagement_id.with_env(self.env).save_dsp(design.index_code, "sel_%s" % design.assertion, chosen)
        return True


class DspOsp(models.Model):
    """A custom ("other") procedure written for the account, with a library procedure's parameters."""

    _name = "ea.audit.dsp.osp"
    _inherit = ["ea.audit.tool.record"]
    _description = "Other substantive procedure"
    _order = "index_code, id"
    _rec_name = "text"

    index_code = fields.Char(string="Lead index", required=True, index=True)
    text = fields.Text(string="Procedure", required=True)
    assertion_ids = fields.Many2many("ea.audit.assertion", string="Assertions")
    nature = fields.Selection(NATURE_SELECTION)
    timing = fields.Selection(TIMING_SELECTION)
    extent = fields.Char()

    def _ea_user_unlink(self):
        for osp in self:
            osp._ea_guard()
            engagement = osp.sudo().engagement_id
            osp.sudo().unlink()
            engagement._ea_invalidate_signoffs("S5.5")
        return True


class EngagementDesign(models.Model):
    _inherit = "ea.audit.engagement"

    dsp_gap_label = fields.Char(string="Accounts with nothing designed", compute="_compute_dsp_gaps", compute_sudo=True)

    def _compute_dsp_gaps(self):
        # first, for all of them: reading the gaps syncs S5.5, whose writes would drop a value already
        # assigned here, including one assigned to another engagement of this batch
        gaps_of = {engagement.id: engagement._ea_dsp_gaps() for engagement in self}
        for engagement in self:
            engagement.dsp_gap_label = ", ".join(gaps_of[engagement.id]) or "—"

    def _ea_sync_dsp(self):
        """dspView's rows: a cell relevant only by the no-selection fallback asks for no procedures."""
        self.ensure_one()
        as_root = self.sudo()
        as_root._ea_sync_cra()
        Design = self.env["ea.audit.dsp.design"].sudo()
        order = {definition["code"]: position for position, definition in enumerate(LEAD_INDEXES)}
        existing = {(d.index_code, d.assertion): d for d in Design.search([("engagement_id", "=", self.id)])}
        seen = set()
        cells = self.env["ea.audit.cra.assessment"].sudo().search([("engagement_id", "=", self.id)])
        for cell in cells.filtered(lambda c: c.relevant and not c.relevant_defaulted):
            key = (cell.index_code, cell.assertion)
            seen.add(key)
            values = {
                "tod_level": cell.tod_level, "significant": cell.significant, "active_row": True,
                "not_rely": (cell.cr or cell.suggested_cr) == "not_rely",
            }
            design = existing.get(key)
            if design:
                changed = {name: value for name, value in values.items() if design[name] != value}
                if changed:
                    design.write(changed)
                continue
            design = Design.create({
                "engagement_id": self.id, "index_code": cell.index_code, "assertion": cell.assertion,
                "sequence": order.get(cell.index_code, 999) * 10 + (ASSERTIONS.index(cell.assertion) if cell.assertion in ASSERTIONS else 9), **values,
            })
            # The library replaced the former catalog (2026-11-16): a new row is offered no catalog
            # choice; the rows created before keep theirs (ea.audit.designed.procedure holds the design).
        for key, design in existing.items():
            if key not in seen and design.active_row:
                design.write({"active_row": False})
        return Design.search([("engagement_id", "=", self.id), ("active_row", "=", True)])

    def _ea_dsp_gaps(self):
        """Significant accounts with key assertions and no procedure selected yet."""
        self.ensure_one()
        designs = self.sudo()._ea_sync_dsp()
        osps = set(self.env["ea.audit.dsp.osp"].sudo().search([("engagement_id", "=", self.id)]).mapped("index_code"))
        osps |= self._ea_library_designed_indexes()
        gaps = []
        for code in dict.fromkeys(designs.mapped("index_code")):
            if code in osps:
                continue
            if not designs.filtered(lambda d: d.index_code == code).choice_ids.filtered("selected"):
                gaps.append(code)
        return gaps

    def save_dsp(self, index_code, field, value):
        """saveDsp: nature and timing pinned to their sets, the timing to what the CRA permits, and
        analytics-led barred on a significant risk (ISA 330 ¶21, UAT B52, B75). Blank always clears."""
        self.ensure_one()
        self._ea_tool_guard()
        if not _INDEX.match(index_code or ""):
            raise rule_error(self.env, "invalid-index")
        parts = (field or "").split("_")
        selection = len(parts) == 2 and parts[0] == "sel" and parts[1] in ASSERTIONS
        design_field = len(parts) == 2 and parts[0] in ASSERTIONS and parts[1] in ("nature", "timing", "extent")
        if not selection and not design_field:
            raise rule_error(self.env, "invalid-field")
        designs = self.sudo()._ea_sync_dsp()
        assertion = parts[1] if selection else parts[0]
        design = designs.filtered(lambda d: d.index_code == index_code and d.assertion == assertion)
        if not design:
            raise rule_error(self.env, "not-found")
        before = None
        if selection:
            if not isinstance(value, list) or len(value) > 40 or any(not isinstance(n, int) or n < 0 or n > 40 for n in value):
                raise rule_error(self.env, "invalid-selection")
            before = design.selected_positions or ""
            chosen = set(value)
            for choice in design.choice_ids:
                if choice.selected != (choice.position in chosen):
                    choice.write({"selected": choice.position in chosen})
            designed = bool(value)
        else:
            kind = parts[1]
            value = value or ""
            if kind == "nature" and value:
                if value not in NATURE_VALUES:
                    raise rule_error(self.env, "invalid-value")
                if value == "sap_led" and design.significant:
                    raise rule_error(self.env, "nature-not-permitted")
            if kind == "timing" and value:
                if value not in TIMING_VALUES:
                    raise rule_error(self.env, "invalid-value")
                if value not in timing_allowed(cra_level_of(design.tod_level) if design.tod_level else None):
                    raise rule_error(self.env, "timing-not-permitted")
            before = design[kind] or ""
            design.write({kind: value or False})
            designed = False
        task_code = INDEX_SECTION.get(index_code)
        if designed and task_code:
            # a designed account needs the paper that executes the design (UAT run 2 B20)
            self.sudo()._ea_ensure_task(task_code)
        self._ea_invalidate_signoffs("S5.5")
        if str(before) != str(value):
            self._ea_log("dsp_changed", "S5.5 %s %s changed" % (index_code, field))
        return True

    def add_dsp_osp(self, index_code, text, assertions=(), nature=None, timing=None, extent=None):
        """osp_list: capped, values pinned to the option sets (it reaches the E4 program and the archive)."""
        self.ensure_one()
        self._ea_tool_guard()
        if not _INDEX.match(index_code or ""):
            raise rule_error(self.env, "invalid-index")
        text = (text or "").strip()
        if not text or len(text) > OSP_TEXT_MAX or len(extent or "") > OSP_EXTENT_MAX:
            raise rule_error(self.env, "invalid-osp")
        if nature and nature not in NATURE_VALUES or timing and timing not in TIMING_VALUES:
            raise rule_error(self.env, "invalid-osp")
        if any(code not in ASSERTIONS for code in assertions):
            raise rule_error(self.env, "invalid-osp")
        Osp = self.env["ea.audit.dsp.osp"].sudo()
        if Osp.search_count([("engagement_id", "=", self.id), ("index_code", "=", index_code)]) >= OSP_MAX:
            raise rule_error(self.env, "invalid-osp")
        osp = Osp.create({
            "engagement_id": self.id, "index_code": index_code, "text": text, "nature": nature or False, "timing": timing or False,
            "extent": extent or False, "assertion_ids": [(6, 0, self.env["ea.audit.assertion"]._ea_from_codes(list(assertions)).ids)],
        })
        task_code = INDEX_SECTION.get(index_code)
        if task_code:
            self.sudo()._ea_ensure_task(task_code)
        self._ea_invalidate_signoffs("S5.5")
        self._ea_log("dsp_changed", "S5.5 %s osp_list changed" % index_code)
        return osp.with_env(self.env)

    def _ea_designed_indexes(self):
        """dspDesignedIndexes: the lead indexes with a library procedure or a custom one in S5.5."""
        self.ensure_one()
        chosen = self.env["ea.audit.dsp.choice"].sudo().search([("engagement_id", "=", self.id), ("selected", "=", True)])
        osps = self.env["ea.audit.dsp.osp"].sudo().search([("engagement_id", "=", self.id)])
        return set(chosen.design_id.mapped("index_code")) | set(osps.mapped("index_code")) | self._ea_library_designed_indexes()

    def _ea_library_designed_indexes(self):
        """The lead indexes with a procedure in the design (library or written by the team)."""
        self.ensure_one()
        procs = self.env["ea.audit.designed.procedure"].sudo().search([
            ("engagement_id", "=", self.id), ("selected", "=", True), ("in_scope", "=", True),
        ])
        return set(procs.mapped("index_code"))

    def _ea_e4_out_of_scope(self):
        """visibleE4Codes' other side (F010): the E4 tasks S5.5 left out. A task shows when an account
        it holds was designed, when it holds no account, or when it already holds work. Nothing is
        written: designing a procedure brings the task back, on every list at once."""
        self.ensure_one()
        designed = self._ea_designed_indexes()
        items = self.env["ea.audit.file.item"].sudo().search([
            ("engagement_id", "=", self.id), ("code", "=like", "E4.%"), ("conditional", "=", False),
        ])
        with_steps = self.env["ea.audit.program.step"].sudo().search([("file_item_id", "in", items.ids)]).file_item_id

        def scoped_out(item):
            indexes = indexes_for_task(item.code)
            holds_work = item.state != "not_started" or item in with_steps
            return bool(indexes) and not holds_work and not designed.intersection(indexes)

        return items.filtered(scoped_out)

    def generate_psp(self, task_code):
        """generatePsp: what S5.5 designed for the task's accounts, idempotent. -1 when nothing was
        designed. The catalog half runs once; a custom procedure is de-duplicated on its wording."""
        self.ensure_one()
        self._ea_tool_guard()
        item = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.id), ("code", "=", task_code)], limit=1)
        if not item:
            raise rule_error(self.env, "not-found")
        indexes = indexes_for_task(task_code)
        if not indexes:
            return 0
        Step = self.env["ea.audit.program.step"].sudo()
        existing = Step.search([("file_item_id", "=", item.id)])
        catalog_done = "psp" in existing.mapped("source")
        seq = max(existing.mapped("seq") or [0])
        osp_no = len([s for s in existing if (s.description or "").startswith("OSP-")])
        bodies = {_step_body(s.description) for s in existing}
        created, saw_design, first = 0, False, None
        designs = self.sudo()._ea_sync_dsp()
        for index in indexes:
            chosen = sorted(set(designs.filtered(lambda d: d.index_code == index).choice_ids.filtered("selected").mapped("position")))
            osps = self.env["ea.audit.dsp.osp"].sudo().search([("engagement_id", "=", self.id), ("index_code", "=", index)])
            procs = self.env["ea.audit.designed.procedure"].sudo().search([
                ("engagement_id", "=", self.id), ("index_code", "=", index), ("selected", "=", True), ("in_scope", "=", True),
            ])
            for proc in procs:
                # the library's procedures, once each: the step is found again by its code
                saw_design = True
                prefix = "%s — " % proc.code
                if proc.step_id or any((s.description or "").startswith(prefix) for s in existing):
                    continue
                seq += 10
                created += 1
                step = Step.create({
                    "engagement_id": self.id, "file_item_id": item.id, "seq": seq, "source": proc.kind.lower(),
                    "description": prefix + (proc.title or proc.code),
                    "assertion_ids": [(6, 0, self.env["ea.audit.assertion"]._ea_from_codes((proc.assertions or "").split(",")).ids)],
                })
                proc.step_id = step
                first = first or step
            if not chosen and not osps:
                continue
            saw_design = True
            if chosen and not catalog_done:
                catalog = psp_for(index)
                position = 0
                for pos in chosen:
                    if pos >= len(catalog):
                        continue
                    position += 1
                    seq += 10
                    created += 1
                    proc = catalog[pos]
                    step = Step.create({
                        "engagement_id": self.id, "file_item_id": item.id, "seq": seq, "source": "psp",
                        "description": "%s%d — %s" % (index, position, proc["en"]),
                        "assertion_ids": [(6, 0, self.env["ea.audit.assertion"]._ea_from_codes(proc["a"].split(",")).ids)],
                    })
                    first = first or step
            for osp in osps:
                body = (osp.text or "").strip()
                if body in bodies:
                    continue
                bodies.add(body)
                osp_no += 1
                seq += 10
                created += 1
                step = Step.create({
                    "engagement_id": self.id, "file_item_id": item.id, "seq": seq, "source": "custom", "description": "OSP-%d — %s" % (osp_no, body),
                    "assertion_ids": [(6, 0, osp.assertion_ids.ids)],
                })
                first = first or step
        if not saw_design:
            return -1
        if first:
            # the procedures ARE the response: link the live risks of the section
            links = self.env["ea.audit.risk.section"].sudo().search([("file_item_id", "=", item.id)])
            first.risk_ids = [(4, link.risk_id.id) for link in links if not link.risk_id.rebutted]
        return created

    def generate_program(self, task_code):
        """generateProgram: the library, cumulative tiers from the section's risks, and the extended
        procedures for a significant risk, linked to it. Idempotent: no-op once steps exist."""
        self.ensure_one()
        self._ea_tool_guard()
        item = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.id), ("code", "=", task_code)], limit=1)
        if not item:
            raise rule_error(self.env, "not-found")
        Step = self.env["ea.audit.program.step"].sudo()
        if Step.search_count([("file_item_id", "=", item.id)]):
            return 0
        fr = is_french(self.env)
        tags = self.env["ea.audit.assertion"]
        seq = 0
        seen = set()

        def add(description, assertions, source):
            nonlocal seq
            seq += 10
            return Step.create({
                "engagement_id": self.id, "file_item_id": item.id, "seq": seq, "source": source, "description": description,
                "assertion_ids": [(6, 0, tags._ea_from_codes(list(assertions)).ids)],
            })

        for step in PROGRAM_LIBRARY.get(task_code, []):
            description = step["descFr"] if fr else step["descEn"]
            seen.add(description)
            add(description, step["assertions"], "library")
        links = self.env["ea.audit.risk.section"].sudo().search([("file_item_id", "=", item.id)])
        risks = links.risk_id.filtered(lambda risk: not risk.rebutted)
        tier = "significant" if risks.filtered("significant") else "heightened" if risks else "baseline"
        for entry in PROCEDURE_LIBRARY:
            if task_code not in entry["sectionCodes"] or TIER_RANK[entry["tier"]] > TIER_RANK[tier]:
                continue
            description = "%s [%s] (%s)" % (entry["titleFr"] if fr else entry["titleEn"], entry["code"], ", ".join(entry["assertions"]))
            if description in seen:
                continue
            seen.add(description)
            add(description, dict.fromkeys(PLATFORM_OF_CANONICAL[code] for code in entry["assertions"]), "library")
        significant = risks.filtered("significant")
        if significant:
            for step in SIGNIFICANT_RISK_EXTENSIONS:
                created = add(step["descFr"] if fr else step["descEn"], step["assertions"], "risk_extension")
                created.risk_ids = [(6, 0, significant.ids)]
            significant.filtered(lambda risk: risk.status == "identified").write({"status": "response_planned"})
        return seq // 10

    def add_custom_step(self, task_code, description, assertions=()):
        """addCustomStep."""
        self.ensure_one()
        self._ea_tool_guard()
        description = (description or "").strip()
        if not description:
            raise rule_error(self.env, "description-required")
        item = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.id), ("code", "=", task_code)], limit=1)
        if not item:
            raise rule_error(self.env, "not-found")
        Step = self.env["ea.audit.program.step"].sudo()
        last = max(Step.search([("file_item_id", "=", item.id)]).mapped("seq") or [0])
        return Step.create({
            "engagement_id": self.id, "file_item_id": item.id, "seq": last + 10, "source": "custom", "description": description,
            "assertion_ids": [(6, 0, self.env["ea.audit.assertion"]._ea_from_codes(list(assertions)).ids)],
        }).with_env(self.env)

    def section_coverage(self, task_code):
        """sectionCoverage: which assertions of each mapped risk the linked steps address."""
        self.ensure_one()
        self._ea_require_access()
        item = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.id), ("code", "=", task_code)], limit=1)
        rows = []
        links = self.env["ea.audit.risk.section"].sudo().search([("file_item_id", "=", item.id)])
        for link in links.filtered(lambda line: not line.risk_id.rebutted).sorted(lambda line: not line.risk_id.significant):
            steps = link.risk_id.program_step_ids.filtered(lambda step: step.file_item_id == item)
            rows.append({
                "riskId": link.risk_id.id, "riskDescription": link.risk_id.description, "significant": link.risk_id.significant,
                "assertions": link.assertion_ids.mapped("code"), "coveredAssertions": steps.assertion_ids.mapped("code"), "linkedSteps": len(steps),
            })
        return rows

    # ------------------------------------------------------------------
    # Screens and Excel
    # ------------------------------------------------------------------

    def action_tool_dsp_list(self):
        """The list of S5.5 (nature, timing, extent per account and assertion), and its Excel."""
        self.ensure_one()
        self._ea_require_access()
        self.sudo()._ea_sync_dsp()
        action = self._ea_list(
            "ea.audit.dsp.design", self.env._("S5.5: procedure design, nature, timing and extent"),
            [("ea_audit_tools.view_dsp_design_list", "list"), ("ea_audit_tools.view_dsp_design_form", "form")],
        )
        action["domain"] = [("engagement_id", "=", self.id), ("active_row", "=", True)]
        action["context"] = {"ea_engagement_id": self.id, "create": False}
        return action

    def action_tool_programs(self):
        return self._ea_list(
            "ea.audit.program.step", self.env._("Audit programs"),
            [("ea_audit_tools.view_program_step_list", "list")],
            {"context": {"ea_engagement_id": self.id, "create": False, "search_default_group_task": 1}, "search_view_id": self.env.ref("ea_audit_tools.view_program_step_search").id},
        )

    def _ea_export_dsp(self, fr):
        from ..exports import simple_workbook

        rows = [[
            design.index_code, design.assertion, design.tod_level_label or "", "yes" if design.significant else "no", design.nature or "",
            design.timing or "", design.extent or "", design.selected_positions or "",
        ] for design in self.sudo()._ea_sync_dsp()]
        return "s5-5-%s.xlsx" % self._ea_export_slug(), simple_workbook("S5.5", DSP_HEAD, rows)

    def _ea_import_dsp(self, table):
        """All or nothing: one refused row refuses the file, through the same method a screen uses."""
        count = 0
        for row in table["rows"]:
            index, assertion = (row.get("index") or "").strip(), (row.get("assertion") or "").strip()
            for name in ("nature", "timing", "extent"):
                if name in row:
                    self.save_dsp(index, "%s_%s" % (assertion, name), (row.get(name) or "").strip())
            if "selected" in row:
                raw = (row.get("selected") or "").strip()
                try:
                    chosen = [int(part) for part in raw.split(",") if part.strip()]
                except ValueError:
                    raise rule_error(self.env, "invalid-selection") from None
                self.save_dsp(index, "sel_%s" % assertion, chosen)
            count += 1
        return count


DSP_HEAD = ["index", "assertion", "tod", "significant", "nature", "timing", "extent", "selected"]


def _step_body(description):
    cut = (description or "").find(" — ")
    return ((description or "") if cut < 0 else (description or "")[cut + 3:]).strip()


class ProgramStepActions(models.Model):
    _inherit = "ea.audit.program.step"

    def action_list_generate_program(self):
        return self._ea_program_wizard("generate")

    def action_list_add_step(self):
        return self._ea_program_wizard("custom")

    def _ea_program_wizard(self, mode):
        engagement = self._ea_context_engagement()
        return {
            "type": "ir.actions.act_window", "name": self.env._("Audit programs"), "res_model": "ea.audit.program.wizard", "view_mode": "form", "views": [(False, "form")],
            "target": "new", "context": {"default_engagement_id": engagement.id, "default_mode": mode},
        }


class DspListActions(models.Model):
    _inherit = "ea.audit.dsp.design"

    def action_list_add_osp(self):
        engagement = self._ea_context_engagement()
        return {
            "type": "ir.actions.act_window", "name": self.env._("Add another substantive procedure"), "res_model": "ea.audit.osp.wizard", "view_mode": "form", "views": [(False, "form")],
            "target": "new", "context": {"default_engagement_id": engagement.id},
        }

    def action_list_export(self):
        return self._ea_context_engagement()._ea_export_action("dsp")

    def _ea_export_kind(self):
        return "dsp"
