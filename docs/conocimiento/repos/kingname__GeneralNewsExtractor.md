# kingname/GeneralNewsExtractor
> Python · **GPL-3.0** · ⭐ 3.802 · Último push 2026-04-21 · https://github.com/kingname/GeneralNewsExtractor

> ⚠️ Licencia GPL-3.0: **solo ideas, nada de código**. Integrarlo o copiar fragmentos obligaría a licenciar nuestro motor bajo GPL. Todo lo de abajo son descripciones de algoritmos, que reimplementaríamos desde cero.

## Qué es (2-3 líneas)
Extractor genérico de **noticias** (título, autor, fecha de publicación y cuerpo) sin reglas por sitio, pensado para prensa china. Implementa el algoritmo del artículo académico "基于文本及符号密度的网页正文提取方法" (extracción del cuerpo por densidad de texto y de signos de puntuación). Incluye un extractor experimental de listados y un "rescate" con LLM.

## Arquitectura en breve
- `gne/__init__.py::GeneralNewsExtractor.extract()`: corrige el HTML (`utils.py::fix_html`), extrae meta, título, fecha y autor **antes** de limpiar (para que los XPath del usuario sigan funcionando sobre el HTML original), elimina ruido (`remove_noise_node`, `pre_parse`) y calcula el cuerpo.
- Extractores por campo en `gne/extractor/`: `ContentExtractor.py`, `TitleExtractor.py`, `TimeExtractor.py`, `AuthorExtractor.py`, `MetaExtractor.py`, `ListExtractor.py`.
- Constantes y patrones en `gne/defaults.py` (regex de fechas, `meta` de fecha, etiquetas y clases "inútiles", palabras clave de peso).
- Configuración opcional por fichero `.gne` (YAML) en el directorio de trabajo con XPath por campo (`utils.py::read_config`).
- Dependencias: `lxml`, `PyYAML` (y `openai`, `bs4`, `json_repair` solo para `llm_crawler.py`).

## Técnicas que nos interesan

### 1. Puntuación de nodos por densidad de texto y de puntuación (cuerpo)
- **Qué hace**: recorre todos los nodos de `<body>` y les da una puntuación; el nodo con mayor puntuación es el cuerpo de la noticia.
- **Cómo** (`extractor/ContentExtractor.py`): para cada nodo calcula
  - **densidad de texto**: (caracteres de texto − caracteres dentro de enlaces) / (número de etiquetas descendientes − número de enlaces). Caso especial: si todas las etiquetas son enlaces pero el texto supera en más de 10 veces al texto enlazado (artículo tipo Wikipedia con palabras enlazadas), se ignora el número de enlaces en lugar de dar densidad 0 (`need_skip_ltgi`).
  - **densidad de signos**: (texto − texto enlazado) / (nº de signos de puntuación + 1), con un conjunto de signos chinos y occidentales (`calc_sbdi`).
  - **número de párrafos**: `<p>` descendientes + nodos de texto directos (`count_text_tag`).
  - **puntuación final**: densidad de texto × log10(párrafos + 2) × ln(densidad de signos) (`calc_new_score`).
  - **peso por clase**: si la clase del nodo contiene palabras como `content`, `article`, `post_body`…, se duplica su recuento de texto (`increase_tag_weight`, lista `HIGH_WEIGHT_ARRT_KEYWORD` en `defaults.py`).
- **Por qué importa**: es un algoritmo **corto, sin dependencias y explicable** para localizar el bloque principal. Sirve tanto para un `auto:main_text_lite` como para **sugerir el selector CSS del cuerpo** al crear un YAML nuevo (el nodo ganador → su ruta CSS).

### 2. Atajo por datos estructurados y XPath del usuario
- **Qué hace**: antes de puntuar, si existe un elemento `itemprop="articleBody"` se usa directamente; si el usuario da `body_xpath`, manda él.
- **Cómo**: inicio de `ContentExtractor.extract()`.
- **Por qué importa**: mismo principio que queremos: selector explícito > dato estructurado > heurística.

### 3. Limpieza previa del árbol
- **Qué hace**: elimina `script`, `style`, `nav`, `aside`, `header`, `footer`, `iframe`…; borra nodos vacíos; convierte `div`/`span` sin hijos en `p`; aplana `span`/`strong` dentro de `p`; elimina nodos cuya clase o id contenga palabras de ruido (`share`, `copyright`, `disclaimer`, `comment`, `recommend`…), comparando **por palabras** tras partir por espacios, guiones y guiones bajos para no borrar por subcadena (evita que `ad` elimine `header-adress`).
- **Cómo**: `utils.py::normalize_node()` y `_is_useless_node()`; listas `USELESS_TAG`, `USELESS_ATTR`, `TAGS_CAN_BE_REMOVE_IF_EMPTY` en `defaults.py`.
- **Por qué importa**: la comparación por palabras de clase/id es un detalle fino aplicable a cualquier poda nuestra.

### 4. Fecha de publicación en cascada
- **Qué hace**: prioridad fija de fuentes.
- **Cómo** (`extractor/TimeExtractor.py::extractor`): XPath del usuario → `meta` (lista `PUBLISH_TIME_META`: `article:published_time`, `og:release_date`, `rnews:datePublished`, `pubdate`, etc.) → JSON-LD (`datePublished`, luego `dateCreated`) → `<time>` con `datetime`/`data-published`/`data-timestamp` → regex sobre el texto (`DATETIME_PATTERN`, de más a menos precisa, con hora primero) + validación básica de mes/día (`_is_valid_date`).
- **Por qué importa**: confirma el mismo orden que htmldate, en versión mínima; es lo que implementaríamos como `auto:date_lite`. Nota: GNE devuelve la cadena cruda, sin normalizar; la normalización es nuestra (clean.py).

### 5. Título por coincidencia `<title>` ↔ `<h1..h5>`
- **Qué hace**: el `<title>` suele llevar el nombre del medio ("Noticia X - El Diario"), y algún `<h*>` lleva el titular limpio. Elige la **subcadena común más larga** entre `<title>` y cada `<h*>`; si es muy corta, cae a `og:title`/`twitter:title`, JSON-LD `headline`, `<title>` partido por `-_|`, o el primer `<h*>`.
- **Cómo**: `extractor/TitleExtractor.py::extract_by_htag_and_title()` y cadena en `extract()`.
- **Por qué importa**: heurística útil para limpiar títulos (quitar el sufijo del sitio) en un `auto:title_lite`.

### 6. Listados por "característica"
- **Qué hace**: dado un texto de ejemplo de un ítem, sube por los ancestros hasta encontrar un nivel donde la misma ruta relativa se repite más de 3 veces; esos son los ítems.
- **Cómo**: `extractor/ListExtractor.py`.
- **Por qué importa**: idea para un asistente que **proponga `item_selector`** a partir de un ejemplo que el usuario pega ("dame el selector de los bloques que contienen 'Piso en venta en Triana'").

## Qué aplicaríamos en nuestro motor
| # | Propuesta | Módulo afectado | Cambio YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | `auto:main_text_lite`: reimplementación propia (desde la descripción del paper, no del código) de la puntuación por densidad de texto + puntuación + nº de párrafos, sobre selectolax, sin dependencias. Alternativa ligera a trafilatura. | nuevo `scraper/parse/auto.py` | `cuerpo: { selector: "auto:main_text_lite", type: str }` | M | 2 |
| 2 | Asistente de selectores en `scraper inspect <url>`: sugiere el selector CSS del bloque principal (nodo ganador) y, dado un texto de ejemplo, un `item_selector` por repetición de estructura. Solo ayuda al autor del YAML; no se ejecuta en producción. | `cli.py`, `parse/auto.py` | — | M | 3 |
| 3 | `auto:date_lite` con la cascada user → meta → JSON-LD → `time` → regex (compartido con la ficha de trafilatura). | `parse/auto.py` | `publicado: { selector: ["auto:date_lite"], type: datetime }` | S | 2 |
| 4 | Poda de ruido por palabras de clase/id (no subcadenas) como paso opcional antes de extraer campos `::html` o texto principal. | `pipeline/clean.py` | `type: text_block` o `clean: [strip_noise]` | S | 3 |
| 5 | Limpieza de títulos: quitar sufijos de sitio con `<title>` vs `<h1>` / `og:site_name`. | `pipeline/clean.py` (nuevo `clean_title`) | `titulo: { selector: "title", type: title }` | S | 3 |

## Qué NO copiaríamos y por qué
- **Nada de código**: GPL-3.0. Las reimplementaciones deben partir del artículo académico y de esta descripción, no del fichero fuente.
- **Patrones de fecha y autor en chino** (`defaults.py::AUTHOR_PATTERN_STR`, fechas con 年月日, 时分): no aplican; nuestras fechas españolas ya están en `clean.py`.
- **`use_visiable_info`** (coordenadas y visibilidad inyectadas desde un navegador): exige renderizar y anotar el DOM; complejidad alta para poco beneficio.
- **`llm_crawler.py`**: usa el SDK de OpenAI (el usuario no quiere ChatGPT) y un User-Agent de navegador falsificado; además el hueco de "extracción con IA" está fuera de alcance de F1–F4 según PLAN.md.
- **Configuración global `.gne` en el directorio actual**: estado implícito; lo nuestro vive en el YAML del sitio.
- **Devolver fechas como texto crudo**: nosotros tipamos y normalizamos siempre.
