# ShivrajY/MagicBox
> C# (.NET) · Apache-2.0 · ⭐ 23 · Último push 2026-08-02 · https://github.com/ShivrajY/MagicBox

## Qué es (2-3 líneas)
"Scraper universal dirigido por configuración" en .NET: cada sitio es un **adapter** YAML con `schemaVersion: 1`, validado contra un **JSON Schema** publicado en el repo, con entradas parametrizadas (`inputs`), request, modo de render, extracción con **transformaciones encadenadas**, estrategia de paginación y política. Pequeño y reciente, pero con el diseño de formato más cercano a lo que buscamos.

## Arquitectura en breve
- `schemas/adapter-v1.schema.json`: contrato del formato (draft 2020-12, `additionalProperties: false` en todos los niveles).
- `src/MagicBox.Core/AdapterRegistry.cs`: carga YAML → lo convierte a JSON → valida contra el schema → deserializa a `AdapterDefinition` (`AdapterModels.cs`) → validación semántica (`ValidateSemantics`) → registra por `id` (rechaza duplicados).
- `src/MagicBox.Core/TemplateExpander.cs`: sustituye `${input.x}` en URL y query; aplica la estrategia de paginación a la query.
- `src/MagicBox.Core/DocumentExtractor.cs`: `items` (CSS o JSONPath) → `fields` con `source` + `transforms`.
- `src/MagicBox.Core/ScrapeOrchestrator.cs`: bucle de páginas, `render.mode` http/browser/auto.
- `src/MagicBox.Cli/Program.cs`: `adapter validate <fichero|carpeta>`, `adapter list`, `scrape`, `doctor`.
- Tests con fixtures: `tests/fixtures/*.html` + `tests/MagicBox.Tests/BuiltInAdapterFixtureTests.cs`.

## Técnicas que nos interesan

### 1. JSON Schema versionado como contrato del YAML
- **Qué hace**: `schemaVersion: 1` en cada fichero; el loader rechaza versiones no soportadas; el schema cierra todas las claves (`additionalProperties: false`), limita rangos (`timeoutMs` 100–300000, `maxPages` ≤ 10000), usa `enum` para modos y `oneOf` para "CSS o JSONPath".
- **Cómo**: `schemas/adapter-v1.schema.json` + `AdapterRegistry.cs` (validación en dos capas: esquema y semántica).
- **Por qué importa**: es justo el hueco "sin JSON Schema para autocompletado" y "sin validación amigable". Con un schema publicado, VS Code (extensión YAML de Red Hat) autocompleta y subraya errores con una línea `# yaml-language-server: $schema=...`.
- **Debilidad a no repetir**: el mensaje de error es genérico ("failed schema validation") sin ruta ni motivo. Nosotros debemos mostrar `list.fields.precio.type: 'moneda' no es válido; opciones: str, int, ..., money`.

### 2. Campo = `source` + `selector` + cadena `transforms`
- **Qué hace**: el origen del valor es explícito (`text`, `attribute`, `innerHtml`, `outerHtml`, `json`, `constant`, `input`, `currentUrl`, `sourceUrl`) y luego una lista ordenada de transformaciones.
- **Cómo**: `DocumentExtractor.cs`, `switch` por `kind` en minúsculas: `trim`, `normalizeWhitespace`, `htmldecode`, `urldecode`, `urlresolve`, `queryParameter` (saca un parámetro de una URL), `requireAbsoluteUri`, `regexCapture`, `replace`, `lower/upper`, `split`, `join`, `int/decimal/bool/date`, `distinct`, `required`, `default`.
- **Fragmento** (`adapters/builtin/duckduckgo.yaml`):
  ```yaml
  url:
    source: attribute
    attribute: href
    transforms:
      - kind: queryParameter
        argument: uddg
      - kind: urldecode
      - kind: requireAbsoluteUri
  ```
- **Por qué importa**: nos falta encadenar transformaciones; hoy solo tenemos `regex` + `type`. Los `source` `constant`, `currentUrl`, `sourceUrl` resuelven casos frecuentes (URL de la ficha como campo, constante "fuente").

### 3. Paginación por estrategias con nombre
- **Qué hace**: `pagination.strategy` ∈ `none | pageParameter | offsetParameter | nextLink | jsonCursor | clickMore`, con `parameter`, `start`, `step`, `maxPages`, `cursorPath`.
- **Cómo**: `TemplateExpander.BuildUri` calcula `start + (page-1)*step` para page/offset; `jsonCursor` lee el cursor del JSON anterior.
- **Por qué importa**: hoy inferimos la estrategia por qué clave hay (`next_selector` vs `url_template`). Una clave `strategy` explícita hace el YAML autoexplicativo y validable (y añade offset y cursor JSON, que no tenemos).

### 4. Entradas parametrizadas (`inputs`) y plantillas `${input.x}`
- **Qué hace**: el adapter declara parámetros con `required`, `type`, `default`; la URL y la query los interpolan (con escape URL en la ruta).
- **Fragmento**: `request: { url: https://.../html/, query: { q: ${input.query} } }`.
- **Por qué importa**: un mismo YAML reutilizable para varias provincias/categorías: `scraper run sites/x.yaml --set provincia=madrid`.

### 5. `render.mode: auto` con `fallbackOn` explícito
- Idea: probar HTTP y pasar a navegador solo bajo condición declarada y revisable (p. ej. "items vacíos"). Útil para no lanzar Playwright por defecto. En sus adapters se deja `fallbackOn: []`.

### 6. `policy.requiredFields` + reglas semánticas por `kind`
- `kind: search` obliga a emitir `title` y `url` (`ValidateSemantics`). Equivale a "perfiles" de sitio con campos obligatorios mínimos.

### 7. Pruebas de adapter contra fixtures HTML
- **Qué hace**: cada adapter incluido tiene su HTML de ejemplo saneado en `tests/fixtures/<id>.html`; un test parametrizado carga el adapter, extrae y compara con el valor esperado.
- **Guía**: `docs/adapter-authoring.md` ("Start from a fixture": capturar, sanear, validar, test determinista, sin credenciales ni datos personales).
- **Por qué importa**: hoy solo probamos con `dry-run` en vivo. Un modo `scraper test sites/x.yaml` offline es barato y evita regresiones.

### 8. Secretos por nombre lógico
- `auth.steps[].secretName` en lugar de contraseñas en YAML (`SecretStore.cs`). Encaja con nuestro `.env`: `${env:PORTAL_USER}`.

## Qué aplicaríamos en nuestro motor

| # | Propuesta | Módulo afectado | Cambio en YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | Generar `schemas/site-v1.schema.json` desde los modelos Pydantic (`model_json_schema()`) + comando `scraper schema` + cabecera `$schema` en plantillas | `config.py`, `cli.py`, `init-site` | `# yaml-language-server: $schema=../schemas/site.schema.json` | S | 1 |
| 2 | `version: 2` opcional; ausente = v1. `extra="forbid"` en todos los modelos con errores formateados (ruta + valor + opciones válidas + sugerencia por distancia de edición) | `config.py` (`load_site`), `cli.py validate` | `version: 2` | S | 1 |
| 3 | `transform:` lista encadenada por campo (trim, replace, regex, split, join, lower, url_param, urljoin, map, default, call) antes del `type` | `pipeline/extract.py`, nuevo `pipeline/transforms.py` | `transform: [strip, {replace: [" €", ""]}, {regex: "(\\d+)"}]` | M | 1 |
| 4 | `source:` explícito opcional: `const`, `page_url`, `list_url`, `var` | `pipeline/extract.py` | `fuente: {const: "BOE"}` / `url_ficha: {source: page_url}` | S | 1 |
| 5 | `pagination.strategy` explícito (`next_link`, `page_param`, `offset_param`, `json_cursor`); se infiere si falta (compat.) | `config.py`, `parse/pagination.py` | `pagination: {strategy: offset_param, param: start, step: 20}` | S | 2 |
| 6 | `vars` + `--set clave=valor` e interpolación `{vars.x}` / `{env:X}` | `config.py`, `cli.py` | `vars: {provincia: madrid}` | S | 2 |
| 7 | `scraper test`: fixtures `sites/<sitio>/fixtures/*.html` + `expected.yaml`, sin red | `cli.py`, nuevo `scraper/testing.py` | `tests: [{fixture: listado.html, expect: {count: 20, first: {titulo: "..."}}}]` | M | 1 |
| 8 | `fetch.mode: auto` con fallback declarado (`when: empty_items`) | `engine.py` | `fetch: {mode: auto, fallback_when: empty_items}` | M | 3 |

## Qué NO copiaríamos y por qué
- **Adapters de buscadores (Google, Bing, Yahoo...)**: rascar SERPs choca con sus condiciones de uso; fuera de nuestro ámbito.
- **`robots: report`** (solo informa, no obliga): nuestro valor por defecto es respetar robots.txt.
- **`ProxyPool.cs` y `ManualChallengeHandler.cs`** (rotación de proxies y resolución manual de retos en navegador visible): rozan la evasión anti-bot; no entran.
- **Mensajes de validación genéricos**: justo lo contrario de lo que queremos.
- **CamelCase en claves** (`timeoutMs`, `maxPages`): mantenemos snake_case por coherencia con nuestro YAML actual.
- Licencia Apache-2.0: reutilizar ideas sin problema; si algún día copiásemos el schema literal habría que conservar NOTICE. No lo copiamos.
