# orm_models.py
from sqlalchemy import Column, Date, Integer, String, DateTime, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()

# =========================
#  TEster Records
# =========================
class TesterRecord(Base):
    __tablename__ = 'tester_records'

    id = Column(Integer, primary_key=True, autoincrement=True)
    tester_code = Column(String(50))
    tester_name = Column(String(100))
    classification = Column(String(50))
    due_date = Column(DateTime)
    datetime_start = Column(DateTime)
    datetime_done = Column(DateTime)
    pic = Column(String(50))
    issues = Column(Text)
    action_taken = Column(Text)
    remarks = Column(String(50))

class TesterCredential(Base):
    __tablename__ = 'tester_credential'

    # Note: Assuming 'id' exists or using tester_code as primary key
    tester_code = Column(String(50), primary_key=True)
    tester_name = Column(String(100))

class User(Base):
    __tablename__ = 'user'

    group = Column(String(50), primary_key=True)
    badge = Column(String(50), primary_key=True)
    name = Column(String(100))
    employee_num = Column(String(50))

# =========================
#  Process Records
# =========================

class ProcessRecord(Base):
        __tablename__ = 'process_records'

        id = Column(Integer, primary_key=True, autoincrement=True)
        asset_id = Column(String(50))
        asset_name = Column(String(100))
        line_no = Column(String(50))
        description = Column(String(255))
        analysis = Column(String(255))
        corrective_action = Column(String(255))
        verification_result = Column(String(50))
        equip_down = Column(DateTime)
        repair_start = Column(DateTime)
        repair_end = Column(DateTime)
        troubleshoot_by = Column(String(100))
        retention_period = Column(String(50))
        effective_date = Column(Date)
        logged_by           = Column(String(50))

class ProcessCredential(Base):
    __tablename__ = 'process_credential'

    # Note: Assuming 'id' exists or using process_code as primary key
    asset_id = Column(String(50), primary_key=True)
    asset_name = Column(String(255))

# ProcessUser intentionally removed — use User model with get_pe_session() instead.
# Both te.user and pe.user share the same schema, so User can be reused.
