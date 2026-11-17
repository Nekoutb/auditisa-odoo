"""The trail stores its lines in English, as written, with a technical key in front; a reader
reads them in their language, without the key and without storage names (F086, D3).

Every line a call to _ea_log can write has an entry here: tests/test_activity_summaries.py
reads the calls in all the addons and fails on a line that has none. A line nothing recognises
(a future one, an old database) is shown as stored, without its key.
"""
import html
import re

from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate("ea_audit_core")

# "signed_off: P1.4 signed by ...": what _ea_log posts on the engagement's chatter.
KEYED_LINE = re.compile(r"^(?P<action>[a-z][a-z0-9_.\-]*): (?P<summary>.*)$", re.S)
_TAG = re.compile(r"<[^>]+>")

# Words the lines carry as stored values. A group named role, word or status goes through here.
WORDS = {
    "preparer": _lt("preparer"),
    "reviewer": _lt("reviewer"),
    "approver": _lt("reviewer"),
    "assignee": _lt("assignee"),
    "partner": _lt("partner"),
    "eqr": _lt("quality reviewer"),
    "eqr_reviewer": _lt("quality reviewer"),
    "staff": _lt("staff member"),
    "senior": _lt("senior"),
    "manager": _lt("manager"),
    "senior_manager": _lt("senior manager"),
    "director": _lt("director"),
    "valid": _lt("valid"),
    "invalid": _lt("invalid"),
    "pre_audit": _lt("pre-audit"),
    "post_audit": _lt("post-audit"),
    "prior_year": _lt("prior year"),
    "effective": _lt("effective"),
    "ineffective": _lt("ineffective"),
    "signed": _lt("signed"),
    "withdrawn": _lt("withdrawn"),
    "updated": _lt("updated"),
    "recorded": _lt("recorded"),
    "current": _lt("current edition"),
    "revised_2026": _lt("2026 revised edition"),
    "Significant": _lt("Significant"),
    "Not significant": _lt("Not significant"),
    "satisfactory": _lt("no exception"),
    "exceptions": _lt("exceptions found"),
    # What a roll-forward carried (engagement.ROLLFORWARD_KEYS)
    "scope": _lt("tasks and scope"),
    "materiality": _lt("materiality basis"),
    "scots": _lt("Transactions and controls"),
    "risks": _lt("risk register"),
    "procedures": _lt("procedure design"),
    "significance": _lt("significance decisions"),
    "comparatives": _lt("prior-year balances"),
    "permanent": _lt("permanent file documents"),
    "answers": _lt("working paper answers"),
    "evidence": _lt("all evidence"),
    # The questions of the task scope of 2026-11-17 (engagement._FACT_FIELDS) and their answers
    "consultation_needed": _lt("Was a consultation needed?"),
    "joint_auditors": _lt("Are there joint auditors?"),
    "yes": _lt("Yes"),
    "no": _lt("No"),
    "blank": _lt("not answered"),
}

# The line, in order, as lists: the translation export reads a string in a tuple after a _lt as a term.
# %(count)s of a group named "keys" is how many storage names it held:
# the reader gets a number, not c_0, eligibility, p_appoint.
_ENTRIES = (
    # Roll forward (owner's mock-up of 2026-11-16)
    [r"^Rolled forward from the (?P<year>\d+) file by (?P<name>.+)$",
     _lt("Rolled forward from the %(year)s file by %(name)s")],
    [r"^Carried forward from the (?P<year>\d+) file: (?P<roles>.+)$",
     _lt("Carried forward from the %(year)s file: %(roles)s")],
    [r"^(?P<count>\d+) evidence file\(s\) carried forward from (?P<year>\d+), to review before relying on them$",
     _lt("%(count)s evidence file(s) carried forward from %(year)s, to review before relying on them")],
    [r"^(?P<count>\d+) working paper\(s\) carried forward from (?P<year>\d+) as drafts, to update$",
     _lt("%(count)s working paper(s) carried forward from %(year)s as drafts, to update")],
    [r"^(?P<code>\S+): Prior-year document reviewed: (?P<file>.+)$",
     _lt("%(code)s: prior-year document reviewed, %(file)s")],
    [r"^Engagement partner transferred from (?P<old>.+) to (?P<new>.+) \((?P<who>.+) now (?P<role>\w+)\)$",
     _lt("Engagement partner transferred from %(old)s to %(new)s (%(who)s now %(role)s)")],
    # The task scope of 2026-11-17: facts decide whether a task applies
    [r"^Tasks brought onto the file by their facts: (?P<codes>.+)$",
     _lt("Tasks brought onto the file by their facts: %(codes)s")],
    [r"^(?P<code>\S+) brought onto the file: a document was filed under it$",
     _lt("%(code)s brought onto the file: a document was filed under it")],
    [r"^Scope question (?P<word>\w+) answered (?P<status>\w+)$",
     _lt("%(word)s answered: %(status)s")],
    [r"^Current task scope applied by (?P<name>.+), no task yet: the profile decides$",
     _lt("Current task scope applied by %(name)s, no task yet: the profile decides")],
    [r"^Current task scope applied by (?P<name>.+) \(scope (?P<old>\S+) to (?P<new>\S+)\)\. Added: (?P<added>.*)\. "
     r"Taken off, holding no work: (?P<hidden>.*)\. Kept, holding work: (?P<kept>.*)$",
     _lt("Current task scope applied by %(name)s (scope %(old)s to %(new)s). Added: %(added)s. Taken off, holding no work: %(hidden)s. Kept, holding work: %(kept)s")],
    # the controls tasks follow the reliance on controls (ea_audit_tools, 2026-11-17)
    [r"^The strategy no longer relies on controls\. Taken off the file, holding no work: (?P<hidden>.*)\. "
     r"Kept as not applicable, holding work: (?P<kept>.*)$",
     _lt("The strategy no longer relies on controls. Taken off the file, holding no work: %(hidden)s. Kept as not applicable, holding work: %(kept)s")],
    [r"^The strategy relies on controls again\. Applicable again, work kept: (?P<codes>.+)$",
     _lt("The strategy relies on controls again. Applicable again, work kept: %(codes)s")],
    [r"^Acceptance gates passed: engagement moved to planning$",
     _lt("Acceptance gates passed: engagement moved to planning")],
    [r"^Planning closed: snapshot taken, engagement moved to execution$",
     _lt("Planning closed: snapshot taken, engagement moved to execution")],
    [r"^Standards edition changed from (?P<status>\S+) to (?P<word>\S+): (?P<why>.*)$",
     _lt("Standards edition changed from %(status)s to %(word)s: %(why)s")],
    [r"^(?P<name>.+) removed from the team \((?P<role>\w+)\)$",
     _lt("%(name)s removed from the team (%(role)s)")],
    [r"^Partner sign-off delegated$", _lt("Partner sign-off delegated")],
    [r"^Partner sign-off delegation cleared$", _lt("Partner sign-off delegation cleared")],
    [r"^(?P<code>\S+) signed by (?P<name>.+) as (?P<role>\w+)$",
     _lt("%(code)s signed by %(name)s as %(role)s")],
    [r"^(?P<code>\S+) sign-off as (?P<role>\w+) removed by (?P<name>.+)$",
     _lt("%(code)s: sign-off as %(role)s removed by %(name)s")],
    [r"^(?P<count>\d+) task\(s\) assigned as (?P<role>\w+): (?P<codes>.+)$",
     _lt("%(count)s task(s) assigned as %(role)s: %(codes)s")],
    [r"^(?P<count>\d+) task\(s\) unassigned as (?P<role>\w+): (?P<codes>.+)$",
     _lt("%(count)s task(s) unassigned as %(role)s: %(codes)s")],
    [r"^(?P<code>\S+) due date set to (?P<date>\S+)$", _lt("%(code)s: due date set to %(date)s")],
    [r"^(?P<code>\S+) due date cleared$", _lt("%(code)s: due date cleared")],
    [r"^(?P<name>.+) declined the engagement: (?P<why>.*)$",
     _lt("%(name)s declined the engagement: %(why)s")],
    [r"^(?P<code>\S+) no longer marked not applicable$", _lt("%(code)s no longer marked not applicable")],
    [r"^(?P<code>\S+) marked not applicable: (?P<why>.*)$", _lt("%(code)s marked not applicable: %(why)s")],
    [r"^Review note raised on (?P<code>\S+)$", _lt("Review note raised on %(code)s")],
    [r"^Review note on (?P<code>\S+) answered$", _lt("Review note on %(code)s answered")],
    [r"^Review note on (?P<code>\S+) cleared$", _lt("Review note on %(code)s cleared")],
    [r"^(?P<code>\S+) signature\(s\) voided after the paper changed: (?P<roles>.+)$",
     _lt("%(code)s signature(s) voided after the paper changed: %(roles)s")],
    [r"^(?P<code>\S+) conclusion review cleared with the voided signature$",
     _lt("%(code)s conclusion review cleared with the voided signature")],
    [r"^(?P<code>\S+) working paper saved: (?P<keys>.+)$",
     _lt("%(code)s working paper saved: %(count)s field(s)")],
    [r"^(?P<code>\S+): answer changed$", _lt("%(code)s: answer changed")],
    [r"^(?P<code>\S+): answer cleared$", _lt("%(code)s: answer cleared")],
    [r"^P7\.2 summary: (?P<role>\w+) (?P<status>signed|withdrawn) by (?P<name>.+)$",
     _lt("P7.2 summary: %(role)s %(status)s by %(name)s")],
    [r"^PBC uploaded by the client: (?P<title>.+) \((?P<file>.+)\) sha256 (?P<hash>\w+)$",
     _lt("Requested document uploaded by the client: %(title)s (%(file)s) sha256 %(hash)s")],
    [r"^PBC uploaded: (?P<title>.+) \((?P<file>.+), sha256 (?P<hash>\w+)\)$",
     _lt("Requested document uploaded: %(title)s (%(file)s, sha256 %(hash)s)")],
    [r"^PBC chased: (?P<title>.+)$", _lt("Requested document chased: %(title)s")],
    [r"^PBC accepted: (?P<title>.+) → (?P<code>\S+)$", _lt("Requested document accepted: %(title)s → %(code)s")],
    [r"^PBC filed: (?P<title>.+) → (?P<code>\S+)$", _lt("Requested document filed: %(title)s → %(code)s")],
    [r"^PBC requested: (?P<title>.+) \((?P<count>\d+) contact\(s\)\)$",
     _lt("Document requested from the client: %(title)s (%(count)s contact(s))")],
    [r"^PBC requested: (?P<title>.+)$", _lt("Document requested from the client: %(title)s")],
    [r"^Completion record (?P<key>\S+) (?P<status>updated|recorded)$",
     _lt("Completion record %(key)s %(status)s")],
    [r"^Report issued: (?P<opinion>.+), dated (?P<date>\S+)$", _lt("Report issued: %(opinion)s, dated %(date)s")],
    [r"^(?P<code>\S+) letter generated: (?P<title>.+) \(v(?P<version>\d+)\)$",
     _lt("%(code)s letter generated: %(title)s (v%(version)s)")],
    [r"^Audit file archived and locked$", _lt("Audit file archived and locked")],
    [r"^Audit file archived and locked by (?P<name>.+)$", _lt("Audit file archived and locked by %(name)s")],
    [r"^Legal hold placed, retention expiry suspended\. Reason: (?P<why>.*)$",
     _lt("Legal hold placed, retention expiry suspended. Reason: %(why)s")],
    [r"^Legal hold released, retention expiry resumes\. Reason: (?P<why>.*)$",
     _lt("Legal hold released, retention expiry resumes. Reason: %(why)s")],
    [r"^Engagement export taken: (?P<file>.+)$", _lt("Engagement export taken: %(file)s")],
    [r"^Template (?P<file>.+) assigned to (?P<code>\S+)$", _lt("Template %(file)s assigned to %(code)s")],
    [r"^(?P<file>.+) reconciled to the trial balance: difference (?P<amount>.+)$",
     _lt("%(file)s reconciled to the trial balance: difference %(amount)s")],
    [r"^Control (?P<name>.+) tested: (?P<status>\S+)$", _lt("Control %(name)s tested: %(status)s")],
    [r"^CRA (?P<cell>\S+) reassessed: (?P<change>.+)$", _lt("Combined risk assessment %(cell)s reassessed: %(change)s")],
    [r"^CRA (?P<cell>\S+) set to not rely: control (?P<name>.+) concluded not effective$",
     _lt("Combined risk assessment %(cell)s set to Not rely: control %(name)s concluded not effective")],
    [r"^(?P<file>.+) imported \((?P<kind>.+), (?P<status>\S+), (?P<count>\d+) rows\)$",
     _lt("%(file)s imported (%(kind)s, %(status)s, %(count)s rows)")],
    [r"^(?P<file>.+): (?P<lines>\d+) lines projected, (?P<rejected>\d+) rejected$",
     _lt("%(file)s: %(lines)s lines projected, %(rejected)s rejected")],
    [r"^S5\.5 (?P<index>\S+) osp_list changed$", _lt("S5.5 %(index)s: other procedures changed")],
    [r"^S5\.5 (?P<index>\S+) (?P<code>\S+) chosen$", _lt("Procedure design %(index)s: %(code)s chosen")],
    [r"^S5\.5 (?P<index>\S+) (?P<code>\S+) removed$", _lt("Procedure design %(index)s: %(code)s removed")],
    [r"^S5\.5 (?P<index>\S+) (?P<keys>\S+) changed$", _lt("S5.5 %(index)s: design changed")],
    [r"^Procedure (?P<index>\S+) (?P<code>\S+) done: (?P<status>\S+)$",
     _lt("Substantive procedure %(index)s %(code)s done: %(status)s")],
    [r"^Procedure (?P<index>\S+) (?P<code>\S+) reopened$", _lt("Substantive procedure %(index)s %(code)s reopened")],
    [r"^Procedure (?P<index>\S+) (?P<code>\S+): (?P<count>\d+) entries selected around year end$",
     _lt("Substantive procedure %(index)s %(code)s: %(count)s entries selected around year end")],
    [r"^Procedure (?P<index>\S+) (?P<code>\S+): (?P<count>\d+) test counts drawn from the inventory listing$",
     _lt("Substantive procedure %(index)s %(code)s: %(count)s test counts drawn from the inventory listing")],
    [r"^Procedure (?P<index>\S+) (?P<code>\S+): (?P<count>\d+) additions and disposals drawn from the register$",
     _lt("Substantive procedure %(index)s %(code)s: %(count)s additions and disposals drawn from the register")],
    [r"^(?P<code>\S+): (?P<count>\d+) signature\(s\) to give again$",
     _lt("%(code)s: %(count)s signature(s) to give again")],
    [r"^ISA 265 deficiency evaluated on C5\.11: graded (?P<status>\w+), communicated in writing on (?P<date>\S+) \(was (?P<word>\w+)\)$",
     _lt("ISA 265 deficiency evaluated on C5.11: graded %(status)s, communicated in writing on %(date)s (was %(word)s)")],
    [r"^ISA 265 deficiency evaluated on C5\.11: graded (?P<status>\w+) \(was (?P<word>\w+)\)$",
     _lt("ISA 265 deficiency evaluated on C5.11: graded %(status)s (was %(word)s)")],
    [r"^Risk added during execution, approval required: (?P<title>.*)$",
     _lt("Risk added during execution, approval required: %(title)s")],
    [r"^S5\.4 selection design recorded: (?P<done>\d+) of (?P<total>\d+) lines$",
     _lt("S5.4 selection design recorded: %(done)s of %(total)s lines")],
    [r"^Materiality v(?P<version>\d+) approved$", _lt("Materiality v%(version)s approved")],
    [r"^Materiality v(?P<version>\d+): overall (?P<overall>\S+), performance (?P<performance>\S+), trivial (?P<trivial>\S+) — items computed under the prior figure need review, and the new version needs approval$",
     _lt("Materiality v%(version)s: overall %(overall)s, performance %(performance)s, clearly trivial %(trivial)s. Items computed under the prior figure need review, and the new version needs approval")],
    [r"^Materiality v(?P<version>\d+): overall (?P<overall>\S+), performance (?P<performance>\S+), trivial (?P<trivial>\S+)$",
     _lt("Materiality v%(version)s: overall %(overall)s, performance %(performance)s, clearly trivial %(trivial)s")],
    [r"^Materiality revised: (?P<up>\d+) misstatement\(s\) became reportable, (?P<down>\d+) became clearly trivial$",
     _lt("Materiality revised: %(up)s misstatement(s) became reportable, %(down)s became clearly trivial")],
    [r"^S2\.5 ITGC conclusion: (?P<status>.+)$", _lt("S2.5 IT general controls conclusion: %(status)s")],
    [r"^Presumed revenue-fraud risk rebutted: (?P<why>.*)$", _lt("Presumed revenue-fraud risk rebutted: %(why)s")],
    # Owner's ruling of 2026-11-15: the rebuttal is proposed, then approved or rejected by the partner.
    [r"^Rebuttal of the presumed revenue-fraud risk proposed by (?P<name>.+?): (?P<why>.*)$",
     _lt("Rebuttal of the presumed revenue-fraud risk proposed by %(name)s: %(why)s")],
    [r"^Rebuttal of the presumed revenue-fraud risk approved by (?P<name>.+?): (?P<why>.*)$",
     _lt("Rebuttal of the presumed revenue-fraud risk approved by %(name)s: %(why)s")],
    [r"^Rebuttal of the presumed revenue-fraud risk rejected by (?P<name>.+?): (?P<why>.*)$",
     _lt("Rebuttal of the presumed revenue-fraud risk rejected by %(name)s: %(why)s")],
    [r"^Risk linked to (?P<index>\S+) from the significant accounts: (?P<title>.*)$",
     _lt("Risk linked to %(index)s from the significant accounts: %(title)s")],
    [r"^Risk unlinked from (?P<index>\S+) on the significant accounts: (?P<title>.*)$",
     _lt("Risk unlinked from %(index)s on the significant accounts: %(title)s")],
    [r"^Tests of details on (?P<index>\S+): projected (?P<amount>.+)$",
     _lt("Tests of details on %(index)s: projected %(amount)s")],
    [r"^Sample of (?P<count>\d+) drawn from (?P<file>.+) \((?P<method>\S+), seed (?P<seed>.+)\)$",
     _lt("Sample of %(count)s drawn from %(file)s (%(method)s, seed %(seed)s)")],
    # Journal-entry and sampling worksheets (owner's mock-ups of 2026-11-16).
    [r"^Sample S-(?P<sample>\S+) concluded: errors found (?P<errors>.+), projected (?P<amount>.+)$",
     _lt("Sample S-%(sample)s concluded: errors found %(errors)s, projected %(amount)s")],
    [r"^Support (?P<file>.+) filed on journal entry (?P<entry>.+)$",
     _lt("Support %(file)s filed on journal entry %(entry)s")],
    [r"^Support (?P<file>.+) filed on sample S-(?P<sample>\S+)$",
     _lt("Support %(file)s filed on sample S-%(sample)s")],
    [r"^Support (?P<file>.+) filed on control (?P<control>.+)$",
     _lt("Support %(file)s filed on control %(control)s")],
    [r"^Journal entry (?P<entry>.+?) cleared: (?P<note>.*)$",
     _lt("Journal entry %(entry)s cleared: %(note)s")],
    [r"^Journal entry (?P<entry>.+?) marked as a problem: (?P<note>.*)$",
     _lt("Journal entry %(entry)s marked as a problem: %(note)s")],
    [r"^Journal entry (?P<entry>.+) put back to clear$",
     _lt("Journal entry %(entry)s put back to clear")],
    [r"^Substantive analytical procedure saved on (?P<index>\S+) / (?P<assertion>\S+): expected (?P<amount>.+)$",
     _lt("Substantive analytical procedure saved on %(index)s / %(assertion)s: expected %(amount)s")],
    [r"^Test-of-controls sample drawn: (?P<done>\d+) of (?P<total>\d+)$",
     _lt("Test-of-controls sample drawn: %(done)s of %(total)s")],
    [r"^Test-of-controls sample redrawn \(draw (?P<draw>\d+)\): (?P<done>\d+) of (?P<total>\d+) — (?P<why>.*)$",
     _lt("Test-of-controls sample redrawn (draw %(draw)s): %(done)s of %(total)s. %(why)s")],
    # P6.2 (owner's request of 2026-11-15): who moved an index from its status, and why.
    [r"^Significance of (?P<index>\S+) changed from (?P<status>.+?) to (?P<word>.+?) by (?P<name>.+?): (?P<why>.*)$",
     _lt("Significance of %(index)s changed from %(status)s to %(word)s by %(name)s: %(why)s")],
    [r"^Significance of (?P<index>\S+) changed from (?P<status>.+?) to (?P<word>.+?) by (?P<name>.+)$",
     _lt("Significance of %(index)s changed from %(status)s to %(word)s by %(name)s")],
    # Significant accounts (owner's mock-up of 2026-11-16): the flag thresholds of the file.
    [r"^Significant accounts: movements flagged above (?P<pct>.+?) and above (?P<amount>\d+) FCFA, set by (?P<name>.+)$",
     _lt("Significant accounts: movements flagged above %(pct)s and above %(amount)s FCFA, set by %(name)s")],
    [r"^Significant accounts: movements flagged above (?P<pct>.+?) or above (?P<amount>\d+) FCFA, set by (?P<name>.+)$",
     _lt("Significant accounts: movements flagged above %(pct)s or above %(amount)s FCFA, set by %(name)s")],
    [r"^SCOT assigned to (?P<name>.+): (?P<title>.*)$", _lt("Class of transactions assigned to %(name)s: %(title)s")],
    [r"^Trial balance imported: (?P<file>.+) \((?P<status>\w+), (?P<count>\d+) rows\)$",
     _lt("Trial balance imported: %(file)s (%(status)s, %(count)s rows)")],
    [r"^Trial balance deleted: (?P<file>.+) \((?P<status>\w+), imported on (?P<date>.+), (?P<count>\d+) rows, total debit (?P<debit>.+), total credit (?P<credit>.+)\)$",
     _lt("Trial balance deleted: %(file)s (%(status)s, imported on %(date)s, %(count)s rows, total debit %(debit)s, total credit %(credit)s)")],
    [r"^(?P<file>.+) deleted \((?P<kind>.+), (?P<status>\S+), imported on (?P<date>.+), (?P<count>\d+) rows, total (?P<amount>.+)\)$",
     _lt("%(file)s deleted (%(kind)s, %(status)s, imported on %(date)s, %(count)s rows, total %(amount)s)")],
    # As written while a refused file was still saved and a version was known by its number: the lines already stored.
    [r"^Trial balance imported \((?P<status>\w+), v(?P<version>\d+), (?P<file>.+)\) — (?P<word>\w+)$",
     _lt("Trial balance imported (%(status)s, v%(version)s, %(file)s): %(word)s")],
    [r"^(?P<file>.+) exported by (?P<name>.+)$", _lt("%(file)s exported by %(name)s")],
    # Owner, 2026-11-16: a document already in the engagement, attached here too (no new upload).
    [r"^(?P<code>\S+): Attached from (?P<source>\S+): (?P<file>.+) v(?P<version>\S+)$",
     _lt("%(code)s: existing document attached from %(source)s, %(file)s v%(version)s")],
    [r"^Finding (?P<ref>.+) reopened: (?P<reason>.+)$", _lt("Finding %(ref)s reopened: %(reason)s")],
    [r"^Adjustment of finding (?P<ref>\S+) booked on the summary of audit differences: (?P<accounts>.+) for (?P<amount>\S+)$",
     _lt("Adjustment of finding %(ref)s booked on the summary of audit differences: %(accounts)s for %(amount)s")],
    # the summary of audit differences reviewed (owner's mock-up of 2026-11-17, "wp-finding-sad")
    [r"^Adjustment of finding (?P<ref>\S+) saved and sent to the summary of audit differences, to review: (?P<accounts>.+) for (?P<amount>\S+)$",
     _lt("Adjustment of finding %(ref)s saved and sent to the summary of audit differences, to review: %(accounts)s for %(amount)s")],
    [r"^Audit difference (?P<name>.+) unposted$", _lt("Audit difference %(name)s unposted")],
    [r"^Audit difference (?P<name>.+) posted$", _lt("Audit difference %(name)s posted")],
    [r"^Review note raised on audit difference (?P<name>.+)$", _lt("Review note raised on audit difference %(name)s")],
    [r"^(?P<code>\S+): (?P<file>.+) v(?P<version>\S+)$", _lt("%(code)s: evidence uploaded, %(file)s v%(version)s")],
    [r"^(?P<code>\S+): (?P<old>.+) renamed to (?P<new>.+)$", _lt("%(code)s: evidence %(old)s renamed to %(new)s")],
    [r"^(?P<code>\S+): Deleted: (?P<file>.+) \(restorable for (?P<days>\S+) days\)$",
     _lt("%(code)s: evidence deleted, %(file)s (restorable for %(days)s days)")],
    [r"^(?P<code>\S+): Removed: (?P<file>.+)$", _lt("%(code)s: evidence removed, %(file)s")],
    [r"^(?P<code>\S+): Restored: (?P<file>.+)$", _lt("%(code)s: evidence restored, %(file)s")],
    # The completion checklist, the assembly window and the archived file (owner's mock-ups of 2026-11-16).
    [r"^Finding recorded after the report date: (?P<what>.*)\. Reason: (?P<why>.*)$", _lt("Finding recorded after the report date: %(what)s. Reason: %(why)s")],
    [r"^Misstatement recorded after the report date: (?P<what>.*)\. Reason: (?P<why>.*)$", _lt("Misstatement recorded after the report date: %(what)s. Reason: %(why)s")],
    [r"^Procedure concluded after the report date: (?P<what>.*)\. Reason: (?P<why>.*)$", _lt("Procedure concluded after the report date: %(what)s. Reason: %(why)s")],
    [r"^Archived after the assembly deadline\. Reason: (?P<why>.*)$", _lt("Archived after the assembly deadline. Reason: %(why)s")],
    [r"^Sealed copy made: (?P<count>\d+) files, fingerprint (?P<sha>\S+)$", _lt("Sealed copy made: %(count)s files, fingerprint %(sha)s")],
    [r"^Sealed copy downloaded$", _lt("Sealed copy downloaded")],
    [r"^Addendum added after archiving: (?P<why>.*)$", _lt("Addendum added after archiving: %(why)s")],
    [r"^Completion checklist signed by the partner: ready to issue$", _lt("Completion checklist signed by the partner: ready to issue")],
    [r"^Work after the report date opened\. Reason: (?P<why>.*)$", _lt("Work after the report date opened. Reason: %(why)s")],
    [r"^Work after the report date closed$", _lt("Work after the report date closed")],
    # The firm's own settings: no engagement.
    [r"^Firm sign-off policy updated$", _lt("Firm sign-off policy updated")],
    [r"^Sign-off rule of (?P<code>\S+) added$", _lt("Sign-off rule of %(code)s added")],
    [r"^Sign-off rule of (?P<code>\S+) changed$", _lt("Sign-off rule of %(code)s changed")],
    [r"^Sign-off rule of (?P<code>\S+) removed$", _lt("Sign-off rule of %(code)s removed")],
    [r"^Firm language set to (?P<language>.+)$", _lt("Firm language set to %(language)s")],
)
ENTRIES = tuple((re.compile(pattern, re.S), template) for pattern, template in _ENTRIES)

# Lines that are the record's own words: only the key says what happened.
BY_ACTION = {
    "misstatement.corrected": _lt("Misstatement corrected: %(text)s"),
    "misstatement.uncorrected": _lt("Misstatement not corrected: %(text)s"),
}


def _word(token, lang):
    label = WORDS.get(token)
    return label._translate(lang) if label else token


def _values(match, lang):
    values = dict(match.groupdict())
    for name in ("role", "word", "status"):
        if name in values:
            values[name] = _word(values[name], lang)
    if "roles" in values:
        values["roles"] = ", ".join(_word(role, lang) for role in values["roles"].split(", "))
    if "keys" in values:
        values["count"] = len(values["keys"].split(", "))
    return values


def _find(summary):
    for pattern, template in ENTRIES:
        match = pattern.match(summary)
        if match:
            return template, match
    return None, None


def is_known(action, summary):
    return action in BY_ACTION or _find(summary)[0] is not None


def translate_summary(action, summary, lang):
    """The line a reader in ``lang`` reads; as stored when nothing recognises it."""
    summary = summary or ""
    lang = lang or "en_US"
    if action in BY_ACTION:
        return BY_ACTION[action]._translate(lang) % {"text": summary}
    template, match = _find(summary)
    if not template:
        return summary
    return template._translate(lang) % _values(match, lang)


def parse_body(body):
    """(action, summary) of a chatter body written by _ea_log, or None."""
    text = html.unescape(_TAG.sub("", str(body or ""))).strip()
    match = KEYED_LINE.match(text)
    return (match["action"], match["summary"]) if match else None
