# joseconstela/webparsy
> JavaScript (Node) · MIT · ⭐ 49 · Último push 2022-12-30 (sin mantenimiento) · https://github.com/joseconstela/webparsy

## Qué es (2-3 líneas)
Herramienta CLI/librería que ejecuta un YAML de **pasos secuenciales** sobre Puppeteer (o `got` para HTTP simple): navegar, rellenar formularios, clicar, hacer scroll, esperar y extraer. El formato imita a los workflows de CI (`version`, `jobs.main.steps`). Proyecto parado desde 2022, útil como referencia de diseño de "acciones de navegador" en YAML.

## Arquitectura en breve
- `index.js`: carga la definición, valida mínimos, lanza Puppeteer con opciones de `jobs.main.browser` y ejecuta `steps` en orden acumulando la salida en un objeto.
- `helpers/definition.js`: `loadFile`/`loadString` con la librería `yaml`; `validate` solo comprueba que existan `jobs`, `jobs.main` y `steps`.
- `helpers/steps.js`: cada paso es `nombre` o `{nombre: params}`; se busca en el registro `helpers/methods/index.js`. Cada método declara si es nativo de Puppeteer (`puppeteer: true`), si procesa HTML (`process`) y cómo formatea su salida (`output`).
- `helpers/methods/*.js`: `goto`, `text`, `property`, `html`, `title`, `url`, `many`, `click`, `form`, `type`, `keyboardPress`, `waitFor`, `waitForNavigation`, `scrollTo`, `scrollToEnd`, `goBack`, `setContent`, `screenshot`, `pdf`.
- `helpers/parser.js`: `cast` por tipo y `transform` (uppercase, lowercase, absoluteUrl).
- Tests: `test/parser.js` (unidad de `cast`/`transform`), `test/auth.js`.

## Técnicas que nos interesan

### 1. Acciones de navegador como lista de pasos en YAML
- **Qué hace**: secuencia declarativa `goto → form/type/click → waitFor → scrollToEnd → extracción`.
- **Cómo**: `helpers/steps.js` (`exec`) despacha por nombre; `waitFor.js` acepta `selector`, `xPath`, `time` o `function`; `scrollToEnd.js` acepta `step`, `sleep`, `max`; `click.js` acepta selector CSS o XPath; `form.js` rellena `fill: [{selector, value}]` y `submit`.
- **Fragmento** (`examples/methods/scrollToEnd.yml`):
  ```yaml
  steps:
    - goto: http://elpais.com
    - scrollToEnd: { step: 300, sleep: 1000, max: 300000 }
  ```
- **Por qué importa**: nuestro modo browser solo tiene `wait_for`. Un bloque `fetch.actions` limitado (wait, click, scroll, fill) cubre "cargar más", cookies de consentimiento y scroll infinito sin escribir Python.

### 2. `many` con `element`: sub-extracción por bloque, anidable
- **Qué hace**: `many` selecciona N elementos y, para cada uno, ejecuta una sub-lista de pasos de extracción (`text`, `property`, `html`...) relativos a ese bloque, devolviendo una lista de objetos. Como `element` usa el mismo despachador, un `many` puede contener otro `many` → **campos anidados** (lista de objetos dentro del item).
- **Cómo**: `helpers/methods/many.js` (`runElement` recorre `params.element` pasando el HTML del bloque a `steps.exec`).
- **Fragmento** (`examples/methods/many.yml`):
  ```yaml
  - many:
      as: github_tools
      selector: a.col-md-6.mb-4
      element:
        - property: { selector: a, property: href, as: url, transform: absoluteUrl }
        - text: { selector: h3.h4, transform: trim, as: name }
  ```
- **Por qué importa**: es exactamente el hueco "sin campos anidados/objetos". Para nosotros: `type: object` / `type: list` con `item_selector` + `fields` recursivos.

### 3. Entradas externas (`flag`, `env`, `file`)
- **Qué hace**: la URL de `goto` o el HTML de `setContent` pueden venir de un *flag* de CLI, de una variable de entorno o de un fichero.
- **Cómo**: `helpers/steps.js` (`getPageHtml`), ejemplo `examples/methods/flags.yml` (`goto: {flag: url}`) y `setContent` con `html | file | env | flag`.
- **Por qué importa**: (a) parametrizar YAML (`--set`); (b) `setContent: {file: ...}` es la base de **probar una config offline contra un HTML guardado**.

### 4. Modo HTTP vs navegador por paso y error claro si no aplica
- `goto: {url, method: got}` descarga sin navegador; los métodos que requieren Puppeteer lanzan "X requires using puppeteer" si se usan en modo HTTP (`click.js`, `scrollToEnd.js`, `waitFor.js`). Nosotros deberíamos detectarlo **al validar** (acciones con `mode: http` = error de config), no en ejecución.

### 5. Tipos de número por convención regional
- `helpers/parser.js`: `fdc` (punto de miles, coma decimal) y `fcd` (coma de miles). Ya lo cubrimos mejor con `money`/`float` autodetectando; confirma que merece la pena un `locale: es|en` explícito para desambiguar "1.234".

### 6. Salida por eventos (`event`, `eventMethod: discard`)
- `many` puede emitir cada elemento como evento y no acumularlo (`examples/methods/many_event.yml`), útil para listados grandes. Nosotros ya persistimos por item; no hace falta.

## Qué aplicaríamos en nuestro motor

| # | Propuesta | Módulo afectado | Cambio en YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | Campos anidados: `type: object` (con `fields`) y `type: list` con `item_selector` + `fields` recursivos; se guardan como JSON en `items.data` y se aplanan al exportar (`precios.0.importe`) o se exportan como hoja aparte | `config.py` (FieldSpec recursivo), `pipeline/extract.py`, `export` | `lineas: {type: list, item_selector: "tr", fields: {...}}` | M | 1 |
| 2 | `fetch.actions` para modo browser: `wait` (selector/ms), `click` (selector, `optional`), `scroll` (`to: bottom`, `times`, `pause_ms`), `fill` (selector, `value: "{vars.q}"`), `click_until_gone` (botón "cargar más", con `max`) | `fetch/browser.py`, `config.py` | ver ejemplo abajo | M | 2 |
| 3 | Validación cruzada: `actions` o `wait_for` con `mode: http` → error de config con mensaje claro | `config.py` (`model_validator`) | — | S | 1 |
| 4 | `scraper test sites/x.yaml --html fichero.html` (equivalente a `setContent: file`) para probar selectores offline | `cli.py`, `engine.py` (fetcher de fichero) | — | S | 1 |
| 5 | `locale: es` a nivel de sitio para desambiguar números/fechas | `pipeline/clean.py` | `locale: es` | S | 3 |

Ejemplo de acciones propuesto:
```yaml
fetch:
  mode: browser
  actions:
    - click: { selector: "#aceptar-cookies", optional: true }
    - scroll: { to: bottom, times: 5, pause_ms: 800 }
    - wait: { selector: "div.card" }
```

## Qué NO copiaríamos y por qué
- **`waitFor: {function: ...}` y `page.evaluate` con JS arbitrario**: ejecución de código desde YAML; difícil de validar y de revisar. Nos quedamos con acciones cerradas.
- **Pasos imperativos como único modelo**: el orden de pasos mezcla navegación y extracción; preferimos extracción declarativa (fields) y acciones solo en la fase fetch.
- **Validación mínima** (`definition.js` solo mira que existan claves) y errores por `process.exit`: nada de eso.
- **Tipado por `cast` laxo** (`Number("1a")` → 1): esconde errores de selector; nosotros devolvemos `None` y lo contamos en "campos vacíos".
- **`form` contra Google** en ejemplos y `--no-sandbox` por defecto: ni scraping de buscadores ni desactivar el sandbox.
- Proyecto abandonado (Puppeteer antiguo); licencia MIT: solo ideas.
