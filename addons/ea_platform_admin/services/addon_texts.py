"""The names and summaries of the shared codebase's addons, so that fr.po can translate them.

The catalogue stores what the manifests say, in English. The screens read it through models/i18n.py,
which translates a source it finds in fr.po and shows any other text as written. This file is only
there for the translation export to find those sources.
"""

from .messages import _

TEXTS = (
    _("AuditISA Core"),
    _("Firm roles, engagements, teams, file index, sign-off governance and gates"),
    _("AuditISA Client Add-on Switches"),
    _("The per-firm switch of optional client add-ons: off hides them and keeps their data"),
    _("AuditISA Firm Agent"),
    _("Heartbeat of a firm's server, its first administrator's one-time link, mail gate"),
    _("AuditISA OHADA Legal Register"),
    _("Statutory deadlines, regulated agreements, art. 715 report, alert procedure, criminal facts, securities attestation, equity monitoring, joint auditor file, art. 525 certification"),
    _("AuditISA Working Papers"),
    _("Paper definitions, answers and history, review notes, conclusions, evidence and the paper renderer"),
    _("AuditISA Client Portal"),
    _("List of documents requested from the client, and their uploads by client contacts invited by a one-time link"),
    _("AuditISA Reports"),
    _("Completion gates, opinion and auditor's report, letters, archive, retention and legal hold, export bundle"),
    _("AuditISA Time and Firm Administration"),
    _("Feuille de temps on hr_timesheet with the firm's weekly deadline; the firm administrator's users and mail screens"),
    _("AuditISA Tools"),
    _("Trial balance, lead schedules, materiality, risks, combined risk assessment, findings, summary of audit differences and the tools hub"),
    _("AuditISA Screens"),
    _("The firm's top bar, home, engagement dashboard and task lists, on the core models"),
    _("SAMPLE: Client notes"),
    _("Sample client add-on, to prove the path: a small notes screen. Not a product feature."),
)
