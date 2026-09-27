# unclecode/crawl4ai
> Python · Apache-2.0 · ⭐ ~84.300 · Último push 2026-09-25 · https://github.com/unclecode/crawl4ai

## Qué es (2-3 líneas)
Crawler asíncrono basado en navegador (Playwright) pensado para alimentar LLMs y pipelines RAG: descarga, limpia el HTML, genera Markdown "limpio" y extrae datos estructurados con estrategias intercambiables (CSS/XPath sin LLM, regex o LLM). Incluye caché en SQLite, crawling profundo con filtros y puntuación de URLs, y un servidor Docker. Proyecto muy activo y muy grande (~40 MB de repo).

## Arquitectura en breve
- `crawl4ai/async_webcrawler.py` — `AsyncWebCrawler.arun()`: orquesta caché → descarga (`async_crawler_strategy.py`, Playwright o HTTP) → limpieza (`content_scraping_strategy.py`) → Markdown (`markdown_generation_strategy.py`) → extracción (`extraction_strategy.py`).
- Configuración por objetos: `BrowserConfig` y `CrawlerRunConfig` (`async_configs.py`), cada uno con su estrategia enchufable (patrón Strategy en todo el código).
- Persistencia de caché: `async_database.py` (tabla `crawled_data` con url como PK: html, cleaned_html, markdown, extracted_content, cabeceras…).
- Crawling profundo: `deep_crawling/` (BFS, DFS, Best-First, filtros y scorers).
- LLM: todo pasa por `litellm` (`utils.py`, `perform_completion_with_backoff` / `aperform_completion_with_backoff`), así que el proveedor es un string tipo `anthropic/<modelo>`: **agnóstico, sirve Claude**.

## Técnicas que nos interesan

### 1. Esquema declarativo CSS/XPath (`JsonCssExtractionStrategy`)
- **Qué hace**: extrae una lista de registros a partir de un esquema JSON con `baseSelector` (bloque de cada registro) y `fields` (nombre, selector, tipo). Es exactamente nuestro `list.item_selector` + `fields`.
- **Cómo**: clase base `JsonElementExtractionStrategy` en `crawl4ai/extraction_strategy.py` (líneas ~1043-1340) con subclases por motor: `JsonCssExtractionStrategy` (BeautifulSoup), `JsonLxmlExtractionStrategy`, `JsonXPathExtractionStrategy`. Detalles útiles:
  - El `type` de un campo puede ser **una lista de pasos encadenados** (p. ej. primero `attribute`, luego `regex`), no un único tipo.
  - Tipos `nested`, `list` y `nested_list` para subestructuras (p. ej. lotes dentro de una subasta).
  - `baseFields`: atributos del propio bloque (p. ej. `data-id`).
  - `source: "+ selector"`: el campo vive en el **hermano siguiente** del bloque, no dentro (caso Hacker News, tablas con filas partidas).
  - `computed`: campos calculados con una función Python; desactivaron `expression` (eval) por seguridad.
  - `default` por campo cuando el selector no encuentra nada.
- **Por qué importa**: valida nuestro diseño (somos casi isomorfos) y nos da ideas baratas: selector de hermano, campos anidados y cadenas de pasos.

### 2. Generación del esquema con LLM **una sola vez** y reutilización sin LLM (`generate_schema`)
- **Qué hace**: dado HTML (o una o varias URLs de muestra) y una consulta en lenguaje natural o un JSON de ejemplo, pide al LLM un esquema CSS/XPath; después ese esquema se guarda y se usa indefinidamente sin coste de LLM.
- **Cómo** (`extraction_strategy.py`, `agenerate_schema`, ~1692-1990):
  1. Reduce el HTML antes de enviarlo: `utils.preprocess_html_for_schema` quita `<head>`, scripts/estilos, trunca textos y atributos largos y limita el tamaño total.
  2. Si hay varias URLs de muestra, las concatena con un delimitador para que el LLM vea variantes de la misma plantilla.
  3. Si solo hay consulta, hace una llamada previa para **inferir el JSON objetivo** y sacar la lista de campos esperados (`_infer_target_json`, `_extract_expected_fields`).
  4. **Bucle de validación**: ejecuta el esquema propuesto sobre el HTML original (`_validate_schema`) y mide elementos base encontrados, cobertura de campos y campos siempre vacíos. Si falla, construye un mensaje de feedback estructurado (`_build_feedback_message`: selector base con 0 coincidencias + árbol de nivel superior, campos vacíos, esquema repetido) y reintenta hasta `max_refinements` (3).
  5. Contabiliza tokens en un acumulador `TokenUsage`.
- **Por qué importa**: es la respuesta correcta a la decisión pendiente del PLAN §7 ("extractor por LLM"): el LLM **escribe el YAML**, no extrae en cada ejecución. Coste casi nulo, resultado determinista y auditable, y encaja con nuestro `dry-run` (que ya calcula campos vacíos, igual que su validador).

### 3. `LLMExtractionStrategy` + chunking
- **Qué hace**: extracción directa por LLM de cada página (esquema Pydantic o "bloques" libres), troceando el contenido.
- **Cómo**: `extraction_strategy.py` (~533-1040). Entrada configurable (`markdown`, `html`, `fit_markdown`); trocea por umbral de tokens con solapamiento (`merge_chunks`, `chunk_token_threshold`, `overlap_rate`, `word_token_rate`) y procesa trozos en paralelo con un pool de 4 hilos (secuencial con pausa para algunos proveedores). Estrategias de troceo en `chunking_strategy.py`: regex por párrafos, frases (NLTK), ventana fija, ventana deslizante y ventana con solapamiento.
- **Por qué importa**: útil solo para páginas sin plantilla estable (texto libre de un anuncio). Nos enseña que conviene alimentar al LLM con **Markdown filtrado**, no HTML, y que hay que medir tokens.

### 4. Caché con modos y validación de frescura
- **Qué hace**: `CacheMode` (`cache_context.py`) con cinco modos: ENABLED, DISABLED, READ_ONLY, WRITE_ONLY, BYPASS; `CacheContext` decide `should_read`/`should_write` por URL.
- **Frescura** (`cache_validator.py`, `CacheValidator`): antes de reutilizar la caché hace una petición ligera con `If-None-Match` / `If-Modified-Since` (304 = fresco); si el servidor no soporta condicionales, descarga solo el `<head>` y compara una **huella** de metadatos (`compute_head_fingerprint` en `utils.py`). Resultados FRESH / STALE / UNKNOWN / ERROR (en ERROR usa la caché como respaldo).
- **Por qué importa**: nuestro PLAN prevé `fetch/cache.py` pero no existe. Los modos READ_ONLY (re-parsear sin tocar la red, ideal para ajustar selectores) y las peticiones condicionales reducen carga sobre el sitio.

### 5. Generación de Markdown y filtros de contenido
- **Qué hace**: `DefaultMarkdownGenerator` (`markdown_generation_strategy.py`) convierte HTML a Markdown (fork propio de html2text en `crawl4ai/html2text/`), transforma enlaces en citas numeradas con lista de referencias al final, y si hay filtro produce además `fit_markdown` (solo lo relevante).
- Filtros en `content_filter_strategy.py`: `PruningContentFilter` (puntúa nodos por densidad de texto, densidad de enlaces, peso de clases/ids tipo "nav/footer/ad" y poda los que no llegan a un umbral; ahora hay versión lxml ~10× más rápida en `content_filter_strategy_lxml.py`), `BM25ContentFilter` (relevancia frente a una consulta) y `LLMContentFilter`.
- **Por qué importa**: un campo de tipo "texto largo como Markdown" es más útil en Excel/LLM que HTML crudo; y la poda heurística es la base para darle a un LLM poco texto.

### 6. Deep crawling con filtros y scorers
- **Qué hace**: recorre enlaces a partir de una URL con BFS/DFS/Best-First, límite de profundidad y de páginas, filtros encadenados y puntuación.
- **Cómo**: `deep_crawling/bfs_strategy.py`, `bff_strategy.py`, `dfs_strategy.py`. `filters.py`: `FilterChain` con `URLPatternFilter` (glob/regex), `DomainFilter`, `ContentTypeFilter`, `ContentRelevanceFilter`, `SEOFilter`, con estadísticas de aceptadas/rechazadas. `scorers.py`: `KeywordRelevanceScorer`, `PathDepthScorer`, `FreshnessScorer` (fechas en la URL), `CompositeScorer` con pesos. Soporta **reanudación**: `export_state` / `resume_state` y callback `on_state_change` para persistir visitados, profundidades y cola.
- **Por qué importa**: nuestro motor es "listado → detalle", sin descubrimiento libre. Lo aprovechable es la idea de **filtros de URL declarativos con contadores** y el **estado reanudable** (el PLAN promete "si se corta, retoma" y aún no lo hacemos).

## Qué aplicaríamos en nuestro motor
| # | Propuesta | Módulo afectado | Cambio en YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | Comando `scraper suggest-selectors <url> [--url otra] --campos "titulo, precio, fecha"`: descarga 1-3 páginas con nuestro fetcher, reduce el HTML (sin head/scripts, textos truncados), pide a Claude un bloque `list:`/`detail:` en nuestro formato YAML, lo valida con la misma lógica del `dry-run` (items encontrados, % de campos vacíos) y reintenta con feedback hasta 3 veces. Resultado: `sites/<nombre>.yaml` para revisión humana. **LLM solo en diseño, nunca en ejecución.** Proveedor por variable de entorno (`LLM_PROVIDER=anthropic`), dependencia opcional `pip install -e .[llm]`. | nuevo `scraper/llm/schema_suggest.py`, `cli.py`, reutiliza `engine.RunReport.empty_fields` | ninguno (genera YAML) | M | 1 |
| 2 | Caché HTTP en disco/SQLite con modos `enabled/read_only/write_only/bypass` (flag `--cache`), guardando ETag y Last-Modified y enviando peticiones condicionales. READ_ONLY permite iterar selectores sin tocar la red. | `fetch/cache.py` (previsto en PLAN), `fetch/http.py`, `storage/models.py` (tabla `http_cache` o ficheros) | `fetch.cache: {mode: enabled, ttl_hours: 24}` | M | 1 |
| 3 | Tipos de campo encadenados y extras del esquema: `source: "+ tr"` (hermano siguiente), `attr` + `regex` en cadena, `type: nested_list` para sublistas (p. ej. lotes). | `parse/selectors.py`, `pipeline/extract.py`, `config.py` | nuevas claves opcionales en `FieldSpec` | S-M | 2 |
| 4 | Tipo de campo `markdown` (HTML → Markdown con enlaces absolutos) para textos largos de detalle. | `pipeline/clean.py` (dep. opcional `markdownify` o similar) | `type: markdown` | S | 2 |
| 5 | Extractor LLM **opcional** por sitio para páginas sin plantilla: entrada en Markdown podado, salida validada contra los `fields` del YAML (Pydantic), con caché por hash de contenido para no pagar dos veces la misma página y contador de tokens en `runs`. | `parse/llm_extract.py` (hueco previsto) | `extract: {mode: llm, instructions: "..."}` | M-L | 3 |
| 6 | Filtros de URL declarativos (include/exclude por patrón) con contadores en el informe, aplicables a `detail_url` y a enlaces de paginación. | `engine.py`, `config.py` | `list.detail_filter: {include: [...], exclude: [...]}` | S | 3 |
| 7 | Estado reanudable: persistir cola/URLs visitadas del run y permitir `scraper run --resume`. | `engine.py`, `storage/repo.py` (tabla `pages` ya sirve de base) | — | M | 3 |

## Qué NO copiaríamos y por qué
- **Modo navegador como base**: crawl4ai asume Playwright; nosotros httpx por defecto y navegador solo si el sitio lo exige (F3). Más barato y más cortés.
- **Modo "stealth", perfiles de navegador, rotación de proxies, `antibot_detector.py`, `user_agent_generator.py`**: fuera de nuestra política (PLAN §2.4 y §7 anti-bot). Ignorado a propósito.
- **Extracción por LLM en cada ejecución como norma**: caro, no determinista y difícil de auditar; solo como último recurso.
- **`CosineStrategy` / clustering por embeddings, `adaptive_crawler.py`, `BestFirst` con scorers**: sobredimensionado para "listado → detalle" de datos estructurados.
- **Dependencia de `litellm`**: arrastra muchas dependencias; para una sola llamada basta un cliente fino con interfaz propia (Anthropic SDK por defecto) que permita cambiar de proveedor.
- Código literal: licencia Apache-2.0 lo permitiría con atribución, pero describimos ideas y reimplementamos.
