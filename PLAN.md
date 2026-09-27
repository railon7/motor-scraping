# Motor de Web Scraping — Plan de proyecto

> Estado: **borrador v0.1** · Fecha: 2026-09-26 · Responsable: Jorge Herrera (Tazuke)
> Decisiones tomadas: Python · SQLite local + export · ejecución manual por CLI · piloto por definir

## 1. Objetivo

Construir un **motor de scraping genérico y clonable** ("plantilla") que, copiado a cualquier proyecto de Tazuke/Nanopyme, permita extraer información de sitios web de forma fiable, guardarla en una base de datos propia del proyecto y exportarla (CSV / Excel / JSON) para su explotación posterior.

El motor **no sabe nada del sitio objetivo**: todo lo específico de cada web vive en un fichero de configuración (`sites/<nombre>.yaml`) y, cuando haga falta, en un pequeño módulo Python de extracción. Así el núcleo se mantiene una sola vez y los proyectos solo añaden configuraciones.

## 2. Principios de diseño

1. **Clonable en minutos**: `git clone` + `pip install` + `scraper run sites/ejemplo.yaml` debe funcionar sin infraestructura externa.
2. **Config-driven**: URLs de arranque, paginación, selectores, campos y reglas de limpieza se declaran en YAML. El código Python es la excepción, no la norma.
3. **Idempotente y reanudable**: repetir una ejecución no duplica datos (clave natural + hash del registro); si se corta, retoma donde estaba.
4. **Cortés y legal por defecto**: respeta `robots.txt`, límite de peticiones por dominio, `User-Agent` identificable, reintentos con backoff. Sin evasión agresiva de anti-bot. Se documenta por proyecto la base legal (datos públicos, no personales o con base RGPD).
5. **Observable**: logs estructurados, tabla `runs` con métricas de cada ejecución (páginas, registros nuevos/actualizados, errores) y `dry-run` para probar selectores sin escribir.
6. **Almacenamiento intercambiable**: SQLite por defecto; PostgreSQL/Supabase activable por variable de entorno sin tocar código (misma capa ORM).

## 3. Arquitectura

```
URLs semilla ─► Scheduler/cola ─► Fetcher ─► Parser ─► Validación ─► Pipeline ─► Storage ─► Exporters
                    │              (httpx /    (YAML +     (Pydantic)  (dedupe,    (SQLite /   (CSV, XLSX,
                    │              Playwright)  selectores)              limpieza,   Postgres)   JSON, Parquet)
                    └── descubre nuevas URLs (paginación, enlaces a detalle) ◄──── normalización)
```

| Capa | Responsabilidad | Tecnología propuesta |
|---|---|---|
| CLI | `run`, `dry-run`, `export`, `init-site`, `status` | Typer + Rich |
| Config | Carga y valida `sites/*.yaml` | PyYAML + Pydantic |
| Fetcher | HTTP con caché, reintentos, rate-limit por dominio; modo navegador para JS | httpx (async) · Playwright (opcional, activable por site) |
| Parser | Extracción por selectores CSS/XPath, paginación, "list → detail" | selectolax (rápido) / parsel (XPath) |
| Modelo | Esquema del registro, tipos, campos obligatorios | Pydantic v2 |
| Pipeline | Limpieza (trim, fechas, precios, teléfonos), normalización, dedupe, hash | Funciones registrables; reutiliza ideas del *Limpiador de Datos* |
| Storage | Tablas `items`, `runs`, `pages`, `errors`; upsert por clave natural | SQLAlchemy 2 / SQLModel · SQLite (WAL) · Postgres opcional |
| Exporters | Volcado a fichero o a destino externo | pandas / openpyxl · webhook opcional (n8n) |

**Modelo de datos mínimo**

- `runs`: id, site, inicio, fin, estado, páginas, nuevos, actualizados, errores.
- `items`: id, site, clave_natural, hash, datos (JSON), url_origen, primera_vez, ultima_vez, run_id. Vistas/tablas tipadas por proyecto se generan a partir del esquema YAML.
- `pages`: url, estado HTTP, fecha, run_id (permite reanudar y auditar).
- `errors`: url, tipo, mensaje, traza, run_id.

## 4. Anatomía de una configuración de sitio (ejemplo)

```yaml
name: ejemplo-listado
base_url: https://www.ejemplo.es
politeness:
  delay_seconds: 2
  max_concurrency: 2
  respect_robots: true
fetch:
  mode: http          # http | browser
start_urls:
  - /listado?page=1
pagination:
  next_selector: "a.siguiente::attr(href)"
  max_pages: 50
list:
  item_selector: "div.card"
  detail_url: "a.titulo::attr(href)"
detail:
  fields:
    titulo:   { selector: "h1", type: str, required: true }
    precio:   { selector: ".precio", type: money }
    fecha:    { selector: "time::attr(datetime)", type: date }
    telefono: { selector: ".tel", type: phone }
key: [titulo, fecha]        # clave natural para dedupe/upsert
export:
  default: xlsx
```

## 5. Estructura del repositorio plantilla

```
motor-scraping/
├── README.md                 # cómo clonar y arrancar en 5 minutos
├── PLAN.md                   # este documento
├── pyproject.toml            # deps y entrypoint `scraper`
├── .env.example              # DB_URL=sqlite:///data/scraper.db, USER_AGENT, ...
├── scraper/
│   ├── cli.py
│   ├── config.py             # modelos Pydantic del YAML
│   ├── fetch/  (http.py, browser.py, ratelimit.py, cache.py, robots.py)
│   ├── parse/  (selectors.py, pagination.py)
│   ├── pipeline/ (clean.py, normalize.py, dedupe.py)
│   ├── storage/ (models.py, repo.py)
│   └── export/ (csv.py, xlsx.py, json.py, webhook.py)
├── sites/
│   └── ejemplo.yaml
├── data/                     # .db y exports (gitignored)
├── tests/                    # unit + fixtures HTML guardados
└── docs/ (CONVENCIONES.md, LEGAL.md, NUEVO-SITIO.md)
```

## 6. Fases

| Fase | Entregable | Criterio de "hecho" |
|---|---|---|
| **F0 · Diseño** (esta sesión + 1) | PLAN.md cerrado, esquema YAML v1, modelo de datos, decisión de piloto | Jorge valida el plan y elige el sitio piloto |
| **F1 · Núcleo HTTP** | CLI `run`/`dry-run`, fetcher httpx con rate-limit y reintentos, parser por selectores, paginación, storage SQLite con upsert, export CSV/XLSX | Scrapea un sitio estático de prueba de principio a fin sin duplicados al repetir |
| **F2 · Calidad de datos** | Tipos `money/date/phone/email`, normalizadores, validación Pydantic, tabla `errors`, informe de ejecución | Registros erróneos no rompen la ejecución y quedan auditados |
| **F3 · JavaScript** | Modo `browser` con Playwright (activable por site), espera de selectores, scroll infinito básico | Mismo YAML funciona sobre una web renderizada en cliente |
| **F4 · Plantilla clonable** | README de arranque, `init-site` que genera YAML esqueleto, tests con fixtures HTML, `docs/NUEVO-SITIO.md`, `.env` para Postgres | Alguien del equipo clona y añade un sitio nuevo sin tocar el núcleo |
| **F5 · Piloto real** | Configuración del primer caso de uso + BBDD poblada + export entregable | Datos útiles en manos de quien los pidió; lecciones vuelven al núcleo |
| *(F6 · Opcional)* | Ejecución programada en VPS (cron/Docker) y disparo desde n8n vía webhook | Solo si un proyecto lo necesita |

## 7. Decisiones pendientes (a comentar)

- **Piloto**: candidatos → subastas del BOE (paginación + detalle, datos públicos), directorio de empresas para prospección, o catálogo/precios de un proveedor. Elegir uno con valor real para no diseñar en el vacío.
  - ✅ *Decisión 2026-09-27*: piloto = **licitaciones del BOE (sección V-A) vía API de datos abiertos**, implementado en `sites/boe-licitaciones.yaml` (v0.3.0).
  - ⚠️ *Contexto*: `subastas.boe.es` prohíbe todos los robots en su robots.txt y `www.boe.es` prohíbe `xml.php`. Si el piloto es el BOE, hacerlo por la **API de datos abiertos** (`/datosabiertos/api/boe/sumario/AAAAMMDD`, JSON) para el sumario y `txt.php` para el detalle (p. ej. anuncios de la sección V), o pedir autorización a la AEBOE. Requiere soporte de respuestas JSON en el motor. Ver [docs/conocimiento/aprendizajes.md](docs/conocimiento/aprendizajes.md).
- **Selectores**: solo CSS (más simple) o CSS + XPath (más potente). Propuesta: CSS por defecto, XPath permitido con prefijo `xpath:`.
- **Extracción con IA**: ¿incluir un extractor opcional por LLM para páginas sin estructura estable? Propuesta: fuera del alcance de F1–F4; hueco previsto en `parse/` para añadirlo después.
- **Anti-bot**: límite claro → si un sitio bloquea con captchas o exige evasión, se descarta o se busca API oficial. No se integran servicios de proxies rotatorios de inicio.
- **Tipado por proyecto**: guardar `datos` como JSON (flexible) frente a generar tablas tipadas desde el YAML (más cómodo para SQL/Excel). Propuesta: JSON + vista/tabla tipada generada automáticamente.
- **Nombre del repo** y ubicación en GitHub de Tazuke.

## 8. Riesgos

| Riesgo | Mitigación |
|---|---|
| Cambios de maquetación rompen selectores | `dry-run` con diff de campos vacíos; tests con fixtures; alerta si % de campos vacíos supera umbral |
| Bloqueos / rate limiting del sitio | Politeness por defecto, backoff, caché de respuestas, Playwright solo cuando hace falta |
| Datos personales sin base legal | `docs/LEGAL.md` obligatorio por sitio; campos sensibles requieren marcarlos explícitamente |
| Sobre-ingeniería antes del primer caso real | F1 mínima; F5 piloto obliga a aterrizar |
| Dependencia de una sola persona | README + convenciones + tests desde F4 |

## 9. Próximos pasos inmediatos

1. Comentar y ajustar este plan (secciones 7 y 6).
2. Elegir el sitio piloto.
3. Crear el repositorio con la estructura de la sección 5 y arrancar F1.

---
Relacionado: [[Limpiador de Datos/README|Limpiador de Datos]] (reutilizar normalizadores) · [[Tazuke_CRM_SAT/docs/CONVENCIONES|Convenciones CRM]] · [[Tazuke_CRM_SAT/docs/N8N-SUPABASE|n8n + Supabase]]
