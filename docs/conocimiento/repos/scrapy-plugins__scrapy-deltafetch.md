# scrapy-plugins/scrapy-deltafetch
> Python · BSD (declarada en `pyproject.toml`; el repo no trae fichero LICENSE) · ⭐ ~275 · Último push 2025-02-26 · https://github.com/scrapy-plugins/scrapy-deltafetch

## Qué es
Un spider middleware de Scrapy de unas 90 líneas que hace crawls "delta": entre ejecuciones recuerda qué páginas ya produjeron items y no vuelve a pedirlas. Así la segunda y siguientes pasadas solo descargan los detalles nuevos.

## Arquitectura en breve
Un solo fichero, `scrapy_deltafetch/middleware.py`, con la clase `DeltaFetch`:
- `from_crawler` lee `DELTAFETCH_ENABLED`, `DELTAFETCH_DIR` y `DELTAFETCH_RESET` y toma el fingerprinter de Scrapy.
- `spider_opened` abre una BBDD `dbm` por spider (`<dir>/<spider>.db`). Con reset la abre en modo `n` (vacía). Si está corrupta, la borra y la recrea.
- `process_spider_output` recorre la salida del callback:
  - si es una **Request** y su clave está en la BBDD, la descarta (stat `deltafetch/skipped`);
  - si es un **item**, guarda la clave de la *petición que generó la respuesta* (`response.request`) con un timestamp (stat `deltafetch/stored`).

## Técnicas que nos interesan

### 1. Marcar la página "productora de items", no la URL visitada
- **Qué hace**: solo se memorizan las páginas que produjeron al menos un item, es decir, las páginas de detalle. Los listados y la paginación solo generan requests, así que nunca se marcan y se vuelven a recorrer siempre, lo que permite descubrir items nuevos.
- **Cómo**: la rama `else` de `process_spider_output` usa `self._get_key(response.request)` cuando lo que sale es un item.
- **Por qué importa**: es la semántica correcta para el modo incremental sin configurar nada. En nuestro motor equivale a recorrer siempre el listado y saltar el `detail_url` si ya existe en `items`.

### 2. Clave de deduplicación sobreescribible por petición
- **Qué hace**: por defecto la clave es el fingerprint de Scrapy, pero `request.meta["deltafetch_key"]` permite usar un id de negocio (p. ej. el id del anuncio) cuando varias URLs apuntan al mismo item.
- **Cómo**: `_get_key()`.
- **Por qué importa**: encaja con nuestra `key` natural. Para el BOE el identificador (`BOE-A-2026-XXXXX`) suele estar ya en la URL del listado, así que se puede decidir "ya visto" sin descargar el detalle.

### 3. Exclusión puntual y reset
- **Qué hace**: `meta["deltafetch_enabled"]=False` fuerza a descargar una petición concreta. El argumento `-a deltafetch_reset=1` o el setting `DELTAFETCH_RESET` vacían el estado.
- **Por qué importa**: hacen falta vías de escape para refrescar, por ejemplo, detalles que cambian (subastas cuyo estado evoluciona).

### 4. Robustez del almacén
- **Qué hace**: si `dbm` no abre, borra el fichero y empieza de cero en lugar de fallar.
- **Por qué importa**: nosotros usamos la BBDD principal, así que no aplica tal cual. La lección es que el estado incremental es una caché y perderlo solo debe costar una pasada completa, nunca datos.

## Qué aplicaríamos en nuestro motor
| # | Propuesta | Módulo afectado | Cambio YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | **Modo incremental**: antes de descargar un `detail_url`, consultar si ya existe un item del sitio con esa `source_url`/fingerprint (o con la clave natural calculable desde los campos del listado). Si existe, saltar la descarga y solo actualizar `last_seen`. Los listados se recorren siempre | `engine.py` (`_process_item`), `storage/repo.py` (`exists_by_url`, `touch_last_seen`), índice en `items.source_url` | `incremental: {enabled: true, key_from: list\|url}` | S | 1 |
| 2 | **Refresco selectivo**: `incremental.refresh_after_days: N` vuelve a descargar los detalles cuyo `last_changed` supera N días. `scraper run --full` ignora el modo incremental (equivale a reset, pero sin borrar datos) | `engine.py`, `cli.py` | `incremental.refresh_after_days` | S | 2 |
| 3 | **Parada temprana por página ya conocida**: si una página entera del listado solo contiene items ya vistos y el orden es por fecha descendente, cortar la paginación. Es una extensión nuestra, no está en deltafetch, pero sale de la misma idea | `engine.py` (`_crawl_listing`) | `incremental.stop_on_known_page: true` | S | 2 |
| 4 | **Contadores** `detail_skipped` y `detail_fetched` en el informe y en `runs` | `engine.py`, `storage/models.py` | — | S | 2 |

## Qué NO copiaríamos y por qué
- **Almacén `dbm` aparte**: ya tenemos `items` con `source_url`, `natural_key` y fechas en SQLite/Postgres. Un segundo almacén se desincronizaría, no es portable entre plataformas (el propio código lo reconoce con un TODO sobre las rutas) y no funciona con Postgres compartido.
- **Marcar como visto sin versión ni caducidad**: deltafetch nunca refresca un detalle. Para datos que cambian (subastas, precios) necesitamos `refresh_after_days`.
- **Enganchar al flujo de salida del spider**: es un detalle de Scrapy. En nuestro caso la decisión va en el orquestador, antes de lanzar la descarga del detalle.
- El proyecto tiene poco mantenimiento (último push en febrero de 2025). Tomamos la idea, no la dependencia.
