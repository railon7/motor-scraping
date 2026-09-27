# alephdata/memorious
> Python · MIT · ⭐ 316 · Último push 2026-05-20 · https://github.com/alephdata/memorious

## Qué es (2-3 líneas)
Framework de crawling de OCCRP/Aleph pensado para periodismo de datos: cada crawler es un YAML que describe un **grafo de etapas** (`pipeline`) conectadas por reglas de salida (`handle`). Las etapas son funciones Python (incluidas o propias) que reciben `context` + `data` y emiten hacia la siguiente. Orientado a descargar documentos y alimentar Aleph, más que a extraer campos tabulares.

## Arquitectura en breve
- `memorious/logic/crawler.py` (`Crawler`): carga el YAML, crea un `CrawlerStage` por clave de `pipeline`, gestiona `schedule`, `delay`, `expire` y un `aggregator` final.
- `memorious/logic/stage.py` (`CrawlerStage`): resuelve `method` en dos pasos: primero un *entry point* registrado (`memorious.operations` en `setup.py`), si no, `paquete.modulo:funcion` importado dinámicamente.
- `memorious/logic/context.py` (`Context`): `emit(rule=..., data=...)` encola la etapa indicada en `handle[rule]`; `recurse()` re-encola la misma etapa (paginación, secuencias largas); tags para incremental (`skip_incremental`, `check_tag`).
- Operaciones incluidas en `memorious/operations/`: `initializers.py` (seed, sequence, dates, enumerate, tee), `fetch.py`, `parse.py`, `clean.py`, `store.py`, `db.py`, `debug.py` (inspect).
- Reglas declarativas de filtrado en `memorious/helpers/rule.py`.
- Cola y estado en Redis/servicelayer (pesado para nuestro caso).

## Técnicas que nos interesan

### 1. Pipeline como grafo de etapas con salidas nombradas
- **Qué hace**: cada etapa decide a qué etapa siguiente enviar cada dato mediante nombres de regla (`pass`, `fetch`, `store`...). Permite multinivel arbitrario (listado → sublistado → detalle → adjunto) y recursividad (una etapa `parse` que envía a `fetch` convierte el scraper en crawler).
- **Cómo**: `Context.emit()` busca `stage.handlers[rule]` y encola esa etapa (`memorious/logic/context.py`). Validación mínima: nombres de etapa con regex `^[A-Za-z0-9_-]+$` (`stage.py`, `validate_name`).
- **Fragmento** (`example/config/simple_web_scraper.yml`):
  ```yaml
  parse:
    method: parse
    params:
      store: { or: [ {mime_group: archives}, {mime_group: documents} ] }
    handle:
      store: store
      fetch: fetch   # recursivo
  ```
- **Por qué importa**: nuestro motor tiene un único nivel `list → detail`. Un grafo de "niveles" con nombre resuelve el multinivel sin volverse un lenguaje de programación.

### 2. Reglas declarativas componibles (`and`/`or`/`not`)
- **Qué hace**: filtros sobre la respuesta (dominio, patrón de URL, mime_type, mime_group, xpath) combinables con `and`/`all`, `or`/`any`, `not`, `match_all`.
- **Cómo**: `memorious/helpers/rule.py`, clase base `Rule` con `configure()` (valida y precompila, lanza error si el valor no es del tipo esperado: "Not a regex", "Ambiguous rules", "Unknown rule") y `apply(res)`. Registro en un diccionario `RULES` nombre→clase.
- **Fragmento** (`example/config/simple_web_scraper.yml`):
  ```yaml
  rules:
    and:
      - domain: occrp.org
      - not:
          or:
            - pattern: "https://www.occrp.org/en/donate.*"
            - mime_group: images
  ```
- **Por qué importa**: nos sirve para `follow`/`skip` de enlaces de detalle y para filtrar items (`when:`) sin código.

### 3. Initializers declarativos (seed / sequence / dates / enumerate)
- **Qué hace**: generan URLs de arranque a partir de rangos numéricos, fechas hacia atrás con paso en días/semanas, o listas; interpolan en la URL con `%(number)s` / `%(date)s`.
- **Cómo**: `memorious/operations/initializers.py`. `sequence` admite `start/stop/step` y un `tag` para no repetir números entre ejecuciones; `dates` admite `format`, `begin/end`, `days/weeks`, `steps`.
- **Por qué importa**: muchos boletines/registros públicos se paginan por fecha o por id. Hoy solo tenemos `start_urls` fijas y `url_template` con `{page}`.

### 4. Extensibilidad por referencia `modulo:funcion` + entry points
- **Qué hace**: cualquier etapa puede apuntar a una función propia (`example.quotes:crawl`) sin tocar el núcleo; las operaciones de terceros se registran como *entry points* y se usan por nombre corto.
- **Cómo**: `CrawlerStage.method` en `memorious/logic/stage.py`; `setup.py` sección `memorious.operations`. La CLI `run-file --src` añade la carpeta `src/` junto al YAML al `sys.path` (`memorious/cli.py`).
- **Por qué importa**: patrón exacto para nuestras "funciones custom" por campo o por sitio (`sites/<sitio>/hooks.py`).

### 5. `params` de etapa + `data` que fluye
- Separación limpia entre configuración estática (`params`) y datos dinámicos que viajan (`data`), con interpolación de `data` en `params` (seed como segunda etapa). Útil para pasar variables de un nivel al siguiente (p. ej. `categoria` del listado al detalle).

### 6. Incremental por tags con caducidad
- `Context.skip_incremental(*criterios)` + `expire` por crawler (`crawler.py`): una operación se salta si ya se hizo en la ventana. Complementa nuestro upsert por hash: evita incluso descargar.

### 7. Utilidades de depuración como etapas
- `inspect` (`memorious/operations/debug.py`) imprime `data` y deja pasar: se inserta en cualquier punto del grafo. Documentación: `docs/src/pages/reference.mdx`, sección por operación con "Parameters" y "Output data" (muy buen formato de referencia).
- Checks de datos opcionalmente estrictos en `memorious/logic/check.py` (`is_not_empty`, `match_date`, `match_regexp`, `has_length`, con `strict` que decide si avisa o lanza).

## Qué aplicaríamos en nuestro motor

| # | Propuesta | Módulo afectado | Cambio en YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | Niveles con nombre (`levels`) generalizando list→detail; `list`/`detail` actuales se traducen internamente a dos niveles | `config.py`, `engine.py` | `levels: {listado: {...follow: {ficha: "a::attr(href)"}}, ficha: {...}}` | L | 2 |
| 2 | Reglas `and/or/not` con `pattern`, `domain`, `selector_exists` para filtrar enlaces a seguir y items | nuevo `scraper/parse/rules.py`, `engine.py` | `follow_if: {and: [{pattern: "/ficha/\\d+"}, {not: {domain: "ads.x"}}]}` | S | 2 |
| 3 | Generadores de semillas: `range` y `dates` | `config.py` (`StartSpec`), `engine.py` | `start: {template: "/boletin/{date}", dates: {from: 2024-01-01, step_days: 1}}` | S | 1 |
| 4 | Funciones custom `modulo:funcion` (hooks por campo y por item) con carpeta `sites/<sitio>/` en `sys.path` | `pipeline/extract.py`, nuevo `scraper/plugins.py` | `transform: [{call: "mis_hooks:normaliza_ref"}]` | M | 1 |
| 5 | Paso `inspect`/`--trace` que vuelca el dict de cada nivel | `engine.py`, `cli.py` | `debug: true` o flag CLI | S | 3 |
| 6 | Validaciones declarativas por campo (`validate: {regex, min_len}`) con modo `warn`/`strict` | `pipeline/extract.py` | `validate: {regex: "^\\d{5}$", on_fail: warn}` | S | 2 |
| 7 | Formato de referencia de docs: por cada bloque "Parámetros / Salida / Ejemplo" | `docs/NUEVO-SITIO.md` → `docs/REFERENCIA-YAML.md` | — | S | 2 |

## Qué NO copiaríamos y por qué
- **Grafo totalmente libre con código en cada etapa**: la potencia se paga en legibilidad; para nuestros usuarios (consultores) preferimos niveles tipados y código solo como excepción.
- **`stealthy` (User-Agent aleatorio)** (`crawler.py`, `helpers/ua.py`): es evasión; nuestro principio es UA identificable.
- **Infra Redis/servicelayer, colas distribuidas y `aggregator`**: rompen "clonable en minutos"; SQLite + asyncio nos basta.
- **Validación casi inexistente del YAML** (se lee con `yaml.safe_load` y se accede con `.get`): los errores aparecen en ejecución. Nosotros ya validamos con Pydantic y queremos ir más allá.
- **XPath como única sintaxis de extracción**: la añadiríamos como opción (`xpath:`), no la impondríamos.
- Licencia MIT: se pueden reutilizar ideas libremente; no copiamos código.
