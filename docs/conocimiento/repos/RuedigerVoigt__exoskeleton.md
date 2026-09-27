# RuedigerVoigt/exoskeleton
> Python · Apache-2.0 · ⭐ 22 · Último push 2026-09-26 (último commit de código 2025-11-03) · https://github.com/RuedigerVoigt/exoskeleton

## Qué es (2-3 líneas)
Framework Python para crawls "lentos y educados" de larga duración, pensado para investigación (descargas masivas de
ficheros, código de página, PDFs con Chrome headless). Todo el estado vive en MariaDB: cola, errores, reintentos,
límites por host, versiones de ficheros, etiquetas y "jobs" de paginación reanudables. Poco popular, pero su modelo de
**errores permanentes vs temporales en la base de datos** es justo lo que nos falta.

## Arquitectura en breve
- `exoskeleton/__main__.py`: clase `Exoskeleton`, fachada que conecta los "managers".
- `queue_manager.py`: `QueueManager` (añadir/deduplicar tareas, bucle `process_queue`).
- `actions.py`: `ExoActions` / acciones concretas (`get_the_object`) con la clasificación de códigos HTTP.
- `error_manager.py`: `CrawlingErrorManager` (reintentos con retraso creciente, errores permanentes, límites 429 por host).
- `job_manager.py`: `JobManager` (jobs de paginación reanudables).
- `statistics_manager.py`, `notification_manager.py` (correo al terminar / hitos), `time_manager.py`
  (espera aleatoria, estimación de tiempo restante), `blocklist_manager.py`, `label_manager.py`.
- `Database-Scripts/Generate-Database-Schema-MariaDB.sql`: esquema, vistas y procedimientos almacenados.

## Técnicas que nos interesan

### 1. Cola en base de datos con retraso por tarea
- **Qué hace**: cada tarea de la cola tiene su contador de intentos, su error actual y un "no antes de" (`delayUntil`).
  El siguiente trabajo es la tarea más antigua que no tenga error permanente, cuyo host no esté castigado por 429 y
  cuyo retraso haya vencido.
- **Cómo**: tabla `queue` en el script SQL (`id` UUID, `url`, `urlHash` SHA-256, `fqdnHash`, `addedToQueue`,
  `causesError`, `numTries`, `delayUntil`, índices en `urlHash` y `delayUntil`). Procedimiento
  `next_queue_object_SP`: filtra `causesError` nulo o de tipo no permanente, excluye hosts con `rateLimits.noContactUntil
  > NOW()`, exige `delayUntil` vencido, ordena por `addedToQueue`. `QueueManager.process_queue()` consume en bucle y
  borra la tarea al terminar bien.
- **Por qué importa**: modelo sencillo y relacional (sin locks sofisticados) que cabe perfectamente en SQLite/Postgres
  con SQLAlchemy; el mismo registro sirve para reanudar y para reintentar "otro día".

### 2. Catálogo de errores con bandera "permanente"
- **Qué hace**: una tabla de tipos de error indica cuáles son permanentes; los 4xx (400-407, 410, 414, 451) y 501 son
  permanentes; 408, 429, 500, 502-504, 509, 529, 598, timeouts, fallos de transacción y errores de proceso son
  temporales; "demasiados intentos" (id 3) es permanente.
- **Cómo**: tabla `errorType (id, short, description, permanent)` con los valores precargados en el script SQL;
  constantes `HTTP_PERMANENT_ERRORS` y `HTTP_TEMP_ERRORS` en `actions.py`; vista `v_errors_in_queue`; funciones
  `num_items_with_temporary_errors()` / `num_items_with_permanent_error()`.
- **Por qué importa**: permite responder "¿qué falló de forma definitiva y qué se puede reintentar?" con una consulta,
  y relanzar solo lo temporal.

### 3. Reintentos diferidos con escalera de esperas
- **Qué hace**: ante error temporal, no reintenta en segundos, sino que aplaza la tarea: 15 min, 30 min, 1 h, 3 h,
  6 h; al llegar al máximo (`queue_max_retries`, 0-10, por defecto 3) la marca como permanente.
- **Cómo**: `CrawlingErrorManager.add_crawl_delay()` (incrementa `numTries` con `increment_num_tries_SP`, elige la
  espera de `DELAY_TRIES` y llama a `add_crawl_delay_SP`); `mark_permanent_error()`.
- **Por qué importa**: complementa nuestro reintento inmediato (segundos) con un "reintento largo" entre ejecuciones:
  un servidor caído por mantenimiento no debería costar el dato.

### 4. Enfriamiento por host tras 429
- **Qué hace**: al recibir 429, el host completo queda sin contactar durante un periodo (por defecto 1.860 s ≈ 31 min).
- **Cómo**: `CrawlingErrorManager.add_rate_limit()` → `add_rate_limit_SP` (tabla `rateLimits` con `noContactUntil`);
  `next_queue_object_SP` excluye esos hosts; `forget_specific_rate_limit()` / `forget_all_rate_limits()` para limpiar.
  `actions.py` además sube el tiempo de espera base (`TimeManager.increase_wait()`) ante errores de conexión
  sospechosos de rate limit.
- **Por qué importa**: es la reacción más cortés posible: si el sitio dice "para", paramos con ese host entero, no
  solo con esa URL.

### 5. "Olvidar" errores de forma selectiva
- **Qué hace**: comandos para volver a poner en cola tareas con errores: todos, solo temporales, solo permanentes o
  un código concreto (p. ej. todos los 503).
- **Cómo**: `forget_all_errors()`, `forget_temporary_errors()`, `forget_permanent_errors()`,
  `forget_specific_error(code)` en `error_manager.py` → procedimientos `forget_*_SP`.
- **Por qué importa**: equivale a un `scraper retry --status 503` que no tenemos; muy práctico para operar.

### 6. Jobs de paginación reanudables
- **Qué hace**: un job con nombre guarda la URL de inicio y la **URL actual** de la paginación; al reanudar, continúa
  desde la última página procesada; se marca como terminado al final.
- **Cómo**: tabla `jobs (jobName, created, finished, startUrl, startUrlHash, currentUrl)`; `JobManager.define_new()`,
  `update_current_url()`, `get_current_url()` (error si ya terminó), `mark_as_finished()` en `job_manager.py`.
- **Por qué importa**: es la solución mínima a "retomar donde estaba" para nuestra paginación `next_selector`, que es
  secuencial por naturaleza (no se puede saltar a la página N sin haber visto la N-1).

### 7. Deduplicación por URL + acción y versiones
- **Qué hace**: no encola una URL ya procesada con la misma acción, ni una tarea idéntica ya en cola; permite forzar
  una nueva versión.
- **Cómo**: `QueueManager.add_to_queue()` consulta `fileMaster`/`fileVersions` por `urlHash` y `__get_queue_uuids()`;
  parámetro `force_new_version`.
- **Por qué importa**: base del **modo incremental** (saltar detalles ya vistos) que tenemos pendiente.

### 8. Estadísticas por host, estimación de tiempo y avisos
- **Qué hace**: contadores por host (éxitos, problemas temporales, errores permanentes, rate limits); estimación del
  tiempo restante; correos al alcanzar hitos o terminar.
- **Cómo**: tabla `statisticsHosts` + `update_host_stats_SP`; `TimeManager.estimate_remaining_time()`;
  `notification_manager.py` (`send_msg_milestone`, `send_msg_finish`, `send_msg_abort_lost_db`).
- **Por qué importa**: la estimación de tiempo restante es trivial y útil en ejecuciones largas; el aviso al terminar
  o al abortar es la base de las alertas que nos faltan.

## Qué aplicaríamos en nuestro motor

| # | Propuesta | Módulos afectados | Cambio YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | **Estados de error en la cola**: columnas `error_code`, `error_permanent`, `tries`, `not_before` en la tabla de cola (ver crawlee); `next()` excluye permanentes y no vencidos. | `storage/models.py`, `storage/repo.py`, `engine.py` | Ninguno | M (junto con la cola) | 1 |
| 2 | **Tabla de clasificación de códigos** (permanente/temporal) con valores por defecto de exoskeleton y sobrescribible por sitio. | `fetch/http.py`, `config.py` | `politeness.permanent_status: [...]`, `politeness.temporary_status: [...]` | S | 1 |
| 3 | **Reintento diferido entre ejecuciones**: los temporales agotados en el run quedan `pending` con `not_before` escalonado; el siguiente `run --resume` (o `scraper retry`) los recoge. | `engine.py`, `storage/repo.py`, `cli.py` | `politeness.deferred_retry_minutes: [15, 60, 360]` | M | 2 |
| 4 | **Enfriamiento del host tras 429** durante el run: si `Retry-After` falta o es excesivo, pausar todo el dominio N minutos o terminar el run como `interrupted` para reanudar después. | `fetch/http.py`, `engine.py` | `politeness.on_429: pause|stop`, `politeness.cooldown_seconds: 1800` | S | 1 |
| 5 | **Checkpoint de paginación** (equivalente a `jobs`): guardar por run y start_url la última página de listado procesada con éxito; `--resume` arranca ahí. Solución mínima si la cola completa se retrasa. | `storage/models.py`, `engine.py` | Ninguno | S | 1 |
| 6 | **Comando `scraper retry`** con filtros (`--temporary`, `--status 503`, `--all`) que vuelve a poner en cola los fallidos del último run. | `cli.py`, `storage/repo.py` | Ninguno | S | 2 |
| 7 | **Modo incremental**: si la URL de detalle normalizada ya existe en `items` (o en `pages` con 2xx) y no ha pasado `refresh_days`, no volver a descargarla y marcar el item como visto (`last_seen`). | `engine.py`, `storage/repo.py` | `incremental: {enabled: true, refresh_days: 7}` | M | 1 |
| 8 | **Estimación de tiempo restante** en el log de progreso y **aviso al terminar/abortar** (webhook n8n o correo) con el resumen del run. | `engine.py`, `export/` (webhook) | `notify: {webhook: ...}` | S | 3 |

## Qué NO copiaríamos y por qué
- **Procedimientos almacenados y dependencia de MariaDB** (`Generate-Database-Schema-MariaDB.sql`): rompe nuestro
  principio de "clonable en minutos" y la portabilidad SQLite/Postgres; la misma lógica cabe en el repo con SQLAlchemy.
- **Espera aleatoria entre 5 y 30 s** (`TimeManager.random_wait`) como mecanismo principal: la aleatoriedad amplia se
  usa para parecer humano; preferimos un delay fijo declarado + `Crawl-delay` + backoff, que es predecible y cortés.
- **Esperas de horas dentro del mismo proceso** (`DELAY_TRIES` hasta 6 h con el bot en bucle): para nosotros la
  ejecución es manual por CLI; los aplazamientos largos deben materializarse como `not_before` y resolverse en una
  ejecución posterior, no con un proceso dormido.
- **Guardar ficheros binarios, PDFs de Chrome y versiones de páginas** (`file_manager.py`, `remote_control_chrome.py`,
  `fileVersions`/`fileContent`): fuera del alcance de un motor de extracción de datos estructurados.
- **Sistema de etiquetas** (`label_manager.py`): nuestro `site` + `run_id` cubre el caso.
- Licencia Apache-2.0: solo patrones, sin copia de código.
