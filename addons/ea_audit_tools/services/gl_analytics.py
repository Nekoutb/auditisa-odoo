"""lib/gl-analytics.ts: the thirty declared analytics, without the database.

The SQL lives in models/gl_console.py. Here: the catalogue, the clamps on each knob, and what
turns the query rows into the source's result shape. Bodies take ``results``, a dict of the
named queries' rows (plain dicts), and keep the source's camelCase.

Wording rule: a result is an EXCEPTION or a RISK INDICATOR REQUIRING AUDIT CONSIDERATION, never
fraud, an error or a misstatement.
Amount convention: signed = debit - credit.
"""
import math
import re

from ._js import is_number, js_number_str, js_round, js_sorted, js_str, js_sum, js_trim
from .gl_line import TOLERANCE, mapped_fields

UNAVAILABLE_EN = "Unavailable — required field not mapped"
UNAVAILABLE_FR = "Indisponible — champ requis non mappé"
NOT_BUILT_EN = "Declared but not computed in this release"
NOT_BUILT_FR = "Déclarée mais non calculée dans cette version"

ANALYTICS = [
    {
        "id": 1, "key": "ledger-reconciliation", "category": "integrity",
        "titleEn": "Ledger reconciliation", "titleFr": "Rapprochement du grand livre",
        "objectiveEn": "Confirm the ledger is internally coherent: total debits equal total credits, month by month and in total.",
        "objectiveFr": "Confirmer la cohérence interne du grand livre : total des débits égal au total des crédits, mois par mois et au total.",
        "assertions": ["C", "A"], "requiredFields": ["account", "amount", "journalDate"],
        "exceptionEn": "A month whose debits and credits do not agree.",
        "exceptionFr": "Un mois dont les débits et les crédits ne concordent pas.",
    },
    {
        "id": 2, "key": "unbalanced-entries", "category": "integrity",
        "titleEn": "Unbalanced journal entries", "titleFr": "Écritures déséquilibrées",
        "objectiveEn": "Identify journal entries whose lines do not net to nil, which double-entry posting should make impossible.",
        "objectiveFr": "Identifier les écritures dont les lignes ne se soldent pas à zéro, ce que la partie double devrait rendre impossible.",
        "assertions": ["C", "A"], "requiredFields": ["jeNumber", "amount", "journalDate"],
        "exceptionEn": "A journal entry with a non-nil net balance.",
        "exceptionFr": "Une écriture dont le solde net n'est pas nul.",
    },
    {
        "id": 3, "key": "exact-duplicates", "category": "integrity",
        "titleEn": "Exact duplicate lines", "titleFr": "Lignes en double exact",
        "objectiveEn": "Detect ledger lines repeated identically on account, entry, date, reference, amount and description.",
        "objectiveFr": "Détecter les lignes répétées à l'identique sur le compte, l'écriture, la date, la référence, le montant et le libellé.",
        "assertions": ["E", "A"], "requiredFields": ["account", "jeNumber", "amount", "journalDate"],
        "exceptionEn": "Each repeat beyond the first occurrence of an identical line.",
        "exceptionFr": "Chaque répétition au-delà de la première occurrence d'une ligne identique.",
    },
    {
        "id": 4, "key": "near-duplicates", "category": "integrity",
        "titleEn": "Near-duplicate entries", "titleFr": "Écritures quasi identiques",
        "objectiveEn": "Detect entries repeating the same counterparty and amount under a different reference or date.",
        "objectiveFr": "Détecter les écritures répétant le même tiers et le même montant sous une référence ou une date différente.",
        "assertions": ["E", "A"], "requiredFields": ["account", "reference", "amount", "thirdPartyCode"],
        "exceptionEn": "A pair of entries matching on amount and counterparty but not on reference.",
        "exceptionFr": "Un couple d'écritures concordant sur le montant et le tiers mais pas sur la référence.",
        "unavailableEn": NOT_BUILT_EN, "unavailableFr": NOT_BUILT_FR,
    },
    {
        "id": 5, "key": "zero-value", "category": "integrity",
        "titleEn": "Nil-value lines", "titleFr": "Lignes de valeur nulle",
        "objectiveEn": "Isolate lines posted with neither a debit nor a credit, which carry no accounting effect.",
        "objectiveFr": "Isoler les lignes comptabilisées sans débit ni crédit, sans effet comptable.",
        "assertions": ["E"], "requiredFields": ["amount", "journalDate"],
        "exceptionEn": "A line whose debit and credit are both nil.",
        "exceptionFr": "Une ligne dont le débit et le crédit sont tous deux nuls.",
    },
    {
        "id": 6, "key": "invalid-debit-credit", "category": "integrity",
        "titleEn": "Invalid debit/credit presentation", "titleFr": "Présentation débit/crédit invalide",
        "objectiveEn": "Find lines carrying a debit and a credit at once, or a negative value on either side, instead of one positive side.",
        "objectiveFr": "Repérer les lignes portant à la fois un débit et un crédit, ou une valeur négative d'un côté, au lieu d'un seul côté positif.",
        "assertions": ["A"], "requiredFields": ["debit", "credit", "journalDate"],
        "exceptionEn": "A line with both sides populated, or a negative debit or credit.",
        "exceptionFr": "Une ligne dont les deux côtés sont servis, ou un débit ou crédit négatif.",
    },
    {
        "id": 7, "key": "weekend-postings", "category": "timing",
        "titleEn": "Weekend and weekday profile", "titleFr": "Profil des jours de la semaine",
        "objectiveEn": "Profile postings by day of the week and measure the share dated on a Saturday or Sunday.",
        "objectiveFr": "Profiler les comptabilisations par jour de la semaine et mesurer la part datée du samedi ou du dimanche.",
        "assertions": ["E", "P"], "requiredFields": ["journalDate"],
        "exceptionEn": "A line dated on a Saturday or Sunday.",
        "exceptionFr": "Une ligne datée d'un samedi ou d'un dimanche.",
    },
    {
        "id": 8, "key": "entry-date-lag", "category": "timing",
        "titleEn": "Entry date lag", "titleFr": "Décalage de la date de saisie",
        "objectiveEn": "Measure the delay between the effective journal date of an entry and the date it was actually recorded.",
        "objectiveFr": "Mesurer le délai entre la date d'effet de l'écriture et sa date de saisie effective.",
        "assertions": ["C", "E"], "requiredFields": ["jeNumber", "journalDate", "jeDate"],
        "exceptionEn": "An entry recorded more than three days after its journal date, or before it.",
        "exceptionFr": "Une écriture saisie plus de trois jours après sa date de journal, ou avant celle-ci.",
    },
    {
        "id": 9, "key": "year-end-concentration", "category": "timing",
        "titleEn": "Year-end concentration", "titleFr": "Concentration de fin d'exercice",
        "objectiveEn": "Show how ledger value is spread across the year and how much of it lands in the closing days of the period.",
        "objectiveFr": "Montrer la répartition de la valeur sur l'exercice et la part comptabilisée dans les derniers jours de la période.",
        "assertions": ["C", "E"], "requiredFields": ["amount", "journalDate"],
        "exceptionEn": "A line dated inside the closing window of the period.",
        "exceptionFr": "Une ligne datée dans la fenêtre de clôture de la période.",
    },
    {
        "id": 10, "key": "monthly-spikes", "category": "pattern",
        "titleEn": "Monthly volume spikes", "titleFr": "Pics d'activité mensuels",
        "objectiveEn": "Flag months whose posted value exceeds the mean of all months by more than the chosen number of standard deviations.",
        "objectiveFr": "Signaler les mois dont la valeur comptabilisée dépasse la moyenne de plus du nombre d'écarts-types retenu.",
        "assertions": ["C", "E"], "requiredFields": ["amount", "journalDate"],
        "exceptionEn": "A month above the mean-plus-n-standard-deviations threshold.",
        "exceptionFr": "Un mois au-dessus du seuil moyenne plus n écarts-types.",
    },
    {
        "id": 11, "key": "top-value", "category": "value",
        "titleEn": "Highest-value lines", "titleFr": "Lignes de plus forte valeur",
        "objectiveEn": "Isolate the largest postings in the ledger by absolute amount, above a percentile cut of the population.",
        "objectiveFr": "Isoler les comptabilisations les plus élevées en valeur absolue, au-delà d'un centile de la population.",
        "assertions": ["V", "A"], "requiredFields": ["amount", "journalDate"],
        "exceptionEn": "A line at or above the percentile threshold.",
        "exceptionFr": "Une ligne égale ou supérieure au seuil de centile.",
    },
    {
        "id": 12, "key": "round-numbers", "category": "pattern",
        "titleEn": "Round-amount postings", "titleFr": "Montants ronds",
        "objectiveEn": "Isolate large postings that are exact multiples of a round base, a pattern more typical of estimates than of transactions.",
        "objectiveFr": "Isoler les comptabilisations élevées correspondant à des multiples exacts d'une base ronde, plus typiques d'estimations que de transactions.",
        "assertions": ["V", "A"], "requiredFields": ["amount", "journalDate"],
        "exceptionEn": "A line at or above the floor and an exact multiple of the round base.",
        "exceptionFr": "Une ligne atteignant le plancher et multiple exact de la base ronde.",
    },
    {
        "id": 13, "key": "benford", "category": "pattern",
        "titleEn": "Benford first-digit profile", "titleFr": "Profil de Benford (premier chiffre)",
        "objectiveEn": "Compare the distribution of leading digits with Benford's law and report the mean absolute deviation per month.",
        "objectiveFr": "Comparer la distribution des premiers chiffres à la loi de Benford et reporter l'écart absolu moyen par mois.",
        "assertions": ["A", "V"], "requiredFields": ["amount", "journalDate"],
        "exceptionEn": "A month whose mean absolute deviation exceeds 1.5 percentage points.",
        "exceptionFr": "Un mois dont l'écart absolu moyen dépasse 1,5 point de pourcentage.",
    },
    {
        "id": 14, "key": "repeated-amounts", "category": "pattern",
        "titleEn": "Repeated amounts", "titleFr": "Montants répétés",
        "objectiveEn": "Identify amounts posted many times over the year and show where in the year they cluster.",
        "objectiveFr": "Identifier les montants comptabilisés de nombreuses fois dans l'année et montrer leur regroupement.",
        "assertions": ["A", "V"], "requiredFields": ["amount", "journalDate"],
        "exceptionEn": "A line whose amount recurs at or above the occurrence threshold.",
        "exceptionFr": "Une ligne dont le montant se répète au moins au seuil d'occurrences.",
    },
    {
        "id": 15, "key": "rare-accounts", "category": "pattern",
        "titleEn": "Rarely used accounts", "titleFr": "Comptes rarement utilisés",
        "objectiveEn": "Surface accounts posted to only a handful of times in the year, whose few movements carry disproportionate weight.",
        "objectiveFr": "Faire ressortir les comptes mouvementés seulement quelques fois dans l'année, dont les rares mouvements pèsent d'autant plus.",
        "assertions": ["E", "A"], "requiredFields": ["account", "journalDate"],
        "exceptionEn": "A line posted to an account used at most the threshold number of times.",
        "exceptionFr": "Une ligne imputée à un compte utilisé au plus le nombre de fois du seuil.",
    },
    {
        "id": 16, "key": "normal-side-exceptions", "category": "integrity",
        "titleEn": "Postings against the normal side", "titleFr": "Comptabilisations à contre-sens",
        "objectiveEn": "Flag postings on the side opposite to the normal balance of the SYSCOHADA account class.",
        "objectiveFr": "Signaler les comptabilisations du côté opposé au sens normal de la classe de compte SYSCOHADA.",
        "assertions": ["A", "C"], "requiredFields": ["account", "amount", "journalDate"],
        "exceptionEn": "A class 2, 3, 5 or 6 account credited, or a class 1 or 7 account debited.",
        "exceptionFr": "Un compte de classe 2, 3, 5 ou 6 crédité, ou un compte de classe 1 ou 7 débité.",
    },
    {
        "id": 17, "key": "unusual-account-combinations", "category": "pattern",
        "titleEn": "Unusual account combinations", "titleFr": "Combinaisons de comptes inhabituelles",
        "objectiveEn": "Score account pairings by how rarely they appear together in the same entry.",
        "objectiveFr": "Noter les couples de comptes selon la rareté de leur présence conjointe dans une même écriture.",
        "assertions": ["A", "C"], "requiredFields": ["account", "jeNumber"],
        "exceptionEn": "An entry pairing accounts that rarely appear together.",
        "exceptionFr": "Une écriture associant des comptes rarement réunis.",
    },
    {
        "id": 18, "key": "missing-mandatory-fields", "category": "completeness",
        "titleEn": "Missing mandatory fields", "titleFr": "Champs obligatoires manquants",
        "objectiveEn": "Count lines missing an account, an entry number, a description, a readable date or an amount.",
        "objectiveFr": "Compter les lignes sans compte, numéro d'écriture, libellé, date lisible ou montant.",
        "assertions": ["C", "A"], "requiredFields": ["account", "jeNumber", "journalDate"],
        "exceptionEn": "A line missing any mandatory field.",
        "exceptionFr": "Une ligne à laquelle manque un champ obligatoire.",
    },
    {
        "id": 19, "key": "missing-references", "category": "completeness",
        "titleEn": "Missing supporting reference", "titleFr": "Référence justificative manquante",
        "objectiveEn": "Count lines posted without a document reference tying them to supporting evidence.",
        "objectiveFr": "Compter les lignes comptabilisées sans référence de pièce les reliant à un justificatif.",
        "assertions": ["C", "E"], "requiredFields": ["reference", "journalDate"],
        "exceptionEn": "A line with no reference.",
        "exceptionFr": "Une ligne sans référence.",
    },
    {
        "id": 20, "key": "third-party-attribution", "category": "attribution",
        "titleEn": "Third-party attribution", "titleFr": "Attribution des tiers",
        "objectiveEn": "Within receivable and payable accounts only, measure how many postings carry the counterparty they belong to.",
        "objectiveFr": "Sur les seuls comptes clients et fournisseurs, mesurer la part des comptabilisations portant le tiers auquel elles se rattachent.",
        "assertions": ["C", "A"], "requiredFields": ["account", "thirdPartyCode", "journalDate"],
        "exceptionEn": "An in-scope line with no third-party code.",
        "exceptionFr": "Une ligne dans le périmètre sans code tiers.",
    },
    {
        "id": 21, "key": "preparer-volume", "category": "attribution",
        "titleEn": "Preparer volume", "titleFr": "Volume par préparateur",
        "objectiveEn": "Show how the posting workload is distributed across the people who recorded the entries.",
        "objectiveFr": "Montrer la répartition de la charge de comptabilisation entre les personnes ayant saisi les écritures.",
        "assertions": ["E", "P"], "requiredFields": ["preparer", "journalDate"],
        "exceptionEn": "A line with no identified preparer.",
        "exceptionFr": "Une ligne sans préparateur identifié.",
    },
    {
        "id": 22, "key": "preparer-value", "category": "attribution",
        "titleEn": "Preparer value", "titleFr": "Valeur par préparateur",
        "objectiveEn": "Show how posted value, not merely line count, is distributed across preparers.",
        "objectiveFr": "Montrer la répartition de la valeur comptabilisée, et non du seul nombre de lignes, entre les préparateurs.",
        "assertions": ["V", "P"], "requiredFields": ["preparer", "amount", "journalDate"],
        "exceptionEn": "Value posted by a preparer with no identity recorded.",
        "exceptionFr": "Valeur comptabilisée par un préparateur non identifié.",
    },
    {
        "id": 23, "key": "reviewer-workload", "category": "attribution",
        "titleEn": "Reviewer workload", "titleFr": "Charge de revue",
        "objectiveEn": "Show how review coverage is distributed and how many postings carry no reviewer at all.",
        "objectiveFr": "Montrer la répartition de la revue et le nombre de comptabilisations sans réviseur.",
        "assertions": ["P", "E"], "requiredFields": ["reviewer", "journalDate"],
        "exceptionEn": "A line with no reviewer recorded.",
        "exceptionFr": "Une ligne sans réviseur enregistré.",
    },
    {
        "id": 24, "key": "self-review", "category": "attribution",
        "titleEn": "Preparer equals approver", "titleFr": "Préparateur identique à l'approbateur",
        "objectiveEn": "Identify entries recorded and approved by the same person, defeating the segregation of duties.",
        "objectiveFr": "Identifier les écritures saisies et approuvées par la même personne, annulant la séparation des tâches.",
        "assertions": ["P"], "requiredFields": ["preparer", "approvedBy"],
        "exceptionEn": "An entry whose preparer and approver are the same person.",
        "exceptionFr": "Une écriture dont le préparateur et l'approbateur sont la même personne.",
    },
    {
        "id": 25, "key": "out-of-hours-postings", "category": "timing",
        "titleEn": "Out-of-hours postings", "titleFr": "Comptabilisations hors heures ouvrées",
        "objectiveEn": "Profile postings by the hour of day they were recorded, outside normal working hours.",
        "objectiveFr": "Profiler les comptabilisations selon l'heure de saisie, en dehors des heures ouvrées.",
        # the import carries a posting DATE but no time of day
        "assertions": ["E", "P"], "requiredFields": ["jeDate"],
        "exceptionEn": "A posting recorded outside working hours.",
        "exceptionFr": "Une comptabilisation saisie hors des heures ouvrées.",
        "unavailableEn": "Unavailable — the import carries no posting timestamp",
        "unavailableFr": "Indisponible — l'import ne comporte pas d'horodatage de saisie",
    },
    {
        "id": 26, "key": "sequence-gaps", "category": "completeness",
        "titleEn": "Entry numbering gaps", "titleFr": "Ruptures de séquence des écritures",
        "objectiveEn": "Test the journal numbering sequence for gaps and repeats within each journal code.",
        "objectiveFr": "Tester la séquence de numérotation des écritures pour détecter ruptures et doublons par code journal.",
        "assertions": ["C"], "requiredFields": ["jeNumber", "journalCode"],
        "exceptionEn": "A missing or repeated number in a journal sequence.",
        "exceptionFr": "Un numéro manquant ou répété dans une séquence de journal.",
        "unavailableEn": NOT_BUILT_EN, "unavailableFr": NOT_BUILT_FR,
    },
    {
        "id": 27, "key": "manual-vs-automated", "category": "pattern",
        "titleEn": "Manual versus system-generated", "titleFr": "Écritures manuelles ou générées",
        "objectiveEn": "Split the ledger between entries raised by hand and those generated by a source module.",
        "objectiveFr": "Répartir le grand livre entre écritures saisies à la main et écritures générées par un module source.",
        "assertions": ["E", "P"], "requiredFields": ["jeNumber"],
        "exceptionEn": "A manual entry in a population expected to be system-generated.",
        "exceptionFr": "Une écriture manuelle dans une population censée être générée par le système.",
        "unavailableEn": "Unavailable — the import carries no entry-source indicator",
        "unavailableFr": "Indisponible — l'import ne comporte pas d'indicateur de source d'écriture",
    },
    {
        "id": 28, "key": "post-period-postings", "category": "timing",
        "titleEn": "Postings after the period end", "titleFr": "Comptabilisations après la clôture",
        "objectiveEn": "Identify entries recorded after the period end but dated inside it.",
        "objectiveFr": "Identifier les écritures saisies après la clôture mais datées à l'intérieur de la période.",
        "assertions": ["C", "E"], "requiredFields": ["journalDate", "jeDate"],
        "exceptionEn": "An entry recorded after the period end and dated before it.",
        "exceptionFr": "Une écriture saisie après la clôture et datée avant celle-ci.",
        "unavailableEn": NOT_BUILT_EN, "unavailableFr": NOT_BUILT_FR,
    },
    {
        "id": 29, "key": "debit-credit-correlation", "category": "integrity",
        "titleEn": "Debit and credit co-movement", "titleFr": "Co-évolution des débits et crédits",
        "objectiveEn": "Track monthly debit and credit totals side by side and measure how closely they move together.",
        "objectiveFr": "Suivre les totaux mensuels de débits et de crédits côte à côte et mesurer leur corrélation.",
        "assertions": ["A", "C"], "requiredFields": ["amount", "journalDate"],
        "exceptionEn": "A month whose debit and credit totals diverge.",
        "exceptionFr": "Un mois dont les totaux de débits et de crédits divergent.",
    },
    {
        "id": 30, "key": "account-frequency-value", "category": "value",
        "titleEn": "Account frequency and value", "titleFr": "Fréquence et valeur par compte",
        "objectiveEn": "Describe the shape of ledger activity month by month: accounts touched, lines posted and value moved.",
        "objectiveFr": "Décrire la forme de l'activité mois par mois : comptes mouvementés, lignes comptabilisées et valeur déplacée.",
        "assertions": ["C", "V"], "requiredFields": ["account", "amount", "journalDate"],
        "exceptionEn": "Informational — no exception condition; the profile supports scoping decisions.",
        "exceptionFr": "Informatif — pas de condition d'exception ; le profil oriente le cadrage.",
    },
]

ANALYTIC_BY_KEY = {definition["key"]: definition for definition in ANALYTICS}

#: Analytic 17 pairs every account of an entry with every other one: quadratic in the entry's
#: width. Entries wider than this are outside its population, and its note says so.
PAIR_ACCOUNT_CAP = 30

#: Benford expected share of each leading digit, in percent.
BENFORD = [math.log10(1 + 1 / (index + 1)) * 100 for index in range(9)]


def t(locale, english, french):
    return french if locale == "fr" else english


def round2(value):
    return js_round(value * 100) / 100


def pct(part, whole):
    return None if whole == 0 else round2((part / whole) * 100)


def cell_sum(rows, index):
    """Sum a numeric column across the result rows, for the totals line."""
    return js_sum(row["cells"][index] if is_number(row["cells"][index]) else 0 for row in rows)


def pearson(xs, ys):
    """Pearson correlation; None when either series is flat (r is undefined then)."""
    n = min(len(xs), len(ys))
    if n < 3:
        return None
    mean_x = js_sum(xs[:n]) / n
    mean_y = js_sum(ys[:n]) / n
    cov = var_x = var_y = 0
    for index in range(n):
        cov += (xs[index] - mean_x) * (ys[index] - mean_y)
        var_x += (xs[index] - mean_x) ** 2
        var_y += (ys[index] - mean_y) ** 2
    if var_x == 0 or var_y == 0:
        return None
    return round2(cov / math.sqrt(var_x * var_y))


def mad_of(counts):
    """Mean absolute deviation from Benford, in points; None on an empty month."""
    total = js_sum(counts)
    if total == 0:
        return None
    return round2(js_sum(abs((value / total) * 100 - BENFORD[index]) for index, value in enumerate(counts)) / 9)


# ---------------------------------------------------------------------------
# input guards

_NUMERIC = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$", re.ASCII)
_PREFIX = re.compile(r"^[0-9]{1,6}$")


def js_number(value):
    """``Number(value)``, NaN included. ``undefined`` is the caller's: pass a float NaN."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return 1 if value else 0
    if is_number(value):
        return value
    text = js_trim(js_str(value))
    if text == "":
        return 0
    return float(text) if _NUMERIC.match(text) else math.nan


def _finite(value):
    number = js_number(value)
    return number if math.isfinite(number) else None


def clamp_int(value, minimum, maximum, fallback):
    number = _finite(math.nan if value is _UNDEFINED else value)
    return fallback if number is None else min(maximum, max(minimum, js_round(number)))


def clamp_number(value, minimum, maximum, fallback):
    number = _finite(math.nan if value is _UNDEFINED else value)
    return fallback if number is None else min(maximum, max(minimum, number))


_UNDEFINED = object()


def clean_prefixes(value):
    """Account prefixes reach a LIKE pattern, so they must be digits only."""
    raw = value if isinstance(value, (list, tuple)) else []
    cleaned = [text for text in (js_trim(js_str(prefix)) for prefix in raw) if _PREFIX.match(text)][:12]
    return list(dict.fromkeys(cleaned)) if cleaned else ["40", "41"]


def read_params(raw):
    """The route's readParams: only the knobs it declares. pairMax is not one of them."""
    raw = raw or {}
    params = {}
    for key in ("percentile", "sdFactor", "roundMin", "roundStep", "minOccurrences", "rareMax", "topN", "yearEndDays"):
        if key in raw:
            number = _finite(raw[key])
            if number is not None:
                params[key] = number
    if isinstance(raw.get("prefixes"), (list, tuple)):
        params["prefixes"] = [js_str(prefix) for prefix in raw["prefixes"]]
    return params


def clamped(params):
    """Every knob, clamped as the implementations clamp them."""
    get = lambda key: params.get(key, _UNDEFINED)  # noqa: E731
    return {
        "days": clamp_int(get("yearEndDays"), 1, 90, 15),
        "factor": clamp_number(get("sdFactor"), 0.5, 6, 2),
        "percentile": clamp_number(get("percentile"), 0.5, 0.9999, 0.99),
        "min": clamp_number(get("roundMin"), 1, 1e15, 100000),
        "step": clamp_number(get("roundStep"), 1, 1e15, 100000),
        "minOcc": clamp_int(get("minOccurrences"), 2, 10000, 10),
        "rareMax": clamp_int(get("rareMax"), 1, 100, 3),
        "pairMax": clamp_int(get("pairMax"), 1, 100, 3),
        "prefixes": clean_prefixes(params.get("prefixes")),
        "topN": clamp_int(get("topN"), 1, 30, 10),
    }


# ---------------------------------------------------------------------------
# the bodies


def _col(key, label):
    return {"key": key, "label": label}


def _row(row, cells):
    return {"month": row["m"], "cells": cells}


def _ledger_reconciliation(results, locale, _knobs):
    q = results["rows"]
    rows = [_row(r, [r["lines"], round2(r["d"]), round2(r["c"]), round2(r["diff"])]) for r in q]
    return {
        "columns": [
            _col("lines", t(locale, "Lines", "Lignes")), _col("debit", t(locale, "Debit", "Débit")),
            _col("credit", t(locale, "Credit", "Crédit")), _col("difference", t(locale, "Difference", "Écart")),
        ],
        "rows": rows,
        "totals": [cell_sum(rows, 0), round2(cell_sum(rows, 1)), round2(cell_sum(rows, 2)), round2(cell_sum(rows, 3))],
        "exceptions": len([r for r in q if abs(r["diff"]) > TOLERANCE]),
        "population": len(q),
        "note": t(
            locale,
            "Population is the months in the ledger; an exception is a month whose debits and credits differ by more than 0.005.",
            "La population est constituée des mois du grand livre ; une exception est un mois dont les débits et crédits diffèrent de plus de 0,005.",
        ),
    }


def _unbalanced_entries(results, locale, _knobs):
    rows = [
        _row(r, [r["entries"], r["unbalanced"], round2(r["diff"]), pct(r["unbalanced"], r["entries"])])
        for r in results["rows"]
    ]
    return {
        "columns": [
            _col("entries", t(locale, "Entries", "Écritures")), _col("unbalanced", t(locale, "Unbalanced", "Déséquilibrées")),
            _col("netDifference", t(locale, "Net difference", "Écart net")), _col("sharePct", t(locale, "% of entries", "% des écritures")),
        ],
        "rows": rows,
        "totals": [cell_sum(rows, 0), cell_sum(rows, 1), round2(cell_sum(rows, 2)), pct(cell_sum(rows, 1), cell_sum(rows, 0))],
        "exceptions": cell_sum(rows, 1),
        "population": cell_sum(rows, 0),
        "note": t(
            locale, "An entry is grouped under the earliest journal date of its lines.",
            "Une écriture est rattachée à la date de journal la plus ancienne de ses lignes.",
        ),
    }


def _population(results):
    found = results.get("population") or []
    return found[0]["n"] if found else 0


def _exact_duplicates(results, locale, _knobs):
    rows = [_row(r, [r["groups"], r["lines"], r["extra"], round2(r["value"])]) for r in results["rows"]]
    return {
        "columns": [
            _col("groups", t(locale, "Duplicate groups", "Groupes de doublons")), _col("lines", t(locale, "Lines involved", "Lignes concernées")),
            _col("extra", t(locale, "Repeat lines", "Lignes répétées")), _col("value", t(locale, "Gross value", "Valeur brute")),
        ],
        "rows": rows,
        "totals": [cell_sum(rows, 0), cell_sum(rows, 1), cell_sum(rows, 2), round2(cell_sum(rows, 3))],
        "exceptions": cell_sum(rows, 2),
        "population": _population(results),
        "note": t(
            locale,
            "Identity is account, entry number, journal date, reference, signed amount and description. The first occurrence of each group is not counted as an exception.",
            "L'identité porte sur le compte, le numéro d'écriture, la date, la référence, le montant signé et le libellé. La première occurrence de chaque groupe n'est pas comptée comme exception.",
        ),
    }


def _zero_value(results, locale, _knobs):
    rows = [_row(r, [r["lines"], r["nil"], pct(r["nil"], r["lines"])]) for r in results["rows"]]
    return {
        "columns": [
            _col("lines", t(locale, "Lines", "Lignes")), _col("nil", t(locale, "Nil-value lines", "Lignes de valeur nulle")),
            _col("sharePct", t(locale, "% of lines", "% des lignes")),
        ],
        "rows": rows,
        "totals": [cell_sum(rows, 0), cell_sum(rows, 1), pct(cell_sum(rows, 1), cell_sum(rows, 0))],
        "exceptions": cell_sum(rows, 1),
        "population": cell_sum(rows, 0),
    }


def _invalid_debit_credit(results, locale, _knobs):
    rows = [
        _row(r, [r["lines"], r["both"], r["negative"], r["neither"], r["both"] + r["negative"] + r["neither"]])
        for r in results["rows"]
    ]
    return {
        "columns": [
            _col("lines", t(locale, "Lines", "Lignes")), _col("both", t(locale, "Both sides posted", "Deux côtés servis")),
            _col("negative", t(locale, "Negative side", "Côté négatif")), _col("neither", t(locale, "Neither side posted", "Aucun côté servi")),
            _col("exceptions", t(locale, "Exceptions", "Exceptions")),
        ],
        "rows": rows,
        "totals": [cell_sum(rows, index) for index in range(5)],
        "exceptions": cell_sum(rows, 4),
        "population": cell_sum(rows, 0),
        "note": t(
            locale, "A well-formed line carries a positive value on exactly one side.",
            "Une ligne bien formée porte une valeur positive d'un seul côté.",
        ),
    }


def _weekend_postings(results, locale, _knobs):
    names = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"] if locale == "fr" else ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    rows = []
    for r in results["rows"]:
        days = [r["d%d" % day] or 0 for day in range(1, 8)]
        weekend = days[5] + days[6]
        rows.append(_row(r, days + [weekend, pct(weekend, r["lines"])]))
    weekend_total = cell_sum(rows, 7)
    line_total = js_sum(cell_sum(rows, index) for index in range(7))
    return {
        "columns": [_col("d%d" % (index + 1), label) for index, label in enumerate(names)] + [
            _col("weekend", t(locale, "Weekend", "Week-end")), _col("weekendPct", t(locale, "% weekend", "% week-end")),
        ],
        "rows": rows,
        "totals": [cell_sum(rows, index) for index in range(7)] + [weekend_total, pct(weekend_total, line_total)],
        "exceptions": weekend_total,
        "population": line_total,
        "note": t(
            locale,
            "Lines with no readable journal date fall outside every weekday column and are shown in the n/a row.",
            "Les lignes sans date de journal lisible ne figurent dans aucune colonne de jour et apparaissent dans la ligne n/a.",
        ),
    }


def _entry_date_lag(results, locale, _knobs):
    rows = [
        _row(r, [
            r["entries"], r["same"], r["one"], r["short"], r["long"], r["negative"],
            None if r["avg"] is None else round2(r["avg"]), None if r["max"] is None else js_round(r["max"]),
        ])
        for r in results["rows"]
    ]
    total_entries = cell_sum(rows, 0)
    weighted = None if total_entries == 0 else round2(
        js_sum((row["cells"][6] or 0) * (row["cells"][0] or 0) for row in rows) / total_entries
    )
    longest = 0
    for row in rows:
        longest = max(longest, row["cells"][7] or 0)
    return {
        "columns": [
            _col("entries", t(locale, "Entries", "Écritures")), _col("sameDay", t(locale, "Same day", "Le jour même")),
            _col("oneDay", t(locale, "1 day", "1 jour")), _col("twoThree", t(locale, "2–3 days", "2–3 jours")),
            _col("overThree", t(locale, "Over 3 days", "Plus de 3 jours")), _col("negative", t(locale, "Recorded before", "Saisie antérieure")),
            _col("avgDays", t(locale, "Average days", "Moyenne (jours)")), _col("maxDays", t(locale, "Longest lag", "Décalage maximal")),
        ],
        "rows": rows,
        "totals": [total_entries, cell_sum(rows, 1), cell_sum(rows, 2), cell_sum(rows, 3), cell_sum(rows, 4), cell_sum(rows, 5), weighted, longest],
        "exceptions": cell_sum(rows, 4) + cell_sum(rows, 5),
        "population": total_entries,
        "note": t(
            locale,
            "Measured per journal entry, using the earliest journal date and earliest entry date of its lines. Entries missing either date are outside the population.",
            "Mesuré par écriture, à partir de la date de journal et de la date de saisie les plus anciennes de ses lignes. Les écritures dépourvues de l'une des dates sont hors population.",
        ),
    }


def _year_end(results, locale, knobs):
    days = knobs["days"]
    q = results["rows"]
    total_value = js_sum(r["value"] for r in q)
    rows = [_row(r, [r["lines"], round2(r["value"]), pct(r["value"], total_value), r["wlines"], round2(r["wvalue"])]) for r in q]
    return {
        "columns": [
            _col("lines", t(locale, "Lines", "Lignes")), _col("value", t(locale, "Gross value", "Valeur brute")),
            _col("sharePct", t(locale, "% of year value", "% de la valeur annuelle")),
            _col("closingLines", t(locale, "Lines in last %d days" % days, "Lignes des %d derniers jours" % days)),
            _col("closingValue", t(locale, "Closing-window value", "Valeur de la fenêtre de clôture")),
        ],
        "rows": rows,
        "totals": [cell_sum(rows, 0), round2(cell_sum(rows, 1)), pct(total_value, total_value), cell_sum(rows, 3), round2(cell_sum(rows, 4))],
        "exceptions": cell_sum(rows, 3),
        "population": cell_sum(rows, 0),
        "note": t(
            locale,
            "The closing window is the last %d days of the engagement period. Concentration there is a risk indicator requiring audit consideration, not a finding in itself." % days,
            "La fenêtre de clôture correspond aux %d derniers jours de la période. Une concentration à cet endroit est un indicateur de risque à examiner, non un constat en soi." % days,
        ),
    }


def _monthly_spikes(results, locale, knobs):
    factor = knobs["factor"]
    label = js_number_str(factor)
    rows = []
    for r in results["rows"]:
        threshold = r["mu"] + factor * r["sd"]
        rows.append(_row(r, [
            r["lines"], round2(r["value"]), round2(r["mu"]), round2(r["sd"]), round2(threshold),
            1 if r["value"] > threshold else 0,
        ]))
    return {
        "columns": [
            _col("lines", t(locale, "Lines", "Lignes")), _col("value", t(locale, "Gross value", "Valeur brute")),
            _col("mean", t(locale, "Mean month", "Moyenne mensuelle")), _col("sd", t(locale, "Standard deviation", "Écart-type")),
            _col("threshold", t(locale, "Mean + %s sd" % label, "Moyenne + %s écarts-types" % label)),
            _col("flag", t(locale, "Above threshold", "Au-dessus du seuil")),
        ],
        "rows": rows,
        "totals": [cell_sum(rows, 0), round2(cell_sum(rows, 1)), None, None, None, cell_sum(rows, 5)],
        "exceptions": cell_sum(rows, 5),
        "population": len(rows),
        "note": t(
            locale,
            "Undated lines are excluded: they cannot belong to a month, and including them would distort the mean.",
            "Les lignes non datées sont exclues : elles n'appartiennent à aucun mois et fausseraient la moyenne.",
        ),
    }


def _top_value(results, locale, knobs):
    q = results["rows"]
    rows = [_row(r, [r["lines"], r["hits"], round2(r["hitValue"]), pct(r["hitValue"], r["value"])]) for r in q]
    threshold = q[0]["threshold"] if q else 0
    cut = js_number_str(round2(knobs["percentile"] * 100))
    level = js_number_str(round2(threshold))
    return {
        "columns": [
            _col("lines", t(locale, "Lines", "Lignes")), _col("hits", t(locale, "Lines above threshold", "Lignes au-dessus du seuil")),
            _col("hitValue", t(locale, "Their gross value", "Leur valeur brute")), _col("sharePct", t(locale, "% of month value", "% de la valeur du mois")),
        ],
        "rows": rows,
        "totals": [cell_sum(rows, 0), cell_sum(rows, 1), round2(cell_sum(rows, 2)), None],
        "exceptions": cell_sum(rows, 1),
        "population": cell_sum(rows, 0),
        "note": t(
            locale,
            "Threshold: the %sth percentile of absolute line amounts, %s." % (cut, level),
            "Seuil : %se centile des montants absolus, soit %s." % (cut, level),
        ),
    }


def _round_numbers(results, locale, knobs):
    rows = [_row(r, [r["lines"], r["hits"], round2(r["value"]), pct(r["hits"], r["lines"])]) for r in results["rows"]]
    minimum, step = js_number_str(knobs["min"]), js_number_str(knobs["step"])
    return {
        "columns": [
            _col("lines", t(locale, "Lines", "Lignes")), _col("hits", t(locale, "Round-amount lines", "Lignes à montant rond")),
            _col("value", t(locale, "Their gross value", "Leur valeur brute")), _col("sharePct", t(locale, "% of lines", "% des lignes")),
        ],
        "rows": rows,
        "totals": [cell_sum(rows, 0), cell_sum(rows, 1), round2(cell_sum(rows, 2)), pct(cell_sum(rows, 1), cell_sum(rows, 0))],
        "exceptions": cell_sum(rows, 1),
        "population": cell_sum(rows, 0),
        "note": t(
            locale,
            "Criteria: absolute amount at least %s and an exact multiple of %s." % (minimum, step),
            "Critères : montant absolu d'au moins %s et multiple exact de %s." % (minimum, step),
        ),
    }


def _benford(results, locale, _knobs):
    by_month = {}
    for r in results["rows"]:
        digit = int(r["digit"]) if r["digit"] and r["digit"] in "123456789" else None
        if digit is None:
            continue
        by_month.setdefault(r["m"], [0] * 9)[digit - 1] += r["n"]
    rows = []
    for month in sorted(by_month):
        counts = by_month[month]
        total = js_sum(counts)
        rows.append({"month": month, "cells": [pct(value, total) for value in counts] + [total, mad_of(counts)]})
    overall = [js_sum(counts[index] for counts in by_month.values()) for index in range(9)]
    overall_total = js_sum(overall)
    exceptions = len([row for row in rows if is_number(row["cells"][10]) and row["cells"][10] > 1.5])
    shares = [js_number_str(round2(value)) for value in BENFORD]
    return {
        "columns": [_col("d%d" % (index + 1), "%d %%" % (index + 1)) for index in range(9)] + [
            _col("lines", t(locale, "Lines", "Lignes")), _col("mad", t(locale, "MAD (pts)", "EAM (pts)")),
        ],
        "rows": rows,
        "totals": [pct(value, overall_total) for value in overall] + [overall_total, mad_of(overall)],
        "exceptions": exceptions,
        "population": len(rows),
        "note": t(
            locale,
            "Expected first-digit shares: %s. A mean absolute deviation above 1.5 points is a risk indicator requiring audit consideration, not a conclusion; nil amounts are outside the population."
            % ", ".join("%d=%s%%" % (index + 1, share) for index, share in enumerate(shares)),
            "Parts attendues du premier chiffre : %s. Un écart absolu moyen supérieur à 1,5 point est un indicateur de risque à examiner, non une conclusion ; les montants nuls sont hors population."
            % ", ".join("%d=%s %%" % (index + 1, share) for index, share in enumerate(shares)),
        ),
    }


def _repeated_amounts(results, locale, knobs):
    rows = [_row(r, [r["amounts"], r["lines"], round2(r["value"])]) for r in results["rows"]]
    occurrences = knobs["minOcc"]
    return {
        "columns": [
            _col("amounts", t(locale, "Distinct repeated amounts", "Montants répétés distincts")),
            _col("lines", t(locale, "Lines", "Lignes")), _col("value", t(locale, "Gross value", "Valeur brute")),
        ],
        "rows": rows,
        "totals": [None, cell_sum(rows, 1), round2(cell_sum(rows, 2))],
        "exceptions": cell_sum(rows, 1),
        "population": _population(results),
        "note": t(
            locale,
            "An amount counts as repeated when it appears at least %d times across the year; the monthly distinct count is not additive, so no total is shown for it." % occurrences,
            "Un montant est réputé répété lorsqu'il apparaît au moins %d fois dans l'année ; le nombre mensuel de montants distincts n'est pas additif, aucun total n'est donc affiché." % occurrences,
        ),
    }


def _rare_accounts(results, locale, knobs):
    rows = [_row(r, [r["accounts"], r["lines"], round2(r["value"])]) for r in results["rows"]]
    postings = knobs["rareMax"]
    return {
        "columns": [
            _col("accounts", t(locale, "Rare accounts touched", "Comptes rares mouvementés")),
            _col("lines", t(locale, "Lines", "Lignes")), _col("value", t(locale, "Gross value", "Valeur brute")),
        ],
        "rows": rows,
        "totals": [None, cell_sum(rows, 1), round2(cell_sum(rows, 2))],
        "exceptions": cell_sum(rows, 1),
        "population": _population(results),
        "note": t(
            locale,
            "An account is rare when it carries at most %d postings in the whole ledger. The monthly account count is not additive across months." % postings,
            "Un compte est rare lorsqu'il porte au plus %d comptabilisations sur l'ensemble du grand livre. Le nombre mensuel de comptes n'est pas additif." % postings,
        ),
    }


def _normal_side(results, locale, _knobs):
    rows = [
        _row(r, [r["inScope"], r["credited"], r["debited"], r["credited"] + r["debited"], round2(r["value"])])
        for r in results["rows"]
    ]
    return {
        "columns": [
            _col("inScope", t(locale, "Lines in scope", "Lignes dans le périmètre")),
            _col("credited", t(locale, "Debit-side accounts credited", "Comptes débiteurs crédités")),
            _col("debited", t(locale, "Credit-side accounts debited", "Comptes créditeurs débités")),
            _col("exceptions", t(locale, "Exceptions", "Exceptions")), _col("value", t(locale, "Their gross value", "Leur valeur brute")),
        ],
        "rows": rows,
        "totals": [cell_sum(rows, 0), cell_sum(rows, 1), cell_sum(rows, 2), cell_sum(rows, 3), round2(cell_sum(rows, 4))],
        "exceptions": cell_sum(rows, 3),
        "population": cell_sum(rows, 0),
        "note": t(
            locale,
            "SYSCOHADA normal sides: classes 2, 3 and 6 are debit accounts; classes 1 and 7, and the depreciation and impairment accounts 28, 29, 39, 49 and 59, are credit accounts. Class 4 (third parties), class 5 (treasury, debited and credited in the normal course) and classes 8–9 are two-sided and outside the population. A contra posting is often a legitimate reversal — it is an exception to explain, not an error.",
            "Sens normaux SYSCOHADA : les classes 2, 3 et 6 sont débitrices ; les classes 1 et 7, ainsi que les comptes d'amortissements et de dépréciations 28, 29, 39, 49 et 59, sont créditrices. La classe 4 (tiers), la classe 5 (trésorerie, débitée et créditée dans le cours normal) et les classes 8–9 sont bilatérales et hors population. Une comptabilisation à contre-sens est souvent une contrepassation légitime : c'est une exception à expliquer, non une erreur.",
        ),
    }


def _unusual_combinations(results, locale, knobs):
    rows = [_row(r, [r["entries"], r["hits"], r["pairs"], r["rare"], pct(r["hits"], r["entries"])]) for r in results["rows"]]
    pair_max = knobs["pairMax"]
    return {
        "columns": [
            _col("entries", t(locale, "Entries", "Écritures")), _col("hits", t(locale, "With a rare pairing", "Avec un couple rare")),
            _col("pairs", t(locale, "Account pairs", "Couples de comptes")), _col("rare", t(locale, "Rare pairs", "Couples rares")),
            _col("sharePct", t(locale, "% of entries", "% des écritures")),
        ],
        "rows": rows,
        "totals": [cell_sum(rows, 0), cell_sum(rows, 1), cell_sum(rows, 2), cell_sum(rows, 3), pct(cell_sum(rows, 1), cell_sum(rows, 0))],
        "exceptions": cell_sum(rows, 1),
        "population": cell_sum(rows, 0),
        "note": t(
            locale,
            "Rarity is counted across the whole ledger: a pairing of two accounts is rare when it appears in at most %d entries all year. Entries touching a single account, or more than %d of them, are outside the population — the first offer no pairing to score, the second would make everything look rare. A rare pairing is a risk indicator requiring audit consideration, not a finding: the first entry of a new kind is rare by definition." % (pair_max, PAIR_ACCOUNT_CAP),
            "La rareté est mesurée sur l'ensemble du grand livre : un couple de comptes est rare lorsqu'il apparaît dans au plus %d écritures sur l'année. Les écritures ne touchant qu'un compte, ou plus de %d, sont hors population — les premières n'offrent aucun couple, les secondes rendraient tout rare. Un couple rare est un indicateur de risque à examiner, non un constat : la première écriture d'un type nouveau est rare par définition." % (pair_max, PAIR_ACCOUNT_CAP),
        ),
    }


def _missing_mandatory(results, locale, _knobs):
    rows = [
        _row(r, [
            r["lines"], r["noAccount"], r["noJe"], r["noDesc"], r["noDate"], r["noAmount"],
            r["noAccount"] + r["noJe"] + r["noDesc"] + r["noDate"] + r["noAmount"],
        ])
        for r in results["rows"]
    ]
    return {
        "columns": [
            _col("lines", t(locale, "Lines", "Lignes")), _col("noAccount", t(locale, "No account", "Sans compte")),
            _col("noJe", t(locale, "No JE number", "Sans numéro d'écriture")), _col("noDesc", t(locale, "No description", "Sans libellé")),
            _col("noDate", t(locale, "No readable date", "Date illisible")), _col("noAmount", t(locale, "No amount", "Sans montant")),
            _col("exceptions", t(locale, "Field gaps", "Champs manquants")),
        ],
        "rows": rows,
        "totals": [cell_sum(rows, index) for index in range(7)],
        "exceptions": cell_sum(rows, 6),
        "population": cell_sum(rows, 0),
        "note": t(
            locale,
            "The exception column counts field gaps, not lines: one line missing two fields contributes twice.",
            "La colonne des exceptions compte les champs manquants, non les lignes : une ligne à laquelle manquent deux champs compte deux fois.",
        ),
    }


def _missing_references(results, locale, _knobs):
    rows = [_row(r, [r["lines"], r["missing"], round2(r["value"]), pct(r["missing"], r["lines"])]) for r in results["rows"]]
    return {
        "columns": [
            _col("lines", t(locale, "Lines", "Lignes")), _col("missing", t(locale, "No reference", "Sans référence")),
            _col("value", t(locale, "Their gross value", "Leur valeur brute")), _col("sharePct", t(locale, "% of lines", "% des lignes")),
        ],
        "rows": rows,
        "totals": [cell_sum(rows, 0), cell_sum(rows, 1), round2(cell_sum(rows, 2)), pct(cell_sum(rows, 1), cell_sum(rows, 0))],
        "exceptions": cell_sum(rows, 1),
        "population": cell_sum(rows, 0),
    }


def _third_party(results, locale, knobs):
    rows = [
        _row(r, [
            r["inScope"], r["attributed"], r["inScope"] - r["attributed"],
            pct(r["attributed"], r["inScope"]), round2(r["unattributedValue"]),
        ])
        for r in results["rows"]
    ]
    prefixes = ", ".join(knobs["prefixes"])
    return {
        "columns": [
            _col("inScope", t(locale, "Lines in scope", "Lignes dans le périmètre")), _col("attributed", t(locale, "With third party", "Avec tiers")),
            _col("unattributed", t(locale, "Without third party", "Sans tiers")), _col("attributedPct", t(locale, "% attributed", "% attribuées")),
            _col("unattributedValue", t(locale, "Unattributed value", "Valeur non attribuée")),
        ],
        "rows": rows,
        "totals": [cell_sum(rows, 0), cell_sum(rows, 1), cell_sum(rows, 2), pct(cell_sum(rows, 1), cell_sum(rows, 0)), round2(cell_sum(rows, 4))],
        "exceptions": cell_sum(rows, 2),
        "population": cell_sum(rows, 0),
        "note": t(
            locale,
            "Population restricted to accounts beginning %s — receivables and payables, the only balances a counterparty code is meaningful for. Percentages are measured against that in-scope population, never the whole ledger." % prefixes,
            "Population limitée aux comptes commençant par %s — clients et fournisseurs, seuls soldes pour lesquels un code tiers a un sens. Les pourcentages sont rapportés à cette population, jamais au grand livre entier." % prefixes,
        ),
    }


def _by_person(results, locale, measure):
    """21, 22, 23: months down the side, the busiest people across, the rest in Other, and the
    unattributed lines in their own column so the gap in the audit trail stays visible."""
    named = [row["person"] for row in results["top"]]
    grid = results["grid"]
    months = js_sorted(list(dict.fromkeys(row["m"] for row in grid)))
    index = {name: position for position, name in enumerate(named)}
    width = len(named) + 2  # named people + Other + Unattributed
    by_month = {month: [0] * width for month in months}
    for row in grid:
        cells = by_month[row["m"]]
        if row["person"] is None:
            cells[width - 1] += row["v"]
        else:
            cells[index.get(row["person"], width - 2)] += row["v"]
    rows = []
    for month in months:
        cells = by_month[month]
        shown = list(cells) if measure == "count" else [round2(value) for value in cells]
        rows.append({"month": month, "cells": shown + [round2(js_sum(cells))]})
    other = t(locale, "Other", "Autres")
    unattributed = t(locale, "Unattributed", "Non attribué")
    columns = [_col("p%d" % position, name) for position, name in enumerate(named)] + [
        _col("other", other), _col("unattributed", unattributed), _col("total", t(locale, "Total", "Total")),
    ]
    gap = results["gap"][0] if results["gap"] else {"missing": 0, "lines": 0}
    measure_note = (
        t(locale, "Cells are line counts.", "Les cellules sont des nombres de lignes.") if measure == "count"
        else t(locale, "Cells are gross posted value.", "Les cellules sont des valeurs brutes comptabilisées.")
    )
    return {
        "columns": columns,
        "rows": rows,
        "totals": [round2(cell_sum(rows, position)) for position in range(len(columns))],
        # exceptions are always lines with nobody recorded, whichever measure is shown
        "exceptions": gap["missing"],
        "population": gap["lines"],
        "note": "%s %s" % (measure_note, t(
            locale,
            'The %d busiest people have their own column; everyone else is folded into "%s". Lines with nobody recorded are shown under "%s" and are the exception count.' % (len(named), other, unattributed),
            "Les %d personnes les plus actives ont leur propre colonne ; les autres sont regroupées sous « %s ». Les lignes sans personne enregistrée figurent sous « %s » et constituent le nombre d'exceptions." % (len(named), other, unattributed),
        )),
    }


def _self_review(results, locale, _knobs):
    rows = [
        _row(r, [r["entries"], r["attributed"], r["same"], pct(r["same"], r["attributed"]), r["none"], round2(r["value"])])
        for r in results["rows"]
    ]
    return {
        "columns": [
            _col("entries", t(locale, "Entries", "Écritures")), _col("attributed", t(locale, "Both names recorded", "Deux noms enregistrés")),
            _col("same", t(locale, "Same person", "Même personne")), _col("sharePct", t(locale, "% of attributed", "% des écritures nominatives")),
            _col("none", t(locale, "Neither name recorded", "Aucun nom enregistré")), _col("value", t(locale, "Their gross value", "Leur valeur brute")),
        ],
        "rows": rows,
        "totals": [cell_sum(rows, 0), cell_sum(rows, 1), cell_sum(rows, 2), pct(cell_sum(rows, 2), cell_sum(rows, 1)), cell_sum(rows, 4), round2(cell_sum(rows, 5))],
        "exceptions": cell_sum(rows, 2),
        "population": cell_sum(rows, 1),
        "note": t(
            locale,
            "The population is entries carrying BOTH a preparer and an approver: segregation of duties can only be tested where the file records who did each part. Entries with neither name have their own column, because that is a gap in the audit trail rather than a self-approval, and folding it in here would overstate this exception. Names are compared trimmed and without regard to case, so one person spelt two ways is still one person; an entry counts once however many of its lines are self-approved.",
            "La population est constituée des écritures portant À LA FOIS un préparateur et un approbateur : la séparation des tâches ne peut être testée que là où le dossier indique qui a fait quoi. Les écritures sans aucun nom disposent de leur propre colonne, car il s'agit d'une rupture de piste d'audit et non d'une auto-approbation ; les y fondre surestimerait cette exception. Les noms sont comparés sans espaces de bord ni distinction de casse : une même personne écrite de deux façons reste une seule personne ; une écriture compte une fois quel que soit le nombre de ses lignes auto-approuvées.",
        ),
    }


def _debit_credit_correlation(results, locale, _knobs):
    q = results["rows"]
    rows = [
        _row(r, [round2(r["d"]), round2(r["c"]), round2(r["d"] - r["c"]), None if r["c"] == 0 else round2(r["d"] / r["c"])])
        for r in q
    ]
    r_value = pearson([r["d"] for r in q], [r["c"] for r in q])
    return {
        "columns": [
            _col("debit", t(locale, "Debit", "Débit")), _col("credit", t(locale, "Credit", "Crédit")),
            _col("difference", t(locale, "Difference", "Écart")), _col("ratio", t(locale, "Debit / credit", "Débit / crédit")),
        ],
        "rows": rows,
        "totals": [round2(cell_sum(rows, 0)), round2(cell_sum(rows, 1)), round2(cell_sum(rows, 2)), None],
        "exceptions": len([r for r in q if abs(r["d"] - r["c"]) > TOLERANCE]),
        "population": len(rows),
        "note": t(
            locale,
            "Pearson correlation of monthly debit and credit totals: %s. The ratio is null where the month has no credits, never infinity."
            % ("not computable (a series has no variance or too few months)" if r_value is None else js_number_str(r_value)),
            "Corrélation de Pearson des totaux mensuels de débits et de crédits : %s. Le ratio est nul lorsque le mois ne comporte aucun crédit, jamais infini."
            % ("non calculable (série sans variance ou trop peu de mois)" if r_value is None else js_number_str(r_value).replace(".", ",")),
        ),
    }


def _account_frequency(results, locale, _knobs):
    rows = [
        _row(r, [
            r["accounts"], r["entries"], r["lines"], round2(r["value"]),
            None if r["accounts"] == 0 else round2(r["lines"] / r["accounts"]),
            None if r["lines"] == 0 else round2(r["value"] / r["lines"]),
        ])
        for r in results["rows"]
    ]
    total_lines = cell_sum(rows, 2)
    total_value = cell_sum(rows, 3)
    return {
        "columns": [
            _col("accounts", t(locale, "Accounts touched", "Comptes mouvementés")), _col("entries", t(locale, "Entries", "Écritures")),
            _col("lines", t(locale, "Lines", "Lignes")), _col("value", t(locale, "Gross value", "Valeur brute")),
            _col("linesPerAccount", t(locale, "Lines per account", "Lignes par compte")), _col("valuePerLine", t(locale, "Value per line", "Valeur par ligne")),
        ],
        "rows": rows,
        "totals": [None, cell_sum(rows, 1), total_lines, round2(total_value), None, None if total_lines == 0 else round2(total_value / total_lines)],
        "exceptions": 0,
        "population": total_lines,
        "note": t(
            locale,
            "Informational profile — it carries no exception condition. Account and entry counts are per month and are not additive across months, so no total is shown for accounts.",
            "Profil informatif — sans condition d'exception. Les nombres de comptes et d'écritures sont mensuels et non additifs ; aucun total n'est donc affiché pour les comptes.",
        ),
    }


BODIES = {
    "ledger-reconciliation": _ledger_reconciliation,
    "unbalanced-entries": _unbalanced_entries,
    "exact-duplicates": _exact_duplicates,
    "zero-value": _zero_value,
    "invalid-debit-credit": _invalid_debit_credit,
    "weekend-postings": _weekend_postings,
    "entry-date-lag": _entry_date_lag,
    "year-end-concentration": _year_end,
    "monthly-spikes": _monthly_spikes,
    "top-value": _top_value,
    "round-numbers": _round_numbers,
    "benford": _benford,
    "repeated-amounts": _repeated_amounts,
    "rare-accounts": _rare_accounts,
    "normal-side-exceptions": _normal_side,
    "unusual-account-combinations": _unusual_combinations,
    "missing-mandatory-fields": _missing_mandatory,
    "missing-references": _missing_references,
    "third-party-attribution": _third_party,
    "preparer-volume": lambda results, locale, _knobs: _by_person(results, locale, "count"),
    "preparer-value": lambda results, locale, _knobs: _by_person(results, locale, "value"),
    "reviewer-workload": lambda results, locale, _knobs: _by_person(results, locale, "count"),
    "self-review": _self_review,
    "debit-credit-correlation": _debit_credit_correlation,
    "account-frequency-value": _account_frequency,
}


# ---------------------------------------------------------------------------
# status and result


def missing_fields(definition, fields):
    """The mapping keys this analytic needs and the dataset lacks."""
    return [
        name for name in definition["requiredFields"]
        if name not in fields and not (name == "amount" and "signedAmount" in fields)
    ]


def status_of(definition, mapping, locale):
    """None when it can run on this mapping, else its honest reason: the mapping first."""
    missing = missing_fields(definition, mapped_fields(mapping))
    if missing:
        return "%s: %s" % (t(locale, UNAVAILABLE_EN, UNAVAILABLE_FR), ", ".join(missing))
    if definition["key"] not in BODIES:
        return t(locale, definition.get("unavailableEn", NOT_BUILT_EN), definition.get("unavailableFr", definition.get("unavailableEn", NOT_BUILT_FR)))
    return None


def catalogue(mapping, locale):
    """All thirty analytics with their status against one dataset's mapping."""
    return [
        {
            "id": definition["id"], "key": definition["key"],
            "title": t(locale, definition["titleEn"], definition["titleFr"]),
            "category": definition["category"],
            "objective": t(locale, definition["objectiveEn"], definition["objectiveFr"]),
            "assertions": definition["assertions"], "requiredFields": definition["requiredFields"],
            "exception": t(locale, definition["exceptionEn"], definition["exceptionFr"]),
            "unavailable": status_of(definition, mapping, locale),
        }
        for definition in ANALYTICS
    ]


def result_shell(definition, locale):
    return {
        "key": definition["key"],
        "title": t(locale, definition["titleEn"], definition["titleFr"]),
        "objective": t(locale, definition["objectiveEn"], definition["objectiveFr"]),
        "requiredFields": definition["requiredFields"],
    }


def unavailable_result(definition, locale, reason):
    return {**result_shell(definition, locale), "unavailable": reason, "columns": [], "rows": [], "exceptions": 0, "population": 0}


def build_result(definition, results, locale, knobs):
    return {**result_shell(definition, locale), **BODIES[definition["key"]](results, locale, knobs)}


#: How a column's figures read. Keys the source shares across analytics mean the same thing.
_MONEY = {
    "debit", "credit", "difference", "value", "netDifference", "closingValue", "hitValue", "mean", "sd",
    "threshold", "unattributedValue", "valuePerLine",
}
_DECIMAL = {"sharePct", "weekendPct", "attributedPct", "mad", "ratio", "avgDays", "linesPerAccount"}


def column_kind(analytic_key, column_key):
    """money, decimal or count: for display only."""
    if analytic_key == "preparer-value":
        return "money"
    if column_key in _MONEY:
        return "money"
    if column_key in _DECIMAL or (analytic_key == "benford" and re.fullmatch(r"d[1-9]", column_key)):
        return "decimal"
    return "count"
