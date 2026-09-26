"""Acceso a datos: engine por DB_URL, upsert de items y registro de runs."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, select
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
    if url.startswith("sqlite"):
        with engine.connect() as c:
            c.exec_driver_sql("PRAGMA journal_mode=WAL")
    return engine


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
            for f in ("pages", "items_new", "items_updated", "items_unchanged", "errors"):
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
                           source_url=source_url, run_id=run.id))
                result = "new"
            elif item.content_hash != content_hash:
                item.content_hash, item.data, item.source_url = content_hash, data, source_url
                item.last_seen = item.last_changed = now
                item.run_id = run.id
                result = "updated"
            else:
                item.last_seen = now
                result = "unchanged"
            s.commit()
            return result

    def items(self, site: str) -> list[Item]:
        with self.Session() as s:
            return list(s.scalars(select(Item).where(Item.site == site).order_by(Item.id)))

    def count_items(self, site: str) -> int:
        return len(self.items(site))
