"""The firm's sign-off matrix as a workbook (F002), as lib/signoff-matrix.ts lays it out: a roles
sheet first, then the "Tasks" sheet, header in row 1, one task per row:

    A Code, B Phase, C Task (FR), D Task (EN), E Tier
    F Today's minimum preparer, G Today's minimum reviewer, H Partner sign-off today
    I Your minimum preparer, J Your minimum reviewer, K Partner sign-off required, L Comment

Import finds the sheet by its name and reads by column position, never by the header, which is
in the reader's language. Only I, J and K are saved; a blank cell is the firm default. No Odoo.
"""
import io
import re
import unicodedata

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.worksheet.datavalidation import DataValidation

MATRIX_SHEET = "Tasks"
_YES = {"yes", "y", "true", "1", "oui", "o", "vrai"}  # i18n: input
_NO = {"no", "n", "false", "0", "non", "faux"}  # i18n: input


def normalise(text):
    plain = "".join(c for c in unicodedata.normalize("NFD", str(text or "")) if not unicodedata.combining(c))
    return re.sub(r"[\s_-]+", " ", plain.replace("’", "'")).strip().lower()


def build_workbook(rows, words):
    """``rows``: dicts with the twelve columns as a list under "cells". ``words``: the sheet names,
    the headers and the role list, in the reader's language."""
    book = Workbook()
    roles = book.active
    roles.title = words["roles_sheet"]
    roles.append(words["roles_header"])
    for row in words["roles"]:
        roles.append(row)
    roles.append([])
    roles.append(["", words["blank_note"]])
    for cell in roles[1]:
        cell.font = Font(bold=True)
    sheet = book.create_sheet(MATRIX_SHEET)
    sheet.append(words["headers"])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    sheet.freeze_panes = "A2"
    for letter, width in zip("ABCDEFGHIJKL", (9, 14, 48, 48, 11, 16, 16, 14, 16, 16, 16, 30)):
        sheet.column_dimensions[letter].width = width
    for row in rows:
        sheet.append(row)
    last = max(len(rows) + 1, 2)
    role_list = DataValidation(type="list", formula1='"%s"' % ",".join(words["role_labels"]), allow_blank=True)
    yes_no = DataValidation(type="list", formula1='"%s"' % ",".join(words["yes_no"]), allow_blank=True)
    sheet.add_data_validation(role_list)
    sheet.add_data_validation(yes_no)
    role_list.add("I2:J%d" % last)
    yes_no.add("K2:K%d" % last)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


class MatrixFileError(Exception):
    """The file is not a matrix at all: ``code`` is "unreadable" or "no-sheet"."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _text(value):
    return "" if value is None else str(value).strip()


def parse_workbook(content, known_codes, role_lookup):
    """(rules, errors). ``rules``: dicts as save_task_rules takes them. ``errors``: (row, kind, value),
    kind one of unknown-code, duplicate, bad-preparer, bad-reviewer, bad-yes-no. The caller
    saves nothing when there is any error."""
    try:
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as error:
        raise MatrixFileError("unreadable") from error
    sheet = next((s for s in book.worksheets if s.title.strip().lower() == MATRIX_SHEET.lower()), None)
    if sheet is None:
        raise MatrixFileError("no-sheet")
    rules, errors, seen = [], [], set()
    for number, cells in enumerate(sheet.iter_rows(values_only=True), start=1):
        if number == 1:
            continue
        cells = list(cells) + [None] * 11
        code, preparer, reviewer, partner = _text(cells[0]), _text(cells[8]), _text(cells[9]), _text(cells[10])
        if not (code or preparer or reviewer or partner):
            continue
        problems = []
        if code not in known_codes:
            problems.append((number, "unknown-code", code))
        elif code in seen:
            problems.append((number, "duplicate", code))
        seen.add(code)
        min_preparer = role_lookup.get(normalise(preparer)) if preparer else None
        if preparer and not min_preparer:
            problems.append((number, "bad-preparer", preparer))
        min_reviewer = role_lookup.get(normalise(reviewer)) if reviewer else None
        if reviewer and not min_reviewer:
            problems.append((number, "bad-reviewer", reviewer))
        answer = normalise(partner)
        partner_required = None
        if answer in _YES:
            partner_required = True
        elif answer in _NO:
            partner_required = False
        elif answer:
            problems.append((number, "bad-yes-no", partner))
        if problems:
            errors.extend(problems)
            continue
        rules.append({
            "code": code, "min_preparer": min_preparer, "min_reviewer": min_reviewer,
            "partner_required": partner_required,
        })
    return rules, errors
