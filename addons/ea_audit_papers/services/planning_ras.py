"""The Planning Review & Approval Summary (lib/planning-ras.ts, gap rules of rasGaps). No Odoo import.

Section A is the preparer's confirmation that each planning deliverable exists, section B
the partner's attestations, section C the engagement quality reviewer's. The partner's
signature here is the approval the planning gate reads, not a chip on the P7.2 row.
"""
from .completeness import js_trim

SECTION_A = (
    {
        "key": "a1",
        "en": "The independence and ethics conclusion is complete for every member of the team, with the safeguards addressing any threat identified.",
        "fr": "La conclusion sur l'indépendance et l'éthique est complète pour chaque membre de l'équipe, avec les sauvegardes répondant aux menaces relevées.",
        "codes": ["P2.1"],
        "na": False,
    },
    {
        "key": "a2",
        "en": "The client acceptance or continuance decision is documented, with its risk rating.",
        "fr": "La décision d'acceptation ou de maintien du client est documentée, avec sa cotation du risque.",
        "codes": ["P1.1"],
        "na": False,
    },
    {
        "key": "a3",
        "en": "The engagement letter and terms of business are signed by management and filed.",
        "fr": "La lettre de mission et les conditions d'intervention sont signées par la direction et classées.",
        "codes": ["P1.4", "P1.3"],
        "na": False,
    },
    {
        "key": "a4",
        "en": "The entity-level control assessment and the fraud considerations are documented.",
        "fr": "L'évaluation du contrôle interne au niveau de l'entité et les considérations de fraude sont documentées.",
        "codes": ["P4.1", "P4.2", "P5.1"],
        "na": False,
    },
    {
        "key": "a5",
        "en": "The audit strategy memorandum is prepared, and the planning report to those charged with governance where one is required.",
        "fr": "Le mémorandum de stratégie d'audit est établi, ainsi que le rapport de planification aux responsables de la gouvernance le cas échéant.",
        "codes": ["S6.1", "S6.2", "P7.1"],
        "na": True,
    },
    {
        "key": "a6",
        "en": "The combined risk assessment is complete.",
        "fr": "L'évaluation combinée des risques est complète.",
        "codes": ["S3.1"],
        "na": False,
    },
    {
        "key": "a7",
        "en": "The audit programme states the nature, timing and extent of both control and substantive procedures, responds to the combined risk assessment, and answers every significant and fraud risk raised.",
        "fr": "Le programme d'audit précise la nature, le calendrier et l'étendue des tests de contrôles et des procédures substantives, répond à l'évaluation combinée des risques et couvre chaque risque important et de fraude relevé.",
        "codes": ["S2.1", "S2.2"],
        "na": False,
    },
    {
        "key": "a8",
        "en": "The engagement team assessment (Appendix 1) is complete: the team collectively has the capabilities, the competence and the time.",
        "fr": "L'évaluation de l'équipe (annexe 1) est complète : l'équipe dispose collectivement des capacités, des compétences et du temps nécessaires.",
        "codes": ["P2.2"],
        "na": False,
    },
    {
        "key": "a9",
        "en": "The initial going-concern assessment is documented (ISA 570 ¶11).",
        "fr": "L'appréciation préliminaire de la continuité d'exploitation est documentée (ISA 570 ¶11).",
        "codes": ["S4.2"],
        "na": False,
    },
    {
        "key": "a10",
        "en": "The significant accounts, disclosures and relevant assertions have been identified and scoped.",
        "fr": "Les comptes significatifs, informations à fournir et assertions pertinentes ont été identifiés et le périmètre arrêté.",
        "codes": ["P6.2", "P6.1"],
        "na": False,
    },
    {
        "key": "a11",
        "en": "Every other planning task in the file is complete to the extent it applies to this engagement.",
        "fr": "Toute autre tâche de planification du dossier est achevée dans la mesure où elle s'applique à cette mission.",
        "codes": [],
        "na": False,
    },
)

SECTION_B = (
    {
        "key": "b1",
        "en": "I have discussed Section A with the engagement team and have reviewed and approved the documents it refers to.",
        "fr": "J'ai examiné la section A avec l'équipe et revu et approuvé les documents auxquels elle renvoie.",
        "codes": [],
        "na": False,
    },
    {
        "key": "b2",
        "en": "I have considered the independence and objectivity of the team and of the firm, and appropriate safeguards are in place where needed.",
        "fr": "J'ai considéré l'indépendance et l'objectivité de l'équipe et du cabinet, et des sauvegardes appropriées sont en place si nécessaire.",
        "codes": ["P2.1"],
        "na": False,
    },
    {
        "key": "b3",
        "en": "I have reviewed the engagement team assessment and am satisfied the team collectively has the capabilities, competence and time to perform the engagement in accordance with professional standards and legal requirements.",
        "fr": "J'ai revu l'évaluation de l'équipe et je suis satisfait qu'elle dispose collectivement des capacités, compétences et du temps pour réaliser la mission conformément aux normes professionnelles et aux exigences légales.",
        "codes": ["P2.2"],
        "na": False,
    },
    {
        "key": "b4",
        "en": "I have held the engagement team discussion on the susceptibility of the financial statements to material misstatement from fraud and error, including the other key members (specialists, IT, tax) as appropriate.",
        "fr": "J'ai tenu la réunion d'équipe sur la sensibilité des états financiers aux anomalies significatives résultant de fraude ou d'erreur, en incluant les autres membres clés (spécialistes, informatique, fiscalité) selon le cas.",
        "codes": ["P5.2"],
        "na": False,
    },
    {
        "key": "b5",
        "en": "I am satisfied with the rigour of the planning process, with the analysis of the key components of audit risk, and with the adequacy of the planned responses; the significant risks discussed with those charged with governance are reflected in our documentation.",
        "fr": "Je suis satisfait de la rigueur du processus de planification, de l'analyse des composantes clés du risque d'audit et de l'adéquation des réponses prévues ; les risques importants évoqués avec les responsables de la gouvernance figurent dans notre documentation.",
        "codes": ["S3.1", "S6.1"],
        "na": False,
    },
    {
        "key": "b6",
        "en": "Where we plan to rely on IT general controls or application controls, I have considered whether the team has the expertise to test them, and involved an IT specialist where required.",
        "fr": "Lorsque nous prévoyons de nous appuyer sur les contrôles généraux informatiques ou applicatifs, j'ai considéré si l'équipe dispose de l'expertise pour les tester et impliqué un spécialiste informatique si nécessaire.",
        "codes": ["P4.3", "S2.1"],
        "na": True,
    },
    {
        "key": "b7",
        "en": "The combined risk assessment reflects the assessed risks, and for the higher-risk areas the audit strategy responds to it.",
        "fr": "L'évaluation combinée des risques reflète les risques évalués et, pour les zones à risque élevé, la stratégie d'audit y répond.",
        "codes": ["S3.1"],
        "na": False,
    },
    {
        "key": "b8",
        "en": "I have reviewed the most recent acceptance or continuance documentation, the risk rating is appropriate, and the decision to act remains appropriate.",
        "fr": "J'ai revu la documentation d'acceptation ou de maintien la plus récente, la cotation du risque est appropriée et la décision d'intervenir demeure appropriée.",
        "codes": ["P1.1"],
        "na": False,
    },
    {
        "key": "b9",
        "en": "Where necessary, all relevant matters have been brought to the attention of those charged with governance.",
        "fr": "Le cas échéant, tous les points pertinents ont été portés à la connaissance des responsables de la gouvernance.",
        "codes": ["P7.1"],
        "na": True,
    },
    {
        "key": "b10",
        "en": "I am not aware of any fact requiring disclosure to the public prosecutor (révélation des faits délictueux) that has not been dealt with as the law requires.",
        "fr": "Je n'ai connaissance d'aucun fait délictueux devant être révélé au procureur de la République qui n'aurait pas été traité selon la loi.",
        "codes": ["C5.6"],
        "na": True,
    },
    {
        "key": "b11",
        "en": "I am satisfied that the firm complies with the rotation requirements applicable to this engagement (IESBA Code and local law).",
        "fr": "Je suis satisfait que le cabinet respecte les exigences de rotation applicables à cette mission (Code IESBA et droit local).",
        "codes": [],
        "na": False,
    },
    {
        "key": "b12",
        "en": "I have considered whether an engagement quality review is required against the firm's criteria and, where it is, the reviewer has been appointed.",
        "fr": "J'ai déterminé si une revue de qualité de la mission est requise au regard des critères du cabinet et, le cas échéant, le réviseur a été désigné.",
        "codes": ["P1.5"],
        "na": False,
    },
    {
        "key": "b13",
        "en": "I have considered the effect of the OHADA Uniform Acts and other applicable legislation on the audit strategy, the presentation of the financial statements and our statutory duties, and the programme responds to it.",
        "fr": "J'ai considéré l'incidence des Actes uniformes OHADA et des autres textes applicables sur la stratégie d'audit, la présentation des états financiers et nos obligations légales, et le programme y répond.",
        "codes": ["E6.1", "C5.2"],
        "na": False,
    },
    {
        "key": "b14",
        "en": "For an initial audit: I have reviewed the acceptance documentation including the communication with the predecessor auditor and the consistency of accounting policies, and the representations made to us have been substantiated.",
        "fr": "Pour un premier exercice : j'ai revu la documentation d'acceptation, dont la communication avec l'auditeur précédent et la permanence des méthodes, et les déclarations qui nous ont été faites ont été corroborées.",
        "codes": ["P1.2", "E6.5"],
        "na": True,
    },
    {
        "key": "b15",
        "en": "For an engagement under close monitoring: I have reviewed the additional procedures planned and am satisfied they address the matters that led to the designation.",
        "fr": "Pour une mission sous surveillance renforcée : j'ai revu les procédures complémentaires prévues et je suis satisfait qu'elles couvrent les motifs de cette désignation.",
        "codes": [],
        "na": True,
    },
    {
        "key": "b16",
        "en": "I have considered the findings of the previous quality review of this engagement and of the practice, and the plan has been amended to respond to them.",
        "fr": "J'ai considéré les constats de la revue qualité précédente de cette mission et du cabinet, et le plan a été adapté en conséquence.",
        "codes": [],
        "na": True,
    },
    {
        "key": "b17",
        "en": "I am satisfied that planning is complete and that fieldwork may begin.",
        "fr": "Je suis satisfait que la planification est achevée et que les travaux sur le terrain peuvent commencer.",
        "codes": [],
        "na": False,
    },
)

SECTION_C = (
    {
        "key": "c1",
        "en": "I have discussed the completion of Section B with the engagement partner and am satisfied with that review.",
        "fr": "J'ai examiné l'achèvement de la section B avec l'associé responsable et je suis satisfait de sa revue.",
        "codes": [],
        "na": False,
    },
    {
        "key": "c2",
        "en": "I have read the audit strategy memorandum, the entity-level control assessment and the fraud considerations, and considered the key risks identified and the adequacy of the planned responses, including to the risk of fraud.",
        "fr": "J'ai lu le mémorandum de stratégie, l'évaluation du contrôle interne au niveau de l'entité et les considérations de fraude, et apprécié les risques clés et l'adéquation des réponses prévues, y compris au risque de fraude.",
        "codes": ["S6.1", "P4.1", "P5.1"],
        "na": False,
    },
    {
        "key": "c3",
        "en": "I have considered the judgements made on materiality and on the significant risks.",
        "fr": "J'ai apprécié les jugements portés sur le seuil de signification et sur les risques importants.",
        "codes": ["P6.1", "S3.1"],
        "na": False,
    },
    {
        "key": "c4",
        "en": "I have reviewed the planning communication to those charged with governance and am satisfied that all relevant matters were raised.",
        "fr": "J'ai revu la communication de planification aux responsables de la gouvernance et je suis satisfait que tous les points pertinents ont été soulevés.",
        "codes": ["P7.1"],
        "na": True,
    },
    {
        "key": "c5",
        "en": "I have carried out the planning requirements of the engagement quality review.",
        "fr": "J'ai réalisé les diligences de planification prévues par la revue de qualité de la mission.",
        "codes": ["P1.5"],
        "na": False,
    },
)

SIGNATURE_ROLES = (
    {"role": "fieldwork", "en": "Person in charge of the fieldwork", "fr": "Responsable des travaux sur le terrain", "min": "senior"},
    {"role": "manager", "en": "Audit manager", "fr": "Manager de la mission", "min": "manager"},
    {"role": "partner", "en": "Engagement partner", "fr": "Associé responsable", "min": "partner"},
    {"role": "eqr", "en": "Engagement quality reviewer", "fr": "Réviseur qualité de la mission", "min": "eqr_reviewer"},
)
ALL_ITEMS = SECTION_A + SECTION_B + SECTION_C
ITEM_KEYS = frozenset(item["key"] for item in ALL_ITEMS)
ANSWERS = frozenset({"yes", "no", "na"})


def unready_lines(answers, task_states):
    """Section A lines resting on a task nobody has started. A task absent from the file
    does not apply to it, and a line answered "na" rests on nothing (UAT run 2 B14)."""
    return [
        item["key"]
        for item in SECTION_A
        if answers.get(item["key"]) != "na"
        and any(task_states.get(code) == "not_started" for code in item["codes"])
    ]


def outstanding(answers):
    return len([item for item in ALL_ITEMS if not answers.get(item["key"])])


def ras_gaps(answers, signatures, unready, role):
    """What must be in place before a tier signs: the keys of what is missing."""
    items = SECTION_A + SECTION_B if role == "partner" else SECTION_A if role == "manager" else ()
    gaps = []
    for item in items:
        answer = answers.get(item["key"])
        if not answer:
            gaps.append(item["key"])
        elif answer == "no" and not js_trim(answers.get("%s_x" % item["key"]) or ""):
            gaps.append("%s_x" % item["key"])
    if role in ("partner", "manager") and unready:
        gaps.append("deliverables")
    if role == "partner":
        for tier in ("fieldwork", "manager"):
            if tier not in signatures:
                gaps.append("sig_%s" % tier)
    return gaps
