# Motor Scraping (Tazuke)

Motor de web scraping **genérico y clonable**: el núcleo no sabe nada del sitio objetivo; cada web se describe en un YAML (`sites/<nombre>.yaml`) con URLs de arranque, paginación, selectores y tipos de campo. Los datos se guardan en SQLite (Postgres/Supabase opcional) sin duplicados y se exportan a CSV / Excel / JSON.

Estado: **F1 (núcleo HTTP) funcional**. Plan completo y fases en [PLAN.md](PLAN.md).

## Arranque en 5 minutos

```bash
git clone https://github.com/railon7/motor-scraping.git mi-proyecto-scraping
cd mi-proyecto-scraping
python -m venv .venv && .venv\Scripts\activate      # Windows  (Linux/Mac: source .venv/bin/activate)
pip install -e .[dev]
copy .env.example .env                              # Linux/Mac: cp
scraper validate sites/ejemplo.yaml
scraper dry-run  sites/ejemplo.yaml --limit 5       # prueba selectores sin escribir nada
scraper run      sites/ejemplo.yaml --export xlsx   # scrapea, guarda en data/scraper.db y exporta
scraper status   sites/ejemplo.yaml
```

## Comandos

| Comando | Qué hace |
|---|---|
| `scraper init-site <nombre>` | Crea `sites/<nombre>.yaml` con un esqueleto comentado |
| `scraper validate <yaml>` | Comprueba la sintaxis de la configuración |
| `scraper dry-run <yaml> [--limit N]` | Descarga y extrae N items sin tocar la BBDD; muestra muestra y campos vacíos |
| `scraper run <yaml> [--limit N] [--export csv\|xlsx\|json]` | Ejecución real con upsert idempotente |
| `scraper export <yaml> [-f fmt] [-o fichero]` | Exporta lo almacenado |
| `scraper status [<yaml>]` | Últimas ejecuciones y métricas |

## Cómo añadir un sitio nuevo

1. `scraper init-site mi-sitio` y edita `sites/mi-sitio.yaml`.
2. Ajusta `item_selector` (bloque de cada registro en el listado) y los `fields`.
   Sintaxis de selectores: CSS + sufijo opcional `::text` (defecto), `::attr(href)`, `::html`.
3. Tipos disponibles: `str, int, float, money, date, datetime, phone, email, url, list`.
   `required: true` descarta el registro (y lo audita en `errors`) si el campo queda vacío.
4. Define `key:` con los campos que identifican un registro (si no, se usa la URL de detalle).
5. `scraper dry-run` hasta que la tabla de campos vacíos esté limpia; después `scraper run`.

Guía detallada en [docs/NUEVO-SITIO.md](docs/NUEVO-SITIO.md). Antes de scrapear un sitio nuevo, revisa [docs/LEGAL.md](docs/LEGAL.md).

## Base de datos

Tablas: `runs` (una fila por ejecución con métricas), `items` (registro por clave natural, con `data` JSON, hash de contenido y fechas `first_seen/last_seen/last_changed`), `pages` (cada URL descargada) y `errors` (fallos de descarga, parseo o validación).

Cambiar a Postgres/Supabase: `DB_URL=postgresql+psycopg://...` en `.env` (instala `psycopg[binary]`).

## Sitios con JavaScript (F3)

`fetch.mode: browser` usa Playwright. Instalación: `pip install -e .[browser]` y `playwright install chromium`.

## Tests

```bash
pytest
```

Los tests levantan un servidor HTTP local con fixtures en `tests/fixtures/site`, así que no necesitan internet.

## Estructura

```
scraper/
  cli.py          # comandos Typer
  config.py       # modelos Pydantic del YAML
  engine.py       # orquestador listado -> detalle -> pipeline -> storage
  fetch/          # http.py (httpx, rate-limit, reintentos), robots.py, browser.py (Playwright)
  parse/          # selectors.py (CSS + sufijos), pagination.py
  pipeline/       # clean.py (tipos), extract.py, dedupe.py (clave natural + hash)
  storage/        # models.py (SQLAlchemy), repo.py (upsert, runs)
  export/         # csv / xlsx / json
sites/            # un YAML por sitio
data/             # BBDD y exports (ignorado por git)
tests/
docs/
```
