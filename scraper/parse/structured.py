"""Datos estructurados embebidos en la página: JSON-LD (schema.org) y etiquetas <meta>.

Suelen cambiar mucho menos que la maquetación, así que conviene usarlos antes que CSS
cuando el sitio los publica (tiendas, noticias, ofertas de empleo, eventos...).

Sintaxis en el YAML:
    jsonld:Product.name               -> primer objeto @type Product, campo name
    jsonld:Product.offers.price       -> se atraviesan objetos; en una lista se toma el primero
    jsonld:Product.offers[1].price    -> índice explícito
    jsonld:Product.image[*]           -> todos los elementos (para type: list)
    jsonld:*.datePublished            -> cualquier tipo
    meta:og:title                     -> <meta property|name|itemprop="og:title" content="...">
"""
from __future__ import annotations

import json
import logging
import re

from selectolax.parser import HTMLParser, Node

log = logging.getLogger("scraper.parse")

_STEP = re.compile(r"^(?P<key>[^\[\]]+)?(?:\[(?P<idx>\d+|\*)\])?$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def _loads_lenient(text: str):
    """JSON-LD del mundo real: a veces trae caracteres de control o comas finales."""
    for candidate in (text, _CONTROL.sub(" ", text), _TRAILING_COMMA.sub(r"\1", _CONTROL.sub(" ", text))):
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    return None


def _flatten(obj, out: list[dict]) -> None:
    """Aplana listas y @graph, y recoge también los objetos anidados con @type (p. ej. mainEntity)."""
    if isinstance(obj, list):
        for x in obj:
            _flatten(x, out)
    elif isinstance(obj, dict):
        if "@type" in obj:
            out.append(obj)
        for k, v in obj.items():
            if k == "@graph" or isinstance(v, (dict, list)):
                _flatten(v, out)


def jsonld_objects(root: Node | HTMLParser) -> list[dict]:
    objs: list[dict] = []
    for script in root.css('script[type="application/ld+json"]'):
        data = _loads_lenient(script.text(strip=True) or "")
        if data is None:
            log.debug("JSON-LD no válido, se ignora")
            continue
        _flatten(data, objs)
    return objs


def _has_type(obj: dict, wanted: str) -> bool:
    if wanted == "*":
        return True
    t = obj.get("@type")
    types = t if isinstance(t, list) else [t]
    # "schema:Product" o "http://schema.org/Product" también cuentan como Product
    return any(isinstance(x, str) and x.rsplit("/", 1)[-1].rsplit(":", 1)[-1] == wanted for x in types)


def _walk(values: list, steps: list[str]) -> list:
    for step in steps:
        m = _STEP.match(step)
        if not m:
            return []
        key, idx = m.group("key"), m.group("idx")
        nxt = []
        for v in values:
            if key is not None:
                if isinstance(v, list):  # atravesar una lista sin índice -> primer elemento
                    v = v[0] if v else None
                v = v.get(key) if isinstance(v, dict) else None
            if v is None:
                continue
            if idx is None:
                nxt.append(v)
            elif isinstance(v, list):
                if idx == "*":
                    nxt.extend(v)
                elif int(idx) < len(v):
                    nxt.append(v[int(idx)])
            elif idx in ("*", "0"):
                nxt.append(v)
        values = nxt
    return values


def _scalar(v) -> str | None:
    if isinstance(v, list):
        v = v[0] if v else None
    if isinstance(v, dict):  # {"@type": "ImageObject", "url": ...} o {"@id": ...}
        v = v.get("url") or v.get("@id") or v.get("name") or v.get("@value")
    if v is None:
        return None
    return v if isinstance(v, str) else json.dumps(v) if isinstance(v, (dict, list)) else str(v)


def jsonld_values(root: Node | HTMLParser, expr: str) -> list[str]:
    """Todos los valores que casan con `Tipo.ruta` (en orden de aparición)."""
    type_name, _, path = expr.partition(".")
    steps = [s for s in re.split(r"\.(?![^\[]*\])", path) if s] if path else []
    out: list[str] = []
    for obj in jsonld_objects(root):
        if not _has_type(obj, type_name):
            continue
        for v in _walk([obj], steps):
            items = v if isinstance(v, list) and steps and steps[-1].endswith("[*]") else [v]
            for item in items:
                s = _scalar(item)
                if s not in (None, ""):
                    out.append(s)
        if out and not (steps and "[*]" in steps[-1]):
            break  # para un valor único basta el primer objeto que lo tenga
    return out


def meta_values(root: Node | HTMLParser, name: str) -> list[str]:
    out = []
    for attr in ("property", "name", "itemprop"):
        for n in root.css(f'meta[{attr}="{name}"]'):
            v = n.attributes.get("content")
            if v:
                out.append(v.strip())
    return out
