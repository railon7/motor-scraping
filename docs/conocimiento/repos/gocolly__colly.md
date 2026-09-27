# gocolly/colly
> Go · Apache-2.0 · ⭐ 25.533 · Último push 2026-09-16 · https://github.com/gocolly/colly

## Qué es (2-3 líneas)
Framework de scraping para Go, muy popular por su API de *callbacks* (`OnRequest`, `OnHTML`, `OnError`...). Un
`Collector` descarga, parsea con goquery (CSS) o xpath y reparte los nodos a las funciones registradas. Pequeño
(~1.700 líneas el núcleo) y fácil de leer: buena fuente de patrones simples y probados.

## Arquitectura en breve
- `colly.go`: `Collector` (configuración, callbacks, `scrape()` → `requestCheck()` → `fetch()`), robots, filtros de
  URL/dominio, profundidad, límite de peticiones, deduplicación de visitadas.
- `http_backend.go`: `httpBackend` con `LimitRule` (límite por dominio) y caché de respuestas en disco (`Cache()`).
- `queue/queue.go`: cola de peticiones con `Storage` enchufable y N hilos consumidores.
- `storage/storage.go`: interfaz para URLs visitadas y cookies (en memoria por defecto; hay backends externos).
- `request.go`, `response.go`, `context.go`: petición serializable (`Marshal`), `Retry()`, contexto compartido
  petición→respuesta.
- `unmarshal.go`: rellenar structs a partir de etiquetas `selector:"..."` / `attr:"..."`.
- `debug/`: depuradores (log y web) que reciben eventos del ciclo de vida.

## Técnicas que nos interesan

### 1. LimitRule: límite por patrón de dominio
- **Qué hace**: reglas por dominio (regex o glob) con `Parallelism` (peticiones simultáneas), `Delay` y `RandomDelay`.
- **Cómo**: `http_backend.go`, struct `LimitRule`; `Init()` crea un canal con capacidad `Parallelism` que actúa de
  semáforo; `Do()` busca la primera regla que casa (`GetMatchingRule`), ocupa un hueco y, **al terminar** la petición,
  duerme `Delay + aleatorio(RandomDelay)` antes de liberarlo. Es decir, el delay se cuenta desde el final de la
  respuesta anterior, no desde su inicio. `Init()` es idempotente para poder compartir la regla entre collectors.
- **Por qué importa**: nuestro `DomainLimiter` aplica un único delay a todos los dominios del sitio y un semáforo
  global. Hay sitios cuyo detalle vive en otro host (CDN, subdominio de fichas, API) que merecen reglas distintas.
  El pequeño jitter tiene sentido de cortesía (evitar ráfagas sincronizadas), no de evasión.

### 2. Caché de respuestas en disco
- **Qué hace**: guarda cada respuesta GET en disco y la reutiliza en ejecuciones posteriores.
- **Cómo**: `httpBackend.Cache()` en `http_backend.go`: clave = SHA-1 de la URL; ruta en dos niveles
  (`<cacheDir>/<2 primeros hex>/<hash>`) para no llenar un directorio; serializa la respuesta (estado, cabeceras,
  cuerpo); **no cachea respuestas ≥500** ni sirve de caché una ≥500; se salta si el método no es GET o si la petición
  lleva `Cache-Control: no-cache`; caducidad por antigüedad del fichero (`CacheExpiration`, opción en `colly.go`);
  escritura atómica (fichero temporal `~` + `rename`).
- **Por qué importa**: es nuestro hueco "no hay caché HTTP". Con caché, iterar selectores en `dry-run` no vuelve a
  pegar al servidor (más cortés y más rápido) y se pueden reproducir fallos.

### 3. Comprobaciones previas a la petición (`requestCheck`)
- **Qué hace**: en un único punto decide si una URL se visita: profundidad máxima, `MaxRequests`, filtros de URL
  permitidos/prohibidos (regex), dominios permitidos, robots.txt y "ya visitada".
- **Cómo**: `Collector.requestCheck()` en `colly.go`; "visitada" usa un hash de URL + cuerpo (`requestHash`) guardado en
  `storage.Storage.Visited/IsVisited`. Errores tipados: `ErrMaxDepth`, `ErrMaxRequests`, `ErrRobotsTxtBlocked`,
  `ErrForbiddenDomain`, `AlreadyVisitedError`.
- **Por qué importa**: ordena la lógica que en nuestro motor está repartida (robots en el fetcher, `seen_urls` local
  en `_crawl_listing`, `_details` en memoria). Filtros `allow/deny` por regex serían útiles en el YAML.
- **Nota**: por defecto colly **ignora** robots.txt (`c.IgnoreRobotsTxt = true` en `Init()`); nosotros mantenemos lo
  contrario como principio.

### 4. Robots.txt por host con grupo de agente
- **Qué hace**: descarga y cachea robots por host, busca el grupo que corresponde a nuestro User-Agent y prueba ruta +
  query.
- **Cómo**: `Collector.checkRobots()` usando la librería `temoto/robotstxt` (`FindGroup`, `Test`).
- **Por qué importa**: confirma nuestro enfoque; lo que añade es probar también la query string, que `urllib.robotparser`
  gestiona de forma limitada.

### 5. Callbacks del ciclo de vida y aborto temprano
- **Qué hace**: `OnRequest` (antes de enviar; puede abortar), `OnResponseHeaders` (tras cabeceras, antes del cuerpo;
  puede abortar la descarga), `OnResponse`, `OnHTML(selector)`, `OnXML(xpath)`, `OnError`, `OnScraped` (al final).
- **Cómo**: `colly.go` (`handleOnRequest`, `handleOnResponseHeaders`, `handleOnHTML`, `handleOnError`,
  `handleOnScraped`); `http_backend.go::Do()` cierra el cuerpo sin leerlo si el callback de cabeceras aborta;
  `MaxBodySize` limita bytes leídos.
- **Por qué importa**: abortar tras cabeceras permite no descargar PDFs o ficheros enormes enlazados por error como
  "detalle". Un sistema de eventos también facilita métricas y alertas sin tocar el motor.

### 6. `<base href>` y charset
- **Qué hace**: al parsear HTML, si hay `<base href>` lo usa para resolver enlaces relativos; detecta codificación en
  respuestas no UTF-8.
- **Cómo**: `handleOnHTML()` en `colly.go` fija `resp.Request.baseURL`; `response.go::fixCharset()`.
- **Por qué importa**: nuestro `extract_one(..., base_url=list_url)` resuelve contra la URL de la página y fallaría en
  webs con `<base href>` distinto (típico en portales públicos antiguos). Charset ya lo cubrimos.

### 7. Cola con almacenamiento enchufable
- **Qué hace**: cola FIFO de peticiones serializadas con N consumidores; el almacenamiento es una interfaz de 4
  métodos (`Init`, `AddRequest`, `GetRequest`, `QueueSize`).
- **Cómo**: `queue/queue.go` (`Queue`, `InMemoryQueueStorage`, `Run()` con `independentRunner`); la petición se
  serializa con `Request.Marshal()` (`request.go`), incluido su contexto.
- **Por qué importa**: la interfaz mínima es un buen modelo para nuestra cola en BD. Sin embargo no guarda estado
  "en curso" ni reintentos: si el proceso muere con una petición sacada de la cola, se pierde. Crawlee resuelve eso
  mejor (ver su ficha).

### 8. Extracción declarativa a struct
- **Qué hace**: `selector:"..."` y `attr:"..."` en campos de struct; soporta slices y structs anidados.
- **Cómo**: `unmarshal.go` (`UnmarshalHTML`, `unmarshalSlice`, `unmarshalStruct`).
- **Por qué importa**: valida nuestro diseño de `fields` en YAML; lo que nos falta y colly tiene es el **anidado**
  (sub-listas con varios campos por elemento, p. ej. lotes dentro de una subasta).

## Qué aplicaríamos en nuestro motor

| # | Propuesta | Módulos afectados | Cambio YAML | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| 1 | **Caché HTTP en disco** con clave SHA-1 de la URL normalizada, dos niveles de carpeta, escritura atómica, sin cachear ≥500 (ni 429), caducidad configurable. `dry-run` la usa por defecto; `run` solo si se pide. Rellenar `FetchResult.from_cache` (ya existe el campo). | nuevo `fetch/cache.py`, `fetch/http.py`, `fetch/browser.py`, `cli.py` | `cache: {enabled: true, ttl_hours: 24}` + flag `--cache/--no-cache` | M | 1 |
| 2 | **Reglas de límite por dominio** (glob) con `delay`, `parallelism` y `jitter`; el delay se cuenta desde el fin de la respuesta anterior. Si no hay reglas, se usan los valores globales actuales. | `fetch/http.py` (`DomainLimiter`), `config.py` | `politeness.domains: [{match: "*.ejemplo.es", delay_seconds: 3, max_concurrency: 1}]` | S | 2 |
| 3 | **Punto único de admisión de URLs** (`should_visit`): dominio permitido, filtros `allow/deny` por regex, `max_pages`/`max_requests`, robots y ya-visitada; cada rechazo con motivo contado en el informe. | `engine.py`, `config.py` | `crawl: {allow: [...], deny: [...], max_requests: 500}` | S | 2 |
| 4 | **Respetar `<base href>`** al resolver `detail_url` y `next_selector`. | `parse/selectors.py`, `parse/pagination.py` | Ninguno | S | 1 |
| 5 | **Aborto por cabeceras**: si `Content-Type` no es HTML (o el tamaño supera un máximo), no descargar el cuerpo y registrar error `skipped`. Usar streaming de httpx. | `fetch/http.py` | `fetch.max_body_mb: 10` | S | 2 |
| 6 | **Campos anidados** (`type: group` con `item_selector` y `fields` propios) para sub-listas estructuradas. | `config.py`, `pipeline/extract.py` | `fields.lotes: {type: group, selector: ".lote", fields: {...}}` | M | 3 |
| 7 | **Eventos internos** (`on_request`, `on_response`, `on_error`, `on_item`) como lista de *listeners* Python opcionales: base para alertas y métricas sin tocar el bucle. | `engine.py` | Ninguno | S | 3 |

## Qué NO copiaríamos y por qué
- **`extensions/random_user_agent.go`** y **`proxy/proxy.go`** (rotación round-robin de proxies): sirven para camuflarse
  y repartir carga entre IPs; va contra nuestro principio de User-Agent identificable y no evasión.
- **Ignorar robots por defecto** (`IgnoreRobotsTxt = true` en `Init()`): nosotros lo respetamos por defecto.
- **Callbacks libres en código** como forma principal de definir un sitio: nuestro modelo es YAML declarativo; los
  eventos serían un punto de extensión, no la interfaz principal.
- **Caché basada en `gob`** tal cual: usaríamos un formato legible (cabeceras JSON + cuerpo) para poder inspeccionarla.
- **Cola sin estado "en curso"** (`queue/queue.go`): insuficiente para reanudar; preferimos el modelo con lease.
- Licencia Apache-2.0: patrones descritos, sin copia de código.
