# Changelog

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
