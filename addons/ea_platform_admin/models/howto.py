"""How-to guides on the console's screens. The texts are in services/howto.py, drawn here in the
reader's language with the pictures of that language."""

from markupsafe import Markup, escape

from odoo import api, fields, models

from ..services import howto
from ..services.messages import _
from .i18n import t

STATIC = "/ea_platform_admin/static/howto"


def _rich(text):
    """Escaped text, where **words** become bold."""
    parts = str(text).split("**")
    out = Markup()
    for index, part in enumerate(parts):
        out += Markup("<strong>%s</strong>") % part if index % 2 else escape(part)
    return out


class PlatformHowto(models.Model):
    _name = "platform.howto"
    _description = "How-to guide"
    _order = "sequence, id"

    code = fields.Char(required=True, readonly=True)
    sequence = fields.Integer(default=10)
    name = fields.Char("Guide", compute="_compute_texts")
    summary = fields.Char("What it is for", compute="_compute_texts")
    step_count = fields.Integer("Steps", compute="_compute_texts")
    body = fields.Html("Content", compute="_compute_body", sanitize=False)

    _code_unique = models.Constraint("UNIQUE(code)", "One record per guide.")

    def _guide(self):
        self.ensure_one()
        try:
            return howto.guide(self.code)
        except KeyError:
            return None

    @api.depends("code")
    @api.depends_context("lang")
    def _compute_texts(self):
        for record in self:
            item = record._guide()
            record.name = t(self.env, item["title"]) if item else record.code
            record.summary = t(self.env, item["summary"]) if item else False
            record.step_count = len(item["steps"]) if item else 0

    @api.depends("code")
    @api.depends_context("lang")
    def _compute_body(self):
        for record in self:
            item = record._guide()
            record.body = self.env["ir.qweb"]._render(
                "ea_platform_admin.howto_page", record._page_values(item),
            ) if item else False

    def _page_values(self, item):
        """Plain strings and Markup only: the template holds no text of its own."""
        env = self.env
        folder = howto.image_folder(env.lang)
        steps = []
        for number, step in enumerate(item["steps"], 1):
            table = step.get("table")
            steps.append({
                "number": number,
                "anchor": f"ea-howto-step-{number}",
                "label": t(env, _("Step %(number)s", number=number)),
                "heading": _rich(t(env, step["heading"])),
                "images": [{
                    "src": f"{STATIC}/{item['code']}/{folder}/{name}",
                    "caption": _rich(t(env, caption)),
                    "alt": t(env, caption),
                } for name, caption in step.get("images", ())],
                "do": [_rich(t(env, text)) for text in step.get("do", ())],
                "list_title": _rich(t(env, step["list_title"])) if step.get("list_title") else False,
                "list": [_rich(t(env, text)) for text in step.get("list", ())],
                "table": {
                    "head": [t(env, text) for text in table["head"]],
                    "rows": [[_rich(t(env, text)) for text in row] for row in table["rows"]],
                } if table else False,
                "after_table": _rich(t(env, step["after_table"])) if step.get("after_table") else False,
                "note": _rich(t(env, step["note"])) if step.get("note") else False,
                "why": _rich(t(env, step["why"])) if step.get("why") else False,
                "next": _rich(t(env, step["next"])) if step.get("next") else False,
            })
        return {
            "title": t(env, item["title"]),
            "summary": t(env, item["summary"]),
            "intro": [_rich(t(env, text)) for text in item["intro"]],
            "steps": steps,
            "labels": {key: t(env, text) for key, text in howto.LABELS.items()},
        }
