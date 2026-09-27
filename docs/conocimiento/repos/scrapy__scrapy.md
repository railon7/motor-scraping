# scrapy/scrapy
> Python · BSD-3-Clause · ⭐ ~64.5k · Último push 2026-09-25 · https://github.com/scrapy/scrapy

## Qué es
El framework de crawling de referencia en Python. Motor asíncrono (Twisted, con puente a asyncio) con scheduler, downloader, cadenas de middlewares, pipelines de items y un sistema de "settings" que activa o desactiva cada pieza. Casi todo lo que nos falta (caché, reanudación, throttling adaptativo, contratos) está resuelto aquí como componente enchufable.

## Arquitectura en breve
- `scrapy/core/engine.py` coordina: pide peticiones al `scheduler` (`scrapy/core/scheduler.py`), las pasa por `downloadermiddlewares/*` al downloader y devuelve las respuestas al spider pasando por `spidermiddlewares/*`.
- Los items salen del spider hacia `ItemPipelineManager` (`scrapy/pipelines/__init__.py`), que ejecuta en orden los pipelines configurados en `ITEM_PIPELINES`.
- Las extensiones (`scrapy/extensions/*`) se cuelgan de señales (`spider_opened`, `response_downloaded`, `item_scraped`, `spider_closed`...).
- Todo se configura en `scrapy/settings/default_settings.py`; cada componente se instancia con `from_crawler` y lanza `NotConfigured` para autodesactivarse.

## Técnicas que nos interesan

### 1. Fingerprint canónico de petición
- **Qué hace**: identifica una petición por un hash estable, de forma que `?a=1&b=2` y `?b=2&a=1` cuenten como la misma.
- **Cómo**: `scrapy/utils/request.py`, función `fingerprint()` y clase `RequestFingerprinter`. Construye un dict con método, URL canonicalizada (`w3lib.url.canonicalize_url`: ordena parámetros de la query, normaliza el escape y quita el fragmento `#`), cuerpo en hex y, solo si se pide, una lista de cabeceras. Lo serializa a JSON con claves ordenadas y le aplica SHA1. Guarda el resultado en una caché `WeakKeyDictionary` por petición. Las cabeceras se excluyen por defecto porque llevan cookies de sesión. Con la meta `verbatim_url` se puede saltar la canonicalización.
- **Por qué importa**: es la pieza común que usan el dupefilter, la caché HTTP y deltafetch. Nosotros deduplicamos solo por URL literal: el `seen_urls` por listado y el `_details` por ejecución, en `engine.py`.

### 2. Dupefilter persistente
- **Qué hace**: descarta peticiones ya vistas dentro de un "job" y, si hay `JOBDIR`, también entre arranques.
- **Cómo**: `scrapy/dupefilters.py`, `RFPDupeFilter`. Mantiene un `set` de fingerprints en memoria. Con `JOBDIR` va añadiendo cada fingerprint a un fichero binario `requests.seen` (2 bytes de longitud más el hash) y lo relee al abrir. Si el fichero quedó truncado por un apagado sucio, ignora el último registro incompleto (`_read_fingerprints`). Suma a la estadística `dupefilter/filtered`.
- **Por qué importa**: es un diario de solo añadir que aguanta los cortes. Es justo lo que necesitamos para reanudar.

### 3. Caché HTTP con políticas intercambiables
- **Qué hace**: guarda las respuestas y las sirve sin volver a pedirlas, o las revalida.
- **Cómo**:
  - El middleware `scrapy/downloadermiddlewares/httpcache.py` (`HttpCacheMiddleware`):
    - En `process_request` busca en el almacenamiento. Si la respuesta está fresca la devuelve marcada con el flag `cached`. Si no lo está, la guarda en `meta["cached_response"]`.
    - En `process_response` decide revalidar (304 → refresca las cabeceras del cacheado y lo devuelve), invalidar o guardar.
    - En `process_exception` sirve la copia cacheada si la red falla (`httpcache/errorrecovery`).
    - Con `HTTPCACHE_IGNORE_MISSING` descarta lo que no esté en caché, es decir, un modo 100 % offline.
    - Registra estadísticas `httpcache/hit|miss|store|revalidate|invalidate|uncacheable`.
  - Las políticas están en `scrapy/extensions/httpcache.py`:
    - `DummyPolicy` guarda todo y todo es siempre fresco. Sirve para el desarrollo y para repetir la ejecución offline.
    - `RFC2616Policy` respeta `Cache-Control` (`no-store`, `no-cache`, `max-age`, `max-stale`, `must-revalidate`) y `Expires`. Usa la heurística del 10 % de `Last-Modified` y añade las cabeceras `If-Modified-Since`/`If-None-Match` a la petición cuando la copia está caducada (`_set_conditional_validators`).
  - Los almacenamientos: `FilesystemCacheStorage` (una carpeta por fingerprint repartida en `key[0:2]/key`, con ficheros meta, cabeceras y cuerpo y gzip opcional) y `DbmCacheStorage`. Ambos caducan por `HTTPCACHE_EXPIRATION_SECS`.
- **Por qué importa**: permite iterar los selectores (dry-run) sin volver a golpear el sitio, que es más cortés y más rápido. Además, la revalidación condicional 304 ahorra ancho de banda en las ejecuciones periódicas, como el BOE diario.

### 4. JOBDIR: pausar y reanudar
- **Qué hace**: con `-s JOBDIR=carpeta`, un Ctrl+C limpio deja en disco la cola pendiente, los fingerprints vistos y el estado del spider. Al relanzar con la misma carpeta, el trabajo continúa.
- **Cómo**:
  - `scrapy/core/scheduler.py`: `Scheduler._dq()` crea colas de prioridad en disco en `JOBDIR/requests.queue/`. En `close()` escribe `active.json` con el estado de prioridades y en `open()` lo lee.
  - Las peticiones se serializan a dict (`request_from_dict` en `utils/request.py` resuelve el callback por nombre de método).
  - `scrapy/extensions/spiderstate.py` persiste un dict `spider.state` en `spider.state`, con pickle.
  - `scrapy/utils/conf.py::_job_dir` crea la carpeta.
- **Por qué importa**: es el hueco "no se puede reanudar". Ojo: solo funciona bien con una parada limpia. La cola en disco no se sincroniza en cada petición.

### 5. AutoThrottle
- **Qué hace**: ajusta el retardo por "slot" (dominio) según la latencia observada.
- **Cómo**: `scrapy/extensions/throttle.py`, `AutoThrottle._adjust_delay`. Calcula el retardo objetivo como latencia / `AUTOTHROTTLE_TARGET_CONCURRENCY` y el nuevo retardo como la media entre el anterior y el objetivo. Si el objetivo es mayor, toma el objetivo, así que sube rápido y baja despacio. Lo acota entre `DOWNLOAD_DELAY` (mínimo) y `AUTOTHROTTLE_MAX_DELAY`. **No reduce** el retardo con respuestas distintas de 200, porque las páginas de error son rápidas y provocarían realimentación. Parte de `AUTOTHROTTLE_START_DELAY` (5 s por defecto).
- **Por qué importa**: si el servidor se ralentiza, nuestro `DomainLimiter` (`fetch/http.py`) sigue con un `delay_seconds` fijo. AutoThrottle es la forma cortés de adaptarse, porque solo aumenta la espera por encima del mínimo configurado.

### 6. Item pipelines con DropItem
- **Qué hace**: una cadena ordenada de procesadores por item, con `open_spider`/`close_spider` y la posibilidad de descartar un item con motivo.
- **Cómo**: `scrapy/pipelines/__init__.py` (`ItemPipelineManager._process_chain`) y `scrapy/exceptions.py::DropItem`, que acepta `log_level`. `scrapy/extensions/corestats.py` cuenta `item_dropped_reasons_count/<Motivo>`.
- **Por qué importa**: nuestro pipeline está cableado en `Engine._process_item`. Hacerlo declarativo por YAML permitiría pasos como filtrar por fecha, normalizar o enriquecer sin tocar el motor.

### 7. Stats y cierre por umbrales
- **Qué hace**: un diccionario de contadores (`inc_value`, `max_value`, `min_value`) que se vuelca al cerrar, más reglas de parada automática.
- **Cómo**: `scrapy/statscollectors.py` (`StatsCollector`, `MemoryStatsCollector._persist_stats`) y `scrapy/extensions/corestats.py` (start/finish time, `finish_reason`, `elapsed_time_seconds`, `item_scraped_count`). `scrapy/extensions/closespider.py` cierra por `CLOSESPIDER_ERRORCOUNT`, `ITEMCOUNT`, `PAGECOUNT`, `TIMEOUT` y `TIMEOUT_NO_ITEM` (sin items en N segundos).
- **Por qué importa**: nuestra tabla `runs` tiene columnas fijas. Un JSON libre de stats en `runs` y un "cortacircuitos" por errores nos darían observabilidad y protección frente a un selector roto o un bloqueo.

### 8. Contracts de spiders
- **Qué hace**: permite escribir en el docstring de un callback anotaciones como `@url`, `@returns items 1 10` o `@scrapes campo1 campo2`, y `scrapy check` las ejecuta contra la web real.
- **Cómo**: `scrapy/contracts/__init__.py` (`ContractsManager` parsea el docstring y envuelve el callback con pre/post hooks) y `scrapy/contracts/default.py` (`UrlContract`, `ReturnsContract`, `ScrapesContract`, `MetadataContract`...).
- **Por qué importa**: es una prueba de humo en vivo que detecta selectores rotos. Nuestra versión natural sería declarativa en el YAML.

## Qué aplicaríamos en nuestro motor
| # | Propuesta | Módulo afectado | Cambio YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | **Caché HTTP** en disco o SQLite indexada por fingerprint, con modo `dummy` (desarrollo: todo fresco) y `rfc` (condicional ETag/Last-Modified → 304). `dry-run` usa la caché por defecto; `--offline` equivale a IGNORE_MISSING | nuevo `fetch/cache.py` (ya previsto en PLAN), `fetch/http.py` (`FetchResult.from_cache` ya existe), `cli.py` | `cache: {enabled: true, policy: dummy\|rfc, expire_hours: 24}` | M | 1 |
| 2 | **Fingerprint canónico** (método + URL canonicalizada + cuerpo) como utilidad común para la caché, la deduplicación, la reanudación y el modo incremental | nuevo `fetch/fingerprint.py`; `engine.py` (`seen_urls`, `_details`) | — | S | 1 |
| 3 | **Reanudar ejecución**: registrar en `pages` el fingerprint y el estado (pendiente/hecha). `scraper run --resume` reabre el último run `interrupted` y salta lo ya hecho. Aprovecha que ya tenemos SQLite, así que no hacen falta ficheros pickle | `storage/models.py` (columna `fingerprint`, índice), `storage/repo.py`, `engine.py`, `cli.py` | — | M | 1 |
| 4 | **Stats JSON + cortacircuitos**: añadir `runs.stats` (JSON) con contadores libres (caché hit/miss, 4xx/5xx, dropped por motivo) y `limits: {max_errors, max_error_ratio, timeout_no_item}` que aborte el run con `finish_reason` | `storage/models.py`, `engine.py` (`RunReport`) | `limits:` | S | 2 |
| 5 | **AutoThrottle cortés**: `DomainLimiter` adaptativo que usa `delay_seconds` como mínimo, sube con la latencia, no baja con respuestas distintas de 2xx y respeta `max_delay` | `fetch/http.py` | `politeness.autothrottle: {enabled, target_concurrency, max_delay}` | S | 2 |
| 6 | **Checks declarativos** (equivalente a contracts): `scraper check sites/x.yaml` pide `check.url`, verifica un número mínimo/máximo de items y los campos obligatorios no vacíos | `cli.py`, reutiliza `Engine(dry_run)` | `check: {url, min_items, max_items, fields: [..]}` | S | 2 |
| 7 | **Pipeline declarativo** de pasos con motivo de descarte (`drop` con razón contabilizada) | `pipeline/`, `engine.py` | `pipeline: [filter_date, ...]` | M | 3 |

## Qué NO copiaríamos y por qué
- **Twisted y el modelo de settings globales/middlewares por prioridad numérica**: para un motor config-driven pequeño es demasiado. Con httpx async y funciones nos basta.
- **Serializar con pickle** (caché, `spider.state`, `response_data`): no es portable ni seguro al cargar datos. Preferimos SQLite/JSON, coherente con nuestra BBDD.
- **La cola en disco del scheduler** (`requests.queue`): nuestra reanudación puede derivarse de `pages`, `items` y la paginación determinista sin duplicar el estado en ficheros.
- **Middlewares de proxy, rotación de UA o similares**: fuera de nuestros principios (no hay evasión).
- **La licencia BSD-3** permite reutilizar, pero no copiamos código: solo los patrones, descritos arriba.
