"""Orquestador: start_urls -> listados (paginación) -> items -> detalle -> pipeline -> storage."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

from scraper.config import DatesConfig, SiteConfig
from scraper.fetch.cache import CacheMode, DiskCache
from scraper.fetch.http import HttpFetcher, RobotsDisallowed
from scraper.parse.jsonsel import parse_json, select_items
from scraper.parse.pagination import next_page_url
from scraper.parse.selectors import document_base, extract_one, parse_html
from scraper.pipeline.dedupe import content_hash, natural_key, to_json
from scraper.pipeline.extract import extract_fields
from scraper.storage.repo import Repo

log = logging.getLogger("scraper.engine")

# Si más de esta proporción de items es inválida, probablemente se rompió un selector:
# no se marca nada como desaparecido para no confundir "mal leído" con "ya no está".
MAX_INVALID_RATIO = 0.2


@dataclass
class RunReport:
    site: str
    dry_run: bool
    status: str = "running"
    pages: int = 0
    pages_cached: int = 0
    items_seen: int = 0
    items_new: int = 0
    items_updated: int = 0
    items_unchanged: int = 0
    items_skipped: int = 0   # modo incremental: detalle no descargado porque no hacía falta
    items_gone: int = 0      # track_removed: dejaron de verse en esta ejecución
    items_invalid: int = 0   # descartados por campos obligatorios vacíos
    items_filtered: int = 0  # descartados por list.include / list.exclude (no cuentan como vistos)
    errors: int = 0
    warnings: list[str] = field(default_factory=list)  # incumplimientos de `expect` o motivo de aborto
    empty_fields: dict[str, int] = field(default_factory=dict)
    sample: list[dict] = field(default_factory=list)

    def note_empty(self, data: dict, field_names) -> None:
        """Cuenta como vacío también un campo que ni siquiera llegó a extraerse (p. ej. sin detalle)."""
        for k in dict.fromkeys([*field_names, *data]):
            if data.get(k) in (None, "", []):
                self.empty_fields[k] = self.empty_fields.get(k, 0) + 1

    @property
    def items_extracted(self) -> int:
        """Items cuyos campos se extrajeron en esta ejecución (los saltados por incremental no cuentan)."""
        return self.items_seen - self.items_skipped

    def fill_rate(self, field_name: str) -> float:
        if not self.items_extracted:
            return 1.0
        return 1 - self.empty_fields.get(field_name, 0) / self.items_extracted


class Engine:
    def __init__(self, cfg: SiteConfig, repo: Repo | None, dry_run: bool = False, limit: int | None = None,
                 cache_mode: CacheMode | None = None, dates: DatesConfig | None = None):
        self.cfg = cfg
        self.dates = dates  # sustituye a cfg.dates (CLI --desde/--hasta)
        self._include = {k: re.compile(v) for k, v in cfg.list.include.items()}
        self._exclude = {k: re.compile(v) for k, v in cfg.list.exclude.items()}
        self.repo = repo
        self.dry_run = dry_run
        self.limit = limit  # máximo de items a procesar (útil en dry-run)
        self.report = RunReport(site=cfg.name, dry_run=dry_run)
        self.run = None
        # dry-run usa la caché por defecto: probar selectores no debe volver a pedir las páginas al sitio
        mode = cache_mode or ("on" if cfg.cache.enabled or dry_run else "off")
        cache_root = Path(os.getenv("CACHE_DIR", "data/cache"))
        self.cache = DiskCache(cache_root / cfg.name, mode=mode, ttl_hours=cfg.cache.ttl_hours)
        # Una descarga por URL de detalle y ejecución (p. ej. la misma ficha de autor en varios items)
        self._details: dict[str, asyncio.Task] = {}
        self._consecutive_errors = 0
        self._abort: str | None = None
        # Alguna página de listado o de detalle falló: no se puede deducir qué items desaparecieron
        self._incomplete = False

    def _make_fetcher(self):
        if self.cfg.fetch.mode == "browser":
            from scraper.fetch.browser import BrowserFetcher
            return BrowserFetcher(self.cfg.politeness, self.cfg.fetch, cache=self.cache)
        return HttpFetcher(self.cfg.politeness, self.cfg.fetch.headers, cache=self.cache)

    @property
    def _writes(self) -> bool:
        return bool(self.repo and self.run and not self.dry_run)

    async def run_async(self) -> RunReport:
        if self.repo:
            self.run = self.repo.start_run(self.cfg.name, dry_run=self.dry_run)
        status = "interrupted"  # si sale por Ctrl+C / cancelación no queda como "ok"
        try:
            async with self._make_fetcher() as fetcher:
                for start, by_date in self.cfg.expanded_start_urls(self.dates):
                    await self._crawl_listing(fetcher, urljoin(self.cfg.base_url + "/", start), by_date)
                    if self._reached_limit() or self._abort:
                        break
            status = self._final_status()
        except Exception as e:  # error global -> run en estado error
            status = "error"
            self._error(None, "fetch", f"{type(e).__name__}: {e}")
            log.exception("Ejecución abortada")
        finally:
            self.report.status = status
            if self.repo and self.run:
                r = self.run
                for f in ("pages", "pages_cached", "items_new", "items_updated", "items_unchanged",
                          "items_skipped", "items_gone", "errors"):
                    setattr(r, f, getattr(self.report, f))
                r.notes = "\n".join(self.report.warnings) or None
                self.repo.finish_run(r, status)
        return self.report

    def run_sync(self) -> RunReport:
        return asyncio.run(self.run_async())

    # ------------------------------------------------------------------
    def _final_status(self) -> str:
        if self._abort:
            self.report.warnings.append(self._abort)
            return "aborted"
        complete = self.limit is None and not self._incomplete
        if complete:
            self.report.warnings += self._check_expect()
        if self.report.warnings:
            return "degraded"
        many_invalid = self.report.items_invalid > MAX_INVALID_RATIO * max(self.report.items_seen, 1)
        if complete and self.cfg.track_removed and self._writes and many_invalid:
            log.warning("[%s] demasiados items inválidos (%d): no se marca ninguno como desaparecido",
                        self.cfg.name, self.report.items_invalid)
        elif complete and self.cfg.track_removed and self._writes:
            self.report.items_gone = self.repo.mark_gone(self.cfg.name, self.run)
            if self.report.items_gone:
                log.info("[%s] %d items ya no aparecen (marcados gone)", self.cfg.name, self.report.items_gone)
        return "ok"

    def _check_expect(self) -> list[str]:
        """Señales de que los selectores se han roto aunque la ejecución 'funcione'."""
        exp, rep, out = self.cfg.expect, self.report, []
        if exp.min_items is not None and rep.items_seen < exp.min_items:
            out.append(f"solo {rep.items_seen} items (mínimo esperado {exp.min_items})")
        for name, minimum in exp.fill_rate.items():
            rate = rep.fill_rate(name)
            if rep.items_extracted and rate < minimum:
                out.append(f"campo '{name}' relleno en el {rate:.0%} de los items (mínimo {minimum:.0%})")
        return out

    def _reached_limit(self) -> bool:
        return self.limit is not None and self.report.items_seen >= self.limit

    def _error(self, url: str | None, kind: str, msg: str) -> None:
        self.report.errors += 1
        log.warning("%s %s: %s", kind, url or "", msg)
        if self._writes:
            self.repo.log_error(self.run, url, kind, msg)

    def _fetch_failed(self, url: str, kind: str, msg: str) -> None:
        self._error(url, kind, msg)
        self._consecutive_errors += 1
        limit = self.cfg.politeness.max_consecutive_errors
        if limit and self._consecutive_errors >= limit and not self._abort:
            self._abort = f"abortado tras {self._consecutive_errors} errores de descarga seguidos (último: {msg})"
            log.error("[%s] %s", self.cfg.name, self._abort)

    async def _fetch_page(self, fetcher, url: str, kind: str, not_found_ok: bool = False):
        if self._abort:
            return None
        try:
            # En ejecuciones reales los listados se revalidan siempre (304 si no cambiaron)
            res = await fetcher.fetch(url, revalidate=kind == "list" and not self.dry_run)
        except RobotsDisallowed as e:  # decisión nuestra, no fallo del sitio: no cuenta para el cortacircuitos
            self._error(url, "robots", str(e))
            return None
        except Exception as e:
            self._fetch_failed(url, "fetch", f"{type(e).__name__}: {e}")
            return None
        self.report.pages += 1
        if res.from_cache:
            self.report.pages_cached += 1
        if self._writes:
            self.repo.log_page(self.run, res.url, kind, res.status, res.elapsed_ms)
        if res.status >= 400:
            if res.status in (404, 410) and not_found_ok:
                log.info("[%s] %s devuelve HTTP %d, fin del listado", self.cfg.name, url, res.status)
            else:
                self._fetch_failed(url, "fetch", f"HTTP {res.status}")
            return None
        self._consecutive_errors = 0
        return res

    async def _crawl_listing(self, fetcher, url: str, by_date: bool = False) -> None:
        """`by_date`: URL generada para un día; un 404 o un día sin items es normal (no hubo publicación)."""
        page_no = 0
        seen_urls: set[str] = set()
        while url and url not in seen_urls and not self._abort:
            seen_urls.add(url)
            page_no += 1
            log.info("[%s] listado p%d %s", self.cfg.name, page_no, url)
            # Pasada la primera página, un 404 es la forma habitual de decir "no hay más"
            errors_before = self.report.errors
            res = await self._fetch_page(fetcher, url, "list", not_found_ok=page_no > 1 or by_date)
            if res is None:
                if self.report.errors > errors_before:  # falló (no es un 404 de fin de listado)
                    self._incomplete = True
                return
            try:
                tree, page_base, nodes = self._parse_listing(res)
            except ValueError as e:
                self._incomplete = True
                self._error(url, "parse", f"respuesta no válida: {e}")
                return
            if not nodes:
                if page_no > 1 or by_date:  # página vacía tras la primera (o día sin items): fin normal
                    log.info("[%s] sin items en p%d, fin del listado", self.cfg.name, page_no)
                else:
                    self._incomplete = True
                    self._error(url, "parse", f"item_selector '{self.cfg.list.item_selector}' no devolvió elementos")
                return

            # Procesamos items de la página con concurrencia limitada por el fetcher
            tasks = []
            for node in nodes:
                # Los campos del listado se extraen aquí para filtrar antes de contar (y de aplicar --limit)
                data, errs = extract_fields(node, self.cfg.list.fields, page_base)
                if not self._passes_filters(data):
                    self.report.items_filtered += 1
                    continue
                if self._reached_limit():
                    break
                self.report.items_seen += 1
                tasks.append(self._process_item(fetcher, node, page_base, data, errs))
            await asyncio.gather(*tasks)

            if self._reached_limit():
                return
            url = next_page_url(self.cfg.pagination, page_base, tree, page_no, self.cfg.base_url)

    def _parse_listing(self, res):
        if self.cfg.fetch.format == "json":
            root = parse_json(res.html)
            return root, res.url, select_items(root, self.cfg.list.item_selector)
        tree = parse_html(res.html)
        return tree, document_base(tree, res.url), tree.css(self.cfg.list.item_selector)

    def _passes_filters(self, data: dict) -> bool:
        def text(k):
            v = data.get(k)
            return "" if v is None else str(v)
        if any(not rx.search(text(k)) for k, rx in self._include.items()):
            return False
        return not any(rx.search(text(k)) for k, rx in self._exclude.items())

    async def _fetch_detail(self, fetcher, url: str) -> tuple[str, dict, list[str]] | None:
        res = await self._fetch_page(fetcher, url, "detail")
        if res is None:
            return None
        tree = parse_html(res.html)
        data, errs = extract_fields(tree, self.cfg.detail.fields, document_base(tree, res.url))
        return res.url, data, errs

    def _unchanged_since_last_fetch(self, list_data: dict, detail_url: str):
        """Modo incremental: item guardado, descargado hace poco y con los mismos datos de listado."""
        days = self.cfg.detail.refresh_days if self.cfg.detail else None
        if days is None or not self._writes:
            return None
        list_fields = set(self.cfg.list.fields)
        if not self.cfg.key or set(self.cfg.key) <= list_fields:
            item = self.repo.find_item(self.cfg.name, natural_key=natural_key(list_data, self.cfg.key, fallback=detail_url))
        else:  # la clave depende del detalle: buscamos por URL (solo si identifica un único item)
            item = self.repo.find_item(self.cfg.name, source_url=detail_url)
        if item is None or item.fetched_at is None:
            return None
        if datetime.now() - item.fetched_at > timedelta(days=days):
            return None
        stored = {k: item.data.get(k) for k in list_fields}
        current = {k: list_data.get(k) for k in list_fields}
        return item if to_json(stored) == to_json(current) else None

    async def _process_item(self, fetcher, node, list_url: str, data: dict, errs: list[str]) -> None:
        source_url = list_url
        detail_url = extract_one(node, self.cfg.list.detail_url, base_url=list_url) if self.cfg.list.detail_url else None
        if detail_url:
            detail_url = urljoin(list_url, detail_url)  # en JSON las URLs pueden venir relativas

        if self.cfg.detail and detail_url:
            known = self._unchanged_since_last_fetch(data, detail_url)
            if known is not None:
                self.repo.touch_item(self.run, known.id)
                self.report.items_skipped += 1
                return
            if detail_url not in self._details:
                self._details[detail_url] = asyncio.create_task(self._fetch_detail(fetcher, detail_url))
            detail = await self._details[detail_url]
            if detail is None:
                # Sin detalle no guardamos: se pisarían los datos completos ya almacenados con datos parciales
                self._incomplete = True
                return
            source_url, d_data, d_errs = detail
            data.update(d_data)
            errs += d_errs
        elif detail_url:
            data.setdefault("detail_url", detail_url)

        self.report.note_empty(data, self.cfg.all_fields)
        if len(self.report.sample) < 5:
            self.report.sample.append(data)

        if errs:
            self.report.items_invalid += 1
            self._error(source_url, "validate", "; ".join(errs))
            return  # registro inválido: se audita y no se guarda

        key = natural_key(data, self.cfg.key, fallback=detail_url or source_url)
        h = content_hash(data)
        if self.dry_run or not self.repo:
            self.report.items_new += 1
            return
        result = self.repo.upsert_item(self.run, self.cfg.name, key, h, data, source_url)
        setattr(self.report, f"items_{result}", getattr(self.report, f"items_{result}") + 1)
