# D4Vinci/Scrapling
> Python · BSD-3-Clause · ⭐ ~83.9k · Último push 2026-09-26 · https://github.com/D4Vinci/Scrapling

## Qué es (2-3 líneas)
Framework de scraping con un parser propio sobre lxml (API tipo parsel: `css`, `xpath`, `::text`, `get/getall`), fetchers HTTP/navegador, spiders y un servidor MCP. Su rasgo distintivo es el **modo adaptativo**: guarda una "huella" del elemento encontrado por un selector y, si más adelante el selector deja de devolver nada, recorre el árbol entero buscando el nodo más parecido a esa huella. Fuera de alcance aquí: sus fetchers "stealth" (evasión anti-bot), que no nos interesan.

## Arquitectura en breve
- `scrapling/parser.py` — clase `Selector` (envoltorio de `lxml.html.HtmlElement`) y `Selectors` (lista). Contiene `css()`, `xpath()`, `relocate()`, `find_similar()`, `find_by_text()`, `find_by_regex()` y el cálculo de similitud.
- `scrapling/core/storage.py` — `StorageSystemMixin` (interfaz `save`/`retrieve`) y `SQLiteStorageSystem` (implementación por defecto).
- `scrapling/core/utils/_utils.py` — `_StorageTools.element_to_dict()`: construye la huella del elemento.
- `scrapling/core/translator.py` — traducción CSS→XPath (cssselect) con `lru_cache(256)`; añade pseudo-elementos `::text` y `::attr()`.
- `scrapling/core/mixins.py` — `SelectorsGeneration`: genera selectores CSS/XPath a partir de un elemento.
- `scrapling/fetchers/*`, `scrapling/engines/*`, `scrapling/spiders/*` — descarga y crawling (ignorados salvo contexto).

## Técnicas que nos interesan

### 1. Huella del elemento ("fingerprint")
- **Qué hace:** al encontrar un elemento con `auto_save=True`, serializa sus propiedades estructurales para poder reencontrarlo después aunque cambie el selector.
- **Cómo:** `_StorageTools.element_to_dict()` (`scrapling/core/utils/_utils.py`) guarda un dict con:
  - `tag`; `attributes` (todos los atributos no vacíos, con `strip`); `text` (solo el texto *propio* del nodo, no el de los hijos);
  - `path`: tupla con los nombres de etiqueta desde la raíz (`('html','body','div','ul','li')`), sin índices ni clases;
  - `parent_name`, `parent_attribs`, `parent_text`;
  - `siblings`: tupla de etiquetas de los hermanos; `children`: tupla de etiquetas de los hijos (se guarda pero **no** se usa al puntuar).
- **Almacenamiento:** `SQLiteStorageSystem` crea la tabla `storage(id, url, identifier, element_data, UNIQUE(url, identifier))`; `element_data` es JSON (orjson). `url` es el **dominio registrable** (vía la librería `tld`, `_get_base_url`), no la URL completa: la huella es compartida por todo el sitio. `identifier` es el propio selector o un nombre explícito (`identifier="precio"`). Solo se guarda **el primer** elemento del resultado (`elements[0]`). `INSERT OR REPLACE`: cada `auto_save` sobrescribe la huella anterior (la huella "se mueve" con la web). Usa `RLock` + WAL para uso multihilo; la clase de storage va envuelta en `lru_cache(1)` para reutilizar la conexión.
- **Por qué importa:** es un formato mínimo y barato (unos cientos de bytes por campo) que podemos guardar por `site + campo` en nuestra BD para diagnosticar y reparar selectores.

### 2. Puntuación de similitud y re-localización
- **Qué hace:** `Selector.relocate(huella, percentage=40)` (`scrapling/parser.py`) compara la huella contra **todos** los elementos de la página y devuelve los de mayor puntuación si superan el umbral.
- **Algoritmo** (`__calculate_similarity_score`): media aritmética de varias comprobaciones, cada una en [0,1], expresada en %:
  1. `tag` igual → 1/0.
  2. Texto propio (solo si la huella tenía texto) → ratio de `difflib.SequenceMatcher`.
  3. Atributos completos → media de similitud de la secuencia de claves y la de valores (`__calculate_dict_diff`, 50/50).
  4. Por cada uno de `class`, `id`, `href`, `src` presentes en la huella → ratio de SequenceMatcher del valor (así pesan más los atributos identificativos).
  5. `path` (tupla de etiquetas) → SequenceMatcher sobre secuencias.
  6. Si hay padre en ambos: nombre del padre, atributos del padre y texto del padre (cada uno un check).
  7. `siblings` → SequenceMatcher sobre la tupla de etiquetas.
  Resultado = `score / checks * 100`. Los elementos se agrupan por puntuación; se devuelve la lista con la máxima si `>= percentage` (40 por defecto). Si no llega, log de aviso con la mejor puntuación. Con log DEBUG imprime el top-5.
- **Flujo en `xpath()`:** si el selector encuentra elementos → los devuelve (y con `auto_save` refresca la huella). Si no encuentra nada y `adaptive=True` → `retrieve(identifier)` → `relocate()` → si encuentra y `auto_save`, guarda la nueva huella. Nota: el fallback **solo se activa cuando el selector devuelve 0 elementos**; si devuelve un elemento equivocado no hay detección.
- **Coste:** O(nº nodos × comprobaciones de SequenceMatcher). No hay poda (ni por `tag` primero); en páginas de 5–10k nodos son decenas/cientos de ms por campo. Aceptable como fallback puntual, no para cada item.
- **Por qué importa:** es exactamente nuestro riesgo nº1 del PLAN ("cambios de maquetación rompen selectores"). Aunque no reparemos solos, podemos **sugerir** el nuevo selector.

### 3. `find_similar()` — encontrar hermanos equivalentes
- **Qué hace:** dado un elemento (p. ej. una tarjeta de producto), encuentra los demás del mismo tipo.
- **Cómo:** filtra candidatos por misma profundidad y misma cadena `abuelo/padre/tag` (XPath `//g/p/t[count(ancestor::*)=N]`), y luego compara atributos (ignorando `href`/`src`) con SequenceMatcher; umbral 0.2 por defecto. Penaliza atributos extra usando `max(len)` en el denominador (`__are_alike`). La docstring reconoce que está inspirado en AutoScraper.
- **Por qué importa:** es la pieza para deducir `list.item_selector` a partir de un único item de ejemplo en un asistente `init-site`.

### 4. Generación de selectores
- **Qué hace:** `generate_css_selector` / `generate_full_css_selector` / XPath (`scrapling/core/mixins.py`).
- **Cómo:** sube por los ancestros; si encuentra `id` para ahí (`#id > ...`); si no, usa `tag` + `:nth-of-type(n)` cuando hay hermanos del mismo tag. **Descarta clases a propósito** (comentario: hay webs que repiten clases). Resultado robusto para *reencontrar* pero frágil ante inserciones (usa posiciones).
- **Por qué importa:** tras un `relocate` exitoso necesitamos proponer un selector nuevo legible para el YAML; conviene uno mejor que el posicional (ver propuestas).

### 5. API de parser y rendimiento
- API: `Selector(html, url, adaptive=True)`; `page.css('.precio::text', auto_save=True)`; más tarde `page.css('.precio', adaptive=True)`. `identifier` desacopla el nombre lógico del selector: permite cambiar el selector sin perder la huella.
- Rendimiento: lxml con `HTMLParser(recover, remove_comments, compact, huge_tree)`, caché de traducción CSS→XPath y objetos perezosos (`text`, `attrib` se calculan bajo demanda). El README afirma que selectolax es ~99x más lento en su test de "extracción de texto de 5000 elementos anidados"; es un benchmark concreto de ellos (`benchmarks.py`) y probablemente penaliza el `.text(deep=True)` de selectolax. **No es motivo para cambiar de parser**: selectolax es rápido en `css()` puro, que es nuestro caso.

## Qué aplicaríamos en nuestro motor
| # | Propuesta | Módulos | YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | **Huellas de campo**: en cada `run` real, para cada campo y el primer item válido, guardar una huella (tag, attrs, texto propio, path de etiquetas, padre, hermanos) en una tabla nueva `field_fingerprints(site, field, scope[list/detail], data JSON, updated_at, run_id)`. Selectolax da `node.tag`, `node.attributes`, `node.parent`, `node.iter()`; el texto propio = texto de los nodos `-text` hijos directos. | `storage/models.py`, `storage/repo.py`, `pipeline/extract.py` (devolver el nodo además del valor), `engine.py` | — | M | 1 |
| 2 | **Diagnóstico de selector roto con sugerencia**: cuando un campo supera el umbral de vacíos (o `item_selector` devuelve 0), cargar la huella y puntuar todos los nodos de la página (algoritmo tipo media de similitudes, umbral ~40–50%, con poda previa por `tag`). Mostrar en `dry-run`/`run` "posible nuevo selector para `precio`: `span.price-now` (78%)" y **no** aplicarlo automáticamente. Nuevo comando `scraper repair sites/x.yaml` que imprime el diff de YAML sugerido. | nuevo `parse/relocate.py`, `cli.py`, `engine.py` | opcional `fields.x.adaptive: suggest|off` | M | 1 |
| 3 | Aplicar la re-localización en caliente solo si el usuario lo activa (`adaptive: auto`), marcando el valor como "recuperado" en `errors` (tipo `relocated`) para que se revise. | `pipeline/extract.py`, `engine.py` | `adaptive: auto` | S (tras 2) | 3 |
| 4 | Generador de selector "legible": al proponer selector, preferir `tag.clase-estable` (descartar clases con dígitos/hashes tipo `css-1x2y3`), luego `[itemprop]`/`[data-*]`, luego `id`, y solo al final `:nth-of-type`. Validar que el selector propuesto devuelva **exactamente** el nodo en la página actual. | nuevo `parse/suggest.py` (compartido con el asistente de autoscraper) | — | M | 2 |
| 5 | Identificador lógico = nombre del campo del YAML (ya lo tenemos). Así un cambio de selector en el YAML no invalida la huella. | — | — | S | 1 |

## Qué NO copiaríamos y por qué
- **Fetchers stealth / camoufox / bypass de Cloudflare** (`scrapling/fetchers/stealth_*`, `engines/_browsers/_stealth.py`): contrarios a nuestro principio de no evasión anti-bot.
- **Re-localización silenciosa por defecto:** si el nodo "más parecido" es incorrecto, guardamos datos malos sin enterarnos. En nuestro caso preferimos alertar y sugerir.
- **Sobrescribir la huella en cada acierto sin historial**: perdemos la referencia buena si un día el selector acierta en un nodo erróneo. Guardaríamos la huella con `run_id` y solo la refrescaríamos si el run no tiene alertas.
- **Huella por dominio y solo del primer elemento**: para listados preferimos huella por `site + campo + scope`, y opcionalmente de 2–3 items para robustez.
- **Cambio de parser a lxml** por su benchmark: nuestro uso (CSS puntual) no lo justifica; mantenemos selectolax.
- Licencia BSD-3: podríamos reutilizar código con atribución, pero la propuesta es reimplementar el algoritmo (es corto) sobre selectolax.
