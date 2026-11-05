"""The working workbooks of milestone 2. Plain openpyxl on plain data, no Odoo here."""
import io
import re

from openpyxl import Workbook
from openpyxl.styles import Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .services.control_labels import freq_label, type_short

HDR = "D9D9D9"
BAND = "C0C0C0"
ENTRY = "FFF2CC"
KEY = "FFEB9C"
SAMPLE = "DDEBF7"
NUM = "#,##0;(#,##0)"
_THIN = Side(style="thin", color="999999")
BOX = Border(top=_THIN, left=_THIN, bottom=_THIN, right=_THIN)


def fill(argb):
    return PatternFill("solid", fgColor=argb)


def tab(text):
    return re.sub(r"[\\/*?:\[\]]", " ", text)[:31]


def to_bytes(book):
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def new_book():
    book = Workbook()
    book.remove(book.active)
    return book


def row_of(sheet, values, bold=False, background=None, numeric_from=None):
    sheet.append(values)
    cells = sheet[sheet.max_row][: len(values)]
    for position, cell in enumerate(cells):
        cell.border = BOX
        if bold:
            cell.font = Font(bold=True)
        if background:
            cell.fill = fill(background)
        if numeric_from is not None and position >= numeric_from and isinstance(cell.value, (int, float)):
            cell.number_format = NUM
    return cells


def widths(sheet, values):
    for position, width in enumerate(values, start=1):
        sheet.column_dimensions[get_column_letter(position)].width = width


def kv(sheet, label, value):
    sheet.append([label, value])
    row = sheet[sheet.max_row]
    row[0].font = Font(bold=True)
    if isinstance(value, (int, float)):
        row[1].number_format = NUM


CRA_LABEL = {
    "en": {"minimal": "Minimal", "low": "Low", "low_sr": "Low (significant risk)", "moderate": "Moderate", "high": "High", "high_sr": "High (significant risk)"},
    "fr": {"minimal": "Minimal", "low": "Faible", "low_sr": "Faible (risque significatif)", "moderate": "Modéré", "high": "Élevé", "high_sr": "Élevé (risque significatif)"},
}
ASSURANCE_LABEL = {
    "en": {"little": "Little", "some": "Some", "corroborative": "Corroborative", "persuasive": "Persuasive"},
    "fr": {"little": "Faible", "some": "Moyenne", "corroborative": "Corroborante", "persuasive": "Probante"},
}


def tod_workbook(view, fr):
    """A cover, then one tab per lead index: parameters, key items in full, the representative
    MUS sample, with the columns the tester fills. Indexes with no ledger line are on the cover."""
    locale = "fr" if fr else "en"
    book = new_book()
    cover = book.create_sheet("Couverture" if fr else "Cover")
    widths(cover, [30, 50])
    cover.append(["Tests de détail : échantillonnage" if fr else "Tests of details: sampling"])
    cover["A1"].font = Font(bold=True, size=14)
    kv(cover, "Client", view["clientName"])
    kv(cover, "Exercice" if fr else "Fiscal year", view["fiscalYear"])
    kv(cover, "Clôture" if fr else "Period end", view["periodEnd"])
    kv(cover, "Devise" if fr else "Currency", "FCFA" if view["currency"] == "XAF" else view["currency"])
    kv(cover, "Préparé par" if fr else "Prepared by", view["preparer"])
    kv(cover, "Seuil de travail" if fr else "Performance materiality", view["te"])
    kv(cover, "Grand livre" if fr else "Ledger", view["ledgerFilename"])
    cover.append([])
    row_of(cover, ["Indice" if fr else "Index", "Taille / Population" if fr else "Size / Population"], bold=True, background=HDR)
    for sheet in view["sheets"]:
        row_of(cover, ["%s %s" % (sheet["indexCode"], sheet["labelFr" if fr else "labelEn"]), "%s / %s" % (sheet["plan"]["sampleSize"], sheet["plan"]["populationCount"])])
    if view["emptyIndexes"]:
        cover.append([])
        row_of(cover, ["Indices sans ligne au grand livre" if fr else "Indexes with no ledger line", ""], bold=True, background=BAND)
        for item in view["emptyIndexes"]:
            row_of(cover, [item["indexCode"], item["labelFr" if fr else "labelEn"]])

    head = (
        ["Réf.", "Compte", "Libellé", "Date", "Montant", "Testé par", "Résultat", "Écart", "Commentaire"]
        if fr else
        ["Ref.", "Account", "Description", "Date", "Amount", "Tested by", "Result", "Difference", "Comment"]
    )
    for sheet in view["sheets"]:
        plan = sheet["plan"]
        ws = book.create_sheet(tab("%s %s" % (sheet["indexCode"], sheet["labelFr" if fr else "labelEn"])))
        widths(ws, [18, 14, 40, 12, 16, 14, 12, 12, 34])
        ws.append(["%s — %s" % (sheet["indexCode"], sheet["labelFr" if fr else "labelEn"])])
        ws["A1"].font = Font(bold=True, size=12)
        cra = CRA_LABEL[locale].get(sheet["cra"], sheet["cra"])
        if not sheet["craFromS31"]:
            cra += " — valeur par défaut : S3.1 n'évalue pas ce compte" if fr else " — default: S3.1 does not assess this account"
        for label, value in (
            ("Évaluation combinée (S3.1)" if fr else "Combined assessment (S3.1)", cra),
            ("Seuil de travail" if fr else "Performance materiality", plan["te"]),
            ("Seuil des éléments clés" if fr else "Key-item threshold", plan["threshold"]),
            ("Assurance d'autres procédures" if fr else "Assurance from other procedures", ASSURANCE_LABEL[locale][sheet["assurance"]]),
            ("Population", plan["populationValue"]),
            ("Couverture des éléments clés %" if fr else "Key-item coverage %", plan["coveragePct"]),
            ("Facteur" if fr else "Factor", plan["factor"] if plan["factor"] is not None else "—"),
            ("Taille de l'échantillon" if fr else "Sample size", plan["sampleSize"]),
            ("Intervalle" if fr else "Interval", plan["interval"] if plan["interval"] is not None else "—"),
        ):
            kv(ws, label, value)
        ws.append([])
        row_of(ws, ["Éléments clés, examinés en totalité" if fr else "Key items, examined in full"] + [None] * 8, bold=True, background=BAND)
        row_of(ws, head, bold=True, background=HDR)
        for line in plan["keyItems"]:
            row_of(ws, [line.get("ref"), line.get("account"), line.get("description"), line.get("date"), line.get("amount"), None, None, None, None], background=KEY, numeric_from=4)
        ws.append([])
        row_of(ws, ["Échantillon représentatif (MUS)" if fr else "Representative sample (MUS)"] + [None] * 8, bold=True, background=BAND)
        row_of(ws, head, bold=True, background=HDR)
        for line in plan["sample"]:
            row_of(ws, [line.get("ref"), line.get("account"), line.get("description"), line.get("date"), line.get("amount"), None, None, None, None], background=SAMPLE, numeric_from=4)
    return to_bytes(book)


def toc_sample_workbook(view, fr):
    """One tab per control selected on S2.1: its attributes and the occurrences to test."""
    book = new_book()
    cover = book.create_sheet("Couverture" if fr else "Cover")
    widths(cover, [34, 24, 18, 14, 14])
    cover.append(["Tests de contrôles : échantillons" if fr else "Tests of controls: samples"])
    cover["A1"].font = Font(bold=True, size=14)
    kv(cover, "Client", view["clientName"])
    kv(cover, "Exercice" if fr else "Fiscal year", view["fiscalYear"])
    kv(cover, "Clôture" if fr else "Period end", view["periodEnd"])
    kv(cover, "Préparé par" if fr else "Prepared by", view["preparer"])
    cover.append([])
    row_of(cover, ["Contrôle" if fr else "Control", "SCOT", "Fréquence" if fr else "Frequency", "Population", "Taille" if fr else "Size"], bold=True, background=HDR)
    used = set()
    for control in view["controls"]:
        row_of(cover, [control["controlName"], control["scotName"], freq_label(control["frequency"], fr), control["population"], control["sampleSize"]])
        name = tab(control["controlName"]) or "Control"
        suffix = 2
        while name.lower() in used:
            name = "%s %d" % (tab(control["controlName"])[:27], suffix)
            suffix += 1
        used.add(name.lower())
        ws = book.create_sheet(name)
        widths(ws, [26, 18, 40, 14, 14, 34])
        ws.append([control["controlName"]])
        ws["A1"].font = Font(bold=True, size=12)
        kv(ws, "SCOT", control["scotName"])
        kv(ws, "Nature", type_short(control["controlType"], fr))
        kv(ws, "Fréquence" if fr else "Frequency", freq_label(control["frequency"], fr))
        kv(ws, "Assertions", ", ".join(control["assertions"]))
        kv(ws, "Population", control["population"])
        kv(ws, "Taille" if fr else "Size", control["sampleSize"])
        kv(ws, "Règle" if fr else "Rule", control["rule"])
        kv(ws, "Tiré le" if fr else "Drawn on", control["drawnAt"])
        ws.append([])
        row_of(ws, ["Occurrence", "Référence" if fr else "Reference", "Description", "Date", "Résultat" if fr else "Result", "Commentaire" if fr else "Comment"], bold=True, background=HDR)
        for item in control["items"]:
            row_of(ws, [item, None, None, None, None, None], background=ENTRY)
    return to_bytes(book)


JE_TESTS = {
    "en": ["Support obtained and agreed", "Business rationale understood", "Authorised by the right person", "Accounts and period appropriate"],
    "fr": ["Justificatif obtenu et rapproché", "Raison économique comprise", "Autorisée par la bonne personne", "Comptes et période appropriés"],
}
JE_LEVERS = {
    "en": ["Vary the timing of the procedures", "Select below the usual thresholds", "Test locations or accounts not usually visited", "Change the selection method from last year"],
    "fr": ["Varier le calendrier des procédures", "Sélectionner sous les seuils habituels", "Tester des sites ou comptes non visités d'ordinaire", "Modifier la méthode de sélection par rapport à N-1"],
}
JE_CONTROLS = {
    "en": ["Who may post a manual entry", "Review and approval of manual entries", "Segregation between preparation and approval", "Controls over the period-end close"],
    "fr": ["Qui peut passer une écriture manuelle", "Revue et approbation des écritures manuelles", "Séparation entre préparation et approbation", "Contrôles de la clôture de période"],
}


def je_workbook(view, fr):
    """E3.1, five tabs: cover, population, criteria, selection, exceptions. Never says "sampled at
    random". Cover cells typed once; the identity on the other tabs reads them by formula."""
    locale = "fr" if fr else "en"
    book = new_book()
    cover = book.create_sheet("1 Couverture" if fr else "1 Cover")
    widths(cover, [46, 60])
    cover.append(["E3.1 Écritures de journal" if fr else "E3.1 Journal entries"])
    cover["A1"].font = Font(bold=True, size=14)
    kv(cover, "Client", view["clientName"])
    kv(cover, "Exercice" if fr else "Fiscal year", view["fiscalYear"])
    kv(cover, "Clôture" if fr else "Period end", view["periodEnd"])
    kv(cover, "Préparé par" if fr else "Prepared by", view["preparer"])
    cover.append([])
    row_of(cover, ["Contexte du risque de fraude (ISA 240 ¶32)" if fr else "Fraud-risk context (ISA 240 ¶32)", ""], bold=True, background=BAND)
    row_of(cover, ["Risque de contournement des contrôles par la direction" if fr else "Risk of management override of controls", None], background=ENTRY)
    cover.append([])
    row_of(cover, ["Leviers d'imprévisibilité" if fr else "Unpredictability levers", "Retenu ? Comment" if fr else "Used? How"], bold=True, background=BAND)
    for text in JE_LEVERS[locale]:
        row_of(cover, [text, None], background=ENTRY)
    cover.append([])
    row_of(cover, ["Contrôles sur les écritures" if fr else "Controls over journal entries", "Constat" if fr else "Finding"], bold=True, background=BAND)
    for text in JE_CONTROLS[locale]:
        row_of(cover, [text, None], background=ENTRY)
    cover.append([])
    row_of(cover, ["Conclusion", None], bold=True, background=ENTRY)
    identity = "=\'%s\'!B2&\" — \"&\'%s\'!B4" % (cover.title, cover.title)

    population = book.create_sheet("2 Population")
    widths(population, [42, 14, 70])
    population.append([identity])
    population["A1"].font = Font(bold=True)
    ledger = view["ledger"]
    if ledger:
        kv(population, "Grand livre" if fr else "Ledger", ledger["filename"])
        kv(population, "SHA-256", ledger["sha256"])
        kv(population, "Lignes du fichier" if fr else "File rows", ledger["rows"])
        kv(population, "Lignes projetées" if fr else "Projected lines", ledger["lines"])
    else:
        population.append(["Aucun grand livre n'est enregistré sur ce dossier : rien n'a été sélectionné." if fr else "No ledger is registered on this file: nothing has been selected."])
    population.append([])
    row_of(population, ["Contrôle" if fr else "Check", "Statut" if fr else "Status", "Détail" if fr else "Detail"], bold=True, background=HDR)
    for check in view["checks"]:
        row_of(population, [check["labelFr" if fr else "labelEn"], check["status"], check["detailFr" if fr else "detailEn"]])

    result = view["result"]
    criteria = book.create_sheet("3 Critères" if fr else "3 Criteria")
    widths(criteria, [40, 60, 40, 12, 12])
    criteria.append([identity])
    criteria["A1"].font = Font(bold=True)
    row_of(criteria, ["Critère" if fr else "Criterion", "Description", "Paramètres" if fr else "Parameters", "Lignes" if fr else "Lines", "Écritures" if fr else "Entries"], bold=True, background=HDR)
    for row in (result or {}).get("criteria", []):
        settings = "; ".join(
            "%s=%s" % (key, ", ".join(value) if isinstance(value, list) else value)
            for key, value in row["settings"].items() if key != "uninformativeTerms"
        )
        row_of(criteria, [row["name"], row["description"], settings, row["matchedLines"], row["matchedEntries"]])

    selection = book.create_sheet("4 Sélection" if fr else "4 Selection")
    tests = JE_TESTS[locale]
    selection.append([identity])
    selection["A1"].font = Font(bold=True)
    if result and result["truncated"]:
        selection.append(["Limité à %d lignes sur %d sélectionnées." % (result["limit"], result["selectedLines"]) if fr else "Capped at %d lines of %d selected." % (result["limit"], result["selectedLines"])])
    head = ["Écriture", "Ligne", "Compte", "Date", "Montant", "Libellé", "Préparé par", "Motifs"] if fr else ["Entry", "Line", "Account", "Date", "Amount", "Description", "Prepared by", "Reasons"]
    row_of(selection, head + tests + ["Conclusion"], bold=True, background=HDR)
    widths(selection, [16, 8, 12, 12, 16, 36, 16, 70, 16, 16, 16, 16, 24])
    for line in (result or {}).get("lines", []):
        reasons = " | ".join("%s: %s" % (reason["label"], reason["detail"]) for reason in line["reasons"])
        row_of(
            selection,
            [line["jeNumber"], line["lineNo"], line["account"], line["journalDate"], line["signed"], line["lineDescription"] or line["jeDescription"], line["preparer"], reasons] + [None] * 5,
            numeric_from=4,
        )

    exceptions = book.create_sheet("5 Exceptions")
    widths(exceptions, [16, 16, 50, 16, 40])
    exceptions.append([identity])
    exceptions["A1"].font = Font(bold=True)
    row_of(exceptions, ["Écriture" if fr else "Entry", "Compte" if fr else "Account", "Constat" if fr else "Exception", "Montant" if fr else "Amount", "Suite donnée" if fr else "Follow-up"], bold=True, background=HDR)
    for _empty in range(10):
        row_of(exceptions, [None] * 5, background=ENTRY)
    return to_bytes(book)


def substantive_workbook(code, title, fr):
    """The generic substantive paper (F062): population, selection, tests, exceptions, conclusion."""
    book = new_book()
    ws = book.create_sheet(tab(code.replace(".", "-")))
    widths(ws, [10, 38, 16, 18, 18, 18, 28, 28])

    def band(text):
        row_of(ws, [text] + [None] * 7, bold=True, background=BAND)

    def entry(label):
        cells = row_of(ws, [label, None, None, None, None, None, None, None])
        for cell in cells[2:]:
            cell.fill = fill(ENTRY)

    ws.append([title])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([])
    band("Identification")
    for label in (("Client", "Exercice", "Préparé par", "Revu par") if fr else ("Client", "Fiscal year", "Prepared by", "Reviewed by")):
        entry(label)
    ws.append([])
    band("1. Population")
    for label in (
        ("Source de la population (IPE)", "Exhaustivité et exactitude vérifiées", "Valeur totale", "Nombre d'éléments") if fr else
        ("Source of the population (IPE)", "Completeness and accuracy checked", "Total value", "Number of items")
    ):
        entry(label)
    ws.append([])
    band("2. Sélection" if fr else "2. Selection")
    for label in (("Méthode", "Seuil des éléments clés", "Taille de l'échantillon") if fr else ("Method", "Key-item threshold", "Sample size")):
        entry(label)
    ws.append([])
    band("3. Tests")
    row_of(ws, (
        ["N°", "Élément testé", "Date", "Montant", "Attendu", "Constaté", "Écart", "Commentaire"] if fr else
        ["No.", "Item tested", "Date", "Amount", "Expected", "Found", "Difference", "Comment"]
    ), bold=True, background=HDR)
    for number in range(1, 26):
        row_of(ws, [number, None, None, None, None, None, None, None], background=ENTRY)
    ws.append([])
    band("4. Anomalies" if fr else "4. Exceptions")
    row_of(ws, (
        ["N°", "Description", "Montant", "Nature", "Extrapolation", "Corrigée", "Réf. C1.1", "Suite"] if fr else
        ["No.", "Description", "Amount", "Type", "Projection", "Corrected", "C1.1 ref.", "Follow-up"]
    ), bold=True, background=HDR)
    for number in range(1, 6):
        row_of(ws, [number, None, None, None, None, None, None, None], background=ENTRY)
    ws.append([])
    band("5. Conclusion")
    entry("Conclusion")
    return to_bytes(book)
