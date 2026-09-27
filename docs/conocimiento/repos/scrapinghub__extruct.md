# scrapinghub/extruct
> Python · BSD-3-Clause · ⭐ 973 · Último push 2026-09-24 · https://github.com/scrapinghub/extruct

## Qué es (2-3 líneas)
Librería de Zyte (antes Scrapinghub) que extrae de un HTML todos los **datos estructurados embebidos**: JSON-LD, microdata (W3C), OpenGraph, RDFa, microformatos y Dublin Core. Devuelve listas de diccionarios por sintaxis y, opcionalmente, en un formato "uniforme" parecido a JSON-LD. Es la base de recipe-scrapers y de muchos pipelines de e-commerce.

## Arquitectura en breve
- Punto de entrada `extruct/_extruct.py::extract(html, base_url, syntaxes=[...], errors='strict'|'log'|'ignore', uniform=False)`.
- Un extractor por sintaxis, todos sobre **lxml**: `jsonld.py::JsonLdExtractor`, `w3cmicrodata.py::LxmlMicrodataExtractor`, `opengraph.py::OpenGraphExtractor`, `rdfa.py::RDFaExtractor` (vía `pyRdfa3` + `rdflib`), `microformat.py` (vía `mf2py`), `dublincore.py`.
- `uniform.py` normaliza la salida de microdata/microformat/OpenGraph/DC a dicts con `@context` y `@type`.
- Dependencias: `lxml`, `lxml-html-clean`, `rdflib`, `pyrdfa3`, `mf2py`, `w3lib`, `html-text`, `jstyleson`. Las de RDFa y microformatos son las pesadas.
- Tests con muestras reales y del W3C en `tests/samples/` (schema.org, songkick, wikipedia, websites, casos inválidos).

## Técnicas que nos interesan

### 1. JSON-LD tolerante
- **Qué hace**: lee cada `<script type="application/ld+json">`, admite que sea objeto o lista, y no revienta con JSON "sucio".
- **Cómo**: `jsonld.py::_extract_items()` intenta `json.loads(strict=False)`; si falla, quita comentarios HTML/JS de línea (`HTML_OR_JS_COMMENTLINE`) y reintenta con `jstyleson` (JSON con comentarios y comas finales). Aplana listas en items. **No** resuelve `@graph` ni referencias `@id`: eso lo deja al consumidor (recipe-scrapers lo hace en `_schemaorg.py::_find_entity()`).
- **Por qué importa**: es el 80 % del valor para nosotros y cabe en ~40 líneas sin dependencias; el resto (buscar el tipo dentro de `@graph`, resolver `@id`) lo tendríamos que añadir nosotros.

### 2. Microdata según la especificación W3C
- **Qué hace**: construye items anidados a partir de `itemscope/itemtype/itemprop`, incluido `itemref` (propiedades definidas fuera del bloque).
- **Cómo**: `w3cmicrodata.py::_extract_item()` y `_extract_property_value()`. La regla del valor según etiqueta es la clave: `meta`→`content`; `img/audio/video/iframe/source`→`src` absolutizado; `a/area/link`→`href` absolutizado; `object`→`data`; `data/meter`→`value`; `time`→`datetime`; si hay atributo `content`, ese; si no, el texto limpio del nodo (`html_text`). Opción `add_html_node` para devolver el nodo y poder seguir con CSS desde él.
- **Por qué importa**: muchos catálogos (PrestaShop, Magento antiguos, portales inmobiliarios) solo tienen microdata. Esta tabla de reglas es la que deberíamos implementar para un prefijo `microdata:`.

### 3. OpenGraph con espacios de nombres
- **Qué hace**: recoge `meta[property][content]` del `<head>`, reconoce los prefijos `og:`, `article:`, `product:`, `music:`, `video:`, `book:`, `profile:` y los declarados en `prefix=""`.
- **Cómo**: `opengraph.py::extract_items()`; la forma uniforme (`uniform.py::_uopengraph()`) aplana y se queda con el primer valor no vacío o, con `with_og_array=True`, con la lista de valores (útil para varias `og:image`).
- **Por qué importa**: OpenGraph es casi universal y da título, imagen, URL canónica, precio (`product:price:amount`) y fecha (`article:published_time`) a coste cero.

### 4. Modo de errores configurable
- **Qué hace**: `errors='strict'|'log'|'ignore'` por sintaxis: un JSON-LD roto no impide leer el OpenGraph.
- **Cómo**: bucle de `processors` en `_extruct.py::extract()` con try/except por sintaxis.
- **Por qué importa**: encaja con nuestra filosofía de "registros erróneos no rompen la ejecución y quedan auditados" (tabla `errors`).

### 5. Salida uniforme
- **Qué hace**: convierte microdata/OG a dicts con `@type` y propiedades planas, para tratarlos igual que JSON-LD.
- **Cómo**: `uniform.py::flatten_dict()`, `_umicrodata_microformat()`.
- **Por qué importa**: permite una **sola sintaxis de ruta** en YAML (`Tipo.propiedad.subpropiedad`) sea cual sea la fuente.

## Qué aplicaríamos en nuestro motor
| # | Propuesta | Módulo afectado | Cambio YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | Módulo `scraper/parse/structured.py` **sin dependencias**: extrae JSON-LD (json + limpieza de comentarios; aplanado de listas y `@graph`; índice por `@id`), OpenGraph/meta y microdata básica (reglas de valor por etiqueta, con selectolax). Se calcula una vez por página y se cachea. | nuevo `parse/structured.py`; `parse/selectors.py` (despacho por prefijo) | ver sintaxis abajo | M | 1 |
| 2 | Prefijos de selector: `jsonld:<Tipo>.<ruta>`, `microdata:<Tipo>.<ruta>`, `meta:<nombre o property>`. Ruta con puntos, índices `[0]` y comodín `[*]` para listas. Tipo sin distinguir mayúsculas y aceptando subtipos declarados (`Product` casa con `["Product","Car"]`). Resolución automática de `{"@id": ...}` contra el índice. | `parse/selectors.py`, `pipeline/extract.py` | `precio: { selector: "jsonld:Product.offers[0].price", type: money }` · `imagen: { selector: "meta:og:image", type: url }` · `marca: { selector: "microdata:Product.brand.name" }` | M | 1 |
| 3 | Fallback declarativo: `selector` acepta lista; gana el primer valor no vacío tras limpiar. Se registra en `runs`/log qué fuente dio el valor (útil para detectar cuándo un sitio quita su JSON-LD). | `pipeline/extract.py`, `config.py` | `selector: ["jsonld:Product.name", "microdata:Product.name", "h1.producto"]` | S | 1 |
| 4 | Items desde datos estructurados: en `list`, permitir `item_selector: "jsonld:ItemList.itemListElement[*]"` para listados que publican su propio `ItemList` (catálogos, rankings), con `fields` relativos al objeto JSON. | `engine.py`, `pipeline/extract.py` | `list: { item_selector: "jsonld:ItemList.itemListElement[*]", fields: { url: { selector: "json:url" } } }` | M | 2 |
| 5 | Comando `scraper inspect <url o fichero>`: vuelca los datos estructurados encontrados (tipos y rutas) para ayudar a escribir el YAML. | `cli.py` | — | S | 2 |
| 6 | extruct como **dependencia opcional** (`[structured-full]`) solo si un cliente necesita RDFa o microformatos; nuestro módulo propio cubre JSON-LD/OG/microdata. | `parse/structured.py` (si está instalado, delega) | `structured: { engine: extruct }` | S | 3 |

## Qué NO copiaríamos y por qué
- **RDFa y microformatos por defecto**: arrastran `rdflib`, `pyRdfa3` y `mf2py`, pesados y lentos, para sintaxis poco frecuentes en webs españolas de negocio. Solo como extra opcional.
- **Parseo con lxml en el núcleo**: nosotros usamos selectolax; mantener dos parsers en el camino caliente complica y ralentiza. Las reglas de microdata se reimplementan fácilmente sobre selectolax.
- **Modo `strict` por defecto**: para scraping preferimos `log` (seguir y auditar).
- Licencia BSD-3-Clause: permisiva, pero igualmente describimos las reglas con nuestras palabras en lugar de copiar código.
