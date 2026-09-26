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
from scraper.fetch.robots import RobotsCache

log = logging.getLogger("scraper.fetch")

DEFAULT_UA = "TazukeScraper/0.1 (+https://tazuke.com)"
RETRY_STATUS = (429, 500, 502, 503, 504)
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


class DomainLimiter:
    """Garantiza un mínimo de `delay` segundos entre peticiones al mismo dominio."""

    def __init__(self, delay: float):
        self.delay = delay
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def wait(self, url: str) -> None:
        host = urlparse(url).netloc
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            last = self._last.get(host, 0.0)
            remaining = self.delay - (now - last)
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._last[host] = time.monotonic()


class HttpFetcher:
    def __init__(self, politeness: Politeness, headers: dict[str, str] | None = None):
        self.p = politeness
        ua = os.getenv("USER_AGENT", DEFAULT_UA)
        self.headers = {"User-Agent": ua, "Accept-Language": "es-ES,es;q=0.9"}
        if headers:
            self.headers.update(headers)
        self.limiter = DomainLimiter(politeness.delay_seconds)
        self.sem = asyncio.Semaphore(politeness.max_concurrency)
        self.robots = RobotsCache(ua) if politeness.respect_robots else None
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

    async def fetch(self, url: str) -> FetchResult:
        assert self._client, "Usar dentro de 'async with'"
        if self.robots and not await self.robots.allowed(self._client, url):
            raise PermissionError(f"robots.txt no permite {url}")

        last_exc: Exception | None = None
        for attempt in range(1, self.p.max_retries + 1):
            wait = min(2 ** attempt, 30)
            async with self.sem:
                await self.limiter.wait(url)
                t0 = time.monotonic()
                try:
                    r = await self._client.get(url)
                except httpx.HTTPError as e:
                    last_exc = e
                    log.warning("intento %d/%d %s: %s", attempt, self.p.max_retries, url, e)
                else:
                    elapsed = int((time.monotonic() - t0) * 1000)
                    if r.status_code in RETRY_STATUS and attempt < self.p.max_retries:
                        wait = _retry_after(r) or wait
                        log.warning("HTTP %d en %s, reintento %d en %.0fs", r.status_code, url, attempt, wait)
                    else:
                        return FetchResult(url=str(r.url), status=r.status_code, html=r.text, elapsed_ms=elapsed)
            if attempt < self.p.max_retries:
                await asyncio.sleep(wait)
        raise RuntimeError(f"No se pudo descargar {url}: {last_exc}")
