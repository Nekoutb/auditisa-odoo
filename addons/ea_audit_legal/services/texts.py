"""The wording and the arithmetic of lib/legal.ts, lib/alerte.ts and lib/papers/statutory-525.ts,
pure. Article numbers are written as the source writes them; ea_audit_reports.services.articles
marks each one for validation when a document or a deadline basis is produced."""
import re

from odoo.addons.ea_audit_reports.services.docx_builder import block
from odoo.addons.ea_audit_reports.services.letters import fcfa as group_digits
from odoo.addons.ea_audit_reports.services.opinion import period_end_text
from odoo.addons.ea_audit_tools.services.legal import add_days_iso, add_months_clamped

CAPACITIES = ("director", "gerant", "shareholder10", "president", "dirigeant", "controlling")
CAPACITY_SELECTION = [
    ("director", "Director"), ("gerant", "Gérant"), ("shareholder10", "Shareholder holding 10% or more"),
    ("president", "President"), ("dirigeant", "Officer"), ("controlling", "Controlling company"),
]
CAPACITY_EN = {
    "director": "director",
    "gerant": "manager",
    "shareholder10": "shareholder holding 10% or more",
    "president": "president",
    "dirigeant": "officer",
    "controlling": "controlling company",
}
CAPACITY_FR = {
    "director": "administrateur",
    "gerant": "gérant",
    "shareholder10": "actionnaire détenant ≥ 10 %",
    "president": "président",
    "dirigeant": "dirigeant",
    "controlling": "société contrôlante",
}

STAGE_LETTERS = {
    "request_sent": {
        "titleEn": "Request for explanations (alert procedure) (to validate)",
        "titleFr": "Demande d'explications (procédure d'alerte)",
        "bodyEn": "By registered letter with acknowledgement of receipt, we ask you for explanations of the facts likely to compromise the continuity of operations identified in the course of our engagement. Your reply is expected within one month of receipt of this letter (OHADA Uniform Act on commercial companies, arts. 150 / 153).",
        "bodyFr": "Par lettre recommandée avec demande d'avis de réception, nous vous demandons des explications sur les faits de nature à compromettre la continuité de l'exploitation relevés dans le cadre de notre mission. Votre réponse est attendue dans le mois qui suit la réception de la présente (AUSCGIE, arts. 150 / 153).",
    },
    "court_informed": {
        "titleEn": "Notice to the competent court (alert) (to validate)",
        "titleFr": "Information de la juridiction compétente (alerte)",
        "bodyEn": "We inform the competent court of the content of the reply received — or of the absence of a reply — to our request for explanations about the continuity of operations.",
        "bodyFr": "Nous informons la juridiction compétente de la teneur de la réponse reçue — ou de l'absence de réponse — à notre demande d'explications relative à la continuité de l'exploitation.",
    },
    "board_invited": {
        "titleEn": "Invitation to the board to deliberate (alert) (to validate)",
        "titleFr": "Invitation du conseil à délibérer (alerte)",
        "bodyEn": "In the absence of a satisfactory reply within the legal time limit, we invite the chairman of the board of directors to have the board deliberate on the facts noted. The board must meet within one month; we will attend the meeting and an extract of the minutes will be sent to us and to the competent court within the following month.",
        "bodyFr": "Faute de réponse satisfaisante dans le délai légal, nous invitons le président du conseil d'administration à faire délibérer le conseil sur les faits relevés. Le conseil doit se réunir dans le mois ; nous assisterons à la séance et un extrait du procès-verbal nous sera adressé ainsi qu'à la juridiction compétente dans le mois qui suit.",
    },
    "rapport_special": {
        "titleEn": "Special alert report (to validate)",
        "titleFr": "Rapport spécial d'alerte",
        "bodyEn": "As the continuity of operations remains compromised, we prepare this special alert report, communicated under the legal conditions (copy to the competent court; communication to the members or presentation to the next general meeting, which we may convene in an emergency).",
        "bodyFr": "La continuité de l'exploitation demeurant compromise, nous établissons le présent rapport spécial d'alerte, communiqué dans les conditions légales (copie à la juridiction compétente ; communication aux associés ou présentation à la prochaine assemblée générale, que nous pouvons convoquer en cas d'urgence).",
    },
}
STAGE_DOC_TITLES_FR = {
    "request_sent": "demande d'explications",
    "court_informed": "information de la juridiction compétente",
    "board_invited": "invitation du conseil à délibérer",
    "rapport_special": "rapport spécial d'alerte",
}
STAGE_DOC_TITLES_EN = {
    "request_sent": "request for explanations",
    "court_informed": "notice to the competent court",
    "board_invited": "invitation to the board to deliberate",
    "rapport_special": "special alert report",
}
STAGE_SELECTION = [
    ("request_sent", "Explanations requested"), ("reply_recorded", "Reply recorded"), ("court_informed", "Court informed"),
    ("board_invited", "Board invited to deliberate"), ("board_deliberated", "Board deliberated"),
    ("rapport_special", "Special report"), ("ag_communicated", "Communicated to the general meeting"), ("closed", "Closed"),
]

#: F058: ten persons above 200 employees, five at or below (threshold to validate).
ART_525_HEADCOUNT_THRESHOLD = 200
_FIGURE = re.compile(r"\d[\d\s  .]*")


def fmt_amount(value, fr=True):
    """Grouped as the language groups: "-10 000 000", "-10,000,000", never "-10000000.000000"."""
    if value is None or value is False or value == "":
        return "—"
    return group_digits(float(value), fr)


def amount_or_nd(value, fr=True):
    if value is None:
        return "n/d" if fr else "n/a"
    return "%s FCFA" % fmt_amount(value, fr)


def headcount_figure(headcount):
    match = _FIGURE.search(headcount or "")
    if not match:
        return None
    digits = re.sub(r"[\s  .]", "", match.group(0))
    return int(digits) if digits else None


def persons_from_headcount(headcount):
    figure = headcount_figure(headcount)
    if figure is None:
        return None
    return "ten" if figure > ART_525_HEADCOUNT_THRESHOLD else "five"


def deadline_rows(period_end, agm_date, report_date, board_date, mandate_type, mandate_start_year, fiscal_year, mandate_expiry_year):
    """generateDeadlines: [{key, due, basis}], dates in ISO, the calendar of C5.2."""
    rows = [
        {"key": "fs_arrete", "due": add_months_clamped(period_end, 4), "basisFr": "AUDCIF art. 23 — FS arrêtés ≤ 4 mois", "basisEn": "AUDCIF art. 23 — financial statements approved by the board within 4 months"},
        {"key": "continuing_conventions_notice", "due": add_months_clamped(period_end, 1), "basisFr": "Art. 438 al. 2 — conventions courantes notifiées ≤ 1 mois de la clôture", "basisEn": "Art. 438 para. 2 — ordinary agreements notified within 1 month of period end"},
        {"key": "ago", "due": add_months_clamped(period_end, 6), "basisFr": "Art. 72 — AGO ≤ 6 mois de la clôture", "basisEn": "Art. 72 — ordinary general meeting within 6 months of period end"},
    ]
    if agm_date:
        rows += [
            {"key": "docs_to_cac", "due": add_days_iso(agm_date, -45), "basisFr": "Art. 71 — documents au CAC ≥ 45 jours avant l'AGO", "basisEn": "Art. 71 — documents to the statutory auditor at least 45 days before the general meeting"},
            {"key": "cac_report_shareholders", "due": add_days_iso(agm_date, -15), "basisFr": "Rapport du CAC aux actionnaires ≥ 15 jours avant l'AGO (à défaut : rapport de carence)", "basisEn": "Statutory auditor's report to the shareholders at least 15 days before the general meeting (failing that: report of default)"},
            {"key": "rapport_special_deposit", "due": add_days_iso(agm_date, -15), "basisFr": "Art. 442 — dépôt du rapport spécial au siège ≥ 15 jours avant l'AGO", "basisEn": "Art. 442 — special report filed at the registered office at least 15 days before the general meeting"},
        ]
    # UAT run 2 B92. Without an AGM date the row is provisional, from the latest lawful AGO.
    rows.append({
        "key": "fs_filing_rccm",
        "due": add_months_clamped(agm_date or add_months_clamped(period_end, 6), 1),
        "basisFr": "Art. 269 — dépôt des états financiers au greffe (RCCM) ≤ 1 mois après leur approbation" + (
            "" if agm_date else " (provisoire : date de l'AGO non renseignée)"  # i18n: input
        ),
        "basisEn": "Art. 269 — financial statements filed at the trade register within 1 month of approval" + (
            "" if agm_date else " (provisional: general meeting date not entered)"
        ),
    })
    if board_date:
        rows.append({"key": "art715_board", "due": board_date, "basisFr": "Art. 715 — rapport du CAC présenté au conseil d'arrêté des comptes", "basisEn": "Art. 715 — statutory auditor's report presented to the board approving the accounts"})
    if report_date:
        rows.append({"key": "file_assembly", "due": add_days_iso(report_date, 60), "basisFr": "ISA 230 — assemblage du dossier ≤ 60 jours du rapport", "basisEn": "ISA 230 — file assembly within 60 days of the report"})
    if mandate_type and mandate_start_year:
        # UAT B102: the mandate runs to the meeting approving the last year's accounts,
        # not to that year's 31 December.
        expiry = mandate_expiry_year(mandate_type, mandate_start_year)
        due = agm_date if agm_date and fiscal_year == expiry else add_months_clamped("%d-12-31" % expiry, 6)
        rows.append({"key": "mandate_expiry", "due": due, "basisFr": "Art. 704 — expiration du mandat à l'AG statuant sur les comptes du dernier exercice (2/6 exercices)", "basisEn": "Art. 704 — mandate expires at the general meeting ruling on the accounts of the last year (2/6 years)"})
    return rows


EGM_EQUITY_BASIS = "Equity below half the capital — extraordinary general meeting within 4 months of approval of the loss-making accounts (SA arts. 664-668; SARL arts. 371-373 — to validate)"
EGM_EQUITY_BASIS_FR = "Capitaux propres < ½ capital — AGE ≤ 4 mois de l'approbation des comptes déficitaires (SA arts. 664-668 ; SARL arts. 371-373 — à valider)"


def equity_conclusion_of(breach, has_tb, half_capital, egm_done):
    """equityConclusionOf (UAT run 2 B22), driven by the live figures so it never contradicts
    them. ``egm_done``: None without an EGM row, else whether that row is done."""
    if not has_tb or half_capital is None:
        return "none"
    if breach:
        return "unchecked-breach" if egm_done is None else "breach"
    return "stale" if egm_done is False else "ok"


def signature_blocks(firm_name, partner_name, on_date, fr=True):
    """UAT run 2 B94, run 3 B08: the documents carried no date and no signatory."""
    blocks = [
        block("p", ("Fait le %s." if fr else "Done on %s.") % period_end_text(on_date, fr)),
        block("b", "Le commissaire aux comptes" if fr else "The statutory auditor"),
        block("p", firm_name),
    ]
    if partner_name:
        blocks.append(block("p", ("%s, associé signataire" if fr else "%s, signing partner") % partner_name))
    return blocks
