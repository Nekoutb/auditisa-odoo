"""lib/subledgers.ts: the CSV reader and amount-column detection, without the DB.

The .xlsx branch of parseTabularFile is not here: it is ExcelJS cell handling and
belongs with the import layer, on whatever spreadsheet reader that layer uses.
"""
import re
import unicodedata

from ._js import js_trim
from .amount import parse_amount
from .errors import SubLedgerError
from .subledger_kinds import SUB_LEDGER_KINDS, is_sub_ledger_kind  # noqa: F401 (the source re-exports them)

_CSV_DELIMITERS = (";", ",", "\t", "|")
_AMOUNT_HINTS = ("amount", "balance", "solde", "montant", "total", "net", "nbv", "value", "valeur")
_COMBINING = re.compile("[̀-ͯ]")
_NEWLINES = re.compile(r"\r\n?")


class TabularRow(dict):
    """A parsed record. ``source_row`` is the physical file row it came from (the
    source's non-enumerable __row): it never becomes a column, messages point at it."""

    source_row = None


def source_row_of(record):
    """The physical file row a parsed record came from, None when it has none."""
    return getattr(record, "source_row", None)


def _count_outside_quotes(line, delimiter):
    n = 0
    quoted = False
    for char in line:
        if char == '"':
            quoted = not quoted
        elif not quoted and char == delimiter:
            n += 1
    return n


def detect_csv_delimiter(lines):
    """One delimiter per file: the candidate that splits the most lines into the same,
    widest shape. Splitting on both ',' and ';' cost the credits of "10 000 000,00" (B27)."""
    sample = lines[:25]
    best_delimiter = ","
    best_score = -1
    for delimiter in _CSV_DELIMITERS:
        counts = [n for n in (_count_outside_quotes(line, delimiter) for line in sample) if n > 0]
        if not counts:
            continue
        # the width most lines agree on, weighted by how many lines agree
        modal = {}
        for n in counts:
            modal[n] = modal.get(n, 0) + 1
        width, agree = sorted(modal.items(), key=lambda kv: (-kv[1], -kv[0]))[0]
        score = agree * 1000 + width
        if score > best_score:
            best_delimiter = delimiter
            best_score = score
    return best_delimiter


def split_csv_line(line, delimiter):
    cells = []
    current = []
    quoted = False
    i = 0
    n = len(line)
    while i < n:
        char = line[i]
        if quoted:
            if char == '"' and i + 1 < n and line[i + 1] == '"':
                current.append('"')
                i += 1
            elif char == '"':
                quoted = False
            else:
                current.append(char)
        elif char == '"':
            quoted = True
        elif char == delimiter:
            cells.append("".join(current))
            current = []
        else:
            current.append(char)
        i += 1
    cells.append("".join(current))
    return [js_trim(cell) for cell in cells]


def _header_line_index(cells_by_line):
    """The first line with at least two non-empty cells, never blindly line 1 (B28)."""
    for i in range(min(len(cells_by_line), 25)):
        if len([cell for cell in cells_by_line[i] if cell != ""]) >= 2:
            return i
    return 0


def csv_lines(text):
    """The lines of a CSV text that hold something."""
    return [line for line in _NEWLINES.sub("\n", text).split("\n") if len(js_trim(line)) > 0]


def parse_csv(text, header_row=True, delimiter=None):
    """{headers, rows}. Without a header row every line is data, under col_N names.
    ``delimiter`` is a person's choice over the one the file suggests."""
    all_lines = _NEWLINES.sub("\n", text).split("\n")
    line_nos = [index + 1 for index, line in enumerate(all_lines) if len(js_trim(line)) > 0]
    lines = [line for line in all_lines if len(js_trim(line)) > 0]
    if len(lines) < (2 if header_row else 1):
        raise SubLedgerError("empty-file")
    delimiter = delimiter if delimiter in _CSV_DELIMITERS else detect_csv_delimiter(lines)

    def split(line):
        return split_csv_line(line, delimiter)

    header_at = _header_line_index([split(line) for line in lines]) if header_row else 0
    if header_row and len(lines) < header_at + 2:
        raise SubLedgerError("empty-file")
    if header_row:
        headers = [header or "col_%d" % (index + 1) for index, header in enumerate(split(lines[header_at]))]
    else:
        width = max(len(split(line)) for line in lines[:25])
        headers = ["col_%d" % (index + 1) for index in range(width)]
    start = header_at + 1 if header_row else 0
    rows = []
    for offset, line in enumerate(lines[start:]):
        cells = split(line)
        row = TabularRow()
        for index, header in enumerate(headers):
            row[header] = cells[index] if index < len(cells) else ""
        row.source_row = line_nos[start + offset]
        rows.append(row)
    return {"headers": headers, "rows": rows}


def parse_tabular_file(filename, content, header_row=True):
    """CSV and text files. An .xlsx file is the import layer's to read (see above)."""
    lower = filename.lower()
    if lower.endswith(".csv") or lower.endswith(".txt"):
        text = content if isinstance(content, str) else content.decode("utf-8", "replace")
        return parse_csv(text, header_row)
    if lower.endswith(".xlsx"):
        raise NotImplementedError("xlsx parsing belongs to the import layer")
    raise SubLedgerError("unsupported-file")


def detect_amount_column(table):
    """The amount column: a named hint first, else the most numeric column."""

    def normalized(header):
        return _COMBINING.sub("", unicodedata.normalize("NFD", header.lower()))

    for header in table["headers"]:
        if any(hint in normalized(header) for hint in _AMOUNT_HINTS):
            return header
    best = None
    best_score = 0
    for header in table["headers"]:
        score = 0
        for row in table["rows"]:
            if parse_amount(row.get(header)) is not None:
                score += 1
        if score > best_score:
            best = header
            best_score = score
    return best if best is not None and best_score >= max(1, len(table["rows"]) / 2) else None
