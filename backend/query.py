# query.py
import time
import pymysql
from backend.new_transaction.connect_db import get_db_connection
from datetime import datetime

_CACHE = {
    'active_products': (None, 0),
    'models': {},
    'stations': {},
    'auth': {},
    'users': (None, 0),
    'tester_records': (None, 0),
}
_CACHE_TTL = 300  # seconds


# ── Customer ──────────────────────────────────────────────────────────────────

class Customer:
    """Reads active projects from projectsdb (separate host config — not pooled)."""

    _config = {
        "host":        "192.168.1.38",
        "user":        "readonly_user",
        "password":    "kts@tsd2025",
        "database":    "projectsdb",
        "charset":     "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
    }

    def get_active_customer(self):
        conn = None
        try:
            conn = pymysql.connect(**self._config)
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT schemadb FROM projects
                    WHERE status IN ('ACTIVE', 'active', 'Active')
                """)
                return [{'id': r['schemadb'], 'name': r['schemadb']} for r in cur.fetchall()]
        except Exception as e:
            print(f"[Customer] {e}")
            return []
        finally:
            if conn:
                conn.close()


# ── Model ─────────────────────────────────────────────────────────────────────

class Model:
    """Reads table names from per-product schemas (separate host config — not pooled)."""

    _base_config = {
        "host":        "192.168.1.38",
        "user":        "readonly_user",
        "password":    "kts@tsd2025",
        "charset":     "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
    }

    def _connect(self, schemadb):
        return pymysql.connect(**{**self._base_config, "database": schemadb})

    def get_models_for_customer(self, schemadb):
        conn = None
        try:
            conn = self._connect(schemadb)
            with conn.cursor() as cur:
                cur.execute("SHOW TABLES")
                rows = cur.fetchall()
            if not rows:
                return []
            names = [list(r.values())[0] for r in rows]
            models = sorted(set(n.split('_')[0] for n in names))
            return [{'id': m, 'name': m} for m in models]
        except Exception as e:
            print(f"[Model] models for '{schemadb}': {e}")
            return []
        finally:
            if conn:
                conn.close()

    def get_stations_for_model(self, schemadb, model_name):
        conn = None
        try:
            conn = self._connect(schemadb)
            with conn.cursor() as cur:
                cur.execute("SHOW TABLES")
                rows = cur.fetchall()
            if not rows:
                return []
            names  = [list(r.values())[0] for r in rows]
            prefix = model_name + '_'
            stations = sorted(set(
                n[len(prefix):] for n in names
                if n.startswith(prefix)
            ))
            return [{'id': s, 'name': s} for s in stations]
        except Exception as e:
            print(f"[Model] stations for '{schemadb}'.'{model_name}': {e}")
            return []
        finally:
            if conn:
                conn.close()


# ── ActiveProjects ────────────────────────────────────────────────────────────

class ActiveProjects:
    """Cached wrapper around Customer and Model."""

    def __init__(self):
        self._customer = Customer()
        self._model    = Model()

    def get_active_products(self):
        now = time.time()
        data, ts = _CACHE['active_products']
        if data is not None and now - ts < _CACHE_TTL:
            return data
        data = self._customer.get_active_customer()
        _CACHE['active_products'] = (data, now)
        return data

    def get_models_by_product(self, product_id):
        now = time.time()
        hit = _CACHE['models'].get(product_id)
        if hit and now - hit[1] < _CACHE_TTL:
            return hit[0]
        data = self._model.get_models_for_customer(product_id)
        _CACHE['models'][product_id] = (data, now)
        return data

    def get_stations_by_model(self, product_id, model_name):
        now = time.time()
        key = f"{product_id}.{model_name}"
        hit = _CACHE['stations'].get(key)
        if hit and now - hit[1] < _CACHE_TTL:
            return hit[0]
        data = self._model.get_stations_for_model(product_id, model_name)
        _CACHE['stations'][key] = (data, now)
        return data


# ── TesterRecords ─────────────────────────────────────────────────────────────

class TesterRecords:
    """
    All queries against te.tester_records.
    Uses the shared connection pool via get_db_connection().

    __init__ is now lazy: it does NOT touch the DB at construction time.
    The tester-code lookup cache is populated on first use and refreshed
    every _CACHE_TTL seconds via _load_tester_records().
    """

    def __init__(self):
        # No DB call here — pool connections are precious at startup
        self._local_cache: dict | None = None

    # ── Internal cache helpers ────────────────────────────────────

    def _load_tester_records(self) -> dict:
        now = time.time()
        records, ts = _CACHE['tester_records']
        if records is not None and now - ts < _CACHE_TTL:
            self._local_cache = records
            return records

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT tester_code, tester_name FROM tester_credential")
                rows = cur.fetchall()
            records = {}
            for row in rows:
                code   = row.get('tester_code') or ''
                suffix = code.split('-')[-1] if '-' in code else code
                records.setdefault(suffix, []).append(row)
            _CACHE['tester_records'] = (records, now)
            self._local_cache = records
            return records
        finally:
            conn.close()

    @staticmethod
    def _suffix(asset_no: str) -> str:
        return asset_no.split('-')[-1] if '-' in asset_no else asset_no

    # ── Public read methods ───────────────────────────────────────

    def get_tester_codes_by_fixture(self, fixture_asset_no: str):
        if not fixture_asset_no:
            return []
        suffix = self._suffix(fixture_asset_no)
        cache  = self._load_tester_records()
        rows   = cache.get(suffix, [])
        return [{'tester_code': r['tester_code'], 'tester_name': r['tester_name']} for r in rows]

    def get_tester_by_fixture(self, fixture_asset_no: str):
        if not fixture_asset_no:
            return None
        suffix = self._suffix(fixture_asset_no)
        cache  = self._load_tester_records()
        rows   = cache.get(suffix)
        if rows:
            return rows[0]
        # Fallback: DB LIKE query for edge cases not covered by suffix index
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tester_code, tester_name "
                    "FROM tester_credential "
                    "WHERE tester_code LIKE %s LIMIT 1",
                    (f'%-{suffix}',)
                )
                return cur.fetchone()
        finally:
            conn.close()

    def get_tester_name_by_code(self, tester_code: str):
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tester_name FROM tester_records "
                    "WHERE tester_code = %s LIMIT 1",
                    (tester_code,)
                )
                row = cur.fetchone()
                return row['tester_name'] if row else None
        finally:
            conn.close()

    def get_open_transactions(self):
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
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
                    WHERE remarks = 'open'
                    ORDER BY datetime_start DESC
                    """
                )
                return cur.fetchall()
        finally:
            conn.close()

    # ── Write methods ─────────────────────────────────────────────

    def create_transaction(self, data: dict):
        """
        Insert a new open transaction.

        DB columns:  tester_code, tester_name, classification,
                     datetime_start, pic, issues, action_taken, remarks
        Form keys:   tester_code, tester_name, classification,
                     person_in_charge (→ pic), has_issues (→ issues),
                     action_taken
        """
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO tester_records
                       (tester_code, tester_name, classification,
                        datetime_start, pic, issues, remarks)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (
                        data.get('tester_code'),
                        data.get('tester_name'),
                        data.get('classification'),
                        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        data.get('person_in_charge'),   # form key → DB column 'pic'
                        data.get('issues', ''),
                        'open',
                    )
                )
            conn.commit()
            _CACHE['tester_records'] = (None, 0)   # bust cache
        finally:
            conn.close()

    def close_transaction(self, transaction_id: int, action_taken: str = ''):
        """
        Stamp datetime_done and flip remarks → 'closed'.
        No data is moved to another table.
        """
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM tester_records "
                    "WHERE id = %s AND remarks = 'open'",
                    (transaction_id,)
                )
                if not cur.fetchone():
                    return False, 'Transaction not found or already closed.'

                cur.execute(
                    """UPDATE tester_records
                    SET datetime_done = %s,
                        remarks       = 'closed',
                        action_taken  = %s
                    WHERE id = %s""",
                    (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), action_taken, transaction_id)
                )
            conn.commit()
            return True, 'Transaction closed successfully.'
        except Exception as e:
            conn.rollback()
            print(f"[close_transaction] {e}")
            return False, str(e)
        finally:
            conn.close()


# ── UserAuth ──────────────────────────────────────────────────────────────────

class UserAuth:
    """
    Authenticates person-in-charge via te.user.
    User list is loaded once into memory and cached for _CACHE_TTL seconds.
    """

    def __init__(self):
        self._users: dict = {}
        self._load_users()

    def _load_users(self) -> dict:
        now = time.time()
        users, ts = _CACHE['users']
        if users is not None and now - ts < _CACHE_TTL:
            self._users = users
            return users

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT `group`, badge, name, employee_num FROM user"
                )
                rows = cur.fetchall()
            users = {
                (r['group'], r['badge']): {
                    'name':         r['name'],
                    'employee_num': r.get('employee_num'),
                }
                for r in rows
            }
            _CACHE['users'] = (users, now)
            self._users = users
            return users
        finally:
            conn.close()

    def authenticate(self, group: str, password: str):
        """
        Returns {'name': ..., 'employee_num': ...} on success, None on failure.
        Results are cached per (group, password) pair for _CACHE_TTL seconds.
        """
        cache_key = f"{group}:{password}"
        now       = time.time()

        hit = _CACHE['auth'].get(cache_key)
        if hit and now - hit[1] < _CACHE_TTL:
            return hit[0]

        self._load_users()
        user   = self._users.get((group, password))
        result = (
            {'name': user['name'], 'employee_num': user.get('employee_num')}
            if user else None
        )
        _CACHE['auth'][cache_key] = (result, now)
        return result
