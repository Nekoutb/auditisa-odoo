"""lib/report.ts: the opinion decision tree (ISA 700/705/706/570/701) and the statutory
report. F049: the opinion paragraph is the art. 710 certification, « Nous certifions… »;
the modified opinions keep the same base. The generated report is French."""
from .docx_builder import block

OPINIONS = ("unmodified", "qualified", "adverse", "disclaimer")

MONTHS_FR = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)

_CERTIFIED_FR = (
    "sont réguliers et sincères et donnent une image fidèle du résultat des opérations de l'exercice écoulé "
    "ainsi que de la situation financière et du patrimoine de la société à la fin de cet exercice"
)
_CERTIFIED_EN = (
    "are regular and sincere [réguliers et sincères] and give a true and fair view of the result of the operations "
    "of the period and of the financial position and assets of the company at its end"
)
_OPINION_FR = {
    "unmodified": ("Opinion", "Nous certifions que les états financiers annuels de {client} pour l'exercice clos le {end} %s, conformément au référentiel SYSCOHADA révisé." % _CERTIFIED_FR),
    "qualified": ("Opinion avec réserves", "Nous certifions que, sous réserve des points décrits dans la section « Fondement de l'opinion avec réserves », les états financiers annuels de {client} pour l'exercice clos le {end} %s." % _CERTIFIED_FR),
    "adverse": ("Opinion défavorable", "En raison de l'importance des points décrits dans la section « Fondement de l'opinion défavorable », nous certifions que les états financiers annuels de {client} pour l'exercice clos le {end} ne sont pas réguliers et sincères et ne donnent pas une image fidèle du résultat des opérations de l'exercice écoulé ainsi que de la situation financière et du patrimoine de la société à la fin de cet exercice."),
    "disclaimer": ("Impossibilité de certifier", "En raison de l'importance des points décrits dans la section « Fondement de l'impossibilité de certifier », nous ne sommes pas en mesure de certifier que les états financiers annuels de {client} pour l'exercice clos le {end} %s." % _CERTIFIED_FR),
}
_OPINION_EN = {
    "unmodified": ("Opinion", "We certify that the annual financial statements of {client} for the year ended {end} %s, in accordance with the SYSCOHADA révisé framework." % _CERTIFIED_EN),
    "qualified": ("Qualified opinion", "We certify that, except for the matters described in the “Basis for qualified opinion” section, the annual financial statements of {client} for the year ended {end} %s." % _CERTIFIED_EN),
    "adverse": ("Adverse opinion", "Because of the significance of the matters described in the “Basis for adverse opinion” section, we certify that the annual financial statements of {client} for the year ended {end} are not regular and sincere and do not give a true and fair view of the result of the operations of the period or of the financial position and assets of the company at its end."),
    "disclaimer": ("Inability to certify", "Because of the significance of the matters described in the “Basis for the inability to certify” section, we are not able to certify that the annual financial statements of {client} for the year ended {end} %s." % _CERTIFIED_EN),
}


def decide_opinion(material_misstatement=False, pervasive=False, scope_limitation=False, going_concern_uncertainty=False):
    """ISA 700/705 decision tree: (opinion, going-concern paragraph)."""
    opinion = "unmodified"
    if scope_limitation:
        opinion = "disclaimer" if pervasive else "qualified"
    elif material_misstatement:
        opinion = "adverse" if pervasive else "qualified"
    return opinion, bool(going_concern_uncertainty)


def period_end_fr(value):
    """A date as French prose: "30 juin 2026", "1er mars 2026". Never an assumed 31 December (UAT B58)."""
    if not value:
        return ""
    day = "1er" if value.day == 1 else str(value.day)
    return "%s %s %s" % (day, MONTHS_FR[value.month - 1], value.year)


def opinion_paragraph(opinion, client, period_end, locale="fr"):
    title, body = (_OPINION_FR if locale == "fr" else _OPINION_EN)[opinion]
    return title, body.format(client=client, end=period_end)


def report_blocks(opinion, client, period_end, report_date, listed=False, co_cac=False, basis=None,
                  going_concern=False, kam=None, kam_none_reason=None, disagreement=None):
    """The body of the auditor's report, between the letterhead and its footer."""
    closing = period_end_fr(period_end)
    title, body = opinion_paragraph(opinion, client, closing, "fr")
    blocks = [
        block("title", "Rapport du commissaire aux comptes sur les états financiers annuels"),
        block("b", "%s — Exercice clos le %s" % (client, closing)),
        block("h", title),
        block("p", body),
    ]
    if opinion != "unmodified" and basis:
        blocks += [block("h", "Fondement de l'%s" % title.lower()), block("p", basis)]
    if going_concern:
        blocks += [
            block("h", "Incertitude significative liée à la continuité d'exploitation"),
            block("p", "Nous attirons l'attention sur la note des états financiers décrivant les événements et conditions indiquant l'existence d'une incertitude significative susceptible de jeter un doute important sur la capacité de la société à poursuivre son exploitation. Notre opinion n'est pas modifiée à l'égard de ce point."),
        ]
    if listed and kam:
        blocks += [block("h", "Points clés de l'audit"), block("p", kam)]
    elif listed and kam_none_reason:
        # ISA 701 para 16: when there is no key audit matter to report, the report says so.
        blocks += [
            block("h", "Points clés de l'audit"),
            block("p", "Nous avons déterminé qu'il n'y a pas de points clés de l'audit à communiquer dans notre rapport. %s" % kam_none_reason),
        ]
    blocks += [
        block("h", "Vérifications et informations spécifiques"),
        block("p", "Nous avons procédé aux vérifications spécifiques prévues par les textes : concordance avec les états financiers et sincérité des informations données dans le rapport de gestion et dans les documents adressés aux associés ou actionnaires (art. 713), respect de l'égalité entre les associés ou actionnaires (art. 714), détention d'actions par les administrateurs (art. 417). Les irrégularités et inexactitudes relevées, le cas échéant, sont signalées à la plus proche assemblée générale (art. 716)."),
    ]
    if co_cac and (disagreement or "").strip():
        blocks += [block("h", "Divergence entre commissaires aux comptes (art. 719)"), block("p", disagreement)]
    dated = report_date.strftime("%d/%m/%Y")
    blocks.append(block("i", (
        "Fait le %s. Les commissaires aux comptes (rapport commun, art. 719)." if co_cac
        else "Fait le %s. Le commissaire aux comptes."
    ) % dated))
    return blocks
