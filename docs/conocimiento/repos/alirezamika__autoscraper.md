# alirezamika/autoscraper
> Python · MIT · ⭐ ~8.0k · Último push 2026-07-29 · https://github.com/alirezamika/autoscraper

## Qué es (2-3 líneas)
Librería pequeña (≈780 líneas en `autoscraper/auto_scraper.py` + `utils.py`) que **aprende reglas de extracción a partir de ejemplos de valores**: le das una URL/HTML y una lista de textos que ves en la página ("iPhone 15", "899 €") y deduce la "ruta" hasta esos nodos. Luego aplica esas reglas a páginas similares y devuelve los valores "exactos" o "similares" (los hermanos equivalentes).

## Arquitectura en breve
- `AutoScraper.build(url|html, wanted_list | wanted_dict, text_fuzz_ratio)` → aprende `stack_list` (lista de reglas).
- `get_result_similar()` / `get_result_exact()` / `get_result()` → aplican reglas.
- `save()` / `load()` → reglas en JSON. `remove_rules()` / `keep_rules()` → poda manual.
- Parser: BeautifulSoup + lxml. HTML normalizado con `unicodedata.normalize('NFKD')` y `html.unescape` (`utils.normalize`).

## Técnicas que nos interesan

### 1. Localizar el nodo que contiene el valor de ejemplo
- **Qué hace:** dado un texto buscado, encuentra los nodos que lo contienen (en texto o en atributos).
- **Cómo** (`_get_children` + `_child_has_text`): recorre todos los nodos **de más profundo a menos** (`reversed(findChildren())`) y un nodo "coincide" si:
  1. su texto completo (`getText().strip()`) coincide con el ejemplo — salvo que el padre tenga exactamente el mismo texto (y no sea la raíz): en ese caso descarta el nodo y acaba quedándose con el **ancestro más alto que aún tiene exactamente ese texto** (p. ej. `<span><b>899 €</b></span>` → `span`);
  2. o su texto *propio* no recursivo coincide (`get_non_rec_text`, marca `is_non_rec_text`);
  3. o el valor de **algún atributo** coincide → registra `wanted_attr` (p. ej. `href`, `src`, `content`, `data-price`);
  4. o para `href`/`src`, la URL absoluta (`urljoin`) coincide → marca `is_full_url`.
  La coincidencia es exacta por defecto, o difusa con `text_fuzz_ratio < 1` (SequenceMatcher), o por regex si el ejemplo es un patrón compilado (`fullmatch`) (`utils.text_match`).
- **Por qué importa:** es justo el primer paso de un `init-site --ejemplo "texto"`: encontrar el nodo y además saber **qué sufijo** usar (`::text` vs `::attr(href)`).

### 2. La "regla" = pila de pasos desde la raíz
- **Cómo** (`_build_stack`): desde el nodo encontrado sube hasta la raíz. Cada nivel se guarda como `(tag, attrs, índice)` donde `attrs` son **solo `class` y `style`** (`_get_valid_attrs`, se rellenan con `""` si faltan) y el índice es la posición del nodo entre los hijos directos del padre **que tienen el mismo tag+class+style**. Se añade `wanted_attr`, `is_full_url`, `is_non_rec_text`, un hash SHA-256 de la regla y `stack_id = "rule_" + hash[:8]`. Reglas duplicadas se eliminan por hash (`unique_stack_list`).
- **Aplicación "similar"** (`_get_result_with_stack`): baja desde la raíz nivel a nivel con `findAll(tag, {class, style}, recursive=False)` **sin usar el índice** salvo en el último nivel → devuelve todos los nodos con la misma forma estructural (p. ej. todos los precios del listado). Con `contain_sibling_leaves` tampoco filtra por índice en la hoja.
- **Aplicación "exact"** (`_get_result_with_stack_index_based`): igual pero en cada nivel toma el hijo con el índice guardado → un solo valor.
- **Tolerancia:** `attr_fuzz_ratio < 1` convierte los valores de `class`/`style` en `FuzzyText`, que BeautifulSoup acepta como filtro con `.search()`; permite que `class="price price--v2"` case con `class="price price--v3"`.
- **Por qué importa:** la idea "el ejemplo me da un nodo; generalizo quitando índices para obtener el conjunto" es la base para proponer **a la vez** `list.item_selector` y los selectores relativos de cada campo.

### 3. Varios ejemplos y alias
- `wanted_dict={"precio": ["899 €", "1.099 €"], "titulo": [...]}`: cada alias genera reglas propias; `group_by_alias=True` agrupa resultados por alias. Dar 2 ejemplos del mismo campo en items distintos ayuda a confirmar que la regla generaliza (ambos deben caer en la misma regla "similar").
- `keep_order` ordena resultados por posición en el documento (atributo `child_index` asignado en recorrido), útil para "coser" campos de un mismo item.

### 4. Limitaciones observadas en el código
- Las reglas son **pila absoluta desde `<html>`**: cualquier wrapper nuevo rompe la regla (más frágil que un CSS relativo).
- Solo `class` y `style` como atributos: ignora `id`, `itemprop`, `data-*`, que suelen ser los más estables.
- Los campos se devuelven como listas separadas por regla; no reconstruye registros (item → campos) salvo por orden.
- Varios ejemplos pueden generar muchas reglas (una por nodo coincidente, incluidos falsos positivos: texto repetido en menú, título en `<title>` y `<h1>`…). El usuario tiene que podar con `keep_rules`.
- BeautifulSoup: lento (Scrapling lo mide ~5x más lento que su `find_similar` en su propio benchmark).

## Qué aplicaríamos en nuestro motor
Diseño de un asistente `scraper init-site <nombre> --url <listado> --ejemplo campo="texto" [--ejemplo ...]`:

| # | Propuesta | Módulos | YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | **Localizar nodo por valor**: recorrer nodos de selectolax de hoja a raíz; coincidir por texto completo, texto propio, atributos (`href/src` también absolutizados) y opcionalmente difuso (normalizando NFKD, espacios y mayúsculas; para precios, comparar solo dígitos). Salida: nodo + sufijo (`::text` o `::attr(x)`). | nuevo `parse/suggest.py` | — | S | 1 |
| 2 | **Deducir `item_selector`**: con ≥2 ejemplos del mismo campo (o 1 ejemplo + detección de hermanos tipo `find_similar`), buscar el **ancestro común más bajo que se repite** como hermano del mismo tag/clase → ese es el item; generar su CSS con clases estables. | `parse/suggest.py` | escribe `list.item_selector` | M | 1 |
| 3 | **Selector relativo por campo**: desde el item hasta el nodo del ejemplo, construir CSS relativo corto (tag + clase estable, `itemprop`, `data-*`), comprobando que en **todos** los items devuelve 0–1 nodos y que en el item del ejemplo devuelve el valor exacto. Escoger el candidato más corto que cumpla. | `parse/suggest.py` | escribe `list.fields.x.selector` | M | 1 |
| 4 | **Validación inmediata**: tras generar el YAML, ejecutar internamente un `dry-run --limit 20` y mostrar el % de vacíos por campo y 3 muestras (reutiliza `RunReport`). Si un campo sale >20% vacío, avisar. | `cli.py`, `engine.py` | — | S | 1 |
| 5 | **Propuesta de `pagination.next_selector`**: buscar `a[rel=next]`, textos "Siguiente/Next/»" o el enlace cuyo `href` difiere del actual solo en un número. | `parse/suggest.py` | escribe `pagination` | S | 2 |
| 6 | Soporte `--ejemplo campo=/regex/` (como autoscraper acepta patrones) para valores variables tipo fechas o precios. | `parse/suggest.py` | — | S | 3 |

Todo esto **genera YAML para revisión humana**; no crea reglas opacas en JSON.

## Qué NO copiaríamos y por qué
- **Reglas como pila absoluta desde la raíz con índices**: frágiles ante cambios mínimos; preferimos CSS relativo al item, legible y editable en el YAML.
- **Formato de reglas propio (JSON opaco con hash)**: nuestro contrato es el YAML; el asistente debe traducir a selectores CSS normales.
- **Solo `class`/`style`**: `style` es ruido que cambia a menudo; nosotros priorizaríamos `itemprop`, `data-*`, clases semánticas.
- **User-Agent de navegador falso** (`request_headers` imita Chrome): contrario a nuestro principio de UA identificable.
- **BeautifulSoup** como dependencia: lento; lo haríamos sobre selectolax.
- Licencia MIT: se podría reutilizar con aviso, pero el algoritmo es simple y lo reimplementaríamos.
