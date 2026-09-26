"""Extracción por selectores CSS con sufijos al estilo Scrapy/parsel.

Sintaxis del selector:
    "h1"                    -> texto del primer h1
    "a.titulo::attr(href)"  -> atributo href
    "div.precio::text"      -> texto (explícito)
    "div.desc::html"        -> HTML interno
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from selectolax.parser import HTMLParser, Node

_SUFFIX = re.compile(r"^(?P<css>.*?)(::(?P<kind>text|html|attr\((?P<attr>[^)]+)\)))?$")


@dataclass
class ParsedSelector:
    css: str
    kind: str  # text | html | attr
    attr: str | None = None


def parse_selector(sel: str) -> ParsedSelector:
    m = _SUFFIX.match(sel.strip())
    assert m
    css = m.group("css").strip()
    kind = m.group("kind") or "text"
    if kind.startswith("attr("):
        return ParsedSelector(css=css, kind="attr", attr=m.group("attr"))
    return ParsedSelector(css=css, kind=kind)


def _value(node: Node, ps: ParsedSelector, base_url: str | None) -> str | None:
    if ps.kind == "attr":
        v = node.attributes.get(ps.attr or "")
        if v is not None and base_url and ps.attr in ("href", "src", "action"):
            v = urljoin(base_url, v)
        return v
    if ps.kind == "html":
        return node.html
    return node.text(separator=" ", strip=True)


def _select(root: Node | HTMLParser, css: str) -> list[Node]:
    if not css:
        return [root if isinstance(root, Node) else root.root]
    return root.css(css)


def extract_one(root: Node | HTMLParser, sel: str, base_url: str | None = None) -> str | None:
    ps = parse_selector(sel)
    nodes = _select(root, ps.css)
    if not nodes:
        return None
    return _value(nodes[0], ps, base_url)


def extract_all(root: Node | HTMLParser, sel: str, base_url: str | None = None) -> list[str]:
    ps = parse_selector(sel)
    out = []
    for n in _select(root, ps.css):
        v = _value(n, ps, base_url)
        if v is not None:
            out.append(v)
    return out


def parse_html(html: str) -> HTMLParser:
    return HTMLParser(html)
