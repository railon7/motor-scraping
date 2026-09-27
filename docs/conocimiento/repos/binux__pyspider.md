# binux/pyspider
> Python · Apache-2.0 · ⭐ ~16.800 · Último push 2024-04-30 (**archivado**, sin mantenimiento) · https://github.com/binux/pyspider

## Qué es (2-3 líneas)
Sistema de crawling completo con web UI (editor de scripts, depuración en vivo, panel de proyectos y resultados), de origen chino. Cada "proyecto" es un script Python con callbacks; un scheduler persistente decide qué URL se descarga y cuándo, incluido el recrawl periódico. Útil como referencia de diseño de scheduler; no como dependencia (archivado y con código Python 2/3 antiguo).

## Arquitectura en breve
Componentes separados que se comunican por colas (`pyspider/message_queue/`: Redis, RabbitMQ, Kombu o multiprocessing):
- **scheduler** (`pyspider/scheduler/scheduler.py`): mantiene la tabla de tareas (taskdb) y una cola por proyecto; decide qué es nuevo, qué hay que recrawlear y qué reintentar.
- **fetcher** (`pyspider/fetcher/tornado_fetcher.py`): descarga HTTP (o PhantomJS/Splash/Puppeteer para JS).
- **processor** (`pyspider/processor/processor.py`): ejecuta el callback del script del usuario.
- **result_worker** (`pyspider/result/result_worker.py`): guarda resultados en resultdb.
- **webui** (`pyspider/webui/`): Flask; depuración, estado y exportación.
- Bases de datos intercambiables (`pyspider/database/`: sqlite, mysql, mongodb, postgres vía sqlalchemy, redis, elasticsearch), con tres tablas lógicas: `projectdb`, `taskdb`, `resultdb`.

## Técnicas que nos interesan

### 1. Identidad de tarea y detección de "ya hecho" (`taskid`)
- **Qué hace**: cada petición tiene un `taskid` (por defecto el md5 de la URL, sobrescribible con `get_taskid` en `pyspider/libs/base_handler.py`). Si llega una petición con un `taskid` ya conocido, el scheduler **no la vuelve a descargar** salvo que se cumpla una condición de recrawl.
- **Cómo**: `Scheduler.on_request` → busca en taskdb → `on_new_request` (inserta y encola) o `on_old_request` (evalúa si reiniciar). En `on_old_request` se reinicia solo si: (a) cambió el `itag`, (b) ha pasado `age` desde `lastcrawltime`, o (c) `force_update`. Si no, "ignore newtask".
- **Por qué importa**: hoy nuestro motor vuelve a descargar **todas** las fichas de detalle en cada ejecución aunque ya las tengamos y no hayan cambiado. Esto es la mayor fuente de peticiones evitables.

### 2. `age` e `itag` para recrawl
- **`age`** (segundos): validez de una página ya descargada. Mientras no caduque, se ignora. Se define por petición o por defecto en `crawl_config` / decorador `@config(age=...)`.
- **`itag`**: "etiqueta de versión" arbitraria. Si cambia, se fuerza la redescarga aunque no haya caducado. Uso típico: poner en `itag` algo que se ve en el **listado** (fecha de actualización, precio, nº de pujas) para redescargar el detalle **solo cuando el listado indica cambio**. También se usa para forzar recrawl de todo un proyecto cambiando `itag` en `crawl_config` tras modificar el script.
- **`auto_recrawl`**: si está activo, al terminar la tarea se reprograma sola a `now + age` (`on_task_done`).
- **Por qué importa**: patrón perfecto para listado → detalle: en el listado tenemos datos baratos; el detalle solo se pide si es nuevo, si ha caducado o si su "firma" del listado ha cambiado.

### 3. `@every` (tareas periódicas dentro del proyecto)
- **Qué hace**: decorador que marca un método como periódico (`every(minutes=..., seconds=...)`). La metaclase `BaseHandlerMeta` recopila estos métodos y calcula el **MCD** de sus intervalos (`_min_tick`); el scheduler envía un único disparo cada `min_tick` y `_on_cronjob` ejecuta solo los métodos cuyo intervalo divide el tick.
- **Por qué importa**: combinado con `age`, `@every(minutes=24*60)` sobre `on_start` + `age=10 días` da "revisa el listado a diario, pero solo redescarga detalles cada 10 días o si cambian". En nuestro caso la programación la haría cron/n8n (F6), pero la **semántica de age/itag** es lo que falta.

### 4. Prioridad y cola con tiempo de ejecución
- **Cómo**: `pyspider/scheduler/task_queue.py`: `TaskQueue` con tres estructuras: cola de prioridad (heap por `priority` y orden de llegada), cola temporal (tareas con `exetime` futuro, p. ej. reintentos) y cola "en proceso" (con timeout para devolverlas si el fetcher se cae). Límite de ritmo por proyecto con **token bucket** (`token_bucket.py`, `rate` y `burst`).
- **Por qué importa**: en nuestro motor la prioridad natural sería "primero páginas de listado, después detalles nuevos, al final detalles a refrescar". No necesitamos colas distribuidas, pero sí el orden.

### 5. Reintentos diferidos y pausa automática por fallos
- **Reintentos**: `on_task_failed` reprograma con una escalera de esperas por intento (`DEFAULT_RETRY_DELAY`: 30 s, 1 h, 6 h, 12 h, 24 h; configurable por proyecto con `retry_delay`). Es decir, **reintenta en otra ejecución**, no solo en la misma.
- **Pausa del proyecto** (circuit breaker): si las últimas `FAIL_PAUSE_NUM` (10) tareas fallan, el proyecto se pausa `PAUSE_TIME` (5 min), luego entra en "checking" y solo se reanuda si `UNPAUSE_CHECK_NUM` (3) tareas salen bien (clase del proyecto en `scheduler.py`, propiedad `paused`).
- **Por qué importa**: si un sitio empieza a devolver 5xx o nos bloquea, hoy seguimos martilleando hasta agotar los items. Pausar/abortar es más cortés y ahorra tiempo.

### 6. Peticiones condicionales (ETag / Last-Modified)
- **Cómo**: `tornado_fetcher.py` (~líneas 259-285) reenvía automáticamente `If-None-Match` y `If-Modified-Since` con los valores guardados en la tarea anterior; en `base_handler._run_task` un **304** no ejecuta el callback (nada que procesar).
- **Por qué importa**: complementa `age`: al caducar, se pregunta "¿ha cambiado?" antes de descargar el cuerpo.

### 7. Resultados y proyectos
- `resultdb` (`pyspider/database/sqlite/resultdb.py`): una fila por `taskid` con `result` (JSON) y `updatetime`; guardar de nuevo **sobrescribe** (upsert por URL). Exportación CSV/JSON desde la web UI (`pyspider/libs/result_dump.py`).
- Proyectos con estados (TODO, STOP, CHECKING, DEBUG, RUNNING) y `rate`/`burst` editables en la UI; en DEBUG el script se ejecuta pero no se guarda.
- **Por qué importa**: confirma nuestro diseño (upsert por clave, datos JSON, export) y el valor de un estado "en pruebas" (nuestro `dry-run`).

## Qué aplicaríamos en nuestro motor
| # | Propuesta | Módulo afectado | Cambio en YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | **Recrawl por antigüedad de detalles**: antes de pedir un `detail_url`, consultar en `items`/`pages` cuándo se descargó por última vez; saltarlo si es más reciente que `max_age`. Contar en el informe `details_skipped`. | `engine.py` (`_process_item`), `storage/repo.py` (consulta por clave/URL), `storage/models.py` (guardar `detail_url` y `detail_fetched_at` en `items`) | `detail: {max_age: "7d"}` | M | 1 |
| 2 | **`itag` desde el listado**: permitir declarar qué campos del listado forman una firma; si la firma coincide con la guardada y no ha caducado `max_age`, no se pide el detalle y se reutilizan los datos de detalle anteriores (upsert mezclando). | `engine.py`, `pipeline/dedupe.py` (hash de subconjunto), `storage/repo.py` | `detail: {refetch_if_changed: [precio, estado]}` | M | 1 |
| 3 | **Circuit breaker**: abortar (o pausar N minutos) la ejecución si hay K errores de fetch consecutivos o un porcentaje de 5xx/429 alto; run queda en estado `aborted` con motivo. | `engine.py`, `fetch/http.py` | `politeness: {abort_after_consecutive_errors: 10}` | S | 1 |
| 4 | **Peticiones condicionales**: guardar ETag/Last-Modified por URL y enviarlos; tratar 304 como "sin cambios" (items_unchanged sin reparsear). | `fetch/http.py`, `fetch/cache.py`, `storage/models.py` (`pages` + etag/last_modified) | — (activo por defecto) | S-M | 2 |
| 5 | **Reintentos entre ejecuciones**: los detalles que fallaron quedan marcados en `errors`/`pages`; `scraper run --retry-failed` (o automático al inicio del siguiente run) los vuelve a intentar primero. | `engine.py`, `storage/repo.py`, `cli.py` | — | S | 2 |
| 6 | **Orden de prioridad**: listados → detalles nuevos → detalles caducados; útil con `--limit`. | `engine.py` | — | S | 3 |
| 7 | Programación: documentar en F6 el patrón "listado diario + detalle con max_age" en cron/n8n, sin construir un scheduler propio. | `docs/` | `schedule: "daily"` informativo | S | 3 |

## Qué NO copiaríamos y por qué
- **Arquitectura distribuida con colas (Redis/RabbitMQ) y procesos separados**: excesivo para ejecución manual/cron de proyectos pequeños; nuestro asyncio monoproceso basta.
- **Web UI con editor y ejecución de scripts Python arbitrarios**: riesgo de seguridad y mucho mantenimiento; nuestro enfoque es YAML + CLI (y, si acaso, n8n como panel).
- **Scripts de proyecto en Python como norma**: va contra el principio "config-driven"; nos quedamos con la semántica (age, itag, prioridad), no con la forma.
- **Fetchers PhantomJS/Splash**: obsoletos; si hace falta JS, Playwright (F3).
- **Dependencia del proyecto**: archivado desde 2024, no se debe instalar ni tomar como base.
- Código literal: Apache-2.0 lo permitiría con atribución, pero solo describimos patrones.
