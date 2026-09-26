"""Descubrimiento de la siguiente página de un listado."""
from __future__ import annotations

from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from scraper.config import Pagination
from scraper.parse.selectors import extract_one


def next_page_url(cfg: Pagination, current_url: str, tree: HTMLParser, page_no: int, base_url: str) -> str | None:
    """Devuelve la URL de la página siguiente o None si no hay más (o se alcanzó max_pages)."""
    if page_no >= cfg.max_pages:
        return None
    if cfg.url_template:
        return urljoin(base_url + "/", cfg.url_template.format(page=cfg.start_page + page_no))
    if cfg.next_selector:
        href = extract_one(tree, cfg.next_selector, base_url=current_url)
        if href and href != current_url:
            return href
    return None
