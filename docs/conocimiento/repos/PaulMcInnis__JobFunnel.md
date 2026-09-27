# PaulMcInnis/JobFunnel
> Python · MIT · ⭐ ~2.200 · Último push 2025-12-10 (**archivado**) · https://github.com/PaulMcInnis/JobFunnel

## Qué es (2-3 líneas)
Herramienta CLI que busca ofertas de empleo en varios portales (Indeed, Monster, Glassdoor) y las consolida en **una hoja CSV maestra** sin duplicados, que el usuario edita a mano (columna `status`). En ejecuciones posteriores respeta lo que el usuario marcó y elimina duplicados tanto por identificador como **por similitud del texto** (TF-IDF).

## Arquitectura en breve
- `jobfunnel/backend/jobfunnel.py` — `JobFunnel.run()`: lee el CSV maestro → actualiza lista de bloqueo → scrapea (o carga la caché diaria) → filtra → detecta duplicados → fusiona → escribe CSV.
- `jobfunnel/backend/scrapers/base.py` — `BaseScraper`: obtiene "soups" de los resultados de búsqueda y construye cada `Job` campo a campo con un pool de hilos; cada scraper concreto declara qué campos son `get` (del listado) y cuáles son "diferidos" (requieren otra petición).
- `jobfunnel/backend/job.py` — modelo `Job` (key_id, título, empresa, descripción, fechas, status…).
- `jobfunnel/backend/tools/filters.py` — `JobFilter`: filtros y deduplicación.
- `jobfunnel/backend/tools/delay.py` — cálculo de retardos por petición.
- Configuración YAML + CLI (`jobfunnel/config/`), validada en clases propias.
- Ficheros persistentes: CSV maestro, `block_list.json` (bloqueados por el usuario), `duplicates_list.json` (duplicados por contenido), caché diaria en pickle.

## Técnicas que nos interesan

### 1. Deduplicación en dos capas: clave + similitud de contenido (TF-IDF)
- **Qué hace**: primero descarta coincidencias exactas por `key_id` (prefijado con el proveedor para evitar colisiones entre portales). Con lo que queda, calcula TF-IDF sobre la **descripción** de entrantes + existentes y marca como duplicado todo entrante con similitud coseno ≥ **0,75** con alguno existente. Solo actúa si hay al menos **25** registros (con menos el TF-IDF no es fiable).
- **Cómo**: `JobFilter.find_duplicates` y `JobFilter.tfidf_filter` en `jobfunnel/backend/tools/filters.py` (scikit-learn `TfidfVectorizer` con `strip_accents="unicode"`, minúsculas y stopwords de NLTK en inglés; `cosine_similarity`). Tipos de duplicado en `resources/enums.py`: `KEY_ID`, `EXISTING_TFIDF`, `NEW_TFIDF`. Los duplicados por contenido se **memorizan** en `duplicates_list.json` para no recalcular y para filtrarlos en adelante por su clave.
- **Qué pasa con el duplicado**: no se añade; se usa para **actualizar el original si es más reciente** (`Job.update_if_newer`, compara `post_date`), conservando el estado que puso el usuario.
- **Por qué importa**: en anuncios (BOE, portales, directorios) el mismo contenido aparece con URLs o IDs distintos (reediciones, varios portales). Nuestra clave natural + hash no detecta eso.
- **Ojo, fallos en su código** (útiles para no repetirlos): en `tfidf_filter` el índice del "más parecido" se calcula sobre el subconjunto filtrado pero se usa sobre la lista completa (puede apuntar al original equivocado); en `jobfunnel.py` la condición `match.type in [KEY_ID or EXISTING_TFIDF]` solo compara con `KEY_ID`. Además solo usa stopwords en inglés.

### 2. Filtros antes de la petición cara
- **Qué hace**: mientras construye un `Job`, tras cada campo comprueba `JobFilter.filterable(job)`; si ya se sabe que se va a descartar (empresa bloqueada, fecha demasiado antigua, id en lista de bloqueo, remoto no deseado), **cancela** y no hace las peticiones diferidas del detalle.
- **Cómo**: `BaseScraper.scrape_job` en `jobfunnel/backend/scrapers/base.py`; campos `high_priority_get_set_fields` primero y `delayed_get_set_fields` al final.
- **Por qué importa**: equivale a "filtrar en el listado antes de pedir el detalle", lo que nos ahorraría peticiones cuando el YAML ya sabe que no interesan ciertos registros.

### 3. La hoja maestra como interfaz de usuario
- El CSV maestro es a la vez salida y entrada: el usuario cambia `status` (p. ej. `archive`, `rejected`, `delete`), y en la siguiente ejecución esos registros pasan a `block_list.json` (`update_user_block_list`) y no vuelven a aparecer ni se sobrescribe su estado.
- **Por qué importa**: patrón muy práctico para clientes que trabajan en Excel: columnas "del usuario" que el scraper nunca pisa.

### 4. Retardos por petición con curva
- `tools/delay.py`: genera una lista de retardos (constante, lineal o sigmoide) con opción aleatoria y mínimo/máximo, y un lock compartido entre hilos. Arranque suave: las primeras peticiones van más despacio o más rápido según la curva.
- **Por qué importa**: poco. Nuestro `DomainLimiter` ya garantiza separación mínima por dominio; el aleatorio con fines de camuflaje no lo queremos.

### 5. Caché diaria y recuperación
- Cada scrape se vuelca a un pickle por fecha/búsqueda (`write_cache`, `load_cache`); `--no-scrape` rehace el CSV desde la caché y `recover()` reconstruye el maestro desde todos los pickles.
- **Por qué importa**: la idea "reconstruir la salida desde lo descargado sin volver a la red" es buena; el pickle no (frágil entre versiones).

## Qué aplicaríamos en nuestro motor
| # | Propuesta | Módulo afectado | Cambio en YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | **Filtros declarativos pre-detalle**: condiciones sobre campos del listado (fecha mínima, valores excluidos, regex) que descartan el item antes de pedir su detalle; contador `items_filtered` en el informe. | `engine.py` (`_process_item`), `config.py` | `list.filters: [{field: fecha, min_age_days: 60}, {field: provincia, in: [Madrid, Toledo]}]` | S | 1 |
| 2 | **Deduplicación por similitud (opcional)**: tras el upsert por clave, comparar campos de texto elegidos entre registros nuevos y existentes del sitio; los que superan el umbral se marcan `duplicate_of` (no se borran) y se informan. Umbral y campos configurables; corpus mínimo; stopwords en español. Implementable sin scikit-learn para volúmenes pequeños (difflib / shingles + Jaccard) y con TF-IDF como extra opcional. | nuevo `pipeline/similar.py`, `storage/models.py` (columna `duplicate_of`), `storage/repo.py`, informe en `cli.py` | `dedupe: {similarity: {fields: [titulo, descripcion], threshold: 0.8, min_corpus: 25}}` | M | 2 |
| 3 | **Columnas del usuario protegidas**: declarar campos que el export incluye vacíos y que, si el usuario los rellena y se reimportan (`scraper import-status fichero.xlsx`), se guardan aparte y nunca se sobrescriben; permitir excluir registros marcados. | `export/`, `storage/models.py` (tabla `item_annotations`), `cli.py` | `export: {user_columns: [estado, notas]}` | M | 3 |
| 4 | **Regla "actualizar solo si más reciente"**: en el upsert, si el YAML declara un campo de fecha de publicación, no sobrescribir datos con una versión más antigua. | `storage/repo.py` | `key_date: fecha_publicacion` | S | 3 |
| 5 | **Reconstruir export desde BBDD** ya lo hacemos (`scraper export`); añadir en README que esa es nuestra "recuperación" (no hace falta caché de pickles). | `README.md` | — | S | 3 |

## Qué NO copiaríamos y por qué
- **Rotación de User-Agent (listas de UAs de escritorio y móvil en `resources/`) y proxies (`config/proxy.py`)**: evasión; contrario a nuestra política de UA identificable.
- **Retardos aleatorios "para parecer humano"**: mismo motivo; nuestro retardo es fijo y declarado (mínimo respetuoso).
- **Borrado silencioso de duplicados por contenido**: preferimos marcar (`duplicate_of`) y auditar; un falso positivo con umbral 0,75 no debe perder datos.
- **Pickles como caché**: frágiles entre versiones y un riesgo de seguridad al cargarlos; nuestra BBDD ya es la fuente de verdad.
- **Scrapers codificados en Python por portal**: contrario a "config-driven".
- **NLTK/scikit-learn como dependencia obligatoria**: pesadas; como extra opcional.
- Código literal: MIT lo permitiría con aviso de licencia, pero solo describimos la técnica.
