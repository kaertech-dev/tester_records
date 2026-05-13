import pymysql
import os
from dotenv import load_dotenv
from dbutils.pooled_db import PooledDB

load_dotenv()

# ── Pool registry ─────────────────────────────────────────────────────────────
# One pool per database name, created lazily on first use.
_pools: dict[str, PooledDB] = {}


def _get_pool(database: str) -> PooledDB:
    """Return the existing pool for `database`, or create one."""
    if database not in _pools:
        host     = os.getenv('DB_HOST')
        port     = int(os.getenv('DB_PORT', 3306))
        user     = os.getenv('DB_USER')
        password = os.getenv('DB_PASSWORD')

        _pools[database] = PooledDB(
            creator=pymysql,
            mincached=2,          # 2 warm connections kept alive at all times
            maxcached=5,          # max idle connections in pool
            maxconnections=10,    # hard cap on simultaneous connections
            blocking=True,        # wait instead of raising when pool is full
            ping=1,               # ping before reuse to drop stale connections
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
        )
    return _pools[database]


def _get_connection(database: str):
    """
    Return a pooled connection for `database`.

    Falls back to port 3306 if DB_PORT fails — same behaviour as the
    original connect_db, but the fallback only happens once on first
    pool creation rather than on every single request.
    """
    try:
        return _get_pool(database).connection()
    except Exception:
        # Pool creation failed on DB_PORT; rebuild with port 3306
        if database in _pools:
            del _pools[database]
        host     = os.getenv('DB_HOST')
        user     = os.getenv('DB_USER')
        password = os.getenv('DB_PASSWORD')

        _pools[database] = PooledDB(
            creator=pymysql,
            mincached=2,
            maxcached=5,
            maxconnections=10,
            blocking=True,
            ping=1,
            host=host,
            port=3306,            # fallback port
            user=user,
            password=password,
            database=database,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
        )
        return _pools[database].connection()


def get_db_connection():
    """Return a pooled connection to the primary TE database."""
    return _get_connection(os.getenv('DB_NAME'))


def get_projects_db_connection():
    """Return a pooled connection to the active-projects database."""
    return _get_connection(os.getenv('ACTIVE_PROJECTS'))


# ── Index helpers (unchanged from original) ───────────────────────────────────

def _ensure_index(connection, table, index_name, columns):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SHOW INDEX FROM `{table}` WHERE Key_name = %s",
                (index_name,)
            )
            if not cursor.fetchone():
                cursor.execute(
                    f"ALTER TABLE `{table}` ADD INDEX `{index_name}` ({columns})"
                )
                connection.commit()
    except Exception:
        pass


def ensure_indexes():
    """Create helpful indexes for the app's most common queries."""
    conn = None
    try:
        conn = get_db_connection()
        _ensure_index(conn, 'tester_records', 'idx_tester_code',     '`tester_code`')
        _ensure_index(conn, 'tester_records', 'idx_remarks',          '`remarks`')
        _ensure_index(conn, 'user',                'idx_user_group_badge', '`group`, `badge`')
    finally:
        if conn:
            conn.close()

    project_conn = None
    try:
        project_conn = get_projects_db_connection()
        _ensure_index(project_conn, 'projects', 'idx_projects_status', '`status`')
    finally:
        if project_conn:
            project_conn.close()