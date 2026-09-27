# okfn-brasil/querido-diario
> Python (Scrapy) · MIT · ⭐ ~1.4k · Último push 2026-09-23 · https://github.com/okfn-brasil/querido-diario

## Qué es
Raspadores de los diarios oficiales municipales de Brasil, de Open Knowledge Brasil. Tiene unos 476 spiders (uno por municipio o asociación) que descargan los PDF de cada edición con metadatos normalizados: fecha, número de edición, si es extraordinaria, poder emisor y territorio. Se ejecuta a diario en Scrapy Cloud. Es el caso más parecido al piloto del BOE: una publicación oficial por fechas, a largo plazo y con ejecuciones incrementales.

## Arquitectura en breve
Todo cuelga de `querido_diario_raspadores/`:
- `gazette/spiders/base/__init__.py`: `BaseGazetteSpider`, la clase raíz con el contrato mínimo y el rango de fechas.
- `gazette/spiders/base/*.py`: **22 clases base por sistema de publicación** (proveedor de software que usan muchos ayuntamientos). Ejemplos: `instar.py` (unos 111 spiders hijos), `doem.py` (unos 57), `dosp.py` (unos 42), `adiarios_v1.py` (unos 34), `sigpub.py`, `atende_v2.py`, `diof.py`...
- `gazette/spiders/<uf>/<uf>_<municipio>.py`: los spiders concretos, casi siempre de **4-6 líneas de configuración** (ver `gazette/spiders/mg/mg_betim.py`: `TERRITORY_ID`, `name`, `base_url`, `start_date`).
- `gazette/items.py` (item `Gazette`), `gazette/resources/gazette_schema.json` (JSON Schema), `gazette/pipelines.py`, `gazette/monitors.py`, `gazette/extensions.py`, `gazette/database/models.py`.
- `scheduler.py` y `.github/workflows/*.yaml`: programan las ejecuciones diarias, mensuales y por fecha.
- `templates/spiders/qdtemplate.tmpl`: la plantilla para `scrapy genspider`.

## Técnicas que nos interesan

### 1. Jerarquía de tres niveles: raíz → sistema de publicación → sitio
- **Qué hace**: separa la lógica de navegación, que es común a todos los municipios que usan el mismo proveedor, de los datos del sitio (URL, fecha de inicio, id de territorio).
- **Cómo**:
  - La raíz `BaseGazetteSpider.__init__` exige los atributos `TERRITORY_ID`, `allowed_domains` y `start_date`, y si falta alguno lanza `NotConfigured` con un mensaje claro.
  - Cada base de sistema valida sus propios atributos: `BaseSigpubSpider` exige `CALENDAR_URL`, `BaseInstarSpider` exige `base_url` y deriva `allowed_domains` de él, y `BaseDoemSpider` exige `state_city_url_part`.
  - Los hijos solo declaran atributos y, a veces, `custom_settings` (`DOWNLOAD_DELAY`, `CONCURRENT_REQUESTS_PER_DOMAIN`), como en `gazette/spiders/al/al_associacao_municipios.py`.
- **Por qué importa**: es exactamente nuestro modelo, pero "YAML hijo que hereda de YAML plantilla". Cuando un sistema de publicación cambia de HTML, se arregla un solo fichero y se reparan decenas de sitios.

### 2. Parámetros de fecha `start` / `end` como argumentos estándar
- **Qué hace**: todos los spiders aceptan `-a start=YYYY-MM-DD -a end=YYYY-MM-DD`. Si no se pasan, se usan el `start_date` del sitio (inicio histórico) y hoy.
- **Cómo**:
  - `BaseGazetteSpider.__init__` parsea las fechas y registra el rango con "Collecting data from X to Y".
  - Cada base convierte el rango al formato del sitio:
    - `BaseInstarSpider.start()` lo inyecta en la URL: `{base_url}/{page}/{dd-mm-aaaa}/{dd-mm-aaaa}/0/0/`.
    - `BaseDoemSpider.start()` genera una URL por mes (`/diarios/{YYYY/MM}`).
    - `BaseSigpubSpider.available_dates_form_fields()` recorre día a día con un formulario.
- **Por qué importa**: la ejecución incremental se reduce a "lanza con `start=ayer`". Para el BOE, su sumario diario (API de datos abiertos, del tipo `/datosabiertos/api/boe/sumario/AAAAMMDD`; verificar la ruta exacta antes del piloto) encaja con una plantilla de URL por día.

### 3. Generadores de secuencias y ventanas de fechas
- **Qué hace**: utilidades para generar días, meses, años y ventanas (semana, mes, año) entre dos fechas, con formato opcional.
- **Cómo**: `gazette/utils/dates.py`: `daily_sequence`, `monthly_sequence`, `yearly_sequence`, `weekly_window`, `monthly_window`, `yearly_window`, todas sobre `dateutil.rrule` y `itertools.pairwise`. Las ventanas cierran con el `end` real (parámetro `end_included`). Tienen tests en `tests/test_dates.py`.
- **Por qué importa**: muchos buscadores oficiales limitan el rango de una consulta. Trocear por ventanas evita tener paginaciones enormes.

### 4. Doble filtro por fecha (en el parseo y en el pipeline)
- **Qué hace**: aunque el sitio devuelva de más (p. ej. el mes entero), solo se emiten los items dentro del rango.
- **Cómo**: `BaseDoemSpider.parse` comprueba `start_date <= date <= end_date`, y `GazetteDateFilteringPipeline` (`gazette/pipelines.py`) descarta con `DropItem` todo lo anterior a `start_date`.
- **Por qué importa**: garantiza que una ejecución incremental no reprocese el histórico.

### 5. Programación: diaria con `start=ayer` más barrido mensual de huecos
- **Qué hace**: cada día se lanzan todos los spiders habilitados con `start=ayer`. El día 1 de cada mes se relanza con `start=hoy-31` para cubrir los días en que algo falló o el diario se publicó tarde. También existe `--full` para el histórico completo.
- **Cómo**: `scheduler.py` (`schedule_enabled_spiders` con `YESTERDAY`, `last_month_schedule_enabled_spiders`, `_schedule_job(full=...)`) y los workflows `.github/workflows/daily_crawl.yaml` y `monthly_crawl.yaml`. La idempotencia la da el `FilesPipeline`: un fichero con estado `uptodate` no se vuelve a persistir (ver `SQLDatabasePipeline.process_item` y `ApiPipeline.process_item`).
- **Por qué importa**: es un patrón simple y robusto que hace innecesario el "reanudar" fino. Solapar ventanas es barato si el upsert es idempotente, y el nuestro ya lo es.

### 6. Registro de spiders con metadatos operativos
- **Qué hace**: una tabla guarda para cada spider el rango de fechas que cubre y si está habilitado en producción.
- **Cómo**: `gazette/database/models.py`, `QueridoDiarioSpider` (`spider_name`, `date_from`, `date_to`, `enabled`) relacionada con `Territory`. Los comandos `gazette/commands/qd-list-enabled.py` (filtra por fechas) y `qd-sync-spiders.py`, y en `scheduler.py` `enable-spider`/`disable-spider`.
- **Por qué importa**: con muchos sitios hace falta saber cuáles se ejecutan, desde cuándo hay datos y cuáles están rotos. Para nosotros basta con los campos `enabled` y `date_from` en el YAML y un `scraper status` que los muestre.

### 7. Validación por esquema y monitores al cierre
- **Qué hace**: cada item se valida contra un JSON Schema y el que no cumple se descarta. Al cerrar se evalúan reglas de salud y, si falla alguna, se avisa (Discord).
- **Cómo**:
  - `gazette/resources/gazette_schema.json`: `date` con formato date, `power` como enum y `files` con `minItems: 1`. Lo aplica el `ItemValidationPipeline` de spidermon (configurado en `gazette/settings.py`: `SPIDERMON_VALIDATION_DROP_ITEMS_WITH_ERRORS`).
  - `gazette/monitors.py`:
    - `RequestsItemsRatioMonitor` falla si hay más de 5 peticiones por item (`QUERIDODIARIO_MAX_REQUESTS_ITEMS_RATIO`), una señal de navegación desbocada o de selectores rotos.
    - `ComparisonBetweenSpiderExecutionsMonitor` falla si en los últimos 7 días (`QUERIDODIARIO_MAX_DAYS_WITHOUT_GAZETTES`) no se ha extraído nada, sumando las estadísticas de ejecuciones anteriores. Es una alerta de "sitio muerto o selector roto".
    - Además usan los monitores estándar de errores, `finish_reason` y validación.
  - `gazette/extensions.py::StatsPersist` guarda las stats de cada job para poder comparar entre ejecuciones.
- **Por qué importa**: resuelve nuestro hueco de "alertas de selectores rotos" con reglas simples sobre stats que ya tenemos en `runs`.

### 8. Detectar páginas de bloqueo y fallar en voz alta
- **Qué hace**: si la respuesta es una página de desafío (interstitial) en lugar del contenido, no la parsea como si fuera buena y cierra el spider con un motivo explícito.
- **Cómo**: `gazette/utils/blocking.py::is_cloudflare_challenge` busca marcadores en los primeros 8 KB. `GazetteDownloaderMiddleware.process_response` (`gazette/middlewares.py`) lanza `CloseSpider("blocked_by_cloudflare_turnstile")`. Hay tests en `tests/test_blocking.py`.
- **Por qué importa**: encaja con nuestra política de no evadir: detectar, parar y auditar, en vez de guardar basura.

### 9. Tests baratos por clase base y de compatibilidad
- **Qué hace**: los tests prueban cada base con un hijo mínimo creado en el propio test, sin red (p. ej. `tests/test_sigpub.py` comprueba que `start()` produce la petición al calendario). `tests/test_spider_compatibility.py` recorre **todos** los spiders con `SpiderLoader` y comprueba una regla global (que no usen el `start_requests` antiguo).
- **Por qué importa**: con muchos sitios, un test que cargue y valide todos los YAML de `sites/` detecta regresiones del esquema sin tocar la red.

## Qué aplicaríamos en nuestro motor
| # | Propuesta | Módulo afectado | Cambio YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | **Rango de fechas de primera clase**: `scraper run sites/boe.yaml --since 2026-09-01 --until 2026-09-26` (por defecto `since` = última fecha OK o `date_from`). Nueva paginación `date_template` que genera URLs por día, mes o ventana con `{date:%Y%m%d}`, `{start}` y `{end}` | `config.py` (`Pagination.date_template`, `date_step: day\|month\|window`), `parse/pagination.py`, nuevo `pipeline/dates.py` (secuencias y ventanas), `cli.py` | `dates: {date_from: 2009-01-01, step: day, template: "/datosabiertos/api/boe/sumario/{date:%Y%m%d}"}` | M | 1 |
| 2 | **Filtro de rango en el pipeline**: `dates.field: fecha_publicacion` descarta los items fuera de `[since, until]` y los cuenta como `dropped_out_of_range` | `engine.py` | `dates.field` | S | 1 |
| 3 | **Plantillas YAML heredables**: `extends: templates/boe-like.yaml` con fusión profunda. El hijo solo aporta `base_url`, `date_from` y lo que cambie. Validar los atributos obligatorios de la plantilla (equivalente al `NotConfigured`) | `config.py` (`load_site` con merge), nueva carpeta `sites/templates/` | `extends:` + `required_vars:` | M | 2 |
| 4 | **Monitores al cierre**: reglas `monitor.max_requests_per_item`, `monitor.max_days_without_items` (consultando `runs`/`items`), `monitor.max_empty_field_ratio` → estado `warning` en `runs` y aviso opcional por webhook (n8n) | nuevo `scraper/monitor.py`, `engine.py`, `storage/repo.py` | `monitor:` | M | 2 |
| 5 | **Barrido de huecos**: `scraper run --backfill 31d` relanza la ventana solapada; es seguro gracias al upsert idempotente | `cli.py` | — | S | 2 |
| 6 | **Detección de página de bloqueo o de mantenimiento**: marcadores configurables → error `blocked` y parada del run (sin reintentos agresivos) | `fetch/http.py`, `engine.py` | `fetch.block_markers: [...]` | S | 3 |
| 7 | **Test global de `sites/`**: pytest que carga y valida todos los YAML y comprueba las claves y plantillas | `tests/` | — | S | 2 |
| 8 | **`enabled` y `date_from` en el YAML** y `scraper status` mostrando sitios habilitados, la última fecha cubierta y los días sin datos | `config.py`, `cli.py` | `enabled: true`, `dates.date_from` | S | 3 |

## Qué NO copiaríamos y por qué
- **`ROBOTSTXT_OBEY = False` y User-Agent de navegador** (`gazette/settings.py`), y el **proxy de pago Zyte Smart Proxy** (`ZyteSmartProxyMiddleware`, `zyte_smartproxy_enabled`): chocan con nuestros principios de cortesía y de no evasión. Mantenemos robots.txt y un UA identificable.
- **Un fichero Python por sitio**: para nosotros el sitio es un YAML y la "clase base" es una plantilla YAML. Python solo como excepción.
- **Dependencia de Scrapy Cloud, spidermon, S3 y la API propia**: es infraestructura de producción que no queremos para un motor clonable en minutos. Replicamos la idea con SQLite más un webhook opcional.
- **Guardar solo los metadatos más el fichero PDF**: su modelo es "documento". El nuestro es "registro estructurado", aunque para el BOE conviene añadir más adelante la descarga opcional de adjuntos con checksum.
- **Licencia MIT**: permitiría reutilizar código, pero seguimos la regla de describir patrones, no copiar.
