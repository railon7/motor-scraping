"""Fetcher con navegador (Playwright) para sitios que renderizan en cliente. Fase F3.

Se activa con `fetch.mode: browser` en el YAML. Requiere `pip install .[browser]`
y `playwright install chromium`. Aplica las mismas reglas de cortesía que el modo HTTP:
robots.txt (con Crawl-delay), ritmo por dominio, User-Agent identificable y caché.
"""
from __future__ import annotations

import os
import time

import httpx

from scraper.config import FetchConfig, Politeness
from scraper.fetch.cache import CachedResponse, DiskCache, OfflineMiss
from scraper.fetch.http import DEFAULT_UA, DomainLimiter, FetchResult, RobotsDisallowed
from scraper.fetch.robots import RobotsCache


class BrowserFetcher:
    def __init__(self, politeness: Politeness, fetch_cfg: FetchConfig, cache: DiskCache | None = None):
        self.p = politeness
        self.cfg = fetch_cfg
        self.ua = os.getenv("USER_AGENT", DEFAULT_UA)
        self.limiter = DomainLimiter(politeness.delay_seconds)
        self.robots = RobotsCache(self.ua) if politeness.respect_robots else None
        self.cache = cache if cache and cache.enabled else None
        self._robots_client: httpx.AsyncClient | None = None
        self._pw = None
        self._browser = None
        self._context = None

    async def __aenter__(self) -> "BrowserFetcher":
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("Instala el extra 'browser': pip install .[browser] && playwright install chromium") from e
        self._robots_client = httpx.AsyncClient(timeout=10, follow_redirects=True)
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)
        self._context = await self._browser.new_context(user_agent=self.ua, extra_http_headers=self.cfg.headers or None)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        if self._robots_client:
            await self._robots_client.aclose()

    async def fetch(self, url: str, revalidate: bool = False) -> FetchResult:
        """`revalidate`: no servir de caché aunque esté fresca (listados: pueden tener items nuevos)."""
        cached = self.cache.get(url) if self.cache else None
        if cached and self.cache.is_fresh(cached) and (not revalidate or self.cache.mode == "offline"):
            self.cache.hits += 1
            return FetchResult(url=cached.final_url, status=cached.status, html=cached.html, elapsed_ms=0, from_cache=True)
        if self.cache and self.cache.mode == "offline":
            raise OfflineMiss(f"modo offline y {url} no está en caché")

        crawl_delay = None
        if self.robots:
            if not await self.robots.allowed(self._robots_client, url):
                raise RobotsDisallowed(f"robots.txt no permite {url}")
            crawl_delay = await self.robots.crawl_delay(self._robots_client, url)

        await self.limiter.wait(url, crawl_delay)
        page = await self._context.new_page()
        t0 = time.monotonic()
        try:
            resp = await page.goto(url, timeout=self.p.timeout_seconds * 1000)
            if self.cfg.wait_for:
                await page.wait_for_selector(self.cfg.wait_for, timeout=self.p.timeout_seconds * 1000)
            html = await page.content()
            status = resp.status if resp else 200
            final_url = page.url
        finally:
            await page.close()
        if self.cache:
            self.cache.put(CachedResponse(url=url, final_url=final_url, status=status, html=html, fetched_at=time.time()))
        return FetchResult(url=final_url, status=status, html=html, elapsed_ms=int((time.monotonic() - t0) * 1000))
