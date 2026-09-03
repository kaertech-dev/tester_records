"""
backend/yield_analysis.py  (streaming-safe edition)

Computes yield statistics from station table data.
Used by both the preview endpoint (JSON) and Excel builder (sheet).

A "pass" row = status column value of 1 (integer or string).
A "fail" row = status column value of 0 (integer or string).
Rows where status is anything else (sensor readings, firmware strings, etc.) are ignored.

This version supports two usage patterns:

1. Streaming (preferred, used by the rewritten download/preview routes):
       acc = YieldAccumulator()
       for schema, table, columns in tables_meta:
           acc.start_table(columns)
           for row in stream_of_rows:
               acc.add_row(row)
       yield_data = acc.finalize()

2. Legacy / batch (kept for backward compatibility with any caller that
   still has full `tables_data` in memory — e.g. tests, or small ad-hoc
   scripts):
       yield_data = compute_yield(tables_data)

Both paths produce the exact same output dict shape, and share the same
underlying accumulation logic so they can never drift apart.
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


# ── Streaming accumulator ───────────────────────────────────────────────────

class YieldAccumulator:
    """
    Holds only running tallies — never a list of rows. Safe to feed
    millions of rows across many tables without growing memory beyond
    a handful of small dicts.
    """

    def __init__(self):
        self.total_pass = 0
        self.total_fail = 0
        self.date_acc   = defaultdict(lambda: [0, 0])   # date  -> [pass, fail]
        self.shift_acc  = defaultdict(lambda: [0, 0])   # shift -> [pass, fail]
        self.po_acc     = defaultdict(lambda: [0, 0])   # po    -> [pass, fail]
        self.reason_acc = defaultdict(int)               # reason -> count

        # Per-table column index cache, set by start_table()
        self._status_idx = None
        self._dt_idx      = None
        self._shift_idx   = None
        self._po_idx       = None
        self._remark_idx  = None

    def start_table(self, columns):
        """
        Call once per table, right after fetching its column list,
        before feeding any rows from that table via add_row().
        """
        if not columns:
            self._status_idx = None
            return

        self._status_idx = _find_col_idx(columns, 'status')
        self._dt_idx      = _find_col_idx(columns, 'date_time', 'datetime_start',
                                            'created_at', 'updated_at', 'date')
        self._shift_idx   = _find_col_idx(columns, 'shift')
        self._po_idx       = _find_col_idx(columns, 'po_num', 'po_number', 'po')
        self._remark_idx  = _find_col_idx(columns, 'remarks', 'remark', 'fail_reason',
                                            'failure_reason', 'reason')

    def add_row(self, row):
        """Feed a single row (tuple/list) from the table currently active
        via the most recent start_table() call. No-op if that table had
        no status column."""
        if self._status_idx is None:
            return
        if self._status_idx >= len(row):
            return

        outcome = _coerce_status(row[self._status_idx])
        if outcome is None:
            return

        is_pass = outcome == 'pass'
        if is_pass:
            self.total_pass += 1
        else:
            self.total_fail += 1

        bucket_idx = 0 if is_pass else 1

        # Date bucket
        if self._dt_idx is not None and self._dt_idx < len(row):
            dt_val = row[self._dt_idx]
            date_key = None
            if isinstance(dt_val, datetime):
                date_key = dt_val.strftime('%Y-%m-%d')
            elif isinstance(dt_val, str) and len(dt_val) >= 10:
                date_key = dt_val[:10]
            if date_key:
                self.date_acc[date_key][bucket_idx] += 1

        # Shift bucket
        if self._shift_idx is not None and self._shift_idx < len(row):
            sv = row[self._shift_idx]
            if sv not in (None, ''):
                self.shift_acc[str(sv)][bucket_idx] += 1

        # PO bucket
        if self._po_idx is not None and self._po_idx < len(row):
            pv = row[self._po_idx]
            if pv not in (None, ''):
                self.po_acc[str(pv)][bucket_idx] += 1

        # Fail reasons
        if not is_pass and self._remark_idx is not None and self._remark_idx < len(row):
            rv = row[self._remark_idx]
            if rv not in (None, '', 0, '0'):
                self.reason_acc[str(rv)] += 1

    def add_rows(self, rows):
        """Convenience: feed a batch (e.g. one fetchmany() chunk) at once."""
        for row in rows:
            self.add_row(row)

    def finalize(self):
        """Produce the same dict shape compute_yield() has always returned."""
        total    = self.total_pass + self.total_fail
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

        top_reasons = sorted(self.reason_acc.items(), key=lambda x: -x[1])[:15]

        return {
            'has_yield_data': has_data,
            'overall':        {'pass': self.total_pass, 'fail': self.total_fail,
                                'total': total, 'yield_pct': yield_pct(self.total_pass, total)},
            'by_date':        _sort_dates(self.date_acc),
            'by_shift':       _to_list(self.shift_acc, 'shift'),
            'by_po':          _to_list(self.po_acc, 'po_num'),
            'fail_reasons':   [{'reason': r, 'count': c} for r, c in top_reasons],
        }


# ── Legacy / batch entry point (kept for backward compatibility) ──────────────

def compute_yield(tables_data):
    """
    Parameters
    ----------
    tables_data : list of (schema, table, columns, rows)

    Returns
    -------
    dict — see YieldAccumulator.finalize() for the exact shape.

    NOTE: this still requires `rows` to be fully materialized in memory
    for each table. Prefer YieldAccumulator directly when streaming from
    the database — this function is kept only for callers (tests, small
    scripts) that already have everything loaded.
    """
    acc = YieldAccumulator()
    for schema, table, columns, rows in tables_data:
        if not columns or not rows:
            continue
        acc.start_table(columns)
        acc.add_rows(rows)
    return acc.finalize()