"""Caché, modo incremental, desaparecidos, expect/degraded, cortacircuitos y migración."""
import sqlite3

from scraper.config import load_site
from scraper.engine import Engine
from scraper.storage.repo import Repo


def test_dry_run_reuses_cache(site_yaml):
    cfg = load_site(site_yaml)
    first = Engine(cfg, repo=None, dry_run=True).run_sync()
    second = Engine(cfg, repo=None, dry_run=True).run_sync()
    assert first.pages_cached == 0
    assert second.pages == first.pages and second.pages_cached == second.pages


def test_offline_mode_needs_cache(site_yaml):
    cfg = load_site(site_yaml)
    rep = Engine(cfg, repo=None, dry_run=True, cache_mode="offline").run_sync()
    assert rep.pages == 0 and rep.errors >= 1  # nada en caché: ninguna petición a la web
    Engine(cfg, repo=None, dry_run=True, cache_mode="on").run_sync()
    rep = Engine(cfg, repo=None, dry_run=True, cache_mode="offline").run_sync()
    assert rep.errors == 1 and rep.pages_cached == rep.pages  # solo el registro sin texto


def test_stale_cache_is_revalidated_with_304(site_yaml):
    cfg = load_site(site_yaml)
    cfg.cache.ttl_hours = 0  # todo caducado: se revalida con If-Modified-Since
    Engine(cfg, repo=None, dry_run=True).run_sync()
    rep = Engine(cfg, repo=None, dry_run=True).run_sync()
    assert rep.pages_cached == rep.pages  # el servidor de pruebas responde 304


def test_incremental_skips_known_details(site_yaml, db_url):
    cfg = load_site(site_yaml)
    cfg.detail.refresh_days = 7
    repo = Repo(db_url)
    Engine(cfg, repo).run_sync()
    rep = Engine(cfg, repo).run_sync()
    assert rep.items_skipped == 3 and rep.pages == 2  # solo los dos listados
    assert rep.items_new == rep.items_updated == 0
    assert repo.count_items(cfg.name) == 3


def test_incremental_refetches_when_list_data_changes(site_yaml, db_url):
    cfg = load_site(site_yaml)
    cfg.detail.refresh_days = 7
    repo = Repo(db_url)
    Engine(cfg, repo).run_sync()
    cfg.list.fields["precio"].type = "str"  # cambia un dato de listado ("950 €" en vez de 950.0)
    rep = Engine(cfg, repo).run_sync()
    assert rep.items_skipped == 0 and rep.items_updated == 3


def test_track_removed_marks_and_revives(site_yaml, db_url):
    cfg = load_site(site_yaml)
    cfg.track_removed = True
    repo = Repo(db_url)
    Engine(cfg, repo).run_sync()
    cfg.pagination.max_pages = 1  # la página 2 "desaparece"
    rep = Engine(cfg, repo).run_sync()
    assert rep.status == "ok" and rep.items_gone == 1
    assert repo.count_items(cfg.name, include_gone=False) == 2
    cfg.pagination.max_pages = 5  # vuelve a aparecer
    rep = Engine(cfg, repo).run_sync()
    assert rep.items_gone == 0 and repo.count_items(cfg.name, include_gone=False) == 3


def test_partial_run_does_not_mark_gone(site_yaml, db_url):
    cfg = load_site(site_yaml)
    cfg.track_removed = True
    repo = Repo(db_url)
    Engine(cfg, repo).run_sync()
    rep = Engine(cfg, repo, limit=1).run_sync()  # con --limit no se sabe qué falta
    assert rep.items_gone == 0 and repo.count_items(cfg.name, include_gone=False) == 3


def test_failed_detail_keeps_stored_data(site_yaml, db_url, monkeypatch):
    cfg = load_site(site_yaml)
    cfg.track_removed = True
    repo = Repo(db_url)
    Engine(cfg, repo).run_sync()
    before = {it.natural_key: it.data for it in repo.items(cfg.name)}

    async def detail_down(self, fetcher, url):
        self._error(url, "fetch", "HTTP 503")
        return None

    monkeypatch.setattr(Engine, "_fetch_detail", detail_down)
    rep = Engine(cfg, repo).run_sync()
    after = {it.natural_key: it.data for it in repo.items(cfg.name)}
    assert after == before  # no se pisan los datos completos con datos parciales
    assert rep.items_gone == 0  # ejecución incompleta: nada se da por desaparecido


def test_expect_marks_degraded(site_yaml, db_url):
    cfg = load_site(site_yaml)
    cfg.expect.min_items = 10
    cfg.expect.fill_rate = {"telefono": 0.9, "texto": 0.5}
    repo = Repo(db_url)
    rep = Engine(cfg, repo).run_sync()
    assert rep.status == "degraded"
    assert any("mínimo esperado 10" in w for w in rep.warnings)
    assert any("'telefono'" in w for w in rep.warnings)  # el item sin texto tampoco tiene teléfono
    run = repo.last_runs(cfg.name)[0]
    assert run.status == "degraded" and "mínimo esperado 10" in run.notes


def test_circuit_breaker_aborts(site_yaml, db_url):
    cfg = load_site(site_yaml)
    cfg.start_urls = ["/no1.html", "/no2.html", "/no3.html", "/no4.html"]
    cfg.politeness.max_consecutive_errors = 2
    rep = Engine(cfg, Repo(db_url)).run_sync()
    assert rep.status == "aborted" and rep.pages == 2
    assert "2 errores de descarga seguidos" in rep.warnings[0]


def test_old_database_is_migrated(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE runs (id INTEGER PRIMARY KEY, site VARCHAR(100), started_at DATETIME, finished_at DATETIME,
            status VARCHAR(20), pages INTEGER, items_new INTEGER, items_updated INTEGER,
            items_unchanged INTEGER, errors INTEGER);
        CREATE TABLE items (id INTEGER PRIMARY KEY, site VARCHAR(100), natural_key VARCHAR(500),
            content_hash VARCHAR(32), data JSON, source_url TEXT, first_seen DATETIME, last_seen DATETIME,
            last_changed DATETIME, run_id INTEGER);
        INSERT INTO items (site, natural_key, content_hash, data) VALUES ('s', 'k', 'h', '{}');
    """)
    con.close()
    repo = Repo(f"sqlite:///{db}")
    cols = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(items)")}
    assert {"seen_run_id", "fetched_at", "gone_at"} <= cols
    assert repo.count_items("s") == 1
