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

class TesterClassification(Base):
    __tablename__ = 'classification'

    classification = Column(String(50), primary_key=True)

class User(Base):
    __tablename__ = 'userv2'
    
    employee_num = Column(String(50), primary_key=True)
    name = Column(String(100))
    group = Column(String(50))
    badge = Column(String(128), unique=True)

# =========================
#  Process Records
# =========================

class ProcessRecord(Base):
        __tablename__ = 'process_records'

        id = Column(Integer, primary_key=True, autoincrement=True)
        asset_id = Column(String(50))
        asset_name = Column(String(100))
        line_no = Column(String(50))
        classification = Column(String(50))
        equip_down = Column(DateTime)
        datetime_start = Column(DateTime)
        datetime_end = Column(DateTime)
        description = Column(String(255))
        action_taken = Column(String(255))
        remarks = Column(String(10))
        pic = Column(String(50))
        logged_by           = Column(String(50))

class ProcessCredential(Base):
    __tablename__ = 'process_credential'

    # Note: Assuming 'id' exists or using process_code as primary key
    asset_id = Column(String(50), primary_key=True)
    asset_name = Column(String(255))

# ProcessUser intentionally removed — use User model with get_pe_session() instead.
# Both te.user and pe.user share the same schema, so User can be reused.
