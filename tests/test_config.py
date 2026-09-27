import pytest

from scraper.config import ConfigError, json_schema, load_site


def _write(tmp_path, text):
    p = tmp_path / "s.yaml"
    p.write_text(text, encoding="utf-8")
    return p


BASE = """name: t
base_url: https://x.es
start_urls: [/]
list:
  item_selector: div
  fields:
    titulo: { selecter: h1 }
"""


def test_unknown_key_is_rejected_with_suggestion(tmp_path):
    with pytest.raises(ConfigError) as e:
        load_site(_write(tmp_path, BASE))
    msg = str(e.value)
    assert "list.fields.titulo.selecter" in msg and "¿quisiste decir 'selector'?" in msg


def test_top_level_typo(tmp_path):
    with pytest.raises(ConfigError) as e:
        load_site(_write(tmp_path, BASE.replace("selecter", "selector") + "paginacion: {max_pages: 2}\n"))
    assert "paginacion: clave desconocida; ¿quisiste decir 'pagination'?" in str(e.value)


def test_missing_required_field(tmp_path):
    with pytest.raises(ConfigError) as e:
        load_site(_write(tmp_path, "name: t\nbase_url: https://x.es\nlist: {item_selector: div}\n"))
    assert "start_urls: falta este campo obligatorio" in str(e.value)


def test_expect_fields_must_exist(tmp_path):
    text = BASE.replace("selecter", "selector") + "expect: {fill_rate: {precio: 0.9}}\n"
    with pytest.raises(ConfigError, match="expect.fill_rate"):
        load_site(_write(tmp_path, text))


def test_json_schema_has_descriptions():
    schema = json_schema()
    assert "properties" in schema and "list" in schema["properties"]
    assert "Crawl-delay" in str(schema)


def test_example_sites_are_valid():
    from pathlib import Path
    for path in Path("sites").glob("*.yaml"):
        load_site(path)
