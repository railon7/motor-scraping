"""Listados desde APIs JSON (piloto BOE): rutas, ancestros, fechas, filtros y detalle HTML con label:."""
from datetime import date
from pathlib import Path

import pytest

from scraper.config import ConfigError, DatesConfig, load_site
from scraper.engine import Engine
from scraper.parse.jsonsel import json_values, parse_json, select_items
from scraper.parse.selectors import extract_one, parse_html
from scraper.storage.repo import Repo

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def boe_yaml(site_server, tmp_path):
    text = (FIXTURES / "boe.yaml").read_text(encoding="utf-8").replace("http://127.0.0.1:PORT", site_server)
    p = tmp_path / "boe.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def _doc():
    return parse_json((FIXTURES / "site/api/sumario/20260925.json").read_text(encoding="utf-8"))


def test_items_with_mixed_shapes():
    # item como objeto o lista, con o sin epígrafe, departamento como objeto o lista
    items = select_items(_doc(), "..item")
    assert [json_values(i, "identificador")[0] for i in items] == ["BOE-A-1", "BOE-B-1", "BOE-B-2", "BOE-B-3", "BOE-B-4"]


def test_ancestors_and_root():
    items = select_items(_doc(), "..item")
    b3 = items[3]
    assert json_values(b3, "@seccion.codigo") == ["5A"]
    assert json_values(b3, "@departamento.nombre") == ["AYUNTAMIENTO DE SEVILLA"]
    assert json_values(b3, "@epigrafe.nombre") == []  # la sección V no tiene epígrafes
    assert json_values(items[0], "@epigrafe.nombre") == ["Medidas urgentes"]
    assert json_values(items[4], "@departamento.nombre") == ["OTROS ENTES"]  # departamento como objeto
    assert json_values(b3, "$.data.sumario.metadatos.fecha_publicacion") == ["20260925"]
    assert json_values(b3, "url_pdf.pagina_inicial") == ["50200"]


def test_explicit_path_and_indexes():
    doc = _doc()
    assert len(select_items(doc, "data.sumario.diario.seccion.departamento.item")) == 4  # sin los de epígrafe
    assert json_values(doc, "data.sumario.diario[0].seccion[1].codigo") == ["5A"]
    with pytest.raises(ValueError):
        select_items(doc, "data[")


def test_json_selector_needs_json_format():
    with pytest.raises(ValueError, match="fetch.format: json"):
        extract_one(parse_html("<p>x</p>"), "json:titulo")


def test_label_selector_th_td():
    tree = parse_html("<table><tr><th>Importe :</th><td>1.200 €</td></tr><tr><th>Plazo</th><td>30 días</td></tr></table>")
    assert extract_one(tree, "label:importe") == "1.200 €"
    assert extract_one(tree, "label:Plazo") == "30 días"
    assert extract_one(tree, "label:Otro") is None


def test_dates_config():
    d = DatesConfig(start=date(2026, 9, 24), end=date(2026, 9, 28), skip_weekdays=[6])
    assert date(2026, 9, 27) not in d.days() and len(d.days()) == 4  # el 27 es domingo
    assert DatesConfig(start=-2, end=0).days(today=date(2026, 9, 27)) == [
        date(2026, 9, 25), date(2026, 9, 26), date(2026, 9, 27)]


def test_boe_like_run(boe_yaml, db_url):
    cfg = load_site(boe_yaml)
    repo = Repo(db_url)
    rep = Engine(cfg, repo).run_sync()
    # día 25: B-1 y B-3 (B-2 excluido por formalización; A-1 y B-4 no son 5A); día 26: B-5; día 24: 404 sin error
    assert rep.errors == 0 and rep.status == "ok"
    assert rep.items_new == 3 and rep.items_filtered == 3
    items = {it.data["identificador"]: it.data for it in repo.items(cfg.name)}
    assert set(items) == {"BOE-B-1", "BOE-B-3", "BOE-B-5"}
    b3 = items["BOE-B-3"]
    assert b3["departamento"] == "AYUNTAMIENTO DE SEVILLA" and b3["numero"] == 237
    assert b3["fecha"] == "2026-09-25" and b3["tipo"] == "Obras" and b3["referencia"] == "BOE-B-3"
    assert b3["texto"] == "1. Poder adjudicador: Entidad 3."
    assert items["BOE-B-5"]["departamento"] == "DIPUTACIÓN DE CÁDIZ"


def test_date_override_and_limit_ignores_filtered(boe_yaml):
    cfg = load_site(boe_yaml)
    rep = Engine(cfg, repo=None, dry_run=True, limit=1,
                 dates=DatesConfig(start=date(2026, 9, 25), end=date(2026, 9, 25))).run_sync()
    assert rep.items_seen == 1 and rep.sample[0]["identificador"] == "BOE-B-1"


def test_config_checks(tmp_path):
    base = ("name: t\nbase_url: https://x.es\nstart_urls: ['/s/{date:%Y%m%d}']\n"
            "fetch: {format: json}\nlist: {item_selector: '..item', fields: {a: {selector: 'json:a'}}}\n")
    p = tmp_path / "a.yaml"
    p.write_text(base, encoding="utf-8")
    with pytest.raises(ConfigError, match="falta el bloque 'dates'"):
        load_site(p)
    p.write_text(base + "dates: {start: -1}\n", encoding="utf-8")
    assert load_site(p).fetch.format == "json"
    p.write_text(base.replace("fields: {a:", "include: {b: 'x'}, fields: {a:") + "dates: {start: -1}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="include/exclude"):
        load_site(p)
