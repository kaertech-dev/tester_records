import os
import urllib.parse
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker, scoped_session
from contextlib import contextmanager

load_dotenv()

# --- te database configuration ---
db_host=os.getenv("DB_HOST", "192.168.1.38")
db_port=os.getenv("DB_PORT", "3306")
db_user=os.getenv("DB_USER", "labeling")
db_pass=os.getenv("DB_PASSWORD", "labeling")
db_name=os.getenv("DB_NAME", "te")

te_url = URL.create(
    drivername="mysql+pymysql",
    username=db_user,
    password=db_pass,
    host=db_host,
    port=int(db_port),
    database=db_name,
    query={"charset": "utf8mb4"}
)

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
    te_url = URL.create(
        drivername="mysql+pymysql",
        username=db_user,
        password=db_pass,
        host=db_host,
        port=3306,
        database=db_name,
        query={"charset": "utf8mb4"}
    )
    te_engine = create_engine(
        te_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )

TeSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=te_engine)

# --- projectsdb database configuration ---
proj_host=os.getenv("PROJECTS_DB_HOST", "192.168.1.38")
proj_port=os.getenv("PROJECTS_DB_PORT", "3306")
proj_user=os.getenv("PROJECTS_DB_USER", "readonly_user")
proj_pass=os.getenv("PROJECTS_DB_PASSWORD", "kts@tsd2025")
proj_name=os.getenv("PROJECTS_DB_NAME", "projectsdb")

projects_url = URL.create(
    drivername="mysql+pymysql",
    username=proj_user,
    password=proj_pass,
    host=proj_host,
    port=int(proj_port),
    database=proj_name,
    query={"charset": "utf8mb4"}
)

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

# ---process database configuration---
process_db_host=os.getenv("PROCESS_DB_HOST", "192.168.1.38")
process_db_port=os.getenv("PROCESS_DB_PORT", "3306")
process_db_user=os.getenv("PROCESS_DB_USER", "labeling")
process_db_pass=os.getenv("PROCESS_DB_PASSWORD", "labeling")
process_db_name=os.getenv("PROCESS_DB_NAME", "pe")

process_url = URL.create(
    drivername="mysql+pymysql",
    username=process_db_user,
    password=process_db_pass,
    host=process_db_host,
    port=int(process_db_port),
    database=process_db_name,
    query={"charset": "utf8mb4"}
)

try:
    process_engine = create_engine(
        process_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )
    process_engine.connect().close()  # test connection
except Exception:
    # If connection fails, fallback to 3306
    process_url = URL.create(
        drivername="mysql+pymysql",
        username=process_db_user,
        password=process_db_pass,
        host=process_db_host,
        port=3306,
        database=process_db_name,
        query={"charset": "utf8mb4"}
    )
    process_engine = create_engine(
        process_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )

ProcessSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=process_engine)

@contextmanager
def get_pe_session():
    """Provide a transactional scope around a series of operations for PE DB."""
    session = ProcessSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()