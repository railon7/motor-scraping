# Changelog

## 0.2.0 — 2026-09-27

Mejoras aplicadas a partir del análisis de 24 proyectos open source de scraping ([docs/conocimiento/](docs/conocimiento/README.md)).

- **robots.txt conforme a RFC 9309**: parser propio con comodines `*` y `$` (el de la librería estándar los ignoraba), regla más específica, grupo por user-agent, `Crawl-delay` respetado, y robots.txt con error 5xx o inaccesible = no rastrear.
- **Caché HTTP** en `data/cache/<sitio>/` con caducidad (`cache.ttl_hours`), revalidación ETag/Last-Modified (304) y `--offline`. `dry-run` la usa por defecto.
- **Modo incremental** (`detail.refresh_days`): no se vuelve a descargar el detalle de un item si se descargó hace poco y los datos del listado no cambiaron.
- **Items desaparecidos** (`track_removed`): columna `gone_at`, solo tras ejecuciones completas y sanas; se reactivan si reaparecen. `export --solo-activos`.
- **Avisos de selectores rotos** (`expect.min_items`, `expect.fill_rate`): la ejecución queda `degraded` con el motivo en `status`.
- **Cortacircuitos** (`politeness.max_consecutive_errors`, 20 por defecto): la ejecución queda `aborted`. Un 429 frena todo el dominio. Códigos reintentables configurables (`retry_status`, añade 408).
- **Datos estructurados**: selectores `jsonld:Tipo.ruta` y `meta:nombre`; `selector` admite una lista de alternativas.
- **Fechas relativas**: "hoy", "ayer", "anteayer", "hace N días/horas/semanas/meses", "N days ago".
- **Enlaces** resueltos contra `<base href>`.
- **Modo navegador**: ahora respeta robots.txt y `Crawl-delay`, usa el User-Agent configurado y la caché.
- **Configuración estricta**: claves desconocidas rechazadas con sugerencia ("¿quisiste decir 'selector'?"); `scraper schema` genera el JSON Schema para VS Code.
- **Corrección**: si falla la descarga de un detalle, el item ya no se guarda con datos parciales encima de los completos.
- **Corrección**: el recuento de campos vacíos incluye campos que no llegaron a extraerse.
- **Corrección**: todas las fechas de la BBDD en hora local (antes mezclaba UTC del servidor SQLite con hora local).
- Migración automática de columnas nuevas en bases existentes.
- Tests: de 21 a 47.

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
