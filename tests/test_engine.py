"""Prueba de extremo a extremo contra el servidor local de fixtures."""
from datetime import date

from scraper.config import load_site
from scraper.engine import Engine
from scraper.export import export_items
from scraper.storage.repo import Repo


def test_end_to_end_and_idempotent(site_yaml, db_url, tmp_path):
    cfg = load_site(site_yaml)
    repo = Repo(db_url)

    rep = Engine(cfg, repo).run_sync()
    # 2 páginas de listado + 2 fichas de autor (la de Ana sale dos veces pero se descarga una)
    assert rep.pages == 4
    assert rep.items_seen == 4
    assert rep.items_new == 3
    assert rep.errors == 1  # el registro sin 'texto' (required) se audita y no se guarda

    items = {it.data["texto"]: it.data for it in repo.items(cfg.name)}
    ana = items["“La vida es breve.”"]
    assert ana["precio"] == 1234.56
    assert ana["tags"] == ["vida", "tiempo"]
    assert ana["nacimiento"] == "1980-03-12"  # JSON serializa la fecha
    assert ana["lugar"] == "Sevilla, España"
    assert ana["telefono"] == "+34955123456"

    # Segunda ejecución: nada nuevo, nada duplicado
    rep2 = Engine(cfg, repo).run_sync()
    assert rep2.items_new == 0 and rep2.items_unchanged == 3
    assert repo.count_items(cfg.name) == 3

    runs = repo.last_runs(cfg.name)
    assert len(runs) == 2 and runs[0].status == "ok"

    # Export en los tres formatos
    for fmt in ("csv", "xlsx", "json"):
        out = export_items(repo.items(cfg.name), fmt, cfg.name, str(tmp_path / f"out.{fmt}"))
        assert out.exists() and out.stat().st_size > 0


def test_dry_run_does_not_write(site_yaml, db_url):
    cfg = load_site(site_yaml)
    rep = Engine(cfg, repo=None, dry_run=True, limit=2).run_sync()
    assert rep.items_seen == 2
    assert len(rep.sample) == 2
    assert Repo(db_url).count_items(cfg.name) == 0


def test_robots_blocks(site_server, site_yaml, db_url):
    cfg = load_site(site_yaml)
    cfg.start_urls = ["/privado/index.html"]
    rep = Engine(cfg, Repo(db_url)).run_sync()
    assert rep.pages == 0 and rep.errors >= 1


def test_url_template_end_is_not_an_error(site_yaml, db_url):
    cfg = load_site(site_yaml)
    cfg.pagination.next_selector = None
    cfg.pagination.url_template = "/page{page}.html"
    cfg.pagination.max_pages = 5
    rep = Engine(cfg, Repo(db_url)).run_sync()
    # index -> page2 -> page3 (listado vacío): fin sin error
    assert rep.items_new == 3
    assert rep.errors == 1  # solo el registro sin 'texto'


def test_url_template_404_is_not_an_error(site_yaml, db_url):
    cfg = load_site(site_yaml)
    cfg.pagination.next_selector = None
    cfg.pagination.url_template = "/pagina{page}.html"  # no existe: 404 en la p2
    rep = Engine(cfg, Repo(db_url)).run_sync()
    assert rep.items_new == 2 and rep.errors == 0


def test_meta_charset_is_respected(site_server):
    import asyncio

    from scraper.config import Politeness
    from scraper.fetch.http import HttpFetcher

    async def go():
        async with HttpFetcher(Politeness(delay_seconds=0, respect_robots=False)) as f:
            return await f.fetch(f"{site_server}/latin1.html")

    assert "Camión de España" in asyncio.run(go()).html


def test_cancelled_run_is_not_marked_ok(site_yaml, db_url, monkeypatch):
    import asyncio

    import pytest

    async def cancel(*a, **k):
        raise asyncio.CancelledError  # lo que llega al motor al pulsar Ctrl+C

    cfg = load_site(site_yaml)
    repo = Repo(db_url)
    engine = Engine(cfg, repo)
    monkeypatch.setattr(engine, "_crawl_listing", cancel)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(engine.run_async())
    assert repo.last_runs(cfg.name)[0].status == "interrupted"
