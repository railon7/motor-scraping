# apify/crawlee-python
> Python · Apache-2.0 · ⭐ 9.552 · Último push 2026-09-26 · https://github.com/apify/crawlee-python

## Qué es (2-3 líneas)
Framework de crawling y scraping de Apify para Python (asyncio). Ofrece una familia de crawlers
(`BasicCrawler`, `HttpCrawler`, `BeautifulSoupCrawler`, `ParselCrawler`, `PlaywrightCrawler`,
`AdaptivePlaywrightCrawler`) que comparten la misma cola de peticiones, almacenamiento, estadísticas y
política de reintentos. Es la referencia más completa y más cercana a nuestro stack (Python, httpx, Playwright, SQLAlchemy).

## Arquitectura en breve
- **Núcleo**: `src/crawlee/crawlers/_basic/_basic_crawler.py` (`BasicCrawler`, ~1.800 líneas). Saca peticiones de un
  `RequestManager`, ejecuta un *pipeline de contexto* y llama al *handler* del usuario (enrutado por `label` con
  `router.py`). Gestiona reintentos, errores, estadísticas, robots.txt y parada.
- **Pipeline de contexto**: `crawlers/_basic/_context_pipeline.py`. Cadena de *middlewares* (generadores async con
  fase de ida y de limpieza) que van enriqueciendo el contexto: timeout → hooks pre-navegación → petición →
  hooks post-navegación → comprobación de estado HTTP → parseo → detección de bloqueo.
- **HTTP vs navegador con la misma interfaz**: `crawlers/_abstract_http/_abstract_http_crawler.py` compone
  `_make_http_request → _handle_status_code_response → _parse_http_response`; `crawlers/_playwright/_playwright_crawler.py`
  compone `_open_page → _navigate → _handle_status_code_response → ...`. Ambos heredan de `BasicCrawler`, así que
  reintentos, cola, robots y estadísticas son idénticos. El cliente HTTP es enchufable (`http_clients/_base.py`,
  `_httpx.py`, `_impit.py`, `_curl_impersonate.py`).
- **Almacenamiento**: tres tipos (`storages/_request_queue.py`, `_dataset.py`, `_key_value_store.py`) con clientes
  intercambiables en `storage_clients/` (`_memory`, `_file_system`, `_sql`, `_redis`).
- **Concurrencia**: `_autoscaling/autoscaled_pool.py` + `snapshotter.py` + `system_status.py`.
- **Estadísticas**: `statistics/_statistics.py`, `_models.py`, `_error_tracker.py`, `_error_snapshotter.py`.

## Técnicas que nos interesan

### 1. Cola de peticiones persistente y reanudable (RequestQueue)
- **Qué hace**: cada URL a visitar es un registro persistente con estado (pendiente / en curso / gestionada). Si el
  proceso muere, al reabrir la cola se retoman las pendientes y las "en curso" caducadas.
- **Cómo**: `storage_clients/_sql/_db_models.py` define `RequestDb` (tabla `request_queue_records`) con
  `request_id` (hash del `unique_key`), `data` (la petición serializada en JSON), `sequence_number`, `is_handled`,
  `time_blocked_until` y `client_key`, más índice parcial `idx_fetch_available` sobre `is_handled = false`.
  `RequestQueueStateDb` guarda dos contadores: uno positivo para peticiones normales y otro negativo para las
  prioritarias ("forefront"), de modo que un único `ORDER BY sequence_number` da el orden correcto.
  En `storage_clients/_sql/_request_queue_client.py`, `fetch_next_request()` toma un lote (máx. 10) de no
  gestionadas cuyo `time_blocked_until` sea nulo o pasado, y las "bloquea" 300 s (`_BLOCK_REQUEST_TIME`) con
  `SELECT ... FOR UPDATE SKIP LOCKED` en Postgres o con un UPDATE condicional en SQLite. `mark_request_as_handled()`
  pone `is_handled=True`; `reclaim_request()` la devuelve a la cola (al principio o al final) para reintentarla.
  `add_batch_of_requests()` deduplica por `unique_key` y devuelve si ya estaba gestionada.
  La variante de ficheros (`_file_system/_request_queue_client.py`) persiste un `RequestQueueState` con los conjuntos
  `in_progress_requests` y `handled_requests`.
- **Por qué importa**: es exactamente nuestro hueco "no se puede reanudar una ejecución cortada". El bloqueo con
  caducidad (lease) hace que una petición "en curso" cuando se cortó la luz vuelva sola a la cola sin marcas manuales.

### 2. Clave única normalizada de petición (`unique_key`)
- **Qué hace**: dos peticiones con la misma `unique_key` son la misma; por defecto se calcula normalizando la URL
  (minúsculas en esquema/host, sin fragmento, parámetros ordenados), opcionalmente incluyendo método y cuerpo.
- **Cómo**: `_request.py` (`Request.unique_key`, `use_extended_unique_key`, `keep_url_fragment`) y
  `_utils/requests.py::compute_unique_key`.
- **Por qué importa**: nuestro `Engine._details` deduplica solo en memoria y por URL literal; `?a=1&b=2` y `?b=2&a=1`
  cuentan como distintas.

### 3. Política de reintentos con clasificación de errores
- **Qué hace**: distingue errores que no merece la pena reintentar de los transitorios, y permite límites por petición.
- **Cómo**: `BasicCrawler._should_retry_request()` (en `_basic_crawler.py`): no reintenta si `request.no_retry`, ni si
  el error es `HttpClientStatusCodeError` (4xx); los `SessionError` tienen su propio contador; si no, compara
  `retry_count` con `request.max_retries` o el global `max_request_retries`. `_raise_for_error_status_code()` convierte
  el código HTTP en excepción, con dos listas configurables: `additional_http_error_status_codes` (tratar como error
  algo que normalmente no lo es) e `ignore_http_error_status_codes` (aceptar p. ej. un 404 como válido). Al agotar
  reintentos, la petición pasa a `RequestState.ERROR`, se marca como gestionada y se llama a `failed_request_handler`.
  Jerarquía de excepciones en `errors.py`.
- **Por qué importa**: nuestro `HttpFetcher.fetch` reintenta solo por lista fija `RETRY_STATUS` y el motor trata todo
  error igual; no hay 4xx "permanente" registrado como tal ni lista configurable por sitio.

### 4. Rate limiting por dominio con backoff ante 429 y Crawl-delay
- **Qué hace**: por dominio, respeta `Crawl-delay` de robots.txt y, al recibir 429, aplica backoff exponencial o el
  `Retry-After`, sin bloquear el resto de dominios.
- **Cómo**: `request_loaders/_throttling_request_manager.py` (`ThrottlingRequestManager`): envuelve la cola, mantiene
  un estado por dominio (`backoff_until`, `consecutive_429_count`, `crawl_delay_until`) y en `record_domain_delay()`
  solo el **primer 429 de una ráfaga** incrementa el exponente (las peticiones en vuelo que también devuelven 429 no
  cuentan doble); si el dominio ha estado tranquilo una ventana extra, el contador se reinicia. Techo `max_delay`
  (60 s por defecto). `fetch_next_request()` elige el dominio que lleva más tiempo esperando y salta los que están en
  enfriamiento, devolviendo `None` en vez de dormir para liberar el hueco de concurrencia. `set_crawl_delay()` se
  alimenta desde `_is_allowed_based_on_robots_txt_file()` en `_basic_crawler.py`.
- **Por qué importa**: nuestro `DomainLimiter` usa un delay fijo y el `Retry-After` solo afecta al reintento de esa URL,
  no frena al resto de peticiones al mismo dominio; tampoco leemos `Crawl-delay`.

### 5. robots.txt aplicado al encolar, no en el fetcher
- **Qué hace**: filtra URLs no permitidas antes de meterlas en la cola, sea cual sea el modo (HTTP o navegador).
- **Cómo**: `BasicCrawler.add_requests()` llama a `_is_allowed_based_on_robots_txt_file()` y manda las rechazadas a
  `_handle_skipped_request(..., 'robots_txt')` (callback `on_skipped_request`). `PlaywrightCrawler` sobrescribe
  `_find_txt_file_for_url` para descargar robots con su propio cliente.
- **Por qué importa**: en nuestro motor robots vive en `fetch/http.py`, por eso `BrowserFetcher` no lo respeta
  (hueco conocido). Subirlo al motor lo arregla para ambos modos.

### 6. Pipeline de navegación común con hooks pre/post
- **Qué hace**: mismo ciclo de vida para HTTP y navegador; los hooks permiten, por ejemplo, fijar cabeceras o esperar
  un selector sin tocar el núcleo.
- **Cómo**: `ContextPipeline.compose()` en `_context_pipeline.py`; hooks registrados con `pre_navigation_hook()` /
  `post_navigation_hook()` en `_abstract_http_crawler.py` y `_playwright_crawler.py`. `_handle_blocked_request_by_content`
  consulta al parser (`is_blocked`) tras parsear.
- **Por qué importa**: hoy `BrowserFetcher` y `HttpFetcher` duplican lógica y divergen (el primero no tiene reintentos
  ni robots). Un "fetcher base" con los pasos comunes evita la divergencia.

### 7. Autoscaling de concurrencia
- **Qué hace**: sube o baja la concurrencia deseada según carga (CPU, memoria, bucle de eventos y **errores 429 del
  cliente**), con tope de tareas por minuto.
- **Cómo**: `_autoscaling/autoscaled_pool.py::_autoscale()` escala con pasos proporcionales (`_SCALE_UP_STEP_RATIO`,
  `_SCALE_DOWN_STEP_RATIO`) entre `min_concurrency` y `max_concurrency`; `snapshotter.py::_snapshot_client()` cuenta
  errores de rate-limit como señal de sobrecarga; `max_tasks_per_minute` limita el ritmo global.
- **Por qué importa**: para nosotros la parte útil es la señal "429 → bajar concurrencia" y el tope por minuto; el
  escalado por CPU/memoria no aplica a nuestro volumen.

### 8. Estadísticas persistentes y agrupación de errores
- **Qué hace**: métricas de ejecución (terminadas, fallidas, reintentos, duración mín/máx, peticiones/minuto,
  histograma de reintentos, códigos de estado) que sobreviven a reinicios; errores agrupados por tipo/mensaje.
- **Cómo**: `statistics/_models.py::StatisticsState` (campos `requests_retries`, `request_retry_histogram`,
  `requests_with_status_code`, `errors`, `retry_errors`); persistencia vía `RecoverableState` en un KeyValueStore
  (`_statistics.py`). `_error_tracker.py` agrupa por fichero/línea, clase y mensaje "similar" (sustituye partes
  variables por comodines). `_error_snapshotter.py` guarda el HTML (y captura en navegador) **solo la primera vez** que
  aparece cada grupo de error. Mensaje de estado periódico (`status_message_logging_interval`).
- **Por qué importa**: la instantánea de HTML del primer fallo es la mejor herramienta para diagnosticar selectores
  rotos; la agrupación evita tablas `errors` con miles de filas iguales.

### 9. Crawler adaptativo HTTP/navegador
- **Qué hace**: decide por petición si basta HTTP o hace falta renderizar; aprende con el tiempo.
- **Cómo**: `crawlers/_adaptive_playwright/_adaptive_playwright_crawler.py` ejecuta a veces ambos modos y compara
  resultados (`_result_comparator.py`); `_rendering_type_predictor.py` entrena una regresión logística (sklearn) sobre
  rasgos de la URL.
- **Por qué importa**: idea valiosa, pero para nosotros basta una versión declarativa (ver propuestas).

## Qué aplicaríamos en nuestro motor

| # | Propuesta | Módulos afectados | Cambio YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | **Cola persistente en BD (`queue`)** con `unique_key`, `kind` (list/detail), `status` (pending/in_progress/done/failed), `retries`, `locked_until`, `run_id`, `parent_url`. El motor encola start_urls, páginas siguientes y detalles; un bucle de trabajadores consume. Al reanudar (`scraper run --resume`) se toman `pending` y `in_progress` con lease caducado. | `storage/models.py`, `storage/repo.py`, `engine.py`, `cli.py` | Ninguno (flag CLI) | L | 1 |
| 2 | **Normalizar URL para `unique_key`** (esquema/host en minúsculas, sin fragmento, query ordenada, quitar parámetros de tracking configurables). | nuevo `parse/urls.py`, `engine.py` | `dedupe.ignore_params: [utm_source, ...]` | S | 1 |
| 3 | **Clasificación de errores temporal/permanente** con listas por sitio: 4xx → permanente sin reintento; 408/429/5xx/timeouts → temporal. `errors.kind` pasa a `http_permanent`, `http_temporary`, `network`, `robots`, `parse`, `validate`. | `fetch/http.py`, `engine.py`, `config.py`, `storage/models.py` | `politeness.retry_status: [...]`, `politeness.ignore_status: [404]` | S | 1 |
| 4 | **Backoff por dominio ante 429** (compartido por todas las peticiones del dominio, solo el primer 429 de la ráfaga cuenta, techo configurable) + **leer `Crawl-delay`** de robots y usar `max(delay_seconds, crawl_delay)`. | `fetch/http.py` (`DomainLimiter`), `fetch/robots.py` | `politeness.max_backoff_seconds` | M | 1 |
| 5 | **Robots y reintentos en el motor, no en el fetcher**: la comprobación de robots se hace al encolar y el bucle de reintentos se saca a una capa común, así `BrowserFetcher` hereda ambos. | `engine.py`, `fetch/http.py`, `fetch/browser.py`, nuevo `fetch/base.py` | Ninguno | M | 1 |
| 6 | **Instantánea del HTML en el primer error de cada tipo** (por ejemplo `data/snapshots/<run>/<grupo>.html`) y **agrupación de errores** en `status`. | `engine.py`, `storage/repo.py`, `cli.py` | `debug.save_error_html: true` | S | 2 |
| 7 | **Estadísticas ampliadas en `runs`**: reintentos, 429 recibidos, duración media/máx., histograma de códigos HTTP (JSON). | `storage/models.py`, `engine.py` | Ninguno | S | 2 |
| 8 | **Hooks declarativos pre/post navegación** limitados (cabeceras por petición, `wait_for`, scroll) comunes a ambos modos. | `fetch/base.py`, `config.py` | `fetch.hooks` | M | 3 |
| 9 | **Modo `fetch.mode: auto`** declarativo: intentar HTTP; si `list.item_selector` no devuelve nada en la primera página, repetir con navegador y recordar la decisión para el resto del run. | `engine.py` | `fetch.mode: auto` | M | 3 |

## Qué NO copiaríamos y por qué
- **Rotación de sesiones y proxies para esquivar bloqueos** (`sessions/_session_pool.py`, `retry_on_blocked`,
  `proxy_configuration.py`, `SessionError` por códigos 401/403/429): su objetivo es sortear protecciones anti-bot,
  contrario a nuestro principio de no evasión. Un bloqueo debe acabar en error permanente y revisión humana.
- **`fingerprint_suite/` y clientes `curl_impersonate` / `impit`**: suplantación de huella de navegador/TLS. Fuera de
  nuestro alcance por la misma razón.
- **Autoscaling por CPU/memoria/event loop** (`snapshotter.py`, `system_status.py`): complejo y pensado para miles de
  peticiones por minuto en la nube; para nosotros sobra con concurrencia fija baja y reducción ante 429.
- **Predictor por regresión logística** (sklearn) del crawler adaptativo: dependencia pesada para un beneficio que
  cubre una regla declarativa.
- **Buffers de metadatos multi-cliente** (`RequestQueueMetadataBufferDb`, `had_multiple_clients`): solo tienen sentido
  con varios procesos consumiendo la misma cola; nuestro caso es una ejecución por sitio.
- Licencia Apache-2.0: se puede inspirar el diseño libremente; si algún día se copiara código habría que conservar
  el aviso de licencia y NOTICE. Aquí solo se describen patrones.
