"""The Excel report: real dates shown DD/MM/YYYY, real numbers. openpyxl only."""
import io

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

_HEAD = PatternFill("solid", fgColor="E4F2EC")


def report_workbook(sheets):
    """``sheets``: (tab title, headers, rows), in tab order."""
    book = Workbook()
    book.remove(book.active)
    for title, headers, rows in sheets:
        sheet = book.create_sheet(title[:31])
        sheet.append(headers)
        for cell in sheet[1]:
            cell.font = Font(bold=True)
            cell.fill = _HEAD
        for row in rows:
            sheet.append(list(row))
            for cell in sheet[sheet.max_row]:
                if hasattr(cell.value, "isoformat"):
                    cell.number_format = "DD/MM/YYYY"
                elif isinstance(cell.value, float):
                    cell.number_format = "0.00"
        for index, header in enumerate(headers, start=1):
            sheet.column_dimensions[sheet.cell(1, index).column_letter].width = max(14, min(44, len(header) + 12))
        sheet.freeze_panes = "A2"
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
