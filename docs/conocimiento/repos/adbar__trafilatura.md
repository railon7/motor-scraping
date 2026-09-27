# adbar/trafilatura
> Python · Apache-2.0 · ⭐ 6.868 · Último push 2026-09-25 · https://github.com/adbar/trafilatura

## Qué es (2-3 líneas)
Librería y CLI para sacar de una página web el **texto principal** (sin menús, pies, barras laterales ni comentarios) y sus **metadatos** (título, autor, fecha, sitio, categorías, etiquetas, licencia). Es la referencia en benchmarks académicos de extracción de texto. También trae descarga, sitemaps, feeds y un pequeño spider, que a nosotros no nos interesan.

## Arquitectura en breve
- Todo gira sobre **lxml** y XPath (`trafilatura/xpaths.py`: listas de expresiones precompiladas).
- `trafilatura/core.py` → `bare_extraction()` / `extract()` orquestan: carga HTML → metadatos (`metadata.py`) → limpieza del árbol (`htmlprocessing.py`) → **cascada de extractores** (`trafilatura_sequence()`) → salida (txt, markdown, json, xml/TEI, html).
- Fecha de publicación: se delega en su librería hermana **htmldate** (`find_date()`), dependencia obligatoria.
- Respaldo: `readability_lxml.py` (port interno de readability), `external.py` (jusText) y `baseline.py` (último recurso).
- Dependencias fijas: `lxml`, `htmldate` (que arrastra `dateparser` y `python-dateutil`), `justext`, `courlan`, `charset_normalizer`, `urllib3`, `certifi`. Extras opcionales (`[all]`): `py3langid`, `faust-cchardet`, `brotli`, `pycurl`.
- Tests con HTML reales y un banco de evaluación (`tests/evaluate.py`, `tests/evaldata.json`) que compara contra otros extractores y tiene "gate" de regresión (`tests/eval_gate.py`).

## Técnicas que nos interesan

### 1. Cascada de extractores con "quien da más gana" (texto principal)
- **Qué hace**: no confía en un único algoritmo. Ejecuta el propio; si el resultado es pobre, lo compara con readability y jusText; si sigue siendo corto, prueba un `baseline`; si cubre poca parte de la página, reintenta en modo "recall".
- **Cómo**: `core.py::trafilatura_sequence()` documenta los 4 pasos. El extractor propio es `main_extractor.py::_extract()`: recorre `BODY_XPATH` (de más específico a más genérico: ids/clases tipo `article-body`, `post-content`, `story-body`, luego `<article>`, luego `<main>`...), toma el primer subárbol que existe, lo poda (`prune_unwanted_sections()`) y se queda con él en cuanto tiene más de un elemento con contenido. Si el texto queda por debajo de `min_extracted_size`, `recover_wild_text()` rescata `<p>` sueltos. La decisión contra readability está en `external.py::_prefer_readability()` con reglas de longitud (p. ej. el propio gana si es más del doble; readability gana si el propio está vacío o es la mitad y no empieza por `{`, que delataría JSON crudo).
- **Por qué importa**: patrón aplicable a nuestros campos: varias fuentes candidatas y un criterio explícito para elegir, en lugar de "primer selector que casa".

### 2. Poda por densidad de enlaces
- **Qué hace**: elimina bloques donde casi todo el texto es enlace (menús, "noticias relacionadas", nubes de tags).
- **Cómo**: `htmlprocessing.py::link_density_test()` calcula, por elemento, longitud de texto en enlaces frente a longitud total; umbrales distintos para `<p>` (30–60 caracteres) y otros bloques (100–300); si los enlaces superan ~80 % del texto o el 80 % de los enlaces son cortos, se considera "boilerplate". `delete_by_link_density()` lo aplica a listas, tablas (`link_density_test_tables()`) y párrafos, con excepción para párrafos dentro de celdas/ítems.
- **Por qué importa**: heurística barata y robusta que podríamos usar para un tipo `main_text` propio sin dependencias, o para limpiar un campo `::html`.

### 3. Metadatos por capas con prioridad (OG → meta → JSON-LD → HTML)
- **Qué hace**: rellena cada metadato desde la fuente más fiable disponible y solo cae a la siguiente si falta.
- **Cómo**: `metadata.py::extract_metadata()`: 1) `extract_opengraph()` (og:title, og:url, og:site_name, og:image, og:type…), 2) `examine_meta()` recorre `<meta name|property|itemprop>` (author, description, article:tag, twitter:*), 3) `extract_meta_json()` parsea cada `<script type="application/ld+json">` y `json_metadata.py::process_parent()` recorre los objetos (incluido `@graph`) quedándose con `Article/NewsArticle/BlogPosting` para autor/título/sección y con `Organization/WebSite` para el nombre del sitio; **JSON-LD sobrescribe** lo anterior para autor y sitio. 4) Solo si sigue faltando, XPath sobre el HTML (`extract_title()`, `extract_author()`, `extract_catstags()`). Tolera JSON-LD roto: `extract_json_parse_error()` intenta regex sobre el texto si `json.loads` falla, y `json.loads(..., strict=False)` para caracteres de control.
- **Por qué importa**: es exactamente el "orden de fuentes" que queremos declarar en YAML. Y la tolerancia a JSON-LD mal formado es imprescindible en webs españolas con plugins SEO de WordPress.

### 4. Fecha de publicación con htmldate (cascada + validación de rango)
- **Qué hace**: busca la fecha de publicación original (no la de modificación) en un orden fijo y valida que sea plausible.
- **Cómo** (htmldate 1.10, `htmldate/core.py::find_date()`): URL (patrón `/2024/03/12/`) → cabecera `<meta>` (lista `DATE_ATTRIBUTES`: `article:published_time`, `citation_date`, `dc.date`…; separa `PROPERTY_MODIFIED`) → JSON-LD (`datePublished`/`dateModified`) → `<abbr>` → elementos con clases/ids de fecha → `<title>`/`<h1>` → `<time datetime>` → timestamps en el HTML → `<img>` → patrones textuales → búsqueda extensiva en todo el texto, eligiendo entre candidatos por frecuencia (`select_candidate()`). Toda fecha se valida entre `min_date` y `max_date` (por defecto, hoy: nada de fechas futuras). Parser: primero regex propias y `dateutil`; `dateparser` (lento, multilingüe) solo como último recurso (`extractors.py::external_date_parser()`). Trafilatura lo llama con `original_date=True` (`settings.py::set_date_params()`).
- **Por qué importa**: nos da el orden de fuentes para un campo "fecha de publicación" y la idea de **validar rango** (rechazar fechas imposibles o futuras), que hoy `clean.py::clean_date()` no hace.

### 5. Modos precisión / recall / rápido
- **Qué hace**: el usuario elige entre menos texto pero seguro (`favor_precision`), más texto (`favor_recall`) o rápido (`fast`, salta readability/jusText).
- **Cómo**: `core.py::bare_extraction()` → `settings.py::Extractor`; los umbrales de densidad y poda cambian según `focus`.
- **Por qué importa**: rendimiento. El modo por defecto puede ejecutar 3–4 extractores por página; con `fast` es claramente más ligero. Para scraping masivo convendría `fast` por defecto.

### 6. Deduplicación aproximada de contenido
- **Qué hace**: detecta textos casi iguales (simhash) y párrafos repetidos.
- **Cómo**: `deduplication.py::Simhash`, `content_fingerprint()`, `LRUCache` + `duplicate_test()`.
- **Por qué importa**: nuestro `pipeline/dedupe.py` usa clave natural + hash exacto; un fingerprint aproximado del texto principal ayudaría a detectar la misma noticia publicada en dos URLs.

## Qué aplicaríamos en nuestro motor
| # | Propuesta | Módulo afectado | Cambio YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | Selectores "virtuales" `auto:` que delegan en trafilatura: `auto:main_text`, `auto:main_html`, `auto:title`, `auto:author`, `auto:date`, `auto:sitename`, `auto:tags`. Se calcula una vez por página (caché por documento) y se sirve a los campos. **Dependencia opcional** (`pip install motor-scraping[texto]`); si no está instalada, error claro al validar el YAML. | nuevo `scraper/parse/auto.py`; `parse/selectors.py` (despacho por prefijo); `config.py` (validación) | `cuerpo: { selector: "auto:main_text", type: str }` · `publicado: { selector: "auto:date", type: date }` | M | 1 |
| 2 | Lista de selectores con fallback en cualquier campo (el primero no vacío gana), imitando la cascada de metadatos: `jsonld:` → `meta:` → CSS. | `pipeline/extract.py`, `config.py` (`selector: str \| list[str]`) | `titulo: { selector: ["jsonld:Article.headline", "meta:og:title", "h1"] }` | S | 1 |
| 3 | Validación de rango de fechas: `min_date` / `max_date` (por defecto, no aceptar futuras salvo campos marcados como `future: true`, p. ej. subastas). | `pipeline/clean.py::clean_date/clean_datetime`, `config.py::FieldSpec` | `fecha: { selector: "...", type: date, max_date: today }` | S | 2 |
| 4 | Orden de fuentes para fecha de publicación sin dependencias (URL → `meta` article:published_time → JSON-LD datePublished → `time[datetime]`) como preset `auto:date_lite`, útil cuando no queramos instalar trafilatura/htmldate. | `parse/auto.py` | `selector: "auto:date_lite"` | S | 2 |
| 5 | Heurística propia de densidad de enlaces para limpiar campos `::html` o para un `auto:main_text_lite` sin lxml. | `pipeline/clean.py` (nuevo `clean_boilerplate`) | `type: text_block` | M | 3 |
| 3b | Fechas relativas y otros idiomas, siguiendo la idea de htmldate de "regex propias primero, parser pesado al final": reglas propias para `hoy`, `ayer`, `anteayer`, `hace N minutos/horas/días/semanas/meses` (y en inglés `N days ago`, `yesterday`) calculadas contra la **fecha de descarga** de la página (no contra `now()` al exportar); `dateparser` solo como dependencia opcional (`[fechas]`) para idiomas que no cubrimos (catalán, francés, portugués…), activable con `lang:`. | `pipeline/clean.py::clean_date/clean_datetime` (recibir fecha de referencia), `pipeline/extract.py` | `publicado: { selector: ".fecha", type: datetime, lang: [es, ca] }` | S (reglas) / S (opcional dateparser) | 1 |
| 6 | Fingerprint aproximado (simhash) del texto principal para dedupe entre URLs. | `pipeline/dedupe.py` | `dedupe: { fuzzy_field: cuerpo }` | M | 3 |

Notas de integración: trafilatura trabaja con lxml, nosotros con selectolax. Se le pasa el HTML en bruto (string), así que no hay conflicto; el coste es parsear dos veces la página, aceptable porque solo ocurre si algún campo usa `auto:`. Dependencias transitivas notables: `dateparser` (pesada, ~varios MB de datos de idiomas) llega vía htmldate; por eso debe ser extra opcional.

## Qué NO copiaríamos y por qué
- **Descargas, spider, sitemaps y feeds** (`downloads.py`, `spider.py`, `sitemaps.py`, `feeds.py`): ya tenemos fetcher con robots, rate-limit y paginación; duplicaría responsabilidades.
- **Reescribir su algoritmo de texto principal**: son miles de líneas afinadas con benchmarks (`xpaths.py`, `main_extractor.py`); reimplementarlo sería caro y peor. Mejor usarlo como dependencia opcional.
- **Salida XML/TEI** (`xml.py`): orientada a lingüística de corpus, sin uso para nuestros clientes.
- **Detección de idioma** (`py3langid`): no la necesitamos de inicio.
- Licencia Apache-2.0: compatible si la usamos como dependencia; aun así no copiamos código, solo ideas y llamadas a su API pública (`extract`, `bare_extraction`, `extract_metadata`).
