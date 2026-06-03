# query.py
import time
from datetime import datetime
from sqlalchemy import text
from backend.database import projects_engine, get_te_session, get_pe_session
from backend.orm_models import TesterRecord, TesterCredential, User, ProcessCredential, ProcessRecord
import bcrypt

_CACHE = {
    'active_products': (None, 0),
    'models': {},
    'stations': {},
    'auth': {},
    'users': (None, 0),
    'tester_records': (None, 0),
    'process_records': (None, 0),
    'pe_users': (None, 0),
}
_CACHE_TTL = 300  # seconds


# ── Customer ──────────────────────────────────────────────────────────────────

class Customer:
    """Reads active projects from projectsdb via SQLAlchemy engine."""

    def get_active_customer(self):
        try:
            with projects_engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT schemadb FROM projects
                    WHERE status IN ('ACTIVE', 'active', 'Active')
                """))
                return [{'id': r[0], 'name': r[0]} for r in result]
        except Exception as e:
            print(f"[Customer] {e}")
            return []


# ── Model ─────────────────────────────────────────────────────────────────────

class Model:
    """Reads table names from per-product schemas."""

    def get_models_for_customer(self, schemadb):
        try:
            # Connect directly to the specific schema
            # Can't easily change database context on the fly with engines safely across threads,
            # so we'll execute a USE statement if supported, or schema-qualify SHOW TABLES.
            # SHOW TABLES FROM `<schemadb>` is the safest way.
            with projects_engine.connect() as conn:
                result = conn.execute(text(f"SHOW TABLES FROM `{schemadb}`"))
                rows = result.fetchall()
            if not rows:
                return []
            names = [r[0] for r in rows]
            models = sorted(set(n.split('_')[0] for n in names))
            return [{'id': m, 'name': m} for m in models]
        except Exception as e:
            print(f"[Model] models for '{schemadb}': {e}")
            return []

    def get_stations_for_model(self, schemadb, model_name):
        try:
            with projects_engine.connect() as conn:
                result = conn.execute(text(f"SHOW TABLES FROM `{schemadb}`"))
                rows = result.fetchall()
            if not rows:
                return []
            names = [r[0] for r in rows]
            prefix = model_name + '_'
            stations = sorted(set(
                n[len(prefix):] for n in names
                if n.startswith(prefix)
            ))
            return [{'id': s, 'name': s} for s in stations]
        except Exception as e:
            print(f"[Model] stations for '{schemadb}'.'{model_name}': {e}")
            return []


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
    Uses ORM Session.
    """

    def __init__(self):
        self._local_cache: dict | None = None

    # ── Internal cache helpers ────────────────────────────────────

    def _load_tester_records(self) -> dict:
        now = time.time()
        records, ts = _CACHE['tester_records']
        if records is not None and now - ts < _CACHE_TTL:
            self._local_cache = records
            return records

        records = {}
        with get_te_session() as session:
            rows = session.query(TesterCredential).all()
            
            for row in rows:
                code   = row.tester_code or ''
                suffix = code.split('-')[-1] if '-' in code else code
                records.setdefault(suffix, []).append({'tester_code': row.tester_code, 'tester_name': row.tester_name})
                
        _CACHE['tester_records'] = (records, now)
        self._local_cache = records
        return records

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
        return rows

    def get_tester_by_fixture(self, fixture_asset_no: str):
        if not fixture_asset_no:
            return None
        suffix = self._suffix(fixture_asset_no)
        cache  = self._load_tester_records()
        rows   = cache.get(suffix)
        if rows:
            return rows[0]
            
        # Fallback: LIKE query for edge cases not covered by suffix index
        with get_te_session() as session:
            row = session.query(TesterCredential).filter(
                TesterCredential.tester_code.like(f'%-{suffix}')
            ).first()
            if row:
                return {'tester_code': row.tester_code, 'tester_name': row.tester_name}
            return None

    def get_tester_name_by_code(self, tester_code: str):
        with get_te_session() as session:
            row = session.query(TesterRecord).filter(TesterRecord.tester_code == tester_code).first()
            return row.tester_name if row else None

    def get_open_transactions(self):
        with get_te_session() as session:
            rows = session.query(TesterRecord).filter(
                TesterRecord.remarks == 'open'
            ).order_by(TesterRecord.datetime_start.desc()).all()
            
            # Convert ORM objects to dicts for the frontend
            return [{
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
            } for r in rows]

    # ── Write methods ─────────────────────────────────────────────

    def create_transaction(self, data: dict):
        def _parse_dt(val):
            if not val:
                return None
            try:
                return datetime.fromisoformat(val)
            except ValueError:
                return None

        with get_pe_session() as session:
            new_record = ProcessRecord(
                asset_id       = data.get('asset_id', '').strip(),
                asset_name     = data.get('asset_name', '').strip(),
                line_no        = data.get('line_no', '').strip(),
                classification = data.get('classification', '').strip(),  # ← fixed
                equip_down     = _parse_dt(data.get('equip_down')),
                datetime_start = _parse_dt(data.get('datetime_start')),  # ← fixed
                datetime_end   = _parse_dt(data.get('datetime_end')),    # ← fixed
                description    = data.get('description', '').strip(),
                action_taken   = data.get('action_taken', '').strip(),   # ← fixed
                remarks        = data.get('remarks', '').strip(),        # ← fixed
                pic            = data.get('pic', '').strip(),            # ← fixed
                logged_by      = data.get('logged_by', '').strip(),
            )
            session.add(new_record)
        _CACHE['process_records'] = (None, 0)
 
    def close_transaction(self, transaction_id: int, action_taken: str = ''):
        try:
            with get_te_session() as session:
                record = session.query(TesterRecord).filter(
                    TesterRecord.id == transaction_id,
                    TesterRecord.remarks == 'open'
                ).first()
                
                if not record:
                    return False, 'Transaction not found or already closed.'

                record.datetime_done = datetime.now()
                record.remarks = 'closed'
                record.action_taken = action_taken
                
            return True, 'Transaction closed successfully.'
        except Exception as e:
            print(f"[close_transaction] {e}")
            return False, str(e)

class ProcessRecords:
    """All queries against pe.process_records and pe.process_credential."""

    def __init__(self):
        self._local_cache: dict | None = None

    # ── Internal credential cache ─────────────────────────────────

    def _load_credential_cache(self) -> dict:
        now = time.time()
        records, ts = _CACHE['process_records']
        if records is not None and now - ts < _CACHE_TTL:
            self._local_cache = records
            return records

        records = {}
        try:
            with get_pe_session() as session:
                rows = session.query(ProcessCredential).all()
                for row in rows:
                    asset_id = row.asset_id or ''
                    suffix = asset_id.split('-')[-1] if '-' in asset_id else asset_id
                    records.setdefault(suffix, []).append({
                        'asset_id': row.asset_id,
                        'asset_name': row.asset_name
                    })
        except Exception as e:
            print(f"[ProcessRecords._load_credential_cache] ERROR: {e}")  # ← log it
            raise    

        _CACHE['process_records'] = (records, now)
        self._local_cache = records
        return records

    @staticmethod
    def _suffix(asset_no: str) -> str:
        return asset_no.split('-')[-1] if '-' in asset_no else asset_no

    # ── Asset lookup ──────────────────────────────────────────────

    def get_asset_by_id(self, asset_id: str):
        """Return {'asset_id': ..., 'asset_name': ...} or None."""
        if not asset_id:
            return None
        try:
            suffix = self._suffix(asset_id)
            cache  = self._load_credential_cache()
            rows   = cache.get(suffix)
            if rows:
                # Prefer exact match
                for r in rows:
                    if r['asset_id'].upper() == asset_id.upper():
                        return r
                return rows[0]

            # Fallback: exact DB query
            with get_pe_session() as session:
                row = session.query(ProcessCredential).filter(
                    ProcessCredential.asset_id == asset_id
                ).first()
                if row:
                    return {'asset_id': row.asset_id, 'asset_name': row.asset_name}
                return None
        except Exception as e:
            print(f"[ProcessRecords.get_asset_by_id] ERROR for '{asset_id}': {e}")  # ← log it
            raise
    # ── PE user search ────────────────────────────────────────────

    def search_pe_users(self, query: str):
        """Return a list of matching PE users [{name, group, employee_num}]."""
        now = time.time()
        users, ts = _CACHE['pe_users']
        if users is None or now - ts >= _CACHE_TTL:
            with get_pe_session() as session:
                rows = session.query(User).all()
                users = [
                    {'name': r.name, 'group': r.group, 'employee_num': r.employee_num}
                    for r in rows
                ]
            _CACHE['pe_users'] = (users, now)

        q = query.lower()
        return [
            u for u in users
            if q in (u.get('name') or '').lower() or q in (u.get('group') or '').lower()
        ][:20]

    # ── Write methods ─────────────────────────────────────────────

    def create_transaction(self, data: dict):
        """Insert a new ProcessRecord into pe.process_records."""
        def _parse_dt(val):
            if not val:
                return None
            try:
                return datetime.fromisoformat(val)
            except ValueError:
                return None

        with get_pe_session() as session:
            new_record = ProcessRecord(
                asset_id       = data.get('asset_id', '').strip(),
                asset_name     = data.get('asset_name', '').strip(),
                line_no        = data.get('line_no', '').strip(),
                classification = data.get('classification', '').strip(),
                equip_down     = _parse_dt(data.get('equip_down')),
                datetime_start = _parse_dt(data.get('datetime_start')),
                datetime_end   = _parse_dt(data.get('datetime_end')),
                description    = data.get('description', '').strip(),
                action_taken   = data.get('action_taken', '').strip(),
                remarks        = data.get('remarks', '').strip(),
                pic            = data.get('pic', '').strip(),
                logged_by      = data.get('logged_by', '').strip(),
            )
            session.add(new_record)
        _CACHE['process_records'] = (None, 0)
# ── UserAuth ──────────────────────────────────────────────────────────────────

class UserAuth:

    def _load_users(self) -> dict:
        now = time.time()
        users, ts = _CACHE['users']
        if users is not None and now - ts < _CACHE_TTL:
            self._users = users
            return users

        with get_te_session() as session:
            rows = session.query(User).all()
            users = {
                r.employee_num: {
                    'employee_num': r.employee_num,
                    'group':        r.group,
                    'name':         r.name,
                    'badge':        r.badge,
                }
                for r in rows
            }
        _CACHE['users'] = (users, now)
        self._users = users
        return users

    @staticmethod
    def _is_hashed(value: str) -> bool:
        return isinstance(value, str) and value.startswith('$2')

    @staticmethod
    def _verify_badge(stored_badge: str, password: str) -> bool:
        if not stored_badge:
            return False
        if stored_badge.startswith('$2'):
            try:
                return bcrypt.checkpw(password.encode(), stored_badge.encode())
            except Exception:
                return False
        return stored_badge == password

    def _upgrade_plaintext_badge(self, employee_num: str, password: str) -> None:
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        with get_te_session() as session:
            row = session.query(User).filter(User.employee_num == employee_num).first()
            if row and row.badge == password:
                row.badge = hashed
        _CACHE['users'] = (None, 0)

    def authenticate(self, identity: str, password: str):
        """
        Accepts either group or employee_num as identity.
        Uses bcrypt-protected badge values wherever possible.
        Legacy plaintext badges are upgraded on successful login.
        """
        self._load_users()

        # Try employee_num lookup first
        user = self._users.get(identity)
        if user and self._verify_badge(user.get('badge', ''), password):
            if not self._is_hashed(user.get('badge', '')):
                self._upgrade_plaintext_badge(identity, password)
            return {
                'group':        user['group'],
                'name':         user['name'],
                'employee_num': user['employee_num'],
            }

        # Fallback to group-based lookup if identity is a group
        for u in self._users.values():
            if u.get('group') != identity:
                continue
            if self._verify_badge(u.get('badge', ''), password):
                if not self._is_hashed(u.get('badge', '')):
                    self._upgrade_plaintext_badge(u['employee_num'], password)
                return {
                    'group':        u['group'],
                    'name':         u['name'],
                    'employee_num': u['employee_num'],
                }

        return None


    def change_password(self, identity: str, old_password: str,
                        new_password: str, db_session_fn=None):
        """
        Verify old_password and store bcrypt hash of new_password in the badge field.
        Returns (True, 'message') or (False, 'error').
        """
        user = self.authenticate(identity, old_password)
        if not user:
            return False, 'Current password is incorrect.'

        if len(new_password) < 6:
            return False, 'New password must be at least 6 characters.'

        get_session = db_session_fn or get_te_session
        hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()

        with get_session() as session:
            row = session.query(User).filter(
                User.employee_num == user['employee_num']
            ).first()
            if not row:
                return False, 'User not found.'
            row.badge = hashed

        _CACHE['users'] = (None, 0)
        _CACHE['auth']  = {}
        return True, 'Password changed successfully.'
    
    def authenticate_with_session(self, identity: str, password: str, db_session_fn):
        """
        Same as authenticate() but queries the given db_session_fn instead of
        the TE cache. Used for PE login so bcrypt verification + auto-upgrade
        work on that database too.
        """
        with db_session_fn() as session:
            # Try employee_num first, then group
            row = session.query(User).filter(User.employee_num == identity).first()
            if not row:
                row = session.query(User).filter(User.group == identity).first()
            if not row:
                return None

            if not self._verify_badge(row.badge or '', password):
                return None

            # Upgrade plaintext → bcrypt on the PE side
            if not self._is_hashed(row.badge or ''):
                hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
                row.badge = hashed
                # session commits automatically via context manager

            return {
                'name':         row.name,
                'employee_num': row.employee_num,
                'group':        row.group,
            }