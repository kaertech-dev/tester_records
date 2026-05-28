# connect_db.py
from backend.database import te_engine, projects_engine, process_engine
from sqlalchemy import text


def _ensure_column(connection, table, column, definition):
    """Add a column if it doesn't exist yet."""
    try:
        result = connection.execute(text(
            "SELECT COUNT(*) FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = :tbl AND COLUMN_NAME = :col"
        ), {"tbl": table, "col": column})
        if result.scalar() == 0:
            connection.execute(text(
                f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}"
            ))
            connection.commit()
    except Exception as e:
        print(f"Error ensuring column {column} on {table}: {e}")


def _ensure_index(connection, table, index_name, columns):
    """Add an index if it doesn't exist yet."""
    try:
        result = connection.execute(
            text(f"SHOW INDEX FROM `{table}` WHERE Key_name = :index_name"),
            {"index_name": index_name}
        )
        if not result.fetchone():
            connection.execute(text(
                f"ALTER TABLE `{table}` ADD INDEX `{index_name}` ({columns})"
            ))
            connection.commit()
    except Exception as e:
        print(f"Error ensuring index {index_name} on {table}: {e}")


def ensure_indexes():
    """Create helpful indexes and run column migrations for the app's most common queries."""

    try:
        with te_engine.connect() as conn:
            _ensure_column(conn, 'user', 'password_hash', 'VARCHAR(255) NULL')
            _ensure_index(conn, 'tester_records', 'idx_tester_code', '`tester_code`')
            _ensure_index(conn, 'tester_records', 'idx_remarks', '`remarks`')
            _ensure_index(conn, 'user', 'idx_user_group_badge', '`group`, `badge`')
    except Exception as e:
        print(f"Error connecting to TE DB for indexes: {e}")

    try:
        with projects_engine.connect() as proj_conn:
            _ensure_index(proj_conn, 'projects', 'idx_projects_status', '`status`')
    except Exception as e:
        print(f"Error connecting to Projects DB for indexes: {e}")

    try:
        with process_engine.connect() as proc_conn:
            _ensure_column(proc_conn, 'user', 'password_hash', 'VARCHAR(255) NULL')
            _ensure_index(proc_conn, 'process_records', 'idx_asset_id', '`asset_id`')
            _ensure_index(proc_conn, 'process_records', 'idx_asset_name', '`asset_name`')
            _ensure_index(proc_conn, 'user', 'idx_user_group_badge', '`group`, `badge`')
    except Exception as e:
        print(f"Error connecting to Process DB for indexes: {e}")