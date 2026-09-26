"""Orquestador: start_urls -> listados (paginación) -> items -> detalle -> pipeline -> storage."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from urllib.parse import urljoin

from scraper.config import SiteConfig
from scraper.fetch.http import HttpFetcher
from scraper.parse.pagination import next_page_url
from scraper.parse.selectors import extract_one, parse_html
from scraper.pipeline.dedupe import content_hash, natural_key
from scraper.pipeline.extract import extract_fields
from scraper.storage.repo import Repo

log = logging.getLogger("scraper.engine")


@dataclass
class RunReport:
    site: str
    dry_run: bool
    pages: int = 0
    items_seen: int = 0
    items_new: int = 0
    items_updated: int = 0
    items_unchanged: int = 0
    errors: int = 0
    empty_fields: dict[str, int] = field(default_factory=dict)
    sample: list[dict] = field(default_factory=list)

    def note_empty(self, data: dict) -> None:
        for k, v in data.items():
            if v in (None, "", []):
                self.empty_fields[k] = self.empty_fields.get(k, 0) + 1


class Engine:
    def __init__(self, cfg: SiteConfig, repo: Repo | None, dry_run: bool = False, limit: int | None = None):
        self.cfg = cfg
        self.repo = repo
        self.dry_run = dry_run
        self.limit = limit  # máximo de items a procesar (útil en dry-run)
        self.report = RunReport(site=cfg.name, dry_run=dry_run)
        self.run = None

    def _make_fetcher(self):
        if self.cfg.fetch.mode == "browser":
            from scraper.fetch.browser import BrowserFetcher
            return BrowserFetcher(self.cfg.politeness, self.cfg.fetch)
        return HttpFetcher(self.cfg.politeness, self.cfg.fetch.headers)

    async def run_async(self) -> RunReport:
        if self.repo:
            self.run = self.repo.start_run(self.cfg.name, dry_run=self.dry_run)
        status = "ok"
        try:
            async with self._make_fetcher() as fetcher:
                for start in self.cfg.start_urls:
                    await self._crawl_listing(fetcher, urljoin(self.cfg.base_url + "/", start))
                    if self._reached_limit():
                        break
        except Exception as e:  # error global -> run en estado error
            status = "error"
            self._error(None, "fetch", f"{type(e).__name__}: {e}")
            log.exception("Ejecución abortada")
        finally:
            if self.repo and self.run:
                r = self.run
                r.pages, r.items_new, r.items_updated = self.report.pages, self.report.items_new, self.report.items_updated
                r.items_unchanged, r.errors = self.report.items_unchanged, self.report.errors
                self.repo.finish_run(r, status)
        return self.report

    def run_sync(self) -> RunReport:
        return asyncio.run(self.run_async())

    # ------------------------------------------------------------------
    def _reached_limit(self) -> bool:
        return self.limit is not None and self.report.items_seen >= self.limit

    def _error(self, url: str | None, kind: str, msg: str) -> None:
        self.report.errors += 1
        log.warning("%s %s: %s", kind, url or "", msg)
        if self.repo and self.run and not self.dry_run:
            self.repo.log_error(self.run, url, kind, msg)

    async def _fetch_page(self, fetcher, url: str, kind: str):
        try:
            res = await fetcher.fetch(url)
        except Exception as e:
            self._error(url, "fetch", f"{type(e).__name__}: {e}")
            return None
        self.report.pages += 1
        if self.repo and self.run and not self.dry_run:
            self.repo.log_page(self.run, res.url, kind, res.status, res.elapsed_ms)
        if res.status >= 400:
            self._error(url, "fetch", f"HTTP {res.status}")
            return None
        return res

    async def _crawl_listing(self, fetcher, url: str) -> None:
        page_no = 0
        seen_urls: set[str] = set()
        while url and url not in seen_urls:
            seen_urls.add(url)
            page_no += 1
            log.info("[%s] listado p%d %s", self.cfg.name, page_no, url)
            res = await self._fetch_page(fetcher, url, "list")
            if res is None:
                return
            tree = parse_html(res.html)
            nodes = tree.css(self.cfg.list.item_selector)
            if not nodes:
                self._error(url, "parse", f"item_selector '{self.cfg.list.item_selector}' no devolvió elementos")
                return

            # Procesamos items de la página con concurrencia limitada por el fetcher
            tasks = []
            for node in nodes:
                if self._reached_limit():
                    break
                self.report.items_seen += 1
                tasks.append(self._process_item(fetcher, node, res.url))
            await asyncio.gather(*tasks)

            if self._reached_limit():
                return
            url = next_page_url(self.cfg.pagination, res.url, tree, page_no, self.cfg.base_url)

    async def _process_item(self, fetcher, node, list_url: str) -> None:
        data, errs = extract_fields(node, self.cfg.list.fields, list_url)
        source_url = list_url
        detail_url = extract_one(node, self.cfg.list.detail_url, base_url=list_url) if self.cfg.list.detail_url else None

        if self.cfg.detail and detail_url:
            res = await self._fetch_page(fetcher, detail_url, "detail")
            if res is not None:
                source_url = res.url
                d_data, d_errs = extract_fields(parse_html(res.html), self.cfg.detail.fields, res.url)
                data.update(d_data)
                errs += d_errs
        elif detail_url:
            data.setdefault("detail_url", detail_url)

        self.report.note_empty(data)
        if len(self.report.sample) < 5:
            self.report.sample.append(data)

        if errs:
            self._error(source_url, "validate", "; ".join(errs))
            return  # registro inválido: se audita y no se guarda

        key = natural_key(data, self.cfg.key, fallback=detail_url or source_url)
        h = content_hash(data)
        if self.dry_run or not self.repo:
            self.report.items_new += 1
            return
        result = self.repo.upsert_item(self.run, self.cfg.name, key, h, data, source_url)
        setattr(self.report, f"items_{result}", getattr(self.report, f"items_{result}") + 1)
