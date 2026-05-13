# backend/new_transaction/db_pool.py
"""
Singleton connection pool using DBUtils.PooledDB.
All parts of the app share this pool instead of opening
a fresh TCP connection on every request.

Install dependency once:
    pip install dbutils
"""

import pymysql
from dbutils.pooled_db import PooledDB

# ── Pool configuration ────────────────────────────────────────────────────────
_DB_CONFIG = {
    "host":        "192.168.1.38",
    "user":        "te_user",
    "password":    "kts@tsd2025",
    "database":    "te",
    "charset":     "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

_pool: PooledDB | None = None


def _get_pool() -> PooledDB:
    """Create the pool once; return the same instance on every subsequent call."""
    global _pool
    if _pool is None:
        _pool = PooledDB(
            creator=pymysql,          # underlying DB driver
            mincached=2,              # keep 2 idle connections alive at startup
            maxcached=5,              # max idle connections kept in pool
            maxconnections=10,        # hard cap on total simultaneous connections
            blocking=True,            # wait (don't raise) when pool is exhausted
            ping=1,                   # ping before reuse to avoid stale connections
            **_DB_CONFIG,
        )
    return _pool


def get_connection():
    """
    Return a pooled connection.  Use exactly like a normal pymysql connection:

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(...)
            conn.commit()
        finally:
            conn.close()   # returns the connection to the pool, does NOT close it
    """
    return _get_pool().connection()