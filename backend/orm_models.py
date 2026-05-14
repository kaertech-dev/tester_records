from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()

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
