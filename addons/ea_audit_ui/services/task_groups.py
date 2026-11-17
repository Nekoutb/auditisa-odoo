"""Port of lib/task-groups.ts: the four phases of the dashboard and their task
groups. Grouping is presentation: the stored file item codes do not change.

``short`` is the label of the panel beside a ring (the approved mock-up); the
task list keeps the full title."""


def _lt(text):
    """Marks an English source for fr.po; the model layer translates it with env._."""
    return text


E3_MERGED_NOTE = _lt("Group E3 was merged into group E5: E3.1 sits there under its original code.")

SECTION_ORDER = ("acceptance", "strategy", "execution", "conclusion")

SECTION_LABELS = {
    "acceptance": _lt("Planning and Risk Identification"),
    "strategy": _lt("Strategy and Risk Assessment"),
    "execution": _lt("Execution"),
    "conclusion": _lt("Conclusion and Reporting"),
}

SECTION_SHORT_LABELS = {
    "acceptance": _lt("Planning"),
    "strategy": _lt("Strategy and risks"),
    "execution": _lt("Execution"),
    "conclusion": _lt("Conclusion"),
}

_E4_MEMBERS = tuple("E4.%d" % n for n in range(1, 37)) + tuple("E5.%d" % n for n in range(1, 6))

TASK_GROUPS = (
    {"id": "p1", "code": "P1", "section": "acceptance", "title": _lt("Acceptance and continuance"), "members": ("P1.1", "P1.2", "P1.3", "P1.4", "P1.5")},
    {"id": "p2", "code": "P2", "section": "acceptance", "title": _lt("Independence and team"), "members": ("P2.1", "P2.2", "P2.3")},
    {"id": "p3", "code": "P3", "section": "acceptance", "title": _lt("Understanding the business"), "members": ("P3.1", "P3.2")},
    {"id": "p4", "code": "P4", "section": "acceptance", "title": _lt("Entity-level controls and IT"), "members": ("P4.1", "P4.2", "P4.3")},
    {"id": "p5", "code": "P5", "section": "acceptance", "title": _lt("Fraud risks and team discussion"), "members": ("P5.1", "P5.2")},
    {"id": "p6", "code": "P6", "section": "acceptance", "title": _lt("Materiality and significant accounts"), "members": ("P6.1", "P6.2")},
    {"id": "p7", "code": "P7", "section": "acceptance", "title": _lt("Planning review and approval"), "members": ("P7.1", "P7.2")},
    {"id": "s1", "code": "S1", "section": "strategy", "title": _lt("Transactions, flows and walkthroughs"), "members": ("S1.1", "S1.2", "S1.3", "S1.4")},
    {"id": "s2", "code": "S2", "section": "strategy", "title": _lt("Controls and IT"), "members": ("S2.1", "S2.2", "S2.3", "S2.4", "S2.5")},
    {"id": "s3", "code": "S3", "section": "strategy", "title": _lt("Combined risk assessment"), "members": ("S3.1",)},
    {"id": "s4", "code": "S4", "section": "strategy", "title": _lt("Specific risk areas"), "members": ("S4.1", "S4.2", "S4.3", "S4.4")},
    {"id": "s5", "code": "S5", "section": "strategy", "title": _lt("Audit procedure design"), "members": ("S5.1", "S5.2", "S5.3", "S5.4", "S5.5", "S5.6")},
    {"id": "s6", "code": "S6", "section": "strategy", "title": _lt("Audit strategy memorandum"), "members": ("S6.1", "S6.2")},
    {"id": "e1", "code": "E1", "section": "execution", "title": _lt("Execution of tests of controls"), "short": _lt("Tests of controls"), "members": ("E1.1", "E1.2")},
    {"id": "e2", "code": "E2", "section": "execution", "title": _lt("Control updates"), "members": ("E2.1",)},
    {"id": "e4", "code": "E4", "section": "execution", "title": _lt("Execution of substantive procedures"), "short": _lt("Substantive procedures"), "members": _E4_MEMBERS},
    {"id": "e5", "code": "E5", "section": "execution", "title": _lt("Specific procedures (E3, E6)"), "members": ("E3.1", "E6.7", "E6.2", "E6.3", "E6.1", "E6.9", "E6.6", "E6.10")},
    {"id": "e6", "code": "E6", "section": "execution", "title": _lt("Registers, opening balances and revaluation"), "short": _lt("Registers, opening balances"), "members": ("E6.4", "E6.5", "E6.8")},
    {"id": "c1", "code": "C1", "section": "conclusion", "title": _lt("Summary of audit differences"), "members": ("C1.1", "C1.2", "C1.3")},
    {"id": "c2", "code": "C2", "section": "conclusion", "title": _lt("Final review of the financial statements"), "members": ("C2.1", "C2.2")},
    {"id": "c3", "code": "C3", "section": "conclusion", "title": _lt("Representations"), "members": ("C3.1",)},
    {"id": "c4", "code": "C4", "section": "conclusion", "title": _lt("Review and approval"), "members": ("C4.1", "C4.2", "C4.3")},
    # The reports the law asks of the statutory auditor, kept as separate tasks under one heading
    # (owner's table of 2026-11-17): the opinion, the special report, the art. 715 report, art. 525.
    {"id": "c5r", "code": "C5", "section": "conclusion", "title": _lt("Statutory reports"), "members": ("C5.1", "C5.3", "C5.4", "C5.10")},
    {"id": "c5", "code": "C5", "section": "conclusion", "title": _lt("Communications and legal procedures"), "members": ("C5.11", "C5.2", "C5.5", "C5.6", "C5.7", "C5.8", "C5.9")},
    {"id": "c6", "code": "C6", "section": "conclusion", "title": _lt("Documentation and archiving"), "members": ("C6.1", "C6.2")},
)

GROUP_BY_ID = {group["id"]: group for group in TASK_GROUPS}
_GROUP_OF_CODE = {code: group for group in TASK_GROUPS for code in group["members"]}

# Which ring belongs to an engagement's phase.
SECTION_OF_PHASE = {
    "acceptance": "acceptance",
    "planning": "strategy",
    "execution": "execution",
    "conclusion": "conclusion",
    "archived": "conclusion",
}


def group_of_code(code):
    """The group of a task code. A code missing from the lists resolves by its
    prefix (P6.2 belongs to P6), as groupOfTask does; None outside the framework."""
    group = _GROUP_OF_CODE.get(code)
    if group:
        return group
    prefix = (code or "").split(".")[0]
    return next((g for g in TASK_GROUPS if g["code"] == prefix), None)


def groups_of_section(section):
    return [group for group in TASK_GROUPS if group["section"] == section]


def phase_label(phase):
    """The word for an engagement's phase on every screen."""
    if phase == "archived":
        return _lt("Archived")
    return SECTION_SHORT_LABELS[SECTION_OF_PHASE[phase]]
