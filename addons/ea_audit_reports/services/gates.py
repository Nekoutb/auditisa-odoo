"""The labels and the grouping of lib/archive-checklist.ts, and the gates a nature waives
(lib/file-index.ts, F075)."""

_LIMITED_REVIEW_WAIVED = {"fs_tieout_passed", "disclosure_checklist"}
_WAIVED = {
    "limited_review": _LIMITED_REVIEW_WAIVED,
    "commissariat_apports": _LIMITED_REVIEW_WAIVED | {"b5_within_materiality", "final_analytical_review", "subsequent_events"},
}

CODE_CAP = 20


def gate_applies_to_nature(key, nature):
    return key not in _WAIVED.get(nature or "", ())


GATE_LABELS = {
    "report_issued": ("Report issued and dated", "Rapport émis et daté"),
    "sections_concluded": ("Every worked E-section concluded and reviewed; no program step left planned", "Chaque section E travaillée conclue et revue ; aucune diligence laissée planifiée"),
    "risks_concluded": ("Every risk concluded, or validly rebutted; mid-audit additions partner-approved", "Chaque risque conclu, ou valablement réfuté ; ajouts en cours de mission approuvés par l'associé"),
    "b5_within_materiality": ("Uncorrected misstatements within final materiality", "Anomalies non corrigées dans le seuil de signification final"),
    "final_analytical_review": ("Final analytical review performed (C2.1)", "Revue analytique finale réalisée (C2.1)"),
    "fs_tieout_passed": ("Financial statement tie-out passed", "Rapprochement des états financiers concluant"),
    "disclosure_checklist": ("Disclosure checklist completed", "Contrôle des informations à fournir complété"),
    "subsequent_events": ("Subsequent events reviewed to the report date", "Événements postérieurs revus jusqu'à la date du rapport"),
    "rep_letters_generated": ("Both representation letters generated (C3.1)", "Les deux lettres d'affirmation générées (C3.1)"),
    "b4_cleared": ("Every significant matter in C1.2 cleared", "Chaque point significatif de C1.2 levé"),
    "partner_conclusion": ("Partner overall conclusion (C4.1)", "Conclusion générale de l'associé (C4.1)"),
    "completion_gates": ("Every completion gate green", "Toutes les portes d'achèvement au vert"),
    "controls_concluded": ("Every control selected for testing designed, tested and concluded", "Chaque contrôle retenu pour test conçu, testé et conclu"),
    "deficiencies_communicated": ("Every significant deficiency communicated in writing to those charged with governance (C5.11, ISA 265 ¶9)", "Chaque déficience significative communiquée par écrit aux responsables de la gouvernance (C5.11, ISA 265 ¶9)"),
    "eqr_complete": ("Engagement quality review complete where required (C4.2, ISQM 2 ¶25)", "Revue de qualité de la mission achevée lorsqu'elle est requise (C4.2, ISQM 2 ¶25)"),
    "c43_cleared": ("No point outstanding at the report date (C4.3)", "Aucun point en suspens à la date du rapport (C4.3)"),
    "tasks_addressed": ("Every applicable task performed, or marked not applicable with a reason", "Chaque tâche applicable réalisée, ou marquée non applicable avec un motif"),
    "papers_signed": ("Every task holding work has a paper signed by its preparer", "Chaque tâche portant des travaux a un papier signé par son préparateur"),
    "reviews_complete": ("Every prepared paper carries its review sign-off", "Chaque papier préparé porte sa signature de revue"),
    "review_notes_cleared": ("Every review note cleared", "Chaque note de revue levée"),
    "review_approval": ("Review and approval summary concluded (C4.1)", "Récapitulatif de revue et d'approbation conclu (C4.1)"),
    "c62_checklist": ("Documentation and archive checklist concluded (C6.2)", "Liste de documentation et d'archivage conclue (C6.2)"),
    "checklist_signed": ("Completion checklist signed by the partner: ready to issue (C6.1)", "Liste d'achèvement signée par l'associé : prêt à émettre (C6.1)"),
    "assembly_confirmed": ("Signed documents filed and permanent file updated (C6.2)", "Documents signés classés et dossier permanent mis à jour (C6.2)"),
    "ready_to_issue": ("Completion checklist signed by the partner: ready to issue (C6.1)", "Liste d'achèvement signée par l'associé : prêt à émettre (C6.1)"),
}

GROUP_OF = {
    "report_issued": "report",
    "tasks_addressed": "papers", "papers_signed": "papers", "reviews_complete": "papers",
    "eqr_complete": "review", "review_notes_cleared": "review", "review_approval": "review",
    "c62_checklist": "assembly", "checklist_signed": "assembly", "assembly_confirmed": "assembly",
}

GROUPS = (
    ("report", "The report", "Le rapport"),
    ("completion", "Completion of the work", "Achèvement des travaux"),
    ("papers", "Working papers prepared and reviewed", "Papiers de travail préparés et revus"),
    ("review", "Review", "Revue"),
    ("assembly", "Assembly and archive", "Assemblage et archivage"),
)


def gate_label(key, fr):
    pair = GATE_LABELS.get(key)
    return (pair[1] if fr else pair[0]) if pair else key
