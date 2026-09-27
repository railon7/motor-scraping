# dgtlmoon/changedetection.io
> Python · Apache-2.0 · ⭐ ~34.6k · Último push 2026-09-25 · https://github.com/dgtlmoon/changedetection.io

## Qué es (2-3 líneas)
Aplicación web (Flask) autoalojada que vigila páginas ("watches") periódicamente, guarda cada versión del contenido filtrado, calcula diffs y notifica por decenas de canales vía **Apprise**. Incluye procesadores especializados: texto/JSON, **restock/precio** (lee datos estructurados JSON-LD/microdata/OpenGraph) y diff visual de imágenes.

## Arquitectura en breve
- `changedetectionio/worker.py` + `worker_pool.py` — workers async que toman watches de una cola, ejecutan el procesador y gestionan excepciones (errores de fetch, filtro no encontrado, etc.).
- `changedetectionio/processors/` — un procesador por tipo: `text_json_diff/processor.py`, `restock_diff/processor.py`, `image_ssim_diff/`. Base en `processors/base.py`.
- `changedetectionio/model/Watch.py` — modelo del watch; historial en disco (`save_history_blob`, `history`, `get_history_snapshot`, `history_trim`).
- `changedetectionio/diff/__init__.py` — `render_diff()` (línea a línea + inline por palabras, tokenizadores en `diff/tokenizers`).
- `changedetectionio/html_tools.py` — filtros CSS/XPath/JSONPath, `strip_ignore_text`.
- `changedetectionio/conditions/` — reglas de negocio con JSON Logic + plugins (`levenshtein_plugin.py`, `wordcount_plugin.py`).
- `changedetectionio/notification/handler.py`, `notification_service.py` — construcción del mensaje (plantillas Jinja2 con variables `{{diff}}`…) y envío con Apprise.
- `changedetectionio/model/App.py` — ajustes globales (p. ej. `filter_failure_notification_threshold_attempts = 6`).

## Técnicas que nos interesan

### 1. Aviso de "el selector dejó de funcionar"
- **Qué hace:** si los filtros CSS/XPath configurados no devuelven nada, no se considera "cambio" sino error de filtro, y tras N fallos **consecutivos** se envía una notificación específica.
- **Cómo:** `ContentProcessor.apply_include_filters()` (`processors/text_json_diff/processor.py`) concatena el resultado de cada filtro; si queda vacío lanza `FilterNotFoundInResponse` (incluye screenshot y datos de elementos para el selector visual). En `worker.py` el `except FilterNotFoundInResponse`: pone `last_error = "…Did the page change layout?…"`, incrementa `consecutive_filter_failures`, y si `>= filter_failure_notification_threshold_attempts` (defecto 6, `model/App.py`) llama a `NotificationService.send_filter_failure_notification()` y **resetea el contador a 0** (evita spam: avisa una vez cada N fallos). En cualquier comprobación correcta el contador vuelve a 0. El mensaje incluye los filtros, la URL y un enlace directo a editar el watch. Mismo patrón para fallos de "browser steps".
- **Por qué importa:** es la política exacta que nos falta: **distinguir "no hay datos" de "no hubo cambios"**, contar fallos consecutivos por sitio y avisar con umbral + anti-spam.

### 2. Historial de versiones
- **Cómo:** por watch hay un directorio con `history.txt` (índice de líneas `timestamp,fichero`) y un fichero por snapshot (`<snapshot_id>.txt`, comprimido `.txt.br` con Brotli a partir de un tamaño umbral). Escritura atómica del snapshot y `append + fsync` del índice (`Watch.save_history_blob`). Límite configurable `history_snapshot_max_length` (watch → etiqueta → global) con `history_trim()`. Lectura con `get_history_snapshot()` que resuelve rutas de forma segura (`realpath`, sin traversal).
- Además guarda `previous_md5` del texto filtrado para detectar cambio sin leer el snapshot, y un checksum del **documento bruto** para saltarse todo el procesado si la página no cambió (`checksumFromPreviousCheckWasTheSame`), invalidado cuando cambia la config de filtros (`FilterConfig.get_filter_config_hash`).
- **Por qué importa:** nuestro `items` solo guarda la última versión y un hash. Un historial append-only por item permitiría auditar y exportar cambios (p. ej. evolución de precios).

### 3. Diffs
- `diff.render_diff()` usa `difflib` a nivel de línea y, para líneas reemplazadas, diff inline por palabras (`render_inline_word_diff`, tokenizador `words_and_html`). Opciones: incluir añadidas/eliminadas/reemplazadas/iguales, formato patch, líneas de contexto, ignorar mayúsculas o espacios.
- En notificaciones expone variantes: `diff`, `diff_added`, `diff_removed`, `diff_full`, `diff_patch` y sus `_clean` (sin prefijos), `current_snapshot`, `prev_snapshot`, `triggered_text` (`notification_service.py`).
- Filtro de tipo de cambio por watch: `filter_text_added/removed/replaced` (`_apply_diff_filtering`) — p. ej. "solo avisar de líneas nuevas".
- **Por qué importa:** para nosotros el diff natural es **por campo** (dict antes/después), más simple y útil que el diff de texto.

### 4. Filtros de ruido y disparadores
Pipeline en `perform_site_check.run_changedetection()` (orden relevante):
1. `include_filters` (CSS, XPath `/…` o `xpath:`, `xpath1:` primer match, JSONPath/jq) y `subtractive_selectors` (quitar nodos: banners, relojes, contadores).
2. HTML → texto; `trim_text_whitespace`.
3. `ignore_text`: textos o regex estilo `/…/i` (con soporte multilínea) cuyas líneas se **excluyen del checksum** pero pueden mostrarse (`html_tools.strip_ignore_text`; `strip_ignored_lines` decide si también se quitan del snapshot). Hay `global_ignore_text` además del del watch.
4. `extract_text` (regex que se queda solo con lo que casa), `extract_lines_containing`, `remove_duplicate_lines`, `sort_text_alphabetically` (anula cambios de orden).
5. Checksum MD5 (opción `ignore_whitespace`).
6. **Reglas de bloqueo**: `trigger_text` (solo hay cambio si aparece cierto texto), `text_should_not_be_present` (solo avisa cuando desaparece, p. ej. "Agotado"), y **conditions** (JSON Logic: `==`, `<`, `in`, contiene…, más plugins de distancia Levenshtein y recuento de palabras; `conditions/__init__.py`, combinación ALL/ANY).
7. `check_unique_lines`: solo cuenta como cambio si hay alguna línea **nunca vista** en todo el historial (`Watch.lines_contain_something_unique_compared_to_history`) — elimina el ruido de contenido rotatorio.
- Opcional: evaluación por LLM de "intención" del cambio para suprimir avisos irrelevantes (`llm/evaluator.py`).

### 5. Vigilancia de restock y precio
- `processors/restock_diff/processor.py`: extrae disponibilidad y precio de **datos estructurados** — primero un extractor puro Python (`pure_python_extractor.py`: JSON-LD, OpenGraph, microdata) y, si falta algo, `extruct` en subproceso (aislado por fugas de memoria de lxml). Disponibilidad = contiene `instock`, `instoreonly`, `limitedavailability`, `onlineonly`, `presale`. Deduplicación de precios repetidos.
- Si el texto de la página indica "agotado" pero los metadatos dicen en stock, **gana el texto** ("lie detected").
- Reglas: `in_stock_processing` = `in_stock_only` (solo avisar al volver a haber stock) o `all_changes`; `follow_price_changes`; `price_change_min/max` (si el precio está dentro del rango, no avisa); `price_change_threshold_percent` (ignora variaciones ≤ X% frente al precio de la comprobación anterior). Guarda `last_price` para mostrar la flecha subida/bajada.
- El snapshot es una línea canónica `In Stock: … - Price: …`, lo que hace el historial compacto y el diff trivial.
- **Por qué importa:** en catálogos/precios (candidato a piloto) muchas webs publican JSON-LD `Product/Offer`, que es **más estable que cualquier selector CSS**.

### 6. Notificaciones (Apprise)
- `notification/handler.py:process_notification()` crea `apprise.Apprise()`, añade cada URL (`mailto://`, `tgram://`, `slack://`, `json://`, `discord://`…) y llama `notify()`. Título/cuerpo son plantillas Jinja2 con las variables anteriores; formato texto/markdown/HTML adaptado por servicio (`apply_service_tweaks`). URLs a nivel watch, con herencia etiqueta → global (`_check_cascading_vars`). `notification_muted` por watch.
- **Por qué importa:** con una sola dependencia (Apprise, BSD-2) cubrimos email, Teams, Telegram, Slack y webhooks (n8n) para avisar de fallos y de cambios.

## Qué aplicaríamos en nuestro motor
| # | Propuesta | Módulos | YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | **Salud de selectores por run**: guardar en `runs` (o tabla `run_field_stats`) el % de vacíos por campo y nº de items por página; al terminar, comparar con la media de los últimos N runs `ok`. Marcar run `degraded` si: `item_selector` devuelve 0 en p1, un campo `required` falla > X%, o un campo sube de vacíos > Y puntos respecto al histórico. Contador `consecutive_failures` por sitio; alertar al llegar al umbral y resetear (anti-spam). | `engine.py` (`RunReport`), `storage/models.py`, `storage/repo.py`, `cli.py status` | `alerts: { max_empty_pct: 30, max_empty_increase: 20, consecutive_runs: 2 }` | M | 1 |
| 2 | **Historial de items**: tabla `item_versions(item_id, run_id, seen_at, content_hash, data JSON)` escrita solo cuando cambia el hash (append-only), y columna `changes` con diff **por campo** `{campo: [antes, después]}`. Límite opcional de versiones por item. `export --cambios --desde <fecha>`. | `storage/models.py`, `storage/repo.py.upsert_item`, `export/` | `history: { keep_versions: 50 }` | M | 1 |
| 3 | **Items desaparecidos**: al final de un run *completo y sano* (no interrumpido, no `degraded`, no `--limit`), marcar `items.status='gone'` + `gone_at` para los del sitio con `last_seen < run.started_at`; volver a `active` si reaparecen. Contabilizar `items_gone` en `runs`. No marcar si el run tiene alerta de selectores (evita "desapariciones" falsas por maquetación rota). | `engine.py`, `storage/repo.py`, `storage/models.py` | `track_removed: true` | S | 1 |
| 4 | **Notificaciones con Apprise** (opcional, extra `[notify]`): URLs en `.env` o YAML; eventos `selector_roto`, `run_error`, `cambios` (resumen: n nuevos/actualizados/desaparecidos + top diffs por campo). | nuevo `scraper/notify.py`, `engine.py` | `notify: { urls: ["mailto://…", "json://n8n…"], on: [selector_roto, cambios] }` | S | 2 |
| 5 | **Filtros de ruido por campo** para el hash: `ignore_in_hash: [visitas, fecha_actualizacion]` y normalizadores (`sort` en listas, `ignore_whitespace`). Evita "actualizados" falsos por contadores o relojes. | `pipeline/dedupe.py.content_hash`, `config.py` | `ignore_in_hash: [...]` / `fields.x.sort: true` | S | 1 |
| 6 | **Disparadores por campo** para notificar: `watch: { precio: { threshold_pct: 5, min: , max: }, stock: { only: back_in_stock } }` inspirado en restock. | nuevo `pipeline/triggers.py` | `watch:` | M | 3 |
| 7 | **Extracción desde JSON-LD/microdata** como tipo de selector: `selector: "jsonld:Product.offers.price"`. Más estable que CSS en e-commerce y fichas. | `parse/selectors.py` (nuevo prefijo), `parse/structured.py` | prefijo `jsonld:` | M | 2 |
| 8 | **Salto por checksum de la página bruta**: guardar hash del HTML de listado/detalle en `pages`; si no cambia y la config tampoco (hash del YAML), saltar el parseo. Solo optimización. | `engine.py`, `storage/models.py` | — | S | 3 |

## Qué NO copiaríamos y por qué
- **Historial como ficheros de texto por watch** (`history.txt` + `.txt.br`): pensado para páginas completas; nuestros datos son registros estructurados → mejor en BD (SQLite/Postgres), consultables y exportables.
- **Diff de texto línea a línea** para items: el diff por campo es más preciso y legible para nuestros usuarios.
- **Evaluación de cambios con LLM**: coste y no determinismo; fuera de alcance (PLAN §7).
- **Proxies, browser steps con login, extensiones de navegador y fetchers para esquivar bloqueos**: contrarios a nuestra política; tampoco necesitamos la UI Flask ni el selector visual (quizá en el futuro).
- **Resetear el contador tras avisar sin registrar el estado "roto"**: nosotros dejaríamos el sitio en estado `degraded` visible en `scraper status` hasta que un run vuelva a estar sano.
- Licencia Apache-2.0: reutilizable con aviso de NOTICE, pero todo lo propuesto es reimplementación de ideas simples.
