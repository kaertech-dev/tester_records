"""
yield_excel.py

Builds the "Yield Summary" sheet inside the station Excel workbook.
Call add_yield_sheet(wb, yield_data) after the main data sheet is built.
"""

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.chart.series import SeriesLabel
from openpyxl.utils import get_column_letter


# ── Colour palette (matches the green station theme) ─────────────────────────
C_HEADER_BG  = "1B4332"   # deep green
C_HEADER_FG  = "FFFFFF"
C_SUB_BG     = "2D6A4F"
C_PASS_BG    = "D8F3DC"
C_PASS_FG    = "1B4332"
C_FAIL_BG    = "FFE5E5"
C_FAIL_FG    = "7D0000"
C_YIELD_BG   = "B7E4C7"
C_YIELD_FG   = "1B4332"
C_ROW_ALT    = "F0FFF4"
C_BORDER     = "95D5B2"
C_TITLE_FG   = "081C15"
C_GRAY       = "6C757D"


def _border(color=C_BORDER):
    s = Side(style="thin", color=color)
    return Border(left=s, right=s, top=s, bottom=s)

def _fill(hex_color):
    return PatternFill("solid", fgColor=hex_color)

def _font(bold=False, size=10, color=C_TITLE_FG, italic=False):
    return Font(name="Arial", bold=bold, size=size, color=color, italic=italic)

def _align(h="center", v="center", wrap=False):
    return Alignment(horizontal=h, vertical=v, wrap_text=wrap)


def _write_section_title(ws, row, col, text, col_span=6):
    cell = ws.cell(row=row, column=col, value=text)
    cell.font      = _font(bold=True, size=11, color=C_HEADER_FG)
    cell.fill      = _fill(C_SUB_BG)
    cell.alignment = _align("left")
    cell.border    = _border()
    if col_span > 1:
        ws.merge_cells(
            start_row=row, start_column=col,
            end_row=row,   end_column=col + col_span - 1
        )
    ws.row_dimensions[row].height = 20


def _write_header_row(ws, row, col, headers, widths=None):
    for i, h in enumerate(headers, start=col):
        cell = ws.cell(row=row, column=i, value=h)
        cell.font      = _font(bold=True, size=10, color=C_HEADER_FG)
        cell.fill      = _fill(C_HEADER_BG)
        cell.alignment = _align()
        cell.border    = _border()
        if widths and (i - col) < len(widths):
            ws.column_dimensions[get_column_letter(i)].width = widths[i - col]
    ws.row_dimensions[row].height = 18


def _write_data_row(ws, row, col, values, alt=False,
                    highlight_col=None, highlight_fn=None):
    for i, v in enumerate(values, start=col):
        cell = ws.cell(row=row, column=i, value=v)
        cell.font      = _font(size=10)
        cell.alignment = _align()
        cell.border    = _border()
        if highlight_col is not None and highlight_fn and (i - col) == highlight_col:
            result = highlight_fn(v)
            if result:
                cell.fill = _fill(result[0])
                cell.font = _font(bold=True, size=10, color=result[1])
            elif alt:
                cell.fill = _fill(C_ROW_ALT)
        elif alt:
            cell.fill = _fill(C_ROW_ALT)
    ws.row_dimensions[row].height = 16


def _yield_color(pct):
    """Return (bg, fg) fill codes based on yield %."""
    if pct is None:
        return None
    if pct >= 99.0:
        return (C_YIELD_BG, C_PASS_FG)
    if pct >= 95.0:
        return ("FFF3CD", "856404")
    return (C_FAIL_BG, C_FAIL_FG)


# ── Main entry point ──────────────────────────────────────────────────────────

def add_yield_sheet(wb, yield_data):
    """
    Append a 'Yield Summary' sheet to *wb* using the dict returned by
    yield_analysis.compute_yield().
    """
    if not yield_data or not yield_data.get('has_yield_data'):
        return   # nothing to add

    ws = wb.create_sheet(title="Yield Summary", index=0)   # first tab
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A4"

    overall = yield_data['overall']

    # ── Title banner (rows 1-2) ───────────────────────────────────────────
    ws.merge_cells("A1:L1")
    title = ws["A1"]
    title.value     = "📊  Yield Summary Report"
    title.font      = _font(bold=True, size=14, color=C_HEADER_FG)
    title.fill      = _fill(C_HEADER_BG)
    title.alignment = _align("center")
    ws.row_dimensions[1].height = 32

    ws.merge_cells("A2:L2")
    sub = ws["A2"]
    sub.value     = (
        f"Pass: {overall['pass']:,}   |   "
        f"Fail: {overall['fail']:,}   |   "
        f"Total: {overall['total']:,}   |   "
        f"Overall Yield: {overall['yield_pct']:.2f}%"
    )
    sub.font      = _font(bold=True, size=12, color=C_PASS_FG)
    sub.fill      = _fill(C_YIELD_BG)
    sub.alignment = _align("center")
    ws.row_dimensions[2].height = 22

    ws.row_dimensions[3].height = 8   # spacer

    current_row = 4
    START_COL   = 1   # column A

    # ── 1. Daily Yield table ──────────────────────────────────────────────
    by_date = yield_data.get('by_date', [])
    if by_date:
        _write_section_title(ws, current_row, START_COL, "Daily Yield", col_span=6)
        current_row += 1

        hdrs = ["Date", "Pass", "Fail", "Total", "Yield %"]
        _write_header_row(ws, current_row, START_COL, hdrs,
                          widths=[14, 10, 10, 10, 12])
        current_row += 1

        chart_data_start = current_row
        for i, row in enumerate(by_date):
            _write_data_row(
                ws, current_row, START_COL,
                [row['date'], row['pass'], row['fail'],
                 row['total'], row['yield_pct']],
                alt=(i % 2 == 1),
                highlight_col=4,
                highlight_fn=_yield_color,
            )
            current_row += 1
        chart_data_end = current_row - 1

        ws.row_dimensions[current_row].height = 10
        current_row += 1

        # Line chart – daily yield %
        if chart_data_end >= chart_data_start:
            lc = LineChart()
            lc.title  = "Daily Yield %"
            lc.style  = 10
            lc.height = 12
            lc.width  = 22
            lc.y_axis.title = "Yield %"
            lc.x_axis.title = "Date"
            lc.y_axis.scaling.min = max(0, min(r['yield_pct'] for r in by_date) - 2)
            lc.y_axis.scaling.max = 100

            data_ref = Reference(
                ws,
                min_col=START_COL + 4,
                max_col=START_COL + 4,
                min_row=chart_data_start - 1,
                max_row=chart_data_end,
            )
            cats = Reference(
                ws,
                min_col=START_COL,
                max_col=START_COL,
                min_row=chart_data_start,
                max_row=chart_data_end,
            )
            lc.add_data(data_ref, titles_from_data=True)
            lc.set_categories(cats)
            lc.series[0].graphicalProperties.line.solidFill  = "22C55E"
            lc.series[0].graphicalProperties.line.width      = 25000
            lc.series[0].marker.symbol = "circle"
            lc.series[0].marker.size   = 4

            ws.add_chart(lc, f"{get_column_letter(START_COL + 6)}{chart_data_start - 1}")

        # Move past the chart (≈ 22 rows tall)
        current_row = max(current_row, chart_data_start + 22)

    # ── 2. Shift Yield table ──────────────────────────────────────────────
    by_shift = yield_data.get('by_shift', [])
    if by_shift:
        _write_section_title(ws, current_row, START_COL, "Yield by Shift", col_span=6)
        current_row += 1
        _write_header_row(ws, current_row, START_COL,
                          ["Shift", "Pass", "Fail", "Total", "Yield %"],
                          widths=[10, 10, 10, 10, 12])
        current_row += 1
        for i, row in enumerate(by_shift):
            _write_data_row(
                ws, current_row, START_COL,
                [row['shift'], row['pass'], row['fail'],
                 row['total'], row['yield_pct']],
                alt=(i % 2 == 1),
                highlight_col=4, highlight_fn=_yield_color,
            )
            current_row += 1
        ws.row_dimensions[current_row].height = 10
        current_row += 1

    # ── 3. PO Yield table ─────────────────────────────────────────────────
    by_po = yield_data.get('by_po', [])
    if by_po:
        _write_section_title(ws, current_row, START_COL, "Yield by PO Number", col_span=6)
        current_row += 1
        _write_header_row(ws, current_row, START_COL,
                          ["PO Number", "Pass", "Fail", "Total", "Yield %"],
                          widths=[16, 10, 10, 10, 12])
        current_row += 1
        for i, row in enumerate(by_po):
            _write_data_row(
                ws, current_row, START_COL,
                [row['po_num'], row['pass'], row['fail'],
                 row['total'], row['yield_pct']],
                alt=(i % 2 == 1),
                highlight_col=4, highlight_fn=_yield_color,
            )
            current_row += 1
        ws.row_dimensions[current_row].height = 10
        current_row += 1

    # ── 4. Fail Reasons table ─────────────────────────────────────────────
    fail_reasons = yield_data.get('fail_reasons', [])
    if fail_reasons:
        _write_section_title(ws, current_row, START_COL, "Top Fail Reasons", col_span=6)
        current_row += 1
        _write_header_row(ws, current_row, START_COL,
                          ["Fail Reason", "Count"],
                          widths=[36, 12])
        current_row += 1
        chart_fr_start = current_row
        for i, row in enumerate(fail_reasons):
            _write_data_row(
                ws, current_row, START_COL,
                [row['reason'], row['count']],
                alt=(i % 2 == 1),
            )
            current_row += 1
        chart_fr_end = current_row - 1

        ws.row_dimensions[current_row].height = 10
        current_row += 1

        # Bar chart – fail reasons
        if chart_fr_end >= chart_fr_start:
            bc = BarChart()
            bc.type    = "bar"
            bc.title   = "Top Fail Reasons"
            bc.style   = 10
            bc.height  = max(8, len(fail_reasons) * 0.9)
            bc.width   = 20
            bc.y_axis.title = "Count"
            bc.barDir  = "bar"   # horizontal

            data_ref = Reference(
                ws,
                min_col=START_COL + 1,
                max_col=START_COL + 1,
                min_row=chart_fr_start - 1,
                max_row=chart_fr_end,
            )
            cats = Reference(
                ws,
                min_col=START_COL,
                max_col=START_COL,
                min_row=chart_fr_start,
                max_row=chart_fr_end,
            )
            bc.add_data(data_ref, titles_from_data=True)
            bc.set_categories(cats)
            bc.series[0].graphicalProperties.solidFill = "E24B4A"

            ws.add_chart(bc, f"{get_column_letter(START_COL + 3)}{chart_fr_start - 1}")

    # ── Final column width pass for data columns ──────────────────────────
    for col_letter, width in [("A", 18), ("B", 12), ("C", 12), ("D", 12), ("E", 14)]:
        if ws.column_dimensions[col_letter].width < width:
            ws.column_dimensions[col_letter].width = width