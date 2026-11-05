"""Port of lib/task-groups.ts: the four phases of the dashboard and their task
groups. Grouping is presentation: the stored file item codes do not change.

``short`` is the label of the panel beside a ring (the approved mock-up); the
task list keeps the full title."""

SECTION_ORDER = ("acceptance", "strategy", "execution", "conclusion")

SECTION_LABELS = {
    "acceptance": "Planification & identification des risques",
    "strategy": "Stratégie & évaluation des risques",
    "execution": "Exécution",
    "conclusion": "Conclusion & rapports",
}

SECTION_SHORT_LABELS = {
    "acceptance": "Planification",
    "strategy": "Stratégie & risques",
    "execution": "Exécution",
    "conclusion": "Conclusion",
}

_E4_MEMBERS = tuple("E4.%d" % n for n in range(1, 37)) + tuple("E5.%d" % n for n in range(1, 6))

TASK_GROUPS = (
    {"id": "p1", "code": "P1", "section": "acceptance", "title": "Acceptation & maintien", "members": ("P1.1", "P1.2", "P1.3", "P1.4", "P1.5")},
    {"id": "p2", "code": "P2", "section": "acceptance", "title": "Indépendance & équipe", "members": ("P2.1", "P2.2", "P2.3")},
    {"id": "p3", "code": "P3", "section": "acceptance", "title": "Comprendre l'activité", "members": ("P3.1", "P3.2")},
    {"id": "p4", "code": "P4", "section": "acceptance", "title": "Contrôles de l'entité & informatique", "members": ("P4.1", "P4.2", "P4.3")},
    {"id": "p5", "code": "P5", "section": "acceptance", "title": "Risques de fraude & discussion d'équipe", "members": ("P5.1", "P5.2")},
    {"id": "p6", "code": "P6", "section": "acceptance", "title": "Seuil de signification & comptes significatifs", "members": ("P6.1", "P6.2")},
    {"id": "p7", "code": "P7", "section": "acceptance", "title": "Revue & approbation de la planification", "members": ("P7.1", "P7.2")},
    {"id": "s1", "code": "S1", "section": "strategy", "title": "SCOT, flux & cheminements", "members": ("S1.1", "S1.2", "S1.3", "S1.4")},
    {"id": "s2", "code": "S2", "section": "strategy", "title": "Contrôles & informatique", "members": ("S2.1", "S2.2", "S2.3", "S2.4", "S2.5")},
    {"id": "s3", "code": "S3", "section": "strategy", "title": "Évaluation combinée des risques", "members": ("S3.1",)},
    {"id": "s4", "code": "S4", "section": "strategy", "title": "Zones de risque spécifiques", "members": ("S4.1", "S4.2", "S4.3", "S4.4")},
    {"id": "s5", "code": "S5", "section": "strategy", "title": "Conception des procédures d'audit", "members": ("S5.1", "S5.2", "S5.3", "S5.4", "S5.5", "S5.6")},
    {"id": "s6", "code": "S6", "section": "strategy", "title": "Mémorandum de stratégie d'audit", "members": ("S6.1", "S6.2")},
    {"id": "e1", "code": "E1", "section": "execution", "title": "Exécution des tests de contrôles", "short": "Tests de contrôles", "members": ("E1.1", "E1.2")},
    {"id": "e2", "code": "E2", "section": "execution", "title": "Mises à jour des contrôles", "members": ("E2.1",)},
    {"id": "e4", "code": "E4", "section": "execution", "title": "Exécution des procédures substantives", "short": "Procédures substantives", "members": _E4_MEMBERS},
    {"id": "e5", "code": "E5", "section": "execution", "title": "Procédures spécifiques (E3, E6)", "members": ("E3.1", "E6.7", "E6.2", "E6.3", "E6.1", "E6.9", "E6.6", "E6.10")},
    {"id": "e6", "code": "E6", "section": "execution", "title": "Registres, soldes d'ouverture & réévaluation", "short": "Registres, soldes d'ouverture", "members": ("E6.4", "E6.5", "E6.8")},
    {"id": "c1", "code": "C1", "section": "conclusion", "title": "Récapitulatif des écarts d'audit", "members": ("C1.1", "C1.2", "C1.3")},
    {"id": "c2", "code": "C2", "section": "conclusion", "title": "Revue finale des états financiers", "members": ("C2.1", "C2.2")},
    {"id": "c3", "code": "C3", "section": "conclusion", "title": "Déclarations", "members": ("C3.1",)},
    {"id": "c4", "code": "C4", "section": "conclusion", "title": "Revue & approbation", "members": ("C4.1", "C4.2", "C4.3")},
    {"id": "c5", "code": "C5", "section": "conclusion", "title": "Communications & rapports légaux", "members": ("C5.1", "C5.11", "C5.2", "C5.3", "C5.4", "C5.5", "C5.6", "C5.7", "C5.8", "C5.9", "C5.10")},
    {"id": "c6", "code": "C6", "section": "conclusion", "title": "Documentation & archivage", "members": ("C6.1", "C6.2")},
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
        return "Archivée"
    return SECTION_SHORT_LABELS[SECTION_OF_PHASE[phase]]
