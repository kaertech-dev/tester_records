"""
backend/download_station_data.py

Flask Blueprint — Station Data Downloader
  GET  /api/stations-list          → returns all unique stations across active schemas
  POST /api/preview-station-data   → returns JSON preview (summary + first N rows per table)
  POST /api/download-station-data  → streams Excel for chosen station + date range
                                     (includes optional "AI Analysis" sheet if ai_summary sent)
"""

from flask import Blueprint, jsonify, request, send_file
from mysql.connector import pooling
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from datetime import datetime, timedelta
import threading
import io
from concurrent.futures import ThreadPoolExecutor, as_completed

station_bp = Blueprint('station_bp', __name__)

# ── CONFIG ────────────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host":     "192.168.1.38",
    "port":     3306,
    "user":     "readonly_user",
    "password": "kts@tsd2025",
}
POOL_SIZE   = 8
MAX_WORKERS = 8
CHUNK_SIZE  = 5000
# ──────────────────────────────────────────────────────────────────────────────

_pool       = None
_pool_lock  = threading.Lock()
_print_lock = threading.Lock()

def tprint(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs)

def get_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = pooling.MySQLConnectionPool(
                pool_name="station_pool",
                pool_size=POOL_SIZE,
                pool_reset_session=True,
                **DB_CONFIG,
            )
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
    """Return list of (schema, table) for all tables in active schemas."""
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
    """Everything after the first underscore is the station. Returns None for _old tables."""
    parts = table_name.split('_', 1)
    if len(parts) < 2:
        return None
    station = parts[1]
    if station.endswith(('_old', '_old2', '_copy', '_2', 'old', '_tochange', 'progtest(old)')):
        return None
    return station

def get_tables_for_station(pool, schemas, station):
    """
    If station == '__all__', return every non-_old table across all schemas.
    Otherwise return tables matching the station exactly.
    """
    all_tables = get_all_tables_for_schemas(pool, schemas)

    if station == '__all__':
        return [
            (schema, table)
            for schema, table in all_tables
            if extract_station(table) is not None   # excludes _old tables
        ]

    return [
        (schema, table)
        for schema, table in all_tables
        if extract_station(table) == station
    ]
def detect_datetime_column(conn, schema, table):
    """
    Detect the best datetime column to filter on.
    Priority: datetime_start > created_at > updated_at > first DATETIME/TIMESTAMP col found.
    """
    cursor = conn.cursor()
    cursor.execute(f"""
        SELECT COLUMN_NAME, DATA_TYPE
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
          AND DATA_TYPE IN ('datetime', 'timestamp', 'date')
        ORDER BY ORDINAL_POSITION
    """, (schema, table))
    cols = cursor.fetchall()
    cursor.close()

    preferred = ['datetime_start', 'created_at', 'updated_at', 'date']
    col_names  = [c[0].lower() for c in cols]
    for pref in preferred:
        if pref in col_names:
            return cols[col_names.index(pref)][0]
    return cols[0][0] if cols else None


def fetch_table_data_filtered(pool, schema, table, date_from, date_to):
    """Fetch rows filtered by date range using chunked fetching."""
    conn = pool.get_connection()
    try:
        dt_col = detect_datetime_column(conn, schema, table)
        cursor = conn.cursor()

        if not dt_col:
            cursor.close()
            tprint(f"  ⚠  {schema}.{table}  (no datetime column — skipped)")
            return schema, table, [], []

        cursor.execute(f"""
            SELECT * FROM `{schema}`.`{table}`
            WHERE `{dt_col}` >= %s AND `{dt_col}` < %s
            ORDER BY `{dt_col}` DESC
        """, (date_from, date_to))

        columns = [desc[0] for desc in cursor.description]
        rows = []
        while True:
            chunk = cursor.fetchmany(CHUNK_SIZE)
            if not chunk:
                break
            rows.extend(chunk)
        cursor.close()
    finally:
        conn.close()

    tprint(f"  ✔  {schema}.{table}  ({len(rows):,} rows)")
    return schema, table, columns, rows


# ── Date range helpers ────────────────────────────────────────────────────────

def resolve_date_range(mode, params):
    """
    Returns (date_from, date_to) as datetime objects.
    date_to is exclusive (start of next day / week / month).
    """
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    if mode == 'today':
        return today, today + timedelta(days=1)

    elif mode == 'day':
        d = datetime.strptime(params['date'], '%Y-%m-%d')
        return d, d + timedelta(days=1)

    elif mode == 'week':
        year = int(params['year'])
        week = int(params['week'])
        monday = datetime.strptime(f'{year}-W{week:02d}-1', '%G-W%V-%u')
        return monday, monday + timedelta(weeks=1)

    elif mode == 'month':
        year  = int(params['year'])
        month = int(params['month'])
        start = datetime(year, month, 1)
        if month == 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, month + 1, 1)
        return start, end

    elif mode == 'range':
        d_from = datetime.strptime(params['date_from'], '%Y-%m-%d')
        d_to   = datetime.strptime(params['date_to'],   '%Y-%m-%d') + timedelta(days=1)
        return d_from, d_to

    else:
        raise ValueError(f"Unknown mode: {mode}")


# ── Excel builder ─────────────────────────────────────────────────────────────

def _style_header(cell):
    cell.font      = Font(name="Arial", bold=True, color="FFFFFF", size=10)
    cell.fill      = PatternFill("solid", start_color="2E4057")
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

def _style_meta_header(cell):
    cell.font      = Font(name="Arial", bold=True, color="FFFFFF", size=10)
    cell.fill      = PatternFill("solid", start_color="1B6CA8")
    cell.alignment = Alignment(horizontal="center", vertical="center")

def _style_section_row(ws, row_num, col_count):
    for col in range(1, col_count + 1):
        cell           = ws.cell(row=row_num, column=col)
        cell.fill      = PatternFill("solid", start_color="D6E4F0")
        cell.font      = Font(name="Arial", bold=True, size=10, color="1B3A57")
        cell.alignment = Alignment(horizontal="left", vertical="center")


def build_station_excel(tables_data, station, date_from, date_to,
                        ai_summary=None, ai_prompt=None):
    """
    Build the Excel workbook.
    If ai_summary is provided, an extra 'AI Analysis' sheet is appended.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title        = f"{station[:28]}"
    ws.freeze_panes = "A2"

    master_headers = ["Schema", "Table", "Row #"]
    for col_idx, h in enumerate(master_headers, start=1):
        _style_meta_header(ws.cell(row=1, column=col_idx, value=h))

    current_row = 2
    max_col     = len(master_headers)
    EVEN_FILL   = PatternFill("solid", start_color="F2F7FB")
    BASE_FONT   = Font(name="Arial", size=9)

    for schema, table, columns, rows in tables_data:
        total_cols = len(master_headers) + len(columns)
        if total_cols > max_col:
            for col_idx, col_name in enumerate(columns, start=len(master_headers) + 1):
                if col_idx > max_col:
                    _style_meta_header(ws.cell(row=1, column=col_idx, value=col_name))
            max_col = total_cols

        # Section separator
        ws.cell(row=current_row, column=1,
                value=f"▶  {schema}.{table}  —  {len(rows):,} row(s)")
        _style_section_row(ws, current_row, max_col)
        ws.row_dimensions[current_row].height = 18
        current_row += 1

        # Column headers
        for col_idx, h in enumerate(master_headers, start=1):
            _style_header(ws.cell(row=current_row, column=col_idx, value=h))
        for col_idx, col_name in enumerate(columns, start=len(master_headers) + 1):
            _style_header(ws.cell(row=current_row, column=col_idx, value=col_name))
        ws.row_dimensions[current_row].height = 20
        current_row += 1

        # Data rows
        for row_num, row in enumerate(rows, start=1):
            is_even = row_num % 2 == 0
            for mc in range(1, len(master_headers) + 1):
                c      = ws.cell(row=current_row, column=mc)
                c.font = BASE_FONT
                if is_even:
                    c.fill = EVEN_FILL
            ws.cell(row=current_row, column=1).value = schema
            ws.cell(row=current_row, column=2).value = table
            ws.cell(row=current_row, column=3).value = row_num
            for col_idx, value in enumerate(row, start=len(master_headers) + 1):
                c      = ws.cell(row=current_row, column=col_idx, value=value)
                c.font = BASE_FONT
                if is_even:
                    c.fill = EVEN_FILL
            current_row += 1

        current_row += 1  # spacer

    # Auto-fit columns
    for col_cells in ws.iter_cols(min_row=1, max_row=ws.max_row):
        max_len = 0
        for cell in col_cells:
            try:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
            except Exception:
                pass
        ws.column_dimensions[col_cells[0].column_letter].width = min(max_len + 4, 50)

    # ── Optional AI Analysis sheet ────────────────────────────────────────
    if ai_summary:
        _add_ai_sheet(wb, ai_prompt or '', ai_summary)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ── AI Analysis sheet builder ─────────────────────────────────────────────────

def _add_ai_sheet(wb, prompt: str, summary: str) -> None:
    """Append a formatted 'AI Analysis' sheet to the workbook."""

    ws = wb.create_sheet(title="AI Analysis")

    # ── Palette
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

    # ── Column widths
    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["B"].width = 95

    # ── Row 1: Title
    ws.merge_cells("A1:B1")
    title = ws["A1"]
    title.value     = "AI Analysis  —  Powered by Claude"
    title.font      = Font(name="Arial", bold=True, size=14, color=WHITE)
    title.fill      = PatternFill("solid", fgColor=PURPLE_DARK)
    title.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 34

    # ── Row 2: Prompt label + value
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

    # ── Row 3: spacer
    ws.row_dimensions[3].height = 6

    # ── Row 4: Section header
    ws.merge_cells("A4:B4")
    sec           = ws["A4"]
    sec.value     = "Analysis Results"
    sec.font      = Font(name="Arial", bold=True, size=11, color=WHITE)
    sec.fill      = PatternFill("solid", fgColor=PURPLE_MID)
    sec.alignment = Alignment(horizontal="left", vertical="center",
                              indent=1)
    ws.row_dimensions[4].height = 22

    # ── Rows 5+: AI text, line by line
    current_row = 5
    for line in summary.splitlines():
        stripped = line.strip()

        # Empty line → small spacer row
        if not stripped:
            ws.row_dimensions[current_row].height = 7
            ws.append(["", ""])
            current_row += 1
            continue

        # Detect markdown headings
        if stripped.startswith("### "):
            text, level = stripped[4:], 3
        elif stripped.startswith("## "):
            text, level = stripped[3:], 2
        elif stripped.startswith("# "):
            text, level = stripped[2:], 1
        else:
            text, level = stripped, 0

        # Strip remaining markdown bold/italic/code markers
        text = text.replace("**", "").replace("*", "").replace("`", "")

        # Bullet indicator
        is_bullet = text.startswith("- ") or text.startswith("• ")
        if is_bullet:
            text = "  •  " + text[2:]

        # Left label column (blank, just coloured)
        left_cell           = ws.cell(row=current_row, column=1, value="")
        left_cell.fill      = PatternFill("solid", fgColor="EEE8FF")
        left_cell.border    = _thin_border(left=True, right=False)

        # Content column
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

    # ── Close bottom border on last content row
    last = current_row - 1
    for col in [1, 2]:
        existing       = ws.cell(row=last, column=col).border
        ws.cell(row=last, column=col).border = Border(
            left=existing.left,
            right=existing.right,
            top=existing.top,
            bottom=Side(style="thin", color=BORDER_COLOR),
        )

    # ── Generated timestamp row
    ws.append(["", ""])
    current_row += 1
    ts_cell           = ws.cell(row=current_row, column=1,
                                value=f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    ws.merge_cells(f"A{current_row}:B{current_row}")
    ts_cell.font      = Font(name="Arial", size=8, italic=True, color="888888")
    ts_cell.alignment = Alignment(horizontal="right")

    ws.freeze_panes = "A2"


# ── Flask routes ──────────────────────────────────────────────────────────────

@station_bp.route('/api/stations-list')
def stations_list():
    """Return sorted list of all unique station names across active schemas."""
    try:
        pool     = get_pool()
        schemas  = get_active_schemas(pool)
        tables   = get_all_tables_for_schemas(pool, schemas)
        stations = sorted(set(
            extract_station(table)
            for _, table in tables
            if extract_station(table)
        ))
        return jsonify(stations)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@station_bp.route('/api/preview-station-data', methods=['POST'])
def preview_station_data():
    """
    Returns JSON preview for the data table visualization.
    Body: { station, mode, date?, year?, week?, month?, date_from?, date_to? }
    Response: {
        station, date_from, date_to,
        total_rows, total_tables,
        tables: [ { schema, table, row_count, columns, rows (first 100) } ]
    }
    """
    PREVIEW_LIMIT = 100

    body    = request.get_json(force=True) or {}
    station = (body.get('station') or '').strip()
    mode    = (body.get('mode')    or 'today').strip()

    if not station:
        return jsonify({'error': 'station is required'}), 400

    try:
        date_from, date_to = resolve_date_range(mode, body)
    except Exception as e:
        return jsonify({'error': f'Invalid date params: {e}'}), 400

    try:
        pool    = get_pool()
        schemas = get_active_schemas(pool)
        matches = get_tables_for_station(pool, schemas, station)

        if not matches:
            label = "all stations" if station == '__all__' else f'station "{station}"'
            return jsonify({'error': f'No tables found for {label}'}), 404

        results = {}
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(
                    fetch_table_data_filtered, pool, schema, table, date_from, date_to
                ): (schema, table)
                for schema, table in matches
            }
            for future in as_completed(futures):
                try:
                    s, t, columns, rows = future.result()
                    results[(s, t)] = (columns, rows)
                except Exception as e:
                    s, t = futures[future]
                    tprint(f"  ✖  {s}.{t} — {e}")

        tables_out = []
        total_rows = 0
        for schema, table in matches:
            if (schema, table) not in results:
                continue
            columns, rows = results[(schema, table)]
            if not rows:
                continue
            total_rows += len(rows)

            def serialize(v):
                if v is None:
                    return None
                if isinstance(v, datetime):
                    return v.strftime('%Y-%m-%d %H:%M:%S')
                try:
                    from decimal import Decimal
                    if isinstance(v, Decimal):
                        return float(v)
                except ImportError:
                    pass
                return str(v) if not isinstance(v, (int, float, bool, str)) else v

            preview_rows = [
                [serialize(cell) for cell in row]
                for row in rows[:PREVIEW_LIMIT]
            ]

            tables_out.append({
                'schema':    schema,
                'table':     table,
                'row_count': len(rows),
                'columns':   columns,
                'rows':      preview_rows,
            })

        if total_rows == 0:
            return jsonify({'error': 'No data found for the selected station and date range.'}), 404

        return jsonify({
            'station':      'All Stations' if station == '__all__' else station,
            'date_from':    date_from.strftime('%Y-%m-%d'),
            'date_to':      (date_to - timedelta(days=1)).strftime('%Y-%m-%d'),
            'total_rows':   total_rows,
            'total_tables': len(tables_out),
            'tables':       tables_out,
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@station_bp.route('/api/download-station-data', methods=['POST'])
def download_station_data():
    """
    Body (JSON):
      {
        station, mode, date?, year?, week?, month?, date_from?, date_to?,
        ai_summary?,   ← optional: AI analysis text to embed as extra sheet
        ai_prompt?     ← optional: the prompt the user typed
      }
    """
    body    = request.get_json(force=True) or {}
    station = (body.get('station')    or '').strip()
    mode    = (body.get('mode')       or 'today').strip()
    ai_summary = (body.get('ai_summary') or '').strip()   # ← NEW
    ai_prompt  = (body.get('ai_prompt')  or '').strip()   # ← NEW

    if not station:
        return jsonify({'error': 'station is required'}), 400

    try:
        date_from, date_to = resolve_date_range(mode, body)
    except Exception as e:
        return jsonify({'error': f'Invalid date params: {e}'}), 400

    try:
        pool    = get_pool()
        schemas = get_active_schemas(pool)
        matches = get_tables_for_station(pool, schemas, station)

        if not matches:
            label = "all stations" if station == '__all__' else f'station "{station}"'
            return jsonify({'error': f'No tables found for {label}'}), 404


        results = {}
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(
                    fetch_table_data_filtered, pool, schema, table, date_from, date_to
                ): (schema, table)
                for schema, table in matches
            }
            for future in as_completed(futures):
                try:
                    s, t, columns, rows = future.result()
                    results[(s, t)] = (columns, rows)
                except Exception as e:
                    s, t = futures[future]
                    tprint(f"  ✖  {s}.{t} — {e}")

        tables_data = [
            (schema, table, *results[(schema, table)])
            for schema, table in matches
            if (schema, table) in results and len(results[(schema, table)][1]) > 0
        ]

        total_rows = sum(len(r[3]) for r in tables_data)
        if total_rows == 0:
            return jsonify({'error': 'No data found for the selected station and date range.'}), 404

        # ── Build Excel (with optional AI sheet) ──────────────────────────
        buf = build_station_excel(
            tables_data, station, date_from, date_to,
            ai_summary=ai_summary or None,
            ai_prompt=ai_prompt   or None,
        )

        station_label = 'all_stations' if station == '__all__' else station
        filename = (
            f"{station_label}_{date_from.strftime('%Y%m%d')}"
            f"_to_{(date_to - timedelta(days=1)).strftime('%Y%m%d')}.xlsx"
        )
        return send_file(
            buf,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename,
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500