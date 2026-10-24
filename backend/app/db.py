import os
from datetime import datetime

from sqlalchemy import Column, DateTime, JSON, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://darkroom:darkroom@localhost:5432/darkroom"
)
# A relative SQLite path ("sqlite:///./darkroom.db") would land wherever uvicorn
# was started from. Pin it to backend/ so there is only ever one database.
if DATABASE_URL.startswith("sqlite:///./"):
    _backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATABASE_URL = "sqlite:///" + os.path.join(_backend, DATABASE_URL[len("sqlite:///./"):])

# SQLite needs this flag because main.py writes from a background thread.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, future=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)
Base = declarative_base()


class ObservationRow(Base):
    __tablename__ = "observations"
    observation_id = Column(String, primary_key=True)
    probe_spec_id = Column(String, index=True)
    platform = Column(String, index=True)
    outcome = Column(String)
    state = Column(JSON)  # the whole JourneyState
    created_at = Column(DateTime, default=datetime.utcnow)


class FindingRow(Base):
    __tablename__ = "findings"
    finding_id = Column(String, primary_key=True)
    platform = Column(String, index=True)
    pattern = Column(String, index=True)
    status = Column(String, index=True)
    data = Column(JSON)  # the whole Finding
    created_at = Column(DateTime, default=datetime.utcnow)


class SpecRow(Base):
    __tablename__ = "specs"
    probe_spec_id = Column(String, primary_key=True)
    platform = Column(String, index=True)
    data = Column(JSON)  # the whole ProbeSpec, incl. discovered_path
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
