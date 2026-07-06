"""
backend/download_station_data.py  (streaming rewrite)

Flask Blueprint — Station Data Downloader
  GET  /api/stations-list          → returns all unique stations across active schemas
  POST /api/preview-station-data   → returns JSON preview + yield summary
  POST /api/download-station-data  → streams Excel, one sheet per table + Yield Summary
  GET  /api/download-station-data-stream  → SSE progress + final download link

Architecture (per the streaming rewrite):

    DB → fetchmany() chunks → ws.append() directly → file
                            → YieldAccumulator (running totals only)

ThreadPoolExecutor has been removed: tables are processed strictly
sequentially, since the DB and the single workbook being written are both
serial bottlenecks anyway.

IMPORTANT MEMORY NOTE: the Yield Summary and AI Analysis sheets need merged
cells, fills, and charts, which openpyxl's write-only mode cannot do, and
openpyxl does not support mixing write-only and normal sheets in one
Workbook (confirmed empirically while building this). So this uses a
normal Workbook, which means appended rows stay resident in memory until
wb.save() — not truly unbounded streaming. To keep memory bounded anyway,
two hard limits are enforced: MAX_ROWS_PER_TABLE (per table) and
MAX_TOTAL_ROWS (across the whole export). Hitting either limit truncates
the export and clearly flags it as capped in the output (a banner sheet in
the Excel file, and a `capped` field in the JSON/SSE responses) rather than
silently dropping data.
"""

from flask import Blueprint, jsonify, request, send_file, Response, stream_with_context
from mysql.connector import pooling
import mysql.connector
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from datetime import datetime, timedelta
from decimal import Decimal
import threading
import io
import json
import tempfile
import os
import uuid

# ── Local yield helpers ───────────────────────────────────────────────────────
from backend.yield_analysis import YieldAccumulator
from backend.yield_excel import add_yield_sheet

station_bp = Blueprint('station_bp', __name__)

# ── CONFIG ────────────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host":     "192.168.1.38",
    "port":     3306,
    "user":     "readonly_user",
    "password": "kts@tsd2025",
}
CHUNK_SIZE         = 5000     # rows pulled from MySQL per fetchmany() call
PREVIEW_LIMIT      = 100      # rows kept in memory per table for JSON preview

# Memory safety: a normal (non-write-only) openpyxl workbook is required so
# the Yield Summary / AI Analysis sheets can use merged cells, fills, and
# charts. That means every row appended to a data sheet stays resident in
# memory until wb.save() — there is no way around this while charts/merged
# cells are in the same file (verified empirically: 30 tables x 10k rows
# reaches ~525MB). So we enforce two budgets instead of relying on streaming
# alone to bound memory:
MAX_ROWS_PER_TABLE = 20000     # hard ceiling per single table
MAX_TOTAL_ROWS     = 150000    # hard ceiling across the whole export
# ──────────────────────────────────────────────────────────────────────────────

_pool_lock  = threading.Lock()
_print_lock = threading.Lock()

def tprint(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs)

_pool = None

def get_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = pooling.MySQLConnectionPool(
                pool_name="station_pool", pool_size=8, **DB_CONFIG)
    return _pool


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_active_schemas(pool):
    conn = pool.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT schemadb
            FROM projectsdb.projects
            WHERE LOWER(TRIM(status)) = 'active'
        """)
        schemas = [row[0] for row in cursor.fetchall()]
        cursor.close()
    finally:
        conn.close()
    return schemas


def get_all_tables_for_schemas(pool, schemas):
    if not schemas:
        return []
    placeholders = ", ".join(["%s"] * len(schemas))
    conn = pool.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT TABLE_SCHEMA, TABLE_NAME
            FROM information_schema.TABLES
            WHERE TABLE_TYPE = 'BASE TABLE'
              AND TABLE_SCHEMA IN ({placeholders})
            ORDER BY TABLE_SCHEMA, TABLE_NAME
        """, tuple(schemas))
        results = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()
    return results


def extract_station(table_name):
    parts = table_name.split('_', 1)
    if len(parts) < 2:
        return None
    station = parts[1]
    if station.endswith(('_old', '_old2', '_copy', '_2', 'old', '_tochange', 'progtest(old)')):
        return None
    return station


def get_tables_for_station(pool, schemas, station, schema_filter=None):
    all_tables = get_all_tables_for_schemas(pool, schemas)
    if schema_filter:
        all_tables = [item for item in all_tables if item[0] == schema_filter]
    if station == '__all__':
        return [
            (schema, table)
            for schema, table in all_tables
            if extract_station(table) is not None
        ]
    return [
        (schema, table)
        for schema, table in all_tables
        if extract_station(table) == station
    ]


_dt_col_cache = {}

def detect_datetime_column(conn, schema, table):
    key = f"{schema}.{table}"
    if key in _dt_col_cache:
        return _dt_col_cache[key]
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COLUMN_NAME, DATA_TYPE
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
          AND DATA_TYPE IN ('datetime', 'timestamp', 'date')
        ORDER BY ORDINAL_POSITION
    """, (schema, table))
    cols = cursor.fetchall()
    cursor.close()
    preferred  = ['datetime_start', 'created_at', 'updated_at', 'date']
    col_names  = [c[0].lower() for c in cols]
    result     = None
    for pref in preferred:
        if pref in col_names:
            result = cols[col_names.index(pref)][0]
            break
    if result is None:
        result = cols[0][0] if cols else None
    _dt_col_cache[key] = result
    return result


def stream_table_rows(schema, table, date_from, date_to, max_rows=None):
    """
    Generator that yields ('columns', columns) once, then ('rows', chunk)
    repeatedly, and finally ('truncated', row_count) if max_rows was hit
    before the table was exhausted. Opens and closes its own connection —
    callers consume this fully (or break) before moving to the next table,
    since tables are processed strictly sequentially.

    max_rows caps how many rows this call will yield in total (used to
    enforce both the per-table ceiling and whatever global row budget
    remains for the export as a whole — the caller passes the smaller of
    the two).
    """
    conn = mysql.connector.connect(**DB_CONFIG)
    try:
        dt_col = detect_datetime_column(conn, schema, table)
        if not dt_col:
            return

        cursor = conn.cursor(dictionary=False)
        query = f"""
            SELECT *
            FROM `{schema}`.`{table}`
            WHERE `{dt_col}` >= %s
              AND `{dt_col}` < %s
            ORDER BY `{dt_col}` DESC
        """
        cursor.execute(query, (date_from, date_to))
        columns = [desc[0] for desc in cursor.description]
        yield ('columns', columns)

        row_count = 0
        truncated = False
        while True:
            chunk = cursor.fetchmany(CHUNK_SIZE)
            if not chunk:
                break
            if max_rows is not None:
                remaining = max_rows - row_count
                if remaining <= 0:
                    truncated = True
                    break
                if len(chunk) > remaining:
                    chunk = chunk[:remaining]
                    truncated = True
            row_count += len(chunk)
            yield ('rows', chunk)
            if truncated:
                break

        if truncated:
            yield ('truncated', row_count)

        cursor.close()
    finally:
        conn.close()


def _serialize_cell(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (int, float, bool, str)):
        return v
    return str(v)


# ── Date range helpers ────────────────────────────────────────────────────────

def resolve_date_range(mode, params):
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if mode == 'today':
        return today, today + timedelta(days=1)
    elif mode == 'day':
        d = datetime.strptime(params['date'], '%Y-%m-%d')
        return d, d + timedelta(days=1)
    elif mode == 'week':
        year   = int(params['year'])
        week   = int(params['week'])
        monday = datetime.strptime(f'{year}-W{week:02d}-1', '%G-W%V-%u')
        return monday, monday + timedelta(weeks=1)
    elif mode == 'month':
        year  = int(params['year'])
        month = int(params['month'])
        start = datetime(year, month, 1)
        end   = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
        return start, end
    elif mode == 'range':
        d_from = datetime.strptime(params['date_from'], '%Y-%m-%d')
        d_to   = datetime.strptime(params['date_to'], '%Y-%m-%d') + timedelta(days=1)
        return d_from, d_to
    else:
        raise ValueError(f"Unknown mode: {mode}")


# ── Excel builder (streaming) ──────────────────────────────────────────────────

def build_station_excel_streaming(matches, date_from, date_to,
                                  ai_summary=None, ai_prompt=None):
    """
    Generator that builds the workbook one table at a time, fetching via
    fetchmany() chunks (never a full table's rows materialized as one
    giant list) and appending straight into that table's sheet.

    Yields progress events as it goes, so SSE callers can stream them live
    instead of receiving everything in one burst after a blocking call.
    The final event carries the finished result.

    Yields
    ------
    ('progress', {'done': i, 'total': N, 'schema': s, 'table': t,
                  'rows': row_count, 'truncated': bool})
        — once per table, right after that table's sheet is finished.
    ('result', {'buf': BytesIO | None, 'total_rows': int,
               'tables_written': int, 'capped': bool})
        — exactly once, last. `buf` is None if no table produced any rows.

    NOTE ON MEMORY: this uses a normal (non-write-only) openpyxl Workbook,
    because the Yield Summary and AI Analysis sheets need merged cells,
    fills, and charts, which write-only sheets cannot do, and openpyxl does
    not support mixing write-only and normal sheets in a single Workbook
    instance (confirmed empirically). A normal workbook keeps every
    appended row resident in memory until wb.save(), so true unbounded
    streaming isn't possible here — instead we enforce a hard global row
    budget (MAX_TOTAL_ROWS) plus a per-table ceiling (MAX_ROWS_PER_TABLE),
    verified to keep memory in the hundreds-of-MB range rather than
    unbounded GB growth.
    """
    wb  = openpyxl.Workbook()
    wb.remove(wb.active)
    acc = YieldAccumulator()

    HEADER_FONT = Font(name="Arial", bold=True, size=10, color="FFFFFF")
    HEADER_FILL = PatternFill("solid", start_color="2E4057")
    META_FONT   = Font(name="Arial", bold=True, size=10)

    total_rows     = 0
    tables_written = 0
    total          = len(matches)
    capped         = False
    capped_tables  = []   # list of (schema, table, reason) for the notice sheet

    for i, (schema, table) in enumerate(matches, start=1):
        if total_rows >= MAX_TOTAL_ROWS:
            capped = True
            capped_tables.append((schema, table, 'skipped — global row budget already exhausted'))
            yield ('progress', {'done': i, 'total': total, 'schema': schema,
                                'table': table, 'rows': 0, 'truncated': True})
            continue

        global_remaining = MAX_TOTAL_ROWS - total_rows
        per_table_budget = min(MAX_ROWS_PER_TABLE, global_remaining)
        hit_global_first = global_remaining < MAX_ROWS_PER_TABLE

        ws = wb.create_sheet(title=f"Table {i}")
        columns       = None
        row_count     = 0
        was_truncated = False

        for kind, payload in stream_table_rows(schema, table, date_from, date_to,
                                                max_rows=per_table_budget):
            if kind == 'columns':
                columns = payload
                meta_cell      = ws.cell(row=1, column=1, value=f"{schema}.{table}")
                meta_cell.font = META_FONT
                for col_idx, col_name in enumerate(columns, start=1):
                    c      = ws.cell(row=2, column=col_idx, value=col_name)
                    c.font = HEADER_FONT
                    c.fill = HEADER_FILL
                acc.start_table(columns)

            elif kind == 'rows':
                for row in payload:
                    ws.append([_serialize_cell(v) for v in row])
                acc.add_rows(payload)
                row_count += len(payload)

            elif kind == 'truncated':
                was_truncated = True

        if columns is None or row_count == 0:
            del wb[ws.title]
        else:
            total_rows     += row_count
            tables_written  += 1
            if was_truncated:
                capped = True
                reason = ('global row budget reached' if hit_global_first
                          else f'per-table limit of {MAX_ROWS_PER_TABLE:,} rows reached')
                capped_tables.append((schema, table, reason))
                note_row = ws.max_row + 2
                note     = ws.cell(row=note_row, column=1,
                                   value=f"⚠ Truncated at {row_count:,} rows ({reason})")
                note.font = Font(name="Arial", italic=True, color="B00020", size=9)

        yield ('progress', {'done': i, 'total': total, 'schema': schema,
                            'table': table, 'rows': row_count, 'truncated': was_truncated})

    if tables_written == 0:
        yield ('result', {'buf': None, 'total_rows': 0,
                          'tables_written': 0, 'capped': capped})
        return

    yield_data = acc.finalize()
    if yield_data.get('has_yield_data'):
        add_yield_sheet(wb, yield_data)

    if capped:
        _add_capped_notice(wb, total_rows, capped_tables)

    if ai_summary:
        _add_ai_sheet(wb, ai_prompt or '', ai_summary)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    yield ('result', {'buf': buf, 'total_rows': total_rows,
                      'tables_written': tables_written, 'capped': capped})


def _add_capped_notice(wb, total_rows, capped_tables):
    """Insert a visible notice sheet (right after Yield Summary, if present)
    so a capped export is never silently incomplete. Lists exactly which
    tables were affected and why, rather than a generic global-limit message."""
    index = 1 if "Yield Summary" in wb.sheetnames else 0
    ws = wb.create_sheet(title="⚠ Export Limited", index=index)
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 55

    header_msg = (
        f"This export was capped at {total_rows:,} total rows. "
        f"Some tables or rows within tables are missing. Narrow the date "
        f"range, or filter to a single station/database, for a complete export."
    )
    cell           = ws.cell(row=1, column=1, value=header_msg)
    ws.merge_cells("A1:B1")
    cell.font      = Font(name="Arial", bold=True, color="B00020", size=11)
    cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[1].height = 45

    ws.cell(row=3, column=1, value="Table").font  = Font(name="Arial", bold=True, size=10)
    ws.cell(row=3, column=2, value="Reason").font = Font(name="Arial", bold=True, size=10)
    r = 4
    for schema, table, reason in capped_tables:
        ws.cell(row=r, column=1, value=f"{schema}.{table}")
        ws.cell(row=r, column=2, value=reason)
        r += 1
    cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[1].height = 60


# ── AI Analysis sheet builder (unchanged — needs a normal, non-write-only sheet) ──

def _add_ai_sheet(wb, prompt: str, summary: str) -> None:
    ws = wb.create_sheet(title="AI Analysis")

    PURPLE_DARK  = "2D1B4E"
    PURPLE_MID   = "6B3FA0"
    LIGHT_BG     = "F5F0FF"
    PROMPT_BG    = "EDE9FF"
    BORDER_COLOR = "C084FC"
    WHITE        = "FFFFFF"

    def _thin_border(left=True, right=True, top=False, bottom=False):
        s = Side(style="thin", color=BORDER_COLOR)
        n = Side(style=None)
        return Border(
            left=s if left else n,
            right=s if right else n,
            top=s if top else n,
            bottom=s if bottom else n,
        )

    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["B"].width = 95

    ws.merge_cells("A1:B1")
    title           = ws["A1"]
    title.value     = "AI Analysis  —  Powered by Claude"
    title.font      = Font(name="Arial", bold=True, size=14, color=WHITE)
    title.fill      = PatternFill("solid", fgColor=PURPLE_DARK)
    title.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 34

    ws["A2"].value     = "Prompt"
    ws["A2"].font      = Font(name="Arial", bold=True, size=10, color=WHITE)
    ws["A2"].fill      = PatternFill("solid", fgColor=PURPLE_MID)
    ws["A2"].alignment = Alignment(vertical="top", wrap_text=True)
    ws["A2"].border    = _thin_border(top=True, bottom=True)

    prompt_text        = prompt or "(no prompt provided)"
    ws["B2"].value     = prompt_text
    ws["B2"].font      = Font(name="Arial", size=10, italic=True, color="4B1D8C")
    ws["B2"].fill      = PatternFill("solid", fgColor=PROMPT_BG)
    ws["B2"].alignment = Alignment(vertical="top", wrap_text=True)
    ws["B2"].border    = _thin_border(top=True, bottom=True)
    prompt_lines       = max(1, len(prompt_text) // 90 + 1)
    ws.row_dimensions[2].height = max(20, min(prompt_lines * 15, 80))

    ws.row_dimensions[3].height = 6

    ws.merge_cells("A4:B4")
    sec           = ws["A4"]
    sec.value     = "Analysis Results"
    sec.font      = Font(name="Arial", bold=True, size=11, color=WHITE)
    sec.fill      = PatternFill("solid", fgColor=PURPLE_MID)
    sec.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[4].height = 22

    current_row = 5
    for line in summary.splitlines():
        stripped = line.strip()
        if not stripped:
            ws.row_dimensions[current_row].height = 7
            ws.append(["", ""])
            current_row += 1
            continue

        if stripped.startswith("### "):
            text, level = stripped[4:], 3
        elif stripped.startswith("## "):
            text, level = stripped[3:], 2
        elif stripped.startswith("# "):
            text, level = stripped[2:], 1
        else:
            text, level = stripped, 0

        text = text.replace("**", "").replace("*", "").replace("`", "")
        is_bullet = text.startswith("- ") or text.startswith("• ")
        if is_bullet:
            text = "  •  " + text[2:]

        left_cell           = ws.cell(row=current_row, column=1, value="")
        left_cell.fill      = PatternFill("solid", fgColor="EEE8FF")
        left_cell.border    = _thin_border(left=True, right=False)

        cell           = ws.cell(row=current_row, column=2, value=text)
        cell.alignment = Alignment(vertical="top", wrap_text=True, indent=1)
        cell.border    = _thin_border(left=False, right=True)

        if level > 0:
            heading_styles = {
                1: (13, PURPLE_DARK, "E8E0FF"),
                2: (11, PURPLE_MID,  "EDE9FF"),
                3: (10, "5B21B6",    "F3EFFF"),
            }
            sz, fc, bg = heading_styles[level]
            cell.font      = Font(name="Arial", bold=True, size=sz, color=fc)
            cell.fill      = PatternFill("solid", fgColor=bg)
            left_cell.fill = PatternFill("solid", fgColor=bg)
            ws.row_dimensions[current_row].height = 22
        else:
            cell.font = Font(name="Arial", size=10, color="1E1040")
            cell.fill = PatternFill("solid", fgColor=LIGHT_BG)
            chars_per_line = 115
            n_lines        = max(1, len(text) // chars_per_line + text.count('\n'))
            ws.row_dimensions[current_row].height = max(15, min(n_lines * 15, 120))

        current_row += 1

    last = current_row - 1
    for col in [1, 2]:
        existing       = ws.cell(row=last, column=col).border
        ws.cell(row=last, column=col).border = Border(
            left=existing.left, right=existing.right, top=existing.top,
            bottom=Side(style="thin", color=BORDER_COLOR),
        )

    ws.append(["", ""])
    current_row += 1
    ts_cell           = ws.cell(row=current_row, column=1,
                                value=f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    ws.merge_cells(f"A{current_row}:B{current_row}")
    ts_cell.font      = Font(name="Arial", size=8, italic=True, color="888888")
    ts_cell.alignment = Alignment(horizontal="right")

    ws.freeze_panes = "A2"


# ── Flask routes ──────────────────────────────────────────────────────────────

@station_bp.route('/traceability/api/active-databases')
def active_databases():
    try:
        pool    = get_pool()
        schemas = get_active_schemas(pool)
        return jsonify(sorted(set(schemas)))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@station_bp.route('/traceability/api/stations-list')
def stations_list():
    try:
        pool      = get_pool()
        database  = (request.args.get('database') or '').strip()
        schemas   = [database] if database else get_active_schemas(pool)
        tables    = get_all_tables_for_schemas(pool, schemas)
        stations  = sorted(set(
            extract_station(table)
            for _, table in tables
            if extract_station(table)
        ))
        return jsonify(stations)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@station_bp.route('/traceability/api/preview-station-data', methods=['POST'])
def preview_station_data():
    """
    Streams each table just like the download route, but only retains up
    to PREVIEW_LIMIT rows per table for the JSON response. Yield stats are
    still computed over every row seen (cheap — just counters).
    """
    body     = request.get_json(force=True) or {}
    station  = (body.get('station') or '').strip()
    database = (body.get('database') or '').strip()
    mode     = (body.get('mode')    or 'today').strip()

    if not station:
        return jsonify({'error': 'station is required'}), 400

    try:
        date_from, date_to = resolve_date_range(mode, body)
    except Exception as e:
        return jsonify({'error': f'Invalid date params: {e}'}), 400

    try:
        pool    = get_pool()
        schemas = [database] if database else get_active_schemas(pool)
        matches = get_tables_for_station(pool, schemas, station, schema_filter=database or None)

        if not matches:
            label = "all stations" if station == '__all__' else f'station "{station}"'
            return jsonify({'error': f'No tables found for {label}'}), 404

        acc        = YieldAccumulator()
        tables_out = []
        total_rows = 0

        for schema, table in matches:
            columns      = None
            preview_rows = []
            row_count    = 0

            for kind, payload in stream_table_rows(schema, table, date_from, date_to):
                if kind == 'columns':
                    columns = payload
                    acc.start_table(columns)
                elif kind == 'rows':
                    acc.add_rows(payload)
                    row_count += len(payload)
                    if len(preview_rows) < PREVIEW_LIMIT:
                        remaining = PREVIEW_LIMIT - len(preview_rows)
                        for row in payload[:remaining]:
                            preview_rows.append([_serialize_cell(v) for v in row])

            if columns is None or row_count == 0:
                continue

            total_rows += row_count
            tables_out.append({
                'schema':    schema,
                'table':     table,
                'row_count': row_count,
                'columns':   columns,
                'rows':      preview_rows,
            })

        if total_rows == 0:
            return jsonify({'error': 'No data found for the selected station and date range.'}), 404

        yield_summary = acc.finalize()

        return jsonify({
            'station':       'All Stations' if station == '__all__' else station,
            'date_from':     date_from.strftime('%Y-%m-%d'),
            'date_to':       (date_to - timedelta(days=1)).strftime('%Y-%m-%d'),
            'total_rows':    total_rows,
            'total_tables':  len(tables_out),
            'tables':        tables_out,
            'yield_summary': yield_summary,
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@station_bp.route('/traceability/api/download-station-data', methods=['POST'])
def download_station_data():
    body       = request.get_json(force=True) or {}
    station    = (body.get('station')    or '').strip()
    database   = (body.get('database')   or '').strip()
    mode       = (body.get('mode')       or 'today').strip()
    ai_summary = (body.get('ai_summary') or '').strip()
    ai_prompt  = (body.get('ai_prompt')  or '').strip()

    if not station:
        return jsonify({'error': 'station is required'}), 400

    try:
        date_from, date_to = resolve_date_range(mode, body)
    except Exception as e:
        return jsonify({'error': f'Invalid date params: {e}'}), 400

    try:
        pool    = get_pool()
        schemas = [database] if database else get_active_schemas(pool)
        matches = get_tables_for_station(pool, schemas, station, schema_filter=database or None)

        if not matches:
            label = "all stations" if station == '__all__' else f'station "{station}"'
            return jsonify({'error': f'No tables found for {label}'}), 404

        result = None
        for kind, payload in build_station_excel_streaming(
            matches, date_from, date_to,
            ai_summary=ai_summary or None,
            ai_prompt=ai_prompt   or None,
        ):
            if kind == 'result':
                result = payload
            # 'progress' events are ignored here — this route returns the
            # file directly with no channel for incremental updates; use
            # /api/download-station-data-stream (SSE) for live progress.

        buf            = result['buf']
        total_rows     = result['total_rows']
        capped         = result['capped']

        if buf is None or total_rows == 0:
            return jsonify({'error': 'No data found for the selected station and date range.'}), 404

        station_label = 'all_stations' if station == '__all__' else station
        filename = (
            f"{station_label}_{date_from.strftime('%Y%m%d')}"
            f"_to_{(date_to - timedelta(days=1)).strftime('%Y%m%d')}.xlsx"
        )
        response = send_file(
            buf,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename,
        )
        # Frontend can check this header to show a "export was truncated"
        # banner without parsing the file. The Excel itself also has a
        # visible "⚠ Export Limited" sheet when capped, as a backstop.
        response.headers['X-Export-Capped']    = '1' if capped else '0'
        response.headers['X-Export-Total-Rows'] = str(total_rows)
        return response

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@station_bp.route('/traceability/api/download-station-data-stream', methods=['GET'])
def download_station_data_stream():
    station    = request.args.get('station', '').strip()
    database   = request.args.get('database', '').strip()
    mode       = request.args.get('mode', 'today').strip()
    ai_summary = request.args.get('ai_summary', '').strip()
    ai_prompt  = request.args.get('ai_prompt', '').strip()
    params     = {k: v for k, v in request.args.items()}

    def generate():
        try:
            date_from, date_to = resolve_date_range(mode, params)
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        pool    = get_pool()
        schemas = [database] if database else get_active_schemas(pool)
        matches = get_tables_for_station(pool, schemas, station, schema_filter=database or None)

        if not matches:
            yield f"data: {json.dumps({'type': 'error', 'message': 'No tables found.'})}\n\n"
            return

        total = len(matches)
        yield f"data: {json.dumps({'type': 'start', 'total': total})}\n\n"

        result = None
        for kind, payload in build_station_excel_streaming(
            matches, date_from, date_to,
            ai_summary=ai_summary or None,
            ai_prompt=ai_prompt or None,
        ):
            if kind == 'progress':
                event = {
                    'type':      'progress',
                    'done':      payload['done'],
                    'total':     payload['total'],
                    'table':     f"{payload['schema']}.{payload['table']}",
                    'rows':      payload['rows'],
                    'truncated': payload['truncated'],
                }
                yield f"data: {json.dumps(event)}\n\n"
            elif kind == 'result':
                result = payload

        buf            = result['buf']
        total_rows     = result['total_rows']
        capped         = result['capped']

        if buf is None or total_rows == 0:
            yield f"data: {json.dumps({'type': 'error', 'message': 'No data found for the selected date range.'})}\n\n"
            return

        yield f"data: {json.dumps({'type': 'building', 'message': 'Finalizing Excel file…'})}\n\n"

        station_label = 'all_stations' if station == '__all__' else station
        filename = (
            f"{station_label}_{date_from.strftime('%Y%m%d')}"
            f"_to_{(date_to - timedelta(days=1)).strftime('%Y%m%d')}.xlsx"
        )

        tmp_id   = uuid.uuid4().hex
        tmp_path = os.path.join(tempfile.gettempdir(), f"stn_{tmp_id}.xlsx")
        with open(tmp_path, 'wb') as f:
            f.write(buf.read())

        yield f"data: {json.dumps({'type': 'done', 'filename': filename, 'download_url': f'/traceability/api/download-temp/{tmp_id}', 'total_rows': total_rows, 'capped': capped})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control':    'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )


@station_bp.route('/traceability/api/download-temp/<tmp_id>')
def download_temp(tmp_id):
    if not tmp_id.isalnum():
        return jsonify({'error': 'Invalid ID'}), 400
    path = os.path.join(tempfile.gettempdir(), f"stn_{tmp_id}.xlsx")
    if not os.path.exists(path):
        return jsonify({'error': 'File not found or expired'}), 404
    return send_file(path, as_attachment=True,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')