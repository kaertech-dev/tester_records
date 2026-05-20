# query.py
import time
from datetime import datetime
from sqlalchemy import text
from backend.database import projects_engine, get_te_session, get_pe_session
from backend.orm_models import TesterRecord, TesterCredential, User, ProcessCredential, ProcessRecord

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
        with get_te_session() as session:
            new_record = TesterRecord(
                tester_code=data.get('tester_code'),
                tester_name=data.get('tester_name'),
                classification=data.get('classification'),
                datetime_start=datetime.now(),
                pic=data.get('person_in_charge'),
                issues=data.get('issues', ''),
                remarks='open'
            )
            session.add(new_record)
        _CACHE['tester_records'] = (None, 0)   # bust cache

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

        def _parse_date(val):
            if not val:
                return None
            try:
                return datetime.strptime(val, '%Y-%m-%d').date()
            except ValueError:
                return None

        with get_pe_session() as session:
            new_record = ProcessRecord(
                asset_id           = data.get('asset_id', '').strip(),
                asset_name         = data.get('asset_name', '').strip(),
                line_no            = data.get('line_no', '').strip(),
                description        = data.get('description', '').strip(),
                analysis           = data.get('analysis', '').strip(),
                corrective_action  = data.get('corrective_action', '').strip(),
                verification_result= data.get('verification_result', '').strip(),
                equip_down    = _parse_dt(data.get('equip_down')),
                repair_start       = _parse_dt(data.get('repair_start')),
                repair_end         = _parse_dt(data.get('repair_end')),
                troubleshoot_by    = data.get('troubleshoot_by', '').strip(),
                retention_period   = data.get('retention_period', '').strip(),
                effective_date     = _parse_date(data.get('effective_date')),
                logged_by           = data.get('logged_by', '').strip(),
            )
            session.add(new_record)
        _CACHE['process_records'] = (None, 0)  # bust cache
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

        with get_te_session() as session:
            rows = session.query(User).all()
            users = {
                (r.group, r.badge): {
                    'name': r.name,
                    'employee_num': r.employee_num,
                }
                for r in rows
            }
        _CACHE['users'] = (users, now)
        self._users = users
        return users

    def authenticate(self, group: str, password: str):
        cache_key = f"{group}:{password}"
        now       = time.time()

        hit = _CACHE['auth'].get(cache_key)
        if hit and now - hit[1] < _CACHE_TTL:
            return hit[0]

        self._load_users()
        user   = self._users.get((group, password))
        result = (
            {'name': user['name'], 'employee_num': user['employee_num']}
            if user else None
        )
        _CACHE['auth'][cache_key] = (result, now)
        return result
