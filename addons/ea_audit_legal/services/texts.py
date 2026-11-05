"""The wording and the arithmetic of lib/legal.ts, lib/alerte.ts and lib/papers/statutory-525.ts,
pure. Article numbers are written as the source writes them; ea_audit_reports.services.articles
marks each one "(à valider)" when a document or a deadline basis is produced."""
import re

from odoo.addons.ea_audit_reports.services.docx_builder import block
from odoo.addons.ea_audit_reports.services.letters import fcfa as group_digits
from odoo.addons.ea_audit_reports.services.opinion import period_end_fr
from odoo.addons.ea_audit_tools.services.legal import add_days_iso, add_months_clamped

CAPACITIES = ("director", "gerant", "shareholder10", "president", "dirigeant", "controlling")
CAPACITY_SELECTION = [
    ("director", "Director"), ("gerant", "Gérant"), ("shareholder10", "Shareholder holding 10% or more"),
    ("president", "President"), ("dirigeant", "Officer"), ("controlling", "Controlling company"),
]
CAPACITY_FR = {
    "director": "administrateur",
    "gerant": "gérant",
    "shareholder10": "actionnaire détenant ≥ 10 %",
    "president": "président",
    "dirigeant": "dirigeant",
    "controlling": "société contrôlante",
}

STAGE_LETTERS = {
    "request_sent": ("Demande d'explications (procédure d'alerte)", "Par lettre recommandée avec demande d'avis de réception, nous vous demandons des explications sur les faits de nature à compromettre la continuité de l'exploitation relevés dans le cadre de notre mission. Votre réponse est attendue dans le mois qui suit la réception de la présente (AUSCGIE, arts. 150 / 153)."),
    "court_informed": ("Information de la juridiction compétente (alerte)", "Nous informons la juridiction compétente de la teneur de la réponse reçue — ou de l'absence de réponse — à notre demande d'explications relative à la continuité de l'exploitation."),
    "board_invited": ("Invitation du conseil à délibérer (alerte)", "Faute de réponse satisfaisante dans le délai légal, nous invitons le président du conseil d'administration à faire délibérer le conseil sur les faits relevés. Le conseil doit se réunir dans le mois ; nous assisterons à la séance et un extrait du procès-verbal nous sera adressé ainsi qu'à la juridiction compétente dans le mois qui suit."),
    "rapport_special": ("Rapport spécial d'alerte", "La continuité de l'exploitation demeurant compromise, nous établissons le présent rapport spécial d'alerte, communiqué dans les conditions légales (copie à la juridiction compétente ; communication aux associés ou présentation à la prochaine assemblée générale, que nous pouvons convoquer en cas d'urgence)."),
}
STAGE_DOC_TITLES = {
    "request_sent": "demande d'explications",
    "court_informed": "information de la juridiction compétente",
    "board_invited": "invitation du conseil à délibérer",
    "rapport_special": "rapport spécial d'alerte",
}
STAGE_SELECTION = [
    ("request_sent", "Explanations requested"), ("reply_recorded", "Reply recorded"), ("court_informed", "Court informed"),
    ("board_invited", "Board invited to deliberate"), ("board_deliberated", "Board deliberated"),
    ("rapport_special", "Special report"), ("ag_communicated", "Communicated to the general meeting"), ("closed", "Closed"),
]

#: F058: ten persons above 200 employees, five at or below (threshold à valider).
ART_525_HEADCOUNT_THRESHOLD = 200
_FIGURE = re.compile(r"\d[\d\s  .]*")


def fmt_amount(value):
    """French-formatted amount: "-10 000 000", never "-10000000.000000"."""
    if value is None or value is False or value == "":
        return "—"
    return group_digits(float(value))


def amount_or_nd(value):
    return "n/d" if value is None else "%s FCFA" % fmt_amount(value)


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
        {"key": "fs_arrete", "due": add_months_clamped(period_end, 4), "basis": "AUDCIF art. 23 — FS arrêtés ≤ 4 mois"},
        {"key": "continuing_conventions_notice", "due": add_months_clamped(period_end, 1), "basis": "Art. 438 al. 2 — conventions courantes notifiées ≤ 1 mois de la clôture"},
        {"key": "ago", "due": add_months_clamped(period_end, 6), "basis": "Art. 72 — AGO ≤ 6 mois de la clôture"},
    ]
    if agm_date:
        rows += [
            {"key": "docs_to_cac", "due": add_days_iso(agm_date, -45), "basis": "Art. 71 — documents au CAC ≥ 45 jours avant l'AGO"},
            {"key": "cac_report_shareholders", "due": add_days_iso(agm_date, -15), "basis": "Rapport du CAC aux actionnaires ≥ 15 jours avant l'AGO (à défaut : rapport de carence)"},
            {"key": "rapport_special_deposit", "due": add_days_iso(agm_date, -15), "basis": "Art. 442 — dépôt du rapport spécial au siège ≥ 15 jours avant l'AGO"},
        ]
    # UAT run 2 B92. Without an AGM date the row is provisional, from the latest lawful AGO.
    rows.append({
        "key": "fs_filing_rccm",
        "due": add_months_clamped(agm_date or add_months_clamped(period_end, 6), 1),
        "basis": "Art. 269 — dépôt des états financiers au greffe (RCCM) ≤ 1 mois après leur approbation" + (
            "" if agm_date else " (provisoire : date de l'AGO non renseignée)"
        ),
    })
    if board_date:
        rows.append({"key": "art715_board", "due": board_date, "basis": "Art. 715 — rapport du CAC présenté au conseil d'arrêté des comptes"})
    if report_date:
        rows.append({"key": "file_assembly", "due": add_days_iso(report_date, 60), "basis": "ISA 230 — assemblage du dossier ≤ 60 jours du rapport"})
    if mandate_type and mandate_start_year:
        # UAT B102: the mandate runs to the meeting approving the last year's accounts,
        # not to that year's 31 December.
        expiry = mandate_expiry_year(mandate_type, mandate_start_year)
        due = agm_date if agm_date and fiscal_year == expiry else add_months_clamped("%d-12-31" % expiry, 6)
        rows.append({"key": "mandate_expiry", "due": due, "basis": "Art. 704 — expiration du mandat à l'AG statuant sur les comptes du dernier exercice (2/6 exercices)"})
    return rows


EGM_EQUITY_BASIS = "Capitaux propres < ½ capital — AGE ≤ 4 mois de l'approbation des comptes déficitaires (SA arts. 664-668 ; SARL arts. 371-373 — à valider)"


def equity_conclusion_of(breach, has_tb, half_capital, egm_done):
    """equityConclusionOf (UAT run 2 B22), driven by the live figures so it never contradicts
    them. ``egm_done``: None without an EGM row, else whether that row is done."""
    if not has_tb or half_capital is None:
        return "none"
    if breach:
        return "unchecked-breach" if egm_done is None else "breach"
    return "stale" if egm_done is False else "ok"


def signature_blocks(firm_name, partner_name, on_date):
    """UAT run 2 B94, run 3 B08: the documents carried no date and no signatory."""
    blocks = [block("p", "Fait le %s." % period_end_fr(on_date)), block("b", "Le commissaire aux comptes"), block("p", firm_name)]
    if partner_name:
        blocks.append(block("p", "%s, associé signataire" % partner_name))
    return blocks
