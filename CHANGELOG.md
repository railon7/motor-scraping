# Changelog

## 0.1.1 — 2026-09-27

Revisión del motor (correcciones de fiabilidad y calidad de datos).

- **Fechas**: se reconocen dentro de un texto y con hora (`Publicado el 12/03/2024 10:30`), meses en inglés y abreviados (`12 mar. 2024`, `March 14, 1879`), años de 2 cifras; las fechas imposibles (`31/02`) dan vacío. `datetime` conserva la hora.
- **Números**: `float` usa las mismas reglas que `money` (`1.234,56` → 1234.56; antes daba 1.234).
- **Teléfonos**: se toma el primer número del texto en lugar de concatenar todos los dígitos.
- **Deduplicación**: si todos los campos de `key` vienen vacíos se usa la URL (antes todos esos registros compartían la clave `|` y se pisaban); claves de más de 500 caracteres se acortan con hash.
- **Motor**: cada ficha de detalle se descarga una sola vez por ejecución aunque aparezca en varios items; un listado vacío o un 404 después de la primera página es fin de paginación, no error; una ejecución cortada (Ctrl+C) queda como `interrupted` y no como `ok`.
- **Descarga**: respeta `Retry-After` en 429/503 (máx. 120 s), no espera tras el último reintento y detecta la codificación de `<meta charset>` cuando el servidor no la declara (webs en ISO-8859-1/Windows-1252).
- Tests: de 8 a 21.

## 0.1.0 — 2026-09-26

Primera versión (fase F1 del PLAN.md).

- CLI `scraper` con `run`, `dry-run`, `export`, `status`, `validate`, `init-site`.
- Configuración de sitio en YAML validada con Pydantic (listado, detalle, paginación, tipos).
- Fetcher httpx asíncrono con rate-limit por dominio, reintentos con backoff y `robots.txt`.
- Parser CSS con sufijos `::text`, `::attr()`, `::html`; URLs relativas resueltas.
- Normalizadores `str, int, float, money, date, datetime, phone, email, url, list` (formatos españoles).
- Storage SQLAlchemy (SQLite por defecto, Postgres por `DB_URL`) con upsert por clave natural + hash.
- Exportación CSV (separador `;`, UTF-8 BOM), XLSX y JSON.
- Fetcher Playwright preparado (`fetch.mode: browser`, extra `[browser]`), pendiente de validar en F3.
- Tests con servidor local de fixtures.
