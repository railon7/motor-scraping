"""Caché de robots.txt por dominio."""
from __future__ import annotations

import logging
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

log = logging.getLogger("scraper.robots")


class RobotsCache:
    def __init__(self, user_agent: str):
        self.ua = user_agent
        self._cache: dict[str, RobotFileParser | None] = {}

    async def allowed(self, client: httpx.AsyncClient, url: str) -> bool:
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._cache:
            rp = RobotFileParser()
            try:
                r = await client.get(f"{origin}/robots.txt", timeout=10)
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                    self._cache[origin] = rp
                else:
                    self._cache[origin] = None  # sin robots -> permitido
            except httpx.HTTPError as e:
                log.debug("robots.txt no disponible en %s: %s", origin, e)
                self._cache[origin] = None
        rp = self._cache[origin]
        return True if rp is None else rp.can_fetch(self.ua, url)
