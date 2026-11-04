"""The Excel workbooks. Plain openpyxl on plain data: no Odoo here.

lead_schedule_workbook and sad_workbook keep the sheets, columns, colours and arithmetic of
app/api/engagements/[id]/lead-schedule-export and sad/export. simple_workbook is the rest.
"""
import io
import re

from .services.lead_classes import account_class_label, account_type_label, lead_index_label
from .services.materiality_model import uncorrected_misstatement_threshold
from .services.sad_model import SAD_COLUMN_COUNT, caption_column
from .services.sad_view import MAIN_TYPES, entry_amount, grid_totals, is_trivial, uncorrected_cascade

HDR = "D9D9D9"
BAND = "C0C0C0"
YEL = "FFFF99"
MONEY = "#,##0;(#,##0)"
PCT = "0.00%"


def _styles():
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    thin = Side(style="thin", color="999999")
    return {
        "Alignment": Alignment,
        "Font": Font,
        "fill": lambda argb: PatternFill("solid", fgColor=argb),
        "box": Border(top=thin, left=thin, bottom=thin, right=thin),
        "double_top": Border(top=Side(style="double")),
        "bottom": Border(bottom=Side(style="thin")),
    }


def _book():
    from openpyxl import Workbook

    book = Workbook()
    book.remove(book.active)
    return book


def _bytes(book):
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _tab_name(text):
    return re.sub(r"[\\/*?:\[\]]", " ", text)[:31]


def simple_workbook(sheet_name, headers, rows, title=None):
    """A flat register: header row, one line per record, frozen, filterable."""
    style = _styles()
    book = _book()
    sheet = book.create_sheet(_tab_name(sheet_name))
    if title:
        sheet.append([title])
        sheet.cell(sheet.max_row, 1).font = style["Font"](bold=True, size=13)
        sheet.append([])
    sheet.append(headers)
    head_row = sheet.max_row
    for cell in sheet[head_row]:
        cell.font = style["Font"](bold=True)
        cell.fill = style["fill"](HDR)
        cell.border = style["box"]
    for row in rows:
        sheet.append(list(row))
    for index, header in enumerate(headers, start=1):
        sheet.column_dimensions[sheet.cell(head_row, index).column_letter].width = max(12, min(44, len(str(header)) + 6))
    sheet.freeze_panes = sheet.cell(head_row + 1, 1)
    sheet.auto_filter.ref = "A%d:%s%d" % (head_row, sheet.cell(head_row, len(headers)).column_letter, sheet.max_row)
    return _bytes(book)


def lead_schedule_workbook(schedules, comments, identity, fr):
    """An Introduction tab, then one tab per index: Current Y, Prior Y, movement, variance, commentary."""
    style = _styles()
    locale = "fr" if fr else "en"
    book = _book()
    intro = book.create_sheet("Introduction")
    intro.column_dimensions["A"].width = 28
    intro.column_dimensions["B"].width = 60
    intro.append(["Feuilles maîtresses" if fr else "Lead Schedules"])
    intro["A1"].font = style["Font"](bold=True, size=14)
    intro.append([])
    intro.append(["Mission" if fr else "Engagement", identity["engagement"]])
    intro.append(["Client", identity["client"]])
    intro.append(["Date de clôture" if fr else "Period end", identity["period_end"]])
    intro.append(["Généré le" if fr else "Generated", identity["generated"]])
    intro.append([])
    intro.append([
        "Contenu" if fr else "Contents",
        (
            "Un onglet par indice de feuille maîtresse ; soldes issus de la balance pré-audit ; l'exercice N-1 "
            "est la balance N-1 si elle est importée, sinon le solde d'ouverture."
        ) if fr else (
            "One tab per lead-schedule index; balances from the pre-audit trial balance; Prior Y is the "
            "prior-year trial balance when imported, otherwise the opening balance."
        ),
    ])
    intro.append([])

    def label(definition):
        return lead_index_label(definition, locale)

    def kind(definition):
        return "%s · %s" % (account_type_label(definition["accountType"], locale), account_class_label(definition["accountClass"], locale))

    for schedule in schedules:
        definition = schedule["definition"]
        intro.append([definition["code"], "%s — %s" % (label(definition), kind(definition))])
    head = (
        ["Compte", "Intitulé", "Classe de compte", "Type de compte", "Exercice N", "Exercice N-1", "Mouvement", "Variation %", "Commentaire"]
        if fr else
        ["Account", "Description", "Account class", "Account type", "Current Y", "Prior Y", "Movement", "Variance %", "Commentary"]
    )
    widths = (12, 34, 22, 14, 16, 16, 16, 11, 44)
    for schedule in schedules:
        definition = schedule["definition"]
        code = definition["code"]
        sheet = book.create_sheet(_tab_name("%s %s" % (code, label(definition))))
        for index, width in enumerate(widths, start=1):
            sheet.column_dimensions[sheet.cell(1, index).column_letter].width = width
        sheet.append(["%s — %s" % (code, label(definition)), "", kind(definition)])
        for cell in sheet[1]:
            cell.font = style["Font"](bold=True, size=12)
        sheet.append([])
        sheet.append(head)
        for cell in sheet[3]:
            cell.font = style["Font"](bold=True)
            cell.fill = style["fill"]("EFEFEF")
            cell.border = style["bottom"]
        for row in schedule["accounts"]:
            sheet.append([
                row["account"], row["name"], account_class_label(definition["accountClass"], locale),
                account_type_label(definition["accountType"], locale), row["closing"], row["prior"], row["movement"],
                row["variancePct"] / 100 if row["variancePct"] is not None else None,
                comments.get("%s|%s" % (code, row["account"]), ""),
            ])
        sheet.append([
            "TOTAL", "%s — %s" % (code, label(definition)), "", "", schedule["closing"], schedule["prior"], schedule["movement"],
            schedule["variancePct"] / 100 if schedule["variancePct"] is not None else None,
            comments.get("%s|total" % code, ""),
        ])
        for cell in sheet[sheet.max_row]:
            cell.font = style["Font"](bold=True)
            cell.border = style["double_top"]
        for line in sheet.iter_rows(min_row=4, min_col=5, max_col=8):
            for cell in line[:3]:
                cell.number_format = "#,##0"
            line[3].number_format = "0.0%"
    return _bytes(book)


def sad_workbook(view, fr):
    """The firm's SAD workbook, six tabs: uncorrected, corrected, conclusion, reclassifications,
    cash flow, disclosures. The same arithmetic as the screen (services/sad_view.py)."""
    style = _styles()
    fill = style["fill"]
    box = style["box"]
    font = style["Font"]
    wrap = style["Alignment"](wrap_text=True, vertical="top")
    book = _book()
    mat = view["materiality"]
    meta = view["meta"]
    cols = (
        ["Actif courant", "Actif non courant", "Passif courant", "Passif non courant", "Capitaux propres", "Résultat"]
        if fr else
        ["Assets Current", "Assets Non-current", "Liabilities Current", "Liabilities Non-current", "Equity components", "Income statement"]
    )

    def add(sheet, values):
        sheet.append(values)
        return sheet[sheet.max_row]

    def band(sheet, title):
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.oddFooter.left.text = view["entityName"]
        sheet.oddFooter.center.text = title
        sheet.oddFooter.right.text = "&P / &N"
        add(sheet, [title])[0].font = font(bold=True, size=13)
        first = add(sheet, [
            "Entité :" if fr else "Entity:", view["entityName"], "Clôture :" if fr else "Period ended:", view["periodEnd"],
            "Devise :" if fr else "Currency:", "FCFA",
        ])
        second = add(sheet, [
            "Seuil global :" if fr else "Overall materiality:", mat["overall"] if mat else "",
            "Seuil de travail :" if fr else "Performance materiality:", mat["performance"] if mat else "",
            "Manifestement négligeable :" if fr else "Clearly trivial:", mat["trivial"] if mat else "",
        ])
        for row in (first, second):
            for cell in row[:6]:
                cell.border = box
            for cell in (row[0], row[2], row[4]):
                cell.font = font(bold=True)
                cell.fill = fill(HDR)
            for cell in (row[1], row[3], row[5]):
                if isinstance(cell.value, (int, float)):
                    cell.number_format = MONEY
        sheet.append([])

    def widths(sheet, values):
        for index, width in enumerate(values, start=1):
            sheet.column_dimensions[sheet.cell(1, index).column_letter].width = width

    def grid_head(sheet, rationale):
        head = add(sheet, [
            "No.", "Réf. papier" if fr else "W/P ref.", "Compte / description" if fr else "Account / description",
            *cols, *(["Justification" if fr else "Rationale"] if rationale else []),
        ])
        for cell in head:
            cell.fill = fill(HDR)
            cell.border = box
            cell.font = font(bold=True, size=9)
            cell.alignment = wrap
        widths(sheet, [5, 12, 42, *[15] * len(cols), *([34] if rationale else [])])

    def entry_rows(sheet, entries, rationale, bands):
        span = 3 + SAD_COLUMN_COUNT + (1 if rationale else 0)
        groups = [
            ("Anomalies avérées :" if fr else "Factual misstatements:", [e for e in entries if e["mtype"] == "factual"]),
            ("Anomalies de jugement :" if fr else "Judgmental misstatements:", [e for e in entries if e["mtype"] == "judgmental"]),
            ("Anomalies extrapolées :" if fr else "Projected misstatements:", [e for e in entries if e["mtype"] == "projected"]),
        ] if bands else [("", entries)]
        for label, rows in groups:
            if label:
                row = add(sheet, [label] + [None] * (span - 1))
                for cell in row:
                    cell.fill = fill(BAND)
                    cell.border = box
                row[0].font = font(bold=True)
            for position, entry in enumerate(rows, start=1):
                head = [position, entry["taskCode"], entry["finding"] or entry["taskTitle"]] + [None] * (span - 3)
                if rationale:
                    head[span - 1] = entry["rationale"]
                row = add(sheet, head)
                for cell in row:
                    cell.fill = fill(YEL)
                    cell.border = box
                row[0].font = font(bold=True)
                row[2].font = font(bold=True)
                for side in ("dr", "cr"):
                    column = caption_column(entry["drCaption"] if side == "dr" else entry["crCaption"])
                    amount = entry["drAmount"] if side == "dr" else -entry["crAmount"]
                    values = [position, entry["ref"] or entry["taskCode"], entry["drAccount"] if side == "dr" else entry["crAccount"]]
                    values += [amount if index == column else None for index in range(SAD_COLUMN_COUNT)]
                    if rationale:
                        values.append(None)
                    row = add(sheet, values)
                    for cell in row:
                        cell.fill = fill(YEL)
                        cell.border = box
                    for cell in row[3:3 + SAD_COLUMN_COUNT]:
                        cell.number_format = MONEY
        totals = grid_totals(entries)
        row = add(sheet, ["Total", "", "", *totals])
        for cell in row:
            cell.font = font(bold=True)
            cell.border = box
        for cell in row[3:]:
            cell.number_format = MONEY
        captions = view["fsCaptions"]
        row = add(sheet, [
            "Montants des états financiers" if fr else "Financial statement amounts", "", "",
            *(captions if captions else [None] * SAD_COLUMN_COUNT),
        ])
        for cell in row:
            cell.border = box
        for cell in row[3:]:
            cell.number_format = MONEY
        row = add(sheet, [
            "Effet des anomalies (% des états financiers)" if fr else "Effect of misstatements as a % of FS amounts", "", "",
            *[(total / captions[index] if captions and captions[index] else None) for index, total in enumerate(totals)],
        ])
        for cell in row:
            cell.border = box
        for cell in row[3:]:
            cell.number_format = PCT
        return totals

    # 1. Uncorrected
    sheet = book.create_sheet("SAD non corrigées" if fr else "SAD uncorrected")
    band(sheet, "Récapitulatif des anomalies non corrigées" if fr else "Summary of uncorrected misstatements")
    grid_head(sheet, False)
    nominal = mat["trivial"] if mat else None
    entries = view["entries"]
    uncorrected = [e for e in entries if not e["corrected"] and e["mtype"] in MAIN_TYPES and not is_trivial(e, nominal)]
    totals = entry_rows(sheet, uncorrected, False, True)
    trivial_entries = [e for e in entries if e["mtype"] in MAIN_TYPES and is_trivial(e, nominal)]
    if trivial_entries:
        sheet.append([])
        row = add(sheet, [
            (
                "Anomalies manifestement négligeables — inférieures au nominal de %s, non cumulées (ISA 450 ¶5)"
                if fr else
                "Clearly trivial misstatements — below the nominal amount of %s, not accumulated (ISA 450 ¶5)"
            ) % nominal,
        ] + [None] * (2 + SAD_COLUMN_COUNT))
        for cell in row:
            cell.fill = fill(BAND)
            cell.border = box
        row[0].font = font(bold=True)
        for position, entry in enumerate(trivial_entries, start=1):
            suffix = (" (corrigée)" if fr else " (corrected)") if entry["corrected"] else ""
            row = add(sheet, [position, entry["taskCode"], "%s%s" % (entry["finding"] or entry["taskTitle"], suffix), entry_amount(entry)])
            for cell in row:
                cell.border = box
            row[3].number_format = MONEY
    cumulative_is = totals[5]
    cascade = uncorrected_cascade(cumulative_is, meta)
    income_after_tax = meta.get("income_after_tax") or None
    sheet.append([])
    for label, value, bold in (
        ("Anomalies non corrigées avant impôt" if fr else "Uncorrected misstatements before tax", cumulative_is, True),
        ("%s (%.0f%%)" % ("Moins : effet d'impôt" if fr else "Less: tax effect of misstatements", cascade["rate"] * 100), cascade["taxEffect"], False),
        ("Anomalies non corrigées en résultat après impôt" if fr else "Uncorrected misstatements in income after tax", cascade["afterTax"], True),
        ("Effet de retournement N-1 — avérées et extrapolées" if fr else "Turnaround effect of prior period — factual and projected", cascade["turnaroundFactual"], False),
        ("Effet de retournement N-1 — de jugement (note 2)" if fr else "Turnaround effect of prior period — judgmental (note 2)", cascade["turnaroundJudgmental"], False),
        ("Effet cumulé des anomalies non corrigées (après impôt)" if fr else "Cumulative effect of uncorrected misstatements (after tax)", cascade["cumulative"], True),
        ("Résultat de l'exercice avant impôt" if fr else "Current year income before tax", view["incomeBeforeTax"], False),
        ("Résultat de l'exercice après impôt" if fr else "Current year income after tax", income_after_tax, False),
    ):
        row = add(sheet, [label, "", "", value])
        row[3].number_format = MONEY
        row[0].border = box
        row[3].border = box
        if bold:
            for cell in row:
                cell.font = font(bold=True)

    # 2. Corrected
    sheet = book.create_sheet("SAD corrigées" if fr else "SAD corrected")
    band(sheet, "Récapitulatif des anomalies corrigées" if fr else "Summary of corrected misstatements")
    grid_head(sheet, True)
    entry_rows(sheet, [e for e in entries if e["corrected"] and e["mtype"] in MAIN_TYPES and not is_trivial(e, nominal)], True, True)

    # 3. Conclusion
    sheet = book.create_sheet("Conclusion SAD" if fr else "SAD conclusion")
    band(sheet, "Conclusion du récapitulatif des anomalies" if fr else "Summary of audit differences conclusion")
    widths(sheet, [58, 18, 18, 18, 18])
    first = add(sheet, ["", "Avant impôt" if fr else "Before tax", "", "Après impôt" if fr else "After tax", ""])
    before, after = ("Avant retournement", "Après retournement") if fr else ("Before turnaround", "After turnaround")
    second = add(sheet, ["", before, after, before, after])
    for row in (first, second):
        for cell in row:
            cell.fill = fill(HDR)
            cell.border = box
            cell.font = font(bold=True, size=9)
    threshold = uncorrected_misstatement_threshold(mat)
    series = cascade["series"]
    income = view["incomeBeforeTax"]
    row = add(sheet, ["Effet cumulé sur le résultat des anomalies non corrigées" if fr else "Cumulative income effect of uncorrected misstatements", *series])
    for cell in row:
        cell.border = box
    for cell in row[1:]:
        cell.number_format = MONEY
    row = add(sheet, ["Résultat de l'exercice (avant / après impôt)" if fr else "Current year income (before / after tax)", income, income, income_after_tax, income_after_tax])
    for cell in row:
        cell.border = box
    for cell in row[1:]:
        cell.number_format = MONEY
    row = add(sheet, [
        "Anomalies en % du résultat" if fr else "Misstatements as a percentage of income",
        cumulative_is / income if income else None,
        series[1] / income if income else None,
        series[2] / income_after_tax if income_after_tax else None,
        series[3] / income_after_tax if income_after_tax else None,
    ])
    for cell in row:
        cell.border = box
    for cell in row[1:]:
        cell.number_format = PCT
    for label, value in (
        ("Seuil de signification global" if fr else "Overall materiality", mat["overall"] if mat else None),
        ("Seuil des anomalies non corrigées (seuil global − seuil de travail)" if fr else "Uncorrected misstatements threshold (overall − performance)", threshold),
    ):
        row = add(sheet, [label, value])
        row[1].number_format = MONEY
        row[0].border = box
        row[1].border = box
    yes, no = ("Oui", "Non") if fr else ("Yes", "No")
    row = add(sheet, [
        "Les anomalies non corrigées dépassent-elles le seuil ?" if fr else "Do uncorrected misstatements exceed the threshold?",
        *[("—" if threshold is None else yes if abs(value) > threshold else no) for value in series],
    ])
    for index, cell in enumerate(row):
        cell.border = box
        cell.font = font(bold=True)
        if index == 0:
            cell.fill = fill(HDR)
        else:
            cell.fill = fill("FFC0C0" if threshold is not None and abs(series[index - 1]) > threshold else "C6EFCE")
    sheet.append([])
    head = add(sheet, ["Facteurs qualitatifs" if fr else "Qualitative factors", "Oui/Non/N-A" if fr else "Yes/No/N/A", "Commentaire" if fr else "Comment"])
    for cell in head:
        cell.fill = fill(HDR)
        cell.border = box
        cell.font = font(bold=True)
    questions = (
        [
            "1. Anomalies sensibles au regard des circonstances de l'entité", "2. Anomalies masquant un changement de tendance",
            "3. Biais possible de la direction", "4. Anomalies intentionnelles (fraude potentielle)",
            "5. Effet significatif des anomalies des exercices antérieurs",
        ] if fr else [
            "1. Misstatements sensitive in the entity's circumstances", "2. Misstatements masking a change in earnings or other trends",
            "3. Possible management bias", "4. Intentional misstatements (possible fraud)",
            "5. Material effect of prior-period uncorrected misstatements",
        ]
    )
    answers = {"yes": yes, "no": no, "na": "N/A"}
    for position, text in enumerate(questions, start=1):
        row = add(sheet, [text, answers.get(meta.get("tq_%d" % position), ""), meta.get("tq_%dc" % position) or ""])
        for index, cell in enumerate(row):
            cell.border = box
            cell.alignment = wrap
            if index:
                cell.fill = fill(YEL)
    sheet.append([])
    row = add(sheet, ["Conclusion de l'équipe" if fr else "Team conclusion", meta.get("concl_text") or ""])
    row[0].font = font(bold=True)
    row[1].alignment = style["Alignment"](wrap_text=True)
    sheet.merge_cells(start_row=row[0].row, start_column=2, end_row=row[0].row, end_column=5)

    # 4. Reclassifications
    sheet = book.create_sheet("Reclassements" if fr else "Reclassification missts")
    band(sheet, "Récapitulatif des reclassements" if fr else "Reclassification misstatements summary")
    grid_head(sheet, True)
    entry_rows(sheet, [e for e in entries if e["mtype"] == "classification"], True, False)

    # 5. Cash flow
    sheet = book.create_sheet("Flux de trésorerie" if fr else "Cash flow missts")
    band(sheet, "Anomalies du tableau des flux de trésorerie" if fr else "Cash flow misstatements schedule")
    head = add(sheet, [
        "No.", "Réf." if fr else "W/P ref.", "Ligne du tableau des flux" if fr else "Statement of cash flows line",
        "Exploitation" if fr else "Operating", "Investissement" if fr else "Investing", "Financement" if fr else "Financing",
        "Évaluation et conclusion" if fr else "Evaluation and conclusion",
    ])
    for cell in head:
        cell.fill = fill(HDR)
        cell.border = box
        cell.font = font(bold=True, size=9)
        cell.alignment = wrap
    widths(sheet, [5, 12, 40, 16, 16, 16, 44])
    operating = investing = financing = 0
    for item in view["cfRows"]:
        row = add(sheet, [item["no"], item["ref"], item["line"], item["operating"], item["investing"], item["financing"], item["evaluation"]])
        operating += item["operating"]
        investing += item["investing"]
        financing += item["financing"]
        for index, cell in enumerate(row):
            cell.fill = fill(YEL)
            cell.border = box
            if 3 <= index <= 5:
                cell.number_format = MONEY
            if index == 6:
                cell.alignment = wrap
    row = add(sheet, ["Total des anomalies non corrigées des flux" if fr else "Total of uncorrected cash flow misstatements", "", "", operating, investing, financing])
    for index, cell in enumerate(row):
        cell.font = font(bold=True)
        cell.border = box
        if index >= 3:
            cell.number_format = MONEY

    # 6. Disclosures
    sheet = book.create_sheet("Informations annexes" if fr else "Missts in disclosures")
    band(sheet, "Anomalies dans les informations annexes" if fr else "Schedule of misstatements in disclosures")
    widths(sheet, [5, 14, 46, 26, 40])
    for corrected in (False, True):
        title = (
            ("Anomalies corrigées dans les annexes" if fr else "Corrected misstatements in disclosures")
            if corrected else
            ("Anomalies non corrigées dans les annexes" if fr else "Uncorrected misstatements in disclosures")
        )
        row = add(sheet, [title, None, None, None, None])
        for cell in row:
            cell.fill = fill(BAND)
            cell.border = box
        row[0].font = font(bold=True)
        head = add(sheet, [
            "No.", "Réf. note" if fr else "FN reference", "Description de l'anomalie" if fr else "Description of misstatement",
            "Référence normative" if fr else "Authoritative guidance", "Évaluation et conclusion" if fr else "Evaluation and conclusion",
        ])
        for cell in head:
            cell.fill = fill(HDR)
            cell.border = box
            cell.font = font(bold=True, size=9)
            cell.alignment = wrap
        for item in view["discRows"]:
            if bool(item["corrected"]) != corrected:
                continue
            row = add(sheet, [item["no"], item["fn"], item["description"], item["guidance"], item["evaluation"]])
            for cell in row:
                cell.fill = fill(YEL)
                cell.border = box
                cell.alignment = wrap
        sheet.append([])
    return _bytes(book)
