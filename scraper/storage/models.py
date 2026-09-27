"""Modelo de datos: runs, items, pages, errors (SQLAlchemy 2).

Todas las fechas se guardan en hora local desde Python (default=datetime.now); el
server_default solo cubre filas creadas fuera del motor.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    site: Mapped[str] = mapped_column(String(100), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # running | ok | degraded (terminó pero no cumple `expect`) | aborted (cortacircuitos) | error | interrupted | dry-run
    status: Mapped[str] = mapped_column(String(20), default="running")
    pages: Mapped[int] = mapped_column(Integer, default=0)
    pages_cached: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    items_new: Mapped[int] = mapped_column(Integer, default=0)
    items_updated: Mapped[int] = mapped_column(Integer, default=0)
    items_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    items_skipped: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)  # modo incremental
    items_gone: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)  # motivos de degraded/aborted


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("site", "natural_key", name="uq_item_site_key"),
        Index("ix_items_site_source_url", "site", "source_url"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    site: Mapped[str] = mapped_column(String(100), index=True)
    natural_key: Mapped[str] = mapped_column(String(500))
    content_hash: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict] = mapped_column(JSON)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now())
    last_changed: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now())
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), nullable=True)  # último run que lo creó o cambió
    seen_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # último run en el que apareció
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # última extracción completa (detalle)
    gone_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # dejó de verse (track_removed)


class Page(Base):
    __tablename__ = "pages"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    url: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(10))  # list|detail
    status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now())


class ScrapeError(Base):
    __tablename__ = "errors"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(30))  # fetch|parse|validate
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now())
