"""Caché de respuestas en disco (un fichero gzip+JSON por URL).

Modos:
    off      -> no se usa
    on       -> se sirve lo fresco (< ttl); lo caducado se revalida con ETag/Last-Modified
    offline  -> solo caché, sin red (para ajustar selectores sin volver a pedir nada al sitio)
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

CacheMode = Literal["off", "on", "offline"]


@dataclass
class CachedResponse:
    url: str            # URL pedida
    final_url: str      # URL tras redirecciones
    status: int
    html: str
    fetched_at: float   # epoch
    etag: str | None = None
    last_modified: str | None = None

    def age_hours(self) -> float:
        return (time.time() - self.fetched_at) / 3600


class OfflineMiss(Exception):
    """En modo offline se pidió una URL que no está en caché."""


class DiskCache:
    def __init__(self, directory: str | Path, mode: CacheMode = "on", ttl_hours: float = 24):
        self.dir = Path(directory)
        self.mode = mode
        self.ttl_hours = ttl_hours
        self.hits = 0

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    def _path(self, url: str) -> Path:
        h = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return self.dir / h[:2] / f"{h}.json.gz"

    def get(self, url: str) -> CachedResponse | None:
        p = self._path(url)
        if not p.exists():
            return None
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                return CachedResponse(**json.load(f))
        except (OSError, ValueError, TypeError):
            return None  # entrada corrupta: se ignora y se sobrescribirá

    def is_fresh(self, entry: CachedResponse) -> bool:
        return self.mode == "offline" or entry.age_hours() < self.ttl_hours

    def put(self, entry: CachedResponse) -> None:
        # Solo respuestas útiles: ni errores de servidor ni 429 (serían "veneno" en la caché)
        if entry.status >= 400:
            return
        p = self._path(entry.url)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as raw, gzip.open(raw, "wt", encoding="utf-8") as f:
                json.dump(entry.__dict__, f, ensure_ascii=False)
            os.replace(tmp, p)  # escritura atómica
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def touch(self, entry: CachedResponse) -> None:
        """Revalidada con 304: renueva la fecha sin cambiar el contenido."""
        entry.fetched_at = time.time()
        self.put(entry)
