"""CSV and XLSX to the {headers, rows} table services/subledgers.py defines.

Outside services/ because it needs openpyxl and the file's bytes. No Odoo here.
"""
import io
from datetime import date, datetime

from .services.errors import SubLedgerError
from .services.subledgers import TabularRow, _header_line_index, csv_lines, detect_csv_delimiter, parse_csv


def _decode(content):
    """Excel on a French Windows writes CP1252, and a UTF-8 file often opens with a BOM."""
    if isinstance(content, str):
        return content.removeprefix("﻿")
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1252", "replace")


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == datetime.min.time() else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _parse_xlsx(content, header_row, sheet_name=None):
    from openpyxl import load_workbook  # comes with Odoo 19; the pure tests do not need it

    try:
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        # the first sheet, unless a person chose another one that the file does hold
        sheet = book[sheet_name] if sheet_name and sheet_name in book.sheetnames else book.worksheets[0]
        lines = []
        for line_no, cells in enumerate(sheet.iter_rows(values_only=True), start=1):
            texts = [_cell_text(cell) for cell in cells]
            if any(texts):
                lines.append((line_no, texts))
    except Exception as error:  # openpyxl raises many types on a corrupt or renamed file
        raise SubLedgerError("unreadable-file") from error
    if len(lines) < (2 if header_row else 1):
        raise SubLedgerError("empty-file")
    if header_row:
        header_at = _header_line_index([texts for _no, texts in lines])
        if len(lines) < header_at + 2:
            raise SubLedgerError("empty-file")
        headers = [header or "col_%d" % (index + 1) for index, header in enumerate(lines[header_at][1])]
        start = header_at + 1
    else:
        headers = ["col_%d" % (index + 1) for index in range(max(len(texts) for _no, texts in lines[:25]))]
        start = 0
    rows = []
    for line_no, texts in lines[start:]:
        row = TabularRow()
        for index, header in enumerate(headers):
            row[header] = texts[index] if index < len(texts) else ""
        row.source_row = line_no
        rows.append(row)
    return {"headers": headers, "rows": rows}


def parse_table(filename, content, header_row=True, sheet=None, delimiter=None):
    """``sheet`` (Excel) and ``delimiter`` (CSV) are a person's choices over the reader's own:
    the first sheet, and the separator the lines suggest."""
    lower = (filename or "").lower()
    if lower.endswith(".xlsx"):
        return _parse_xlsx(content, header_row, sheet)
    if lower.endswith(".csv") or lower.endswith(".txt"):
        return parse_csv(_decode(content), header_row, delimiter)
    raise SubLedgerError("unsupported-file")


def sheet_names(filename, content):
    """The sheets of an Excel file, in the file's order; nothing for a CSV."""
    if not (filename or "").lower().endswith(".xlsx"):
        return []
    from openpyxl import load_workbook

    try:
        return list(load_workbook(io.BytesIO(content), read_only=True, data_only=True).sheetnames)
    except Exception as error:
        raise SubLedgerError("unreadable-file") from error


def found_delimiter(filename, content):
    """The separator a CSV's own lines suggest; None for an Excel file."""
    lower = (filename or "").lower()
    if not (lower.endswith(".csv") or lower.endswith(".txt")):
        return None
    return detect_csv_delimiter(csv_lines(_decode(content)))
