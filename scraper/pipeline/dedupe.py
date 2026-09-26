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


def natural_key(data: dict, key_fields: list[str], fallback: str) -> str:
    """Concatena los campos clave; si no hay 'key' en el YAML usa la URL de origen."""
    if not key_fields:
        return fallback
    parts = [str(data.get(k) if data.get(k) is not None else "") for k in key_fields]
    return "|".join(parts)


def content_hash(data: dict) -> str:
    return hashlib.sha256(to_json(data).encode("utf-8")).hexdigest()[:32]
