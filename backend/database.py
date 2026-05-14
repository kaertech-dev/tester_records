import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from contextlib import contextmanager

load_dotenv()

# --- te database configuration ---
db_host = os.getenv("DB_HOST", "192.168.1.38")
db_port = os.getenv("DB_PORT", "3306")
db_user = os.getenv("DB_USER", "testing")
db_pass = os.getenv("DB_PASSWORD", "testing")
db_name = os.getenv("DB_NAME", "te")

te_url = f"mysql+pymysql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}?charset=utf8mb4"

# Fallback mechanism if the provided port fails (from connect_db.py legacy logic)
try:
    te_engine = create_engine(
        te_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )
    te_engine.connect().close() # test connection
except Exception:
    # If connection fails, fallback to 3306
    te_url = f"mysql+pymysql://{db_user}:{db_pass}@{db_host}:3306/{db_name}?charset=utf8mb4"
    te_engine = create_engine(
        te_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )

TeSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=te_engine)

# --- projectsdb database configuration ---
proj_host = os.getenv("PROJECTS_DB_HOST", "192.168.1.38")
proj_port = os.getenv("PROJECTS_DB_PORT", "3306")
proj_user = os.getenv("PROJECTS_DB_USER", "readonly_user")
proj_pass = os.getenv("PROJECTS_DB_PASSWORD", "kts@tsd2025")
proj_name = os.getenv("PROJECTS_DB_NAME", "projectsdb")

projects_url = f"mysql+pymysql://{proj_user}:{proj_pass}@{proj_host}:{proj_port}/{proj_name}?charset=utf8mb4"

projects_engine = create_engine(
    projects_url,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

ProjectsSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=projects_engine)

@contextmanager
def get_te_session():
    """Provide a transactional scope around a series of operations for TE DB."""
    session = TeSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

@contextmanager
def get_projects_session():
    """Provide a transactional scope around a series of operations for Projects DB."""
    session = ProjectsSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
