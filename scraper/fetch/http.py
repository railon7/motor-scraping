"""Fetcher HTTP asíncrono: rate-limit por dominio, reintentos con backoff y robots.txt."""
from __future__ import annotations

import asyncio
import codecs
import logging
import os
import re
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from scraper.config import Politeness
from scraper.fetch.cache import CachedResponse, DiskCache, OfflineMiss
from scraper.fetch.robots import RobotsCache

log = logging.getLogger("scraper.fetch")

DEFAULT_UA = "TazukeScraper/0.1 (+https://tazuke.com)"
MAX_RETRY_AFTER = 120  # segundos; si el sitio pide esperar más, mejor fallar y reintentar otro día
_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([\w-]+)""", re.I)


def _retry_after(r: httpx.Response) -> float | None:
    """Segundos indicados en la cabecera Retry-After (solo formato numérico)."""
    v = r.headers.get("retry-after", "").strip()
    return min(float(v), MAX_RETRY_AFTER) if v.isdigit() else None


def _detect_encoding(content: bytes) -> str:
    """Codificación cuando la cabecera Content-Type no la indica: <meta charset> o UTF-8."""
    m = _META_CHARSET.search(content[:4096])
    if m:
        try:
            return codecs.lookup(m.group(1).decode("ascii")).name
        except LookupError:
            pass
    return "utf-8"


@dataclass
class FetchResult:
    url: str
    status: int
    html: str
    elapsed_ms: int
    from_cache: bool = False


class RobotsDisallowed(PermissionError):
    """La URL está prohibida por robots.txt (no es un fallo del sitio: no se reintenta)."""


class DomainLimiter:
    """Garantiza un mínimo de `delay` segundos entre peticiones al mismo dominio.

    Además permite "frenar" un dominio entero (p. ej. tras un 429) con `backoff`.
    """

    def __init__(self, delay: float):
        self.delay = delay
        self._last: dict[str, float] = {}
        self._not_before: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def wait(self, url: str, delay: float | None = None) -> None:
        host = urlparse(url).netloc
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            gap = max(self.delay, delay or 0.0)
            ready_at = max(self._last.get(host, 0.0) + gap, self._not_before.get(host, 0.0))
            if ready_at > now:
                await asyncio.sleep(ready_at - now)
            self._last[host] = time.monotonic()

    def backoff(self, url: str, seconds: float) -> None:
        host = urlparse(url).netloc
        self._not_before[host] = max(self._not_before.get(host, 0.0), time.monotonic() + seconds)


class HttpFetcher:
    def __init__(self, politeness: Politeness, headers: dict[str, str] | None = None,
                 cache: DiskCache | None = None):
        self.p = politeness
        ua = os.getenv("USER_AGENT", DEFAULT_UA)
        self.headers = {"User-Agent": ua, "Accept-Language": "es-ES,es;q=0.9"}
        if headers:
            self.headers.update(headers)
        self.limiter = DomainLimiter(politeness.delay_seconds)
        self.sem = asyncio.Semaphore(politeness.max_concurrency)
        self.robots = RobotsCache(ua) if politeness.respect_robots else None
        self.cache = cache if cache and cache.enabled else None
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "HttpFetcher":
        self._client = httpx.AsyncClient(
            headers=self.headers,
            timeout=self.p.timeout_seconds,
            follow_redirects=True,
            default_encoding=_detect_encoding,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.aclose()

    async def fetch(self, url: str, revalidate: bool = False) -> FetchResult:
        """`revalidate`: no servir de caché aunque esté fresca (listados: pueden tener items nuevos)."""
        assert self._client, "Usar dentro de 'async with'"
        cached = self.cache.get(url) if self.cache else None
        if cached and self.cache.is_fresh(cached) and (not revalidate or self.cache.mode == "offline"):
            self.cache.hits += 1
            return FetchResult(url=cached.final_url, status=cached.status, html=cached.html, elapsed_ms=0, from_cache=True)
        if self.cache and self.cache.mode == "offline":
            raise OfflineMiss(f"modo offline y {url} no está en caché")

        crawl_delay = None
        if self.robots:
            if not await self.robots.allowed(self._client, url):
                raise RobotsDisallowed(f"robots.txt no permite {url}")
            crawl_delay = await self.robots.crawl_delay(self._client, url)

        # Revalidación de una entrada caducada: si el servidor responde 304 no se descarga de nuevo
        conditional = {}
        if cached and cached.etag:
            conditional["If-None-Match"] = cached.etag
        if cached and cached.last_modified:
            conditional["If-Modified-Since"] = cached.last_modified

        last_exc: Exception | None = None
        for attempt in range(1, self.p.max_retries + 1):
            wait = min(2 ** attempt, 30)
            async with self.sem:
                await self.limiter.wait(url, crawl_delay)
                t0 = time.monotonic()
                try:
                    r = await self._client.get(url, headers=conditional)
                except httpx.HTTPError as e:
                    last_exc = e
                    log.warning("intento %d/%d %s: %s", attempt, self.p.max_retries, url, e)
                else:
                    elapsed = int((time.monotonic() - t0) * 1000)
                    if r.status_code == 304 and cached:
                        self.cache.touch(cached)
                        self.cache.hits += 1
                        return FetchResult(url=cached.final_url, status=cached.status, html=cached.html,
                                           elapsed_ms=elapsed, from_cache=True)
                    if r.status_code in self.p.retry_status and attempt < self.p.max_retries:
                        wait = _retry_after(r) or wait
                        if r.status_code == 429:  # frena todo el dominio, no solo esta URL
                            self.limiter.backoff(url, wait)
                        log.warning("HTTP %d en %s, reintento %d en %.0fs", r.status_code, url, attempt, wait)
                    else:
                        if self.cache:
                            self.cache.put(CachedResponse(
                                url=url, final_url=str(r.url), status=r.status_code, html=r.text,
                                fetched_at=time.time(), etag=r.headers.get("etag"),
                                last_modified=r.headers.get("last-modified")))
                        return FetchResult(url=str(r.url), status=r.status_code, html=r.text, elapsed_ms=elapsed)
            if attempt < self.p.max_retries:
                await asyncio.sleep(wait)
        raise RuntimeError(f"No se pudo descargar {url}: {last_exc}")
