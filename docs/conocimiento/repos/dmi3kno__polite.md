# dmi3kno/polite
> R · MIT (+ fichero LICENSE; GitHub lo muestra como NOASSERTION) · ⭐ ~335 · Último push 2026-09-09 · https://github.com/dmi3kno/polite

## Qué es (2-3 líneas)
Paquete de R ("Be nice on the web") que envuelve `httr`/`rvest` para scrapear de forma responsable siguiendo tres principios: **presentarse** (User-Agent), **pedir permiso** (robots.txt) e **ir despacio y no pedir dos veces** (rate-limit + memoización). Pequeño (≈9 ficheros R) y muy claro como referencia de "política de cortesía".

## Arquitectura en breve
- `R/bow.R` — `bow(url, user_agent, delay, times, force)`: crea una "sesión educada" para un host: descarga y parsea robots.txt, calcula el retardo efectivo y fija el límite de ritmo global.
- `R/nod.R` — `nod(bow, path)`: cambia de ruta dentro de la sesión (si cambia de host, hace un nuevo `bow`) y avisa si la nueva ruta no está permitida.
- `R/scrape.R` — `scrape(bow, query, accept, content)`: petición GET con límite de ritmo, reintentos y **memoizada** (`memoise`).
- `R/rip.R` — `rip()`: descarga de ficheros con el mismo límite y sin sobrescribir si ya existe.
- `R/politely.R` — `politely(fun)`: convierte **cualquier** función que reciba una URL en una versión educada (robots + retardo + caché).
- `R/utils.R` — reintentos (`httr::RETRY` con `pause_base = 5`), limitadores (`ratelimitr`: 1 petición cada `delay` s), `is_scrapable`.
- `R/use-manners.R` — plantilla de proyecto con las funciones educadas.

## Técnicas que nos interesan

### 1. bow / scrape / nod: permiso por sesión y por ruta
- **Qué hace**: separa "presentarse al host" (una vez) de "pedir una página" (muchas). `bow` obtiene robots.txt una sola vez por host; `scrape` comprueba la ruta concreta y devuelve `NULL` con aviso si no está permitida; `nod` permite navegar dentro del host reutilizando la sesión.
- **Por qué importa**: nuestro `RobotsCache` (`scraper/fetch/robots.py`) hace lo mismo a nivel de host; bien. Lo que añade polite es **avisar al validar el YAML** ("esta ruta no es scrapeable"), antes de lanzar el run.

### 2. Respeto de `Crawl-delay` (el retardo efectivo es el máximo)
- **Qué hace**: el retardo efectivo es `max(crawl_delay de robots para ese UA, o el de "*", retardo pedido por el usuario)`; en `politely` además con un suelo de 1 s (`fetch_rtxt` en `R/politely.R`, `bow` en `R/bow.R`).
- **Salvaguarda**: si el retardo es < 5 s y el UA es el genérico del paquete, **se niega a ejecutar**; con UA propio solo avisa.
- **Por qué importa**: **nuestro motor no lee `Crawl-delay`**. `RobotFileParser` de la biblioteca estándar ya expone `crawl_delay(ua)` y `request_rate(ua)`, así que es barato. También nos inspira la regla "sin UA propio configurado, retardo mínimo más conservador".

### 3. Memoización: "nunca pidas dos veces"
- **Qué hace**: `scrape` es la versión memoizada de la función real; misma URL + parámetros = respuesta de caché sin tocar la red **ni esperar el retardo** (`politely` solo duerme si no hay acierto de caché). `bow(force = TRUE)` limpia las cachés de robots y de `scrape`. `politely(cache = ...)` permite caché en memoria o en disco.
- **Por qué importa**: nuestro motor solo evita repetir el mismo detalle **dentro** de una ejecución (`Engine._details`). Una caché persistente (con TTL) evitaría repetir entre ejecuciones y al hacer `dry-run` sucesivos mientras se ajustan selectores.

### 4. Negociación de contenido y codificación
- **Qué hace**: `scrape(accept = "json" | "xml" | "csv" | ...)` envía la cabecera `Accept` adecuada; `content = "text/html; charset=UTF-8"` fuerza tipo/codificación si el servidor miente; si falla el parseo devuelve bytes crudos con un aviso explicativo.
- **Por qué importa**: para el piloto BOE necesitamos pedir `Accept: application/json` a la API de datos abiertos; nuestro fetcher ya admite cabeceras por sitio (`fetch.headers`), pero no sabe parsear JSON/XML. La idea de "override de charset" ya la cubrimos parcialmente con `_detect_encoding`.

### 5. `rip`: descargas de ficheros con la misma cortesía
- Descarga binarios (PDF, CSV) con el mismo limitador y sin re-descargar si el fichero existe.
- **Por qué importa**: el BOE publica cada anuncio en PDF; si un proyecto necesita los PDF, que pasen por el mismo fetcher (robots + ritmo) y se deduplicen por nombre/hash.

### 6. `politely()`: cortesía como decorador
- Envuelve cualquier función con URL (p. ej. un lector de CSV remoto) y le añade robots + retardo + caché.
- **Por qué importa**: en Python equivaldría a exponer nuestro `HttpFetcher` como utilidad reutilizable para scripts auxiliares de proyecto, en lugar de que cada script use `requests` directo.

## Qué aplicaríamos en nuestro motor
| # | Propuesta | Módulo afectado | Cambio en YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | **Respetar `Crawl-delay` / `Request-rate`**: retardo efectivo por dominio = `max(politeness.delay_seconds, crawl_delay de robots)`; registrarlo en el log y en `runs`. | `fetch/robots.py` (exponer `crawl_delay(ua)`), `fetch/http.py` (`DomainLimiter` con retardo por host) | — (automático; `respect_robots` ya existe) | S | 1 |
| 2 | **Chequeo de robots en `validate`/`dry-run`**: comprobar start_urls y una muestra de detalles contra robots.txt y avisar antes de ejecutar. | `cli.py`, `fetch/robots.py` | — | S | 1 |
| 3 | **Caché persistente de respuestas con TTL** (memoización entre ejecuciones), desactivable con `--no-cache` y limpiable con `scraper cache clear` (equivalente a `force`). Si hay acierto, no se aplica el retardo. | `fetch/cache.py`, `fetch/http.py`, `cli.py` | `fetch.cache: {ttl_hours: 24}` | M | 1 (compartida con crawl4ai/pyspider) |
| 4 | **Suelo de retardo si no hay UA propio**: si `USER_AGENT` no está configurado en `.env`, forzar `delay_seconds >= 5` y avisar. | `fetch/http.py` | — | S | 2 |
| 5 | **Formato de respuesta**: `fetch.accept: json|xml|html` que fija la cabecera `Accept` y elige parser (ver propuesta de fuentes JSON en el fichero del BOE). | `fetch/http.py`, `parse/` | `fetch: {accept: json}` | M | 1 (para piloto BOE) |
| 6 | **Descarga de adjuntos** (`type: file` en un campo): descarga el enlace a `data/files/<site>/` pasando por el fetcher, sin repetir si ya existe. | `pipeline/`, `fetch/http.py` | `pdf: {selector: "a.pdf::attr(href)", type: file}` | M | 3 |

## Qué NO copiaríamos y por qué
- **Limitador global de proceso** (`ratelimitr` aplicado a la función, no al host): polite limita todas las peticiones por igual; nuestro limitador por dominio es más fino y correcto con varios sitios.
- **Memoización en memoria sin TTL**: sirve en una sesión interactiva de R, no para un motor que se ejecuta periódicamente; nosotros necesitamos caché persistente y con caducidad.
- **Devolver `NULL` silencioso ante 4xx/5xx**: preferimos registrar en `errors` y contarlo en el run.
- **Plantillas de proyecto con `usethis`**: ya tenemos `init-site`.
- Código literal: es R y MIT; solo tomamos los principios.
