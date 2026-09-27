# Aprendizajes y hoja de ruta

Síntesis de las 24 fichas de [repos/](repos/) (cómo se hizo: [metodologia.md](metodologia.md)). Fecha: 2026-09-27.

## 1. Ideas que se repiten en los proyectos maduros

1. **No volver a pedir lo que ya tienes.** Scrapy (HTTP cache, deltafetch), colly (caché), pyspider (`age`/`itag`), crawl4ai y polite coinciden: caché de respuestas + modo incremental. Es la mejora que más reduce carga sobre el sitio y tiempo de ejecución.
2. **Una ejecución que "funciona" puede estar rota.** changedetection.io, querido-diario (monitores) y los contracts de Scrapy vigilan síntomas: pocos items, campos vacíos, días sin datos. Sin esto, un cambio de maquetación produce Excel vacíos en silencio.
3. **Distinguir "ya no está" de "no lo he podido leer".** changedetection.io y exoskeleton solo marcan algo como desaparecido cuando la ejecución fue completa y sana. Un fallo parcial nunca debe borrar ni pisar datos buenos.
4. **Los datos estructurados son más estables que el CSS.** recipe-scrapers resuelve 281 de sus 640 sitios solo con schema.org (JSON-LD); extruct y trafilatura priorizan JSON-LD/meta y caen a heurísticas o selectores. Muchas webs españolas (tiendas, portales de empleo, noticias) publican JSON-LD.
5. **La configuración es un producto.** MagicBox, ferret y memorious validan la config con errores legibles, publican un esquema y prueban cada config contra HTML guardado. Una errata en el YAML no debe pasar en silencio.
6. **La cortesía es código, no una promesa.** gocrawl, polite y exoskeleton aplican `Crawl-delay`, frenan todo el dominio ante un 429, distinguen errores permanentes de temporales y paran solos ante una racha de errores.
7. **El LLM, para escribir la plantilla, no para cada página.** crawl4ai genera el esquema de selectores con un LLM *una vez* y luego extrae sin LLM (barato, determinista, auditable). Extraer con LLM en cada ejecución queda para páginas sin estructura estable.
8. **Plantilla común + configuración por sitio escala.** querido-diario mantiene ~476 spiders de diarios oficiales con 22 clases base; recipe-scrapers, 640 sitios. Es exactamente la apuesta del motor; su lección es añadir herencia (`extends:`) y tests por sitio.

## 2. Hallazgos que cambian decisiones del PLAN

- **Piloto BOE → no por subastas.** `subastas.boe.es/robots.txt` es `Disallow: /` para todos los robots (verificado 2026-09-27). Además `www.boe.es` prohíbe `xml.php`. Alternativa conforme: la **API de datos abiertos** (`/datosabiertos/api/boe/sumario/AAAAMMDD`, JSON o XML según `Accept`, verificada) para el sumario diario, y `txt.php` (permitido salvo idiomas concretos) para el detalle. Esto requiere soporte de respuestas JSON en el motor (hoja de ruta, prioridad 1). Detalle: [repos/Quantika14__BOE-scraping.md](repos/Quantika14__BOE-scraping.md).
- **`urllib.robotparser` no basta.** No entiende comodines (`*`, `$`), así que no aplicaba reglas como `Disallow: /diario_boe/txt.php?*lang=ca`. Sustituido por un parser propio conforme a RFC 9309.
- **Anti-bot fuera, confirmado.** Gran parte del ecosistema 2026 (CloakBrowser, camofox, botasaurus, rotación de proxies, User-Agent de navegador) va de evadir. Incluso proyectos serios como querido-diario desactivan robots.txt. Lo descartamos explícitamente.

## 3. Aplicado en la versión 0.2.0

| Mejora | De dónde sale | Dónde está |
|---|---|---|
| robots.txt RFC 9309 (comodines, regla más larga, grupo por UA, 5xx = no rastrear) + `Crawl-delay` | polite, gocrawl, verificación BOE | [fetch/robots.py](../../scraper/fetch/robots.py) |
| 429 frena todo el dominio; códigos reintentables configurables (`retry_status`) | crawlee, exoskeleton | [fetch/http.py](../../scraper/fetch/http.py) |
| Caché HTTP en disco con TTL, revalidación ETag/Last-Modified (304) y `--offline`; `dry-run` la usa por defecto | Scrapy, colly, crawl4ai, polite | [fetch/cache.py](../../scraper/fetch/cache.py) |
| Modo navegador con robots, `Crawl-delay`, User-Agent propio y caché | crawlee | [fetch/browser.py](../../scraper/fetch/browser.py) |
| Modo incremental `detail.refresh_days`: no se descarga el detalle si se descargó hace poco y el listado no cambió | deltafetch, pyspider (`itag`) | [engine.py](../../scraper/engine.py) |
| Items desaparecidos (`track_removed`, columna `gone_at`), solo en ejecuciones completas y sanas | changedetection.io, exoskeleton | [engine.py](../../scraper/engine.py), [storage/repo.py](../../scraper/storage/repo.py) |
| `expect` (`min_items`, `fill_rate`) → estado `degraded` con motivo | changedetection.io, querido-diario, contracts de Scrapy | [engine.py](../../scraper/engine.py) |
| Cortacircuitos `max_consecutive_errors` → estado `aborted` | Scrapy (CloseSpider), pyspider | [engine.py](../../scraper/engine.py) |
| Un detalle fallido ya no pisa datos completos con datos parciales | changedetection.io (no confundir fallo con cambio) | [engine.py](../../scraper/engine.py) |
| Selectores `jsonld:Tipo.ruta` y `meta:nombre` | extruct, recipe-scrapers | [parse/structured.py](../../scraper/parse/structured.py) |
| `selector` como lista de alternativas (el primero con valor gana) | trafilatura, GNE (idea) | [pipeline/extract.py](../../scraper/pipeline/extract.py) |
| Fechas relativas ("hoy", "ayer", "hace 3 días", "2 weeks ago") | htmldate (trafilatura) | [pipeline/clean.py](../../scraper/pipeline/clean.py) |
| Enlaces resueltos contra `<base href>` | colly | [parse/selectors.py](../../scraper/parse/selectors.py) |
| Config estricta: claves desconocidas rechazadas con "¿quisiste decir…?" + `scraper schema` (JSON Schema para VS Code) | MagicBox, ferret | [config.py](../../scraper/config.py), [schemas/](../../schemas/) |
| Migración automática de columnas nuevas en bases existentes | — (necesidad propia) | [storage/repo.py](../../scraper/storage/repo.py) |

Resultado medido contra quotes.toscrape.com (20 citas, 2 páginas): primera ejecución 17 descargas; segunda, con `refresh_days`, **2 descargas** y los 20 items intactos.

## 4. Hoja de ruta (no aplicado todavía)

**Prioridad 1**

| Mejora | Por qué | Origen | Esfuerzo |
|---|---|---|---|
| ~~Respuestas JSON (`fetch.format: json`, rutas `json:`)~~ | ✅ Hecho en v0.3.0 (XML pendiente) | Aneiang.Pa, BOE datosabiertos | M |
| ~~Semillas por rango de fechas (`dates`, `--desde/--hasta`)~~ | ✅ Hecho en v0.3.0 | querido-diario, memorious | M |
| ~~Filtros declarativos antes del detalle~~ | ✅ Hecho en v0.3.0 (`list.include/exclude`) | JobFunnel, Aneiang.Pa | S |
| `transform:` encadenado por campo (strip, replace, regex, split, map, `call: modulo:funcion`) | Hoy solo hay `regex` + tipo; los casos reales piden 2–3 pasos | MagicBox, memorious, Aneiang.Pa | M |
| Tests por sitio con HTML guardado + `expected.json` (`scraper test`) | Detectar selectores rotos sin salir a internet; requisito de F4 | recipe-scrapers, MagicBox | S-M |
| Reanudar ejecuciones (`run --resume`) con cola en BD | Ejecuciones largas cortadas no empiezan de cero | crawlee, exoskeleton, Scrapy JOBDIR | L |
| Asistente de selectores con Claude: `scraper suggest-selectors <url> --campos ...` que escribe el YAML y lo valida con dry-run | Acelera el alta de sitios; el LLM no interviene en la extracción diaria | crawl4ai (`generate_schema`) | M |

**Prioridad 2**

| Mejora | Origen | Esfuerzo |
|---|---|---|
| Historial de versiones por item (`item_versions` con diff por campo) y `export --cambios --desde` | changedetection.io | M |
| `ignore_in_hash` para campos que cambian solos (contadores, "actualizado hace…") | changedetection.io | S |
| Notificaciones (Apprise o webhook n8n) en `degraded`/`aborted`/cambios | changedetection.io, querido-diario | S |
| Campos anidados (`type: object/list` con `fields` propios) | webparsy, ferret | M |
| Herencia de YAML (`extends:`) y variables (`vars`, `{env:X}`, `{today}`) | querido-diario, MagicBox | M |
| Filtros declarativos antes del detalle (`skip_if`) | JobFunnel, Aneiang.Pa | S |
| `pagination.strategy` explícita (offset, cursor JSON, "cargar más") y `fetch.actions` en navegador | MagicBox, webparsy, ferret | M |
| Prefijo `xpath:` (requiere lxml/parsel) | Aneiang.Pa, PLAN §7 | S-M |
| Sugerencia de selector nuevo cuando uno se rompe (huella del elemento + similitud) | Scrapling | M |
| Duplicados por similitud de texto (marcar `duplicate_of`, nunca borrar) | JobFunnel | M |

**Prioridad 3:** `auto:main_text` / `auto:date` con trafilatura como extra opcional; tipo `duration`; `scraper inspect <url>`; `fetch.mode: auto`; guardar el HTML del primer fallo de cada tipo; columnas del usuario en el Excel que el motor no sobrescribe.

## 5. Qué no haremos (y por qué)

- **Evasión anti-bot** (stealth, fingerprint, rotación de proxies/UA, pausas "humanas", resolución de captchas): contradice el principio de cortesía y legalidad del PLAN y, en la práctica, el acuerdo tácito con el sitio.
- **Copiar código de proyectos GPL/AGPL** (GeneralNewsExtractor, firecrawl, EasySpider): solo ideas, reimplementadas.
- **Un fichero Python por sitio como norma** (recipe-scrapers, querido-diario): el YAML sigue siendo la norma; Python solo como *hook* excepcional.
- **Arquitectura distribuida / web UI** (pyspider, crawlab): fuera de escala para los proyectos actuales.
