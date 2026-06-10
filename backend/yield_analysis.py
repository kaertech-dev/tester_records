"""
yield_analysis.py

Computes yield statistics from station table data.
Used by both the preview endpoint (JSON) and Excel builder (sheet).

A "pass" row = status column value of 1 (integer or string).
A "fail" row = status column value of 0 (integer or string).
Rows where status is anything else (sensor readings, firmware strings, etc.) are ignored.
"""

from datetime import datetime
from collections import defaultdict


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_pass(value):
    return value == 1 or value == '1' or value is True

def _is_fail(value):
    return value == 0 or value == '0' or value is False

def _coerce_status(value):
    """Return 'pass', 'fail', or None."""
    if _is_pass(value):
        return 'pass'
    if _is_fail(value):
        return 'fail'
    return None


def _find_col_idx(columns, *candidates):
    """Return index of first matching candidate column name (case-insensitive)."""
    lower = [c.lower() for c in columns]
    for name in candidates:
        if name.lower() in lower:
            return lower.index(name.lower())
    return None


# ── Core analysis ─────────────────────────────────────────────────────────────

def compute_yield(tables_data):
    """
    Parameters
    ----------
    tables_data : list of (schema, table, columns, rows)

    Returns
    -------
    dict  with keys:
        overall        – {pass, fail, total, yield_pct}
        by_date        – list of {date, pass, fail, total, yield_pct}
        by_shift       – list of {shift, pass, fail, total, yield_pct}
        by_po          – list of {po_num, pass, fail, total, yield_pct}
        fail_reasons   – list of {reason, count}   (top 15)
        has_yield_data – bool (False if no status 0/1 found at all)
    """

    # Accumulators
    total_pass = total_fail = 0
    date_acc   = defaultdict(lambda: [0, 0])   # date -> [pass, fail]
    shift_acc  = defaultdict(lambda: [0, 0])
    po_acc     = defaultdict(lambda: [0, 0])
    reason_acc = defaultdict(int)

    for schema, table, columns, rows in tables_data:
        if not columns or not rows:
            continue

        status_idx  = _find_col_idx(columns, 'status')
        dt_idx      = _find_col_idx(columns, 'date_time', 'datetime_start',
                                     'created_at', 'updated_at', 'date')
        shift_idx   = _find_col_idx(columns, 'shift')
        po_idx      = _find_col_idx(columns, 'po_num', 'po_number', 'po')
        remark_idx  = _find_col_idx(columns, 'remarks', 'remark', 'fail_reason',
                                     'failure_reason', 'reason')

        if status_idx is None:
            continue

        for row in rows:
            if status_idx >= len(row):
                continue
            raw_status = row[status_idx]
            outcome    = _coerce_status(raw_status)
            if outcome is None:
                continue

            is_pass = outcome == 'pass'
            if is_pass:
                total_pass += 1
            else:
                total_fail += 1

            # Date bucket
            if dt_idx is not None and dt_idx < len(row):
                dt_val = row[dt_idx]
                if isinstance(dt_val, datetime):
                    date_key = dt_val.strftime('%Y-%m-%d')
                elif isinstance(dt_val, str) and len(dt_val) >= 10:
                    date_key = dt_val[:10]
                else:
                    date_key = None
                if date_key:
                    date_acc[date_key][0 if is_pass else 1] += 1

            # Shift bucket
            if shift_idx is not None and shift_idx < len(row):
                sv = row[shift_idx]
                if sv not in (None, ''):
                    shift_acc[str(sv)][0 if is_pass else 1] += 1

            # PO bucket
            if po_idx is not None and po_idx < len(row):
                pv = row[po_idx]
                if pv not in (None, ''):
                    po_acc[str(pv)][0 if is_pass else 1] += 1

            # Fail reasons
            if not is_pass and remark_idx is not None and remark_idx < len(row):
                rv = row[remark_idx]
                if rv not in (None, '', 0, '0'):
                    reason_acc[str(rv)] += 1

    total = total_pass + total_fail
    has_data = total > 0

    def yield_pct(p, t):
        return round(p / t * 100, 2) if t else 0.0

    def _sort_dates(acc):
        out = []
        for d in sorted(acc):
            p, f = acc[d]
            t = p + f
            out.append({'date': d, 'pass': p, 'fail': f,
                         'total': t, 'yield_pct': yield_pct(p, t)})
        return out

    def _to_list(acc, key_name):
        out = []
        for k in sorted(acc, key=lambda x: -(acc[x][0] + acc[x][1])):
            p, f = acc[k]
            t = p + f
            out.append({key_name: k, 'pass': p, 'fail': f,
                         'total': t, 'yield_pct': yield_pct(p, t)})
        return out

    top_reasons = sorted(reason_acc.items(), key=lambda x: -x[1])[:15]

    return {
        'has_yield_data': has_data,
        'overall':        {'pass': total_pass, 'fail': total_fail,
                            'total': total, 'yield_pct': yield_pct(total_pass, total)},
        'by_date':        _sort_dates(date_acc),
        'by_shift':       _to_list(shift_acc, 'shift'),
        'by_po':          _to_list(po_acc, 'po_num'),
        'fail_reasons':   [{'reason': r, 'count': c} for r, c in top_reasons],
    }