import time
from sqlalchemy import create_engine, String, Float, Integer, Boolean, Text, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class SettingsRow(Base):
    __tablename__ = 'settings'
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    value: Mapped[dict] = mapped_column(JSON)


class ConnectionReport(Base):
    __tablename__ = 'connection_reports'
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    value: Mapped[dict] = mapped_column(JSON)


class Device(Base):
    __tablename__ = 'devices'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    mode: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[str] = mapped_column(String(150))
    schema: Mapped[dict] = mapped_column(JSON, default=dict)
    mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    relay: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class Sample(Base):
    __tablename__ = 'samples'
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(100), index=True)
    mode: Mapped[str] = mapped_column(String(10), index=True)
    at: Mapped[float] = mapped_column(Float, index=True)
    power: Mapped[float | None] = mapped_column(Float, nullable=True)
    voltage: Mapped[float | None] = mapped_column(Float, nullable=True)
    current: Mapped[float | None] = mapped_column(Float, nullable=True)
    energy: Mapped[float] = mapped_column(Float, default=0)  # integrated interval kWh


class Charge(Base):
    __tablename__ = 'charges'
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(100), index=True)
    mode: Mapped[str] = mapped_column(String(10), index=True)
    started: Mapped[float] = mapped_column(Float, index=True)
    ended: Mapped[float | None] = mapped_column(Float, nullable=True)
    energy: Mapped[float] = mapped_column(Float, default=0)
    average: Mapped[float] = mapped_column(Float, default=0)
    peak: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(30), default='active')


class Rule(Base):
    __tablename__ = 'rules'
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(100), index=True)
    mode: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(30))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSON)
    due_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_run: Mapped[str | None] = mapped_column(String(100), nullable=True)


class Event(Base):
    __tablename__ = 'events'
    id: Mapped[int] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(String(10), index=True)
    at: Mapped[float] = mapped_column(Float, default=time.time)
    kind: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text)


def connect(url):
    engine = create_engine(url, connect_args={'check_same_thread': False} if url.startswith('sqlite') else {}, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)
