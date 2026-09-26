"""Clave natural y hash de contenido para upsert idempotente."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime


def _json_default(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    return str(o)


def to_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, default=_json_default)


MAX_KEY_LEN = 500  # longitud de items.natural_key


def natural_key(data: dict, key_fields: list[str], fallback: str) -> str:
    """Concatena los campos clave; usa la URL de origen si no hay 'key' o todos vienen vacíos.

    Las claves más largas que la columna se sustituyen por un prefijo legible + hash.
    """
    parts = [str(data[k]) if data.get(k) not in (None, "", []) else "" for k in key_fields]
    key = "|".join(parts) if any(parts) else fallback
    if len(key) > MAX_KEY_LEN:
        key = key[: MAX_KEY_LEN - 42] + "#" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:40]
    return key


def content_hash(data: dict) -> str:
    return hashlib.sha256(to_json(data).encode("utf-8")).hexdigest()[:32]
