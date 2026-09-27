"""robots.txt según RFC 9309: comodines `*` y `$`, regla más larga gana, Crawl-delay.

`urllib.robotparser` no entiende comodines (p. ej. `Disallow: /txt.php?*lang=ca` del BOE),
por eso usamos un parser propio.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urlparse

import httpx

log = logging.getLogger("scraper.robots")


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[bool, str]] = field(default_factory=list)  # (allow, patrón)
    crawl_delay: float | None = None


def _pattern_regex(pattern: str) -> re.Pattern:
    anchored = pattern.endswith("$")
    body = re.escape(pattern.rstrip("$")).replace(r"\*", ".*")
    return re.compile(body + ("$" if anchored else ""))


class RobotsRules:
    def __init__(self, text: str, user_agent: str):
        self.allow_all = False
        self.disallow_all = False
        groups = self._parse(text)
        token = user_agent.split("/")[0].strip().lower()
        chosen = [g for g in groups if token and token in g.agents]
        if not chosen:
            chosen = [g for g in groups if "*" in g.agents]
        self.rules = [(allow, p, _pattern_regex(p)) for g in chosen for allow, p in g.rules if p]
        delays = [g.crawl_delay for g in chosen if g.crawl_delay is not None]
        self.crawl_delay = max(delays) if delays else None

    @classmethod
    def allowing_all(cls) -> "RobotsRules":
        r = cls("", "")
        r.allow_all = True
        return r

    @classmethod
    def disallowing_all(cls) -> "RobotsRules":
        r = cls("", "")
        r.disallow_all = True
        return r

    @staticmethod
    def _parse(text: str) -> list[_Group]:
        groups: list[_Group] = []
        current: _Group | None = None
        last_was_agent = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (s.strip() for s in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if current is None or not last_was_agent:
                    current = _Group()
                    groups.append(current)
                current.agents.append(value.split("/")[0].strip().lower())
                last_was_agent = True
                continue
            last_was_agent = False
            if current is None:
                continue
            if key in ("allow", "disallow"):
                current.rules.append((key == "allow", value))
            elif key == "crawl-delay":
                try:
                    current.crawl_delay = float(value)
                except ValueError:
                    pass
        return groups

    def allowed(self, url: str) -> bool:
        if self.allow_all:
            return True
        if self.disallow_all:
            return False
        parts = urlparse(url)
        path = unquote(parts.path or "/") + (f"?{unquote(parts.query)}" if parts.query else "")
        best: tuple[int, bool] | None = None  # (longitud del patrón, allow)
        for allow, pattern, rx in self.rules:
            if rx.match(path):
                cand = (len(pattern), allow)
                # la regla más específica gana; a igual longitud, Allow
                if best is None or cand[0] > best[0] or (cand[0] == best[0] and allow):
                    best = cand
        return True if best is None else best[1]


class RobotsCache:
    def __init__(self, user_agent: str):
        self.ua = user_agent
        self._cache: dict[str, RobotsRules] = {}

    @staticmethod
    def _origin(url: str) -> str:
        parts = urlparse(url)
        return f"{parts.scheme}://{parts.netloc}"

    async def _load(self, client: httpx.AsyncClient, origin: str) -> RobotsRules:
        try:
            r = await client.get(f"{origin}/robots.txt", timeout=10, headers={"User-Agent": self.ua})
        except httpx.HTTPError as e:
            # RFC 9309: robots inaccesible -> no rastrear (lo cortés ante la duda)
            log.warning("robots.txt inaccesible en %s (%s): no se rastrea el sitio", origin, e)
            return RobotsRules.disallowing_all()
        if r.status_code >= 500:
            log.warning("robots.txt de %s responde HTTP %d: no se rastrea el sitio", origin, r.status_code)
            return RobotsRules.disallowing_all()
        if r.status_code >= 400:  # 4xx: no hay robots -> todo permitido
            return RobotsRules.allowing_all()
        return RobotsRules(r.text, self.ua)

    async def rules(self, client: httpx.AsyncClient, url: str) -> RobotsRules:
        origin = self._origin(url)
        if origin not in self._cache:
            self._cache[origin] = await self._load(client, origin)
        return self._cache[origin]

    async def allowed(self, client: httpx.AsyncClient, url: str) -> bool:
        return (await self.rules(client, url)).allowed(url)

    async def crawl_delay(self, client: httpx.AsyncClient, url: str) -> float | None:
        return (await self.rules(client, url)).crawl_delay
