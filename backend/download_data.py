# download_data.py

import csv
import io
from datetime import datetime, timedelta
from flask import Blueprint, request, Response
from backend.new_transaction.connect_db import get_db_connection

download_bp = Blueprint('download', __name__, url_prefix='/api')


def _fetch_records(where_clause: str, params: tuple) -> list[dict]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    id,
                    tester_code,
                    tester_name,
                    classification,
                    due_date,
                    datetime_start,
                    datetime_done,
                    pic,
                    issues,
                    action_taken,
                    remarks
                FROM tester_records
                {where_clause}
                ORDER BY datetime_start DESC
                """,
                params,
            )
            return cur.fetchall()
    finally:
        conn.close()


def _to_csv(rows: list[dict]) -> str:
    if not rows:
        return ''
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


@download_bp.route('/download-records', methods=['GET'])
def download_records():
    """
    Query params:
        mode  : 'today' | 'day' | 'week' | 'month' | 'range'
        date  : YYYY-MM-DD  (used for mode=day)
        year  : YYYY        (used for mode=week/month with week/month params)
        week  : 1-53        (used for mode=week)
        month : 1-12        (used for mode=month)
        start : YYYY-MM-DD  (used for mode=range)
        end   : YYYY-MM-DD  (used for mode=range)
    """
    mode = request.args.get('mode', 'today')
    now  = datetime.now()

    try:
        if mode == 'today':
            date_str = now.strftime('%Y-%m-%d')
            where    = "WHERE DATE(datetime_start) = %s"
            params   = (date_str,)
            label    = f"today_{date_str}"

        elif mode == 'day':
            date_str = request.args.get('date', now.strftime('%Y-%m-%d'))
            where    = "WHERE DATE(datetime_start) = %s"
            params   = (date_str,)
            label    = f"day_{date_str}"

        elif mode == 'week':
            year  = int(request.args.get('year',  now.year))
            week  = int(request.args.get('week',  now.isocalendar()[1]))
            # Monday of that ISO week
            monday = datetime.fromisocalendar(year, week, 1)
            sunday = monday + timedelta(days=6)
            where  = "WHERE DATE(datetime_start) BETWEEN %s AND %s"
            params = (monday.strftime('%Y-%m-%d'), sunday.strftime('%Y-%m-%d'))
            label  = f"week_{year}_W{week:02d}"

        elif mode == 'month':
            year  = int(request.args.get('year',  now.year))
            month = int(request.args.get('month', now.month))
            where  = "WHERE YEAR(datetime_start) = %s AND MONTH(datetime_start) = %s"
            params = (year, month)
            label  = f"month_{year}_{month:02d}"

        elif mode == 'range':
            start = request.args.get('start', now.strftime('%Y-%m-%d'))
            end   = request.args.get('end',   now.strftime('%Y-%m-%d'))
            where  = "WHERE DATE(datetime_start) BETWEEN %s AND %s"
            params = (start, end)
            label  = f"range_{start}_to_{end}"

        else:
            return Response("Invalid mode.", status=400)

    except (ValueError, TypeError) as e:
        return Response(f"Invalid parameter: {e}", status=400)

    rows    = _fetch_records(where, params)
    csv_str = _to_csv(rows)

    filename = f"tester_records_{label}.csv"
    return Response(
        csv_str,
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
            'X-Record-Count': str(len(rows)),
        },
    )