"""Aplica un conjunto de FieldSpec sobre un nodo HTML y devuelve un dict limpio + errores."""
from __future__ import annotations

import re

from selectolax.parser import HTMLParser, Node

from scraper.config import FieldSpec
from scraper.parse.selectors import extract_all, extract_one
from scraper.pipeline.clean import clean_value


def _is_empty(v) -> bool:
    return v is None or v == "" or v == []


def _extract_raw(root: Node | HTMLParser, spec: FieldSpec, selector: str | None, base_url: str):
    many = spec.multiple or spec.type == "list"
    if selector is None:
        text = root.text(separator=" ", strip=True)
        return [text] if many else text
    return extract_all(root, selector, base_url) if many else extract_one(root, selector, base_url)


def extract_value(root: Node | HTMLParser, spec: FieldSpec, base_url: str):
    """Prueba los selectores en orden (si hay varios) y devuelve el primer valor limpio no vacío."""
    for selector in spec.selectors or [None]:
        raw = _extract_raw(root, spec, selector, base_url)
        if spec.regex and isinstance(raw, str):
            m = re.search(spec.regex, raw)
            raw = (m.group(1) if m.lastindex else m.group(0)) if m else None
        value = clean_value(raw, spec.type)
        if not _is_empty(value):
            return value
    return None


def extract_fields(root: Node | HTMLParser, fields: dict[str, FieldSpec], base_url: str) -> tuple[dict, list[str]]:
    data: dict = {}
    errors: list[str] = []
    for name, spec in fields.items():
        value = extract_value(root, spec, base_url)
        if _is_empty(value):
            value = spec.default
        if _is_empty(value) and spec.required:
            errors.append(f"campo obligatorio vacío: {name}")
        data[name] = value
    return data, errors
