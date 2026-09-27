# Quantika14/BOE-scraping
> Python · Sin licencia declarada (todos los derechos reservados por defecto) · ⭐ 8 · Último push 2021-08-13 · https://github.com/Quantika14/BOE-scraping

## Qué es (2-3 líneas)
Dos scripts sueltos (`BOE_extractor.py` y `BORME_extractor.py`, ~90 líneas cada uno) que recorren **por fuerza bruta** los identificadores de documentos del BOE (`BOE-A-<año>-<n>`) y del BORME (`BORME-C-<año>-<n>`), descargan el XML de cada uno y guardan título y texto en MongoDB y/o en un CSV por año. Interés principal para nosotros: **qué formatos ofrece el BOE** y qué no hacer.

## Arquitectura en breve
- Bucle `while` con año inicial y contador `i` global; URL construida como `https://www.boe.es/diario_boe/xml.php?id=BOE-A-{año}-{i}` (o `diario_borme/xml.php?id=BORME-C-...`).
- `requests.get` con cabecera `Accept: application/xml`, sin User-Agent propio, **sin retardo** y sin respeto de robots.txt.
- Parseo con BeautifulSoup en modo `xml`: primer `<titulo>` y concatenación de todos los `<texto>`.
- Fin de año por heurística: si se acumulan 1.000 errores, pasa al año siguiente.
- Guardado: `db.DG_BOE.update(... upsert=True)` por URL en MongoDB y/o línea `url|titulo|texto|año` en `BOE-A-<año>.csv` (sin escapar el separador).

## Técnicas que nos interesan

### 1. El BOE publica XML por documento (pero robots.txt lo excluye)
- El script demuestra que cada disposición/anuncio tiene XML estructurado en `/diario_boe/xml.php?id=<identificador>` (metadatos + texto). **Sin embargo, `https://www.boe.es/robots.txt` contiene `Disallow: /diario_boe/xml.php?` y `Disallow: /diario_borme/xml.php?`** (comprobado 2026-09-27). Nuestro motor con `respect_robots: true` lo bloquearía, y es lo correcto.
- La versión HTML del mismo documento, `/diario_boe/txt.php?id=<identificador>`, **sí está permitida** (solo se excluyen las variantes `lang=ca|va|gl|eu|en|fr`). Los PDF en `/boe/dias/...` también; `/datos/pdfs/` está excluido.

### 2. API oficial de datos abiertos (lo que el script no usa y deberíamos usar)
Verificado en `https://www.boe.es/datosabiertos/api/api.php` y con una petición real (2026-09-27):
- **Sumario diario del BOE**: `GET https://www.boe.es/datosabiertos/api/boe/sumario/{aaaammdd}`, respuesta `application/xml` o `application/json` según la cabecera `Accept`. Hay XSD descargable.
- **Sumario diario del BORME**: `GET /datosabiertos/api/borme/sumario/{aaaammdd}`.
- **Legislación consolidada**: `GET /datosabiertos/api/legislacion-consolidada` (búsqueda con `from`/`to`…), `/id/{id}`, `/id/{id}/metadatos`, `/metadata-eli`, `/analisis`, `/texto`, `/texto/indice`, `/texto/bloque/{id_bloque}`.
- **Tablas auxiliares**: `/datosabiertos/api/datos-auxiliares/{materias|ambitos|estados-consolidacion|departamentos|rangos|relaciones-anteriores|relaciones-posteriores}`.
- Estructura JSON del sumario: `status{code,text}` + `data.sumario{metadatos{publicacion, fecha_publicacion}, diario[]{numero, sumario_diario, seccion[]}}`. Cada `seccion` (`1`, `2A`, `2B`, `3`, `4`, `5A` Contratación del Sector Público, `5B` Otros anuncios oficiales…) contiene `departamento[]`; en secciones 1-3 hay un nivel `epigrafe[]` intermedio y en 5A/5B los `item` cuelgan directamente del departamento. Cada `item` trae `identificador` (p. ej. `BOE-B-2026-30881`), `titulo`, `url_pdf{texto, szBytes, pagina_inicial, pagina_final}`, `url_html` (txt.php) y `url_xml` (xml.php).
- **Cuidado**: como es JSON convertido de XML, `item`/`departamento` pueden venir como **objeto o lista** según haya uno o varios; hay que normalizar a lista.
- Condiciones de reutilización publicadas en la propia web de datos abiertos (aceptarlas y citarlas en `docs/LEGAL.md`).

### 3. Portal de Subastas (`subastas.boe.es`)
- **`https://subastas.boe.es/robots.txt` = `User-agent: *` / `Disallow: /`** (comprobado 2026-09-27). Es decir, el portal de subastas no admite rastreo automatizado de ningún tipo, y la API de datos abiertos **no** ofrece un endpoint de subastas.
- Consecuencia directa para nuestro PLAN §7: **el piloto "subastas del BOE" tal como está planteado (scrapear el Portal de Subastas) no es viable dentro de nuestra política** (respeto de robots, sin evasión). Alternativas legítimas: (a) anuncios de la sección V del BOE vía API de sumarios (licitaciones públicas en 5A y otros anuncios oficiales en 5B, donde aparecen algunos anuncios de subasta de organismos); (b) pedir a la AEBOE acceso/reutilización formal de los datos del portal; (c) otro piloto.

### 4. Anti-patrones del script (para no repetirlos)
- Enumerar identificadores a ciegas (hasta 320.000 por año) en lugar de leer el sumario del día: miles de peticiones fallidas y carga innecesaria.
- Sin retardo, sin UA identificable y contra un `Disallow` explícito.
- Detección de fin de año por "1.000 errores seguidos".
- `except Exception` genérico que oculta si el error es 404, 429 o de parseo.
- CSV con separador `|` sin escapar (el texto legal contiene `|`), y concatenación del texto con `" | "` que pierde la estructura de párrafos.

## Qué aplicaríamos en nuestro motor
| # | Propuesta | Módulo afectado | Cambio en YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | **Fuentes JSON/XML declarativas**: `fetch.format: json|xml|html`; para JSON, `item_selector` y `fields` con rutas tipo JSONPath/"punteado" (`data.sumario.diario[*].seccion[*].departamento[*].item[*]`), normalizando objeto→lista. Para XML, selectores XPath (el PLAN ya proponía prefijo `xpath:`). | `parse/` (nuevo `parse/jsonpath.py`), `config.py`, `engine.py` (elegir parser según formato), `fetch/http.py` (cabecera Accept) | `fetch: {format: json, headers: {Accept: application/json}}` + selectores de ruta | M | 1 |
| 2 | **URLs de arranque generadas por fecha**: `start_urls` con plantilla `{fecha:%Y%m%d}` y rango (`desde`, `hasta`, o `ultimos_dias: 7`), saltando días sin publicación (404 = normal). | `config.py`, `engine.py` | `start_dates: {template: "/datosabiertos/api/boe/sumario/{date:%Y%m%d}", last_days: 7}` | S-M | 1 |
| 3 | **Filtro por rama del árbol** (solo sección `5B`, o departamentos concretos, o títulos que contengan "subasta") antes de pedir el detalle HTML. Reutiliza la propuesta de filtros pre-detalle (JobFunnel). | `engine.py`, `config.py` | `list.filters: [{field: seccion, in: ["5B"]}, {field: titulo, regex: "(?i)subasta"}]` | S | 1 |
| 4 | **Detalle por `url_html` (txt.php)** con selectores CSS del documento, nunca `url_xml` (excluido por robots). Clave natural = `identificador`. | `sites/boe-anuncios.yaml` (nuevo) | `key: [identificador]`, `list.detail_url: url_html` | S | 1 |
| 5 | **Actualizar PLAN §7**: sustituir "subastas del BOE" por "anuncios de la sección V del BOE vía API de datos abiertos" o pedir autorización a la AEBOE; anotar en `docs/LEGAL.md` el `Disallow: /` de subastas.boe.es y las condiciones de reutilización. | `PLAN.md`, `docs/LEGAL.md` | — | S | 1 |

## Recomendación para el piloto BOE: HTML vs API/XML
- **Listado: API JSON de sumarios** (`/datosabiertos/api/boe/sumario/{fecha}`), no HTML. Es oficial, estable, versionada con XSD, una petición por día y trae identificador, título, departamento, sección y enlaces. Encaja con nuestro upsert por clave (`identificador`).
- **Detalle: HTML `txt.php`** (permitido) con selectores CSS; **no** `xml.php` (prohibido en robots.txt aunque la API lo enlace). Si el cliente necesita el PDF, descargarlo por el fetcher educado.
- **Subastas del Portal (`subastas.boe.es`)**: descartado mientras su robots.txt sea `Disallow: /` y no haya autorización expresa.
- Esto requiere en el motor: formato JSON (propuesta 1) y start_urls por fecha (propuesta 2) antes de F5.

## Qué NO copiaríamos y por qué
- Todo el enfoque: fuerza bruta de IDs, sin cortesía, contra robots.txt, sin gestión de errores, CSV mal escapado, MongoDB con API obsoleta (`update`).
- Código: el repo no declara licencia (por defecto no se puede reutilizar); tampoco hay nada que merezca reutilizarse.
