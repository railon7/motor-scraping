# hhursev/recipe-scrapers
> Python · MIT · ⭐ 2.237 · Último push 2026-09-09 · https://github.com/hhursev/recipe-scrapers

## Qué es (2-3 líneas)
Librería que extrae recetas (título, ingredientes, pasos, tiempos, raciones, imagen, valoraciones, nutrición…) de **~640 webs de cocina** con una API común. Su truco: la mayoría de sitios publican `schema.org/Recipe`, así que cada scraper por sitio solo escribe lo que el schema no da bien. Es el mejor ejemplo público de "cientos de sitios sobre una base común".

## Arquitectura en breve
- `recipe_scrapers/_abstract.py::AbstractScraper`: clase base con un método por campo (`title()`, `ingredients()`, `total_time()`…). Por defecto lanzan `NotImplementedError`. Al construirse, parsea el HTML con BeautifulSoup y crea `self.schema` (`_schemaorg.py::SchemaOrg`, sobre extruct con `json-ld` + `microdata`) y `self.opengraph` (`_opengraph.py`).
- **Plugins** (`recipe_scrapers/plugins/`) que envuelven cada método como decoradores, configurados en `settings/default.py::PLUGINS` (orden = de exterior a interior). El clave es `schemaorg_fill.py::SchemaOrgFillPlugin`: si el método del sitio no está implementado (o lanza `FillPluginException`), devuelve el valor del schema. `opengraph_fill.py` hace lo mismo para `site_name` e `image`. Otros: `normalize_string`, `html_tags_stripper`, `best_image`, `static_values`, `exception_handling`.
- Un fichero por sitio (`recipe_scrapers/<sitio>.py`), una clase con `host()` y solo los métodos que el schema no resuelve. De 640 módulos, **281 solo definen `host()`** (confían al 100 % en schema.org/OG); unos 300 usan `self.soup` para algún campo.
- Registro: diccionario `SCRAPERS = {Clase.host(): Clase, ...}` en `recipe_scrapers/__init__.py`. `scrape_html(html, org_url, supported_only=...)` busca por host; si no hay, con `supported_only=False` usa `_factory.py::SchemaScraperFactory` (scraper genérico que solo lee schema) y falla con `NoSchemaFoundInWildMode` si no hay Recipe.
- Mixins para familias de sitios que comparten plugin de WordPress: `_wprm.py::WPRMMixin` (WP Recipe Maker) y agrupación de ingredientes con selectores configurables (`_grouping_utils.py::group_ingredients()`).
- Dependencias mínimas: `beautifulsoup4`, `extruct`, `isodate`; `requests` opcional.

## Técnicas que nos interesan

### 1. Schema.org primero, código por sitio solo para excepciones
- **Qué hace**: el scraper genérico cubre la mayoría de campos; cada sitio sobrescribe lo que falta o está mal.
- **Cómo**: `SchemaOrgFillPlugin.run()` envuelve cada método de la lista `run_on_methods`; captura `NotImplementedError`/`FillPluginException` y llama al método homónimo de `self.schema`. El sitio puede incluso invocar `self.schema.x()` y retocar el resultado (80 sitios lo hacen).
- **Por qué importa**: invierte el coste de mantenimiento: un sitio nuevo con buen schema es una línea. En nuestro motor el equivalente es "campos por defecto desde datos estructurados + YAML solo con las excepciones".

### 2. Búsqueda del objeto correcto dentro del JSON-LD
- **Qué hace**: encuentra el `Recipe` aunque venga dentro de `@graph`, como `mainEntity` de un `WebPage`, con `@type` en lista, o duplicado en JSON-LD y microdata.
- **Cómo**: `_schemaorg.py::_find_entity()` y `_contains_schematype()` (comparación sin mayúsculas sobre el tipo o lista de tipos). Guarda aparte `Person` por `@id`/`url` y `AggregateRating` por `@id` para **resolver referencias** cuando el Recipe solo trae `{"@id": ...}`. Si el mismo recipe (mismo `@id` o `name`) aparece en dos sintaxis, fusiona propiedades sin pisar las ya presentes.
- **Por qué importa**: es la lógica que nos falta para que `jsonld:Product.brand.name` funcione en webs reales (Yoast, RankMath y WooCommerce usan `@graph` + `@id`).

### 3. Normalizadores de dominio
- **Qué hace**: convierte formatos heterogéneos a valores comparables.
- **Cómo**: `_utils.py::get_minutes()` acepta entero, duración ISO 8601 (`PT1H30M`, vía `isodate`), rangos ("12-15 minutes", "12 to 15") y texto con horas/minutos/días/segundos y fracciones (`_extract_fractional()`: "1½ hours"). `get_yields()` distingue raciones, unidades, docenas y tandas. `normalize_string()` limpia entidades y espacios. `csv_to_tags()` para keywords.
- **Por qué importa**: nos falta un tipo `duration` (ISO 8601 aparece en schema.org: `duration`, `prepTime`, `timeRequired`, también en ofertas de empleo) y la idea de aceptar rangos ("de 12 a 15").

### 4. Tests "HTML guardado + JSON esperado", descubiertos automáticamente
- **Qué hace**: cada sitio tiene en `tests/test_data/<host>/` pares `<nombre>.testhtml` + `<nombre>.json`. Un único generador de tests los convierte en casos.
- **Cómo**: `tests/__init__.py::prepare_test_cases()` recorre las carpetas, y por cada par crea un método de test con `test_func_factory()`. Distingue `MANDATORY_TESTS` (si la clave no está en el JSON, el test **exige que el método lance excepción**: así se documenta que el sitio no ofrece ese campo) y `OPTIONAL_TESTS` (solo se comprueban si están). Comprobaciones cruzadas: que `ingredient_groups` contenga los mismos ingredientes que `ingredients`, y que `instructions` y `instructions_list` coincidan. Solo permite un test "wild" (sitio no registrado) por ejecución.
- **Por qué importa**: es justo lo que queremos en F4: añadir un sitio = añadir YAML + HTML guardado + JSON esperado, sin escribir tests en Python.

### 5. Generador de scraper + datos de test
- **Qué hace**: `generate.py <Clase> <url...>` crea el módulo desde plantilla, lo registra en `__init__.py`, descarga el HTML y deja un JSON esperado con las claves vacías para rellenar.
- **Cómo**: `generate.py::_generate_scraper()` (reescritura por AST de `templates/scraper.py`), `_register_scraper()`, `_generate_tests_and_data()`.
- **Por qué importa**: inspira `scraper init-site --capture <url>`: genera YAML esqueleto, guarda el HTML (respetando robots) y un JSON esperado a partir del primer `dry-run`, que el humano revisa.

### 6. Declarar "este sitio no da este campo"
- **Qué hace**: distingue "no encontrado por error" de "el sitio nunca lo publica" o "es un valor fijo".
- **Cómo**: `_exceptions.py::FieldNotProvidedByWebsiteException` y `StaticValueException` llevan un valor de retorno; `plugins/static_values.py` los convierte en aviso + valor.
- **Por qué importa**: en nuestro motor un campo `required` vacío siempre es error; nos vendría bien `static: "valor"` o `not_provided: true` para que los informes de calidad no den falsos positivos.

### 7. Detección de sitio soportado por host
- **Qué hace**: `scraper_exists_for(url)` y `get_supported_urls()` responden si hay scraper para un dominio (`_utils.py::get_host_name()` quita `www.`).
- **Por qué importa**: podríamos declarar `hosts:` en cada YAML y permitir `scraper run <url>` que elija la configuración sola, con un YAML genérico "solo schema.org" como comodín.

## Qué aplicaríamos en nuestro motor
| # | Propuesta | Módulo afectado | Cambio YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | **Relleno automático desde schema.org**: bloque `schema:` a nivel de `detail`/`list` que mapea campos a rutas por defecto; los campos con `selector` explícito ganan, los vacíos se rellenan del schema (y registran la fuente). | `pipeline/extract.py`, `parse/structured.py` (ver ficha extruct) | `detail: { schema: { type: Product, fill: { nombre: name, precio: "offers.price", sku: sku } }, fields: { precio: { selector: ".precio-oferta", type: money } } }` | M | 1 |
| 2 | Resolución de `@graph`, `mainEntity` y referencias `@id` en el módulo de datos estructurados. | `parse/structured.py` | — (transparente) | S | 1 |
| 3 | Tests por sitio con fixtures: `tests/sites/<site>/<caso>.html` + `<caso>.expected.json`, un único test parametrizado de pytest que los descubre; campos ausentes en el JSON deben salir vacíos. | `tests/test_sites.py` (nuevo), `tests/conftest.py` | — | S | 1 |
| 4 | `scraper init-site --capture <url>`: YAML esqueleto (pre-rellenado con los tipos schema.org detectados), HTML guardado en fixtures y JSON esperado desde un `dry-run`. Descarga una sola vez, con nuestro fetcher cortés. | `cli.py`, `engine.py` | — | M | 2 |
| 5 | Tipo `duration` (ISO 8601 y texto "1 h 30 min", "90 minutos", rangos "de 12 a 15 min") → minutos (int). Implementación propia, sin `isodate` (el patrón ISO es simple). | `pipeline/clean.py`, `config.py::FieldType` | `duracion: { selector: "jsonld:JobPosting.duration", type: duration }` | S | 2 |
| 6 | `static:` y `not_provided: true` por campo para distinguir ausencias legítimas en los informes. | `config.py::FieldSpec`, `pipeline/extract.py` | `moneda: { static: "EUR" }` | S | 3 |
| 7 | `hosts:` en el YAML + `scraper run <url>` que elige config por dominio; YAML genérico `sites/_schema_generico.yaml` como comodín. | `config.py`, `cli.py` | `hosts: [tienda.es, www.tienda.es]` | S | 3 |
| 8 | Perfiles reutilizables para familias de CMS (WooCommerce, PrestaShop, WordPress + Yoast) mediante `extends:`, equivalente a sus mixins. | `config.py` (merge de YAML) | `extends: perfiles/woocommerce.yaml` | M | 3 |

## Qué NO copiaríamos y por qué
- **Un fichero Python por sitio**: nuestro principio es config-driven; el equivalente debe ser YAML (con escape a Python solo en casos extremos).
- **Plugins por monkey-patching de métodos de clase** (`_abstract.py::__init__` reescribe los métodos de la clase la primera vez): potente pero opaco y con estado global; nuestra cadena de fallback declarativa en YAML es más legible.
- **`settings` global vía variable de entorno** (`RECIPE_SCRAPERS_SETTINGS`): preferimos que todo viva en el YAML del sitio.
- **User-Agent con apariencia de navegador** (`_abstract.py::HEADERS` comienza por "Mozilla/5.0… (compatible…)" con el comentario de que algunos sitios cierran el contenido a bots): nuestro principio es un User-Agent identificable y sin evasión.
- **BeautifulSoup + `html.parser`**: lento frente a selectolax.
- **Lógica específica de recetas** (grupos de ingredientes, nutrición, raciones): fuera de nuestro dominio salvo que un cliente lo pida.
- Licencia MIT: permisiva; aun así solo tomamos ideas.
