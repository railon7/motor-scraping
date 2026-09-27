"""Acceso a datos: engine por DB_URL, upsert de items y registro de runs."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, func, inspect, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from scraper.pipeline.dedupe import to_json
from scraper.storage.models import Base, Item, Page, Run, ScrapeError

DEFAULT_DB_URL = "sqlite:///data/scraper.db"


def get_engine(db_url: str | None = None):
    url = db_url or os.getenv("DB_URL", DEFAULT_DB_URL)
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, future=True, json_serializer=to_json)
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    if url.startswith("sqlite"):
        with engine.connect() as c:
            c.exec_driver_sql("PRAGMA journal_mode=WAL")
    return engine


def _add_missing_columns(engine) -> None:
    """Migración mínima: añade columnas e índices nuevos a bases creadas con versiones anteriores.

    Solo añade (nunca borra ni cambia tipos); las columnas nuevas son siempre anulables.
    """
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in existing:
                    ddl_type = col.type.compile(dialect=engine.dialect)
                    conn.exec_driver_sql(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl_type}')
        for table in Base.metadata.sorted_tables:
            for index in table.indexes:
                index.create(conn, checkfirst=True)


class Repo:
    def __init__(self, db_url: str | None = None):
        self.engine = get_engine(db_url)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)

    # --- runs -------------------------------------------------------------
    def start_run(self, site: str, dry_run: bool = False) -> Run:
        with self.Session() as s:
            run = Run(site=site, status="dry-run" if dry_run else "running")
            s.add(run)
            s.commit()
            return run

    def finish_run(self, run: Run, status: str = "ok") -> None:
        with self.Session() as s:
            db = s.get(Run, run.id)
            for f in ("pages", "pages_cached", "items_new", "items_updated", "items_unchanged",
                      "items_skipped", "items_gone", "errors", "notes"):
                setattr(db, f, getattr(run, f))
            db.status = status if run.status != "dry-run" else "dry-run"
            db.finished_at = datetime.now()
            s.commit()

    def last_runs(self, site: str | None = None, limit: int = 10) -> list[Run]:
        with self.Session() as s:
            q = select(Run).order_by(Run.id.desc()).limit(limit)
            if site:
                q = q.where(Run.site == site)
            return list(s.scalars(q))

    # --- pages / errors ---------------------------------------------------
    def log_page(self, run: Run, url: str, kind: str, status: int | None, elapsed_ms: int | None) -> None:
        with self.Session() as s:
            s.add(Page(run_id=run.id, url=url, kind=kind, status=status, elapsed_ms=elapsed_ms))
            s.commit()

    def log_error(self, run: Run, url: str | None, kind: str, message: str) -> None:
        with self.Session() as s:
            s.add(ScrapeError(run_id=run.id, url=url, kind=kind, message=message[:4000]))
            s.commit()

    # --- items ------------------------------------------------------------
    def upsert_item(self, run: Run, site: str, natural_key: str, content_hash: str, data: dict, source_url: str | None) -> str:
        """Devuelve 'new' | 'updated' | 'unchanged'."""
        with self.Session() as s:
            item = s.scalar(select(Item).where(Item.site == site, Item.natural_key == natural_key))
            now = datetime.now()
            if item is None:
                s.add(Item(site=site, natural_key=natural_key, content_hash=content_hash, data=data,
                           source_url=source_url, run_id=run.id, seen_run_id=run.id, fetched_at=now,
                           first_seen=now, last_seen=now, last_changed=now))
                result = "new"
            elif item.content_hash != content_hash:
                item.content_hash, item.data, item.source_url = content_hash, data, source_url
                item.last_seen = item.last_changed = now
                item.run_id = run.id
                result = "updated"
            else:
                item.last_seen = now
                result = "unchanged"
            if item is not None:
                item.seen_run_id, item.fetched_at, item.gone_at = run.id, now, None
            s.commit()
            return result

    def find_item(self, site: str, natural_key: str | None = None, source_url: str | None = None) -> Item | None:
        """Item por clave natural o, si no, por URL de origen (solo si es única)."""
        with self.Session() as s:
            if natural_key is not None:
                return s.scalar(select(Item).where(Item.site == site, Item.natural_key == natural_key))
            found = list(s.scalars(select(Item).where(Item.site == site, Item.source_url == source_url).limit(2)))
            return found[0] if len(found) == 1 else None

    def touch_item(self, run: Run, item_id: int) -> None:
        """Modo incremental: el item sigue ahí pero no se ha vuelto a descargar."""
        with self.Session() as s:
            item = s.get(Item, item_id)
            item.last_seen, item.seen_run_id, item.gone_at = datetime.now(), run.id, None
            s.commit()

    def mark_gone(self, site: str, run: Run) -> int:
        """Marca como desaparecidos los items activos que no se vieron en `run`."""
        with self.Session() as s:
            res = s.execute(
                update(Item)
                .where(Item.site == site, Item.gone_at.is_(None),
                       or_(Item.seen_run_id.is_(None), Item.seen_run_id != run.id))
                .values(gone_at=datetime.now())
            )
            s.commit()
            return res.rowcount or 0

    def items(self, site: str, include_gone: bool = True) -> list[Item]:
        with self.Session() as s:
            q = select(Item).where(Item.site == site).order_by(Item.id)
            if not include_gone:
                q = q.where(Item.gone_at.is_(None))
            return list(s.scalars(q))

    def count_items(self, site: str, include_gone: bool = True) -> int:
        with self.Session() as s:
            q = select(func.count()).select_from(Item).where(Item.site == site)
            if not include_gone:
                q = q.where(Item.gone_at.is_(None))
            return s.scalar(q)
