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
    # 2 páginas de listado + 3 detalles (el item sin texto no tiene detail_url)
    assert rep.pages == 5
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
