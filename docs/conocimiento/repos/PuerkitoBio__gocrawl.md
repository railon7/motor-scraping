# PuerkitoBio/gocrawl
> Go · BSD-3-Clause · ⭐ 2.051 · Último push 2021-05-19 (sin actividad desde entonces) · https://github.com/PuerkitoBio/gocrawl

## Qué es (2-3 líneas)
Crawler "cortés" en Go, pequeño (~1.400 líneas) y centrado en respetar robots.txt y el `Crawl-delay`. Todo el
comportamiento se personaliza con una interfaz `Extender` de hooks. Proyecto inactivo, pero su diseño de
"un trabajador por host" y su gestión del retraso siguen siendo una referencia clara de buenas prácticas.

## Arquitectura en breve
- `crawler.go`: `Crawler` recibe semillas, normaliza URLs, las filtra y las reparte a un **worker por host**
  (`enqueueUrls`, `launchWorker`, `collectUrls`). Lleva el mapa `visited` por URL normalizada.
- `worker.go`: bucle del worker (`run`), descarga (`fetchURL`), robots (`requestRobotsTxt`,
  `isAllowedPerRobotsPolicies`), cálculo del retraso (`setCrawlDelay`) y visita (`visitURL`).
- `ext.go`: interfaz `Extender` (hooks) y `DefaultExtender`; cliente HTTP que no sigue redirecciones.
- `options.go`: opciones (`CrawlDelay`, `RobotUserAgent`, `SameHostOnly`, `HeadBeforeGet`, `MaxVisits`,
  `WorkerIdleTTL`, `URLNormalizationFlags`).
- `errors.go`: `CrawlError` con tipos (`CrawlErrorKind`).
- `urlcontext.go`: `URLContext` (URL, URL normalizada, URL de origen, `State` arbitrario que viaja con la URL).

## Técnicas que nos interesan

### 1. Un worker por host y robots.txt como primera petición
- **Qué hace**: cada host tiene su propia cola y su propio worker, que procesa en serie. Al crear el worker de un host
  nuevo, la primera URL encolada es su robots.txt.
- **Cómo**: `Crawler.enqueueUrls()` (`crawler.go`) lanza el worker si no existe y apila primero el contexto de robots
  (`getRobotsURLCtx`); `worker.run()` detecta `IsRobotsURL()` y llama a `requestRobotsTxt()`; el resto de URLs pasan
  por `isAllowedPerRobotsPolicies()`. Las no permitidas disparan el hook `Disallowed`. Si el worker queda ocioso más de
  `WorkerIdleTTL`, se destruye.
- **Por qué importa**: garantiza por construcción que nunca hay dos peticiones simultáneas al mismo host y que robots
  se evalúa antes que cualquier URL, sin carreras. Es la forma más simple de "cortesía estricta".

### 2. Crawl-delay de robots y retraso calculable
- **Qué hace**: el retraso entre peticiones a un host es el de robots.txt si existe, si no el de opciones; y se puede
  recalcular tras cada petición con información de la anterior.
- **Cómo**: `worker.setCrawlDelay()` llama al hook `ComputeDelay(host, DelayInfo, FetchInfo)` con
  `DelayInfo{OptsDelay, RobotsDelay, LastDelay}` y `FetchInfo{Duration, StatusCode, ...}` de la última descarga.
  `DefaultExtender.ComputeDelay` devuelve `RobotsDelay` si es >0. En `fetchURL()` el retraso empieza a contar **después**
  de recibir la respuesta (`w.wait = time.After(...)`).
- **Por qué importa**: permite retraso **adaptativo cortés**: si el servidor tarda mucho en responder o devuelve 5xx,
  esperar más. Nuestro `DomainLimiter` ignora `Crawl-delay` y la latencia del servidor.
- **Matiz**: gocrawl prioriza `Crawl-delay` incluso si es menor que el configurado; nosotros tomaríamos el máximo.

### 3. Redirecciones como nuevas URLs
- **Qué hace**: no sigue redirecciones de forma transparente; encola el destino como URL nueva (con la misma URL de
  origen), de modo que pasa por filtros, robots, dominio permitido y deduplicación.
- **Cómo**: `HttpClient.CheckRedirect` en `ext.go` devuelve `ErrEnqueueRedirect` (salvo para robots.txt, que sí sigue
  hasta 10); `worker.fetchURL()` captura ese error y encola `ctx.cloneForRedirect(...)`.
- **Por qué importa**: con `follow_redirects=True` (nuestro `HttpFetcher`) una redirección a otro dominio o a una ruta
  prohibida por robots se descarga sin comprobar. Tampoco detectamos que dos URLs de detalle redirigen a la misma.

### 4. Normalización de URLs para deduplicar
- **Qué hace**: normaliza todas las URLs (purell, modo agresivo por defecto) y deduplica por la forma normalizada.
- **Cómo**: `options.go` (`URLNormalizationFlags`, `DefaultNormalizationFlags = purell.FlagsAllGreedy`);
  `urlcontext.go` guarda `url` y `normalizedURL`; `enqueueUrls()` consulta `visited[normalizedURL]`.
- **Por qué importa**: mismo hueco que en crawlee: nuestra deduplicación de detalles es por URL literal.

### 5. HEAD antes de GET
- **Qué hace**: opcionalmente hace HEAD y decide con el hook `RequestGet` si merece la pena el GET (por defecto, solo
  si 2xx).
- **Cómo**: `Options.HeadBeforeGet`, bucle en `worker.fetchURL()`, `DefaultExtender.RequestGet` en `ext.go`.
- **Por qué importa**: útil para descartar binarios o 404 sin descargar el cuerpo; coste: doble petición. Preferimos
  abortar tras cabeceras en streaming (ver ficha de colly).

### 6. Tipos de error y hooks de ciclo de vida
- **Qué hace**: cada error lleva un tipo (`Fetch`, `ParseRobots`, `HttpStatusCode`, `ReadBody`, `ParseBody`,
  `ParseURL`, `ProcessLinks`, `ParseRedirectURL`) y se notifica al hook `Error`. Hooks: `Start`, `End`, `Filter`,
  `Enqueued`, `Fetch`, `Visit`, `Visited`, `Disallowed`, `ComputeDelay`, `RequestRobots`/`FetchedRobots`.
- **Cómo**: `errors.go` (`CrawlErrorKind`, `lookupCek`), interfaz `Extender` en `ext.go`.
- **Por qué importa**: `RequestRobots` permite devolver un robots.txt cacheado (sin petición); `Disallowed` da
  visibilidad a lo que se saltó por robots, algo que hoy solo aparece como excepción genérica en nuestro log.

### 7. Estado que viaja con la URL
- **Qué hace**: cada URL encolada puede llevar un valor arbitrario (`State`) que se recupera al visitarla.
- **Cómo**: `URLContext.State` en `urlcontext.go`; se conserva en redirecciones.
- **Por qué importa**: en nuestra cola persistente, cada petición de detalle debería llevar los campos ya extraídos del
  listado (`data` parcial) para poder reanudar sin volver a descargar el listado.

## Qué aplicaríamos en nuestro motor

| # | Propuesta | Módulos afectados | Cambio YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | **Crawl-delay efectivo = max(`delay_seconds`, Crawl-delay de robots)**, contado desde el fin de la respuesta anterior; guardarlo en el informe del run. | `fetch/robots.py`, `fetch/http.py`, `fetch/browser.py` | Ninguno | S | 1 |
| 2 | **Retraso adaptativo cortés**: si la latencia media del dominio crece o aparecen 5xx/429, multiplicar el delay (p. ej. ×2, con techo) y relajarlo poco a poco tras respuestas sanas. | `fetch/http.py` (`DomainLimiter`) | `politeness.adaptive: true`, `politeness.max_delay_seconds: 30` | M | 2 |
| 3 | **Redirecciones bajo control**: seguirlas manualmente (máx. 5) comprobando dominio permitido y robots en cada salto; registrar URL final en `pages`; deduplicar detalles por URL final. | `fetch/http.py`, `engine.py` | `crawl.follow_offsite_redirects: false` | S | 2 |
| 4 | **Motivos de salto visibles**: contador por motivo (`robots`, `offsite`, `duplicate`, `filtered`, `max_pages`) en `RunReport` y `status`. | `engine.py`, `cli.py` | Ninguno | S | 2 |
| 5 | **Estado de listado adjunto al detalle en la cola** (los `fields` del listado viajan con la petición de detalle). Condición necesaria para reanudar (ver cola persistente de crawlee/exoskeleton). | `engine.py`, `storage/models.py` | Ninguno | S (dentro de la cola) | 1 |

## Qué NO copiaríamos y por qué
- **User-Agent por defecto que imita a Firefox y `RobotUserAgent` "Googlebot"** (`options.go`): hacerse pasar por un
  navegador o por Googlebot es engañoso y va contra nuestro principio de identificación; usamos un único UA honesto
  tanto para pedir como para evaluar robots.
- **Worker/goroutine por host** tal cual: en asyncio lo equivalente es un lock + reloj por dominio (ya lo tenemos en
  `DomainLimiter`); no hace falta replicar la arquitectura de canales.
- **Normalización "greedy"** de purell por defecto: algunas transformaciones (quitar `www`, ordenar/eliminar
  parámetros, quitar barra final) pueden fusionar URLs distintas; preferimos una normalización conservadora y
  configurable.
- **HEAD sistemático antes de GET**: duplica peticiones al servidor; menos cortés que abortar tras cabeceras.
- Proyecto inactivo desde 2021 y licencia BSD-3-Clause (permisiva, exige conservar aviso de copyright si se copiara
  código). Aquí solo tomamos ideas.
