# download_data.py

import csv
import io
from datetime import datetime, timedelta
from flask import Blueprint, request, Response
from backend.database import get_te_session
from backend.orm_models import TesterRecord
from sqlalchemy import func, extract

download_bp = Blueprint('download', __name__, url_prefix='/api')

def _to_csv(rows: list[dict]) -> str:
    if not rows:
        return ''
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


@download_bp.route('/traceability/api/download-records', methods=['GET'])
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
        with get_te_session() as session:
            query = session.query(TesterRecord)

            if mode == 'today':
                date_str = now.strftime('%Y-%m-%d')
                query = query.filter(func.date(TesterRecord.datetime_start) == date_str)
                label = f"today_{date_str}"

            elif mode == 'day':
                date_str = request.args.get('date', now.strftime('%Y-%m-%d'))
                query = query.filter(func.date(TesterRecord.datetime_start) == date_str)
                label = f"day_{date_str}"

            elif mode == 'week':
                year  = int(request.args.get('year',  now.year))
                week  = int(request.args.get('week',  now.isocalendar()[1]))
                # Monday of that ISO week
                monday = datetime.fromisocalendar(year, week, 1)
                sunday = monday + timedelta(days=6)
                
                query = query.filter(func.date(TesterRecord.datetime_start).between(
                    monday.strftime('%Y-%m-%d'), sunday.strftime('%Y-%m-%d')
                ))
                label = f"week_{year}_W{week:02d}"

            elif mode == 'month':
                year  = int(request.args.get('year',  now.year))
                month = int(request.args.get('month', now.month))
                
                query = query.filter(
                    extract('year', TesterRecord.datetime_start) == year,
                    extract('month', TesterRecord.datetime_start) == month
                )
                label = f"month_{year}_{month:02d}"

            elif mode == 'range':
                start = request.args.get('start', now.strftime('%Y-%m-%d'))
                end   = request.args.get('end',   now.strftime('%Y-%m-%d'))
                
                query = query.filter(func.date(TesterRecord.datetime_start).between(start, end))
                label = f"range_{start}_to_{end}"

            else:
                return Response("Invalid mode.", status=400)

            records = query.order_by(TesterRecord.datetime_start.desc()).all()
            
            rows = [{
                'id': r.id,
                'tester_code': r.tester_code,
                'tester_name': r.tester_name,
                'classification': r.classification,
                'due_date': r.due_date,
                'datetime_start': r.datetime_start,
                'datetime_done': r.datetime_done,
                'pic': r.pic,
                'issues': r.issues,
                'action_taken': r.action_taken,
                'remarks': r.remarks
            } for r in records]

    except (ValueError, TypeError) as e:
        return Response(f"Invalid parameter: {e}", status=400)
    except Exception as e:
        return Response(f"Error fetching data: {str(e)}", status=500)

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