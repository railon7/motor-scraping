"""Fetcher con navegador (Playwright) para sitios que renderizan en cliente. Fase F3.

Se activa con `fetch.mode: browser` en el YAML. Requiere `pip install .[browser]`
y `playwright install chromium`.
"""
from __future__ import annotations

import time

from scraper.config import FetchConfig, Politeness
from scraper.fetch.http import DomainLimiter, FetchResult


class BrowserFetcher:
    def __init__(self, politeness: Politeness, fetch_cfg: FetchConfig):
        self.p = politeness
        self.cfg = fetch_cfg
        self.limiter = DomainLimiter(politeness.delay_seconds)
        self._pw = None
        self._browser = None

    async def __aenter__(self) -> "BrowserFetcher":
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("Instala el extra 'browser': pip install .[browser] && playwright install chromium") from e
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def fetch(self, url: str) -> FetchResult:
        await self.limiter.wait(url)
        page = await self._browser.new_page()
        t0 = time.monotonic()
        try:
            resp = await page.goto(url, timeout=self.p.timeout_seconds * 1000)
            if self.cfg.wait_for:
                await page.wait_for_selector(self.cfg.wait_for, timeout=self.p.timeout_seconds * 1000)
            html = await page.content()
            status = resp.status if resp else 200
        finally:
            await page.close()
        return FetchResult(url=url, status=status, html=html, elapsed_ms=int((time.monotonic() - t0) * 1000))
