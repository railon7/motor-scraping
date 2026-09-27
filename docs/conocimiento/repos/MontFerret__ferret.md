# MontFerret/ferret
> Go · Apache-2.0 · ⭐ 6013 · Último push 2026-09-23 · https://github.com/MontFerret/ferret

## Qué es (2-3 líneas)
Lenguaje declarativo propio (**FQL**, inspirado en AQL de ArangoDB) y runtime embebible en Go para "automatización de datos": consultar páginas (estáticas o vía Chrome/CDP), transformar y devolver JSON. La rama por defecto es **v2 (alpha)**, un compilador a bytecode + VM genérico; los *drivers* HTML/CDP y los ejemplos de scraping viven en la rama `v1` (`examples/*.fql`), que es la que citamos para el uso práctico.

## Arquitectura en breve
- v2 (rama principal): `pkg/parser` (gramática), `pkg/compiler` → `pkg/bytecode` → `pkg/vm`; `pkg/stdlib/*` (strings, arrays, datetime, objects, testing...); `pkg/diagnostics` (errores con posición); `pkg/module` (extensiones con *hooks* de ciclo de vida, ver `docs/maintainers/architecture/modules.md`); `pkg/formatter`; `pkg/debugger`.
- v1 (rama `v1`): funciones HTML `DOCUMENT`, `ELEMENT(S)`, `INNER_TEXT`, `CLICK`, `INPUT`, `WAIT_ELEMENT`, `WAIT_NO_CLASS`, `SCROLL_BOTTOM`, `NAVIGATE`, `ELEMENT_EXISTS`, con drivers `http` y `cdp`.
- Palabras clave de sincronización en v2: `WAITFOR ... TIMEOUT`, `DISPATCH`, `RETRY` (`pkg/compiler/syntax_words.go`).

## Técnicas que nos interesan

### 1. Extracción = consulta con proyección a objeto (anidamiento natural)
- **Qué hace**: `FOR el IN ELEMENTS(doc, sel) RETURN { campo: ..., otro: ... }`; un `RETURN` puede contener otra subconsulta → listas de objetos anidadas sin sintaxis especial.
- **Fragmento** (v1 `examples/static-page.fql`, resumido):
  ```
  FOR el IN ELEMENTS(doc, ".py-4.border-bottom")
      LIMIT 10
      RETURN { name: TRIM(INNER_TEXT(el, ".f3")), url: "https://github.com" + ELEMENT(el,"a").attributes.href }
  ```
- **Por qué importa**: confirma el modelo mental "item = objeto cuyos campos pueden ser listas de objetos" que queremos en YAML (`type: list` + `fields`), y que `LIMIT`/`FILTER` por item son primitivas esperadas.

### 2. Paginación y "cargar más" como bucles condicionales
- **Qué hace**: `FOR i DO WHILE ELEMENT_EXISTS(doc, nextSelector)` con `CLICK` + `WAIT_ELEMENT` por iteración (v1 `examples/pagination_while.fql`); scroll infinito con `SCROLL_BOTTOM` + `WAIT(ms)` hasta que aparece un marcador de fin (v1 `examples/lazy-loading.fql`).
- **Por qué importa**: identifica las condiciones de parada que un YAML debe poder expresar: "mientras exista el selector X", "hasta que aparezca Y", "máximo N". Para nosotros: `pagination: {strategy: click_next, selector, until_missing: true, max_pages}` y `scroll: {until: "selector", max: N}`.

### 3. Esperas con timeout y filtro (`WAITFOR EVENT ... FILTER ... TIMEOUT`)
- v1 `examples/pagination.fql`: esperar un evento de navegación cuya URL cumpla un patrón, con timeout. v2 lo convierte en sintaxis de primera clase (`pkg/compiler/internal/wait_event.go`, `wait_predicate.go`, `wait_recovery.go`).
- **Por qué importa**: toda acción de navegador en nuestro YAML debe llevar `timeout_ms` y condición explícita, y un fallo de espera debe ser un error de página auditado, no un cuelgue.

### 4. Parámetros externos `@nombre`
- `@criteria`, `@pages` en v1 `examples/pagination.fql`: la consulta declara parámetros que se inyectan al ejecutar. Mismo patrón que `vars` + `--set`.

### 5. Diagnósticos estructurados con posición, pista y nota
- **Qué hace**: cada error lleva `Kind`, `Message`, `Hint`, `Note` y `Spans` sobre el fuente, y se renderiza con el fragmento y un caret bajo la zona errónea.
- **Cómo**: `pkg/diagnostics/diagnostic.go` (struct `Diagnostic`), `render.go` (`SpanRenderer`), `formatter.go`.
- **Por qué importa**: es el estándar al que aspirar para `scraper validate`: "sites/x.yaml:23:12 · `list.fields.precio.type`: valor 'moneda' no válido. Pista: ¿quisiste decir 'money'?". Con `ruamel.yaml` (o marcas de línea de PyYAML) podemos mapear la ruta Pydantic a línea/columna.

### 6. Aserciones dentro del propio script (librería `T::`)
- v1 `examples/pagination.fql` usa `T::NOT::EMPTY(prefix, "...")` y `T::NOT::NONE(...)` para fallar pronto con mensaje propio; en v2 está en `pkg/stdlib/testing/` (`assertion.go`, `comparison.go`) y hay casos de prueba `.fql` en `test/integration/vm/testdata/testing/`.
- **Por qué importa**: equivalente a `expect:` en nuestro YAML: "el listado debe tener ≥ 10 items", "el campo precio debe estar lleno en ≥ 90 %". Convierte el `dry-run` en un test con veredicto.

### 7. Extensibilidad por módulos con namespaces y hooks
- `docs/maintainers/architecture/modules.md`: módulos con nombre estable registran funciones (namespaced) y hooks antes/después de compilar y de ejecutar, con orden definido (before en orden de registro, after en orden inverso). Modelo sano para nuestros plugins de transformaciones: registro por nombre + espacio de nombres (`mi_proyecto.normaliza_ref`).

### 8. Capacidades controladas por el anfitrión
- El runtime decide qué funciones y recursos expone a cada programa. Para nosotros: los hooks Python solo se cargan de `sites/<sitio>/` o de paquetes declarados, nunca `eval` de cadenas del YAML.

## Qué aplicaríamos en nuestro motor

| # | Propuesta | Módulo afectado | Cambio en YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | Errores de validación con fichero:línea:columna, ruta, mensaje, pista ("¿quisiste decir...?") | `config.py` (`load_site`), `cli.py validate` | — | M | 1 |
| 2 | Bloque `expect` (aserciones de calidad) evaluado en `dry-run`/`test`: `min_items`, `fill_rate`, `regex` | `engine.py` (`RunReport`), `cli.py` | `expect: {min_items: 10, fill_rate: {precio: 0.9}}` | S | 1 |
| 3 | Paginación `click_next` / `load_more` con `until_missing`, `max_pages`, `timeout_ms` (solo browser) | `fetch/browser.py`, `parse/pagination.py` | `pagination: {strategy: load_more, selector: "button.mas", max_pages: 20}` | M | 2 |
| 4 | Registro de transformaciones/plugins con namespace y carga explícita | `pipeline/transforms.py`, `plugins.py` | `plugins: [sites.mi_sitio.hooks]` | S | 2 |
| 5 | `limit` y `skip_if` por nivel (equivalentes a `LIMIT`/`FILTER`) | `engine.py` | `list: {limit: 100}` | S | 3 |

## Qué NO copiaríamos y por qué
- **Un lenguaje de programación propio**: FQL es potente pero exige aprender una sintaxis nueva, compilador y VM; nuestro público edita YAML. Tomamos sus primitivas (bucle condicional, proyección, espera con timeout, aserciones), no el lenguaje.
- **Lógica ad hoc para adivinar variantes de la página** (v1 `examples/pagination.fql` detecta prefijos CSS de Amazon): frágil y dirigida a un sitio concreto; además, scraping de Amazon choca con sus condiciones de uso.
- **Opciones de driver para bloquear recursos** (`ignore.resources` de imágenes en v1 `examples/crawler.fql`): legítimo por rendimiento, pero no es prioritario y no aporta al formato.
- **Arquitectura v2 (bytecode, VM, debugger)**: fuera de escala para nosotros.
- Licencia Apache-2.0: reutilizamos ideas; no copiamos código ni gramática.
