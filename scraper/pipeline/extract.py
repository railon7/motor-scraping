"""Aplica un conjunto de FieldSpec sobre un nodo HTML y devuelve un dict limpio + errores."""
from __future__ import annotations

import re

from selectolax.parser import HTMLParser, Node

from scraper.config import FieldSpec
from scraper.parse.selectors import extract_all, extract_one
from scraper.pipeline.clean import clean_value


def extract_fields(root: Node | HTMLParser, fields: dict[str, FieldSpec], base_url: str) -> tuple[dict, list[str]]:
    data: dict = {}
    errors: list[str] = []
    for name, spec in fields.items():
        if spec.multiple or spec.type == "list":
            raw = extract_all(root, spec.selector or "", base_url) if spec.selector else [root.text(strip=True)]
        else:
            raw = extract_one(root, spec.selector, base_url) if spec.selector else root.text(separator=" ", strip=True)
        if spec.regex and isinstance(raw, str):
            m = re.search(spec.regex, raw)
            raw = (m.group(1) if m.lastindex else m.group(0)) if m else None
        value = clean_value(raw, spec.type)
        if value in (None, "", []):
            value = spec.default
        if value in (None, "", []) and spec.required:
            errors.append(f"campo obligatorio vacío: {name}")
        data[name] = value
    return data, errors
